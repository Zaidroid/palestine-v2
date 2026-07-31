#!/usr/bin/env bash
# P0.7 — migration runner. Applies db/migrations/*.sql in filename order,
# records applied versions, idempotent, refuses to touch the wrong database.
#
# Usage:
#   db/migrate.sh              apply pending migrations
#   db/migrate.sh --status     list applied / pending
#   db/migrate.sh --tuning     apply db/tuning.sql (ALTER SYSTEM) + restart hint
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a; . "$ROOT/.env"; set +a

: "${PGDATABASE:?}" "${PGUSER:?}" "${PGPASSWORD:?}"
GUARD_DB="palestine_v2"
CONTAINER="palestine-v2-db"

# All psql goes through the container so no host postgres client is required.
psql_run() {
  docker exec -i -e PGPASSWORD="$PGPASSWORD" "$CONTAINER" \
    psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d "$PGDATABASE" "$@"
}

# --- Safety: never run against anything but the v2 database -------------------
if [ "$PGDATABASE" != "$GUARD_DB" ]; then
  echo "REFUSING: PGDATABASE is '$PGDATABASE', expected '$GUARD_DB'." >&2
  exit 1
fi
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "REFUSING: container '$CONTAINER' is not running." >&2
  exit 1
fi
ACTUAL=$(psql_run -tAc "SELECT current_database()")
if [ "$ACTUAL" != "$GUARD_DB" ]; then
  echo "REFUSING: connected database is '$ACTUAL', expected '$GUARD_DB'." >&2
  exit 1
fi

psql_run -q <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     TEXT PRIMARY KEY,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  checksum    TEXT NOT NULL
);
SQL

applied() { psql_run -tAc "SELECT 1 FROM schema_migrations WHERE version='$1'" | grep -q 1; }

if [ "${1:-}" = "--status" ]; then
  printf '%-34s %s\n' "MIGRATION" "STATUS"
  for f in "$ROOT"/db/migrations/*.sql; do
    v=$(basename "$f")
    if applied "$v"; then printf '%-34s %s\n' "$v" "applied"; else printf '%-34s %s\n' "$v" "PENDING"; fi
  done
  exit 0
fi

if [ "${1:-}" = "--tuning" ]; then
  echo "Applying db/tuning.sql (ALTER SYSTEM)..."
  psql_run -q < "$ROOT/db/tuning.sql"
  echo "Done. Restart required:  docker restart $CONTAINER"
  exit 0
fi

for f in "$ROOT"/db/migrations/*.sql; do
  v=$(basename "$f")
  sum=$(sha256sum "$f" | cut -c1-16)
  if applied "$v"; then
    prev=$(psql_run -tAc "SELECT checksum FROM schema_migrations WHERE version='$v'")
    [ "$prev" = "$sum" ] || echo "WARN: $v already applied but file changed ($prev -> $sum)" >&2
    continue
  fi
  echo "==> $v"
  # Each migration runs in its own transaction; a failure aborts the whole run.
  psql_run -q -1 < "$f"
  psql_run -q -c "INSERT INTO schema_migrations(version,checksum) VALUES ('$v','$sum')"
done
echo "OK — all migrations applied."
