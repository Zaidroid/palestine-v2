"""Off-device, encrypted, verified backup of everything tier 1 cannot re-derive.

    .venv/bin/python -m ops.backup --dry-run     # do everything except upload
    .venv/bin/python -m ops.backup               # nightly path
    .venv/bin/python -m ops.backup --status      # what the last run did

WHY THIS EXISTS AT ALL
Every retention rule in this project — never delete, never overwrite, keep the
raw payload — defends against *logic* destroying data. None of it defends
against *hardware*. This host has exactly one physical disk (a single NVMe,
`/` on LVM over nvme0n1p3). Until this ran, 395 MB and ~531k observations,
including 92,844 checkpoint observations reconstructed from v1 and the bronze
archive that makes them re-derivable, lived in exactly one place.

So "backup" here means OFF THIS MACHINE. A copy in /opt/backups is a
convenience for fast restore, not a backup; v1's nightly job writes to
/opt/backups/palestine on the same disk and would die with it. (v1's script
already supports BACKUP_REMOTE via rclone — it was built and left switched off.)

WHY THE MANIFEST COUNTS ROWS INSIDE AN EXPORTED SNAPSHOT
Six timers write to this database, two of them every 2-5 minutes. Counting rows
before or after pg_dump would produce a manifest that disagrees with the dump by
whatever landed in between, and then the restore test could never assert
equality — only a fuzzy "close enough", which is exactly the kind of check that
passes while quietly rotting. Instead one connection opens a REPEATABLE READ
transaction, exports its snapshot, counts every table inside it, and hands the
snapshot id to pg_dump so both see an identical database. The restore test can
then assert EXACT equality, and a mismatch is a real defect rather than noise.

WHY IT IS ENCRYPTED
The payload includes the Telegram session (account-takeover material) and .env
(DB password, api_hash, FIRMS key), and the subject matter is military
checkpoints in an occupied territory. The destination is consumer cloud storage.
Symmetric AES256 via gpg, passphrase in a keyfile outside the repo.

    THE KEYFILE IS ON THE DISK THIS PROTECTS AGAINST LOSING.
    If it is not also somewhere else, the off-site copy is unrecoverable noise
    and this whole file is theatre. See --show-key-instructions.

WHAT IS IN A BACKUP SET
    db.dump.gpg        pg_dump custom format, compressed (schema + data)
    globals.sql.gpg    roles/grants — a fresh cluster needs these first
    bronze.tar.zst.gpg raw source payloads; makes silver/gold reproducible
    secrets.tar.gpg    .env + Telethon session + poller cursor
    manifest.json      row counts, sizes, sha256 of each file (NOT encrypted,
                       so a restore can be planned before anything is decrypted)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.db import connect, _env  # noqa: E402

CONTAINER = "palestine-v2-db"
STAGING = Path(os.environ.get("BACKUP_DIR", "/opt/backups/palestine-v2"))
KEYFILE = Path(os.environ.get(
    "BACKUP_KEYFILE", str(Path.home() / ".config/palestine-v2/backup.key")))
STATUS_FILE = ROOT / "ops" / "backup-status.json"

# Local copies are for fast restore, not for survival — keep few.
LOCAL_KEEP = 7
# Remote is the actual backup. 30 dailies plus every first-of-month forever;
# at ~80 MB/set that is ~2.4 GB rolling against a 15 GiB quota.
REMOTE_KEEP = 30

# P0.4 tripwires, measured against the previous successful run.
MIN_DUMP_FRACTION = 0.50   # a dump half the size of yesterday's is not credible
MIN_ROW_FRACTION = 0.95    # tables are append-mostly; a real drop is a defect


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _remotes() -> list[str]:
    """rclone destinations, comma-separated, e.g. 'gdrive:pv2,b2:pv2'.

    Two destinations is not belt-and-braces fussiness: one provider losing an
    account, or a sync bug propagating a corrupt set, takes out every copy that
    lives behind it. Independence is the point, exactly as it is for sources.

    A run succeeds if at least one destination took the set. A destination that
    failed is recorded and warned about rather than silently tolerated — the
    second copy going quietly missing for a month is the failure this guards
    against.
    """
    raw = (os.environ.get("BACKUP_REMOTE") or _env().get("BACKUP_REMOTE", ""))
    return [r.strip() for r in raw.split(",") if r.strip()]


def _remote() -> str:
    """First configured destination — used by restore_test's --from-remote."""
    rs = _remotes()
    return rs[0] if rs else ""


# ── the database ────────────────────────────────────────────────────────────

