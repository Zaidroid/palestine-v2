---
job: 08
slug: lake-second-pass
status: returned · A+B+C+D · judgment pass · 2026-10-20
opened: 2026-10-20 by Claude (Fable), for two nights
branch: job-08-lake-second-pass
deadline: 2026-10-21 08:00 UTC first return (whatever is finished), 2026-10-22 08:00 UTC the rest; update JOB-08-RETURN.md at every stop point
---

# JOB-08 — The lake, read to the bar: eleven families, every candidate, delivered loadable

**Why.** JOB-06 built the lake (284,728 figure sentences, 29 families, 2003 → 2026) and proved two things: phrase cues read clean, and a pilot of 30 rows per family is not a series. Claude re-read all 343 pilot rows and wrote the bar down (`db/reference/job06_review.yaml`, `docs/jobs/JOB-06-RETURN.md` → "Claude's review"). This job reads the **full candidate sets** of the families worth having, to that bar, and delivers them in the shapes the loader already takes, so that the morning's work is a 30-row check and one command, not a rebuild.

**Goal.** For each family below, in order: every candidate sentence judged, duplicates merged, places named, tallies dated at their period, each kept row with its quote and document; a self-check; a return table. Stop points between families: a family that is finished is returned even if the next is not started.

## The bar (from JOB-06's review; every family is read against it)

1. **A row is an event or a tally, never a mention.** "Settlers uprooted 200 trees in Qusra on Tuesday" is a row. "The occupation has uprooted thousands of trees" is not. "Since 7 October 2023, 64,200 dunums" is a cumulative statement: it goes to `cited`, not to the series.
2. **Several outlets on one event are one row.** Same place, same count or a near count, within 14 days: keep the agency's (WAFA, Ma'an) or the fuller count, and name the others in `note` with their doc ids. The pilot's 87 kept tree rows were 45 events.
3. **A tally cited on several dates is one row, dated at its period.** The Commission's half-year figure (45,195 trees) appeared on five dates; it is one row for 1 Jan – 30 Jun 2026. `from`/`to` carry the period; precision is `month` for a calendar month, `year` for a year, `day` otherwise.
4. **The dot.** In a military order «7.498 دونم» is 7 dunums and 498 m² (a decimal). In WAFA's tallies «26.395 شجرة» is 26,395 (a thousands separator). Decide by the magnitude and the sentence, print the rule you applied in `note` when the dot decided the value, and never let «5283» stand for «5.283».
5. **Places.** Name the village as the sentence spells it (`place_ar`) and its governorate in English (`gov`: Jenin, Tubas, Tulkarm, Nablus, Qalqilya, Salfit, Ramallah, Jericho, Jerusalem, Bethlehem, Hebron; Gaza families: Gaza Strip). The loader resolves `place_ar` + `gov` against the gazetteer dump `data/raw/settlements/localities.json` (name + governorate; the lowest id wins). When no village is in the sentence, `place_ar: null` and the governorate; when neither, `gov: null` (the region). Do not invent a village from a dateline.
6. **The authority.** Name it when the sentence names it ("the Ministry of Agriculture documented…"); otherwise `authority: "<outlet> (not named in the sentence)"`. A sentence that reads like a monthly report but does not say whose is marked `caution`.
7. **Qualifiers stay.** «أكثر من» → `more_than`, «نحو / حوالي / قرابة / ما يقارب» → `about`, «ما لا يقل عن» → `at_least`, «لا يتجاوز» → `up_to`. The value is the number printed; the qualifier is a field.
8. **No inferred numbers.** «عشرات» (dozens) is not a number. A headline with a number and a body with another: take the body and note the headline.
9. **Lives are never rounded** and carry the publisher's wording in the quote.
10. **Drops are written down** with one reason each (`dropped:`), as job06_review.yaml does, so nobody re-litigates them.

## Inputs

