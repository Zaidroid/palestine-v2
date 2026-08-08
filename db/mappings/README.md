# Mapping specs — one YAML per v1 databank category

These are TRAP-4's reviewable documents: every decision the migration ETL
(T2.3) makes per category is written here FIRST, reviewed as a document, and
only then executed by code that reads these files. The ETL must refuse to
process a category whose spec is missing or `status: draft`.

Every claim in a spec cites `ops/t2-category-audit.json` — specs are derived
from measured records, not from v1's README. If a spec disagrees with the
audit, the spec is wrong.

## Spec format

```yaml
category: water                # v1 category directory name
shape: observation             # observation | event  (event ONLY for
                               #   conflict, demolitions — things that happen
                               #   at a place+time; everything else measures)
status: draft                  # draft | reviewed  — ETL runs only on reviewed
records_measured: 25049        # from the audit, the expect{} baseline

source_routing:                # record.sources[0].name → source.key (042)
  by_name:
    "HDX": hdx
  default: hdx                 # for records with sources: []
                               # names resolve via licenses.json aliases;
                               # an unroutable name FAILS the run, loudly

datasets:                      # every (category, source) pair, pre-declared;
  - key: v1_water_hdx          #   the loader upserts exactly these and
    source: hdx                #   refuses a record routing anywhere else

indicator:
  template: "water.{indicator_code}"   # fields in {braces}; the result is
                                       # observation.indicator

value:
  num_from: metrics.value      # first non-null wins
  text_from: null
  unit_from: indicator_name    # or a literal: {literal: "percent"}

occurred_at:
  from: date                   # source field for the event date
  precision: day               # exact|hour|day|month|year|unknown
  rules:                       # ordered, first match wins; the three v1
                               #   freshness defeats die here:
    - if: "date == fetch_day"  # ingest-date masquerade (culture 100%, land 66%)
      then: "reported_at-only" #   → occurred_at = reported_at, precision=unknown
                               #   (T7 already excludes unknown/year from freshness)
    - if: "date endswith -12-31 and event_type is an aggregate"
      then: "truncate to year start, precision=year"   # the -154-days defeat

place:
  strategy: pcode              # the FIRST rung. pcode | latlon |
                               #   gazetteer_key | name | region | none
  fallback: [latlon, region]   # the rungs tried in order when it misses;
                               #   which one fired is counted in the run
                               #   report as place_rung:<name>
  # region strings: 'Gaza Strip'→place 1, 'West Bank'→place 2,
  # 'Palestine'→place_id NULL (attrs.region keeps the string),
  # 'East Jerusalem'→Jerusalem governorate row + attrs.region preserved.
  min_decided_pct: 1.0         # every RETAINED record reaches an error-free
                               #   place decision; a deliberate NULL counts.
                               #   Default 1.0, so omitting it still means it
  min_located_pct: 0.92        # optional: fraction at point/locality/
                               #   governorate grade. Set from the audit, not
                               #   from hope — and only where the source
                               #   actually carries geo

stable_id: stable_id           # field for observation.v1_stable_id
                               #   (idempotency; 'id' if no stable_id field)
attrs_passthrough:             # category-specific fields the audit found
  - wash_status                #   (keep small; description NEVER — bulk text
  - access_level               #   stays in bronze, raw_ref points at it)

expect:                        # the records:null lesson — a run that sees
  min_records: 22000           #   fewer than this FAILS, it does not "succeed
                               #   with less"; ≈0.9 × records_measured

notes: |
  Measured quirks the numbers above summarize; anything a future reader
  would need before editing this spec.
```

## Laws

1. **No date is trusted twice.** A category whose `date` equals the fetch day
   (audit: `ingest_masquerade_pct`) does not get an `occurred_at` from it —
   `reported_at` keeps the fetch time and precision goes `unknown`. Freshness
   math (T7) already ignores `unknown`/`year` precision, so these records can
   never fake freshness again — that is the defeat that made culture report
   `freshness_days_since_latest: 0` forever.
2. **Year buckets are years.** `-12-31` aggregate dates become
   `occurred_at = Jan 1 of that year, precision = year` — never a day-precise
   December record (the `-154 days` negative-freshness defeat).
3. **Place is resolved, never guessed.** Use the richest measured field;
   a category with 0% geo is a region-aggregate, and `place_id NULL` with
   `attrs.region` is the honest answer for country-wide numbers. No name
   matching against the Arabic gazetteer for English org names.
4. **Every record lands somewhere visible.** A record that fails routing,
   date rules, or place resolution is COUNTED in the run report by reason.
   Percentages below `min_decided_pct` or `min_located_pct` fail the run.
5. **Specs are per (category, source).** Nine categories mix licenses in one
   file (audit `source_licenses`); the dataset a record joins decides what
   the license filter believes about it, so routing is exhaustive and
   unroutable records are errors, not defaults.
6. **`description` is not data.** It stays in bronze; `raw_ref` points there.
   One sanctioned exemption, granted in review: historical's 27 timeline
   events carry description into event.attrs.summary, because for 13 of them
   it is the entire record.

## The registry: which keys are real (added 2026-08-08)

**`ingest/spec.py` is the authority on this format, not this file.** Every key
path a spec may contain is registered there with what the machine does about
it, `load_spec()` validates against it before reading a single record, and an
unknown key is refused with a spelling suggestion. This section explains the
scheme; run `python -m ingest.spec --explain` for the current list.

