#!/usr/bin/env bash
# Daily: backtest what we would have SERVED against what independent sources
# later reported. Closes Gate 1 and keeps it closed — a parser change or a new
# channel can move precision, and nothing else in the system would notice.
#
# Appends to ops/accuracy.ndjson so the trend is inspectable, not just the
# latest number.
set -euo pipefail
cd /home/zaid/palestine-v2
exec "$(dirname "$0")/with-heartbeat.sh" measure-accuracy 86400 10800 -- .venv/bin/python -m learn.accuracy --days 7 --write
