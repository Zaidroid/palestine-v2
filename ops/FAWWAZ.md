# Fawwaz and this system

Fawwaz (Zaid's Hermes assistant, the admin-owned gateway on this host) already
loads this project's MCP server as a subprocess — he can query roads, fuel,
incidents, and now the system's own health. Zaid's standing decision
(2026-08-04): **operational updates reach him through Fawwaz in the chat he
already has — no new bots, no new channels.**

## The division of labour

- **Checking** — continuous: watchdog every ~10 min, nightly backup with
  restore proof, weekly measure-review. All automated.
- **Audit & fix** — the weekly maintenance run (`palestine-v2-maintain.timer`,
  Mondays ~05:10 UTC): a Claude **Opus 5** session (model pinned in
  `ops/maintain.sh` at Zaid's instruction) runs `ops/maintenance-prompt.md`
  and writes `ops/digest-latest.md` + `ops/digests.ndjson`.
- **Delivery** — Fawwaz, via two MCP tools on the palestine-v2 server:
  - `ops_digest` — the weekly digest + measurement ledgers
  - `system_health` — live faults and open alarms, any time

## The one message Zaid sends Fawwaz to activate this

> Fawwaz, you have palestine-v2 tools. Every Monday at 9am, call the
> `ops_digest` tool and send me its Arabic summary exactly as written.
> Anything marked **[ZAID]** — highlight it to me as a question needing my
> answer. If I ever ask you "what's the system status?", use `system_health`
> and answer from it. Never summarize precision numbers optimistically —
> relay them as written, including whatever is marked unmeasured.

(The digest itself is Arabic-first — that is how the weekly run writes it
and how Fawwaz relays it; only this standing instruction is English.)

(If Fawwaz's gateway was started before 2026-08-04, the two tools appear
after its next restart — `sudo systemctl restart hermes-gateway`.)

## Real-time alarms (separate from the weekly digest)

`ops/notify.py` still wants `ALERT_BOT_TOKEN`/`ALERT_CHAT_ID` in `.env` — that
delivery ALSO lands in the same @abed_hermes_bot chat, so it adds urgency,
not channels. Until it is configured, alarms wait in `ops/alerts.ndjson` for
the watchdog, the weekly run, or a `system_health` call to surface them.
