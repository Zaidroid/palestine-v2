# Plan 04 · MCP tool answers (Arabic + English renderers, façades)

Phase 1 — Safety inversions — a wrong 'open' or a hidden closure. Read `00-README.md` first (setup, rules, the per-task loop).

## Scope

- **Files you may edit:** `serve/mcp_server.py`, `serve/mcp_en.py`, `serve/mcp_facades.py`, `tests/test_facades.py`, `tests/test_headlines.py`, `tests/test_name_safety.py`, `tests/test_renderers_offline.py`
- **Tests to run after every task:** `tests/test_facades.py tests/test_renderers_offline.py` (with the local DB sourced), then the full suite once at the end of the file.
- **Area rules:** Put new tests in tests/test_renderers_offline.py: call the renderer functions directly with hand-built REST-shaped payloads (read serve/app.py for the real shapes) so they run without an API. Every answer that states a value must state its age; a direction split must carry both ages; unknown vs no source never blurred; no 'None' in either language; AR and EN name the same facts. Do not change REST payload shapes (serve/app.py is owned by another group).

- Confirmed tasks: 29 · verify-first tasks: 37 · refuted (skip): 0

## A. Confirmed tasks (independently verified — do these first, in order)

### RENDERERS-01 · F009 · critical · safety
**checkpoint_status ignores a fresh direction-specific closure when the other direction is unknown**

- **Where:** `serve/mcp_server.py:182`
- **What goes wrong:** A channel posts "قلنديا دخول مغلق" (filed inbound=closed, 9 min old) after the last 'both' reading has decayed. A traveller asks checkpoint_status("قلنديا") with the default direction=both and is told there is no new update and it was last open — while the payload's by_direction.inbound says closed 9 minutes ago. The same happens when inbound and outbound are both fresh 'closed' from two direction-specific readings (flows equal → else branch → decayed 'both' row).
- **Fix:** In the direction=both branch, consider all three rows: if any direction row is known and differs from the `both` row (or the `both` row is unknown), speak each known direction with its own age and say the other is unknown ("مغلق للداخل قبل 9 دقايق؛ للخارج ما في تحديث"). Never let a known direction row be hidden behind an unknown general row. Mirror in mcp_en.checkpoint_status; add a fixture test for both scenarios.
- **Evidence (audited code):**
```
if (direction == "both" and inb and outb
            and inb["flow"] != outb["flow"]
            and "unknown" not in (inb["flow"], outb["flow"])):
        answer = (f"{nm}: {FLOW_AR.get(inb['flow'], inb['flow'])} للداخل، "...
    else:
        suffix = "" if direction == "both" else f" {DIR_AR[direction]}"
        answer = f"{nm}{suffix}: {_flow_phrase(d)}.{_presence_phrase(d)}"

checkpoint_serving (db/migrations/027:27-43) builds the `both` row only from readings filed as direction='both' (`s.direction = t.dir OR s.direction = 'both'`), so an inbound-only reading never reaches it. Probe (scratchpad/mcp-tools/taut.py) with both=unknown/last open 190 min, inbound=closed 9 min, outbound=unkno …
```
- **Verifier's check:** serve/mcp_server.py:182-192: the split branch requires inb AND outb known and different; every other case renders `_flow_phrase(d)` where `d` is the `both` row. db/migrations/027_absence_is_not_presence.sql:27-43: the `flow` CTE joins `s.direction = t.dir OR s.direction = 'both'`, so for t.dir='both' only readings filed as 'both' qualify — an inbound-only reading never reaches that row. resolve/belief.py REFRESH_SQL writes state_current keyed on (place_id, state_kind, direction), and cascade/checkpoint_text.py:162-171 maps دخول/للداخل → inbound, so direction-specific rows exist in the data sha …
- **Already in the release plan:** PLAN §4 R2 (direction essentially unused; 4 places differ by direction) and §7 P1-A.1 (palhub promotion makes direction-specific readings the majority) — the renderer defect itself is not named anywhere
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-02 · F011 · critical · safety
**Exit closures are spoken in NEITHER language unless the verdict is `unverified` — the audit's 15:27 case (slow at Za'tara, Ein Siniya closed at the exit) is reintroduced**

- **Where:** `serve/mcp_server.py:951`
- **What goes wrong:** Ramallah→Nablus with Za'tara congested (on route, 40 km in) and Ein Siniya/Beit El closed 2 km off the route in the first 10 km: _score returns `slow` before computing doubts (corridor.py:376-380); exit_closures lists the closure; near_note skips it because it is in exit_ids; doubt_note is empty because the verdict is not unverified. The traveller hears 'passable but congested' and drives toward a closed exit — exactly the omission the 2026-09-24 audit reported and 978ca3b claims to have fixed.
- **Fix:** In both renderers, subtract from the near-miss warning only names that were actually spoken: `spoken = {x['name'] for x in best.get('doubts') or [] if x['kind']=='exit_closure'}`; or, better, speak `exit_closures` for every verdict as its own clause ('إغلاق على طريق الخروج من X عند Y') and keep doubts only for the verdict reason. Add a unit test that stubs `s.api` for slow/unknown/blocked + exit closure and asserts the name appears in both answers.
- **Evidence (audited code):**
```
mcp_server.py:950-951: `exit_ids = {x.get("name") for x in (best.get("exit_closures") or [])}` / `blocking_nm = [m for m in nm if m.get("flow") == "closed" and m.get("name") not in exit_ids]`; :984 `if best.get("verdict") == "unverified":` gates the only place exit closures are spoken. mcp_en.py:176-178 does the same subtraction and :133 the same gate. resolve/corridor.py:646-647: `exit_closures=_closures_at_ends(near_misses, dist, cap=None)` is ALWAYS filled, `doubts=doubt_records(...) if verdict == "unverified" else []`. Executed with a stubbed api(): verdict slow + Ein Siniya closed 2327 m off at along 0.1 → AR 'الطريق سالك بس فيه ازمة. 3 من 8 حواجز عليها تقارير حديثة. يمر عبر: سردا.' EN …
```
- **Verifier's check:** Confirmed. serve/mcp_server.py:950-951 subtracts every `exit_closures` name from the near-miss warning. The only place exit closures are spoken is the doubt_note, gated at :984 on verdict=='unverified'. resolve/corridor.py:646-647 always fills exit_closures but sets `doubts` only when verdict=='unverified'. mcp_en.py:133 and :176-178 do the same. `_score` returns slow/blocked/unknown before it computes doubts (:362-380). I ran both renderers with a stubbed api() on verify/v0.py: slow, blocked and unknown with Ein Siniya closed 2327 m off at along 0.05. Neither the AR nor the EN answer names Ei …
- **Already in the release plan:** PLAN §7 P0-B.2/P0-B.3; §11 2026-09-24 17:05 'P0-A.3 + P0-B.2/3 · done' (claims doubts + exit_closures spoken in both languages; true only for `unverified`)
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-03 · F010 · critical · safety
**place_profile anchors on one resolver and reads live checkpoint state through another, with no age and no fuzzy doubt**

- **Where:** `serve/mcp_server.py:1197`
- **What goes wrong:** place(place="Hawara"): cp resolves to the town of Huwara (kind locality, `resolved.as_checkpoint: True`), live status is fetched by name and lands on عورتا at 0.707; the answer reads "حوارة: الحاجز سالك، …" — a different checkpoint's flow, no age, no doubt, under the town's name. With flow=unknown it reads "الحاجز غير معروف" with no last-known/age.
- **Fix:** Resolve once: if cp.kind is not checkpoint, treat it as not found; fetch status by the resolved name (cp.name) and verify `live.match.resolved_to == cp.name` else drop the clause; reuse checkpoint_status()'s answer fragment (age + doubt) instead of a bare flow word. Same for mcp_en.place_profile (:369 `which` reads the flag).
- **Evidence (audited code):**
```
cp = api("/v2/geo/resolve", q=place, state_kind="checkpoint_status")   # :1179
    anchor = cp if cp.get("found") else town                                 # :1182
    ...
            live = api("/v2/checkpoints/status", name=place, direction="both")  # :1193
            said.append(f"الحاجز {FLOW_AR.get(live.get('flow'), live.get('flow'))}")  # :1197

geo.py:522-561: resolve_for_state_kind falls through to resolve_place with `prefer_kind` — a +3.0 ranking bonus in _prefer (:190-203), not a filter — so `cp.found` can be a locality; app.py:445-509 _resolve_checkpoint is a separate difflib matcher ("Hawara" → عورتا at 0.707). The sentence carries neither `age_minutes` nor `match.score`.
```
- **Verifier's check:** serve/mcp_server.py:1179 resolves via /v2/geo/resolve with state_kind=checkpoint_status; :1182 anchors on it if found; :1193 fetches live status by the RAW `place` string (not cp['name']) through /v2/checkpoints/status, which uses a different matcher (app.py:445-509 `_resolve_checkpoint`, difflib); :1197 speaks a bare flow word with no age and no match score. migration 035:39-40 gives checkpoint_status place_kind='checkpoint', so resolve_for_state_kind (geo.py:522-561) tries checkpoint rows first but on no exact/folded hit falls through to resolve_place with prefer_kind — a +3.0 bonus in _pref …
- **Already in the release plan:** PLAN §4 R1 ('place_profile("Huwara") … returns the town'); §7 P0-A.1 says `place` 'returns BOTH the town and the checkpoint row when both exist' and the ledger 17:05 marks P0-A.1 done — the code still anchors on one row and only sets `resolved` flags
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-04 · F044 · high · safety
**The direction-split checkpoint sentence carries no age in either language**

- **Where:** `serve/mcp_en.py:71`
- **What goes wrong:** Qalandiya inbound reported open 3 minutes ago, outbound reported closed 170 minutes ago (inside the 6 h flow band, DECISIONS 2026-07-31 P2.4): the only checkpoint answer that mentions both directions is the one with no age, so a traveller cannot tell a fresh closure from a nearly-expired one — DESIGN law 1 ('every status chip carries its age') is violated on the most consequential branch.
- **Fix:** In both renderers, print each direction with its own age: 'قلنديا: سالك للداخل (قبل 3 دقائق)، ومغلق للخارج (قبل 3 ساعات)' / 'open inbound (3 min ago), closed outbound (2h ago)'. Extend tests/test_headlines.py::test_english_says_the_direction_split to assert an age string.
- **Evidence (audited code):**
```
serve/mcp_en.py:68-72
    if (d.get("direction") == "both" and inb.get("flow") and outb.get("flow")
            and inb["flow"] != outb["flow"]
            and "unknown" not in (inb["flow"], outb["flow"])):
        out = (f"{name}: {FLOW.get(inb['flow'], inb['flow'])} inbound, "
               f"{FLOW.get(outb['flow'], outb['flow'])} outbound.{tail}")
Arabic twin serve/mcp_server.py:182-192: the split branch builds the sentence with no _age_ar; `آخر تحديث` is appended only in the else branch (`if d["flow"] != "unknown": answer += ...` inside else). Both per-direction rows carry `age_minutes` (serve/app.py:590-592). Probe: inbound 3 min / outbound 170 min -> 'قلنديا: open inbound, closed outb …
```
- **Verifier's check:** Confirmed in both languages. mcp_server.py:180-186, the split branch, builds the sentence with only the flows and presence; 'آخر تحديث' is appended only inside the else branch (:187-191). mcp_en.py:68-72 likewise omits _age. app.py:590-593 gives each by_direction row its own age_minutes, and the top-level age_minutes is also unused on this branch. Probe with api monkeypatched (inbound open 3 min, outbound closed 170 min): AR 'قلنديا: سالك للداخل، ومغلق للخارج.' and EN 'قلنديا: open inbound, closed outbound.' The existing test (tests/test_headlines.py:123-127) asserts only the words inbound/out …
- **Already in the release plan:** Class only: PLAN-2026-09-24 §7 P0-A.2(c) (age when the payload has one); §11 line 223 records 'EN carries … direction split' as done, without the age
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-05 · F045 · high · safety
**EN checkpoints_near turns 'place not resolved' into 'No recent checkpoint reports around None'**

