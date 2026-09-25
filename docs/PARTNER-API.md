# Partner API — live status for the West Bank

One server, two surfaces over the same data and the same code path:

* **MCP over HTTP** — `POST https://live-api.zaidlab.xyz/mcp` (JSON-RPC 2.0, stateless, no session to resume)
* **REST** — `https://live-api.zaidlab.xyz/v2/...` (same numbers, for callers without an MCP client)

16 tools (since 2026-09-24; the 28 earlier names still answer as aliases for one
release, off the menu). No write path: an agent cannot file a report, ever, by design.
Call `about` first — it says what this system holds and, more usefully, what it
holds nothing for.

---

## 1. Authentication

**Testing? There is a published key. No signup, no email.**

    pv2_1fd90b4e9ca4f43149a92d5198479d78

Use it as a header, or appended to the url if your client's UI takes only a url:

    Authorization: Bearer pv2_1fd90b4e9ca4f43149a92d5198479d78
    X-Api-Key: pv2_1fd90b4e9ca4f43149a92d5198479d78
    https://live-api.zaidlab.xyz/mcp?key=pv2_1fd90b4e9ca4f43149a92d5198479d78

It is shared, so it carries a ceiling: **5,000 calls a day across everyone using
it**, reset at midnight UTC. Hit that and you get `429` until the day rolls over.
The data behind it is the full read surface — 16 tools, and every tool a paying
partner gets. What differs is not access but redistribution: `latest_news` and
`search` return an excerpt of a channel's wording to every external caller (§8),
because those words are not ours to republish. It is
also printed in the `401` body, so anyone who finds the endpoint by themselves
can start without asking.

For anything real, ask us for your own key. One key per integration, so traffic
is attributable and a leak is one revocation rather than an outage.

A missing or unknown key returns `401` with the reason in the JSON-RPC error body.
Keys are read from a file on every request, so revocation takes effect without a
restart, and `?key=` is scrubbed from the server's access log.

**Hosted clients (Claude, ChatGPT, and anything else that cannot hold a static
header) use OAuth instead**, per the MCP authorization spec. Point the connector
at `https://live-api.zaidlab.xyz/mcp` with no key and it will:

1. get a `401` carrying `WWW-Authenticate: Bearer resource_metadata=".../‌.well-known/oauth-protected-resource"`;
2. read `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server`;
3. register itself at `POST /register` (RFC 7591);
4. open `GET /authorize` — a page asking for your partner key, because this is a
   gate and not a formality;
5. exchange the resulting code at `POST /token` (authorization code + PKCE S256)
   for an access token.

Tokens last 30 days, refresh tokens 90, and both survive a redeploy. A token
dies with its partner key (remove the key and every token issued under it is
refused on the next call) and spends that key's daily quota. Refresh tokens
rotate on use and are bound to the client that obtained them. PKCE is
required. Code exchange is single-use: a replayed code is refused, and so is
one presented with the wrong PKCE verifier.

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

Sixteen public names, generated from the server's own `tools/list` (`ops/gen_partner_tools.py`; a required argument is starred, a declared default is shown). Older names still answer for one release but are not on the menu.

**`about`** — What this system is, what it holds, what it holds NOTHING for, and whether it is alive — call this first. overview (default) is a short reduction; section=sources|fields|gaps|stream returns the full detail. `no source` means nothing measures a field, ever; `unknown` means nobody credible reported recently.
  <br>arguments: `section`="overview"

**`checkpoint_status`** — Is a named checkpoint open right now? Returns flow (open/congested/slow/closed), whether it is passable, who is present (army, police, settlers, inspection) as a SEPARATE fact, and how old the reading is. Inbound and outbound can differ and are both reported.
  <br>arguments: `name`*, `direction`="both"

