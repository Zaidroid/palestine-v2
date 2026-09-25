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
set -uo pipefail
cd /home/zaid/palestine-v2

ip=$(docker inspect wb-valhalla \
       --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
       2>/dev/null)
[ -z "$ip" ] && { echo "wb-valhalla not running — nothing to sync" >&2; exit 1; }

want="http://${ip}:8002"
have=$(grep -E '^VALHALLA_URL=' .env | cut -d= -f2-)

if [ "$want" = "$have" ]; then
    curl -sS -m 5 "${want}/status" >/dev/null 2>&1 \
        && exit 0 \
        || { echo "valhalla at $want is unreachable despite matching IP" >&2; exit 1; }
fi

echo "valhalla moved: ${have:-<absent>} -> $want"
# ATOMIC (audit F278): the secrets file was rewritten in place through `cat >`
# every 15 minutes, and a missing VALHALLA_URL line meant an endless restart.
umask 077
tmp=".env.tmp.$$"; trap 'rm -f "$tmp"' EXIT
if [ -n "$have" ]; then
    sed "s|^VALHALLA_URL=.*|VALHALLA_URL=${want}|" .env > "$tmp"
else
    { cat .env; echo "VALHALLA_URL=${want}"; } > "$tmp"
fi
if cmp -s "$tmp" .env; then
    echo "no change to .env after all"; exit 0
fi
chmod 600 "$tmp"
mv -f "$tmp" .env
sudo -n systemctl restart palestine-v2-api.service && echo "api restarted"
