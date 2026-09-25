# Plan 10 · External feed parsers (fuel prices, MoH Gaza, power, weather, connectivity, fires)

Phase 4 — Silent failures: ingestion, feeds, operations. Read `00-README.md` first (setup, rules, the per-task loop).

## Scope

- **Files you may edit:** `cascade/fuel_price.py`, `cascade/fuel_image.py`, `cascade/moh_gaza.py`, `cascade/palhub_fuel.py`, `ingest/sources/fuel_prices.py`, `ingest/sources/weather.py`, `ingest/sources/connectivity.py`, `ingest/sources/power.py`, `ingest/sources/fires.py`, `ingest/sources/osm_fuel.py`, `ingest/sources/moh_gaza.py`, `ingest/sources/palhub_fuel_image.py`, `tests/test_fuel_price.py`, `tests/test_fuel_image.py`, `tests/test_power.py`, `tests/test_conflict_gaza.py`, `tests/test_feeds_hardening.py`
- **Tests to run after every task:** `tests/test_fuel_price.py tests/test_fuel_image.py tests/test_power.py tests/test_conflict_gaza.py tests/test_feeds_hardening.py` (with the local DB sourced), then the full suite once at the end of the file.
- **Area rules:** Numbers are facts: decimal commas, Arabic-Indic digits, cumulative vs daily, revisions, unknown sections must never be filed under another tier. A scheduled future power cut is never served as active; a cut ends when announced. One outlet cannot corroborate itself. MoH ingest must not overwrite a revised value (supersede, keep the old in attrs).

- Confirmed tasks: 7 · verify-first tasks: 18 · refuted (skip): 0

## A. Confirmed tasks (independently verified — do these first, in order)

### FEEDS-01 · F036 · high · accuracy
**One outlet can self-corroborate a fuel price: its RSS item is a claim and its page is a web unit**

- **Where:** `ingest/sources/fuel_prices.py:233`
- **What goes wrong:** Quds News publishes a single article whose RSS description carries the price list (many Arabic feeds ship the full body). The claim path reads it under src:<rss_qudsn>, the web path reads the same article under web:qudsn.co: units=2, named_units>=1, distinct_texts=2 → believed with no second outlet at all. Any misread in that one article (see the comma-decimal finding) is served as the official price. The belief rule the module docstring calls 'the defence none of those survive' is bypassed for two of the ten feeds.
- **Fix:** Derive the independence unit from the publisher, not the transport: a small table {rss_qudsn: 'qudsn.co', rss_palinfo: 'palinfo.com', tg_<channel>: '<domain>'} applied in _row (outlet → unit) so both readings collapse to one unit; or exclude from claim_rows any claim whose source key is an rss_* feed that is also in FEEDS. Add a unit test that a web row and a claim row from the same outlet produce the same independence_unit.
- **Evidence (audited code):**
```
FEEDS includes "https://qudsn.co/rss" and "https://palinfo.com/feed/" (:67-68) while the comment at :55-57 says both are already read by rss_news. rss_news stores every item as a claim with raw_text = title + description (ingest/sources/rss_news.py:141-171, source keys rss_qudsn / rss_palinfo). claim_rows (:230-244) reads ANY claim matching شيكل + a fuel word and sets the unit to `COALESCE(s.independence_group, 'src:' || s.source_id::text)`, while read_article sets `unit=f"web:{domain}"` (:177). fuel_price_believed needs `units >= 2` (073:71) and a stated pairing gets text_key `'unit:' || independence_unit` (073:47-49), so the two readings of one article are two distinct texts.
```
- **Verifier's check:** Confirmed. FEEDS includes qudsn.co/rss and palinfo.com/feed (fuel_prices.py:67-68). rss_news.py:56-59 stores those same feeds as claims under rss_qudsn/rss_palinfo, with raw_text = title + '. ' + summary (:141-171). claim_rows (:230-244) filters on the shekel and fuel words only, never on source, and gives the claim the unit COALESCE(independence_group,'src:'||id). No learner ever sets independence_group for rss_* sources: learn/source_independence.py clusters on checkpoint_flow co-observations. read_article gives the page unit 'web:'+domain (:177). In 073:47-49 a stated pairing gets text_key …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### FEEDS-02 · F037 · high · safety
**A power cut keeps being served for ~22 hours after its announced end**

