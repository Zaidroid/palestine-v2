#!/usr/bin/env bash
# The Valhalla IP sync — the fixer for the routing outage that already
# happened — ran with no heartbeat and no OnFailure, so a half-applied run
# left the API dead while the watchdog read green (audit F065). Wrapped and
# registered like every other job; the unit's ExecStart points here.
set -uo pipefail
cd /home/zaid/palestine-v2
exec ./ops/with-heartbeat.sh valhalla-ip 900 1800 -- ./ops/sync-valhalla-ip.sh