COUNT_SQL = """
SELECT c.relname
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY 1
"""


def dump_database(out_dir: Path) -> dict[str, int]:
    """pg_dump + per-table row counts that describe THE SAME snapshot.

    The connection must stay open for the whole pg_dump: an exported snapshot
    only exists while its exporting transaction does.
    """
    counts: dict[str, int] = {}
    with connect() as conn:
        with conn.cursor() as cur:
            # Must be the first statement in the transaction.
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cur.execute("SELECT pg_export_snapshot()")
            snapshot = cur.fetchone()[0]

            cur.execute(COUNT_SQL)
            tables = [r[0] for r in cur.fetchall()]
            for t in tables:
                cur.execute(f'SELECT count(*) FROM public."{t}"')
                counts[t] = cur.fetchone()[0]

            # Local socket inside the container is `trust`, so no password ever
            # reaches an argv or an environment variable.
            dump = out_dir / "db.dump"
            with dump.open("wb") as fh:
                subprocess.run(
                    ["docker", "exec", "-u", "postgres", CONTAINER,
                     "pg_dump", "-U", _env().get("PGUSER", "palestine"),
                     "-d", _env().get("PGDATABASE", "palestine_v2"),
                     "--format=custom", "--compress=6",
                     f"--snapshot={snapshot}"],
                    check=True, stdout=fh, stderr=subprocess.PIPE)
        conn.rollback()

    globals_sql = out_dir / "globals.sql"
    with globals_sql.open("wb") as fh:
        subprocess.run(
            ["docker", "exec", "-u", "postgres", CONTAINER,
             "pg_dumpall", "-U", _env().get("PGUSER", "palestine"),
             "--globals-only", "--no-role-passwords"],
            check=True, stdout=fh, stderr=subprocess.PIPE)
    return counts


# ── the files ───────────────────────────────────────────────────────────────

BRONZE_FULL_DAY = 1          # a full set on the 1st; increments in between


LAST_FULL_MARKER = STAGING / "last-full.json"     # outside the pruned 20* dirs (F273)
MIN_REMOTE_SETS = 5
EVIDENCE = ROOT / "data" / "evidence"


def _count_objects(src: Path, newer_than: float | None) -> int:
    n = 0
    for f in src.rglob("*"):
        if f.is_file() and (newer_than is None or f.stat().st_mtime > newer_than):
            n += 1
    return n


def archive_bronze(out_dir: Path) -> str:
    """Raw source payloads. Silver and gold are re-derivable from these.

    INCREMENTAL since 2026-08-07. Bronze was 572 MB and tarred whole every
    night against a 15 GiB remote with REMOTE_KEEP=30. Vaulting v1's snapshot
    archive as as_of evidence roughly triples it, and 30 × 2 GB does not fit.

    Bronze is content-addressed and append-only — an object never changes once
    written — so "everything newer than the last full set" is a complete
    description of the delta. A full set on the 1st of each month bounds how
    many increments a restore must replay; the manifest records which kind this
    is, and ops/restore_test.py reads that rather than guessing.
    """
    src = ROOT / "data" / "bronze"
    if not src.exists():
        return "absent"
    ref = _last_full_bronze()
    full = ref is None or _now().day == BRONZE_FULL_DAY
    # The delta is cut from the moment the LAST tar started (F273): objects
    # written during tar+encrypt used to land in no set, and the reference was
    # the gpg blob's mtime read from local staging that prune_local trims.
    global _BRONZE_FROM, _BRONZE_OBJECTS
    _BRONZE_FROM = _now().timestamp()
    cmd = ["tar", "-C", str(ROOT / "data"),
           "--use-compress-program=zstd -19 -T0",
           "-cf", str(out_dir / "bronze.tar.zst")]
    if not full:
        cmd += [f"--newer-mtime=@{int(ref)}"]
    cmd.append("bronze")
    _run(cmd)
    _BRONZE_OBJECTS = _count_objects(src, None if full else ref)
    return "full" if full else "incremental"


_BRONZE_FROM: float | None = None
_BRONZE_OBJECTS: int | None = None


def archive_evidence(out_dir: Path) -> str:
    """The as_of vault's indexes and manifest (data/evidence): ops/evidence.py
    said they were in the backup set and they were not (audit F276)."""
    if not EVIDENCE.exists():
        return "absent"
    _run(["tar", "-C", str(ROOT / "data"), "--use-compress-program=zstd -19 -T0",
          "-cf", str(out_dir / "evidence.tar.zst"), "evidence"])
    return "present"


