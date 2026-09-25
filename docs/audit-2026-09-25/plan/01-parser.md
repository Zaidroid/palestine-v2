# Plan 01 · Checkpoint status parser (the sign of every road fact)

Phase 1 — Safety inversions — a wrong 'open' or a hidden closure. Read `00-README.md` first (setup, rules, the per-task loop).

## Scope

- **Files you may edit:** `cascade/checkpoint_text.py`, `tests/test_checkpoint_text.py`
- **Tests to run after every task:** `tests/test_checkpoint_text.py tests/test_palhub_roads.py tests/test_poller.py` (with the local DB sourced), then the full suite once at the end of the file.
- **Area rules:** Every inversion (closed read as open, absence read as presence, conditionals/questions/future read as assertions) gets a regression test with the exact Arabic input before the fix. Prefer failing toward `unparsed`/`question` over guessing. Keep HANDOFF §4 traps (token boundaries, short substrings, negator consumption, ما زال). The parser has no version constant; a change affects new rows only until a --full re-import on main-server — say so in your report.

- Confirmed tasks: 14 · verify-first tasks: 15 · refuted (skip): 1

## A. Confirmed tasks (independently verified — do these first, in order)

### PARSER-01 · F001 · critical · safety
**'ما' as the conjunction in بعد ما / قبل ما / زي ما / حسب ما / كل ما is read as a negator and flips the following status**