- **Where:** `serve/mcp_en.py:96`
- **What goes wrong:** checkpoints(place="Hawarra") (or any misspelling the resolver rejects): Arabic says 'I do not know where Hawarra is'; English says there are no recent checkpoint reports around it — an English reader treats an unresolved name as a quiet road and travels. Also leaks 'None'.
- **Fix:** At the top of checkpoints_near (and every renderer): `if d.get("error") or d.get("found") is False: return "Place not recognised — try the Arabic spelling or a nearby town."`. Better: make the tools return one failure shape ({found:false, reason}) and have add_english render it once for all tools before dispatching to the renderer. Add a test that feeds each renderer the exact error payload its tool returns and asserts no 'None' and no absence claim.
- **Evidence (audited code):**
```
serve/mcp_en.py:92-97
    cps = [c for c in d.get("checkpoints", []) if c.get("flow") != "unknown"]
    counts = d.get("counts") or {}
    if not cps:
        return (f"No recent checkpoint reports around {d.get('origin')}. "
                f"{counts.get('in_radius', 0)} are in range but their last news is old.")
The unresolved-place payload the tool returns is serve/mcp_server.py:345-346 `return {"answer": f"ما عرفت وين {place}.", "error": "place not resolved"}` (no origin/counts/checkpoints). mcp_http.py:428-441 treats it as a successful call (failed=False) and attaches the English. Probe in this checkout: add_english("checkpoints_near", {"answer":..., "error":"place not resolved"}) -> 'N …
```
- **Verifier's check:** Confirmed. serve/mcp_server.py:343-346 returns {answer:'ما عرفت وين X.', error:'place not resolved'} with no origin/counts/checkpoints when /v2/geo/resolve returns found:false (app.py:1072/1079/1083 all do). The public façade checkpoints(place=...) routes to checkpoints_near (mcp_facades.py:77-80). mcp_http.py:428-441 marks the call successful (failed=False) and calls add_english; mcp_en.add_english (:651-665) never checks `error`, and mcp_en.checkpoints_near (:92-96) falls into the empty branch. licence.apply (:437-438) returns error payloads untouched, so answer_en survives. Probe in this ch …
- **Already in the release plan:** Class only: PLAN-2026-09-24 §7 P0-A.2(a)/(b) (contract test never written); PLAN-2026-09-21 accuracy-audit item 5 ('None' artifact scan) — error payloads not probed
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-06 · F046 · high · safety
**EN incidents_near turns 'place not resolved' into 'No incidents recorded around None in the last None hours'**

- **Where:** `serve/mcp_en.py:220`
- **What goes wrong:** incidents(place="Al-Mughayyir" misspelt): the English answer asserts there are no incidents around the place for an unstated window, while the Arabic says the place was not recognised. A raid-avoidance decision is made on a manufactured 'no incidents'.
- **Fix:** Same guard as above: render `error`/`found is False` payloads as a not-found sentence before the 'nothing recent' branch; never print `d.get('origin')`/`d.get('hours')` without a fallback. Cover with a renderer test over the real error payload.
- **Evidence (audited code):**
```
serve/mcp_en.py:218-222
    items = d.get("incidents") or []
    if not items:
        return (f"No incidents recorded around {d.get('origin')} in the last "
                f"{d.get('hours')} hours.")
Tool payload for an unresolved place: serve/mcp_server.py:452-453 `return {"answer": f"ما عرفت وين {place}.", "error": "place not resolved"}`. Probe: -> 'No incidents recorded around None in the last None hours.'
```
- **Verifier's check:** Confirmed. serve/mcp_server.py:450-453 returns {answer, error:'place not resolved'} with no origin/hours for an unresolved place; façade incidents(place=...) routes there (mcp_facades.py:83-86); mcp_http.py:436-441 treats it as success and add_english (mcp_en.py:651-665) dispatches to incidents_near (:218-221), whose empty branch prints d.get('origin')/d.get('hours'). Probe: 'No incidents recorded around None in the last None hours.' licence.apply leaves error payloads (and answer_en) intact. This is an affirmative absence claim, the dangerous direction for raid/settler-attack avoidance. Not r …
- **Already in the release plan:** Class only: PLAN-2026-09-24 §7 P0-A.2(b) (contract test never written); PLAN-2026-09-21 accuracy-audit item 5 fixed the incidents_summary 'Noneh' instance, not this path
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-07 · F047 · high · correctness
**news façade silently drops place/kind in search mode and hours in newest mode; declared limit default is wrong for search**

- **Where:** `serve/mcp_facades.py:101`
- **What goes wrong:** news(text="قلنديا", place="رام الله", kind="roads") searches West-Bank-wide including road tables; news(hours=6) returns the newest messages of any age; news(text="x") returns up to 20 items though the schema promised 8. None of this is reported to the caller.
- **Fix:** Route search with `area` and `kind` (extend search() to pass area and filter ROAD_BULLETIN like latest_news), pass `hours` to /v2/news/latest in newest mode, and set search's default limit to the declared 8 (or declare 20). Add route() cases for each.
- **Evidence (audited code):**
```
def _r_news(a: dict) -> tuple[str, dict]:
    if a.get("text"):
        return "search", a
    return "latest_news", {**a, "area": a.get("place") or a.get("area")}

route() (:326-327) keeps only keys in the target schema: search takes {text, hours, limit} (mcp_server.py:1638-1641), latest_news {area, limit, kind} (:1826-1834). Façade schema :218 declares `limit … default 8` while search() defaults to 20 (:1235).
```
- **Verifier's check:** Confirmed by execution. serve/mcp_facades.py:101-104 routes on `text`; route() :326-327 keeps only keys in the target schema. search's schema (mcp_server.py:1665-1674, finding cited :1638) is {text, hours, limit}; latest_news's (:1844-1854, cited :1826) is {area, limit, kind}; latest_news() :613 takes no hours; search() :1235 defaults limit=20 while the façade schema :218 declares default 8. Ran: route('news', {text, place, kind, hours}) → ('search', {'text','hours'}) — place and kind gone; route('news', {hours:6, place}) → ('latest_news', {'area'}) — hours gone. /v2/news/latest (app.py news_l …
- **Already in the release plan:** PLAN §7 P0-A.1 defines `news` (← latest_news + search; 'road tables excluded unless kind=roads'); ledger §11 17:05 P0-A.1 done — search mode does not honour that spec
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-08 · F049 · high · safety
**checkpoint_status blurs 'unknown name' with 'known checkpoint that has never been read'**

- **Where:** `serve/mcp_server.py:173`
- **What goes wrong:** One of the 36 checkpoints that never had a flow reading (PLAN §4 R3) is asked for by its exact name; the caller is told the name is unknown, retries spellings, and never learns the true state: tracked, no source has ever reported it.
- **Fix:** If `resolved_to` is present, answer "{resolved_to}: حاجز معروف بس ما وصلنا عنه ولا تقرير" and keep found=False with `reason`; same in English.
- **Evidence (audited code):**
```
if not d.get("found"):
        return {"answer": f"ما عرفت حاجز اسمه {name}.", **d}

app.py:579-581 returns `{"found": False, "query": name, "resolved_to": m["name"], "reason": "no checkpoint reading has ever been recorded here"}` for a resolved checkpoint with no row in checkpoint_serving. mcp_en.py:57 says "No checkpoint found matching that name."
```
- **Verifier's check:** Confirmed. serve/mcp_server.py:172-173 returns 'ما عرفت حاجز اسمه {name}' for every found=False. serve/app.py:574-579: when _resolve_checkpoint matches but checkpoint_serving has no row it returns {found: False, query, resolved_to: m['name'], reason: 'no checkpoint reading has ever been recorded here'}. That branch is reachable: the view (db/migrations/027_absence_is_not_presence.sql:24-) is built FROM state_serving rows with state_kind='checkpoint_flow' joined to place, so a servable checkpoint that never had a flow reading has no row. mcp_en.py:56-57 says 'No checkpoint found matching that n …
- **Already in the release plan:** PLAN §4 R3 measures the population ('36 never had a flow reading') but nothing schedules the rendering fix
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-09 · F035 · high · safety
**MCP checkpoint_status omits the reading's age whenever inbound and outbound differ (Arabic and English)**

- **Where:** `serve/mcp_server.py:182`
- **What goes wrong:** Inbound reported open at 09:00, outbound reported closed at 11:00, asked at 16:30: both readings are still assertable (< 6 h) and the answer reads 'حوارة: سالك للداخل، ومغلق للخارج.' / 'Huwara: open inbound, closed outbound.' with no age at all, although the inbound reading is 7.5 h old under a 12 h default half-life. The G1 contract (PLAN §6) requires the age of the newest datum in every answer.
- **Fix:** In both renderers append the per-direction ages from by_direction (e.g. 'مغلق للداخل (قبل 20 دقيقة)، وسالك للخارج (قبل 3 ساعة)') and add a pure test on mcp_en.checkpoint_status and on mcp_server.checkpoint_status with `api` monkeypatched to a fixture where inbound≠outbound, asserting an age token is present in both strings.
- **Evidence (audited code):**
```
if (direction == "both" and inb and outb and inb["flow"] != outb["flow"] …): answer = (f"{nm}: {FLOW_AR…} للداخل، و{FLOW_AR…} للخارج."…) — the `آخر تحديث` clause is appended only in the else branch at :192 (`if d["flow"] != "unknown": answer += f" آخر تحديث {_age_ar(…)}."`). serve/mcp_en.py:68-72 has the same shape: `out = (f"{name}: {FLOW…} inbound, {FLOW…} outbound.{tail}")` with no `_age(...)`.
```
- **Verifier's check:** Confirmed at serve/mcp_server.py:182-187. The split branch builds '{nm}: X للداخل، وY للخارج.' plus presence, and the age clause `آخر تحديث` is added only in the else branch (:191-192). serve/mcp_en.py:68-72 has the same shape with no _age(). A fixture run printed 'حوارة: سالك للداخل، ومغلق للخارج.' with no age. The finding's example numbers are wrong: checkpoint_flow has max_assert_seconds=21600 (016:39-40), so a 7.5 h-old inbound reading would be 'unknown' and would fall to the else branch, which prints an age. The defect itself holds for any pair of differing readings under 6 h. This breaks …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-10 · F050 · high · safety
**The direction-split answer carries no age at all**

