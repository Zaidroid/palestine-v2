#!/usr/bin/env bash
# Continuous fuel ingestion: tee spool -> v2 state tables.
# The palhub feed sweeps every ~30 min; running every 5 min keeps the API within
# one sweep of the source without hammering anything. Idempotent — re-reading
# the same spool lines produces the same observations.
set -uo pipefail
cd "$(dirname "$0")/.."
exec ./.venv/bin/python -m ingest.sources.palhub_loader