| class | meaning |
|---|---|
| `enforced` (35) | generic loader code reads it. Changing the **value** changes behaviour without touching Python. |
| `implemented` (43) | real behaviour, hand-written in the category's transformer. Type-checked here; obedience is proven by `ops/spec_equivalence.py`, not by the registry. |
| `data_map` (5) | the node's child keys are DATA — crosswalk entries, upstream source names. Values are shape-checked, keys are not. |
| `rationale` (6) | prose. Measured counts, notes, reasoning. **No behaviour**, and the validator says so rather than letting it look like a rule. |
| `unimplemented` (0) | declared by some spec and doing nothing. `load_spec` REFUSES. A spec may not promise what no code delivers. |

Why this exists. On 2026-08-08 three keys were in that last class without
anyone knowing:

- **`place.min_resolved_pct`** — declared in 20 of 24 specs, read by nothing.
  Twenty reviewed documents asserted a resolution floor that could not fail.
- **`source_routing.default`** — declared in 21 specs, read by nothing, and
  its absence was not neutral: a record with `sources: []` routed to `None`,
  which fails the whole run rather than taking the declared default.
- **the latlon rung of `place.fallback`** — declared in 4 specs, never
  implemented. education and infrastructure both said `[latlon, region]` and
  both transformers went pcode → region.

That third one had teeth. v1's geo enrichment ran for one window around
2026-07-21 — *the window the specs were written in* — and stopped. Measured
against the evidence vault: `admin2_pcode` went 0 → 2,357 → 0 for education
and 0 → 3,261 → 0 for infrastructure, `gazetteer_key` 0 → 2,492 → 0 for
historical, and refugees lost 16 UNRWA coordinates. So 5,881 rows sat at
region grade holding a perfectly good lat/lon, the floor that existed to catch
it was inert, and the only reason anyone found out is that someone went
looking. `ops/v1_field_health.py` is now how you look, and the ladder is real,
so the loader stands on the field that survived rather than the one that
didn't.

The lesson generalises past this format: **prefer the input that is always
there.** A derived code is one upstream job away from vanishing; a coordinate
that came with the record is not.

## Format v2 — extensions adopted in review (2026-08-05, see REVIEW.md)

The drafting pass proved the base format cannot describe five categories.
These constructs are part of the format; a spec using one the loader lacks
must FAIL, not skip — which is now true by construction rather than by
intention, because the registry refuses it:

- `migrate: false` + `skip_reason` — the category is measured, specced, and
  deliberately not loaded (water, westbank, news). The ETL refuses it.
- `datasets[].overrides` — per-dataset narrowing of indicator/value/
  occurred_at/place/attrs/expect (refugees, economic, prisoners, historical).
- `shape_overrides` — route a subset (by event_type) to the other table:
  conflict's cumulative series → observation; historical's timeline → event.
- `indicator.overrides` and `value.num_from_overrides` — per-event_type
  behaviour inside one dataset (infrastructure).
- `place.name_from` / `place.crosswalk` / `place.fallback` /
  `place.latlon_exclude` / `place.forbid` — measured resolution ladders;
  crosswalks are keyed on gazetteer name_en, never place_id, so a rebuild
  cannot silently repoint them. `forbid` lists fields that LOOK like geo and
  are fabricated (synthetic centroids, projected metres). `latlon_exclude`
  names event types whose coordinates are projected metres rather than
  degrees — the rung is skipped for them and only for them, because the
  record is sound and one field is not.
- `fan_out` — one record becomes several observations when the real values
  live in per-period fields (historical censuses; demolitions metrics). The
  run report asserts the expected observation count separately from records
  read.
- `metrics_rules` — event-shape metric renames (cumulative series keys get
  `_cumulative` suffixes and a cumulative flag).
- `drop:` — declared, measured, counted-by-reason removals. A drop without a
  measured count in the spec is invalid.
- Resolution floors are TWO keys: `min_decided_pct` (default 1.0 — every
  retained record reaches an error-free decision, deliberate NULL included)
  and `min_located_pct` (optional — point/locality/governorate grade). Both
  may be set per dataset under `datasets[].overrides.place`, because a
  whole-category average cannot see one dataset going dark inside it — which
  is exactly how refugees' UNRWA camps lost every coordinate they had while
  the category floor stayed green.
- Loader conventions, global: a `{brace}` resolving to null drops its
  segment; interpolated values are slugged (lowercase, non-alnum runs → `_`);
  Arabic mojibake is repaired by a guarded cp1252→utf-8 round trip and
  repairs are counted; multi-source records assert strictest-license-wins
  against the routed dataset; stock series anchor at the START of their
  labeled period with `attrs.reference = 'period-end stock'`; canonical unit
  normalization keeps the original in `attrs.unit_raw`.

Extensions adopted 2026-08-06 (first user: conflict_westbank, the raw WB
cumulative series v1's unified transform destroys):

- `input: {root, glob}` — a spec may read a v1 RAW tree instead of the
  unified category directory (still strictly read-only; index/recent files
  excluded). Records without v1 stable_ids use synthetic natural keys with a
  distinguishing prefix (`t4praw-wb-<date>:<field>`) so 044 idempotency
  holds and replay machinery — which keys on real v1 hash generations —
  never confuses them for v1 ids.
- `v1_category:` — when the spec's file name is not the serving category
  (conflict_westbank → conflict), this declares which category views its
  datasets join. Absent, the file name is the category, as before.
