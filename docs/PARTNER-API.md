# Partner API — live status for the West Bank

One server, two surfaces over the same data and the same code path:

* **MCP over HTTP** — `POST https://live-api.zaidlab.xyz/mcp` (JSON-RPC 2.0, stateless, no session to resume)
* **REST** — `https://live-api.zaidlab.xyz/v2/...` (same numbers, for callers without an MCP client)

27 tools. No write path: an agent cannot file a report, ever, by design. Read the
`coverage` tool first — it says what this system holds and, more usefully, what it
holds nothing for.

---

## 1. Authentication

Send the key once per request, either way:

    Authorization: Bearer <key>
    X-Api-Key: <key>

A client whose UI takes a single URL and has no header field (Claude's connector
UI is one) appends it instead:

    https://live-api.zaidlab.xyz/mcp?key=<key>

A missing or unknown key returns `401` with the reason in the JSON-RPC error body.
Keys are read from a file on every request, so revocation takes effect without a
restart, and `?key=` is scrubbed from the server's access log.

## 2. Handshake

Standard MCP. `initialize` answers with the protocol version it will use
(`2025-06-18`, `2025-03-26` and `2024-11-05` are supported; anything else is
answered with the current one), then `tools/list`, then `tools/call`. `ping`
works. `GET /mcp` returns `405` on purpose: this transport is stateless, and
there is no server-initiated stream — live changes are on `/v2/stream` as SSE.

