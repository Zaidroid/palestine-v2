# Partner QA pass — 2026-09-23

An external reviewer ran all 27 tools over the public MCP endpoint and hand-checked
the answers against the data. This is the triage: what was verified, what was
fixed the same day, what is queued, and what is a decision rather than a bug.

Verdicts here are mine, from re-running each claim against the live server. Where a
claim turned out to be a design that nothing explained, that is written down too —
a design a reviewer cannot see is indistinguishable from a bug.

---

## Fixed the same day

**1. An English name could answer about the wrong checkpoint.** WORST OF THE SET.
`checkpoint_status("Zaatara")` returned عطارة — 11 km away, opposite state —
because the real checkpoint's registered Latin name is "Za'tara (Tapuach)" and the
apostrophe-free spelling matched nothing exactly, so it fell through to fuzzy
matching and took the nearest Latin lookalike at score 0.738, silently.
Fixed: aliases in migration `074` (`zaatara`, `zatar`, `zotara`, …) make the common
spelling an exact hit, and the match score now travels in the payload. Any match
below 0.9 says so in the answer; below 0.8 the doubt leads the sentence.
Re-verification found a second instance the same shape: `Hawara` resolved to عورتا
at 0.707 — now it opens with doubt instead of an answer.
Tests: `tests/test_name_safety.py`.

**2. `connectivity_now`'s English said "No current measurement of the network"
while the payload said status=normal, two minutes old.** The renderer knew the
status key `ok`; the API emits `normal`. Every healthy reading fell to a default
that asserted absence. Fixed, and an unrecognised status now names itself instead
of claiming silence. Tests: `test_surface_honesty.py`, `test_name_safety.py`.

**3. `crossings` denied data the server held.** It said no source has ever reported
Allenby while `checkpoints_summary` listed جسر الملك حسين with a reading 114
minutes old. Fixed: a crossing that is also a checkpoint is served from the
checkpoint layer and `basis` says which layer answered. Allenby now reads
`closed, age 116 min, basis checkpoint_flow`. Tests: `test_name_safety.py`.

**4. `latest_news area="Ramallah"` was a literal text match.** It returned two
items, one from July, because the channel text is Arabic and the filter was Latin.
It now resolves the name first. Re-verified: 3 items, newest same-minute.

**5. `place_pattern`'s headline contradicted its own hours.** It was binary — any
closed hour meant "usually closed", otherwise "usually open" — and answered
"usually open most hours" for Qalandiya, whose modal hour is `congested`. The
default grain was also `checkpoint_status`, the legacy kind that carries `idf` and
`police` in the same value column as `open`, so per-hour counts mixed two axes.
Fixed: default is `checkpoint_flow`, and the headline reports the modal value and
its tally. Now: *"قلنديا: عادة فيه أزمة — 19 من 21 ساعة إلها تقارير كافية."*

**6. `search` searched the last 100 messages.** "قلنديا" over 24 hours returned
zero hits while 49 matching messages sat in the claim store — the road-condition
channel alone holds 27,588 of them, none recent enough to reach a 100-message
window. The window is now the caller's and the match happens in the database: 20
hits.

**7. Coverage called a deliberately retired field "stale".** Fuel availability was
retired on 2026-09-23 and coverage still reported `fuel_diesel`/`fuel_gasoline` as
stale, which reads as a broken feed beside a working fuel-prices feature. Retired
kinds now report `retired`.

---

## Verified — not a bug, but nothing said so

**Staleness bands look inconsistent.** A 57-minute reading reads `live`, a
97-minute one `stale`, a 299-minute one `live`. This is by design: the band is
`half_life_seconds` for that source, so it means "are we still watching this place
at its own rhythm", not "how old is this". A checkpoint reported every few minutes
is overdue sooner than one reported twice a day. That reasoning was in a SQL
comment, not in any payload — now it travels as `staleness_note` on the checkpoint
tools.

**"checkpoints_summary failed auth twice."** My restarts, during the OAuth work.
Not a defect; noted so it does not get re-reported.

---

## Queued, with the diagnosis

**Incidents: duplication and misclassification.** Two channels reporting one
Huwara demolition should be one event with `independent_sources: 2`, not two
events — that contradicts the independence model the whole system rests on and is
the highest-value item left. Separately, the incident classifier measures 0.717
against its 0.80 gate and its errors concentrate in one class (obituaries,
funerals and features read as reports). ZAID-9 settled the taxonomy on
2026-09-23: an obituary or a funeral is not a death report. The classifier fix and
its re-measurement are next, then the dedup rule.

**`what_correlates_with` fills a candidate pool and tests nothing.** Reported; not
reproduced here because the probe used an invalid indicator string — needs one run
with a real indicator to confirm whether the pool is same-concept by construction.

**Food-price units are all `ILS_per_kg`** including eggs, milk, drinking water and
tea. Data-side; needs the units checked against the source series.

**Reporter-facing leaks of internal names.** Incident channels appear as `src:36`
rather than source keys, in some payloads.

**Small batch, cheap:** "In the last Noneh" in the incidents English answer;
`weather_now` filtered to Ramallah still saying "Normal across the West Bank";
the fuel headline dating every price to Sept 7 when kerosene and LPG are Sept 1;
`closed_now` listing النبي يونس twice; the `licenses` source filter not narrowing
its totals; the databank description saying 186k rows / 19 categories when it is
206k / 20; `compare` repeating attribution per data point; `place_history`
omitting today; the static Rafah note.

---

## Zaid's call, not a bug

**IODA licence conflict.** `connectivity_now` labels its source CC BY-NC 4.0 while
the licence registry records "all rights reserved, redistribution: ask, permission
request not yet sent". Both statements are in the product. Which one is correct is
a licensing decision, and licence-facing facts are not an agent's to settle —
raising it here rather than changing either one.

---

## Data health, as reported

* **48% of checkpoints have no recent reading** (119 of 250). That is the honest
  `unknown`, not an outage: nobody reported them inside their freshness window.
* **13 v1 pipeline steps failing ~30 nights** (OCHA casualties and demolitions,
  PCBS, HaMoked, B'Tselem). Real, in the v1 world being replaced, and worth a look
  on its own — a month of silence is not a transient.
* **"Fuel station availability stale since 07:31"** is the retired feed; coverage
  now says so (fix 7).
* **Water, crossings and cooking gas have no source at all** — true, and stated.