- **The lake, all of it, per family:** `data/raw/jobs/06/lake/*.ndjson.gz` (one file per publisher; filter on `family`). Each record has `doc_id`, `date`, `publisher`, `url`, `family`, `cue`, `number`, `printed`, `unit`, `qualifier`, `place_hint`, `period_hint`, `authority_hint`, `quote` (≤300 chars). Read **every** record of the family, not only `data/raw/jobs/06/series/*.candidates.ndjson.gz`: those are JOB-06's narrower pre-filter (trees 1,165 of 3,299, land orders 799 of 2,021) and are a useful first tier, no more. Write every lake record you read for a family, unchanged and in one fixed order, to `data/raw/jobs/08/<family>.read.ndjson.gz`; **`idx` in the review file is the 0-based line number of the record in that file** (the loader picks the row by `doc` + `idx`, exactly as it does for JOB-06's reviewed files).
- **Skip what JOB-06 already loaded:** every `doc` listed in `db/reference/job06_review.yaml` (loaded or dropped) is settled. Trees and land orders here are **2003 → 2025** plus any 2026 sentence not in that file.
- For families I and J the lake is too thin (demolitions before 2009: 174 sentences; checkpoint closures are states, often with no number, so the lake missed most). The clause-level read needs the bodies: dump the corpus once as JOB-06 did (`docs/jobs/JOB-06-archive-figures-lake.md` → Inputs; one server-side cursor, ~36 min, 1.1 GB), and **delete it when the job ends**. `df -h /` first; stop below 20 GB free (95 GB free on 20 Oct).
- Checkpoint names for J: the gazetteer's 401 checkpoints, dumped read-only once:
  ```bash
  cd /home/zaid/palestine-v2 && .venv/bin/python - <<'PY'
  import json, sys; sys.path.insert(0, '.')
  from resolve.db import connect
  with connect() as c:
      c.execute("SET default_transaction_read_only = on")
      rows = c.execute("SELECT place_id, name_ar, name_en, attrs->>'aliases_ar' FROM place WHERE kind='checkpoint' AND merged_into IS NULL").fetchall()
  json.dump([{"place_id": r[0], "ar": r[1], "en": r[2], "aliases": r[3]} for r in rows], open("data/raw/jobs/08/checkpoints.json", "w"), ensure_ascii=False)
  print(len(rows))
  PY
  ```
- Database read-only throughout (the dump and the checkpoint list are the only reads). No `serve/`, no restart, no publishing.

## The families, in order (each a stop point)

Deliver each as `data/raw/jobs/08/<family>.review.yaml` in the schema named (with its `dropped:` map), plus `<family>.REVIEW.md` (the self-check, the cluster count, the pattern failures) and `<family>.read.ndjson.gz` (the records read, the file `idx` points into). For I and J, sentences taken from the corpus pass go into the same `.read` file in the lake's record shape, `family` set, `cue` naming the clause pattern.

