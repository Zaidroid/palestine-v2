#!/usr/bin/env bash
# A throwaway local test database for working on this plan away from main-server.
# Postgres 16 + PostGIS 3 + TimescaleDB 2 on 127.0.0.1:5433, schema only, NO production data.
# Verified 2026-09-25 on Ubuntu 24.04 (Claude Code cloud container). It never touches main-server.
#
#   bash docs/audit-2026-09-25/plan/local-test-db.sh install   # once per container (apt; ~2 min)
#   bash docs/audit-2026-09-25/plan/local-test-db.sh start     # start the cluster (creates it the first time)
#   bash docs/audit-2026-09-25/plan/local-test-db.sh migrate   # apply db/migrations/*.sql not yet applied
#   source docs/audit-2026-09-25/plan/local-test-db.sh env     # export PG* so resolve.db.connect() works
#
# Known, deliberate deviations from db/migrate.sh (both are findings in the plan, 08-gazetteer.md):
#   * 062_place_closure.sql is applied WITHOUT `-1`: it adds an enum value and uses it in the same
#     transaction, which fails under migrate.sh's own `psql -1`.
#   * 018 and 074 are recorded as skipped: they insert aliases for production place_ids that do not
#     exist in an empty database.
set -uo pipefail
PGBIN=/usr/lib/postgresql/16/bin
DATA=/var/lib/postgresql/palv2
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

_env() {
  export PGHOST=127.0.0.1 PGPORT=5433 PGUSER=palestine PGPASSWORD=localtest PGDATABASE=palestine_v2
}

case "${1:-env}" in
  install)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && apt-get install -y -qq postgresql-16 postgresql-16-postgis-3
    curl -fsSL https://packagecloud.io/timescale/timescaledb/gpgkey | gpg --dearmor -o /usr/share/keyrings/timescaledb.gpg
    echo "deb [signed-by=/usr/share/keyrings/timescaledb.gpg] https://packagecloud.io/timescale/timescaledb/ubuntu/ noble main" \
      > /etc/apt/sources.list.d/timescaledb.list
    apt-get update -qq && apt-get install -y -qq timescaledb-2-postgresql-16
    pip install -q pytest fastapi httpx "psycopg[binary]" pyyaml uvicorn python-multipart
    ;;
  start)
    if [ ! -d "$DATA" ]; then
      install -d -o postgres -g postgres "$DATA"
      su postgres -c "$PGBIN/initdb -D $DATA -U postgres --auth=trust -E UTF8 --locale=C.UTF-8" >/dev/null
      printf "port = 5433\nlisten_addresses = '127.0.0.1'\nshared_preload_libraries = 'timescaledb'\ntimescaledb.telemetry_level = off\nmax_connections = 60\nfsync = off\nsynchronous_commit = off\n" >> "$DATA/postgresql.conf"
      FIRST=1
    fi
    su postgres -c "$PGBIN/pg_ctl -D $DATA -l $DATA/server.log -w start" | tail -1
    if [ "${FIRST:-0}" = 1 ]; then
      psql -h 127.0.0.1 -p 5433 -U postgres -qc "CREATE ROLE palestine LOGIN SUPERUSER PASSWORD 'localtest'"
      createdb -h 127.0.0.1 -p 5433 -U postgres -O palestine palestine_v2
    fi
    ;;
  migrate)
    _env
    psql -qc "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), checksum TEXT NOT NULL)" 2>/dev/null
    for v in 018_fix_governorate_names.sql 074_crossing_name_aliases.sql; do
      psql -qc "INSERT INTO schema_migrations(version,checksum) VALUES ('$v','skipped-data-only') ON CONFLICT DO NOTHING"
    done
    for f in "$REPO"/db/migrations/*.sql; do
      v=$(basename "$f")
      psql -tAc "SELECT 1 FROM schema_migrations WHERE version='$v'" | grep -q 1 && continue
      if [ "$v" = 062_place_closure.sql ]; then tx=""; else tx="-1"; fi
      if out=$(psql -q -v ON_ERROR_STOP=1 $tx -f "$f" 2>&1); then
        psql -qc "INSERT INTO schema_migrations(version,checksum) VALUES ('$v','local')"
        echo "OK   $v"
      else
        echo "FAIL $v :: $(echo "$out" | grep -m1 ERROR)"
      fi
    done
    ;;
  env) _env ;;
esac