Call a tool with:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"insights","arguments":{"place":"رام الله","days":30}}}
```

Every tool returns three things: a short Arabic `answer` written to be read aloud
verbatim, an English `answer_en`, and the structured data behind both (also
mirrored into `structuredContent`). **The `answer` already contains the
uncertainty — the age of the reading, whether anyone independent corroborated it,
whether the field has a source at all.** Do not rephrase it into something more
confident.

## 3. The tools

**Checkpoints** — `checkpoint_status` (one named checkpoint: flow, whether it is
passable, who is present, age), `checkpoints_near` (nearest first, with what is
NOT known), `checkpoints_summary` (West Bank picture).

**Incidents** — `incidents_near` (raids, settler attacks, closures, arrests,
demolitions, with the count of *independent* channels), `incidents_summary`.

**Insights and analysis** — `insights` (below), `place_history`,
`place_pattern` (hour-of-day rhythm at one place), `area_history` (governorate
rollup), `trend`, `compare`, `correlate`, `what_correlates_with`, `data_gaps`
(where the record thins), `databank` (categories and series), `licenses` (what
each dataset's licence obliges).

**Getting around** — `can_i_travel` (route plus the checkpoints on it),
`where_is`, `crossings` (Rafah, Kerem Shalom, Allenby, King Hussein).

**Conditions** — `weather_now`, `connectivity_now`, `fuel_prices` (the Petroleum
Corporation's monthly maximum for the West Bank, confirmed only when two
independent outlets agree and one names the Corporation), `latest_news`,
`search`, `stream_info`.

**Meta** — `coverage`, `place_profile`.

## 4. The question this was built for

> "Give me quick insights about checkpoint status last month around Ramallah."

```json
{"name":"insights","arguments":{"place":"رام الله","days":30,"radius_km":15}}
```

Answer, 2026-09-23 (abridged from the real payload):

```json
{
  "scope": {"name": "رام الله", "name_en": "Ramallah", "kind": "locality",
            "lat": 31.9038, "lon": 35.2034, "radius_km": 15, "days": 30},
  "checkpoints": {
    "places": 33, "readings": 10168,
    "over_window": {"open": 7430, "congested": 1525, "closed": 1209, "slow": 1},
    "now": {"open": 14, "closed": 6, "congested": 4, "unknown": 11},
    "freshest_reading_minutes": 2,
    "directions": {"both": 10168, "inbound": 447, "outbound": 563},
    "most_reported": [{"name_ar": "عين سينيا", "readings": 1547, "distinct_values": 3}],
    "changing": [{"name_ar": "عين سينيا", "readings": 1547, "distinct_values": 3}],
    "busiest_hours_hebron": [{"hour": 17, "n": 791}, {"hour": 20, "n": 727}],
    "presence": {"army": {"present": 668, "absent": 108},
                 "inspection": {"present": 423},
                 "police": {"present": 120}, "settlers": {"present": 6}}
  },
  "incidents": {"by_type": [{"type": "raid", "events": 270, "corroborated": 19},
                            {"type": "settler_attack", "events": 192, "corroborated": 21}]},
  "quality": {"checkpoints": {"precision": 0.8203, "n": 10803},
              "incidents": {"precision": 0.717, "ci95": [0.647, 0.777], "n": 180,
                            "gate": 0.80, "state": "below gate"}},
  "caveats": ["A checkpoint reading is what a channel reported, not an official count. ...",
              "`present` counts sightings; an empty presence block means nobody sighted them ..."],
  "as_of": "2026-09-23T15:58:00+00:00"
}
```

## 5. What the numbers mean — read this before building UI on them

* **A reading is a report, not a census.** "open" means a channel said so recently.
* **`unknown` is not `open`.** It means nobody reported recently. The single most
  dangerous thing a client can do is render it as all-clear.
* **`present` is a separate axis from flow.** Army/police/inspection/settlers is a
  count of *sightings*; an empty block means nobody looked, never that they are
  absent. `absent` is the stronger fact: somebody stood there and said so.
* **Timestamps are report times.** Incident `occurred_at` is when the channel
  posted (precision: hour), so "in this window" means reported in it.
* **`independent_sources` counts independence groups.** Channels that mirror each
  other count once, so a wire story reprinted five times is still one source.
* **Every subject carries its sample size and the precision it was measured at.**
  Today the checkpoint layer measures 0.8203 (n=10,803) and the incident
  classifier 0.717 against its 0.80 gate — which the payload says out loud. The
  answer to "is this accurate?" is the number, not a claim.
* **Non-events are honest.** `absent_types` lists incident types with no reports
  in the window; that is absence of evidence and is labelled as such.

## 6. Limits

* 300 MCP requests per minute per client IP (sliding window). HTTP `429` beyond it.
* A per-key daily quota; the reset is midnight UTC.
* Heaviest call measured: `insights` over 90 days / 25 km, ~1.3 s cold. Answers
  that re-aggregate the whole dataset are cached for up to 60 seconds, and `as_of`
  in the payload is when the answer was built, so its age is always visible.
* No account, no cookie, no tracking pixel, nothing to accept.

## 7. Privacy

* No PII is served. Place names, checkpoint states, road conditions, incident
  types — no names of people, no reporter identities, no locations of individuals.
* Caller IP is used only for rate limiting and is stored in a coarse bucket; the
  usage ledger records the tool, its arguments, the duration and whether it
  succeeded, rotated at a size cap.
* Keys are never written to disk in a response or to the log (the log scrubber
  redacts `?key=`).
* The server makes no outbound call to any third party on this path: the map
  router, the database and the API are all on the same host.

## 8. Attribution and licence

* Checkpoints and incidents are derived from public Telegram road-condition and
  news channels, processed into state — the served objects are the derived
  readings, not the channels' text.
* Gaza and West Bank casualty series are **Tech for Palestine's, Unlicense
  (public domain)**.
* The historical databank carries per-source terms: several sets are
  `commercial_use=false` and are **not** part of this release. `licenses` names
  each one's obligations, and `coverage` names each source.
* Attribution string to carry: *"Data: Palestine Data Platform, processed from
  public channel reports; Gaza and West Bank series via Tech for Palestine."*

## 9. Ten calls to try first

```bash
K=<key>; U=https://live-api.zaidlab.xyz/mcp
call() { curl -s -X POST "$U?key=$K" -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"$1\",\"arguments\":$2}}"; }

call coverage '{}'
call checkpoints_summary '{}'
call checkpoints_near '{"place":"نابلس","limit":10}'
call checkpoint_status '{"name":"حوارة"}'
call incidents_summary '{"hours":24}'
call incidents_near '{"place":"الخليل","hours":168,"limit":20}'
call insights '{"place":"رام الله","days":30,"radius_km":15}'
call can_i_travel '{"origin":"رام الله","destination":"نابلس"}'
call crossings '{}'
call weather_now '{}'
```

## 10. Known gaps, stated plainly

* The incident classifier is **below its own 0.80 gate**. The errors are
  concentrated in one class: obituaries, funerals and features being read as
  incident reports. Until that classifier ships (in progress), treat incident
  counts as a lower-confidence signal — which every incident payload says.
* Coverage is not uniform. `coverage` and `data_gaps` list the fields that are
  thin, stale or have never had a source at all. Some governorates are quieter
  than others because fewer channels report on them, not because less happens.
* A caller may see `unknown` far more than it expects. That is the system
  refusing to guess.
