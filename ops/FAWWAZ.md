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

> فوّاز، عندك أدوات palestine-v2. كل يوم اثنين الساعة ٩ الصبح استدعِ أداة
> `ops_digest` وابعثلي الملخص العربي منها كما هو، وأي بند فيه **[ZAID]**
> أبرزه لي كسؤال. وإذا سألتك في أي وقت "شو وضع النظام؟" استخدم
> `system_health` وجاوبني منها. لا تلخّص أرقام الدقة بتفاؤل — انقلها كما
> كُتبت، مع ما هو غير مقاس.

(If Fawwaz's gateway was started before 2026-08-04, the two tools appear
after its next restart — `sudo systemctl restart hermes-gateway`.)

## Real-time alarms (separate from the weekly digest)

`ops/notify.py` still wants `ALERT_BOT_TOKEN`/`ALERT_CHAT_ID` in `.env` — that
delivery ALSO lands in the same @abed_hermes_bot chat, so it adds urgency,
not channels. Until it is configured, alarms wait in `ops/alerts.ndjson` for
the watchdog, the weekly run, or a `system_health` call to surface them.
