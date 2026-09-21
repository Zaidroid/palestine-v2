"""THE LOCAL ANALYST — a consumer of `claim`, not a collector.

Design: ~/lifeos-kernel/docs/LOCAL-ANALYST-2026-09.md. This package is P0 of it:
organ A (language detection), the skeleton the model organs B–G plug into
(watermark loop, provenance, metrics, gaming backpressure), and nothing else.

    .venv/bin/python -m analyst.loop              # the service loop
    .venv/bin/python -m analyst.loop --once       # one tick, then exit
    .venv/bin/python -m analyst.backfill_lang --dry-run

WHAT IT MAY WRITE
`claim.lang` and `claim.attrs.lang_detector` (organ A — metadata ABOUT the
text, not a restatement of what the source said), `analyst_run`,
`analyst_watermark`, and later `claim_classification` rows under
`classifier='analyst-<organ>'`. It never writes `event`, `state_current`,
`observation` or `state_observation` outside quarantine, and never touches the
belief engine.
"""