- **Where:** `serve/mcp_server.py:190`
- **What goes wrong:** Inbound reading 55 min old, outbound 3 h old but still inside the kind's assert ceiling: the traveller hears "مغلق للداخل، وسالك للخارج" with no indication either reading is hours old, which G1 ("the age of the newest datum") forbids and DESIGN law 1 calls the differentiator.
- **Fix:** Append each direction's age from by_direction[*].age_minutes ("مغلق للداخل (قبل 55 دقيقة)، وسالك للخارج (قبل 3 ساعات)") and end the sentence before the presence clause. Same in mcp_en. Extend test_headlines' split fixture to assert an age string.
- **Evidence (audited code):**
```
answer = f"{nm}{suffix}: {_flow_phrase(d)}.{_presence_phrase(d)}"
        if d["flow"] != "unknown":
            answer += f" آخر تحديث {_age_ar(d.get('age_minutes'))}."

The age line is indented under the `else:`; the split branch at :185-187 builds the sentence and never appends an age. Probe output: "قلنديا: مغلق للداخل، وسالك للخارج. وفي جيش" (no age, and the presence clause dangles after the full stop). mcp_en.py:71-73 is the same.
```
- **Verifier's check:** serve/mcp_server.py:185-187 builds the split sentence and returns to :193 without an age; the only age line (:192) is under the `else:` at :188. Probe with inbound=closed 55 min, outbound=open 180 min, present=['idf'] returns exactly 'قلنديا: مغلق للداخل، وسالك للخارج. وفي جيش' — no age, presence clause after the full stop. mcp_en.py:68-73 mirrors it: 'قلنديا: closed inbound, open outbound. army present.' tests/test_headlines.py:127-128 only asserts the words 'inbound'/'outbound' appear, so no test pins an age. by_direction[*].age_minutes is in the payload (app.py:590-592) but never spoken. Ci …
- **Already in the release plan:** PLAN §6 G1 ('the age of the newest datum' in every answer); DESIGN law 1 — not scheduled as a task; ledger 17:05 'EN carries fuzzy doubt + direction split' added the split to EN without an age either
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-11 · F051 · high · doc-drift
**Per-call boilerplate notes the plan moved to the reading-contract resource are still attached to every reply**

