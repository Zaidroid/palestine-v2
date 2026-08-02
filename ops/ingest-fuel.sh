#!/usr/bin/env bash
# Continuous fuel ingestion: tee spool -> v2 state tables.
# The palhub feed sweeps every ~30 min; running every 5 min keeps the API within
# one sweep of the source without hammering anything.
#
# This used to claim it was "idempotent — re-reading the same spool lines
# produces the same observations". It was not: re-reading them INSERTED them
# again, 98.48% of all fuel rows were exact duplicates, and one observation was
# stored 490 times. Genuinely idempotent since migration 023, which gives the
# loader a cursor (ingest_seen) instead of a comment asserting it has one.
set -uo pipefail
cd "$(dirname "$0")/.."
exec "$(dirname "$0")/with-heartbeat.sh" ingest-fuel 300 900 -- ./.venv/bin/python -m ingest.sources.palhub_loader