def _last_full_bronze() -> float | None:
    """mtime of the most recent FULL bronze set, read from the manifests —
    which are deliberately unencrypted, so this needs no marker file of its
    own and cannot disagree with what the set actually contains."""
    try:
        marker = json.loads(LAST_FULL_MARKER.read_text())
        if marker.get("bronze_from"):
            return float(marker["bronze_from"])
    except (OSError, ValueError):
        pass
    best = None
    for mf in sorted(STAGING.glob("20*/manifest.json")) if STAGING.exists() else []:
        try:
            if json.loads(mf.read_text()).get("bronze_kind") != "full":
                continue
        except (ValueError, OSError):
            continue
        blob = mf.parent / "bronze.tar.zst.gpg"
        if blob.exists():
            best = max(best or 0.0, blob.stat().st_mtime)
    return best


def archive_secrets(out_dir: Path) -> None:
    """.env, the Telethon session, and the poller cursor.

    The session is a live SQLite database with an open journal, so it is copied
    with `.backup` rather than `cp` — a byte copy of a mid-write SQLite file
    restores as corruption.

    A restored session must NEVER be run while the poller is running. Two
    Telethon clients sharing one auth key can invalidate the account, and this
    account took real effort to get working.
    """
    with tempfile.TemporaryDirectory() as td:
        stage = Path(td) / "secrets"
        stage.mkdir()
        for name in (".env",):
            if (ROOT / name).exists():
                shutil.copy2(ROOT / name, stage / name)
        # The partner-key store and OAuth state (audit F276): a restore
        # without them is an API every partner is locked out of.
        keys = ROOT / ".keys"
        if keys.exists():
            shutil.copytree(keys, stage / ".keys",
                            ignore=shutil.ignore_patterns("*.bak*"))
        sess_dir = ROOT / "data" / "session"
        if sess_dir.exists():
            for f in sess_dir.iterdir():
                if f.suffix == ".session":
                    _run(["sqlite3", str(f), f".backup '{stage / f.name}'"])
                elif f.suffix == ".json":
                    shutil.copy2(f, stage / f.name)
        _run(["tar", "-C", str(stage.parent), "-cf",
              str(out_dir / "secrets.tar"), "secrets"])


def encrypt(path: Path) -> Path:
    """Symmetric AES256. Inputs are already compressed, so gpg does not."""
    if not KEYFILE.exists():
        raise SystemExit(f"FATAL: keyfile missing: {KEYFILE}")
    out = path.with_suffix(path.suffix + ".gpg")
    _run(["gpg", "--batch", "--yes", "--symmetric", "--cipher-algo", "AES256",
          "--compress-algo", "none", "--passphrase-file", str(KEYFILE),
          "--output", str(out), str(path)])
    path.unlink()
    return out


# ── verification and alarms ─────────────────────────────────────────────────

def previous_manifest() -> dict | None:
    sets = sorted(p for p in STAGING.glob("20*") if (p / "manifest.json").exists())
    if not sets:
        return None
    return json.loads((sets[-1] / "manifest.json").read_text())


def sanity(manifest: dict, prev: dict | None) -> list[str]:
    """P0.4 — a backup that ran but produced less than it should is a failure.

    A silently truncated dump is worse than a missing one: the missing one is
    obviously broken, and this one looks like a healthy green checkmark.
    """
    problems: list[str] = []
    if manifest["db"]["dump_bytes"] < 1_000_000:
        problems.append(f"dump is only {manifest['db']['dump_bytes']} bytes")
    if not prev:
        return problems

    pb, cb = prev["db"]["dump_bytes"], manifest["db"]["dump_bytes"]
    if pb and cb < pb * MIN_DUMP_FRACTION:
        problems.append(f"dump shrank {pb} -> {cb} bytes "
                        f"(<{MIN_DUMP_FRACTION:.0%} of previous)")

    for table, prev_n in prev["db"]["rows"].items():
        now_n = manifest["db"]["rows"].get(table)
        if now_n is None:
            problems.append(f"table {table} disappeared (had {prev_n} rows)")
        elif prev_n > 0 and now_n < prev_n * MIN_ROW_FRACTION:
            problems.append(f"{table}: {prev_n} -> {now_n} rows "
                            f"(<{MIN_ROW_FRACTION:.0%} of previous)")
    return problems


# ── the remote ──────────────────────────────────────────────────────────────

def upload(set_dir: Path, remote: str) -> None:
    """Copy, then verify the bytes actually landed.

    `rclone check` compares checksums against the remote. Without it this
    reports success on a copy that half-failed.
    """
    dest = f"{remote}/{set_dir.name}"
    _run(["rclone", "copy", "--checksum", str(set_dir), dest])
    _run(["rclone", "check", "--one-way", "--checksum", str(set_dir), dest])


