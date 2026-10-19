---
job: 03
slug: pcbs-energy-tables-fuel-2012-2023
status: merged · 2026-10-19 by Claude
opened: 2026-10-19 by Claude (Fable)
branch: job-03-pcbs-energy-tables
---

# JOB-03 — PCBS Energy Tables: monthly fuel prices 2012→2023, transcribed from the PDFs

**Why.** Zaid asked for an official source for the fuel price history. The PCBS CPI dashboard gives monthly average fuel prices by region from 2019-01 (Claude fetches that directly). Before 2019 the only official monthly series is PCBS's yearly *Energy Tables* (PDF/HTML): monthly West Bank, Jerusalem and Gaza average prices for LPG 12 kg, kerosene, petrol 95 and diesel. For liquid fuels the PCBS average equals the official cap (checked Dec 2014: diesel 6.18, petrol 95 6.68, kerosene 6.18); LPG runs 2–3 ILS above the cap because PCBS prices the cylinder delivered to the home.

**Goal.** One NDJSON of monthly figures 2012→2023 with the page they came from, and a return that says which years/regions are complete.

## Inputs (read these files; they are PCBS, CC BY 4.0, cite "PCBS, Consumer Price Survey <year>")

| Year | File | Note |
|---|---|---|
| 2012 | https://www.pcbs.gov.ps/Portals/_Rainbow/Documents/Energy%20Tables%20and%20balance%202012.pdf | Table 8 |
| 2014 | https://www.pcbs.gov.ps/Portals/_Rainbow/Documents/en2014_6a.htm (West Bank), `_7a` Jerusalem, `_8a` Gaza | HTML |
| 2015 | https://www.pcbs.gov.ps/Portals/_Rainbow/Documents/Energy-2015-10-e.htm (Gaza; find the West Bank file on the index) | HTML |
| 2017 | https://www.pcbs.gov.ps/Portals/_Rainbow/Documents/Energy%20Tables%202017.pdf | Table 9 |
| 2020 | https://www.pcbs.gov.ps/Portals/_Rainbow/Documents/energy-tables-2020-en.pdf | would not read on 19 Oct; retry, else note |
| 2021 | https://www.pcbs.gov.ps/Portals/_Rainbow/Documents/EnergyTables2021E.pdf | Table 9 |
| 2022 | https://www.pcbs.gov.ps/Portals/_Rainbow/Documents/Energy-Tables-2022.pdf | not yet opened |
| 2023 | https://www.pcbs.gov.ps/Portals/_Rainbow/Documents/Energy_Tables2023.pdf | Table 9 |
| index | https://www.pcbs.gov.ps/site/886/default.aspx | find 2013, 2016, 2018, 2019 and any 2024 |

Download each into `data/raw/jobs/03/src/` (keep the file; name it `pcbs-energy-<year>.<ext>`). Check `robots.txt` once by hand; read at most one file a minute.

The PDF text extracts, but table titles come out after their data blocks: read the table by its column header row (months) and confirm the region from the title that follows.

## Records

`data/raw/jobs/03/pcbs_fuel_monthly.ndjson`, one per (year, month, region, product):
`{"period":"2014-12","region":"West Bank","product":"diesel","value":6.18,"unit":"ILS_per_litre","source_file":"pcbs-energy-2014.htm","table":"Table 9","page":12,"quote":"<the row as printed, ≤200 chars>","confidence":"sure"}`

Products: `gasoline_95`, `diesel`, `kerosene`, `lpg_12kg` (unit `ILS_per_cylinder`), `coal` if present (unit as printed). Regions as printed: West Bank (J1 excluded), Jerusalem J1, Gaza Strip. Yearly averages go in a second file, `pcbs_fuel_yearly.ndjson`, same shape with `"period":"2014"`.

## Return and acceptance

`JOB-03-RETURN.md`: a table of year × region × product with the number of months found (12 = complete); the files that would not read; 20 rows checked by hand against the PDF image. Claude re-checks 20 rows; at most one wrong value. Known cross-checks the data must reproduce: Jan 2012 WB petrol 95 6.88, diesel 6.60, LPG 70.17; Dec 2014 WB diesel 6.18, petrol 95 6.68; Jan 2021 WB petrol 95 5.42; Jan 2023 WB petrol 95 6.59.

## Do not

- Write to the database; touch `serve/`; mix PCBS LPG (delivered) into any series of official caps.
- Invent a month that the table leaves blank; record it as absent in the return.
