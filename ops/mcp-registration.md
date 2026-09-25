# MCP registration — one name, two doors (rewritten 2026-09-25, P2-B)

The server is **Palestine Data — live + databank** (بيانات فلسطين): `serverInfo.name =
palestine-data`, `serverInfo.title` = that name, and the same name on the OAuth metadata
(`resource_name`), the consent page, the front page and the partner guide. Run `tools/list`
for the live catalogue rather than keeping a copy here.

- Front page: https://live-api.zaidlab.xyz/ — a browser gets the page (status, the twelve
  questions answered live, how to connect); an API client gets the JSON route map, unchanged.
- Partner guide: https://live-api.zaidlab.xyz/docs/partner (`docs/PARTNER-API.md` rendered;
  the file itself at `/docs/partner.md`), and the twelve-question script at `/docs/try-twelve.sh`.

## The surface

- **16 public tools** — `about`, `checkpoint_status`, `checkpoints`, `can_i_travel`,
  `incidents`, `place`, `insights`, `news`, `weather_now`, `connectivity_now`, `fuel_prices`,
  `crossings`, `databank`, `series`, `correlate`, `licence`. Ten are functions in `TOOLS`
  (`serve/mcp_server.py`); six (`checkpoints`, `incidents`, `place`, `news`, `series`,
  `licence`) are façades in `serve/mcp_facades.py` that route to an absorbed tool by their
  arguments.
- **19 absorbed names still answer for one release**, hidden from `tools/list`: `coverage`,
  `data_gaps`, `stream_info`, `licenses`, `licence_tools`, `checkpoints_near`,
  `checkpoints_summary`, `incidents_near`, `incidents_summary`, `place_profile`,
  `place_history`, `place_pattern`, `where_is`, `latest_news`, `search`, `trend`, `compare`,
  `what_correlates_with`, `area_history`. With the nine names that kept their place, all 28
  pre-2026-09-24 names still work.
- **3 host-only tools** — `system_health`, `ops_digest`, `mcp_usage` — over stdio only. Over
  HTTP they are refused by name (-32601), not merely hidden. `/health` follows the same line:
  counts and status are public, the names of failing jobs are local-only.
- No write path on either transport: contributing a report stays human (`/v2/crowd`).

| transport | who | tools |
|---|---|---|
| stdio · `.venv/bin/python -m serve.mcp_server` from the repo root | processes on this host — the Hermes gateways spawn it for Fawwaz and Sameera; Claude Code here | the 16 + the 3 host-only (+ the aliases) |
| HTTP · `POST https://live-api.zaidlab.xyz/mcp` (streamable HTTP, stateless, JSON-RPC 2.0) | anybody with a key or an OAuth token | the 16 (+ the aliases) |

## The door (HTTP)

- **A partner key** as `Authorization: Bearer <key>`, `X-Api-Key: <key>` or `?key=<key>` (the
  last is scrubbed from the access log). Keys live in `.keys/partner-keys.json`, outside the
  repo, re-read on every request, so revocation needs no restart. Each key has a daily quota.
- **The public test key** is the `public-test` record in that file: shared, 5,000 calls a day
  across everyone, printed in every 401 body, on the consent page and on the front page (all
  three read it from the file, so rotating it is one edit).
- **OAuth 2.0 for hosted clients** (Claude, ChatGPT): RFC 9728 metadata at
  `/.well-known/oauth-protected-resource` (and `…/mcp`), RFC 8414 at
  `/.well-known/oauth-authorization-server`, RFC 7591 registration at `POST /register`, then
  `/authorize` — a page that asks for a partner key, because this is a gate — and `/token`
  (authorization code, PKCE S256 required, refresh tokens rotate). A token dies with its key
  and spends that key's quota. The 401 carries `WWW-Authenticate: Bearer resource_metadata=…`
  and `x-key-request: https://live-api.zaidlab.xyz/#connect`.
- Callers on this host (127.0.0.1) need no key and are served at the `house` licence tier;
  everyone through the tunnel is `partner` (news bodies excerpted).
- Limits: 300 MCP requests per 60 s per address; a body is at most 256 KB and a batch 8
  messages.

## Registering it

- **Claude (claude.ai, desktop):** Settings → Connectors → Add custom connector →
  `https://live-api.zaidlab.xyz/mcp` with no key → the consent page asks for one.
- **Claude Code:** `claude mcp add --transport http palestine-data https://live-api.zaidlab.xyz/mcp --header "X-Api-Key: <key>"`
  (leave the header out to go through OAuth instead).
- **ChatGPT and other MCP clients:** the same URL as a remote MCP server. A client that speaks
  OAuth finds the consent page by itself; one that takes only a URL uses `…/mcp?key=<key>`.
- **On this host:** stdio, `command` = `/home/zaid/palestine-v2/.venv/bin/python`, `args` =
  `["-m", "serve.mcp_server"]`, working directory = the repo root. It talks to the API over
  HTTP (`PALESTINE_API`, default `http://127.0.0.1:7870`) and needs no database credentials.

## Proof

`docs/try-twelve.sh` asks the twelve canonical questions over HTTP with a key;
`tests/test_mcp_http.py`, `tests/test_mcp_oauth.py` and `tests/test_front_door.py` hold the
surface, the door, and the links on the front page, the guide and the OAuth metadata.