def prune_local() -> list[str]:
    sets = sorted(p for p in STAGING.glob("20*") if p.is_dir())
    removed = []
    for p in sets[:-LOCAL_KEEP] if len(sets) > LOCAL_KEEP else []:
        shutil.rmtree(p)
        removed.append(p.name)
    return removed


def prune_remote(remote: str) -> list[str]:
    """Keep the last REMOTE_KEEP sets, plus every first-of-month forever.

    Monthlies cost ~1 GB/year against a 15 GiB quota and are the only defence
    against a corruption that is not noticed within 30 days.
    """
    out = _run(["rclone", "lsf", "--dirs-only", remote]).stdout.decode()
    sets = sorted(d.strip("/") for d in out.splitlines() if d.strip())
    # ONE set per calendar month (its first), not every set cut on a 1st —
    # nine hand-runs on 08-01 were pinned forever — and never below
    # MIN_REMOTE_SETS (audit F274).
    first_of_month: dict[str, str] = {}
    for s_ in sets:
        first_of_month.setdefault(s_[:7], s_)
    keep = set(sets[-REMOTE_KEEP:]) | set(first_of_month.values())
    if len(keep & set(sets)) < MIN_REMOTE_SETS:
        keep |= set(sets[-MIN_REMOTE_SETS:])
    removed = []
    for s in sets:
        if s not in keep:
            _run(["rclone", "purge", f"{remote}/{s}"])
            removed.append(s)
    return removed


# ── driver ──────────────────────────────────────────────────────────────────

