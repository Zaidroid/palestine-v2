#!/usr/bin/env bash
# Keep VALHALLA_URL pointing at the routing engine (found dead 2026-08-07).
#
# wb-valhalla belongs to another stack, publishes no host port, and the host
# cannot resolve container names — so v2 reaches it by container IP, and that
# IP changes every time the container restarts. On 2026-08-06 it moved
# 172.22.0.2 → .4 and /v2/route returned "routing unavailable" for eleven
# hours with nothing noticing: the route endpoints answer 200 with an error
# body, so the API smoke tests passed.
#
# This re-resolves the IP, rewrites .env only when it actually changed, and
# restarts the API so the new value is read. Idempotent and quiet.
#
# WHAT CHANGED ON 2026-09-25, AND WHY — the fixer for that outage could fail
# the same way, silently:
#   * It ran unwatched: no heartbeat, no OnFailure. It now runs through
#     with-heartbeat.sh (valhalla-ip, in the watchdog's EXPECTED_JOBS) and the
#     unit alarms on failure.
#   * .env was rewritten BEFORE the restart, and a restart that failed (sudo
#     refused, systemctl non-zero) left the running API on the old IP while
#     the next tick found .env already matching and exited 0 — forever. The
#     watchdog, which reads .env, probed the new IP and said `ok`. A restart
#     the API still owes is now remembered until it happens, and every tick
#     fails loudly until then.
#   * `cat tmp > .env` truncated the one secrets file first and wrote it
#     second; a kill or a full disk between the two left it empty — the DB
#     password and api_hash gone for every timer at once. It is now written
#     beside itself and renamed into place, which is atomic.
#   * With no VALHALLA_URL line at all, the substitution changed nothing and
#     the API was restarted every 15 minutes, exit 0. The line is now added.
set -euo pipefail
here="$(dirname "$(readlink -f "$0")")"

if [ -z "${VALHALLA_SYNC_WRAPPED:-}" ]; then
    export VALHALLA_SYNC_WRAPPED=1
    exec "$here/with-heartbeat.sh" valhalla-ip 900 1800 -- "$here/sync-valhalla-ip.sh" "$@"
fi

cd "$here/.."
envfile="$(readlink -f .env)"           # write beside the real file, not over a symlink
state="${XDG_STATE_HOME:-$HOME/.local/state}/palestine-v2"
pending="$state/valhalla-restart-pending"

if ! ip=$(docker inspect wb-valhalla \
            --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
            2>/dev/null) || [ -z "$ip" ]; then
    echo "wb-valhalla not running — nothing to sync, and routing is down" >&2
    exit 1
fi

want="http://${ip}:8002"
have=$(sed -n 's/^VALHALLA_URL=//p' "$envfile" | tail -n 1)

if [ "$want" != "$have" ]; then
    echo "valhalla moved: ${have:-<no VALHALLA_URL line>} -> $want"
    # 0600 and on the same filesystem, so the rename below is atomic; `.bak`
    # so a copy stranded by a SIGKILL matches .gitignore's `.env.*.bak` and
    # cannot be committed with the secrets inside it.
    tmp=$(mktemp --suffix=.bak "$(dirname "$envfile")/.env.valhalla-XXXXXX")
    trap 'rm -f "$tmp"' EXIT
    if grep -q '^VALHALLA_URL=' "$envfile"; then
        sed "s|^VALHALLA_URL=.*|VALHALLA_URL=${want}|" "$envfile" > "$tmp"
    else
        cat "$envfile" > "$tmp"
        [ -z "$(tail -c 1 "$envfile")" ] || echo >> "$tmp"
        printf 'VALHALLA_URL=%s\n' "$want" >> "$tmp"
    fi
    chmod 600 "$tmp"
    sync "$tmp"
    mv -f "$tmp" "$envfile"
    mkdir -p "$state"
    : > "$pending"
fi

# The running API read VALHALLA_URL once, at import. Until it has restarted
# since .env last changed here, the file is not what it is using.
if [ -e "$pending" ]; then
    if sudo -n systemctl restart palestine-v2-api.service; then
        rm -f "$pending"
        echo "api restarted — it now reads $want"
    else
        echo "API RESTART FAILED — .env says $want but the running API still holds" \
             "the old address; routing answers 'unavailable' until it restarts" >&2
        exit 1
    fi
fi

if ! curl -sS -m 5 "${want}/status" >/dev/null 2>&1; then
    echo "valhalla at $want is unreachable despite matching IP" >&2
    exit 1
fi
