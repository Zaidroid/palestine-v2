"""Database connection helper. Reads .env; refuses to connect to anything but
the v2 database, so a stray script can never point at v1 or honcho's Postgres.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
GUARD_DB = "palestine_v2"


def _env() -> dict[str, str]:
    env: dict[str, str] = {}
    envfile = ROOT / ".env"
    if envfile.exists():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items() if k.startswith("PG")})
    return env


def dsn() -> str:
    e = _env()
    db = e.get("PGDATABASE", GUARD_DB)
    if db != GUARD_DB:
        raise RuntimeError(f"refusing to connect to '{db}' — expected '{GUARD_DB}'")
    return (f"host={e.get('PGHOST','127.0.0.1')} port={e.get('PGPORT','5433')} "
            f"dbname={db} user={e.get('PGUSER','palestine')} password={e['PGPASSWORD']}")


@contextmanager
def connect(**kw):
    conn = psycopg.connect(dsn(), **kw)
    try:
        yield conn
    finally:
        conn.close()
