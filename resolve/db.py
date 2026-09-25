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


_ENV_CACHE: tuple[float, dict[str, str]] | None = None


def _env() -> dict[str, str]:
    """.env parsed once per change (by mtime): dsn() ran on every query and
    re-read the file each time (audit 2026-09-25 F293)."""
    global _ENV_CACHE
    envfile = ROOT / ".env"
    mtime = envfile.stat().st_mtime if envfile.exists() else -1.0
    if _ENV_CACHE is None or _ENV_CACHE[0] != mtime:
        parsed: dict[str, str] = {}
        if mtime >= 0:
            for line in envfile.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                parsed[k.strip()] = v.strip()
        _ENV_CACHE = (mtime, parsed)
    env = dict(_ENV_CACHE[1])
    env.update({k: v for k, v in os.environ.items() if k.startswith("PG")})
    return env


def env_value(key: str, default: str | None = None) -> str | None:
    """Read a setting the way the DB layer does: .env first, then the real
    environment. Added 2026-08-07 after /v2/route ran eleven hours on a
    hardcoded fallback IP because serve/app.py consulted os.environ only,
    and .env — where VALHALLA_URL actually lives — was never read."""
    return os.environ.get(key) or _env().get(key) or default


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


# ── a pool for the serving layer (audit 2026-09-25 F293/F287) ─────────────
# The API opened one backend per statement against max_connections=20, so
# ~17 concurrent callers were the real ceiling. When psycopg_pool is installed
# the serving layer borrows from one pool (PG_POOL_MAX, default 12); when it
# is not, it falls back to a connection per call exactly as before — nothing
# breaks on a machine without the package, the ceiling just stays low.
_POOL: object | None = None
_POOL_UNAVAILABLE = False


def _pool():
    global _POOL, _POOL_UNAVAILABLE
    if _POOL is not None or _POOL_UNAVAILABLE:
        return _POOL
    try:
        from psycopg_pool import ConnectionPool
    except ImportError:
        _POOL_UNAVAILABLE = True
        return None
    _POOL = ConnectionPool(dsn(), min_size=1,
                           max_size=int(os.environ.get("PG_POOL_MAX", "12")),
                           open=True, name="palestine-v2-serving")
    return _POOL


def pool_status() -> dict:
    """For /health: whether the serving layer is pooled, and how full."""
    pool = _pool()
    if pool is None:
        return {"pooled": False}
    st = pool.get_stats()
    return {"pooled": True, "size": st.get("pool_size"), "max": pool.max_size,
            "in_use": st.get("pool_size", 0) - st.get("pool_available", 0),
            "waiting": st.get("requests_waiting", 0)}


@contextmanager
def connection():
    """A connection for ONE unit of work: pooled when a pool exists, fresh
    otherwise. Commits on clean exit, rolls back on an exception (both paths
    behave like `with psycopg.connect(...) as conn`)."""
    pool = _pool()
    if pool is not None:
        with pool.connection() as conn:
            yield conn
        return
    with psycopg.connect(dsn()) as conn:
        yield conn
