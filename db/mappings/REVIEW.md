# Spec review of record — 2026-08-05

Reviewer: the supervising session (Fable), over 21 Opus-drafted specs plus its
own water.yaml. Every open question left in a spec's notes is answered here;
a spec is `reviewed` because its questions have recorded answers, not because
they disappeared. The ETL (T2.3) implements spec + this file.

## Category verdicts

| category | verdict | the deciding fact |
|:--|:--|:--|
| aid_access | **migrate** | one lorry per row; trucks = COUNT(*), never SUM |
| casualties | **migrate** | breakdowns kept — they carry the only splits |
| conflict | **migrate** | cumulative series re-shaped to observation (below) |
| connectivity | **migrate** | additive vs Tier 1 — no overlap, verified |
| culture | **migrate** after 043 | needs `heritage_composite` source row |
| demolitions | **migrate as observation** | zero events in an "event" category |
| economic | **migrate** | 26 contradictory poverty rows quarantined |
| education | **migrate** | mojibake repaired at load (global convention) |
| food | **migrate** | WB/GS baskets re-pointed to region rows (below) |
| funding | **migrate** | cleanest sellable set; empty rules approved |
| health | **migrate** | dedupe to 12,502; expect fails a 40k write |
| historical | **migrate** | fan_out approved; 27 timeline rows → event |
| infrastructure | **migrate** | all-zero 'unknown' series loads (law 4) |
| martyrs_snapshot_2023 | **migrate** | serving posture is [ZAID] (below) |
| **news** | **SKIP** | 20-day rolling window; Tier 1 supersedes; nothing sellable |
| pcbs | **migrate quarantined** | mislabeled World Bank data; option (b) |
| prisoners | **migrate** | month precision; shared indicators kept (the point) |
| refugees | **migrate** | UNRWA aggregate rows get their own indicator (below) |
| settlements | **migrate** | stock convention (a) — same-year anchor (below) |
| **water** | **SKIP** | 25,049 numbers with no indicator identity, no period, batch dates |
| **westbank** | **SKIP** | zero unique records — a view v1 wrote out as data |
| martyrs… | see above | |

247,325 v1 records → ~219,128 in scope after the three skips; health dedupe
and conflict/economic drops reduce further, fan-outs add back. The run report
publishes the arithmetic per category.

## Cross-cutting decisions

1. **Resolution floors get two keys.** `min_decided_pct` (default 1.0):
   fraction of retained records reaching an error-free place decision,
   deliberate NULL included — an unroutable/failed row breaks it.
   `min_located_pct` (optional): fraction landing at point/locality/
   governorate grade. conflict's 0.78 becomes `min_located_pct`; specs using
   1.0-with-teeth semantics (demolitions, casualties) keep meaning via
   `min_decided_pct` + their failure-counting rules.
2. **Stock series anchor at the start of the labeled period** — settlements
   option (a): a 1967 year-end stock lands at 1967-01-01, precision=year,
   `attrs.reference = 'period-end stock'`. Uniform with flows; the year is
   right, and precision=year says exactly how much more we know. Applies to
   prisoners (month grain) identically.
3. **Shape follows the data, not the category list.** demolitions →
   `shape: observation` (fan_out: structures/displaced/affected). conflict's
   `daily_casualty_report` + `summary` → observation via `shape_overrides`
   (indicators conflict.gaza_cumulative_killed / _injured). historical's 27
   timeline records → `shape: event` via override (option (b)); their
   description is carried into event.attrs.summary — the one sanctioned law-6
   exemption, because for 13 of them it is the entire record.
4. **Drops are counted, never silent** — conflict's two drop blocks approved
   (977 false-zero placeholders, 44 payload-free rows); economic's 26
   contradictory pcbs_poverty_rate rows are dropped with reason
   `contradictory_duplicate` (not guessed into poverty/deep-poverty).
5. **Units: normalize at load, preserve raw.** aid_access Truck≡trucks,
   Ton≡MT collapse into canonical units with `attrs.unit_raw` keeping the
   original. Uniform-but-wrong unit fields (IMF 'number', education
   'students', OONI 'measurements') are nulled per spec; never propagated.
6. **Mojibake is repaired at load** (education/westbank fields): cp1252→utf-8
   round-trip guarded by try/except; non-round-tripping strings pass
   unchanged and are counted in the run report.
7. **Strictest-license-wins assertion**: for multi-source records the loader
   asserts no name in sources[] maps to a source stricter than the routed
   dataset's; violation fails the run (conflict's index-0 coincidence).
8. **food's 'West Bank'/'Gaza Strip' basket markets** override to region rows
   (place 2 / place 1), NOT WFP's admin2 — a WB-wide basket inside Ramallah's
   series is a wrong place served confidently, law 3 in spirit.
9. **refugees/UNRWA**: the 11 aggregate rows take indicator
   `refugees.registered_total` (label in attrs.aggregate_label); the
   '% living within camp borders' row gets unit 'percent'. A naive SUM can no
   longer mix grains.
10. **health dedupe**: in-memory on stable_id at load, PLUS a unique index
    `(dataset_id, v1_stable_id, occurred_at) WHERE v1_stable_id IS NOT NULL`
    in T2.3's migration. Multi-valued (indicator, date, dimension) groups are
    counted in the run report (fact, not error).
11. **connectivity**: IODA durations migrate verbatim (3.8-year artifacts
    included) — attrs carry outage_datasource for collapsing; rewriting
    upstream values is not an ETL right. The 'ioda' attribution-string
    question rides with T2.5, where attribution starts deriving from the
    source row.