- **Where:** `serve/mcp_server.py:218`
- **What goes wrong:** Ledger §11 P0-A.3 reads done; a partner following the plan expects the notes once in `palestine://reading-contract` and finds them per call and absent from the resource.
- **Fix:** Move staleness_note/band_note into READING_CONTRACT and drop them from the payloads, or amend the ledger to 'partial'.
- **Evidence (audited code):**
```
"staleness_note": ("band is relative to this checkpoint's own reporting "
                               "rhythm, not a fixed age"),

Also crossings `band_note`/`note` (:722-728), can_i_travel `caveat` (:1049-1052), place_history `counts` (:797), trend `caveat` (:1333-1336). mcp_http.READING_CONTRACT (:127-150) does not carry the band note.
```
- **Verifier's check:** Confirmed as doc-drift. serve/mcp_server.py:218 still attaches staleness_note on every checkpoint_status reply (tests/test_surface_honesty.py:57 pins it), :720 passes the API's band_note through (serve/app.py:2186), :806 'counts', :1045 and :1334 'caveat' are per call. mcp_http.READING_CONTRACT (:127-150) has no band/staleness entry and INSTRUCTIONS (:78-99) does not carry it. docs/PLAN-2026-09-24-PUBLIC-RELEASE.md:109 (P0-A.3) says 'staleness_note/band_note/caveat move to palestine://reading-contract and the server instructions — served once, not per call' and 'hard caps on payload bytes per …
- **Already in the release plan:** PLAN §7 P0-A.3 (:109: staleness_note/band_note/caveat move to palestine://reading-contract and instructions, served once); ledger §11 :224 claims P0-A.3 done with proof 978ca3b; QA-2026-09-23 :71 records staleness_note being added per call on purpose
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-12 · F052 · high · safety
**checkpoints (near) lists flows with no age, and says '0 checkpoints in the area but their news is old'**

- **Where:** `serve/mcp_server.py:356`
- **What goes wrong:** checkpoints(place="نابلس") reads "حوالين نابلس: حوارة سالك، زعترة مغلق…" with readings that may be up to the assert ceiling old; the traveller cannot tell a 3-minute closure from a 3-hour one. With no tracked checkpoint in radius it reads "في 0 حاجز بالمنطقة بس آخر أخبارهم قديمة".
- **Fix:** Append `(قبل N دقيقة)` per listed checkpoint and the newest age overall; when in_radius == 0 say "ما في حاجز متابَع ضمن N كم". Mirror in mcp_en; assert an age string in test_headlines.
- **Evidence (audited code):**
```
if not known:
        answer = (f"ما في تحديثات جديدة عن الحواجز حوالين {place or 'هون'}. "
                  f"في {counts.get('in_radius', 0)} حاجز بالمنطقة بس آخر أخبارهم قديمة.")   # :355-356
    else:
        closed = [r for r in known if r["flow"] == "closed"]
        parts = [f"{r['name']} {FLOW_AR.get(r['flow'], r['flow'])}"
                 f"{_presence_phrase(r)}" for r in known[:4]]

Each result carries age_minutes (app.py:544, _checkpoint_out :424) but no age reaches the sentence; mcp_en.checkpoints_near (:89-100) likewise.
```
- **Verifier's check:** Confirmed by reading and by execution. serve/mcp_server.py:353-364: the no-known branch prints counts.get('in_radius', 0) verbatim (:356), and the known branch (:358-364) formats name + FLOW_AR + presence with no age; age_minutes exists per result (app.py:424 _checkpoint_out, :550-551 nearby) and is only placed in the payload list (:371). Ran checkpoints_near with a faked api: in_radius=0 → 'ما في تحديثات جديدة عن الحواجز حوالين نابلس. في 0 حاجز بالمنطقة بس آخر أخبارهم قديمة.'; a 170-minute-old open reading → 'حوارة سالك' with no age. mcp_en.checkpoints_near :89-100 is identical. tests/test_he …
- **Already in the release plan:** PLAN §7 P0-A.2 (c) 'answer must contain an age when the payload has one' — ledger §11 17:05 marks P0-A.2/A.4 done (proof test_headlines 16 passed) but tests/test_answer_contract.py does not exist and this headline carries no age; INSTRUCTIONS (mcp_http.py:77-95) promises 'The answer already carries … how old the reading is'
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-13 · F053 · high · accuracy
**incidents_near speaks a village_ambiguous event as if it happened in the governorate city**

- **Where:** `serve/mcp_server.py:472`
- **What goes wrong:** A report about a twin-named village (17 such events in the 09-24 re-read) is located to Ramallah's governorate row with precision village_ambiguous; the answer reads "اقتحام في رام الله قبل ساعة" — the city named as the site, exactly what G3 says must never happen — while incidents_summary correctly keeps it out of by_place.
- **Fix:** Treat any precision other than `named` as governorate-level: `if prec != "named": where = f"{named_place} (محافظة {place}، القرية غير محددة)" if named_place else f"محافظة {place}"`. Same in mcp_en. Add a fixture row with place_precision=village_ambiguous.
- **Evidence (audited code):**
```
where = i["place"]
            if i.get("place_precision") == "governorate" and i.get("named_place"):
                where = f"{i['named_place']} (محافظة {i['place']})"
            elif i.get("place_precision") == "governorate":
                where = f"محافظة {i['place']}"

ingest/sources/news_incidents.py:339 files twins on the governorate row: `Located(res.place_id, "village_ambiguous" if twins else "governorate", …)`; app.py:822 passes the precision through unchanged. mcp_en.py:225-229 has the same two-case test.
```
- **Verifier's check:** serve/mcp_server.py:472-476 rewrites `where` only when place_precision == 'governorate'; any other value (including 'village_ambiguous') falls through to `i['place']`. ingest/sources/news_incidents.py:339 files twins on the governorate row with precision 'village_ambiguous'; :623 writes it into event.attrs; serve/app.py:822 passes it through unchanged. The governorate row for Ramallah is named 'رام الله' (migration 021:22), so the spoken sentence names the city. Probe (scratchpad/verify/probe_rest.py) with a village_ambiguous item: AR 'حوالين رام الله: اقتحام في رام الله قبل 11 ساعة.'; EN (mcp …
- **Already in the release plan:** PLAN §6 G3 ('governorate fallbacks never counted under a city') and §7 P0-C.1c (several candidates → `village_ambiguous`); ledger 18:07 records 17 such events; app.py:897 honours it in the summary — the renderer branch is unscheduled
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-14 · F054 · high · correctness
**Façade arguments are forwarded past the REST validation caps and turn into tool errors instead of clamps**

- **Where:** `serve/mcp_server.py:620`
- **What goes wrong:** news(limit=30) → 120 > 100 → 422 → "صار خطأ بالنظام"; place(view=pattern, days=3) → 422; incidents(place=…, hours=200) → 422. Each is a legal call by the published schema.
- **Fix:** Clamp in the tool functions (min(limit*4, 100), max(days, 7), min(hours, 168)) and declare minimum/maximum in the façade schemas.
- **Evidence (audited code):**
```
d = api("/v2/news/latest", area=area, limit=max(limit * 4, 20) if kind != "all" else limit)
    ...
    d = api("/v2/news/latest", text=text.strip(), hours=hours, limit=limit * 3)   # :1247

app.py:934 `limit: int = Query(10, ge=1, le=100)`; :1612 patterns `days: int = Query(60, ge=7, le=365)`; :767 incidents `hours … le=168`. The façade schemas (mcp_facades.py:181, :196, :218) declare none of these bounds.
```
- **Verifier's check:** Confirmed by a probe that mocked httpx.get with the REST caps: route('news',{limit:30}) -> latest_news -> /v2/news/latest limit=120; route('news',{text,limit:34}) -> search (:1247) -> limit=102; route('place',{view:'pattern',days:3}) -> place_pattern -> /v2/patterns/place days=3; route('incidents',{place,hours:200}) -> incidents_near -> /v2/incidents/recent hours=200. Each raised HTTPStatusError. The caps are real: serve/app.py:934 limit le=100, :1612 days ge=7, :767 hours le=168. api() (:57-66) calls raise_for_status, and both transports turn any non-TypeError exception into {'answer': 'صار خ …
- **Already in the release plan:** PLAN §4 :48 records the symptom only (place_profile('Huwara') … no incidents, blamed on town-vs-checkpoint); §7 P0-A.1 'every default declared' (ledger done) declares no bounds; root cause not diagnosed anywhere
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-15 · F055 · high · safety
**crossings says 'no source at all' when every sourced crossing has merely decayed**

- **Where:** `serve/mcp_server.py:680`
- **What goes wrong:** The only crossing with a basis (Allenby/King Hussein) passes its assert ceiling. crossings() then tells the caller there is no source for ANY crossing and marks the call unmet, while the payload holds basis=checkpoint_flow, last_known_value and age_minutes for the bridge — `unknown` and `no source` blurred (DESIGN law 2), and the QA-09-23 item 3 complaint returns in the renderer.
- **Fix:** Compute decayed/unsourced before the early return; only when no crossing has a basis emit the no-source sentence. Otherwise: "بلا قراءة حديثة: جسر الملك حسين (آخر معلومة سالك قبل 14 ساعة)" + the no-source list. Set `no_source` True only when `unsourced == items`. Fix mcp_en.crossings identically and add a fixture with one decayed basis row.
- **Evidence (audited code):**
```
known = [c for c in items if c.get("value") not in (None, "unknown")]
    if not known:
        return {"answer": ("ما عندي ولا مصدر بيقول عن حالة المعابر — "
                           "مش معناها مفتوحة، معناها ما حدا بيخبرنا."),
                ...
                "no_source": True,
                "warning": ("Every crossing reads `unknown` because NO source "
                            "reports crossing status yet. ...

The decayed/unsourced split (:697-711) runs only after this early return. mcp_en.py:348-351 renders the same "no source reports crossing status yet". app.py:2102-2204 serves King Hussein Bridge from checkpoint_flow with basis, last_known_value and age; tests/test_name_sa …
```
- **Verifier's check:** serve/mcp_server.py:680-689: `known` excludes every value in (None,'unknown') and returns the 'ما عندي ولا مصدر' answer with no_source=True before the decayed/unsourced split at :697-698. serve/app.py:2124-2126 sets basis='checkpoint_flow' whenever `cf.value IS NOT NULL`; state_serving (016_max_assert_age.sql:106-115) emits the TEXT 'unknown' once decayed, never NULL, so a decayed King Hussein row keeps basis + last_known_value + age while value='unknown'. Probe (scratchpad/verify/probe_rest.py) with one decayed basis row + one unsourced row: AR answer is the no-source sentence, no_source=True …
- **Already in the release plan:** docs/QA-2026-09-23-partner-pass.md item 3 (REST fixed via `basis`); PLAN §4 R1 (crossings headline) and §7 P0-A.4 ('crossings headline names what has no source'); ledger §11 17:05 P0-A.2/A.4 done — the code contradicts the 'three kinds of silence' the tool's own comment promises whenever no crossing has a current value
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-16 · F056 · high · safety
**can_i_travel never speaks the age of its evidence and leaks an English verdict token into the Arabic alternate clause**

- **Where:** `serve/mcp_server.py:937`
- **What goes wrong:** "الطريق سالك على الأغلب. 4 من 7 حواجز عليها تقارير حديثة" is read aloud with the newest of those readings 80 minutes old; the alternate reads "بديل: 66 دقيقة (likely_open)" — a Latin token in a sentence meant for a voice bot.
- **Fix:** Add "أحدث قراءة قبل N دقيقة" (min age over known) and the age of the first blocked checkpoint; map the alternate's verdict through the same Arabic `say` table.
- **Evidence (audited code):**
```
detail += f". بديل: {alt['duration_minutes']:.0f} دقيقة ({alt['verdict']})"
    ...
    return {"answer": f"{say}{detail}.{doubt_note} "
                      f"{best['known']} من {best['checkpoints_on_route']} حواجز عليها تقارير حديثة."
                      f"{pass_note}{cover_note}{near_note}",             # :1005-1008
            ...
            "oldest_known_minutes": best.get("oldest_known_minutes"),   # :1040

Ages are spoken only for exit closures and near misses; `blocked_at` (:933) and `slow_at` carry none, and `oldest_known_minutes` is payload-only. mcp_en.can_i_travel (:102-160) is the same.
```
- **Verifier's check:** Confirmed. serve/mcp_server.py:937 interpolates alt['verdict'] raw into the Arabic sentence; the answer at :1005-1008 speaks ages only via doubt_note (exit closures, :985-996) and near_note (:952-962); blocked_at is joined as bare names (:934); oldest_known_minutes is payload-only (:1028). Ran can_i_travel with a faked route payload (blocked, alt likely_open 66 min) → 'الطريق مسكّر — مسكّر عند زعترة. بديل: 66 دقيقة (likely_open). 4 من 7 حواجز عليها تقارير حديثة.' — Latin token, no age. mcp_en.can_i_travel :102-160 likewise joins blocked_at bare and never speaks a newest age.
- **Already in the release plan:** PLAN §7 P0-A.2 (c) (age in the answer when the payload has one) — ledger §11 claims P0-A.2 done, test_answer_contract.py absent; PLAN §4 R1 'EN route omits the alternate' (still true); ledger P0-A.3+P0-B.2/3 spoke ages only for exit closures
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-17 · F057 · high · doc-drift
**Route waypoints are not labelled as settlements although the ledger marks P0-A.4 done**

- **Where:** `serve/mcp_server.py:970`
- **What goes wrong:** A settlement with an Arabic gazetteer name (e.g. عوفرا, حومش) sits nearest the alignment in its slice: it is chosen by the Arabic-first preference and read aloud as "يمر عبر: … عوفرا …" to a Palestinian traveller as if it were a town they can pass through.
- **Fix:** Add a settlement flag to place (attrs or kind) from OSM place=… / the v1 restrictions layer, carry `settlement: true` in passes, and render "مستوطنة عوفرا" / "settlement: Ofra" or drop settlements from the spoken list; correct the ledger line to say labelling is pending.
- **Evidence (audited code):**
```
waypoints = [w["name"] for w in (best.get("passes") or [])][:5]
    pass_note = (f" يمر عبر: {'، '.join(waypoints)}." if waypoints else "")

resolve/corridor.py:611-614: "The registry does not flag settlements, so this is a preference, not a claim about what a place is."; :625-628 passes carries only name/name_en/along/km/off_m. mcp_en.py:141-143 prints name_en or name. PLAN §7 P0-A.4: "waypoints list Palestinian localities first and label settlements (`settlement:`)"; §11 17:05 "P0-A.2/A.4 · done".
```
- **Verifier's check:** serve/mcp_server.py:970-971 prints `w['name']` for each pass with no label; mcp_en.py:162-164 (cited as :141-143) prints name_en or name. resolve/corridor.py:611-614 comment states 'The registry does not flag settlements, so this is a preference, not a claim'; :625-628 emits only name/name_en/along/km/off_m. grep for a settlement flag across db/migrations, resolve/geo.py and resolve/corridor.py finds only databank category views (049:77-80, 056:73) — no place attribute. PLAN :110 promises 'label settlements (`settlement:`)' and :117 'settlements labelled'; the ledger lines marking A.4 and B.3 …
- **Already in the release plan:** PLAN §4 R1 (waypoints naming settlements Ofra, Mevo Shillo, Givat harel, Homesh); §7 P0-A.4 ('label settlements (`settlement:`)') and P0-B.3 ('`passes`: … settlements labelled'); ledger §11 17:05 'P0-A.2/A.4 · done' — the code contradicts the label half of A.4
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-18 · F058 · high · accuracy
**place_profile's hourly pattern still uses the legacy mixed `checkpoint_status` kind**

- **Where:** `serve/mcp_server.py:1206`
- **What goes wrong:** place(view=profile) returns an `hours` table whose modal value per hour can be `idf` or `inspection` instead of a flow word — the very defect the QA pass had fixed for place_pattern — and a client reading `pattern.hours[h].usually` gets presence for flow.
- **Fix:** Use state_kind="checkpoint_flow" (and pass the resolved kind through), or call place_pattern() and reuse its tally.
- **Evidence (audited code):**
```
("pattern", lambda: api("/v2/patterns/place",
                                                place_id=anchor["place_id"],
                                                state_kind="checkpoint_status",
                                                days=60))):

place_pattern (:810-823) was changed to default `checkpoint_flow` after the 09-23 QA pass because `checkpoint_status` carries idf/police in the same column as flow.
```
- **Verifier's check:** Confirmed. serve/mcp_server.py:1204-1207 calls /v2/patterns/place with state_kind='checkpoint_status' (and :1179 resolves the checkpoint with the same legacy kind). app.py:1595-1605 PATTERN_SQL takes the modal `value` per hour from state_observation WHERE state_kind=%s AND modality='assertion'. ingest/sources/checkpoints.py:52 LEGACY_KIND='checkpoint_status' and :180-182 writes each v1 update with v1's own `v1status` and r.modality (assertion for readable reports). docs/QA-2026-09-23-partner-pass.md:45-46 records that this column 'carries idf and police in the same value column as open'; place …
- **Already in the release plan:** docs/QA-2026-09-23-partner-pass.md §5 (default grain was checkpoint_status; fixed for place_pattern only — mcp_server.py:809 now defaults to checkpoint_flow, guarded by tests/test_surface_honesty.py:30); PLAN §7 P0-A.1 made place_profile the DEFAULT `place` view
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-19 · F059 · high · correctness
**place_profile never shows incidents for days > 7: hours=days*24 exceeds the REST cap and the 422 is swallowed**

- **Where:** `serve/mcp_server.py:1216`
- **What goes wrong:** place(view=profile, place="حوارة") — the default view and the one the `place_briefing` prompt (mcp_http.py:187-193) tells a model to call — answers "حوارة: … 12 يوم فيها تقارير." with no incidents and no error, whatever happened there this month. Only days ≤ 7 ever returns incidents.
- **Fix:** Clamp to the endpoint's cap (`hours=min(days*24, 168)`) and say the incident window in the sentence ("أحداث آخر 7 أيام"); do not swallow HTTP errors — record `out["incidents_error"]` and say so. Add a unit test with a fake api asserting hours ≤ 168.
- **Evidence (audited code):**
```
inc = api("/v2/incidents/recent", lat=town["lat"], lon=town["lon"],
                      hours=days * 24, radius_km=10, limit=20)
            out["incidents"] = inc.get("incidents", [])
            ...
        except Exception:                                   # noqa: BLE001
            out["incidents"] = []

app.py:767: `hours: int = Query(24, ge=1, le=168)`. With the default days=30 the request is hours=720 → FastAPI 422 → httpx raise_for_status → caught → incidents silently [].
```
- **Verifier's check:** serve/mcp_server.py:1214-1219: `hours=days * 24` with the signature default days=30 (:1170) → hours=720; the bare `except Exception` sets incidents=[] and nothing is recorded. serve/app.py:767 `hours: int = Query(24, ge=1, le=168)` → FastAPI 422; api() at :62 calls raise_for_status() so a 422 raises HTTPStatusError, which the except swallows. The façade path reaches this default: mcp_facades.py:94-98 `_r_place` passes args through, schema :196 declares days default 30, and mcp_http.py:189-195 `_p_place` tells a model to call place(view=profile). Probe with a fake api that raises on hours>168: …
- **Already in the release plan:** PLAN §4 R1 ('place_profile("Huwara") … 24 empty hours and no incidents') names the symptom; §7 P0-A.1 folds place_profile into `place` and the ledger 17:05 marks P0-A.1 done — the cause (hours cap) is nowhere
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-20 · F060 · high · safety
**Swallowed REST failures render as 'no recent information about it'**

- **Where:** `serve/mcp_server.py:1228`
- **What goes wrong:** The API is restarting or /v2/checkpoints/status times out; place(view=profile, place="حوارة") answers "حوارة: ما في معلومات حديثة عنها." — the refusal word `unknown` used for what is actually an error, so a caller (and the usage ledger's `unmet`) reads a system fault as a quiet day.
- **Fix:** Collect the failed sections and say "ما قدرت أقرأ: الحالة، الأحداث" with `errors: {...}` in the payload; never render an exception as absence of reports.
- **Evidence (audited code):**
```
except Exception:                                   # noqa: BLE001
            pass                                               # :1198-1199 (live status)
        ...
        except Exception:                                   # noqa: BLE001
            out[label] = None                                  # :1210-1211 (history/pattern)
        ...
    out["answer"] = (f"{anchor.get('name')}: " + "، ".join(said) + "."
                     if said else
                     f"{anchor.get('name')}: ما في معلومات حديثة عنها.")   # :1225-1228
```
- **Verifier's check:** Confirmed in code, with one nuance on the scenario. serve/mcp_server.py:1191-1199 wraps the live status call in `except Exception: pass`; :1209-1211 sets history/pattern to None on failure; :1213-1220 sets incidents to [] on failure; :1225-1228 renders 'ما في معلومات حديثة عنها' whenever `said` is empty, and no errors/partial key is added, so a swallowed failure is indistinguishable from a quiet day. Nuance: if the API is fully down, the two resolves at :1178-1179 raise before any of this and the transport answers 'صار خطأ بالنظام' (mcp_http.py:437-441), so the sentence needs the resolves to s …
- **Already in the release plan:** DESIGN.md three-state vocabulary (value / unknown / no source) and INSTRUCTIONS are the rule this breaks; nothing in the plans schedules the fix
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-21 · F061 · high · correctness
**series/trend declares and accepts `days` but never applies it**

- **Where:** `serve/mcp_server.py:1261`
- **What goes wrong:** series(indicators="food.price.bread", days=30) computes the last-3-vs-median comparison over the whole history (years), and the reply's `caveat` tells the reader it compared within their window. The schema promise ("every default declared") is now a declared default for a parameter that does nothing.
- **Fix:** Pass `frm=(today - days)` to /v2/databank/compare (it accepts frm/to, app.py:2455) and state the window in the sentence; or remove `days` from the façade. Add a fake-api test asserting the frm parameter.
- **Evidence (audited code):**
```
def trend(indicator: str, days: int = 90, place: str | None = None) -> dict:
    ...
    d = api("/v2/databank/compare", indicators=f"{indicator},{indicator}",
            place_id=place_id)                                     # :1272

No other line in trend() reads `days` (grep: only age_days). mcp_facades.py:118 forwards it (`"days": a.get("days")`) and :236-237 declares `"days": {"default": 90, "description": "single-indicator mode: the window"}`.
```
- **Verifier's check:** serve/mcp_server.py:1261-1339: the only occurrences of 'days' inside trend() are the parameter and the unrelated `age_days` (:1318-1330); :1272 calls /v2/databank/compare with indicators and place_id only. Probe with days=30 recorded compare params {'indicators': 'food.price.bread,food.price.bread', 'place_id': None} — no frm/to, although app.py:2455-2456 accepts them. mcp_facades.py:118 forwards `days` and :236-237 declares default 90. Doc drift vs PLAN :108 and ledger :218 confirmed. One inaccuracy in the failure scenario: the reply's `caveat` ('compares the last three readings to the median …
- **Already in the release plan:** PLAN §4 R1 ('`trend.days` silently ignored'); §7 P0-A.1 ('`series` (← trend + compare; … `days` honoured)'); ledger §11 17:05 'P0-A.1 · done' — the code contradicts 'days honoured'
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-22 · F062 · high · accuracy
**databank headline's 'series from X to Y' is computed over the returned page, not the series**

- **Where:** `serve/mcp_server.py:1466`
- **What goes wrong:** databank(category="demolitions") returns the 10 newest rows, all 2026, and the sentence says "السلسلة من 2026 إلى 2026" for a series that runs 2009→2026 — the span the plan's own example sentence promises. The English renderer (mcp_en.py:441-447) still prints a row count.
- **Fix:** Take the span from /v2/databank/indicators (from_date/to_date per indicator, app.py:2399) for the indicators in `newest`, or from a min/max the category route adds; phrase the page as "أحدث 10 سجلات". Update mcp_en.databank to the same facts.
- **Evidence (audited code):**
```
dates = sorted(str(it.get("occurred_at") or "")[:10] for it in items if it.get("occurred_at"))
    span = f" السلسلة من {dates[0][:4]} إلى {dates[-1][:4]}." if dates else ""

`items` is /v2/databank/{category} ORDER BY occurred_at DESC LIMIT limit (app.py:2775-2782); the tool's default limit is 10.
```
- **Verifier's check:** serve/mcp_server.py:1466-1467 computes `dates` from `items`, which is the page returned by /v2/databank/{category}; serve/app.py:2775-2776 orders that query `ORDER BY o.occurred_at DESC LIMIT %s`, and the tool default is limit=10 (:1426). Probe with 10 rows all dated 2026: AR answer ends 'السلسلة من 2026 إلى 2026. (10 سجل معروض من أصل أكثر)'. The per-indicator span exists elsewhere (app.py:2399-2403 /v2/databank/indicators from_date/to_date) and is not used. mcp_en.py:462-468 (cited as :441-447) still prints '{count} rows from {category}'. Confirmed as described; only the mcp_en line citation …
- **Already in the release plan:** PLAN §7 P0-A.4 ('databank headline = latest value per indicator + span + source ("… السلسلة 2009→2026")'); §6 G5 ('every category answer is a sentence (latest value, span, source)'); ledger §11 17:05 'P0-A.2/A.4 · done · Databank latest-figure headline' — the span is computed over the page and the EN renderer is still a row count
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-23 · F268 · medium · operability
**Composite tools have no overall deadline: up to six sequential 30 s calls per request**

- **Where:** `serve/mcp_server.py:63`
- **What goes wrong:** One slow endpoint (coverage measured 2.7 s cold before caching; a locked DB) turns about() into a 30–180 s request; the tunnel/client times out, the worker keeps running, and 16 such requests exhaust the MCP pool so every other caller queues behind them.
- **Fix:** Give api() a per-call timeout of ~8 s and each composite a total budget (pass a deadline down; skip optional sections with a `partial: [names]` marker); bound _handle with a future timeout and return isError when exceeded.
- **Evidence (audited code):**
```
r = httpx.get(f"{API}{path}", params={k: v for k, v in params.items() if v is not None},
                  timeout=30.0)

place_profile makes 2 resolves + status + history + pattern + incidents (:1178-1220), about makes coverage + radar + scout + stream + categories (:1533-1551); mcp_http runs each message on a 16-thread pool (:76, :644) with no wall-clock limit.
```
- **Verifier's check:** Confirmed. serve/mcp_server.py:62-63 httpx.get(..., timeout=30.0) per call with no deadline parameter. place_profile :1178-1220 issues 2 resolves + status + history + pattern + incidents sequentially; about :1538-1541 calls coverage() (1 GET) + data_gaps() (radar + scout, :1490-1502) + stream_info() (1) + /v2/databank/categories (1) = 5 sequential GETs. serve/mcp_http.py:76 _POOL = ThreadPoolExecutor(max_workers=16); :643-644 awaits asyncio.gather(loop.run_in_executor(_POOL, _handle, ...)) with no wait_for or cancellation, so a slow tool holds its worker for the full chain. /v2/coverage is q_c …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-24 · F305 · medium · correctness
**`series(..., days=N)` is declared in the façade schema and ignored by `trend`; ledger P0-A.1 marks it done**

- **Where:** `serve/mcp_server.py:1261`
- **What goes wrong:** `series(indicators="food.price.bread", days=30)` returns "last 3 readings vs the median of the rest" computed over the ENTIRE series (years), while the schema told the caller the comparison covers 30 days; the answer text names no window, so a reader quotes a 30-day trend that is actually an all-history one.
- **Fix:** In `trend`, compute `frm = (date.today() - timedelta(days=days)).isoformat()` and pass `frm=frm` to `/v2/databank/compare`; say the window in `answer`/`answer_en`; add a test that monkeypatches `s.api` and asserts `frm` is sent. Correct the ledger line or leave `days` out of the schema.
- **Evidence (audited code):**
```
serve/mcp_server.py:1261 `def trend(indicator: str, days: int = 90, place: str | None = None) -> dict:` — lines 1261-1336 never reference `days` (only `age_days`); :1272-1273 `d = api("/v2/databank/compare", indicators=f"{indicator},{indicator}", place_id=place_id)` passes no `frm`. serve/mcp_facades.py:236-237 `"days": {"type": "integer", "default": 90, "description": "single-indicator mode: the window"}`. PLAN §7 P0-A.1 specifies `series` "(← trend + compare; ...; `days` honoured)" and §11 line 218 records "P0-A.1 · done". `/v2/databank/compare` accepts `frm`/`to` (serve/app.py:2455-2456) so the window was one parameter away.
```
- **Verifier's check:** Confirmed by running a script (scratchpad/verify/trend_days.py). route('series', {indicators:'food.price.bread', days:30}) gives trend {'indicator':..., 'days':30} (mcp_facades.py:118). trend (mcp_server.py:1261-1336) never reads `days` and calls api('/v2/databank/compare', indicators=..., place_id=None) without frm. Output: first=2010-01-01, last=2021-01-01, the whole history. /v2/databank/compare accepts frm/to (app.py:2455-2456), and _series applies no default window (app.py:2414-2432). The façade schema advertises days (default 90) as 'single-indicator mode: the window' (mcp_facades.py:236 …
- **Already in the release plan:** PLAN-2026-09-24 §4 R1 line 47 ('trend.days silently ignored'); §7 P0-A.1 line 107 ('series ... `days` honoured'); §11 line 218 '2026-09-24 17:05 UTC · P0-A.1 · done' (contradicted by code)
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-25 · F269 · medium · accuracy
**about() counts every `place` row of kind checkpoint as 'tracked', not the servable set**

- **Where:** `serve/mcp_server.py:1564`
- **What goes wrong:** The first call a stranger makes says "على 359 حاجز متابَع" while checkpoints() says tracked=272 and 95 with a current status: two 'tracked' numbers for one system, the larger one overstated by the merged duplicates.
- **Fix:** Use checkpoints_summary()'s `tracked` (or add a servable-only count to /v2/coverage) and say both facts: tracked and with a current reading.
- **Evidence (audited code):**
```
ar = (f"بيانات فلسطين: {cov.get('total_claims', 0):,} رسالة من "
          f"{len(cov.get('sources') or [])} مصدر، {sum((cov.get('live_states') or {}).values()):,} "
          f"حالة مباشرة على {places.get('checkpoint', 0)} حاجز متابَع.")

/v2/coverage `places` is `SELECT kind, COUNT(*) FROM place GROUP BY 1` (app.py:1004) — no servable / merged_into filter — while checkpoints_summary's `tracked` counts checkpoint_serving rows (:616). PLAN §4 R3 measured 359 rows of which 86 merged, 272 servable (a DB number; not re-measured here).
```
- **Verifier's check:** Confirmed. serve/mcp_server.py:1562-1564 speaks places.get('checkpoint') from coverage() (:644-645 → /v2/coverage). serve/app.py:1003: q_cached('SELECT kind::text AS kind, COUNT(*) AS n FROM place GROUP BY 1') — no servable or merged_into predicate — returned as 'places' (:1026). db/migrations/013_place_quality.sql:33-36 adds merged_into and servable and merged duplicates keep their row, so they are counted. checkpoints_summary's tracked (app.py:616-620) sums checkpoint_serving rows with direction='both', and that view is filtered WHERE p.servable (027). Two 'tracked' numbers by construction. …
- **Already in the release plan:** PLAN §4 R3 gives the measured population (359 rows, 86 merged, 272 servable) — numbers only, nothing scheduled
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-26 · F270 · medium · operability
**The stdio transport still diverges from HTTP: no ping, no instructions, no outputSchema, no licence block**

- **Where:** `serve/mcp_server.py:2056`
- **What goes wrong:** hermes (the host agent) sends the spec's keep-alive `ping` and receives -32601; the stdio client never sees the three-state reading contract that INSTRUCTIONS carries, so Fawwaz's/Sameera's agents get the tools without the sentence that tells them not to rephrase `answer`.
- **Fix:** Make main() a loop over mcp_http._handle(msg, ip="127.0.0.1", tier="house") with a stdio flag that keeps HOST_ONLY callable; delete the duplicate dispatcher.
- **Evidence (audited code):**
```
if method == "initialize":
            _reply(rid, {"protocolVersion": PROTOCOL,
                         "capabilities": {"tools": {}}, ...          # :2022-2027, no `instructions`
        ...
        elif method in ("notifications/initialized", "initialized"):
            continue
        elif rid is not None:
            _error(rid, -32601, f"method not found: {method}")      # `ping` lands here

mcp_http._handle answers ping (:361), sends INSTRUCTIONS (:359), adds outputSchema (:305) and licence.apply (:448); stdio calls listed_tools() bare (:2032) and TOOLS directly (:2047).
```
- **Verifier's check:** Confirmed. serve/mcp_server.py main() :2015-2058: initialize reply (:2024-2028) carries protocolVersion/capabilities/serverInfo and no `instructions`; there is no `ping` branch, so ping falls through to `_error(rid, -32601, 'method not found')` at :2056 (finding cited :2053); tools/list (:2033) returns listed_tools(include_host_only=True) bare, with no outputSchema; tools/call (:2048) calls add_english(target, TOOLS[target][0](**args)) and never licence.apply. The HTTP side has all four: mcp_http.py ping :375, instructions :373, outputSchema :311, licence.apply :448 (finding's :361/:359/:305 a …
- **Already in the release plan:** PLAN §4 R1 last bullet ('Two transports diverge (stdio: 31 tools, 2024-11-05 only, no instructions/licence/structuredContent/ping)'); P0-A.1 (done, ledger 17:05) covered only façade listing + route() on stdio; DECISIONS.md 2026-07-31 'One stdio server, no SDK dependency'
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-27 · F271 · medium · test-gap
**test_absorbed_names_are_off_the_menu_but_still_answer cannot fail: the envelope never has a top-level `error` on a tool failure**

- **Where:** `tests/test_facades.py:45`
- **What goes wrong:** Every absorbed alias could raise on every call (or the API could be down) and this gate stays green; the ledger's "every old name still answers" rests on it.
- **Fix:** Assert `not reply["result"]["isError"]` and that `payload(reply)` has no `error` key; the plan's tests/test_answer_contract.py (P0-A.2) should be the home for this.
- **Evidence (audited code):**
```
assert "error" not in call(old, place="نابلس") if old == "where_is" \
            else "error" not in call(old)

mcp_http._handle wraps a raised tool as `{"result": {"content": …, "isError": True}}` (:425-431, :452-456). Probe with no API running: `sorted(r) == ['id', 'jsonrpc', 'result']`, isError True, payload {'error': 'Connection refused', 'answer': 'صار خطأ بالنظام.'}, and `"error" not in r` is True. The test passes in this checkout with no database.
```
- **Verifier's check:** Ran `pytest tests/test_facades.py -k absorbed` in this checkout with no API: 1 passed. serve/mcp_http.py:428-431 catches a raised tool and sets out={'error':…, 'answer':'صار خطأ بالنظام.'}, failed=True; :449-453 wraps it as result={'content':…, 'isError': True}. Only _err (:282-283) emits a top-level 'error', and it is used for protocol errors (:417-425). Probe (scratchpad/verify/probe9.py) calling 'coverage' with no API: reply keys ['id','jsonrpc','result'], isError True, payload error '[Errno 111] Connection refused', and `"error" not in r` evaluates True. So tests/test_facades.py:45-46 cann …
- **Already in the release plan:** PLAN §7 P0-A.2 and §10 name tests/test_answer_contract.py (not in the tree: `ls` → no such file); ledger §11 17:05 P0-A.1 cites 'test_facades 33 passed' as proof for 'every old name still answers'
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-28 · F504 · low · accuracy
**Arabic age phrases ignore dual/plural and can go negative; flow vocabulary differs per tool**

- **Where:** `serve/mcp_server.py:68`
- **What goes wrong:** A voice bot reads "قبل 2 ساعة" (should be ساعتين) and "قبل 5 دقيقة" (should be 5 دقايق); a negative age is read literally. A listener hears مفتوح in one answer and سالك in the next for the same state.
- **Fix:** One lexicon module with a numbered-noun helper (1 → دقيقة, 2 → دقيقتين, 3–10 → دقايق, 11+ → دقيقة), clamp negatives to "الآن", and route every renderer through the same flow/event maps.
- **Evidence (audited code):**
```
def _age_ar(minutes: int | None) -> str:
    ...
    if minutes < 60:
        return f"قبل {int(minutes)} دقيقة"
    if minutes < 1440:
        return f"قبل {int(minutes // 60)} ساعة"
    return f"قبل {int(minutes // 1440)} يوم"

Probe: "قبل 2 ساعة", "قبل 5 دقيقة", "قبل 2 يوم", "قبل -3 دقيقة" (a future occurred_at from clock skew). insights/history say مفتوح (:299), checkpoints say سالك (:129), pattern/route say مسكّر (:834, :898); INCIDENT_AR vs _AR_EVENTS are two hand-kept maps (:439-448).
```
- **Verifier's check:** Confirmed by running the function (serve/mcp_server.py:68-75): _age_ar(120) -> 'قبل 2 ساعة', _age_ar(5) -> 'قبل 5 دقيقة', _age_ar(2880) -> 'قبل 2 يوم', _age_ar(-3) -> 'قبل -3 دقيقة'. There is no dual/plural branch and no clamp. _mins_since (:532-541) returns int((now - t)//60) with no floor, so a future occurred_at/reported_at yields a negative, and the API's own age_minutes is EXTRACT(EPOCH FROM now() - observed_at)/60 with no GREATEST (db/migrations/006_state.sql:87, 026_expose_serving_mode.sql:65), so the negative can also arrive from the API; whether a future timestamp actually exists cann …
- **Already in the release plan:** DECISIONS.md 2026-07-31 · P1.8 (negative-age class, clamped at palhub ingest only) — the grammar and vocabulary split are in no plan
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### RENDERERS-29 · F505 · low · doc-drift
**correlate's `answer` is English in two of its three modes**

- **Where:** `serve/mcp_server.py:1077`
- **What goes wrong:** INSTRUCTIONS promises `answer` is Palestinian Arabic to be read aloud; a pair correlation or an indicator search returns an English `answer` and an identical `answer_en`, so an Arabic voice client reads English.
- **Fix:** Render the Arabic from the structured fields (rho, n, ci95, lag) and leave plain_english to answer_en.
- **Evidence (audited code):**
```
return {"answer": (f"{d['plain_english']} — n={d['n']}"
                           + (f", lag {d['lag_days']}d" if d["lag_days"] else "")
                           + f", 95% CI {d['ci95']}."), ...
    if search or concept:
        ...
        return {"answer": (f"{len(inds)} series matched: " ...   # :1084
```
- **Verifier's check:** Confirmed. serve/mcp_server.py:1077-1080 returns answer = f"{d['plain_english']} — n=..., lag ..d, 95% CI ..." and :1084-1085 returns answer = f"{len(inds)} series matched: ..." — both English; only the no-argument concepts mode (:1088) is Arabic. serve/mcp_http.py:85-86 (INSTRUCTIONS) and :141 (READING_CONTRACT['answer']) promise Palestinian Arabic to be read aloud. serve/mcp_en.py:435-442 builds answer_en from the same plain_english, so both fields are English; they are near-identical rather than byte-identical (answer_en uses '(n=.., 95% CI ..)' plus the first caveat and omits the lag), a m …
- **Already in the release plan:** PLAN §7 P0-A.2 (answer contract, checks a–e) is the natural home but lists no 'answer is Arabic' check; not otherwise known
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

## B. Verify-first tasks (reported by one reader, not independently checked)

For each: reproduce it with a failing test first. If you cannot reproduce it, do NOT change code — add one line to `SKIPPED.md` with the id and why.

- **RENDERERS-V01 · F252 · medium** — EN checkpoint_status drops the requested direction the Arabic states — `serve/mcp_en.py:81`
  - scenario: checkpoint_status(name=قلنديا, direction=outbound): Arabic 'قلنديا للخارج: مغلق', English 'قلنديا: closed' — read aloud verbatim (the contract), the English asserts the checkpoint is closed in both directions while inbound is open.
  - suggested fix: Add `scope = '' if d.get('direction') in (None,'both') else f' ({d['direction']})'` and put it after the name in every branch; assert in a renderer test.
- **RENDERERS-V02 · F253 · medium** — EN can_i_travel with no route says 'None. 0 of 0 checkpoints on it have recent reports.' — `serve/mcp_en.py:128`
  - scenario: Origin and destination Valhalla cannot connect (or a Valhalla tile gap): the Arabic says a route could not be computed; the English reads 'None. 0 of 0 checkpoints…' — a nonsense sentence on the tool a traveller reads first.
  - suggested fix: `if not d.get("routes"): return "Could not compute a route between those places."` before anything else, and never `str(verdict)` — fall back to 'No verdict' with the raw word in parentheses.
- **RENDERERS-V03 · F254 · medium** — EN can_i_travel omits the alternate route the Arabic names when the main road is blocked — `serve/mcp_en.py:131`
  - scenario: رام الله→نابلس blocked at Huwara with a passable 72-minute alternate: the Arabic reader is told the alternate, the English reader only that the road is blocked — the plan's own list of divergences.
  - suggested fix: Mirror the Arabic: find the first `routes[i]` with verdict likely_open/slow and append 'Alternative: {duration} min ({verdict}), {known} of {n} checkpoints reported'. Assert in the parity test.
- **RENDERERS-V04 · F255 · medium** — EN fuel headline dates every product to the first confirmed row's date; the Arabic was fixed for this exact defect — `serve/mcp_en.py:211`
  - scenario: September list: English tells a reader petrol's 7.2 has been in force since 1 Sep (it began the 7th); the wrong date is served with the right price.
  - suggested fix: Port the AR date logic (`dates = sorted({...})`; single date, else 'from {first} (newest {last})') and print `reported` prices for unconfirmed/conflicting rows; test with the two-date payload.
- **RENDERERS-V05 · F256 · medium** — EN incidents_summary still prints 'in the last None hours' on an empty window — `serve/mcp_en.py:258`
  - scenario: incidents(hours=1) on a quiet hour -> English 'No incidents recorded in the last None hours.' The QA pass recorded the 'Noneh' fix as done; only the non-empty branch was fixed.
  - suggested fix: Use `d.get('window_hours') or d.get('hours')` in the empty branch too (one-line), and let ops/mcp_accuracy_audit.py:355-361's None check also probe an empty window.
- **RENDERERS-V06 · F257 · medium** — EN what_correlates_with with an unresolved place says 'Nothing held is comparable to this series. Reasons:' — `serve/mcp_en.py:415`
  - scenario: correlate(indicator=food.price.bread, place="Ramalla"): Arabic says the place is unknown; English says nothing in the databank is comparable to bread prices — a false negative about the data.
  - suggested fix: Handle `found is False` first ('Place not recognised'); when `skipped` is empty and `tested` is absent, say the scan did not run.
- **RENDERERS-V07 · F258 · medium** — EN correlate drops the lag and every caveat but the first, so a lag-scanned fit is presented without the lag doubt the Arabic carries — `serve/mcp_en.py:439`
  - scenario: correlate(a, b, max_lag=30): the best of 61 shifts is served; the Arabic says 'lag 3d', the English reads as a contemporaneous finding.
  - suggested fix: Print lag_days when non-zero and include the lag and small-n caveats (not only [0]); in the concept/no-arg modes name the top concepts and matched indicator strings as the Arabic does (:1084-1091).
- **RENDERERS-V08 · F259 · medium** — EN licenses with an unmatched source filter asserts '0 rows are republishable … 0 are sellable' — `serve/mcp_en.py:448`
  - scenario: licence(scope=sources, source="btselem") when B'Tselem is not served: the English answer states that zero databank rows may be republished — a false licensing statement a partner may act on. (The Arabic `answer` in this branch is also English, a separate parity oddity.)
  - suggested fix: `if not d.get("tiers"): return d.get("answer") if it is English, else "No served source matches that name."`; give the AR branch an Arabic sentence.
- **RENDERERS-V09 · F260 · medium** — EN databank headline is still 'N rows from category' after the Arabic moved to the latest figure; the test only checks for a digit — `serve/mcp_en.py:468`
  - scenario: databank(category=demolitions) in English: '5 rows from demolitions.' — the sentence the plan called 'true and empty'; ledger P0-A.2/A.4 reads as if both languages were fixed.
  - suggested fix: Render `latest_by_indicator` in EN (value, unit, date at the row's precision, place_en, partial-year flag, source, span); replace the digit check with an assertion on the latest value appearing in both sentences.
- **RENDERERS-V10 · F261 · medium** — insights speaks the overall gate but never the per-type precision beside the death count it names, in either language — `serve/mcp_en.py:503`
  - scenario: insights(place=رام الله, days=30): 'Incidents in the window: 5 death (2 corroborated) … measures 77 % against its 80 % gate' — the death count is served with the aggregate number while its own measured precision is 60 %. The agent audit flagged exactly this ('headline repeats death counts without the 35% precision for that type').
  - suggested fix: Build a by_type dict from `inc.by_type` and append _precision_en(quality.summary(that))/_precision_ar(...) in both insights renderers; add to test_insights.py.
- **RENDERERS-V11 · F262 · medium** — add_english and quality.incident_precision fail silently: a renderer exception or a missing precision file leaves no trace — `serve/mcp_en.py:661`
  - scenario: A field rename in one REST payload breaks one renderer: every call of that tool loses its English for weeks, the suite stays green (no test asserts presence per tool), /health says ok. Or the nightly job truncates ops/incident-precision.json: incident answers stop mentioning precision and read as fully trusted.
  - suggested fix: Log `tool` + exception at WARNING and increment a counter exposed in /health (`answer_en_failures`); in quality, distinguish 'no file' from 'unreadable' and surface `precision: {state: 'unmeasured — file missing'}` so the sentence says it. Tests: a renderer that raises must produce a log line; a missing file must produce an explicit note.
- **RENDERERS-V12 · F383 · medium** — The suite has no isolation from production: MCP tools default to the production API port and the ledger's full run used it; conftest isolates only two of the write paths — `serve/mcp_server.py:44`
  - scenario: A test that legitimately exercises a write path (the crowd report happy path, a future `learn` path, an alert) is added without a patch in conftest; it writes to the production ledger/table on every run, as the usage ledger did for 329 entries (conftest.py:25-32).
  - suggested fix: A `docker compose` test database filled by `db/migrate.sh` and selected by `PALESTINE_DB_URL` in a session fixture; refuse to run DB/API tests when the URL/port matches the production defaults unless `PALESTINE_ALLOW_PROD_TESTS=1`; require `PALESTINE_API` to be set explicitly for the MCP-over-HTTP tests.
- **RENDERERS-V13 · F303 · medium** — MCP tools reach the API by fresh loopback HTTP requests: `place` = 6 nested requests (~10 connections), `about` = 5, each holding an MCP thread while waiting for a thread in the pool it competes with — `serve/mcp_server.py:62`
  - scenario: Under external REST load that fills the 40-thread pool, every MCP tool's loopback request queues behind it; the MCP thread waits up to the 30-s httpx timeout and then answers "صار خطأ بالنظام", so the agent surface degrades first and hardest. Even idle, a `place` profile pays six middleware passes, six JSON decode/encode cycles, six TCP handshakes and ~10 database connections for one answer.
  - suggested fix: Keep the single data path but change the transport: a module-level `httpx.Client` with keep-alive at minimum; better, when `PALESTINE_API` names this process, dispatch through an in-process ASGI transport (`httpx.ASGITransport(app)`) or call the route functions directly behind the same `api()` seam, so a tool costs no socket and no second pool hop; make `place_profile` fetch the checkpoint row onc …
- **RENDERERS-V14 · F187 · medium** — MCP fuel_prices crashes with TypeError when a product is awaiting_list and was never confirmed — `serve/mcp_server.py:105`
  - scenario: gasoline_98 (or lpg_2_5kg, which al-ayyam omits) was read by a single outlet last month and by nobody this month: the row is awaiting_list with last_confirmed_price None; `format(None, 'g')` raises and the whole fuel_prices tool returns an error for every product.
  - suggested fix: Guard: if last_confirmed_price is None say 'ولا سعر مؤكد سابق' / 'no earlier confirmed price'; add a unit test with such a row. Consider having 073 emit 'no_data' instead of 'awaiting_list' when nothing was ever confirmed.
- **RENDERERS-V15 · F263 · medium** — 'Resolved but never a reading' is rendered as 'no checkpoint found' in both languages (no-source blurred into not-found) — `serve/mcp_server.py:172`
  - scenario: checkpoint_status('بيت فوريك') for a gazetteer checkpoint that no channel has ever reported: the user is told the name is unknown and retries spellings, when the truth is 'the checkpoint exists; nothing measures it' (the `no source` state DESIGN says must never be blurred).
  - suggested fix: When `resolved_to` is present, say it in both languages: 'عرفت حاجز {resolved_to} بس ما وصلني عنه ولا تقرير أبداً — مش معناها مفتوح' / '{resolved_to} is a known checkpoint, but no source has ever reported it — that is unmeasured, not open.' Add a renderer test over the REST shape.
- **RENDERERS-V16 · F304 · medium** — `news(limit≥26)` and `news(text=..., limit≥34)` produce a REST 422 and a system-error answer because the tool multiplies limit past the route's cap — `serve/mcp_server.py:620`
  - scenario: A client asks `news(place="نابلس", limit=30)` → latest_news requests limit=120 → FastAPI returns 422 → httpx raises → the tool answers "صار خطأ بالنظام" with isError=true; the same for `news(text="قلنديا", limit=40)`. The failure reads as a broken server for a request the schema permits.
  - suggested fix: Clamp in both tools (`min(100, ...)`) and declare `"maximum": 25` (news) in the façade schema, or have the route page instead of cap; add a test that monkeypatches `s.api` to capture `limit` and asserts it never exceeds 100 for limit=1000.
- **RENDERERS-V17 · F323 · medium** — `slow` never says WHERE the congestion is: `congested_at` is in the payload, absent from both sentences — `serve/mcp_server.py:933`
  - scenario: Congestion at the traveller's exit (Beit El) and congestion 45 km away at Za'tara produce the identical sentence; the reader cannot tell whether to leave now or later, or by which road. The English `summary` (:378) names it but no renderer uses summary.
  - suggested fix: Add a detail clause for slow: AR ' — ازمة عند ' + '، '.join(best['slow_at'][:2]); EN ' — congested at …'; include the reading's age from `checkpoints`.
- **RENDERERS-V18 · F324 · medium** — When the best route is an alternate, neither answer says the direct road is blocked or that this is a detour; `is_alternate`/`passes` are dropped per route and the 'بديل' branch is unreachable — `serve/mcp_server.py:935`
  - scenario: Za'tara closed: the traveller hears 'probably passable' and (in Arabic) no duration; they take Route 60 as usual because nothing said the direct road is shut and the passable one is a 66-minute detour via Deir Dibwan. An agent reading the MCP payload cannot tell which entry is the primary.
  - suggested fix: Expose `is_alternate` and `passes` per route; when rs[0]['is_alternate'], prefix AR 'الطريق المباشر مسكّر عند X؛ هذا بديل عبر Y ({N} دقيقة). ' and EN 'The direct road is blocked at X; this is the alternative via Y ({N} min). '; speak duration in Arabic too; delete the dead alt branch.
- **RENDERERS-V19 · F325 · medium** — Blind-stretch reason is a fixed phrase — 'نص الطريق تقريباً' / 'most of the route' — whatever the gap actually is; the km in the doubt record are never rendered — `serve/mcp_server.py:994`
  - scenario: Jenin→Hebron (~100 km) with a 10.5 km unwatched stretch at km 40–50: the traveller is told roughly half the route is unwatched (5× the truth) and never learns which 10 km; on a 53 km route with a 10 km gap 'most of the route' is 19 %.
  - suggested fix: Render the record: AR f"ما في حاجز متابَع على {x['km']:.0f} كيلو ({x['from_km']:.0f}–{x['to_km']:.0f} كيلو من الطريق)", EN f"no tracked checkpoint for {x['km']:.0f} km ({from}–{to} km in)"; drop the duplicate cover_note when a blind_stretch doubt was spoken.
- **RENDERERS-V20 · F326 · medium** — The spoken route answer never names the resolved origin/destination, and the MCP payload drops them — a fuzzy mis-resolution is invisible — `serve/mcp_server.py:998`
  - scenario: A caller types 'بيتونيا' meaning Beitunia but the resolver fuzzy-matches 'بيت اونيا' or a station/checkpoint of a similar name; the answer says 'الطريق سالك على الأغلب' about a different journey and neither the sentence nor the structured MCP payload says what was resolved. PLAN §6 G1 requires every answer to 'name the resolved subject'.
  - suggested fix: Copy `d['origin']`/`d['destination']` into the MCP payload and open both sentences with 'من {origin.place} لـ{destination.place}: …' / 'From X to Y: …'; echo `kind` in the REST origin/destination blocks.
- **RENDERERS-V21 · F327 · medium** — The age of the on-route readings is never spoken: 'تقارير حديثة'/'recent reports' covers anything up to the 6-hour max_assert ceiling — `serve/mcp_server.py:999`
  - scenario: Three checkpoints last reported open 5 h 40 min ago, nothing since: verdict likely_open, sentence '3 من 8 حواجز عليها تقارير حديثة' — the same words as three 5-minute-old readings. DESIGN law 1 (age changes the answer) and G1 (the age of the newest datum in every answer) are met by checkpoint_status but not by the route answer; the MCP instructions promise 'the answer already carries … how old the …
  - suggested fix: Select `staleness_band` in ON_ROUTE_SQL; speak the newest and oldest known ages ('أحدث تقرير قبل N دقيقة، أقدمها قبل M') in both renderers; treat a route whose freshest on-route reading is in the 'stale' band as a doubt ('كل التقارير أقدم من ساعتين') so `open` is not spoken over stale-band evidence.
- **RENDERERS-V22 · F264 · medium** — Arabic place_profile states the checkpoint flow with no age while the English carries it — `serve/mcp_server.py:1197`
  - scenario: place(place=حوارة): Arabic 'حوارة: الحاجز سالك، 3 حدث بآخر 30 يوم' with no age, on a reading that may be five hours old within band; when flow is `unknown` the Arabic prints 'الحاجز غير معروف' with no last-known value or age either. Law 1 broken in the primary language.
  - suggested fix: Use _flow_phrase(live) + _age_ar as checkpoint_status does; mirror last_known_flow when unknown.
- **RENDERERS-V23 · F171 · medium** — MCP databank headline dates precision-unknown rows to 2009-01-01 and reports the series span from the returned page, not the series — `serve/mcp_server.py:1475`
  - scenario: databank(category='demolitions', indicator='demolitions.locality') → 'demolitions.locality.structures: 416 structures في 2009-01-01، القدس' — a cumulative 2009→Aug-2026 total for Jabal al-Mukabbir spoken as an event on 1 Jan 2009 in Jerusalem; the default call says 'السلسلة من 2023 إلى 2026' for a series that starts in 2009 because only the 10 newest rows were fetched; nothing says the corpus was …
  - suggested fix: Render by precision: year → 'في 2026'; month/day → the date; unknown → 'إجمالي تراكمي من {coverage_start} إلى {coverage_end}' from attrs; speak attrs.locality_name when place is a governorate; take the span from a separate min/max query (or the categories endpoint's from/to) instead of the page; test with a fixture payload by monkeypatching serve.mcp_server.api.
- **RENDERERS-V24 · F496 · low** — EN checkpoints_near omits army/police/settler sightings the Arabic names per checkpoint — `serve/mcp_en.py:98`
  - scenario: Ein Sinya open with army present: Arabic 'عين سينيا سالك وفي جيش', English 'عين سينيا open'. DESIGN law 8 (presence is a sighting that qualifies the flow answer) holds in one language.
  - suggested fix: Append ' (army present)' etc. from PRESENCE as checkpoint_status does (:59-60).
- **RENDERERS-V25 · F497 · low** — EN checkpoints_summary lists a shared name twice; the Arabic deduplicates it — `serve/mcp_en.py:115`
  - scenario: Two distinct places named النبي يونس closed: English reads as a duplicate row bug (the QA pass reported it) while Arabic says '(and one more closed under a repeated name)'.
  - suggested fix: Mirror the dedupe and the 'shared name' remark; prefer name_en when present.
- **RENDERERS-V26 · F470 · low** — English fuel answer still names one date for every product (the QA item was fixed only in Arabic) — `serve/mcp_en.py:213`
  - scenario: answer says 'ساري من 2026-09-01 (وأحدثها 2026-09-07)' while answer_en says 'in force from 2026-09-01' for the 7.65 petrol price — the AR/EN parity the contract promises (PLAN §7 P0-A.2) is broken on the fuel tool.
  - suggested fix: Mirror the dates logic from mcp_server.fuel_prices in mcp_en.fuel_prices and add the case to the answer-contract test.
- **RENDERERS-V27 · F498 · low** — The spoken precision note names at most three weak types; with round 8 the fourth (land_levelling 0.667) is dropped from speech — `serve/mcp_en.py:278`
  - scenario: A window containing all four weak types: the payload marks land_levelling 0.667 but the sentence a voice bot reads aloud says nothing about it.
  - suggested fix: Drop the [:3] cap (the list is short by construction) or say 'and N more under the gate'.
- **RENDERERS-V28 · F499 · low** — EN databank on an invalid category prints '0 rows from None.' — `serve/mcp_en.py:468`
  - scenario: databank(category="Demolitions") (capital letter fails the [a-z0-9_] check): English '0 rows from None.'
  - suggested fix: Render `error` payloads as 'No category named …' and include the category name in the error dict.
- **RENDERERS-V29 · F500 · low** — EN insights loses its English entirely on a not-found place ('%g' on None), unlike every other tool — `serve/mcp_en.py:478`
  - scenario: insights(place="Ramalla"): Arabic explains, English is absent — the reader cannot tell a gap from a refusal.
  - suggested fix: `if d.get("found") is False: return "Place not recognised."` and guard the format with `or 0`.
- **RENDERERS-V30 · F501 · low** — EN place_history omits the worst day and EN data_gaps omits the top gaps and scout candidates the Arabic names — `serve/mcp_en.py:571`
  - scenario: place(view=history, place=حوارة, days=7): the Arabic reader learns which day had the most closures; the English reader does not. about(section=gaps): English gives counts, Arabic names the failing supply lines.
  - suggested fix: Compute the worst day from `series` in EN as the Arabic does; list `gaps` with severity ≥ 3 and `scout.top_candidates` in EN.
- **RENDERERS-V31 · F461 · low** — Age phrases floor to the hour: 119 minutes is spoken as 'قبل 1 ساعة' / '1h ago' — `serve/mcp_server.py:74`
  - scenario: Fact A asked 119 minutes after the report: the answer says the reading is one hour old; a traveller weighing a 2-hour-old closure hears half its age.
  - suggested fix: Render half-hours below 6 h ('قبل ساعة ونص', '1h 55m ago') or round to the nearest 10 minutes; keep exact minutes in the payload.
- **RENDERERS-V32 · F502 · low** — Arabic connectivity_now asserts 'working normally' for any status outside unknown/outage/degraded — the mirror image of the fixed English `ok` bug — `serve/mcp_server.py:590`
  - scenario: The ingester adds a `partial` value or the REST omits `status` on an error path: Arabic says the West Bank internet is working normally.
  - suggested fix: Make the else branch explicit for 'normal' only and print the raw status otherwise, as the English does; share one vocabulary constant with ingest/sources/connectivity.py:119-124.
- **RENDERERS-V33 · F534 · low** — Only 5 of the 8 sampled waypoints are spoken, so the destination-end third of the route is never named — `serve/mcp_server.py:970`
  - scenario: Ramallah→Nablus: 'يمر عبر' stops around Sinjil/Lubban (~km 33) and never names Za'tara-area towns or Huwara, the stretch where the decisive checkpoints are.
  - suggested fix: Speak all sampled waypoints, or sample 5 buckets when the sentence must stay short; never drop the last bucket.
- **RENDERERS-V34 · F535 · low** — Presence sightings (`cautions`) are in the payload but spoken by neither renderer, despite the module saying they are surfaced for families planning a journey — `serve/mcp_server.py:1007`
  - scenario: Settlers reported at a checkpoint on the route 20 minutes ago (value present, within the 2 h ceiling): the spoken answer is 'الطريق سالك على الأغلب' with no mention; only a client that parses `cautions` learns it.
  - suggested fix: One clause per renderer: AR 'شوهد {جيش|مستوطنين|شرطة} عند X قبل N دقيقة'; EN 'army/settlers seen at X N min ago'.
- **RENDERERS-V35 · F520 · low** — `series` for one indicator fetches the same series twice; `compare` runs two queries per indicator (up to 12 connections) — `serve/mcp_server.py:1272`
  - scenario: `series(indicators="casualties.annual_total")` runs four statements on four connections, two of them the identical ordered fetch of every point of the series, serialises both copies through the loopback, and discards one; a six-indicator compare opens twelve connections against a 17-session budget.
  - suggested fix: One points query `WHERE v.indicator = ANY(%s)` grouped in Python and one meta query `WHERE indicator = ANY(%s)`; give `trend` a single-series path (or call `_series` once).
- **RENDERERS-V36 · F456 · low** — `licenses` tool description hard-codes '6,562 rows' share-alike; the registry now has 7,838 after OONI was re-read — `serve/mcp_server.py:1691`
  - scenario: A stdio caller (Fawwaz/Sameera) or an alias user reads a share-alike count that is 1,276 rows short of the registry's own answer in the same payload (`tiers.commercial_sharealike`).
  - suggested fix: Delete the number from both strings; the payload's `tiers` block is the source.
- **RENDERERS-V37 · F457 · low** — The stdio transport still lacks instructions, resources, prompts, ping and the licence block while mcp_http.py's docstring claims one table, two equal transports — `serve/mcp_server.py:2024`
  - scenario: The on-host agents never receive the reading contract ('unknown is never the last value') or the route/place prompts that encode call order; a bug fixed in `_handle` (argument validation, error scrubbing) is not fixed in `main()`.
  - suggested fix: Make `main()` parse each line and call `mcp_http._handle(msg, ip="127.0.0.1", tier="house")` (it is transport-agnostic and already handles initialize/ping/resources/prompts/tools), keeping only stdout framing here; delete the duplicated dispatcher.