**`checkpoints`** — Checkpoints around a place, nearest first, with what is known and how much is NOT known; with no place, the West-Bank-wide picture (open / closed / congested / no recent reading, and which are closed now). For ONE named checkpoint use checkpoint_status.
  <br>arguments: `place`, `lat`, `lon`, `direction`="both", `radius_km`=15, `limit`=6

**`can_i_travel`** — Can I get from A to B right now? Returns every reasonable route scored by the checkpoints ON it — in travel order, each with its age — plus alternatives when one is blocked. Use this instead of checking checkpoints one by one: a journey needs EVERY checkpoint passable, so one confirmed closure blocks the route. Checkpoints nobody has reported recently never block and are always named.
  <br>arguments: `origin`*, `destination`*

**`incidents`** — Located incidents — raids, settler attacks, closures, arrests, demolitions — each with how many INDEPENDENT channels reported it. Around a place when `place` (or lat/lon) is given; otherwise West-Bank-wide counts by type and the worst-affected places. Times are when a channel POSTED, precise to the hour.
  <br>arguments: `place`, `lat`, `lon`, `hours`=12, `radius_km`=25, `limit`=8

**`place`** — One place, four views. profile (default): everything both tiers hold — live checkpoint state, recent history, hourly pattern, nearby incidents. history: daily report counts and what they said. pattern: what USUALLY happens by hour of day. locate: the coordinates. A town and the checkpoint named after it are different rows; the answer says which it covers.
  <br>arguments: `place`*, `view`="profile", `days`=30, `state_kind`

**`insights`** — ONE reduction of a place over a window: checkpoint status distribution around it, which checkpoints actually changed, the busiest hours, incident counts by type, and the measured precision of each subject. Use it for 'what was happening around X last month' instead of fetching rows and averaging them. scope=governorates: totals per governorate instead of one place.
  <br>arguments: `place`, `lat`, `lon`, `days`=30, `radius_km`=15, `scope`="place", `state_kind`

**`news`** — The newest ingested messages (Telegram channels and RSS), optionally filtered by area — or, with `text`, a literal search for the words somebody used. Bodies are excerpted to 250 characters for partners: the channels own their wording.
  <br>arguments: `text`, `place`, `hours`=168, `limit`=8, `kind`

**`weather_now`** — Weather conditions and advisories per West Bank governorate — heat waves, storms, frost. Optionally filter to one governorate. Useful alongside movement answers: 43C changes what a checkpoint queue means.
  <br>arguments: `place`

**`connectivity_now`** — Whether West Bank internet is reachable, measured externally by IODA (routing table, active probes, darknet telescope) rather than reported by anyone. Answers 'is the internet down' when nobody can post that it is.
  <br>arguments: no arguments

**`fuel_prices`** — Official West Bank fuel prices (petrol 95/98, diesel, kerosene, cooking-gas cylinders): the Petroleum Corporation's monthly MAXIMUM consumer price, not a pump price and not Gaza's. A price is given only when two independent outlets agree; otherwise the answer says it is unconfirmed, conflicting, or that this month's list has not been read yet. history=true lists every confirmed price so far.
  <br>arguments: `product`, `history`=false

**`crossings`** — Status of Gaza and West Bank crossings (Rafah, Kerem Shalom, Erez, Zikim, Kissufim, Allenby / King Hussein…): open / partial / closed / unknown, where `partial` is NOT open. A crossing nobody reports reads `unknown`, and the answer says which crossings have no source at all — most Gaza crossings today.
  <br>arguments: `place`

**`databank`** — Historical databank (200k+ rows, 20 categories: prisoners, demolitions, food prices, funding, martyrs roster…) with per-source licensing. No `category` lists what exists; `as_of` (YYYY-MM-DD) reconstructs a past day's answer.
  <br>arguments: `category`, `indicator`, `as_of`, `limit`=10

**`series`** — A databank series over time. One indicator: is it above or below its own baseline (the last three readings against the median of the rest), and how old the newest reading is. Two to six comma-separated indicators: side by side in their own units over the window they share — nothing is rescaled onto one axis. Find indicator strings with correlate(search=...).
  <br>arguments: `indicators`*, `place`, `days`=90