12. **martyrs anchor**: 2023-10-07 (in-record, sorts the memorial before the
    live era) at precision=unknown. dob passes through (it is upstream public
    data), but the serving default is the [ZAID] question below.
13. **Audit-tool fixes landed** (fail-closed fetch day, month-day histogram,
    informative fill, batch-date concentration, distinct counts) — the audit
    JSON in ops/ is the regenerated version; agents' findings reproduced.

## [ZAID] — product calls surfaced by this review (nothing blocks on them)

- **Martyrs serving posture**: license permits per-name serving (even paid);
  recommendation is free tier, aggregate cuts by default, per-name behind an
  explicit memorial view. Ethics call, not a license call.
- **Nakba gazetteer**: historical's 2,424 Mandate-era localities could become
  place rows (resolution 33% → ~99%, a gazetteer nothing else has), at the
  cost of doubling the place table and admitting 1,177 post-1948 Israeli
  localities POM records for contrast. Specs assume NO until you say yes.
- **Tech4Palestine license contradiction**: registry says CC-BY-4.0
  sellable; every conflict record embeds 'varies'. 042 currently wins →
  21% of conflict is sellable on the registry's word. Confirm T4P's terms or
  flip the source row.
- **'Western Erez' = Zikim?** 6,304 aid rows (12.6%) sit on the Gaza region
  row pending your confirmation that UNRWA's 'Western Erez' is the northern
  corridor 034 seeded as Zikim Crossing.
- The standing 24-source verify-required list from 042 (includes everything
  above the pcbs/prisoners/historical categories serve).

---

## Addendum 2026-08-06 — conflict_westbank (reviewed same-day, author+reviewer noted)

Zaid's directive: re-source OCHA casualties+demolitions from HDX (the Phase-4
filing). **The premise failed measurement**: OCHA oPt's casualties and
demolitions databases are NOT on HDX under any name, org, or topic query —
the org's 33 datasets are boundaries/schools/barriers; the "21 CC-BY
datasets" claim from the license research pass was true of the org but false
of these two databases. Recorded here so nobody chases that ghost again.

What fulfilled the intent instead: T4P's raw West Bank cumulative series
(healed by the June-9 stall fix), spec conflict_westbank.yaml. Review calls:

1. conflict.yaml's drop of the 977 unified WB rows STANDS — those rows are
   genuinely value-free (v1's transform maps only the never-filled daily
   fields). The raw series is a different input, not a reversal.
2. fill-day law: 'un' days are observations even when values hold (a flash
   update confirming a value is a claim); unchanged fill days are padding
   (752 dropped, counted); moved fill days carry information and stay, with
   attrs.flash_source disclosing the date's provenance.
3. Revisions: first-write-wins per (day, field); measured 0 cumulative
   decreases across 1,035 days; the next kept day self-corrects the series.
4. Provenance for lawyer-before-ads: T4P compiles OCHA-origin WB figures;
   we rely on T4P's Unlicense over their compilation, same posture as
   gaza_moh-via-T4P. The commercial tier carries the rows on that basis.
5. Single-reviewer note: drafted and reviewed by the same session (Opus
   agents not warranted for one spec); the measured arithmetic (1,035 →
   283 kept → 2,255 obs) is pinned in the spec and reproduced by the run.

---

## Addendum 2026-08-06 — the water recovery (water_gho; the skip vindicated)

Zaid's directive: recover the skipped water category by fetching the true
source with indicator identity. Measurement resolved it almost to nothing —
the best possible outcome:

1. **The 25,049 anonymous rows were never a loss.** Census by title: ~23k
   are WHO GHO health bundles whose identity-true content v1_health_who
   already serves (184 GHO codes); the six JMP WASH access codes sit at
   EXACT row parity with the GHO API (75=75 each; hygiene 33=33). ~2k are
   World Bank WDI subsets (economic's domain). 6 rows are MPI/SDG strays.
   v1's "water" category was a fetcher artifact — a grab-bag mirror with
   columns stripped — not a data asset.
2. **The entire GHO WSH_* universe (27 codes) was diffed against health:**
   WHO publishes NO WASH burden estimates for PSE (WSH_1/3/10/20/30 series
   all empty — probed directly); exactly ONE code with PSE data was
   missing: WSH_SANITATION_OD (75 rows, 2000–2024, 0–2%). That is the
   whole recoverable delta, now dataset who_gho_wash — the first fully
   v2-native dataset (ops/fetch_gho_wash.py, atomic, floor-guarded,
   nightly in databank-sync before the loader).
3. **Value rule measured, not assumed:** GHO ships the series with
   NumericValue null and integer-rounded display strings ("0"/"1"/"2") —
   parsed with attrs.value_basis disclosing it per row.
4. **The real gap was the serving surface**: /v2/databank/water served
   nothing while the complete access series sat inside health. Decision:
   water is a DOMAIN — the category serves its own datasets plus health's
   wsh_* series (app.py + 051's v_water). One fact, one storage row, two
   category doors; indicator names keep their home namespace so provenance
   stays visible; the API test asserts no fact is served twice.
5. License honesty: who source row is CC-BY-NC-SA-3.0-IGO — the water
   category serves with attribution and stays OUT of the commercial tier.
6. Single-reviewer note: same-session author+review, arithmetic pinned in
   the spec (75 records → 75 observations) and reproduced by the run.
