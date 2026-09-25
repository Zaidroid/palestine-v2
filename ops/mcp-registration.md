# MCP registration — the two doors (rewritten 2026-09-24)

Sixteen public names over 29 tool functions, one table (`TOOLS` in `serve/mcp_server.py`)
plus the façade table (`serve/mcp_facades.py`), two transports. The server calls itself
**Palestine Data — live + databank** (`serverInfo.name = palestine-data`). Run `tools/list`
for the current catalogue rather than keeping a copy here.

| transport | who | tools |
|---|---|---|
| stdio · `serve/mcp_server.py` | processes on this host (Fawwaz, Sameera, Claude Code here) | the 16 + 3 host-only (`system_health`, `ops_digest`, `mcp_usage`) |
| HTTP · `POST https://live-api.zaidlab.xyz/mcp` | anybody with a key | the 16 (19 old names answer as aliases, hidden: `mcp_facades.ABSORBED`) |

HTTP needs a key — `Authorization: Bearer`, `X-Api-Key` or `?key=` — or an OAuth 2.0
token (RFC 9728/8414/7591, PKCE); the shared `public-test` key is printed in the 401
body and on the consent page. Keys live in `.keys/partner-keys.json` outside the repo,
re-read whenever the file changes. Per-IP limiter 300/60 s; per-key daily quota for
header and `?key=` callers — OAuth token callers are not yet counted against it, and
removing a key does not yet revoke the tokens issued with it (PARTNER-API §1,
SECURITY-REVIEW §8; PLAN P1-C.4). See `docs/PARTNER-API.md`.

The 29 tool functions are the 32 entries of `TOOLS` minus the 3 host-only ones; 10 of
them are listed under their own name, 19 answer only as aliases, and 6 of the 16 listed
names are façades that route to them (`licence`, `checkpoints`, `incidents`, `place`,
`news`, `series`) while 3 more (`crossings`, `insights`, `correlate`) are façades over a
tool of the same name. Counted from `serve/mcp_facades.py` 2026-09-25.

The host-only tools are refused by name over HTTP (-32601), not merely hidden.
`/health` follows the same line: counts and status are public, the names of failing
jobs are local-only.
