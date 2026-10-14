# Connectivity · الاتصال

Measured on the store at 2026-10-14 18:07 UTC by `ops/databank_index.py`. [Back to the index](README.md)

## Web censorship measurements, share anomalous per day (OONI)

قياسات حجب المواقع، نسبة الشذوذ يومياً (OONI)

- **Key:** `v1_connectivity_ooni` · **publisher:** OONI (`ooni`)
- **Rows:** 1,378 held · 1,378 a question can reach · 1,378 exportable · 11 older values kept
- **Span:** 2017-02-09 → 2026-10-13 · **series:** 1 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-10-13)
- **Terms:** CC-BY-NC-SA-4.0 · partners: yes (share-alike, non-commercial) · terms: https://github.com/ooni/license/blob/master/data/LICENSE.md
- **Credit:** Censorship measurements: OONI (ooni.org), CC-BY-NC-SA-4.0.
- **Ask:** MCP `databank(category="connectivity", indicator="connectivity.censorship_measurement")` · REST `/v2/databank/connectivity?indicator=connectivity.censorship_measurement`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `connectivity.censorship_measurement` | Share of OONI web measurements showing an anomaly, per day (0 to 1) · نسبة قياسات OONI للوصول إلى المواقع التي سجّلت حالة شاذة، يوميًا (من 0 إلى 1) |  | 1,378 | 2017-02-09 | 2026-10-13 | 0 |

## Internet outages detected, with their duration (IODA)

انقطاعات الإنترنت ومدتها (IODA)

- **Key:** `v1_connectivity_ioda` · **publisher:** IODA (Georgia Tech) internet outage detection (`ioda`)
- **Rows:** 1,003 held · 1,003 a question can reach · 0 exportable · 1,080 older values kept
- **Span:** 2022-03-02 → 2026-10-13 · **series:** 1 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-10-13)
- **Terms:** LicenseRef-IODA-All-Rights-Reserved · partners: withheld (ask); the figure is cited with its source · terms: https://api.ioda.inetintel.cc.gatech.edu/v2/entities/query?entityType=country&entityCode=PS
- **Credit:** Internet outage detection: IODA, Georgia Tech Internet Intelligence Lab. Copyright (c) 2021-2025 Georgia Tech Research Corporation.
- **Ask:** MCP `databank(category="connectivity", indicator="connectivity.internet_outage")` · REST `/v2/databank/connectivity?indicator=connectivity.internet_outage`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `connectivity.internet_outage` | Internet outage detected: its duration in seconds (IODA) · انقطاع مرصود للإنترنت: مدّته بالثواني (IODA) |  | 1,003 | 2022-03-02 | 2026-10-13 | 2 |
