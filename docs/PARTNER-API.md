# Partner API — live status for the West Bank

One server, two surfaces over the same data and the same code path:

* **MCP over HTTP** — `POST https://live-api.zaidlab.xyz/mcp` (JSON-RPC 2.0, stateless, no session to resume)
* **REST** — `https://live-api.zaidlab.xyz/v2/...` (same numbers, for callers without an MCP client)

16 tools (since 2026-09-24; 19 earlier names still answer as aliases for one
release, hidden from `tools/list` — §3 lists each one and the name that replaces
it). No tool files a report: an agent cannot submit one, ever, by design.
Call `about` first — it says what this system holds and, more usefully, what it
holds nothing for.

<!-- Rewritten 2026-09-25 against `serve/mcp_facades.py` (LISTED, ABSORBED) and
serve/mcp_oauth.py as they are on disk. Until then §3 and §9 taught the 28-name
surface the façades replaced, so a partner building from this page integrated
against names that are hidden and scheduled to stop answering. -->



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
partner gets. What differs is not access but redistribution: `news` returns an
excerpt of a channel's wording to every external caller (§8), because those
words are not ours to republish. It is
also printed in the `401` body, so anyone who finds the endpoint by themselves
can start without asking.

For anything real, ask us for your own key. One key per integration, so traffic
is attributable and a leaked key sent as a header or `?key=` is one revocation
rather than an outage (for OAuth connectors see the note below the flow).

A missing or unknown key returns `401` with the reason in the JSON-RPC error body.
The key file is re-read whenever it changes, so removing a key stops header and
`?key=` calls without a restart, and `?key=` is scrubbed from the server's
access log.

**Hosted clients (Claude, ChatGPT, and anything else that cannot hold a static
header) use OAuth instead**, per the MCP authorization spec. Point the connector
at `https://live-api.zaidlab.xyz/mcp` with no key and it will:

1. get a `401` carrying `WWW-Authenticate: Bearer resource_metadata="https://live-api.zaidlab.xyz/.well-known/oauth-protected-resource"`;
2. read `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server`;
3. register itself at `POST /register` (RFC 7591);
4. open `GET /authorize` — a page asking for your partner key, because this is a
   gate and not a formality;
5. exchange the resulting code at `POST /token` (grant `authorization_code`) for
   an access token. S256 is the only PKCE method accepted: send `code_challenge`
   with `code_challenge_method=S256` and the matching `code_verifier`.

An access token lasts 30 days (`expires_in` says so) and survives a redeploy.
A code lasts five minutes and is single-use: a replayed code is refused, and so
is one whose PKCE challenge the verifier does not match.

**What OAuth does not yet do, stated so you do not rely on it** (the code on
2026-09-25; closing these is PLAN §7 P1-C.4, and this paragraph changes when
it lands):

* removing a partner key stops that key's header calls at once, but does **not**
  revoke the OAuth tokens already issued with it;
* calls made with an OAuth token are not counted against the key's daily quota —
  the per-IP limit (§6) is their only ceiling;
* a refresh token is exchanged for a fresh pair whenever it is presented; there
  is no enforced 90-day refresh lifetime, and the used refresh token is not
  retired;
* PKCE is checked only when the client sent a challenge — a code issued without
  one exchanges without a verifier. Every hosted client we know sends one; send
  it.

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

The sixteen names `tools/list` returns, in the order it returns them. Every
tool that takes a place calls the argument `place` (Arabic or English); every
parameter is described and every default is declared in the schema, so
`tools/list` is the authoritative copy of this table.

