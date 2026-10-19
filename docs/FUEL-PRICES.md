# Fuel prices — the official monthly maximum

**Status, 18 October 2026.** The dataset is live; the historical backfill is
running. The confirmed series is **24 observations (Aug–Oct 2026)**. The first
202 archived bodies parsed into **16 price transcriptions, all single-outlet**;
**135 were refused `no_attribution`** — the old articles do not name the
Petroleum Corporation, so the belief rule confirms nothing from them. The
remaining **2,612** bodies are being fetched. Nothing below is estimated: the
archive is being read, and the belief rule refuses what it cannot confirm.

## What the number is

The Palestinian General Petroleum Corporation (الهيئة العامة للبترول, Ministry of
Finance) sets the **maximum consumer price** of petrol 95/98, diesel, kerosene
and cooking-gas cylinders for the West Bank, once a month and sometimes again
mid-month. It is a regulated **ceiling, not a pump price**: a station may sell
below it, and a station above it is breaking the published maximum. **Gaza has
no official consumer fuel price.**

There is no machine-readable feed. The list reaches the public as news, reposted
by every outlet within the hour.

## The eight products

| product | Arabic | unit |
|---|---|---|
| gasoline_95 | بنزين 95 | ILS/L |
| gasoline_98 | بنزين 98 | ILS/L |
| diesel | سولار | ILS/L |
| kerosene | كاز | ILS/L |
| lpg_2_5kg | أسطوانة غاز 2.5 كغم | ILS/cylinder |
| lpg_5kg | أسطوانة غاز 5 كغم | ILS/cylinder |
| lpg_12kg | أسطوانة غاز 12 كغم | ILS/cylinder |
| lpg_48kg | أسطوانة غاز 48 كغم | ILS/cylinder |

## How it is believed

One article is one **transcription** (`cascade/fuel_price.py`, reader
`fuel_price@4`). Every transcription — including refusals — lands in
`fuel_price_report`. A price is served only when **two independent outlets**
transcribe the same number for the same product and effective date, and **at
least one names the authority**. That rule is SQL (`fuel_price_believed`, view,
migration 071); nothing in the loader can promote a single outlet.

## The dataset

- **dataset** `fuel_prices_official`, `v1_category = fuel`, `cadence = monthly`.
- **source** `psc_petroleum`, the authority, not the outlets. Licence `NONE`,
  redistribution `attribution`; the outlets and URLs ride in each observation's
  `attrs`.
- **concept** `fuel.price.official`; **8 indicators**
  `fuel.price.official.<product>`, `measure_kind = stock`, `grain = month`,
  `place_grain = region`, canonical units `ILS_per_litre` / `ILS_per_cylinder`.
- **observations**: one per product and effective date, `place_id = 2` (West
  Bank), `occurred_precision = day`, `reported_at = first publication`,
  `v1_stable_id` and `identity_key`, `databank_serving`-visible.
- **licence shown**: `NONE` + attribution: “Official monthly maximum consumer
  prices: Palestinian General Petroleum Corporation, transcribed from
  Palestinian outlets.”

## API

- `/v2/fuel/prices` — current believed prices and the scope note.
- `/v2/fuel/prices/history` — the believed series.
- `/v2/databank/categories` — the `fuel` dataset, with `from`/`to` and licence.
- `/v2/databank/indicators?q=fuel` — the 8 indicators with `rows_served`.
- `/v2/databank/licenses`, `/v2/databank/where` — the licence and the West Bank.
- `/v2/databank/radar` — the coverage verdict. On 18 October 20:46 the fuel
  dataset is **fresh**: 24 rows, 4 effective dates, span 2026-08-01 → 2026-10-01,
  monthly rhythm 24 d, age 17 d, allowance 72 d.
- `docs/databank/` — the nightly index (3,737 series defined; 3,571 with rows).

## Coverage and history

- `publisher_window_from` **2003-02-25** (the archive's oldest fuel-price
  headline); the served `from` is **2026-08-01**. The radar judges the series
  monthly and fresh, but that window is the honest measure of the history still
  missing: the confirmed series covers 4 effective dates, not 2003→2026.
- Archive: **2,773** headlines 2002-10-31 → 2026-10-13; **161** had bodies;
  **2,612** are being fetched.
- The first 202 bodies: **16 price transcriptions, all single-outlet**;
  **135 refused `no_attribution`**; 45 `no_prices`. The belief rule does not
  bend for them.
- Therefore the confirmed history will be **sparse before 2026**, and the
  series will say so rather than pad it. The 2,612-body pass is the test of how
  far back the confirmation goes. The first 200 already show the constraint:
  about 8 % yield a price, and none of those had two independent outlets.

## Operations

- `db/migrations/128_fuel_price_dataset.sql` — source, dataset, concept, unit,
  the 8 indicators.
- `ops/load_fuel_prices.py` — `fuel_price_believed` → observations; idempotent;
  commits explicitly (`resolve.db.connect` closes without committing).
- `faselah-fuel-databank.timer` — daily 04:10, after the 03:40 databank sync.
- `ops/backfill_fuel_prices.py` — archived bodies → `fuel_price_report`; the
  belief view and the loader follow.
- `ops/databank_index` — rebuilds the API/docs index; `/v2/databank/indicators`
  defaults to limit 100, so query `?q=fuel` for the fuel set.

## Tests

`tests/test_fuel_prices_dataset.py` — the served shape (8 indicators, both
units, West Bank place, provenance) and loader idempotency; plus the known
October values (petrol 95 = 8.17, diesel = 8.99, 12 kg gas = 90.00).

## Caveats

- The maximum, not the pump; West Bank only; Gaza has no official price.
- Two independent outlets, one naming the authority; no exceptions.
- The historical archive's attribution is the binding constraint; if the 2,612
  bodies do not name the authority, the confirmed series stays recent.
- Availability (which station has diesel) was **retired by Zaid on 23 Sep 2026**
  and is not revived here; the image cards are not used.