- **Where:** `ingest/sources/power.py:317`
- **What goes wrong:** Notice 4878: cut 08:30–13:30 on 2026-09-01. The last assertion lands at 13:25; from 13:30 to about 11:30 the next day /v2/services still answers 'power cut active in قرية تل' (age growing, staleness 'live' then 'recent'), which is the stale-value-in-confident-clothes failure the module docstring says it exists to avoid.
- **Fix:** When `window and window[1] < now` and the last observation for the place is a 'cut' assertion, write a `'normal'`/`'restored'` assertion at window_end (observed_at = window_end) once; alternatively let the serving query treat attrs.window_end < now() as unknown/ended. Test: parse_window + a fake clock → after the window one restored row exists and no further cut rows.
- **Evidence (audited code):**
```
Inside the window a 'cut' assertion is written on every 15-minute tick (:284, :323-334); outside it `if not active: continue` (:317) writes nothing, and nothing writes a 'restored'/'normal' observation at window_end. state_serving turns a reading to 'unknown' only when confidence < floor, the band is 'expired' (8 half-lives = 96 h) or age > max_assert (48 h for power, 036) (026:23-25). With base 0.9, half-life 12 h and floor 0.25 the last in-window assertion stays asserted for 12·log2(0.9/0.25) ≈ 22 h. /v2/services shows it as power_cuts_active (serve/app.py:653) — the window_end is in attrs but the value says cut.
```
- **Verifier's check:** Confirmed. Inside the window a 'cut' assertion is written on every tick (:323-334). After the window, 'if not active: continue' (:317) writes nothing, and nothing anywhere reads window_end except the /v2/services payload (grep: app.py:661-662 only). Power config: half-life 43200 s and floor 0.25 (006:35), max_assert 48 h (036), no place_state_cadence or state_value_decay rows (the cadence writer covers checkpoint kinds only). state_serving (026) therefore keeps the value 'cut' until 0.9*0.5^(t/12h) < 0.25, which is t ≈ 22.2 h. With crowd-refresh's 0.85 base it is about 21 h. Crowd has 0 submit …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### FEEDS-03 · F038 · high · safety
**power.py's state_current rebuild ignores modality, so a future scheduled cut is served as active**

- **Where:** `ingest/sources/power.py:342`
- **What goes wrong:** Sept 2: NEDCO posts a notice for قرية تل on Sept 5 (scheduled row, observed_at Sept 2 10:00). Sept 3 09:00: a real cut in نابلس is active, `written`=1, the rebuild runs over every place: for قرية تل the newest observation is the scheduled row → state_current = cut@Sept 2 10:00 → /v2/services reports a live power cut in قرية تل until ~Sept 3 08:00 on a day with no cut, with window_start in the future in the same payload.
- **Fix:** Add `AND modality = 'assertion'` to the rebuild's WHERE (mirroring belief.py), or better delete the private rebuild and call `resolve.belief.refresh([STATE_KIND], conn=conn)` as the other loaders do (DECISIONS 2026-08-01 says belief.py is the one implementation). Add a SQL gate test: no state_current power row whose newest observation is 'scheduled'.
- **Evidence (audited code):**
```
The announcement is inserted with value 'cut', modality 'scheduled', observed_at = discovery time (:298-315). When any active cut was written (`if stats["written"]`, :336) the rebuild runs `SELECT DISTINCT ON (place_id, state_kind) ... FROM state_observation WHERE state_kind = %s ORDER BY place_id, state_kind, observed_at DESC` (:342-346) with no modality filter, and upserts `WHERE EXCLUDED.observed_at >= state_current.observed_at` (:351). resolve/belief.py's REFRESH_SQL (crowd refresh every 2 min) only counts `modality = 'assertion'` (:120) and has the same forward-only guard (:212), so it cannot undo the promotion. /v2/services lists every power row with value <> 'unknown' as power_cuts_ac …
```
- **Verifier's check:** Confirmed. The rebuild at power.py:338-351 is SELECT DISTINCT ON (place_id,state_kind) ... WHERE state_kind=%s ORDER BY observed_at DESC, with no modality filter. It runs over every place whenever stats['written'] is non-zero (:336). Scheduled rows are inserted with observed_at=now at discovery (:298-315). In a throwaway Postgres I ran the exact SQL extracted from power.py: a place with only a 'scheduled' row got state_current value 'cut'. belief.REFRESH_SQL, which ops/crowd-refresh.sh runs over power, reads only assertions (:112-120) and upserts with a forward-only guard (:212), so it cannot …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### FEEDS-04 · F073 · high · safety
**power.py rebuilds state_current from 'scheduled' rows: a future announced cut is served as an active cut**