**`correlate`** — Concepts, indicator search, correlation and scanning over the databank. No arguments: the concepts held. `search`/`concept`: find an indicator string. `a` and `b`: correlate two series — REFUSES rather than returning a misleading number (two cumulative tolls correlate at ~1.0 and that measures time). `indicator` alone: SCAN for series that move with it; results are hypotheses to check pairwise, never findings, and the answer says how many tests it ran.
  <br>arguments: `a`, `b`, `search`, `concept`, `indicator`, `place`, `place_id`, `candidates`=40, `max_lag`, `allow_same_concept`=false

**`licence`** — What may be REUSED from here, and how. scope=tools (default): what each public tool may hand a commercial partner — whole, excerpt, per-row, or cited fact only. scope=sources: who owns the databank's rows, each licence's obligation, attribution text, and which publishers' terms nobody has read yet. Call it before republishing anything.
  <br>arguments: `scope`="tools", `source`

### Reading a route verdict

`can_i_travel` returns a verdict per route, and **the verdict does not speak for
parts of the road nobody watched**. Read it with its coverage block:

    "coverage": {
      "distance_km": 53.3,
      "checkpoints_on_route": 8,
      "coverage_fraction": 0.5,
      "covered_km": 26.5,
      "longest_gap_km": 26.8,
      "longest_gap_from_km": 0.0,
      "longest_gap_to_km": 26.8,
      "verdict_covers": "part of the route"
    }

Checkpoints are matched to a route by proximity to its geometry, and on
Ramallah–Nablus the first one sits 26.9 km into a 53 km drive. The verdict is
therefore a claim about the whole journey while the evidence covers half of it,
so `coverage` names the blind stretch in kilometres and the `answer` sentences say
it out loud in both languages. `verdict_covers` is `the whole route` or `part of
the route`; treat the latter as "not verified here", not as "clear".

Also returned:

* `passes` — the towns the route actually goes through, in travel order, one per
  equal slice of the route, each with `km` along and `off_m` lateral offset. This
  is what lets a reader judge the route rather than trust a word; it is sampled
  rather than exhaustive (the route passes 228 named places within 1.5 km).
* `near_misses` — closures and congestion just outside the scored corridor, with
  distance and age. Named in the `answer`, never promoted onto the route: whether
  a checkpoint 2 km off the alignment is on somebody's journey is their call.
* `checkpoints` — in travel order, each with its flow, age and sources.

Each entry in `routes` carries its own `coverage`, so a longer alternate can be
the better-watched one. Routes rank by verdict then by time, never by how much we
happen to know about them.

**Conditions** — `weather_now`, `connectivity_now`, `fuel_prices` (the Petroleum
Corporation's monthly maximum for the West Bank, confirmed only when two
independent outlets agree and one names the Corporation), `latest_news`,
`search`, `stream_info`.

**Meta** — `about` (coverage, gaps, stream), `place`, `licence` (what each tool above
may hand you, and in what form — see §8).

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

OAuth adds nothing to the privacy surface: registration takes a client name and a
redirect URI, no personal data, and an issued token identifies an integration
rather than a person.

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
  `commercial_use=false` and are **not** part of this release. `licence`
  (`scope=sources`) names each one's obligations, and `about` names each source.
* Attribution string to carry: *"Data: Palestine Data Platform, processed from
  public channel reports; Gaza and West Bank series via Tech for Palestine."*

### What you may carry away, per tool

Call **`licence`** (`scope=tools`, or `GET /v2/licence/tools`) before you republish
anything from here. It grades every public tool and tells you which of four
things you are holding. Grades are read from the source register at call time,
so that table is authoritative and this paragraph is only the shape of it.

