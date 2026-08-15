# Registering the Palestine v2 MCP server

24 tools, one table (`TOOLS` in `serve/mcp_server.py`), two transports. Every
tool returns a short Arabic `answer` string (ready to speak) plus structured
data. Run `tools/list` for the current catalogue rather than keeping a copy
here — a hand-maintained list beside the code drifts from it within a week.

| transport | who it is for | what it serves |
|:--|:--|:--|
| stdio · `serve/mcp_server.py` | processes on this host (Fawwaz, Sameera, Claude Code here) | all 24 tools |
| HTTP · `POST /mcp` | anybody, no clone and no venv | 22 — the ops tools are withheld |

## Public HTTP — https://live-api.zaidlab.xyz/mcp

Streamable HTTP, JSON-RPC 2.0, stateless, no auth. Mounted on the existing
public host rather than a new one because the tunnel is token-managed:
hostnames live in the Cloudflare dashboard and cannot be added from here.

```bash
claude mcp add --transport http palestine https://live-api.zaidlab.xyz/mcp
```

Three things hold that surface in place, and all three have tests
(`tests/test_mcp_http.py`):

- **`system_health` and `ops_digest` are not served over HTTP.** They report
  failing units and the maintenance ledger — infrastructure detail answering a
  question nobody outside asked. Refused by name, not merely hidden from the
  listing.
- **No write path**, exactly as on stdio. The crowd endpoints stay human.
- **A caller's string never becomes a URL path.** `databank(category=…)` was
  the one place it did, and `../../health` walked out of the databank surface
  into another endpoint. Now validated at the tool AND in `api()`, through
  which every tool fetches.

`/health` follows the same line: counts and status are public, the names of
what is currently broken are answered only for local callers.

## Claude Code — on this host, all 24 tools

```bash
claude mcp add palestine -- /home/zaid/palestine-v2/.venv/bin/python \
    -m serve.mcp_server
```
(run from `/home/zaid/palestine-v2`, or add `--cwd`)

## Fawwaz / Sameera (hermes)

hermes reads MCP servers from its config. Add:

```yaml
mcp:
  servers:
    palestine:
      command: /home/zaid/palestine-v2/.venv/bin/python
      args: ["-m", "serve.mcp_server"]
      cwd: /home/zaid/palestine-v2
```

Fawwaz's config: `/home/admin/.hermes/config.yaml`
Sameera's:      `/home/admin/.hermes/profiles/taqwa/config.yaml`

## Any other agent — plain HTTP

The same data is on the REST API, no MCP needed:

```
GET http://127.0.0.1:7870/v2/fuel/nearby?lat=32.22&lon=35.25&fuel=diesel
GET http://127.0.0.1:7870/v2/fuel/stations?region=نابلس
GET http://127.0.0.1:7870/v2/fuel/summary
GET http://127.0.0.1:7870/health
```

## Contract note for whoever builds the voice bot

`answer` already contains the uncertainty ("الموقع تقريبي", "آخر تحديث قبل
ساعتين"). Read it as-is. Do NOT rephrase it into something more confident — the
whole serving layer is built so a stale or imprecise reading is never asserted
as current, and smoothing that away in the voice layer defeats it. During a
fuel shortage the difference is a wasted tank; for a checkpoint it is worse.
