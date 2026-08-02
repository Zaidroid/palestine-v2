#!/usr/bin/env bash
# Palhub road bulletin -> checkpoint_flow observations (QUARANTINED).
#
# Collected continuously, deliberately not believed: it agrees with the road
# channels only 46.7% of the time against their 96.8% with each other. See
# ingest/sources/palhub_roads.py. The rows accumulate so the disagreement can be
# diagnosed; nothing reaches a served value until a measurement says it should.
set -uo pipefail
cd /home/zaid/palestine-v2
exec ./ops/with-heartbeat.sh ingest-palhub-roads 300 900 -- \
     .venv/bin/python -m ingest.sources.palhub_roads --limit 500
