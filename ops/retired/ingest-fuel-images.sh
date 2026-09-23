#!/usr/bin/env bash
# Fuel from the archived rendered cards (F-05, 2026-09-22).
#
# The tee spool's text bulletins stopped on 2026-08-28, so the only fuel signal
# left is @palhubappfuel's rendered cards — which the poller has been archiving
# all along and nothing was reading. This reads them, writes them SERVED and
# FLAGGED (--serve: modality `assertion`, attrs.modality_basis `image_ocr`, and
# the warning on every row), and refreshes belief for the two kinds it owns.
#
# NEWEST FIRST and inside a time window, because a fuel reading is asserted for
# `max_assert_seconds` (3 h, state_kind_config) after the CARD's own timestamp:
# reading yesterday's cards produces rows that are already expired, which is
# exactly what the first catch-up run measured (0 available of 212).
#
# Every 10 minutes, up to 60 new cards from the last 6 hours. The channel posts a
# MEASURED 28.6 cards an hour — 4.8 per ten-minute window — so 60 is twelve times
# the arrival rate, and the first timed run took 11 minutes of CPU to read 150 on
# the box that also runs Frigate, Immich and the voice stack. Same coverage,
# roughly a quarter of the CPU. Drop --serve to write `quarantined` rows again —
# that is the whole undo.
set -uo pipefail
cd "$(dirname "$0")/.."
exec "$(dirname "$0")/with-heartbeat.sh" fuel-images 600 1800 -- \
  ./.venv/bin/python -m ingest.sources.palhub_fuel_image \
      --serve --since-hours 6 --limit 60