- **Where:** `ingest/sources/power.py:345`
- **What goes wrong:** Run at 10:00: NEDCO index lists a cut for قرية X scheduled for tomorrow 08:00-14:00 (window parsed, not active) and a cut for Y active now. X gets a 'scheduled' row with observed_at=10:00, value 'cut'; Y gets an 'assertion' row; stats['written']=1 triggers the rebuild; for X the newest power observation is the scheduled row, so state_current(X,power)='cut', base_confidence 0.9, observed_at 10:00. state_serving (power half-life 12h, max_assert 48h) serves value='cut'; /v2/services (app.py:642-653 `WHERE s.state_kind='power' AND s.value <> 'unknown'`) lists X under power_cuts_active with tomorrow's window in attrs, for up to 48h, and the MCP conditions façade relays it. A user in X is told the power is cut now.
- **Fix:** Add `AND modality = 'assertion'` to the rebuild's FROM clause (and to the identical rebuilds in weather.py:218, connectivity.py:169, news_incidents.py:383-384), or delete these four private rebuilds and call resolve.belief.refresh([STATE_KIND]) as checkpoints.py and crowd-refresh do. Add a gate to test_gate2 (or a new test_gate_belief.sql): no state_current row for ANY kind whose (place_id,state_kind,direction,observed_at,source_id) lacks a modality='assertion' observation — G2.4 today restricts itself to five checkpoint kinds (tests/test_gate2_checkpoints.sql:62).
- **Evidence (audited code):**
```
power.py:302 inserts the announcement with observed_at = now: `SELECT %s,%s,'cut',%s,%s,%s,0.9,'both',false,'scheduled',%s` (params `(res.place_id, STATE_KIND, title[:200], now, source_id, ...)`, now = datetime.now(timezone.utc) at :262). Then :336-351: `if stats["written"] and not dry_run: INSERT INTO state_current ... SELECT DISTINCT ON (place_id, state_kind) place_id, state_kind, 'both', value, observed_at, source_id, confidence, 1, 0, now() FROM state_observation WHERE state_kind = %s ORDER BY place_id, state_kind, observed_at DESC ON CONFLICT ... WHERE EXCLUDED.observed_at >= state_current.observed_at` — no `modality = 'assertion'` predicate. Migration 040:8-10 claims the opposite: `exc …
```
- **Verifier's check:** Confirmed. power.py:296-312 inserts every notice with a parsed window as modality='scheduled', value 'cut', observed_at=now (first sight, :261), whatever the window is. Whenever any notice in the run is active (stats['written']>0), the rebuild at :336-351 runs `DISTINCT ON (place_id,state_kind) ... FROM state_observation WHERE state_kind=%s ORDER BY ... observed_at DESC` with no modality predicate (line 345). I replayed the repo's own SQL, extracted from power.py and resolve/belief.py, against a throwaway Postgres 16. A place that has only a scheduled row becomes state_current=('cut', 0.9). be …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### FEEDS-05 · F174 · medium · accuracy
**A comma decimal ('8,15 شيكل') is split as a clause boundary and the tail reads as a wrong price**

- **Where:** `cascade/fuel_price.py:230`
- **What goes wrong:** An outlet that writes decimals with a comma (or a copy editor who uses the Arabic comma) publishes the list; the reader stores diesel = 15.0 as a stated reading. With the self-corroboration hole above, or two outlets carrying the same wire text, it is believed and served as 15 ILS/L; a rival correct reading with two units only turns it into 'conflicting' (price withheld).
- **Fix:** In _clauses, never split on a comma that sits between two digits: use `re.split(r"(?<!\d)[،,](?!\d)|[؛;*•]|\s-\s|:\s(?=\D)", sentence)`, and normalise `(?<=\d)[،,](?=\d{1,2}\b)` to '.' in normalise(). Add the two strings above to tests/test_fuel_price.py expecting {'gasoline_95': 8.15, 'diesel': 8.39}.
- **Evidence (audited code):**
```
_clauses splits on `[،,؛;*•]` (:230) before _PRICE is applied, although _PRICE claims to accept `[.,]` as the decimal separator (:119) and read_prices does `.replace(",", ".")` (:277). Ran the parser on 'أعلنت الهيئة العامة للبترول ... اعتبارا من 1 أيلول 2026: البنزين 95 بسعر 8,15 شيكلا والسولار 8,39 شيكلا.' → verdict=prices, prices={'diesel': 15.0}; the Arabic-comma form '8،15' gives the same {'diesel': 15.0}. BOUNDS diesel is (3, 15) so 15.0 passes (:290), and the pairing is single-product/single-value so evidence.inferred=False.
```
- **Verifier's check:** Reproduced with cascade/fuel_price.parse. '...البنزين 95 بسعر 8,15 شيكلا والسولار 8,39 شيكلا' gives verdict=prices, {'diesel': 15.0}, evidence clause '15 شيكلا والسولار 8', inferred=False. The Arabic-comma form '8،15' gives the same result, while the dot form gives the correct {8.15, 8.39}. Cause: _clauses (:230) splits on [،,] before _PRICE (:119) and the replace(',', '.') at :277 ever see the number. BOUNDS diesel (3,15) is inclusive (:290). Limits on the trigger: single-product comma forms are refused (no_prices), and the misread needs a fraction of .03-.15 followed by a second product. 8.1 …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### FEEDS-06 · F176 · medium · accuracy
**MoH cascade parser files an unknown section's totals under the previous tier (the 72,274-in-one-day class)**

- **Where:** `cascade/moh_gaza.py:127`
- **What goes wrong:** Every archived 2025 bulletin with a 'منذ استئناف' block (the form the Ministry used from March to October 2025), and any future bulletin whose new section wording is not in SECTIONS, produces a gaza.moh.injuries.daily (or deaths.daily, when the 24 h line is spelled 'شهيدان') row carrying a running total. PLAN §7 P1 plans to give gaza_moh_daily a stable id and serve it; at that moment the databank publishes a catastrophic daily figure, the exact artifact DECISIONS 2026-08-08 records.
- **Fix:** Reset `current = None` on any line that looks like a section header (starts with 🔴/⭕ or contains 'منذ' and ends with ':') but matched no known tier, and log it to `rejected`; add 'الحصيلة التراكمية' and 'منذ استئناف' (as its own tier, not emitted) to SECTIONS; read value-first and spelled forms or, better, replace this parser with analyst/organ_c.read (which handles all of these). Add the three bulletins above to a test asserting no daily value ≥ 1,000.
- **Evidence (audited code):**
```
The tier is switched only by the three SECTIONS regexes (:60-68); any other header line falls through `if current is None: continue` (:133) with `current` still the previous tier, and `setdefault` (:148) then accepts a measure the previous tier lacked. Ran parse() on a bulletin with a daily block ('عدد الشهداء 7 شهداء') followed by '🔴 منذ استئناف العدوان في 18 مارس 2025: إجمالي عدد الشهداء: 5,000 / إجمالي عدد الإصابات: 16,000' → tiers = {'daily': {'deaths': 7, 'injuries': 16000}, ...}: 16,000 injuries recorded as ONE DAY. The same run showed value-first lines ('شهيدان', '5 إصابات') and the 'الحصيلة التراكمية' header (both measured by analyst/organ_c.py:21-34 as real bulletin forms) are not r …
```
- **Verifier's check:** The mechanism is confirmed: an unrecognised header line leaves `current` unchanged (moh_gaza.py:126-134), and setdefault (:148) then fills a measure the previous tier lacked. The finding's synthetic bulletin gives daily {'deaths':7,'injuries':16000}. A value-first daily block followed by an unknown header gives daily {5000,16000}. I also ran the parser on the 9 real 2026 bulletins in tests/test_organ_c.py. None mis-tiers, because their headers are recognised. The daily tier is read in only 2 of 9, because value-first lines like '- 5 شهداء' are dropped, as the finding says. So the real-data tri …
- **Already in the release plan:** PLAN §4 R4 (gaza_moh_daily 1,248 rows held, served nowhere) · §7 P1-B.1 (gaza_moh_daily given a stable id) · §4 R5 / §7 P2-A.1 (organ C wired). The mis-tiering itself is not named
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### FEEDS-07 · F182 · medium · data-integrity
**MoH ingest overwrites revised values and clobbers reported_at on every hourly run**

- **Where:** `ingest/sources/moh_gaza.py:92`
- **What goes wrong:** The Ministry posts a corrected bulletin later the same day: the first value is overwritten with no trace, violating HANDOFF §1 rule 2 ('nothing is deleted or overwritten; corrections supersede') and CLAUDE.md's 'a data fix keeps the old value in attrs'. Independently, after the second hourly run every gaza_moh_daily row's reported_at equals the last run time, so 'when did the Ministry say this' is gone for all ~1,248 rows.
- **Fix:** Keep a cursor (ingest_seen keyed on claim_id) so a claim is read once; on a genuine conflict supersede the old row (sys_period / a superseded_by attr) rather than DO UPDATE, and never set reported_at = now(). Add the ledger count check from HANDOFF §4 (count(*) vs count(distinct …)).
- **Evidence (audited code):**
```
`ON CONFLICT (dataset_id, place_id, indicator, occurred_at) WHERE place_id IS NOT NULL AND v1_stable_id IS NULL DO UPDATE SET value_num=EXCLUDED.value_num, reported_at=now()` (:90-92). The SELECT at :68-70 has no cursor (`ORDER BY cl.reported_at`, every claim of the source every run), so every existing row hits DO UPDATE each hour.
```
- **Verifier's check:** Confirmed. The SELECT at moh_gaza.py:67-70 has no cursor and re-reads every bulletin claim on each hourly run (ops/ingest-gaza.sh). ON CONFLICT ... DO UPDATE SET value_num=EXCLUDED.value_num, reported_at=now() (:90-92) has no WHERE, so every existing row is rewritten each hour and reported_at becomes the run time. The unique index is 045 observation_rollup_uniq. No trigger or history table on observation preserves the old value (047 sys_period is only defaulted, and 061 covers v1_stable_id rows). This violates HANDOFF §1 rule 2. There is also a provenance mismatch: attrs is not updated on conf …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

## B. Verify-first tasks (reported by one reader, not independently checked)

For each: reproduce it with a failing test first. If you cannot reproduce it, do NOT change code — add one line to `SKIPPED.md` with the id and why.

- **FEEDS-V01 · F095 · medium** — Four independent normalisers (arabic.normalize, fuel_price.normalise, moh_gaza._normalise, palhub_* tables) disagree on digits, bidi marks and orthography — `cascade/fuel_price.py:97`
  - scenario: Each reader has a different blind spot: a fuel outlet that writes 'الهيئه' or 'اسطوانه' (ه) yields no_attribution / no cylinder price (0 of the 23 fixture articles today, so latent); an RLM inside a news token survives normalize (6/928 texts) but not moh_gaza; a Persian digit in a MoH line is not folded but survives only because \d and int() accept it. Nobody can state one rule for 'what a digit i …
  - suggested fix: One `resolve/arabic.py` function family: normalize_marks() (Cf chars, NBSP), normalize_digits() (both digit sets + U+066B decimal preserved as '.'), normalize_letters(); every cascade composes these and writes its patterns through _norm_pat-style folding; tests that each cascade's patterns are stable under its own normaliser.
- **FEEDS-V02 · F173 · medium** — effective_from takes the first day-month in the anchor tail: 'منتصف ليلة 31 آب/1 أيلول' dates the list a day early and can strand a month as awaiting_list — `cascade/fuel_price.py:203`
  - scenario: Two outlets carry the same wording for the October list on Sept 30: newest_list for every product becomes Sept 30 and is believed; on Sept 30 October's prices are served as September's, and from Oct 1 the whole month reads 'awaiting_list' unless at least one outlet dates it 'من 1 تشرين الأول'. Also the ordinary 'aug 31 midnight' phrasing shifts every effective_from by one day.
  - suggested fix: When the tail contains two day-month pairs separated by '/', 'و' or '-' (a midnight boundary), take the later one; alternatively prefer a date whose month equals the period month. Test the string above → 2026-09-01.
- **FEEDS-V03 · F175 · medium** — A sentence-level negative filter throws away the whole official list when it mentions Israel or contains 'كان ' — `cascade/fuel_price.py:268`
  - scenario: The Corporation's standard wording ('الأسعار مرتبطة بالأسواق الإسرائيلية') or an outlet phrasing a rise in agorot makes the list unreadable from that outlet; with two outlets needed, a month's list stays 'unconfirmed'/'awaiting_list' even though it was published everywhere — HANDOFF §4's 'short Arabic substrings inside common words' in a new place.
  - suggested fix: Apply the negators at clause level and only to the clause carrying the price (a clause that says 'غير صحيح' or 'بدلا من' is skipped; 'الإسرائيلية' in another clause is not); anchor `كان` and `سابق` to token boundaries (`(?<![؀-ۿ])كان(?![؀-ۿ])`); drop 'أغورة' from the sentence filter since _OLD_OR_DELTA handles deltas. Re-run the corpus: raya 1214890 must read the four litre prices.
- **FEEDS-V04 · F177 · medium** — Connectivity's trailing baseline contains the outage: a ≥ 4-day outage reads 'normal' — `ingest/sources/connectivity.py:107`
  - scenario: A prolonged West Bank degradation (or a total blackout lasting four days) is asserted as an outage for ~3.5 days and then flips to 'normal' at confidence 0.85 while nothing has changed; /v2/connectivity and the MCP say 'الإنترنت بالضفة شغال طبيعي'. HANDOFF §4 names this exact shape for feed thresholds ('must hold out the window it judges').
  - suggested fix: Fetch e.g. 14 days and take the baseline from the window ending 24 h before now (exclude the judged tail entirely), and treat a zero/absent baseline as unknown rather than ratio 1.0. Add the simulation above to a test: 120 h at 20 % must still be 'outage'.
- **FEEDS-V05 · F178 · medium** — FIRMS bbox covers a slice of Israel and pixels carry no place, so 'fires in the West Bank' counts Israeli farmland — `ingest/sources/fires.py:60`
  - scenario: Stubble burning season in the Jezreel valley: 30 VIIRS pixels around Afula/Beit She'an, none in the West Bank, are reported as '30 fires' in the West Bank incident summary; a partner correlates them with settler-attack counts.
  - suggested fix: After parsing each row, run the same PostGIS containment used by osm_fuel (region polygon 'West Bank'), skip pixels outside and set place_id/admin codes for those inside; keep the raw CSV in bronze. Serving side, count only fire events with place_id.
- **FEEDS-V06 · F179 · medium** — A dead FIRMS key or API records success: fires.py exits 0 on fetch errors and no watchdog feed covers it — `ingest/sources/fires.py:275`
  - scenario: The MAP_KEY expires or FIRMS starts returning 'Invalid MAP_KEY' / 5xx: every 15-minute run raises RuntimeError inside fetch, both sensors are skipped, '0 thermal detections' is printed, the unit exits 0, the heartbeat says ok, and satellite corroboration silently disappears for good — HANDOFF §4's 'health inferred from the absence of a complaint'.
  - suggested fix: In main(): return 1 when every sensor fetch failed (or when stats['errors'] is non-empty and detections == 0); in the watchdog add a check on max(occurred_at) of fire_detection events against a FIRMS-measured ceiling and drop the phantom 'fire' entry. Test main() with fetch monkeypatched to raise → exit 1.
- **FEEDS-V07 · F180 · medium** — Empty pages are re-fetched every 15 minutes, not every two hours, because an unchanged page inserts nothing — `ingest/sources/fuel_prices.py:227`
  - scenario: Each headline-first article (the raya.ps case the docstring describes) and each off-topic article that passes the loose TOPIC filter (the msdrnews oil story in the corpus) costs ~184 fetches over two days instead of 24 — eight times the intended load on the outlets — and a handful of them can consume the 25-article cap so a genuinely new list is not read on that tick.
  - suggested fix: Record every attempt: either update a `last_fetched_at` on the existing row when the insert conflicts (`ON CONFLICT ... DO UPDATE SET fetched_at = now()` would break the supersession order — use a separate column or an attempts table), or keep the refusal row's fetched_at and compute `last` from a fuel_price_fetch log. Test _due with a stub cursor: unchanged page at hour 2h15 → not due.
- **FEEDS-V08 · F181 · medium** — Two readers of the same MoH bulletin: the weak one runs hourly into the database, the ratified one only cross-checks — `ingest/sources/moh_gaza.py:24`
  - scenario: The hourly job keeps filling `observation` with readings that organ C's gold set would refuse (mis-tiered totals, 48-h counts as daily, missing days), while the number a human ratified never reaches a row. When P1 gives gaza_moh_daily a stable id, the wrong reader's rows are the ones that get served.
  - suggested fix: Make ingest/sources/moh_gaza.py call organ_c.read + organ_c.validate(previous=last accepted) and write only accepted rows (with window_hours, as_of_date from the bulletin and the verdict notes in attrs); retire cascade/moh_gaza.py or keep it as a test oracle. Add a gold test that the ingest path reproduces tests/gold/moh_c.jsonl.
- **FEEDS-V09 · F183 · medium** — OSM station loader is not idempotent: a re-run duplicates every station — `ingest/sources/osm_fuel.py:112`
  - scenario: Someone runs `python -m ingest.sources.osm_fuel` to refresh the registry (the docstring invites it): ~400 new station rows appear beside the old ones, each servable, with different place_ids — identity churn on the entities fuel observations and alias resolution point at, the HANDOFF §4 shape where 'stations without OSM coordinates share a locality centroid'.
  - suggested fix: Upsert on a unique expression index `(source_refs->>'osm_type', (source_refs->>'osm_id'))` for kind='station', updating geom/name/attrs and keeping place_id; or look up by osm_id first and skip. Latent today (the vertical is retired), so also mark the module retired in its docstring.
- **FEEDS-V10 · F184 · medium** — A start time written '12:00 من ظهر' parses as midnight, asserting the cut 12 hours early — `ingest/sources/power.py:81`
  - scenario: A notice 'من الساعة 12:00 من ظهر حتى الساعة 3:00 مساء' is asserted as an active cut from midnight: `active_now` is true for 12 hours during which the power is on, and the 'cut' then decays for a further ~22 h past 15:00.
  - suggested fix: Allow `(?:من\s+|بعد\s+)?` before the marker in TIME and treat 'ظهر' with hour 12 as 12, 'ليل' with 12 as 0; parse every window pair, not just the first two times. Add the string above to tests/test_power.py expecting 12:00 → 15:00.
- **FEEDS-V11 · F185 · medium** — Weather writes 'normal' at 0.95 confidence when the forecast fields are missing — `ingest/sources/weather.py:60`
  - scenario: Open-Meteo returns a block whose daily arrays are null for a governorate (model gap, or a partial response); the system asserts 'nothing worth mentioning' for that governorate for the next 6 h (max_assert) at the same confidence as a real reading — no-data blurred into a value, contrary to docs/DESIGN.md's three words.
  - suggested fix: In load(), skip the governorate (or write value 'unknown' with a note) when tmax or tmin is None; make advisory() return None for missing temperatures and treat None as 'no reading'. Test: advisory(None, None, None, None) is None and load() writes no row for such a block.
- **FEEDS-V12 · F418 · low** — moh_gaza IS_REPORT/SECTIONS require the hamza spelling 'الإحصائي' / 'إطلاق': a hamza-less day is silently not a report — `cascade/moh_gaza.py:56`
  - scenario: The ministry (or a reposting channel) types 'الاحصائي' once; that day's toll is not emitted, nothing is logged as rejected, and the feed-age watchdog sees a quiet day rather than a parse miss.
  - suggested fix: Fold أإآ→ا in _normalise (as in the patterns) or write `ال[اإ]حصائي`, `[اإ]طلاق`; count 'looked like a report but no tier matched' as a rejected line so the silent branch is visible.
- **FEEDS-V13 · F462 · low** — IODA empty-series trap is still an exit-0 path — `ingest/sources/connectivity.py:188`
  - scenario: IODA changes its response shape (the documented 200-with-empty-series behaviour) — every run succeeds, nothing is written, the state decays to unknown and the first alarm arrives a day later, naming the feed rather than the collector.
  - suggested fix: Return 1 (and beat --fail) when the response had no usable signals; keep the heartbeat semantics of 'ran and found nothing' for the legitimate empty case by distinguishing 'no data points' from 'series present but flat'.
- **FEEDS-V14 · F463 · low** — Low-confidence FIRMS pixels count as fires and boost report confidence as much as high-confidence ones — `ingest/sources/fires.py:184`
  - scenario: A low-confidence daytime pixel (hot roof, flare) 2.8 km from a locality where a channel reported settlers burning a field lifts that report from 0.5 to 0.85 and is counted as a satellite-detected fire.
  - suggested fix: Scale the boost by the fire's confidence (e.g. factor 1 - 0.7·f.confidence) and count only 'n'/'h' pixels in served totals, storing 'l' pixels with status 'possible'.
- **FEEDS-V15 · F464 · low** — The table-unit check is run once per table row over the whole page — `ingest/sources/fuel_prices.py:109`
  - scenario: A long listing page with hundreds of numeric two-cell rows and no shekel header costs hundreds of full-page regex walks per fetch — seconds per page in a step with no timeout budget.
  - suggested fix: Compute `shekel_table = bool(_SHEKEL_TABLE.search(page))` once before the loop.
- **FEEDS-V16 · F465 · low** — MoH occurred_at is the claim's UTC date, not the bulletin's own date — `ingest/sources/moh_gaza.py:89`
  - scenario: A bulletin dated 13 September posted after midnight Gaza time is filed under the 14th (or, posted between 00:00 and 03:00 local, under the previous UTC day), so two bulletins can collide on one key and the upsert overwrites one of them.
  - suggested fix: Use organ C's as_of_date for occurred_at, fall back to the claim date converted to Asia/Gaza, and carry window_hours so a 48-hour count is never a 'day' row.
- **FEEDS-V17 · F466 · low** — Only the first two clock times make the window; a two-window notice loses its second cut and a 2-digit year silently dates it to year 26 — `ingest/sources/power.py:144`
  - scenario: An afternoon cut announced in the same notice as a morning one is never asserted; a notice with a two-digit year is discovered, counted as parsed, and never active.
  - suggested fix: Iterate over pairs of times and record every window; reject years < 2000 as unparsed (counted in stats).
- **FEEDS-V18 · F467 · low** — weather_threshold table is documentation only; the bands are hard-coded in code — `ingest/sources/weather.py:62`
  - scenario: An operator revises the storm band in weather_threshold as the migration invites; nothing changes, and the note on the row now contradicts the code that produces the value.
  - suggested fix: Either store the numeric thresholds in the table and read them in advisory(), or amend 019/DECISIONS to say the table is a register of names and severities.
