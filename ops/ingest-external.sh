#!/usr/bin/env bash
# Non-Telegram sources: RSS wires and Open-Meteo.
#
# Kept in one unit because they share a property that matters operationally —
# neither touches a Telegram session, so this can run while the poller is
# rate-limited, stopped, or being reconfigured. The two ingestion paths fail
# independently, which is most of the point of having them.
#
# A failing feed must not stop the others, so each step is allowed to fail.
#
# But "allowed to fail" used to mean the unit printed `weather failed` and then
# exited 0, so systemd recorded a success and OnFailure= could never fire. Six
# feeds could be dead at once and the only trace was a line in the journal.
# Steps are still independent; the failures are now COUNTED, named in the
# heartbeat, and re-raised at the end so the unit's exit status tells the truth.
set -uo pipefail
cd /home/zaid/palestine-v2

failed=()
step() {
  local name="$1"; shift
  "$@" || { echo "$name failed"; failed+=("$name"); }
}

step rss_news       .venv/bin/python -m ingest.sources.rss_news
step weather        .venv/bin/python -m ingest.sources.weather
step connectivity   .venv/bin/python -m ingest.sources.connectivity
step power          .venv/bin/python -m ingest.sources.power
# No-ops with a clear message until FIRMS_MAP_KEY is set in .env, so a failure
# here is a real failure rather than the expected unconfigured state.
step fires          .venv/bin/python -m ingest.sources.fires
step classify       .venv/bin/python -m ingest.sources.news_incidents

if [ ${#failed[@]} -eq 0 ]; then
  .venv/bin/python -m ops.heartbeat ingest-external --interval 900 --grace 1800 \
      --detail '{"steps": 6, "failed": 0}' || true
  exit 0
fi

joined=$(IFS=,; echo "${failed[*]}")
.venv/bin/python -m ops.heartbeat ingest-external --interval 900 --grace 1800 \
    --fail "failed steps: $joined" || true
echo "${#failed[@]} of 6 steps failed: $joined" >&2
exit 1
