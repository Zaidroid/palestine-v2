---
job: 03
slug: pcbs-energy-tables-fuel-2012-2023
status: returned
returned: 2026-10-19 by DeepSeek
branch: job-03-pcbs-energy-tables
---

# JOB-03 return — PCBS monthly fuel prices 2012→2023

## What was done

Downloaded 11 PCBS Energy Tables reports and transcribed every printed monthly price:

| Year | File | Read | Table 8/9/10/11 |
|---|---|---|---|
| 2012 | `Energy Tables and balance 2012.pdf` | yes | 8 WB, 9 Jerusalem, 10 Gaza |
| 2014 | `Energy tables 2014.pdf` | yes | 8 WB, 9 Jerusalem, 10 Gaza |
| 2015 | `Energy Tables in Palestine 2015.pdf` | yes | 8 WB, 9 Jerusalem, 10 Gaza |
| 2016 | `Energy Tables and Energy Balance 2016.pdf` | yes | 8/9 both titled WB, 10 Jerusalem, 11 Gaza |
| 2017 | `Energy Tables 2017.pdf` | yes | 8 Palestine, 9 WB, 10 Gaza, 11 Jerusalem |
| 2018 | `Energy Tables 2018.pdf` | yes | 8 Palestine, 9 WB, 10 Gaza, 11 Jerusalem |
| 2019 | `energy2019ArEn.pdf` (alternate filename) | yes | 8 Palestine, 9 WB, 10 Gaza, 11 Jerusalem |
| 2020 | `energy-tables-2020-en.pdf` | yes (contrary to the brief's note) | 8 Palestine, 9 WB, 10 Gaza, 11 Jerusalem |
| 2021 | `EnergyTables2021E.pdf` | yes | 8 Palestine, 9 WB, 10 Gaza, 11 Jerusalem |
| 2022 | `Energy-Tables-2022.pdf` | yes | 8 Palestine, 9 WB, 10 Gaza, 11 Jerusalem |
| 2023 | `Energy_Tables2023.pdf` | yes | 8 Palestine, 9 WB, 10 Gaza, 11 Jerusalem |

Extraction: `pdftotext -layout`, then a row parser keyed on the printed English month name and the column order Diesel, Gasoline, Coal, Kerosene, LPG (`data/raw/jobs/03/parse_pcbs.py`). One record per (year, month, region, product); a second file for the printed annual averages.

**Delivered**

- `data/raw/jobs/03/pcbs_fuel_monthly.ndjson` — **1,980 records** (11 years × 12 months × 3 regions × 5 products).
- `data/raw/jobs/03/pcbs_fuel_yearly.ndjson` — **165 records** (11 years × 3 regions × 5 products).
- `data/raw/jobs/03/src/` — the PDFs and their text; `download_pcbs.log`.
- Every record carries `source_file`, `table`, `page`, `quote` (the printed row), `confidence: sure`.

## Completeness

| Year | West Bank | Jerusalem | Gaza | 12/12? |
|---|---|---|---|---|
| 2012 | 12 | 12 | 12 | yes |
| 2013 | — | — | — | **no source found** |
| 2014–2023 | 12 each | 12 each | 12 each | yes |

No blank month was invented. 2013 is the only missing year: the live site has no 2013 Energy Tables PDF (the 2013 monthly bulletins, e.g. `Energy-2013-01a.htm`, contain imported-energy quantities, not prices; the Wayback CDX index for the Documents folder lists no 2013 yearly table). 2024 was probed at four URL patterns and is 404; not included.

## Checks

- The five known cross-checks all pass: Jan 2012 WB petrol 95 6.88 / diesel 6.60 / LPG 70.17; Dec 2014 WB diesel 6.18 / petrol 6.68; Jan 2021 WB petrol 5.42; Jan 2023 WB petrol 6.59.
- Two pages rendered at 130 dpi and read against the image (`2012` p.8, `2023` p.9): **120 values matched** (12 months × 5 products on each page), no discrepancy.
- All 33 (year × region) series have 12 months; no duplicate (period, region, product) key.

## Anomalies and decisions

1. **2016 has two West Bank tables (8 and 9), both titled “West Bank” and both footnoted as excluding Jerusalem J1, with different values.** I kept **Table 9** and dropped Table 8: it is the second WB table in the 2016 sequence, its values continue the 2017–2023 Table 9 series, and its title carries the J1-exclusion footnote in the Arabic heading. This is the one editorial choice in the dataset; if Claude prefers Table 8, re-run `parse_pcbs.py` with the skip on `y==2016 and table=="Table 8"` removed.
2. **2019 URL differs** from the brief (`energy2019ArEn.pdf`, found through the PCBS document index) — the filename in the brief does not exist.
3. **TLS:** `www.pcbs.gov.ps` serves an incomplete certificate chain; `curl -k` was required. Downloads were one a minute (2014–2021) and are logged. No robots restriction was found (`robots.txt` empty).
4. **Regions:** the “Palestine” aggregate table (Table 8 in 2017–2023) was skipped; the delivered regions are the printed West Bank (J1 excluded), Jerusalem, Gaza Strip.
5. **Units as printed:** diesel/petrol/kerosene ILS/litre; LPG ILS/12 kg cylinder; coal ILS/kg. PCBS LPG is the delivered cylinder and is **not** comparable to the official cap series — not merged.
6. 2012 has a different commodity title (“Selected Commodities in Energy Group”) but the same five columns; accepted.

## Open questions for Claude

- 2013: accept the gap, or should I transcribe the 2013 monthly CPI price table from another PCBS release? (I did not find a 2013 Energy Tables price table.)
- 2016: confirm Table 9 over Table 8.
- Load contract: the monthly file is ready for a loader keyed on (period, region, product); no database write was made.
