# MCP registration — the two doors (rewritten 2026-09-24)

Sixteen public names over 29 tool functions, one table (`TOOLS` in `serve/mcp_server.py`)
plus the façade table (`serve/mcp_facades.py`), two transports. The server calls itself
**Palestine Data — live + databank** (`serverInfo.name = palestine-data`). Run `tools/list`
for the current catalogue rather than keeping a copy here.

| transport | who | tools |
|---|---|---|
| stdio · `serve/mcp_server.py` | processes on this host (Fawwaz, Sameera, Claude Code here) | the 16 + 3 host-only (`system_health`, `ops_digest`, `mcp_usage`) |
| HTTP · `POST https://live-api.zaidlab.xyz/mcp` | anybody with a key | the 16 (28 old names answer as aliases, hidden) |

HTTP needs a key — `Authorization: Bearer`, `X-Api-Key` or `?key=` — or an OAuth 2.0
token (RFC 9728/8414/7591, PKCE); the shared `public-test` key is printed in the 401
body and on the consent page. Keys live in `.keys/partner-keys.json` outside the repo,
re-read per request. Per-IP limiter 300/60 s; per-key daily quota. See `docs/PARTNER-API.md`.

The host-only tools are refused by name over HTTP (-32601), not merely hidden.
`/health` follows the same line: counts and status are public, the names of failing
jobs are local-only.