| tier | what it means |
|---|---|
| `full` | our own derived observation — the live tracker. Yours to carry, with attribution. |
| `share-alike` (still `full`) | reached an ODbL row (OpenStreetMap fuel stations). Sellable, but a derived **database** must be released under ODbL. |
| `excerpt` | somebody else's **wording**. See below. |
| `filtered` | databank rows, each carrying its own licence. |
| `cited_fact_only` | a third party's measurement we hold no redistribution right to (IODA connectivity). Cite it; do not republish it. |

**`latest_news` and `search` return an excerpt, not the message.** Every channel
feeding them is graded `no-redistribution` — the words are the channels' own
copyright, and a key we issue cannot grant a licence we do not hold. You get the
first 250 characters, the source name and the timestamp, which is a citation;
each item says `excerpted: true` and `full_text_chars`, and the payload's
`licence.refused` states how many were cut and why. Nothing is silently short.
If your product needs full bodies, that is a permission conversation with the
channels, not a key change.

A grade says what you may **redistribute**, not what you may **read**.
Everything on this server is readable; the cut is only on carrying it away.

## 9. Twelve questions to try first

Run `docs/try-twelve.sh` with your key and you have the twelve canonical
questions the release is measured on (PLAN §10) in one pass — each answer in
both languages, the licence tier of what you received, and the round-trip
time; the key is never echoed:

```bash
THAURA_KEY=pv2_... ./docs/try-twelve.sh
```

The same twelve by hand, if you would rather see the wire format:

```bash
K=<key>; U=https://live-api.zaidlab.xyz/mcp
call() { curl -s -X POST "$U" -H "X-Api-Key: $K" -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"$1\",\"arguments\":$2}}"; }

call about '{}'
call checkpoint_status '{"name":"قلنديا"}'
call checkpoint_status '{"name":"Huwara"}'
call can_i_travel '{"origin":"رام الله","destination":"نابلس"}'
call can_i_travel '{"origin":"Nablus","destination":"Jenin"}'
call incidents '{"place":"رام الله","hours":12}'
call insights '{"place":"نابلس","days":7}'
call crossings '{"place":"رفح"}'
call fuel_prices '{}'
call databank '{"category":"casualties","limit":3}'
call databank '{"category":"demolitions","limit":5}'
call place '{"place":"حوارة","view":"history","days":30}'
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

## 11. Availability, and what to do when something looks wrong

**Our commitment: 99% monthly availability of `POST /mcp` and the read routes,
excluding the two carve-outs below.** Plainly: in a month, up to roughly seven
hours of unavailability is inside the commitment. A number we can hold is worth
more to you than one that sounds better.

Excluded, because they are outside anything this system can promise:

* **The host's own power or connectivity.** This runs on one machine in a home
  lab in the West Bank. A power cut, a PSU failure or a local internet outage
  takes the API with it, and we cannot promise availability our electricity
  supply does not have.
* **Planned maintenance announced at least 24 hours ahead** on the status
  endpoint below.

Beyond the number, the commitment is that failure is **visible, not silent**.
`GET /health` returns the machine's own verdict — `status`, `faults_total`,
`jobs_ok/jobs_total`, `feeds_ok/feeds_total`, `families` (ok/faults per watchdog family) — and it goes
`degraded` rather than staying `ok` when the watchdog has faults. A halted
backfill or a stop-the-line fault is reported there rather than discovered by you.

**When a call looks wrong, email `zaidsalem@live.com` with the exact request, the
exact response, and the UTC time.** The three reports that help most:

* a **wrong answer** — the most valuable report there is. Include the answer text
  and, if you can, the source you believe contradicts it;
* a **refusal you disagree with** — include `licence.refused` or `refused`
  verbatim: those fields state why the system declined, and a wrong refusal is a
  bug worth fixing;
* a **performance** number you cannot live with — include the call and the
  timing, since our own figures are measured warm and yours may not be.

We will answer a report with the mechanism, not an apology.