| tool | what it answers | arguments (default) |
|---|---|---|
| `about` | what the system holds, what it holds nothing for, whether it is alive | `section` = overview · sources · fields · gaps · stream |
| `checkpoint_status` | one named checkpoint: flow, passable, who is present, age, per direction | `name` (required), `direction` (both) |
| `checkpoints` | checkpoints around a place, nearest first, with what is NOT known; no place = the West-Bank-wide picture | `place` or `lat`/`lon`, `direction` (both), `radius_km` (15), `limit` (6) |
| `can_i_travel` | every reasonable route from A to B, scored by the checkpoints on it | `origin`, `destination` (both required) |
| `incidents` | raids, settler attacks, closures, arrests, demolitions — each with its count of *independent* channels; no place = West-Bank-wide counts by type | `place` or `lat`/`lon`, `hours` (12 around a place, 24 for the summary), `radius_km` (25), `limit` (8) |
| `place` | one place in four views: profile · history · pattern (hour of day) · locate | `place` (required), `view` (profile), `days` (30; pattern uses 60), `state_kind` |
| `insights` | one reduction of a place over a window (below); `scope=governorates` ranks governorates instead | `place` or `lat`/`lon`, `days` (30), `radius_km` (15), `scope` (place), `state_kind` |
| `news` | the newest ingested messages, or with `text` a literal search; bodies excerpted for partners (§8) | `text`, `place`, `hours` (168, search mode), `limit` (8), `kind` = news · roads · all (news) |
| `weather_now` | conditions and advisories per governorate | `place` |
| `connectivity_now` | whether West Bank internet is reachable, measured externally by IODA | — |
| `fuel_prices` | the Petroleum Corporation's monthly maximum for the West Bank, confirmed only when two independent outlets agree and one names the Corporation | `product`, `history` (false) |
| `crossings` | Gaza and West Bank crossings: open · partial · closed · unknown, and which have no source at all | `place` |
| `databank` | the historical databank: no `category` lists what exists; `as_of` reconstructs a past day | `category`, `indicator`, `as_of`, `limit` (10) |
| `series` | one indicator against its own baseline, or two to six side by side in their own units | `indicators` (required), `place`, `days` (90) |
| `correlate` | concepts, indicator search, a pair correlation that refuses rather than mislead, or a scan | `a`+`b`, or `search`/`concept`, or `indicator`; see its schema |
| `licence` | what may be reused from here: per tool (`scope=tools`) or per data owner (`scope=sources`) | `scope` (tools), `source` |

**The 19 earlier names** still answer when called by name, for one release, and
are hidden from `tools/list`. Each is routed to the tool that replaced it and is
graded and rendered exactly as before; build against the right-hand column,
because the left one will stop answering (`unknown tool`) when the alias release
ends.

| earlier name | call instead |
|---|---|
| `coverage`, `data_gaps`, `stream_info` | `about` (`section=sources` · `gaps` · `stream`) |
| `licenses`, `licence_tools` | `licence` (`scope=sources` · `scope=tools`) |
| `checkpoints_near`, `checkpoints_summary` | `checkpoints` (with / without `place`) |
| `incidents_near`, `incidents_summary` | `incidents` (with / without `place`) |
| `place_profile`, `place_history`, `place_pattern`, `where_is` | `place` (`view=profile` · `history` · `pattern` · `locate`) |
| `latest_news`, `search` | `news` (without / with `text`) |
| `trend`, `compare` | `series` (one indicator / several, comma-separated) |
| `what_correlates_with` | `correlate` (`indicator=`) |
| `area_history` | `insights` (`scope=governorates`) |

### Reading a route verdict

The `verdict` is one of `likely_open`, `slow`, `unverified`, `unknown`,
`blocked`. `unverified` means nothing on the route is reported closed but we
could not see enough of the road to call it open — it is not a softer
`likely_open`.

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

The sample is a day older than the incident measurement it quotes: its
`quality.incidents` is round 7 (0.717). Today's payload carries round 8 — read
the block, never this page (§5).

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
  Incident answers carry a `precision` block: the hand-scored round, the
  classifier version it measured and the version now serving, the overall
  number with its interval and `n`, the gate, and the types below it. Quote that
  block, not a number from this page — pages go stale and the block is read
  from `ops/incident-precision.json` on every call. (For orientation only: round
  8, 2026-09-24, measured classifier 1.8.0 at 0.767 [0.693–0.827], n=150,
  against a 0.80 gate, with death and siege lowest at 0.60; 1.8.1 serves and is
  unmeasured until round 9.) The answer to "is this accurate?" is the number,
  not a claim.
* **Non-events are honest.** `absent_types` lists incident types with no reports
  in the window; that is absence of evidence and is labelled as such.

## 6. Limits

* 300 MCP requests per minute per client IP (sliding window). HTTP `429` beyond it.
* A per-key daily quota for keys sent as a header or `?key=`; the reset is
  midnight UTC. (OAuth tokens are not yet counted against it — §1.)
* Heaviest call measured: `insights` over 90 days / 25 km, ~1.3 s cold. Answers
  that re-aggregate the whole dataset are cached for up to 60 seconds, and `as_of`
  in the payload is when the answer was built, so its age is always visible.
* No account, no cookie, no tracking pixel, nothing to accept.

## 7. Privacy

OAuth adds nothing to the privacy surface: registration takes a client name and a
redirect URI, no personal data, and an issued token identifies an integration
rather than a person.

