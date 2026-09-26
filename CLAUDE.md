# Palestine Data — live + databank (بيانات فلسطين)

Working notes for a Claude Code session on this repository. Read
`docs/HANDOFF.md` §1 first: its seven hard rules are the constitution of this
project (v1 at `/opt/stacks/palestine` is live production and is never
developed in place; no data loss; the Telegram account is the scarcest asset;
`claim` is immutable; the API reads the `*_serving` views; secrets live in
`.env`, which is never committed).

## Where things run

- **main-server** (Zaid's homelab) runs everything: the TimescaleDB in docker
  (`palestine-v2-db`, 127.0.0.1:5433), the serving API (`palestine-v2-api`,
  :7870 → https://live-api.zaidlab.xyz, MCP at `/mcp`), the pollers and timers
  (`docs/HANDOFF.md` §2). The classifier timer runs the working tree every
  5 minutes, so `cascade/` and `ingest/` changes go live at the next tick;
  `serve/` changes go live only after `sudo systemctl restart palestine-v2-api`,
  which is Zaid's hand.
- **A checkout anywhere else** (a cloud session, a laptop) has the code and the
  docs but no database, no `.env` and no v1 SQLite. What runs there: the
  pure-Python tests — `tests/test_news.py`, `tests/test_place_extraction.py`,
  `tests/test_quality.py`, `tests/test_facades.py`, `tests/test_headlines.py`,
  `tests/test_corridor.py` (the parts that build no connection) — and
  `ops/rescore_round.py N` (re-reads a scored precision round with the current
  classifier, no DB). Anything that imports `resolve.db.connect` or reads
  `PALESTINE_API` needs main-server; write the change, keep the tests you can
  run green, and say which ones you could not run.
- v1's stack is read through one setting, `V1_ROOT` (environment or `.env`;
  default `/opt/stacks/palestine`). Set `V1_ROOT=none` on a machine without v1:
  every v1 path then points nowhere and each reader's "v1 absent" branch runs.
  Code never spells the path itself; `resolve.db.v1_path()` does
  (`tests/test_v1_root.py` holds that line).
- Never fabricate a DB measurement. If a number needs the database, say so.

## The plan and the ledger

- `docs/PLAN-2026-09-24-PUBLIC-RELEASE.md` — the canonical plan: six measured
  root causes, gates G1–G7, workstreams P0→P3, Zaid's decisions, and §11, the
  append-only progress ledger (`date · task · done|blocked|partial · proof`).
  Every claim of progress goes there with the commit and the number.
- `docs/HANDS-2026-09-24.md` — the copy-paste blocks only Zaid can run
  (restarts, v1's `.env`, systemd drop-ins, letters).
- `docs/PLAN-2026-09-21-PALESTINE-FOCUS.md` — the earlier plan; its §8 ledger
  is history. `docs/DESIGN.md` — the serving doctrine (Arabic first, the
  three-state vocabulary: value / unknown / no source).
- Incident classifier quality is measured, never asserted:
  `learn/incident_precision.py --sample --round N` draws a hand-scored round,
  `--score --round N` scores it, `ops/incident-precision.json` is the latest
  round and `serve/quality.py` puts it beside every incident count. Round 8
  (2026-09-24, classifier 1.8.0) measured 0.767 overall; 1.8.1 serves
  unmeasured until round 9 draws a fresh sample. The audit branch bumps it to
  1.9.0 — its go-live prerequisites are in the audit's `HANDS-NEEDED.md` item 9.
- `docs/audit-2026-09-25/` — the 2026-09-25 audit: `plan/00-README.md` (how to
  work the fix plan), `plan/STATUS.md` (every task done / partial / open, with
  its commit), `plan/HANDS-NEEDED.md` (what only main-server can do, and the
  rollout runbook). Read STATUS before fixing anything the audit found.

## Conventions

- One pair of hands per file: while a workstream is open, one executor edits
  `serve/`, `resolve/`, `cascade/`, `tests/` and appends to §11.
- Rails: Claude Max, Codex, and local models on the brain — no other paid API.
- Commits end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`
  (or the model that wrote them).
- Migrations: `db/migrations/NNN_*.sql`, applied on main-server with
  `db/migrate.sh`; a data fix keeps the old value in `attrs` for rollback.
- Tests on main-server: a dev API on :7871
  (`.venv/bin/python -m uvicorn serve.app:app --port 7871`) and
  `PALESTINE_API=http://127.0.0.1:7871 .venv/bin/python -m pytest -q tests`,
  deselecting the vault schedule tests. Stop the dev API by its pid or port —
  never by a pattern that also matches the production unit.
