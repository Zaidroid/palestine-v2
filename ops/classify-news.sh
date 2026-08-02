#!/usr/bin/env bash
# Classify newly-polled news claims into located incidents.
#
# Incremental by default: claims already carrying a classification are skipped,
# so this is cheap to run often. After any change to cascade/news.py run it once
# with --rebuild, which discards only THIS classifier's output and redoes it —
# the claims themselves are never touched.
set -euo pipefail
cd /home/zaid/palestine-v2
exec "$(dirname "$0")/with-heartbeat.sh" classify-news 300 900 -- .venv/bin/python -m ingest.sources.news_incidents