* No PII is served through MCP. Place names, checkpoint states, road conditions,
  incident types — no reporter identities, no locations of individuals. The one
  named-person record is deliberate and gated: the memorial roster of the
  identified dead is readable over REST only with `?memorial=true`
  (`/v2/databank/martyrs_snapshot_2023`), and no MCP tool asks for it.
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
* The historical databank carries per-source terms, and **every row it serves
  carries its own licence, `commercial_use` and `redistribution` grade**. Rows
  from sources that grant no redistribution right (HaMoked, Addameer, Peace Now,
  Good Shepherd, OCHA's UN-terms sets) or that have granted nothing yet (IODA,
  All Rights Reserved with a letter pending; the heritage register, terms
  unread) ARE served to a query, with that grade attached: a credited
  fact answering a question is reporting, not redistribution (migration 066).
  They are excluded from bulk export (`databank_bulk`, the open-data release),
  and they are not yours to republish. `licence(scope=sources)` names each
  source's obligation; `about(section=sources)` names each source.
* Attribution string to carry: *"Data: Palestine Data Platform, processed from
  public channel reports; Gaza and West Bank series via Tech for Palestine."*

### What you may carry away, per tool

Call **`licence`** (default `scope=tools`, or `GET /v2/licence/tools`) before
you republish anything from here. It grades every public tool and tells you
which of four things you are holding. Grades are read from the source register
at call time, so that table is authoritative and this paragraph is only the
shape of it. A façade is graded as the tool that actually answered it
(`licence.via` names that tool), so `checkpoints` with a place and without one
can carry different obligations.

| tier | what it means |
|---|---|
| `full` | our own derived observation — the live tracker. Yours to carry, with attribution. |
| `share-alike` (still `full`) | reached an ODbL row (OpenStreetMap fuel stations). Sellable, but a derived **database** must be released under ODbL. |
| `excerpt` | somebody else's **wording**. See below. |
| `filtered` | databank rows, each carrying its own licence and grade. Nothing is removed from a query answer; what you may carry away is decided per row. |
| `cited_fact_only` | a third party's measurement we hold no redistribution right to (IODA connectivity). Cite it; do not republish it. |

**`news` returns an excerpt, not the message** (in both modes: newest and
`text` search). Every channel feeding it is graded `no-redistribution` — the words are the channels' own
copyright, and a key we issue cannot grant a licence we do not hold. You get the
first 250 characters, the source name and the timestamp, which is a citation;
each item says `excerpted: true` and `full_text_chars`, and the payload's
`licence.refused` states how many were cut and why. Nothing is silently short.
If your product needs full bodies, that is a permission conversation with the
channels, not a key change.

A grade says what you may **redistribute**, not what you may **read**.
Everything on this server is readable; the cut is only on carrying it away.

## 9. Ten calls to try first

Run `docs/try-ten-calls.sh` with your staging key and you have all ten in one
pass — it prints each answer, the licence tier of what it just received, and the
round-trip time, and it never echoes the key:

```bash
THAURA_KEY=pv2_... ./docs/try-ten-calls.sh
```

The same ten calls by hand, if you would rather see the wire format:

```bash
K=<key>; U=https://live-api.zaidlab.xyz/mcp
call() { curl -s -X POST "$U?key=$K" -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"$1\",\"arguments\":$2}}"; }

call about '{}'
call checkpoints '{}'
call checkpoints '{"place":"نابلس","limit":10}'
call checkpoint_status '{"name":"حوارة"}'
call incidents '{"hours":24}'
call incidents '{"place":"الخليل","hours":168,"limit":20}'
call insights '{"place":"رام الله","days":30,"radius_km":15}'
call can_i_travel '{"origin":"رام الله","destination":"نابلس"}'
call crossings '{}'
call weather_now '{}'
```

The same ten questions the script and this list asked before 2026-09-25, under
the names `tools/list` now returns; the earlier names (`coverage`,
`checkpoints_summary`, `checkpoints_near`, `incidents_summary`,
`incidents_near`) still answer for one release but are not what to build on.

## 10. Known gaps, stated plainly

* The incident classifier is **below its own 0.80 gate** (round 8, 2026-09-24:
  0.767 on 1.8.0). Most errors are one class: a message that is not an incident
  report at all — a funeral notice, a feature, a retrospective — read as one
  (42 of the 59 errors across all 198 claims scored in round 8, adversarial
  ones included). The version serving now, 1.8.1, is
  unmeasured until round 9. Treat incident counts as a lower-confidence signal,
  which every incident payload's `precision` block says.
* Coverage is not uniform. `about` (`section=fields`, `section=gaps`) lists the fields that are
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
`jobs_ok/jobs_total`, `feeds_ok/feeds_total`, `feed_age_minutes` — and it goes
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
