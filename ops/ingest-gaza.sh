#!/usr/bin/env bash
# Gaza Ministry of Health daily reports -> databank observations.
set -uo pipefail
cd /home/zaid/palestine-v2
exec ./ops/with-heartbeat.sh ingest-gaza 3600 7200 -- .venv/bin/python -m ingest.sources.moh_gaza
