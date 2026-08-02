#!/usr/bin/env bash
# Recompute belief over every crowd-reportable field.
#
# The checkpoint sync refreshes checkpoint kinds and the fuel loader refreshes
# fuel kinds, but a crowd report can be about power, water, internet or a road
# closure — and nothing was recomputing those, so such a report would sit in
# state_observation forever without ever reaching state_current.
#
# It also matters for the P2.4 gate. A report withheld for want of a second
# witness must start counting the MOMENT that witness arrives, and the only
# thing that notices is a refresh. Without this, corroboration would only take
# effect the next time some other feed happened to touch the same kind.
set -uo pipefail
cd /home/zaid/palestine-v2
exec ./ops/with-heartbeat.sh crowd-refresh 120 600 -- \
     .venv/bin/python -c "
from resolve.belief import refresh, crowd_kinds
print(f'crowd belief: {refresh(crowd_kinds())} rows across {len(crowd_kinds())} kinds')
"