- **Where:** `cascade/checkpoint_text.py:154`
- **What goes wrong:** 'بعد ما سكروا الحاجز' (after they closed the checkpoint) is stored as OPEN; 'بعد ما فتحوا الحاجز سالك' (after they opened it, it's flowing) is stored as CLOSED. 'بعد ما', 'قبل ما', 'زي ما', 'مثل ما', 'حسب ما', 'كل ما', 'لما' are among the most frequent dialect conjunctions and each one precedes a status verb naturally.
- **Fix:** In _negated, skip 'ما' when toks[j-1] is in a small head set {بعد, قبل, زي, مثل, حسب, كل, اول, عقب, بس, مثلما} or when 'ما' is followed by a personal pronoun (هو/هي/هم) — those are relative/temporal ما, not negation. Keep 'ما' + verb/adjective negation. Add the four lines as regressions.
- **Evidence (audited code):**
```
cascade/checkpoint_text.py:154 `NEGATORS = frozenset(["مش", "ما", "مو", "بدون", "بلا", "غير"])`; :461-490 _negated looks two tokens back and only exempts the CONTINUATIVES (زال…). Run: read("بعد ما سكروا الحاجز") -> flow open@0.8; read("زي ما هو مسكر") -> open@0.8; read("حسب ما سمعت مسكر") -> open@0.8; read("بعد ما فتحوا الحاجز سالك") -> flow closed@0.8 (فتحوا flipped to closed, then most-restrictive beats سالك).
```
- **Verifier's check:** Confirmed. NEGATORS contains 'ما' (cascade/checkpoint_text.py:154). _negated (:461-490) looks up to two tokens back and exempts only CONTINUATIVES (:481-482) and a negator already consumed by a nearer lexicon word. Run here: 'بعد ما سكروا الحاجز', 'زي ما هو مسكر' and 'حسب ما سمعت مسكر' each give flow open@0.8. 'بعد ما فتحوا الحاجز سالك' gives flow closed@0.8: فتحوا flips to closed and then wins as the most restrictive value. One small inaccuracy: 'لما' in the failure scenario is a single token and is not affected. The mechanism and every quoted example reproduce.
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### PARSER-02 · F005 · critical · safety
**'ما' as a relative particle is read as a negator and inverts closed to open**

- **Where:** `cascade/checkpoint_text.py:154`
- **What goes wrong:** A road channel posts 'عطارة حسب ما سمعت مسكر' (Atara is closed, as I heard). v1 files the line for عطارة; checkpoints.py:174 re-reads it; the flow fact is `open` at 0.80 -> state_observation checkpoint_flow=open -> belief 0.85 (parse confidence unused) -> checkpoint_serving flow=open, passable=true. 'حسب ما', 'زي ما', 'مثل ما', 'بعد ما', 'قبل ما', 'كل ما', 'طول ما' are standard Palestinian frames; three of the five probes above produce a false open on a closed checkpoint.
- **Fix:** Treat 'ما' as a negator only when j == i-1 (directly before the status) or when followed by في/فيه/عاد/بقي/بقيش/يوجد; never when the preceding token is one of حسب/زي/زى/مثل/بعد/قبل/كل/طول/عشان/وقت/لما. Add the five probes as regression cases in tests/test_checkpoint_text.py.
- **Evidence (audited code):**
```
NEGATORS = frozenset(["مش", "ما", "مو", "بدون", "بلا", "غير"]) and _negated() at :470 `for j in range(max(0, i - 2), i):` accepts any of them within two tokens with no lexicon word between. Measured through read(): "زي ما هو مسكر" -> bot:flow=open; "حسب ما قالوا مغلق" -> open; "مثل ما كان مغلق" -> open; "عطارة حسب ما سمعت مسكر" -> open; "بعد ما فتح الحاجز الوضع هدي" -> closed.
```
- **Verifier's check:** Reproduced through read(): 'زي ما هو مسكر', 'حسب ما قالوا مغلق', 'مثل ما كان مغلق' and 'عطارة حسب ما سمعت مسكر' all give bot:flow=open(0.8). 'بعد ما فتح الحاجز…' gives closed. That is four false opens out of five probes, not the three the finding says. Cause: NEGATORS at cascade/checkpoint_text.py:154 contains 'ما'. _negated (:461-484, loop at :470) looks two tokens back, and its only guards are CONTINUATIVES (زال…) and 'consumed by a closer lexicon word'. هو/قالوا/كان/سمعت are not lexicon words, so the closed value gets _FLIP'ed to open (:569-570). The path is live: ops/sync-checkpoints.sh → …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### PARSER-03 · F006 · critical · safety
**Uncertainty and conditionals without an interrogative particle are asserted as open**

- **Where:** `cascade/checkpoint_text.py:192`
- **What goes wrong:** 'I don't know if Huwara is open' and 'if the checkpoint opens, tell us' are each written checkpoint_flow=open at 0.90 and served passable — evidence manufactured from the absence of knowledge.
- **Fix:** Add "ما بعرف", "مابعرف", "حد بعرف", "حدا بعرف", "بعرف اذا", "حد يعرف" to QUESTION_PHRASES; in read(), a clause whose first token is اذا/إذا/لو/في حال/بحال is conditional -> modality 'question' (or a new 'conditional' modality, which needs the CHECK in migration 040 extended).
- **Evidence (audited code):**
```
QUESTION_PHRASES :192-199 holds "حدا يعرف", "مين بيعرف", "حدا بيعرف", "بدنا نعرف", "بدي اعرف" but not the dialect 'ما بعرف'/'حد بعرف'; nothing handles اذا/لو. Measured: "ما بعرف اذا حوارة سالك" -> assertion bot:flow=open; "حد بعرف اذا حوارة سالك" -> open; "اذا فتح الحاجز خبرونا" -> open; "اذا سالك احكولنا" -> open.
```
- **Verifier's check:** Reproduced with /tmp/.../verify/b1_probe.py. 'ما بعرف اذا حوارة سالك', 'حد بعرف اذا حوارة سالك', 'حدا بعرف اذا حوارة سالك', 'مابعرف اذا…', 'اذا فتح الحاجز خبرونا', 'لو فتح…' and 'اذا سالك احكولنا' all come back as modality=assertion with flow=open at 0.90. QUESTION_PHRASES (cascade/checkpoint_text.py:192-199) has 'حدا يعرف' and 'حدا بيعرف' but not the common dialect 'حدا بعرف' or 'ما بعرف'. QUESTION_OPENERS does not include اذا or لو, and nothing else in the module handles them (grep finds no اذا). _negated does not rescue these lines: ما sits more than two tokens before سالك. The questions-ar …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### PARSER-04 · F002 · critical · safety
**Negators are not recognised behind a fused waw or in fused spellings, so 'ومش سالك' serves OPEN and 'وما في جيش' serves army PRESENT**

- **Where:** `cascade/checkpoint_text.py:478`
- **What goes wrong:** A channel writes 'عطارة ومش سالك' (Atara, and NOT flowing) — the ordinary way to append a status after the place — and the line is stored as checkpoint_flow=open at 0.9, an assertion that reaches belief and the API. 'سالك ومافي جيش' (flowing, no army), the commonest good-news shape, is stored as army present. The 2026-08-01 fix (DECISIONS: 'a negator is consumed by the first lexicon word it reaches', HANDOFF §4) covers 'المربعة بدون جيش سالكة' but not the same sentence with a waw: 'المربعة سالكة وبدون جيش' records idf present. Frequency in the road corpus cannot be measured in this checkout (no v1 SQLite), but both shapes are standard Palestinian dialect.
- **Fix:** In _negated, test the token through the same waw/fa peel _lex uses (`_bare_neg(tok) in NEGATORS` where _bare_neg strips one leading و/ف when len>=3) and extend the existential set: NEGATORS += {"مافي", "مافيش", "مفيش", "ماف"}; also treat "وما"/"ومش"/"وبدون"/"وبلا"/"وغير" identically. Add the six lines above to tests/test_checkpoint_text.py as inversion regressions.
- **Evidence (audited code):**
```
cascade/checkpoint_text.py:478 `if toks[j] not in NEGATORS and not la_fi:` compares the raw token; NEGATORS (:154) = {"مش", "ما", "مو", "بدون", "بلا", "غير"}. _lex (:255) strips a leading و for lexicon words (`if len(tok) >= 4 and tok[0] == "و" and tok[1:] in table`) but _negated never does. Run in this checkout: read("عطارة ومش سالك") -> flow open@0.9; read("سالكة وما في جيش") -> flow open + presence idf@0.88; read("حوارة سالك وبدون تفتيش") -> presence inspection@0.88; read("عطارة مسكر وبلا جيش") -> presence idf; read("جبع سالك مافي جيش") / "سالك مافيش جيش" / "عطارة سالكة ومافيش جيش" -> presence idf@0.88.
```
- **Verifier's check:** Confirmed at cascade/checkpoint_text.py:478. _negated compares the raw token with NEGATORS (:154) and never strips the leading waw, while _lex (:255) does strip it for lexicon words. The PHRASES entry 'مش سالك' (:104) is matched on whole tokens, so it also misses 'ومش'. I ran every example in this checkout. 'عطارة ومش سالك' gives flow open@0.9 (both). 'سالكة وما في جيش', 'جبع سالك مافي جيش', 'سالك مافيش جيش', 'عطارة سالكة ومافيش جيش' and 'المربعة سالكة وبدون جيش' each give presence idf@0.88. 'حوارة سالك وبدون تفتيش' gives presence inspection. The unfused 'المربعة بدون جيش سالكة' correctly give …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### PARSER-05 · F003 · critical · safety
**An emoji-only per-direction line collapses to one 'both' reading and the FIRST emoji in dict order wins: 'الداخل ✅ الخارج ❌' serves OPEN both ways**

- **Where:** `cascade/checkpoint_text.py:617`
- **What goes wrong:** A channel posts the palhub-style shorthand 'الداخل ✅ الخارج ❌' (inbound OK, outbound closed). Because no word carries a status the emoji branch runs, finds ✅ first, and stores flow=open for direction 'both' — the closed outbound lane is served as open. Swapping the emoji order in the text does not change the answer.
- **Fix:** When the clause has ≥2 direction positions, bind each emoji occurrence to the nearest preceding direction word and emit one fact per direction with its own token position; when emoji conflict inside one direction (or no direction), emit the most restrictive value or return unparsed — never let dict order decide. Tests for the four lines.
- **Evidence (audited code):**
```
cascade/checkpoint_text.py:617-622 `if not out and not any(t in _FUEL_NOUNS for t in toks): for ch, v in EMOJI_FLOW.items(): if ch in raw_clause: out.append(("flow", v, 0.65, -1)); break` — one fact, token_pos -1, and _assign_directions maps pos<0 to ("both", False). EMOJI_FLOW (:183) lists ✅/🟢 before ❌/⛔. Run: read("الداخل ✅ الخارج ❌") -> flow open@0.65 (both); read("للداخل 🟢 للخارج 🔴") -> open@0.65; read("جبع دخول ✅ خروج ❌") -> open@0.65; read("بيت ايل الداخل❌ الخارج✅") -> open@0.65.
```
- **Verifier's check:** Confirmed at cascade/checkpoint_text.py:617-621. The emoji fallback walks EMOJI_FLOW in dict order (✅ is listed before ❌, :183), appends one fact with token_pos -1 and breaks. _assign_directions maps pos<0 to ('both', False) (:436-438). Run here: 'الداخل ✅ الخارج ❌', 'جبع دخول ✅ خروج ❌' and 'بيت ايل الداخل❌ الخارج✅' all give flow open@0.65 for direction both. The last one shows that dict order, not text order, decides the value. '🔴' is not in EMOJI_FLOW, which fits the comment calling it an attention marker, so the 🟢/🔴 example is weaker. The ✅/❌ cases alone establish the defect: an outbound la …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### PARSER-06 · F019 · high · safety
**'فتح النار' (opened fire) is read as the checkpoint being open**

- **Where:** `cascade/checkpoint_text.py:62`
- **What goes wrong:** A shooting at Huwara is filed as flow=open at 0.90, presence idf; checkpoint_serving says passable=true with army present. The traveller is sent toward live fire.
- **Fix:** Add ('فتح النار','presence','idf'), ('فتحوا النار','presence','idf'), ('فتحت النار','presence','idf'), ('اطلاق النار','presence','idf'), ('اطلاق نار','presence','idf') to PHRASES so the tokens are consumed before the single-token loop, and never infer flow from them.
- **Evidence (audited code):**
```
:62 `"فاتح": "open", "فاتحه": "open", "فتح": "open", "فتحت": "open",` and :63 `"فتحوا": "open"`. Measured: "الجيش فتح النار على المركبات عند حاجز حوارة" -> bot:flow=open + presence=idf; "فتحوا النار على الشباب عند الحاجز" -> bot:flow=open.
```
- **Verifier's check:** Reproduced. 'الجيش فتح النار على المركبات عند حاجز حوارة' gives presence=idf plus flow=open(0.9). 'فتحوا النار على الشباب عند الحاجز' and 'العسكر فتحوا النار' give flow=open(0.9). فتح/فتحت/فتحوا are flow=open at :62-63, and no PHRASES entry consumes 'فتح النار', so the single-token loop (:552-571) emits open. On the live path (checkpoints.py:174, 192-207 → belief 0.85), checkpoint_serving gives passable=true with present=['idf']. resolve/corridor.py:535-543 only attaches presence as info, and the verdict is decided by flow alone (:221-222, 362-393), so the route can read likely_open. How often …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### PARSER-07 · F020 · high · safety
**Dual/plural/dialect closure forms and 'ممنوع/منع الدخول' are not in the lexicon, so closures are lost and mixed lines read open**

- **Where:** `cascade/checkpoint_text.py:83`
- **What goes wrong:** A channel reports 'حوارة وزعترة مغلقان' — the dual is skipped, nothing is written, the previous `open` belief stands and decays for up to 6 hours in confident clothes; in a mixed line the only recognised word is سالك and the closed checkpoints are written open (measured). 'منع الدخول والخروج' records soldiers but not the closure, so passable stays true.
- **Fix:** Add مغلقان/مغلقتان/مغلقتين/مسكرين/مسكرات/مسكرينها/مقفول/مقفوله/مقفولين/سكروه/سكرت/اغلق/اغلقت/يغلق/تغلق/ساكرين; phrases 'ممنوع الدخول'/'ممنوع الخروج' -> closed for that direction, 'منع الدخول'/'منعوا الدخول'/'منع الخروج' likewise, 'منع ... المرور' within 3 tokens -> closed. Regression cases for each.
- **Evidence (audited code):**
```
FLOW_WORDS closed entries at :83-86 are مغلق/مغلقه/مغلقين/مقفل/مقفله/مسكر/مسكره/موقوف/مسدود/مسدوده/سكروا/سكر/اغلاق only. Measured: "الحواجز مسكرين" -> unparsed; "الحاجز مقفول" -> unparsed; "البوابة مقفولة" -> unparsed; "اغلقت قوات الاحتلال حاجز حوارة" -> unparsed; "الاحتلال يغلق حاجز عورتا" -> unparsed; "سكروه" -> unparsed; "ممنوع الدخول لنابلس من حوارة" -> unparsed; "الجيش منع الدخول والخروج من حوارة" -> presence=idf only; "منعوا الناس من المرور" -> unparsed; "مفرق جيت وحاجز صرّة مغلقان بالاتجاهين مع تواجد للمستـ.ـوطنين" (real corpus line, claim 450) -> presence=settlers only, no closure.
```
- **Verifier's check:** Reproduced. These all come back modality=unparsed: 'الحواجز مسكرين', 'الحاجز مقفول', 'البوابة مقفولة', 'اغلقت قوات الاحتلال حاجز حوارة', 'الاحتلال يغلق حاجز عورتا', 'سكروه', 'ممنوع الدخول لنابلس من حوارة', 'منعوا الناس من المرور', 'حوارة مغلقان' and 'الحاجز ما بيسكروه'. 'الجيش منع الدخول والخروج من حوارة' comes back presence=idf only. Claim 450's clause 'مفرق جيت وحاجز صرّة مغلقان…' comes back settlers only. FLOW_WORDS closed entries (:82-86) lack the dual/plural مغلقان/مسكرين/مقفول* and verb forms اغلق*/يغلق/سكروه. PHRASES (:128-136) covers only منع/ممنوع المرور, not الدخول/الخروج. _lex (:238 …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### PARSER-08 · F021 · high · safety
**'The closure was lifted / the jam is over' asserts closed or congested and restarts the closure's clock**

- **Where:** `cascade/checkpoint_text.py:86`
- **What goes wrong:** The one message a waiting family needs — 'the closure at Huwara was lifted' — is written checkpoint_flow=closed with a fresh observed_at, so the served closure is refreshed rather than ended and stays 'live' for another half-life.
- **Fix:** In _scan_clause, when a CLEARING word (or رفع/رفعوا/انتهي/انتهت/خلص/خلصت/راحت/زالت/فكوا) is within two tokens before a closure/congestion NOUN (اغلاق, الاغلاق, ازمه, زحمه, حصار, محسوم), emit ('flow','open',0.80) instead of the noun's value. Regressions for the six probes.
- **Evidence (audited code):**
```
:86 `"اغلاق": "closed"` is a noun; the cleared-open inference at :627-631 fires only when no flow fact exists, so a clearing verb before a closure noun yields the noun's value. Measured: "تم رفع الاغلاق عن حاجز حوارة" -> bot:flow=closed; "انتهى الاغلاق على حوارة" -> closed; "خلص الاغلاق" -> closed; "راحت الزحمة" -> congested; "انتهت الازمة على عورتا" -> congested; "خلصت الازمة" -> congested.
```
- **Verifier's check:** Reproduced. 'تم رفع الاغلاق عن حاجز حوارة', 'انتهى الاغلاق على حوارة' and 'خلص الاغلاق' → flow closed at 0.90. 'راحت الزحمة', 'انتهت الازمة على عورتا' and 'خلصت الازمة' → congested at 0.90. In every case Reading.cleared=True. Cause: 'اغلاق' (:86) and 'ازمه'/'زحمه' are FLOW_WORDS, found via _lex article-stripping. The cleared→open inference (:629-631) fires only when no flow fact exists. _cleared_nearby is consulted only for presence nouns, never for flow nouns. The importer ignores r.cleared (checkpoints.py:180-210). Line numbers are accurate; the inference is at 629-631, with a comment at 627 …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### PARSER-09 · F013 · high · safety
**'راح' (dialect future particle) is a CLEARING word: 'راح يسكروا الحاجز' (they are going to close it) infers OPEN**

- **Where:** `cascade/checkpoint_text.py:146`
- **What goes wrong:** 'راح' is both 'left' and the future marker ('is going to'). 'الجيش راح يسكر الحاجز' (the army is about to close the checkpoint) is stored as army ABSENT and road OPEN — the exact inversion the layer exists to prevent, on the line that most needs to be right. The imperfect verbs يسكر/يسكروا/بيسكروا are not in FLOW_WORDS, so nothing competes with the inferred open.
- **Fix:** Treat راح/رح/بد/بده/بدهم followed by an imperfect verb (token starting with ي/ت/ب + 3 letters, or any token whose ي/ب/ت-stripped form is in FLOW_WORDS/PRESENCE_WORDS) as a FORECAST: return modality 'forecast' (not evidence) or at least never set `cleared` from راح when the next token is not a presence noun. Add يسكر/يسكروا/بيسكروا/تسكر and يفتح/يفتحوا/بيفتحوا as forecast-only forms. Regression tests for the four lines.
- **Evidence (audited code):**
```
cascade/checkpoint_text.py:144-149 `CLEARING_WORDS = frozenset([... "راح", "راحت", "راحوا", ...])`; :553 `cleared = any(t in CLEARING_WORDS ...)`; :629-632 `if (cleared and not any(a == "flow" ...) and not any(a == "presence" ...)): out.append(("flow", "open", 0.72, -1))`. Run: read("راح يسكروا الحاجز") -> flow open@0.72; read("راح يسكروا") -> open@0.72; read("الجيش راح يسكر الحاجز") -> absence idf@0.78 + flow open@0.72; read("راح الجيش يسكر") -> same.
```
- **Verifier's check:** Confirmed. 'راح', 'راحت' and 'راحوا' are in CLEARING_WORDS (cascade/checkpoint_text.py:146). `cleared` is computed over the whole line (:553). When no flow or presence fact exists, the clearing branch appends ('flow','open',0.72,-1) (:629-632). The imperfect forms يسكر/يسكروا are not in FLOW_WORDS (only سكر and سكروا are), so nothing competes. Run here: 'راح يسكروا الحاجز' and 'راح يسكروا' give flow open@0.72. 'الجيش راح يسكر الحاجز' and 'راح الجيش يسكر' give absence idf@0.78 plus flow open@0.72. No code tells the future-marker راح apart from the verb 'left'. The existing tests only pin the 'l …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### PARSER-10 · F022 · high · safety
**'X سالك ولا لا' (a question) reads as open, while 'X سالك ولا زحمة' (a reassurance) reads as a question**

- **Where:** `cascade/checkpoint_text.py:353`
- **What goes wrong:** 'عورتا سالك ولا لا' without a question mark is exactly defect #1 in this module's docstring (questions become facts, biased toward feared-closed checkpoints) and is served as open. The most common all-clear ('open, no jam') is discarded as a question.
- **Fix:** In _is_question: 'ولا' followed by لا/لأ/لاء or ending the line -> question regardless of flow values; 'ولا' followed by a congestion/presence noun with only ONE opposing flow value -> not a question (and treat that 'ولا' as a negator for the following noun in _negated). Regression cases for both.
- **Evidence (audited code):**
```
:353-356 `if "ولا" in toks: vals = {v for v in (_lex(t, FLOW_WORDS) for t in toks) if v}; if len(vals) >= 2: return True`. Measured: "عورتا سالك ولا لا" -> assertion bot:flow=open; "عورتا سالك ولا" -> assertion open; "حوارة سالك ولا زحمة" -> question; "حوارة سالك ولا ازمة" -> question.
```
- **Verifier's check:** Reproduced. 'عورتا سالك ولا لا' and 'عورتا سالك ولا' give assertion bot:flow=open(0.9). 'حوارة سالك ولا زحمة', 'حوارة سالك ولا ازمة' and 'حوارة سالك ولا في زحمة' give question. _is_question (:342-362) treats 'ولا' as a question only when two distinct FLOW values are present (:353-356). 'لا' is not a lexicon word, so 'X سالك ولا لا' has one value and becomes an assertion, while 'سالك ولا زحمة' (open/congested) becomes a question. The module's own comment at :350-352 says disjunctive questions often carry no '?'. Assertions go to checkpoint_flow (checkpoints.py:188-207), and questions are archiv …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### PARSER-11 · F014 · high · safety
**'لا يوجد جيش' and 'لا جيش ولا تفتيش' record the army PRESENT; a negator after the noun ('الجيش مش موجود') is invisible**

- **Where:** `cascade/checkpoint_text.py:476`
- **What goes wrong:** 'الحاجز مفتوح لا يوجد تفتيش' (open, no inspection) is stored as open WITH inspection present; 'لا جيش ولا تفتيش' (no army, no inspection) is stored as both present. These are cautions manufactured from reassurance — the inversion class DECISIONS 2026-08-03 (ولا في مستوطنين) says P2.4 exists to prevent — and the absence statement, the only evidence of 'they have gone', is lost.
- **Fix:** Extend la_fi to the existential verbs ("يوجد", "يوجد اي", "فش", "فيش"); treat 'لا' directly before a PRESENCE noun (never before a FLOW adjective, preserving 'لا مسكر') as negation, and 'ولا' between two presence nouns as negating the second; add a forward check for toks[i+1:i+3] in (("مش"|"ما"), ("موجود"|"موجوده"|"في"|"فيه")) → absence. Regression tests.
- **Evidence (audited code):**
```
cascade/checkpoint_text.py:476-478 `la_fi = (toks[j] in ("لا", "ولا") and j + 1 < len(toks) and toks[j + 1] in ("في", "فيه")) / if toks[j] not in NEGATORS and not la_fi: continue` — لا negates only before في/فيه, and _negated only looks BACKWARD. Run: read("لا يوجد جيش") -> presence idf@0.88; read("لا جيش ولا تفتيش") -> presence idf + presence inspection; read("لا في جيش ولا تفتيش") -> absence idf + presence inspection; read("الحاجز مفتوح لا يوجد تفتيش") -> open + presence inspection; read("الجيش مش موجود") -> presence idf; read("جيش ما في") -> presence idf.
```
- **Verifier's check:** Confirmed at cascade/checkpoint_text.py:476-478. la_fi fires only when لا/ولا comes directly before في/فيه, and _negated only looks backward. Run here: 'لا يوجد جيش' gives presence idf@0.88. 'لا جيش ولا تفتيش' gives presence idf plus presence inspection. 'لا في جيش ولا تفتيش' gives absence idf plus presence inspection. 'الحاجز مفتوح لا يوجد تفتيش' gives open plus presence inspection. 'الجيش مش موجود' and 'جيش ما في' both give presence idf. Every error runs toward a false caution, and the absence statement is lost. That is less dangerous than a false open, so I rate it medium rather than the cl …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### PARSER-12 · F023 · high · accuracy
**Negated existentials in the commonest spellings ('مافي', 'مفيش', 'لا يوجد', 'لا X ولا Y', 'ما في ولا') assert presence or congestion**

- **Where:** `cascade/checkpoint_text.py:476`
- **What goes wrong:** A reporter standing at Jaba' saying 'مافي جيش' is served as army present (checkpoint_idf=present at 0.85, sighting arrays in checkpoint_serving), and 'مافي ازمة' as congested — the inversion class HANDOFF §4 documents (28.31% of presence mentions are negated) recreated for the spellings people actually type.
- **Fix:** Add مافي/مافيش/مفيش/فش/فيش/ماكو to NEGATORS; extend la_fi to لا/ولا before يوجد/يوجدش/في/فيه and to لا/ولا directly before a PRESENCE or congestion noun when the clause holds no opposing flow word ('لا X ولا Y' lists). Regression cases for all eight probes.
- **Evidence (audited code):**
```
:476-477 `la_fi = (toks[j] in ("لا", "ولا") and j + 1 < len(toks) and toks[j + 1] in ("في", "فيه"))` is the only shape in which لا negates; NEGATORS :154 has no fused مافي/مافيش/مفيش/فش. Measured: "مافي جيش على الحاجز" -> presence=idf; "مفيش جيش" -> presence=idf; "ما في ولا جيش" -> presence=idf; "لا يوجد جيش على الحاجز" -> presence=idf; "لا جيش ولا شرطة" -> presence=idf + presence=police; "مافي ازمة" -> flow=congested; "لا يوجد ازمة" -> congested; "سالك ولا جيش ولا شي" -> open + presence=idf.
```
- **Verifier's check:** Reproduced, all eight probes. The fused and MSA forms 'مافي جيش', 'مفيش جيش', 'مافيش جيش', 'فش جيش', 'لا يوجد جيش', 'ما في ولا جيش', 'لا جيش ولا شرطة' → presence idf (and police) at 0.88. 'مافي ازمة' and 'لا يوجد ازمة' → congested. 'سالك ولا جيش ولا شي' → open plus idf present. The spaced forms 'ما في جيش' and 'ولا في جيش' correctly read as absence. Cause: NEGATORS (:154) holds only separate particles, and la_fi (:476-477) accepts لا/ولا only before في/فيه. In 'ما في ولا جيش', ولا sits directly before جيش, so la_fi fails; the ما in the window is skipped because 'في' is not a lexicon word... th …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### PARSER-13 · F015 · high · safety
**A clearing verb never clears a FLOW noun: 'انتهت الازمه' / 'خلصت الازمه' / 'راحت الازمه' serve CONGESTED at 0.9**

- **Where:** `cascade/checkpoint_text.py:559`
- **What goes wrong:** 'خلصت الازمة عالحاجز' (the jam at the checkpoint is over) — a standard all-clear — is stored as congested at 0.9, and because the flow fact exists the withdrawal inference never fires. The road is reported jammed by the message that says it cleared.
- **Fix:** In the flow branch, if the value is congested/slow/closed and _cleared_nearby(toks, i) is true (انتهت/خلصت/راحت/انفكت adjacent to the noun), emit ("flow", "open", 0.72, i) instead; add انفكت/انفك/فكت to CLEARING_WORDS. Tests for the three lines plus a guard that 'ازمه وراح الجيش' still reads congested.
- **Evidence (audited code):**
```
cascade/checkpoint_text.py:575-584: the flow branch is `flow = _lex(t, FLOW_WORDS); if flow: ... if _negated(toks, i): flip else out.append(("flow", flow, 0.90, i))` — no _cleared_nearby check (that exists only in the presence branch :596-606), and :629 infers open only `if not any(a == "flow" ...)`. Run: read("انتهت الازمه") -> flow congested@0.9; read("خلصت الازمه") -> congested@0.9; read("راحت الازمه") -> congested@0.9.
```
- **Verifier's check:** Confirmed, but the cited line is off. The flow branch starts at cascade/checkpoint_text.py:559 (`flow = _lex(t, FLOW_WORDS)`), with the append at 570-573; line 575 is the presence lookup. The flow branch never consults _cleared_nearby; only the presence branch does (:599). The inferred open at :629-632 is skipped once any flow fact exists. Run here: 'انتهت الازمه', 'خلصت الازمه', 'راحت الازمه' and 'خلصت الازمة عالحاجز' all give flow congested@0.9 with cleared=True. The error is a false caution, not a false open, so I rate it medium.
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### PARSER-14 · F024 · high · safety
**Clearing verbs used as future/aspect markers ('راح ي…', 'تركوا') infer `open`**

- **Where:** `cascade/checkpoint_text.py:631`
- **What goes wrong:** 'راح' is the ordinary Palestinian future marker. 'راح يسكروا حوارة' is written checkpoint_flow=open and, because belief ignores parse confidence, served at 0.85 as passable while the checkpoint is being closed.
- **Fix:** Infer open from a clearing verb only when an obstacle/presence noun (حاجز, بوابه, محسوم, جيش, اغلاق, ازمه, زحمه) is within two tokens of it; never when the next token starts with ي/ت/ن/ا-imperfect prefix or is a place name; drop 'تركوا'/'خلص' from bare inference. Add the three probes as regressions.
- **Evidence (audited code):**
```
CLEARING_WORDS :144-148 includes "راح", "راحت", "راحوا", "تركوا", "خلص"; :627-631 `if (cleared and not any(a == "flow" ...) and not any(a == "presence" ...)): out.append(("flow", "open", 0.72, -1))`. Measured: "راح يسكروا حوارة" (they are going to close Huwara) -> bot:flow=open(0.72); "راح يسكر الحاجز كمان شوي" -> open; "تركوا الناس واقفين على الحاجز ساعتين" -> open(0.72).
```
- **Verifier's check:** Reproduced. 'راح يسكروا حوارة', 'راح يسكر الحاجز كمان شوي' and 'تركوا الناس واقفين على الحاجز ساعتين' each give cleared=True and flow=open(0.72). CLEARING_WORDS (:144-148) contains راح/راحت/راحوا/تركوا/خلص. The line-wide `cleared` flag (:547) plus the rule at :627-631 infers open whenever no other flow or presence word was found. The verbs يسكروا/يسكر (imperfect) and واقفين are not in the lexicon, so nothing blocks the inference. Parse confidence is ignored by resolve/belief.py, so the served confidence is 0.85. The existing test at tests/test_checkpoint_text.py:326 covers only 'راح الجيش …' ( …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

## B. Verify-first tasks (reported by one reader, not independently checked)

For each: reproduce it with a failing test first. If you cannot reproduce it, do NOT change code — add one line to `SKIPPED.md` with the id and why.

- **PARSER-V01 · F093 · medium** — Dialect closure and entry-ban vocabulary is unparsed: سكرو/فتحو (alef-less), بفتشوا, فاضي, مقطوع, مسكرين/مسكرات/مغلقان, ممنوع الدخول / منعو الدخول produce no evidence — `cascade/checkpoint_text.py:58`
  - scenario: 'سكرو الحاجز' (they closed the checkpoint, the commonest alef-less spelling) and 'ممنوع الدخول' (entry forbidden) are retained as unparsed and contribute nothing to belief, so the last flow reading (often 'open') keeps decaying towards unknown instead of being replaced by closed — the traveller sees stale-open or unknown where the channel said closed. The road corpus is not in this checkout, so th …
  - suggested fix: Add the inflections (سكرو, فتحو, مسكرين, مسكرات, مغلقان, مغلقات, سالكات, مفتوحات, مقطوع/مقطوعه=closed, فاضي/فاضيه/رايق/رايقه/هادي/هاديه=open, طوابير/طابور=congested) and the entry-ban phrases (ممنوع الدخول, منع الدخول, منعو/منعوا الدخول, الدخول ممنوع, ممنوع الخروج, ممنوع المرور exists) with direction inbound/outbound; add جيب/جيبات to PRESENCE idf. Better: generate feminine/dual/plural/alef-less f …
- **PARSER-V02 · F118 · medium** — 'وقفة' (a vigil) reads as congestion and locative 'في حاجز X' reads as soldiers present — `cascade/checkpoint_text.py:76`
  - scenario: Every ordinary locative 'في حاجز حوارة' files an army sighting (checkpoint_idf=present, decays 45 min) and a protest vigil files a jam — false cautions that erode trust in the caution channel and pollute the presence persistence fit.
  - suggested fix: Match 'في حاجز'/'فيه حاجز' only when the next token is not a place-name token (end of clause, or followed by a status word); read وقفه as congestion only with سيارات/سير/مركبات within two tokens; add regressions.
- **PARSER-V03 · F094 · medium** — Uncertainty phrases are not questions: 'مش عارف سالك' is stored as CLOSED and 'مش عارف اذا الحاجز سالك ولا لا' as OPEN — `cascade/checkpoint_text.py:192`
  - scenario: A member asking 'I don't know if the checkpoint is open or not' becomes an assertion of open at 0.9; 'مش عارف سالك' becomes closed at 0.8. The module's own thesis (:8-14: questions became facts in v1) is defeated by the commonest hedge.
  - suggested fix: Add 'مش عارف', 'ما بعرف', 'مابعرف', 'مش عارفه', 'حدا جرب', 'مين جرب', 'اذا' + flow word to QUESTION_PHRASES / a hedge list that returns modality 'question'; make the 'ولا لا' tail (`ولا لا`, `او لا`) a question marker on its own. Tests.
- **PARSER-V04 · F119 · medium** — Sequenced and past-tense lines assert the EARLIER state; 'سالك او مسكر' asserts closed — `cascade/checkpoint_text.py:687`
  - scenario: The reopening message ('it was closed this morning, now flowing') is written closed with a fresh observed_at, so the served closure is extended by another half-life exactly when it ended.
  - suggested fix: Within a clause, if a status is preceded (<=2 tokens) by كان/كانت/كانوا/الصبح/قبل and another status is preceded by هلا/هسا/الان/صار/بعد/تم, keep the later; treat 'بعد + closure noun' as past; treat 'X او Y' with two opposing flow words as a question; add regressions.
- **PARSER-V05 · F105 · medium** — No regression test covers any of the six checkpoint_text inversions; 179 pattern tests are green while each reproduces — `tests/test_checkpoint_text.py:99`
  - scenario: The parser runs on every v1 update every two minutes (ingest/sources/checkpoints.py:187); a lexicon or negation edit that re-introduces any of these inversions passes the suite. The 0.94 hand audit (DECISIONS 2026-08-03) cannot be re-run because no road-line corpus is in the repo.
  - suggested fix: Add the constructed lines from findings 1-6 and 16-17 as parametrised inversion tests (expected value AND the value that must NOT appear); commit a small roads fixture (the 200-message gold set of PLAN P1-A.5) with hand verdicts and a DB-free scorer like ops/rescore_round.py for checkpoint_text.
- **PARSER-V06 · F127 · medium** — No regression coverage for the inversion classes measured here, none for the v1 import cursor, none for the Palhub loader's write logic — `tests/test_checkpoint_text.py:151`
  - scenario: Any of the parser inversions above can be reintroduced or left in place with the suite green; the ledger's '928 passed' says nothing about them.
  - suggested fix: Add the adversarial battery from this audit (both scratch scripts) as parametrised tests with expected facts; a rolled-back DB test for checkpoints.py that inserts two v1 rows with equal/older timestamps and asserts both import once; a unit test for the Palhub write-decision function extracted from load().
- **PARSER-V07 · F431 · low** — Feminine and verbal reassurance forms are missing, so all-clears are lost asymmetrically — `cascade/checkpoint_text.py:60`
  - scenario: 'it's flowing now' in verb form never refreshes belief, so a stale closure outlives its end (the opposite asymmetry to the missing closure forms, but it also starves the cadence fit).
  - suggested fix: Add the forms; regressions.
- **PARSER-V08 · F415 · low** — Dead lexicon keys: 'بطئ' and 'بطيئ' can never match normalized text (ئ→ي), so the common hamza spellings of 'slow' fall to unparsed — `cascade/checkpoint_text.py:66`
  - scenario: A line 'عين شبلي بطئ' (very common spelling) yields no slow reading; the same class of bug HANDOFF §4 lists first ('Arabic orthography must match on both sides') inside the one lexicon that is not folded at import.
  - suggested fix: Replace the dead keys with their normalized forms ('بطي', 'بطيي') and add a test asserting normalize(k)==k for every key in FLOW_WORDS/PRESENCE_WORDS/DIRECTION_WORDS/PHRASES/CLEARING_WORDS/QUESTION_*; or build the tables through normalize() at import as news.py does.
- **PARSER-V09 · F432 · low** — Dead lexicon keys that can never match a normalised token, and a presence-subject guard that never fires for موقوف — `cascade/checkpoint_text.py:66`
  - scenario: 'الحركة بطيئة' (normalises to بطييه) is unparsed; a soldier 'standing' at an entrance files a closure.
  - suggested fix: Normalise every key at import and assert `normalize(k) == k` in a test; add 'بطييه'; move موقوف into the guard's own branch or out of FLOW_WORDS.
- **PARSER-V10 · F416 · low** — 'في حاجز X' (at checkpoint X) is read as an army sighting; 'داخل'/'خارج' as prepositions become explicit directions — `cascade/checkpoint_text.py:128`
  - scenario: 'في حاجز عورتا ازمة' (at Awarta checkpoint there is a jam) records soldiers present at 0.92 — higher than a stated sighting (0.88) — from a locative preposition; 'the army inside the town' records an explicit inbound direction nobody stated.
  - suggested fix: Make 'في حاجز' predicative only when clause-final or followed by no further token (the test_bare_noun cases), and treat داخل/خارج as directions only when preceded by ل/لل/عال or article-bearing (الداخل/الخارج) — never the bare preposition before a noun.
- **PARSER-V11 · F433 · low** — The two parsers disagree on what 🟡 means — `cascade/checkpoint_text.py:184`
  - scenario: Road channels repost Palhub's glyph vocabulary; a bare 'عورتا 🟡' is served slow (passable, mild) while the source meant a medium jam, and the two lanes then contradict each other in corroboration.
  - suggested fix: Map 🟡/🟨 to congested in EMOJI_FLOW (or drop them from the emoji-only branch) and add a cross-parser consistency test.
- **PARSER-V12 · F417 · low** — Sentence punctuation is not a clause boundary, so a negator or direction in one sentence binds a status in the next — `cascade/checkpoint_text.py:208`
  - scenario: 'ما في اشي جديد. سالك' or 'بدون تفتيش. سالك' style two-sentence lines let the first sentence's particle flip the second's status.
  - suggested fix: Add `[.؟!|/]+` (a dot not between two Arabic letters — the censorship-dot rule already protects that case) to _CLAUSE_SPLIT and a test.
- **PARSER-V13 · F434 · low** — A '?' anywhere in the line, including inside a URL, turns the whole report into a question — `cascade/checkpoint_text.py:343`
  - scenario: Channel footers with tracking links (t.me/...?boost, ?start=) silently drop every assertion in that message from belief.
  - suggested fix: Strip URLs (https?://\S+) before the mark test; regression.
- **PARSER-V14 · F435 · low** — A single direction word binds every fact in the clause, including prepositional داخل/خارج, and direction_explicit is never read downstream — `cascade/checkpoint_text.py:425`
  - scenario: A 'both'-lane all-clear is narrowed to one lane and the other lane keeps decaying; a copy-channel 'سالك' (both, inferred) posted 3 minutes after an explicit 'مغلق للداخل' from an independent reporter wins the inbound slot purely on time.
  - suggested fix: Bind a flow fact to the clause's single direction only when the direction word is within two tokens or it is the only status; keep explicit=False otherwise; carry direction_explicit into state_current and prefer explicit over inferred within the corroboration window in checkpoint_serving.
- **PARSER-V15 · F436 · low** — 'غير/مش' before a normalcy adjective is flipped to closed — `cascade/checkpoint_text.py:491`
  - scenario: 'the situation is not normal' — a caution — is served as a closure at 0.80 and refreshes the closed clock.
  - suggested fix: Flip normalcy adjectives to congested (or emit no flow fact) instead of closed.

## C. Refuted — do not fix

- F025 A single-line bulletin naming several checkpoints collapses to one most-restrictive verdict attached to every place v1 matched (`cascade/checkpoint_text.py:687`) — The code behaviour is real. read() keeps one flow per direction across all clauses (:684-687). _CLAUSE_SPLIT (:208) has no '.', '|' or emoji boundary. checkpoints.py:192-207 writes every fact to the single pid. The Ramallah probe reproduces bot:closed. The premise that makes it a user-facing failure …
