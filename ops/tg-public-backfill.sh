#!/usr/bin/env bash
# Read the public history of the news channels, newest first, every channel a
# slice at a time so all of them reach back together (2026-10-13).
#
#   bash ops/tg-public-backfill.sh            # runs for days; safe to stop and start
#   touch data/raw/tg_public/STOP             # ends it cleanly after the page in hand
#
# One page every two seconds. It ends at the first refusal from Telegram
# (exit 3) and does not try again by itself. See ops/fetch_telegram_public.py.
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
MAIN="${ARCHIVE_ROOT:-/home/zaid/palestine-v2}"
PY="$MAIN/.venv/bin/python"
OUT="$MAIN/data/raw/tg_public"
CHANNELS="${CHANNELS:-QudsN safaps palinfo alkofiyatv alqastalps maannews eyeonpalestine2 nabuls_news jeninnews1 khalelnews ramallahnewss tulkrmeoon qalqilianewss bethlehemnewss JerichoNews jeninalkarama bzunewss Palrcs wfp_gaza gedcogaza palmoh mohepalestine}"
cd "$HERE"
for UNTIL in ${SLICES:-2026-06-01 2025-10-01 2025-01-01 2024-04-01 2023-10-01 2022-01-01 2019-01-01 1990-01-01}; do
  echo "== slice: back to $UNTIL == $(date -u +%FT%TZ)"
  # shellcheck disable=SC2086
  "$PY" -m ops.fetch_telegram_public $CHANNELS --until "$UNTIL" --pause 2 \
      --out "$OUT" --cache "$MAIN/data/cache/tg_public_html" --bronze-root "$MAIN/data/bronze"
  rc=$?
  [ $rc -eq 0 ] || { echo "stopped with exit $rc at $(date -u +%FT%TZ)"; exit $rc; }
  [ -e "$OUT/STOP" ] && { echo "stop file found; ending"; exit 0; }
done
echo "every channel is read to its first post == $(date -u +%FT%TZ)"