| # | family | candidates | schema (the loader already takes A–C; D–K are new and the morning adds them) |
|---|---|---:|---|
| A | **trees, 2003 → 2025** | 3,299 in the lake (2,231 before 2026) | `trees_incidents:` `{doc, idx, trees, qualifier, place_ar→place, gov, actor: settlers\|army, kind: olive\|almond\|grapevines\|fruit_trees\|trees, note}` and `trees_tallies:` `{doc, idx, authority, from, to, precision, caution, rows: [{measure: all\|olive, place: West Bank\|<governorate>, trees, qualifier}]}` — exactly job06_review.yaml's shape |
| B | **land seizure orders, 2003 → 2025** | 2,021 (1,599 before 2024) | `land_orders:` `{doc, idx, n, dunums, qualifier, place, gov, kind: order\|declaration, purpose, note}`; cumulative "since" figures → `cited:` (schema K) |
| C | **Gaza aid trucks before the ceasefire, 2008 → 9 Oct 2025** | 1,322 in the lake, most of them 2024–2025 | `gaza_trucks_stated:` `{doc, idx, day or from+to, trucks, scope: aid\|all\|fuel\|commercial, authority, qualifier, note}` — a day's count as an authority stated it (GMO, UNRWA, COGAT as quoted, OCHA); the 2025-10 → series is loaded, skip it |
| D | **fishing zone** | 175 | `fishing_zone:` `{doc, idx, date, nautical_miles, kind: stated\|expanded\|reduced\|closed, authority, note}` — the permitted distance on the day; a closure is 0 |
| E | **hunger strikes** | 1,061 | `hunger_strikes:` `{doc, idx, date, prisoners, day_of_strike, prison, kind: mass\|individual\|solidarity, name (individual), authority, note}` — one statement of a strike's size or day; solidarity strikes by non-prisoners are `kind: solidarity` and not series rows |
| F | **iron gates** | 179 | `gates_installed:` `{doc, idx, date, gates, place_ar, gov, note}` one installation event; cumulative counts ("910 barriers") → `cited:` |
| G | **settler-attack tallies** | 758 + the Commission's monthly sentences in the trees/land families | `attack_tallies:` `{doc, idx, authority, from, to, precision, rows: [{place, attacks, qualifier}]}` — the Commission's and OCHA's counts of attacks per period, with the governorate split when printed |
| H | **administrative detention orders** | 1,216 | `admin_detention_tallies:` `{doc, idx, authority (Addameer, Prisoners' Club, PPS, Commission of Detainees), from, to, precision, orders, new_orders, renewals, qualifier, note}` — orders issued in a period; a stock ("3,400 administrative detainees") is `stock: true`, kept apart |
| I | **demolitions by village, 2001 → 2008** | 174 in the lake + a clause pass over the corpus; expect sparse | `demolitions_reported:` `{doc, idx, date, structures, kind: homes\|structures\|agricultural\|tents, place_ar, gov, actor, warnings: false, note}` — OCHA's table covers 2009 →, so read 2001–2008 fully and 2009 → only as a 200-row cross-check sample, reported in REVIEW.md |
| J | **checkpoint closures by name, 2003 → 2023** | 3,571 in the lake + a clause pass over the corpus | `checkpoint_states:` `{doc, idx, date, checkpoint_ar, checkpoint_id (from checkpoints.json when matched), state: closed\|opened\|partial\|restricted, who: army\|settlers, authority, note}` — the state, not the number: the lake's numbers here were mostly dates. The live tier covers 2024 →; stop at 2023 |
| K | **wages** | 783 | `cited:` rows in section I's shape (`db/reference/cited_figures.yaml` → I): `{id, topic: wages, measure, date, precision, from, to, value, qualifier, unit, region, publisher, document, quote, verification: secondary\|read, caution}` — PCBS's average daily wage by region and period; statements, not a series |

Volume is the whole set. A family with fewer than 12 clean rows over 2 years is returned as `verdict: sparse` with its rows anyway.

## Self-check (per family, in REVIEW.md)

- 12 random kept rows re-read against the quote with the bar's ten points; print the twelve and the verdict on each.
- Every kept row whose value is above the family's 95th percentile re-read (the dot, the thousands, the misplaced number).
- Cluster report: candidates → kept → clusters merged (count), and the three largest clusters named.
- Pattern failures: what the cue caught that it should not have, in one line each, so the next pass can tighten it.

## Acceptance (Claude, the morning after each return)

30 random kept rows per family plus every row above the 95th percentile, read against the quote. More than two wrong in the thirty sends the family back with the wrong rows named. A family that passes is loaded by `ops/load_job_returns.py --only 08` (A–C with the existing branches; D–K after migration 137 adds their indicators, a routine build).

## Rules that do not move

`docs/jobs/README.md` → "The rules that do not move", and: ≤ 6 workers; a `STOP` file at `data/raw/jobs/08/STOP` ends the run cleanly at the next family boundary; detached with a log and a `DONE` marker; the corpus dump deleted at the end; the return updated at every stop point with the table **family · candidates · kept · clusters · span · self-check result · verdict**.
