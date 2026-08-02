"""Prove the backup restores. An untested backup is a belief, not a backup.

    .venv/bin/python -m ops.restore_test            # latest local set
    .venv/bin/python -m ops.restore_test --set 2026-07-31T15-17-26Z
    .venv/bin/python -m ops.restore_test --from-remote   # pull it back down first

WHAT THIS ACTUALLY CHECKS
Not "did a file get written" — that is what a broken backup also looks like.
It decrypts the set, verifies each file against the sha256 the manifest recorded,
restores the dump into a scratch database in the live cluster, and asserts the
restored row counts EXACTLY equal the manifest's. Exact equality is only
meaningful because ops/backup.py counts rows inside the same exported snapshot
pg_dump used; without that this could only assert "roughly", which is a check
that passes forever while slowly becoming false.

THE TIMESCALEDB TRAP, AS MEASURED RATHER THAN ASSUMED
This database has three hypertables (claim, state_observation, observation)
whose data lives in 10 chunk tables under _timescaledb_internal. The restore
must be bracketed by:

    SELECT timescaledb_pre_restore();   -- suspend catalog management
    pg_restore ...
    SELECT timescaledb_post_restore();

Both paths were run against a real set to find out what the bracket actually
buys, because the folklore reason ("the hypertables come back hollow") is NOT
what happens on 2.29 — and a test built on a wrong mechanism checks the wrong
thing. Measured:

    with the bracket:     0 pg_restore errors
    without the bracket:  8 errors — 7x "ONLY option not supported on
                          hypertable operations", 1x "table claim is not a
                          hypertable"

The rows all arrive either way and the hypertables DO re-register either way.
What is lost without the bracket is 8 schema objects — constraints and indexes
on the hypertables — while pg_restore exits 0 and every row count matches.

That is the whole reason this file checks the schema and not just the rows: the
failure it exists to catch is invisible to a row count. `--no-bracket` runs the
broken path deliberately, so the test can be shown to fail on demand rather than
merely believed to work.

WHY IT RESTORES INTO THE LIVE CLUSTER
Same PostgreSQL 16.14, same TimescaleDB 2.29.0, same PostGIS 3.6.4. A restore
proven against a different build proves less. It is a separate database, dropped
at the end, and it never touches palestine_v2.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops.backup import (CONTAINER, KEYFILE, STAGING, _remote, _run,  # noqa: E402
                        _sha256)
from resolve.db import _env  # noqa: E402

SCRATCH = "palestine_v2_restoretest"
HYPERTABLES = {"claim", "state_observation", "observation"}
# PostGIS ships spatial_ref_sys populated by CREATE EXTENSION and also dumps its
# contents, so the restore re-inserts rows that already exist. Expected, benign,
# and not a reason to fail the test.
EXTENSION_OWNED = {"spatial_ref_sys"}


def _psql(db: str, sql: str, quiet: bool = False) -> str:
    cp = subprocess.run(
        ["docker", "exec", "-u", "postgres", CONTAINER, "psql", "-v",
         "ON_ERROR_STOP=1", "-U", _env().get("PGUSER", "palestine"),
         "-d", db, "-tAc", sql],
        capture_output=True)
    if cp.returncode != 0 and not quiet:
        raise RuntimeError(f"psql failed: {cp.stderr.decode()[:300]}")
    return cp.stdout.decode().strip()


def latest_set() -> Path:
    sets = sorted(p for p in STAGING.glob("20*") if (p / "manifest.json").exists())
    if not sets:
        raise SystemExit("no local backup set found — run ops.backup first")
    return sets[-1]


def fetch_from_remote(name: str | None) -> Path:
    """Pull a set back from the remote — the only test that proves the OFF-SITE
    copy is restorable, rather than the local staging copy."""
    remote = _remote()
    if not remote:
        raise SystemExit("BACKUP_REMOTE not set")
    if not name:
        out = _run(["rclone", "lsf", "--dirs-only", remote]).stdout.decode()
        name = sorted(d.strip("/") for d in out.splitlines() if d.strip())[-1]
    dest = STAGING / f".remote-{name}"
    dest.mkdir(parents=True, exist_ok=True)
    _run(["rclone", "copy", "--checksum", f"{remote}/{name}", str(dest)])
    return dest


def verify_checksums(set_dir: Path, manifest: dict) -> list[str]:
    bad = []
    for name, meta in manifest["files"].items():
        f = set_dir / name
        if not f.exists():
            bad.append(f"{name}: missing")
        elif _sha256(f) != meta["sha256"]:
            bad.append(f"{name}: sha256 mismatch")
    return bad


def restore(set_dir: Path, work: Path, bracket: bool = True) -> int:
    """Restore into the scratch DB. Returns the pg_restore error count."""
    enc = set_dir / "db.dump.gpg"
    dump = work / "db.dump"
    _run(["gpg", "--batch", "--yes", "--quiet", "--decrypt",
          "--passphrase-file", str(KEYFILE), "--output", str(dump), str(enc)])

    _psql("postgres", f'DROP DATABASE IF EXISTS {SCRATCH}', quiet=True)
    _psql("postgres", f'CREATE DATABASE {SCRATCH}')
    # Extension first, at the cluster's own version, then suspend its catalog
    # management for the duration of the restore.
    _psql(SCRATCH, "CREATE EXTENSION IF NOT EXISTS timescaledb")
    if bracket:
        _psql(SCRATCH, "SELECT timescaledb_pre_restore()")

    _run(["docker", "cp", str(dump), f"{CONTAINER}:/tmp/restore.dump"])
    try:
        # Not --exit-on-error: pg_restore should complete so the assertions
        # below can describe the whole damage, not just the first item.
        cp = subprocess.run(
            ["docker", "exec", "-u", "postgres", CONTAINER, "pg_restore",
             "-U", _env().get("PGUSER", "palestine"), "-d", SCRATCH,
             "--no-owner", "--no-privileges", "/tmp/restore.dump"],
            capture_output=True)
        if bracket:
            _psql(SCRATCH, "SELECT timescaledb_post_restore()")
        return cp.stderr.decode().count("error:")
    finally:
        subprocess.run(["docker", "exec", CONTAINER, "rm", "-f",
                        "/tmp/restore.dump"], capture_output=True)


SCHEMA_SQL = """
SELECT coalesce(string_agg(x, E'\\n' ORDER BY x), '') FROM (
  SELECT 'idx:' || n.nspname || '.' || c.relname AS x
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE c.relkind = 'i' AND n.nspname IN ('public', '_timescaledb_internal')
  UNION ALL
  SELECT 'con:' || n.nspname || '.' || t.relname || '.' || con.conname
    FROM pg_constraint con
    JOIN pg_class t ON t.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
   WHERE n.nspname IN ('public', '_timescaledb_internal')
) s
"""


def check_schema() -> list[str]:
    """Compare indexes and constraints against the live database.

    This is the check that catches the missing-bracket failure. Every row count
    matches and every hypertable registers; what silently vanishes is 8
    constraints and indexes, and nothing else here would notice.
    """
    live = set(_psql(_env().get("PGDATABASE", "palestine_v2"),
                     SCHEMA_SQL).splitlines())
    got = set(_psql(SCRATCH, SCHEMA_SQL).splitlines())
    missing = sorted(live - got)
    problems = [f"{len(missing)} schema objects missing after restore"] if missing else []
    problems += [f"  missing {m}" for m in missing[:10]]
    if len(missing) > 10:
        problems.append(f"  ... and {len(missing) - 10} more")
    return problems


def compare(manifest: dict) -> tuple[list[str], int, int]:
    # Count every restored public table the same way backup.py counted them.
    listing = _psql(SCRATCH, """
        SELECT string_agg(c.relname, ',' ORDER BY c.relname)
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'""")
    restored: dict[str, int] = {}
    for t in [x for x in listing.split(",") if x]:
        restored[t] = int(_psql(SCRATCH, f'SELECT count(*) FROM public."{t}"'))

    problems, matched = [], 0
    for table, expected in manifest["db"]["rows"].items():
        got = restored.get(table)
        if got is None:
            problems.append(f"{table}: MISSING after restore (expected {expected:,})")
        elif got != expected and table not in EXTENSION_OWNED:
            problems.append(f"{table}: expected {expected:,}, restored {got:,}")
        else:
            matched += 1
    return problems, matched, sum(restored.values())