def run(dry_run: bool = False, accept_shrink: str | None = None) -> dict:
    started = _now()
    STAGING.mkdir(parents=True, exist_ok=True)
    name = started.strftime("%Y-%m-%dT%H-%M-%SZ")
    set_dir = STAGING / f".{name}.partial"
    if set_dir.exists():
        shutil.rmtree(set_dir)
    set_dir.mkdir(parents=True)

    status: dict = {"ok": False, "started_at": started.isoformat(), "set": name}
    try:
        rows = dump_database(set_dir)
        dump_bytes = (set_dir / "db.dump").stat().st_size
        bronze_kind = archive_bronze(set_dir)
        evidence_kind = archive_evidence(set_dir)
        archive_secrets(set_dir)

        files = {}
        for f in sorted(set_dir.iterdir()):
            enc = encrypt(f)
            files[enc.name] = {"bytes": enc.stat().st_size, "sha256": _sha256(enc)}

        manifest = {
            "set": name,
            "created_at": started.isoformat(),
            "host": os.uname().nodename,
            "db": {"rows": rows, "dump_bytes": dump_bytes,
                   "total_rows": sum(rows.values())},
            "files": files,
            "bronze_kind": bronze_kind,   # full | incremental | absent
            "bronze_from": (datetime.fromtimestamp(_BRONZE_FROM, tz=timezone.utc).isoformat()
                            if _BRONZE_FROM else None),
            "bronze_objects": _BRONZE_OBJECTS,
            "evidence": evidence_kind,    # present | absent
            "encryption": "gpg symmetric AES256",
            "keyfile_sha256_prefix": _sha256(KEYFILE)[:16],
        }
        problems = sanity(manifest, previous_manifest())

        # --accept-shrink: a deliberate, ONE-RUN, audited override for the
        # row-fraction tripwire — and only that tripwire. Migration 038
        # legitimately deleted 7,330 wrong classifications and the v1.6
        # rebuild rewrote the ledger; the guard then wedged every future
        # backup, because a failed run never becomes the comparison baseline.
        # The reason is recorded in the manifest, so a restore five years from
        # now can tell an audited cleanup from an unnoticed catastrophe. The
        # other tripwires (tiny dump, dump halved, table DISAPPEARED) stay
        # armed even under the flag — no cleanup explains those.
        if accept_shrink:
            waived = [p for p in problems if "rows (<" in p]
            problems = [p for p in problems if "rows (<" not in p]
            if waived:
                manifest["accepted_shrink"] = {"reason": accept_shrink,
                                               "waived": waived}
                status["accepted_shrink"] = accept_shrink

        manifest["sanity"] = problems or ["ok"]
        (set_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

        if problems:
            raise RuntimeError("; ".join(problems))

        # Only now does the set become real — a partial dir is never uploaded
        # and never counts as the previous run.
        final = STAGING / name
        set_dir.rename(final)
        set_dir = final
        if bronze_kind == "full" and _BRONZE_FROM:
            LAST_FULL_MARKER.write_text(json.dumps({"set": name, "bronze_from": _BRONZE_FROM}))

        remotes = _remotes()
        uploaded, failures = [], {}
        if remotes and not dry_run:
            for remote in remotes:
                try:
                    # Prune BEFORE the upload it must make room for (F274):
                    # the off-host copy died on quota with the pruning queued
                    # behind the upload that could not happen.
                    prune_remote(remote)
                    upload(set_dir, remote)
                    uploaded.append(f"{remote}/{name}")
                except Exception as exc:                           # noqa: BLE001
                    detail = (exc.stderr.decode()[:200]
                              if isinstance(exc, subprocess.CalledProcessError)
                              and exc.stderr else str(exc))
                    failures[remote] = detail
            if not uploaded:
                raise RuntimeError(
                    "every destination failed: " +
                    "; ".join(f"{k}: {v}" for k, v in failures.items()))
        elif not remotes:
            status["warning"] = "BACKUP_REMOTE not set — LOCAL ONLY, not a backup"

        status["remotes"] = uploaded
        if failures:
            status["remote_failures"] = failures
            status["warning"] = (f"{len(failures)} of {len(remotes)} destinations "
                                 f"failed — the second copy is not there")
        # Single-destination risk was raised and ACCEPTED by Zaid on 2026-08-01
        # (no NAS on the network, every Tailscale Linux box intermittent, and a
        # destination that is often offline produces alarms people learn to
        # ignore). Recorded in the status file so it stays visible, but not
        # warned about on every run — a warning that fires nightly and is always
        # expected trains you to skim past the one that matters.
        if len(remotes) < 2 and not dry_run:
            status["single_destination_risk"] = "accepted 2026-08-01"

        status.update({
            "ok": True,
            "total_rows": manifest["db"]["total_rows"],
            "dump_bytes": dump_bytes,
            "set_bytes": sum(f["bytes"] for f in files.values()),
            "finished_at": _now().isoformat(),
            "duration_s": round((_now() - started).total_seconds(), 1),
        })
    except Exception as exc:                                       # noqa: BLE001
        detail = exc.stderr.decode()[:400] if isinstance(
            exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
        status["error"] = f"{type(exc).__name__}: {detail}"
        status["finished_at"] = _now().isoformat()
        if set_dir.exists() and set_dir.name.startswith("."):
            shutil.rmtree(set_dir, ignore_errors=True)
    finally:
        try:
            status["pruned_local"] = prune_local()       # always, even after a failure (F274)
        except Exception as exc:                                       # noqa: BLE001
            status["prune_local_error"] = str(exc)[:200]
        STATUS_FILE.write_text(json.dumps(status, indent=2))
    return status


KEY_INSTRUCTIONS = f"""
The backup passphrase lives at:
    {KEYFILE}

It is on the disk these backups exist to survive losing. Copy it into your
password manager now — without it the off-site copies are unrecoverable noise:

    cat {KEYFILE}

Nothing else needs to change. The key is not printed by any script, is not in
the repo, and is not in .env.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="build and verify a set locally, but do not upload")
    ap.add_argument("--status", action="store_true", help="show the last result")
    ap.add_argument("--show-key-instructions", action="store_true")
    ap.add_argument("--accept-shrink", metavar="REASON",
                    help="accept row-count decreases FOR THIS RUN ONLY, recording "
                         "REASON in the manifest. For audited cleanups (e.g. a "
                         "migration deleting derived rows); never routine.")
    a = ap.parse_args()

    if a.show_key_instructions:
        print(KEY_INSTRUCTIONS)
        return 0
    if a.status:
        print(STATUS_FILE.read_text() if STATUS_FILE.exists() else "never run")
        return 0

    s = run(a.dry_run, accept_shrink=a.accept_shrink)
    if s["ok"]:
        mb = s["set_bytes"] / 1e6
        print(f"backup ok · {s['set']} · {mb:.1f} MB · "
              f"{s['total_rows']:,} rows · {s['duration_s']}s")
        for r in s.get("remotes", []):
            print(f"  uploaded and checksum-verified -> {r}")
        for r, why in (s.get("remote_failures") or {}).items():
            print(f"  FAILED -> {r}: {why}", file=sys.stderr)
        if s.get("warning"):
            print(f"  WARNING: {s['warning']}")
        if s.get("pruned_local"):
            print(f"  pruned local={s['pruned_local']}")
        return 0
    print(f"BACKUP FAILED: {s['error']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
