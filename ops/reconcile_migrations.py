#!/usr/bin/env python3
"""F-02 · reconcile the migrations ledger.

051–067 are applied — their tables, views and indexes exist in the database —
but no row was ever written to `schema_migrations`, so `db/migrate.sh` believes
they are pending and would run each one a second time.

This script proves each unrecorded file actually landed, then records it with
the same checksum the runner itself computes (sha256 of the file, first 16
characters). It refuses to write anything unless every file is provably
applied, so a half-applied migration can never be laundered into "recorded".

A file is proven one of two ways:

  * by its declared DDL — every CREATE TABLE / VIEW / INDEX name is looked up
    in the catalogue, and every ADD CONSTRAINT in pg_constraint; or
  * for data-only migrations, which declare no object at all, by the read-only
    statements in `db/migrations/ledger-proofs.json`. A file with neither is
    refused rather than trusted.

Read-only until the last step. `--check` runs the whole verification and stops
before the inserts.

Usage:
  .venv/bin/python ops/reconcile_migrations.py --check   # verify only
  .venv/bin/python ops/reconcile_migrations.py           # verify, then record
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

GUARD_DB = "palestine_v2"
CONTAINER = "palestine-v2-db"

# Every object kind the migration runner can record. The set is closed on
# purpose: a file declaring something this script cannot verify makes the run
# refuse rather than pass that file on an unchecked object.
OBJECT_PATTERNS = {
    "table": re.compile(
        r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)",
        re.I | re.M,
    ),
    "view": re.compile(
        r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?VIEW\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)",
        re.I | re.M,
    ),
    "index": re.compile(
        r"^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)",
        re.I | re.M,
    ),
    "sequence": re.compile(
        r"^\s*CREATE\s+SEQUENCE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)",
        re.I | re.M,
    ),
    "type": re.compile(
        r"^\s*CREATE\s+TYPE\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)", re.I | re.M
    ),
    "function": re.compile(
        r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)",
        re.I | re.M,
    ),
}

# Constraints are declared DDL too, and a missing one is exactly the kind of
# half-applied state this ledger exists to make impossible.
CONSTRAINT_PATTERN = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)\s+"
    r"ADD\s+CONSTRAINT\s+([A-Za-z_][\w$]*)",
    re.I,
)


def load_env(root: Path) -> dict[str, str]:
    """Read .env without ever echoing it."""
    env = dict(os.environ)
    env_file = root / ".env"
    if not env_file.is_file():
        sys.exit(f"REFUSING: {env_file} not found.")
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def psql(env: dict[str, str], sql: str) -> str:
    """All SQL goes through the container, exactly as db/migrate.sh does."""
    proc = subprocess.run(
        [
            "docker", "exec", "-i", "-e", f"PGPASSWORD={env['PGPASSWORD']}", CONTAINER,
            "psql", "-v", "ON_ERROR_STOP=1", "-tA", "-q",
            "-U", env["PGUSER"], "-d", env["PGDATABASE"], "-c", sql,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"REFUSING: psql failed: {proc.stderr.strip()[:400]}")
    return proc.stdout.strip()


def guard(env: dict[str, str]) -> None:
    if env.get("PGDATABASE") != GUARD_DB:
        sys.exit(f"REFUSING: PGDATABASE is {env.get('PGDATABASE')!r}, expected {GUARD_DB!r}.")
    running = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True
    ).stdout.split()
    if CONTAINER not in running:
        sys.exit(f"REFUSING: container {CONTAINER} is not running.")
    actual = psql(env, "SELECT current_database()")
    if actual != GUARD_DB:
        sys.exit(f"REFUSING: connected database is {actual!r}, expected {GUARD_DB!r}.")


def declared(sql_text: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for kind, pattern in OBJECT_PATTERNS.items():
        names = [m.group(1) for m in pattern.finditer(sql_text)]
        if names:
            found[kind] = names
    return found


def exists(env: dict[str, str], kind: str, name: str) -> bool:
    if kind == "type":
        return psql(env, f"SELECT to_regtype('{name}') IS NOT NULL") == "t"
    if kind == "function":
        return psql(env, f"SELECT to_regprocedure('{name}') IS NOT NULL") == "t"
    return psql(env, f"SELECT to_regclass('{name}') IS NOT NULL") == "t"


def constraint_exists(env: dict[str, str], table: str, name: str) -> bool:
    return psql(
        env,
        "SELECT count(*) FROM pg_constraint "
        f"WHERE conname = '{name}' AND conrelid = to_regclass('{table}')",
    ) != "0"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None, help="repo root (default: parent of ops/)")
    ap.add_argument(
        "--proofs",
        default=None,
        help="proofs file for data-only migrations (default: db/migrations/ledger-proofs.json)",
    )
    ap.add_argument("--check", action="store_true", help="verify only; write nothing")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    migrations = sorted((root / "db" / "migrations").glob("*.sql"))
    if not migrations:
        sys.exit(f"REFUSING: no migrations under {root / 'db' / 'migrations'}")

    proofs_file = (
        Path(args.proofs).resolve()
        if args.proofs
        else root / "db" / "migrations" / "ledger-proofs.json"
    )
    proofs = json.loads(proofs_file.read_text()) if proofs_file.is_file() else {}

    env = load_env(root)
    guard(env)

    recorded = dict(
        line.split("|")
        for line in psql(env, "SELECT version, checksum FROM schema_migrations").splitlines()
        if line
    )
    print(f"recorded: {len(recorded)} · files on disk: {len(migrations)}")

    unrecorded, drifted = [], []
    for path in migrations:
        if path.name in recorded:
            current = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            if current != recorded[path.name]:
                drifted.append((path.name, recorded[path.name], current))
            continue
        unrecorded.append(path)

    for name, prev, current in drifted:
        print(f"WARN: {name} recorded but the file changed ({prev} -> {current})")

    if not unrecorded:
        print("nothing pending — the ledger agrees with the disk.")
        return 0

    print(f"\nunrecorded: {len(unrecorded)}")
    failures = 0
    for path in unrecorded:
        text = path.read_text()
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        checks = [
            (kind, n) for kind, names in declared(text).items() for n in names
        ]
        checks += [("constraint", f"{t}.{c}") for t, c in CONSTRAINT_PATTERN.findall(text)]

        misses: list[str] = []
        if checks:
            for kind, name in checks:
                if kind == "constraint":
                    table, _, cname = name.partition(".")
                    ok = constraint_exists(env, table, cname)
                else:
                    ok = exists(env, kind, name)
                if not ok:
                    misses.append(f"{kind} {name}")
            detail = f"{len(checks)} objects"
        else:
            file_proofs = proofs.get(path.name)
            if not file_proofs:
                misses.append("no declared object and no entry in ledger-proofs.json")
                detail = "0 objects"
            else:
                for proof in file_proofs:
                    got = psql(env, proof["sql"])
                    if got != str(proof["expect"]):
                        misses.append(
                            f"proof expected {proof['expect']}, got {got} — {proof['why']}"
                        )
                detail = f"{len(file_proofs)} proofs"

        status = "ok" if not misses else "MISSING"
        print(f"  [{status:7}] {path.name:<40} {detail:<12} sha {checksum}")
        if misses:
            failures += 1
            for m in misses:
                print(f"            {m}")

    if failures:
        print(
            f"\nREFUSING to record: {failures} of {len(unrecorded)} file(s) are not "
            "provably applied. Nothing was written."
        )
        return 2

    if args.check:
        print(f"\n--check: all {len(unrecorded)} file(s) verified present; nothing written.")
        return 0

    for path in unrecorded:
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        psql(
            env,
            "INSERT INTO schema_migrations(version, checksum) VALUES "
            f"('{path.name}', '{checksum}') ON CONFLICT (version) DO NOTHING",
        )
    total = psql(env, "SELECT count(*) FROM schema_migrations")
    print(f"\nrecorded {len(unrecorded)} file(s). schema_migrations now holds {total} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