def check_hypertables() -> list[str]:
    """Rows can arrive while hypertables silently do not. Assert the structure."""
    out = _psql(SCRATCH, """
        SELECT string_agg(hypertable_name || ':' || num_chunks, ',' ORDER BY 1)
        FROM timescaledb_information.hypertables""")
    found = dict(p.split(":") for p in out.split(",") if ":" in p)
    live = _psql(_env().get("PGDATABASE", "palestine_v2"), """
        SELECT string_agg(hypertable_name || ':' || num_chunks, ',' ORDER BY 1)
        FROM timescaledb_information.hypertables""")
    expect = dict(p.split(":") for p in live.split(",") if ":" in p)

    problems = []
    for name in HYPERTABLES:
        if name not in found:
            problems.append(f"{name}: NOT a hypertable after restore "
                            f"(pre/post_restore did not run correctly)")
        elif name in expect and found[name] != expect[name]:
            problems.append(f"{name}: {found[name]} chunks, live has {expect[name]}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set", help="backup set name (default: latest local)")
    ap.add_argument("--from-remote", action="store_true",
                    help="download the set first — tests the OFF-SITE copy")
    ap.add_argument("--keep", action="store_true", help="do not drop the scratch DB")
    ap.add_argument("--no-bracket", action="store_true",
                    help="skip timescaledb_pre/post_restore — the KNOWN-BROKEN "
                         "path, kept so this test can be shown to fail")
    a = ap.parse_args()

    set_dir = (fetch_from_remote(a.set) if a.from_remote
               else (STAGING / a.set if a.set else latest_set()))
    manifest = json.loads((set_dir / "manifest.json").read_text())
    print(f"restore test · set {manifest['set']} · "
          f"{'REMOTE' if a.from_remote else 'local'} copy")

    bad = verify_checksums(set_dir, manifest)
    if bad:
        print("FAIL — file integrity:", *bad, sep="\n  ")
        return 1
    print(f"  checksums ok ({len(manifest['files'])} files)")

    try:
        with tempfile.TemporaryDirectory() as td:
            errors = restore(set_dir, Path(td), bracket=not a.no_bracket)
        if a.from_remote and set_dir.name.startswith(".remote-"):
            # The downloaded copy is scratch. Left behind it accumulates one
            # full set per weekly run on the same disk the backups exist to
            # survive losing.
            shutil.rmtree(set_dir, ignore_errors=True)
        problems, matched, total = compare(manifest)
        problems += check_hypertables()
        problems += check_schema()
        if errors:
            problems.insert(0, f"pg_restore reported {errors} errors")
        print(f"  restored {total:,} rows across {matched} tables")
        ht = _psql(SCRATCH, """
            SELECT string_agg(hypertable_name || ' (' || num_chunks || ' chunks)',
                   ', ' ORDER BY 1) FROM timescaledb_information.hypertables""")
        print(f"  hypertables: {ht}")
    finally:
        if not a.keep:
            _psql("postgres", f'DROP DATABASE IF EXISTS {SCRATCH}', quiet=True)

    if problems:
        print("FAIL:", *problems, sep="\n  ")
        return 1
    print("PASS — the backup restores, exactly, hypertables intact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
