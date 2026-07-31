# Registering the Palestine v2 MCP server

One stdio server, `serve/mcp_server.py`, exposing four tools. Every tool returns
a short Arabic `answer` string (ready to speak) plus structured data.

| tool | question it answers |
|:--|:--|
| `fuel_near` | وين في سولار/بنزين؟ — nearest available stations |
| `fuel_summary` | وضع الوقود بالضفة — West-Bank-wide totals |
| `latest_news` | آخر الأخبار — recent messages, optionally by area |
| `coverage` | what this system currently holds (sources, states, places) |

## Claude Code

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
