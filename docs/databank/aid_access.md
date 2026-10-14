# Aid Access · وصول المساعدات

Measured on the store at 2026-10-14 18:11 UTC by `ops/databank_index.py`. [Back to the index](README.md)

## Aid consignments entering Gaza, Oct 2023 to Jan 2025 (UNRWA logistics log)

شحنات المساعدات الداخلة إلى غزة، من تشرين الأول 2023 إلى كانون الثاني 2025 (الأونروا)

- **Key:** `v1_aid_access_unrwa_aid_trucks` · **publisher:** UNRWA Gaza Supply and Logistics dashboard (`unrwa_aid_trucks`)
- **Rows:** 50,059 held · 50,059 a question can reach · 50,059 exportable · 0 older values kept
- **Span:** 2023-10-21 → 2025-01-16 · **series:** 4 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** ended by its publisher (last information 2025-01-16)
- **Terms:** CC-BY · partners: yes (attribution) · terms: https://data.humdata.org/dataset/state-of-palestine-gaza-aid-truck-data
- **Credit:** Gaza aid truck data: UNRWA via HDX (CC-BY).
- **Read before use:** UNRWA's log of supplies entering Gaza, one row per consignment line. By the publisher's own notice the records after 5 May 2024 are partial, and the log ends on 16 January 2025: a count for any day after 5 May 2024 is a floor, not the total, and no day after 16 January 2025 has a figure at all. Rows are counted in pallets, tonnes or lorries and are never added across units.
- **Ask:** MCP `databank(category="aid_access", indicator="aid_access.consignment.food_items")` · REST `/v2/databank/aid_access?indicator=aid_access.consignment.food_items`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `aid_access.consignment.food_items` | Aid entering Gaza, food items: quantity per consignment line, in the row's unit (UNRWA) · المساعدات الداخلة إلى قطاع غزة، مواد غذائية: كمية كل شحنة بوحدة السطر (الأونروا) | pallet | 38,390 | 2023-10-21 | 2025-01-16 | 6 |
| `aid_access.consignment.medical_supplies` | Aid entering Gaza, medical supplies: quantity per consignment line, in the row's unit (UNRWA) · المساعدات الداخلة إلى قطاع غزة، مستلزمات طبية: كمية كل شحنة بوحدة السطر (الأونروا) | pallet | 1,692 | 2023-10-21 | 2025-01-05 | 5 |
| `aid_access.consignment.mixed_items` | Aid entering Gaza, mixed items: quantity per consignment line, in the row's unit (UNRWA) · المساعدات الداخلة إلى قطاع غزة، مواد متنوعة: كمية كل شحنة بوحدة السطر (الأونروا) | pallet | 1,812 | 2023-10-22 | 2025-01-13 | 6 |
| `aid_access.consignment.non_food_items` | Aid entering Gaza, non-food items: quantity per consignment line, in the row's unit (UNRWA) · المساعدات الداخلة إلى قطاع غزة، مواد غير غذائية: كمية كل شحنة بوحدة السطر (الأونروا) | pallet | 8,165 | 2023-10-23 | 2025-01-13 | 5 |

## Aid offloaded, collected and arrived in Gaza, per day (UN2720 Mechanism)

المساعدات المفرّغة والمستلمة والواصلة إلى غزة، يومياً (آلية 2720)

- **Key:** `un2720_aid_daily` · **publisher:** UN2720 Mechanism for Gaza (UNOPS) — Monitoring & Tracking Dashboard (`un2720`)
- **Rows:** 3,435 held · 3,435 a question can reach · 0 exportable · 1,546 older values kept
- **Span:** 2025-05-19 → 2026-08-31 · **series:** 9 · **cadence:** daily
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-08-31)
- **Terms:** no-license-found · partners: withheld (ask); the figure is cited with its source · terms: https://info.un2720.org/
- **Credit:** Aid movements into Gaza: UN2720 Mechanism for Gaza (UNOPS), Monitoring & Tracking Dashboard (tracking.un2720.org). No licence is stated; counts only consignments processed through the UN2720 Mechanism.
- **Scope:** Only humanitarian consignments processed through the UN2720 Mechanism. Three stages of one journey (offloaded, collected, arrived): never added together. The publisher revises past days and caps the window at its last verified day.
- **Read before use:** Pallets of aid that reached their intended destination inside Gaza that day, as verified by the UN2720 Mechanism (UNOPS). It says nothing about distribution to families, and it covers only cargo sent through that UN mechanism (no commercial goods, no aid sent outside it). It is not UNRWA's count, which ended on 16 January 2025: the two are never one series.
- **Read before use:** Tonnes of aid that reached their intended destination inside Gaza that day, as verified by the UN2720 Mechanism (UNOPS). It says nothing about distribution to families, and it covers only cargo sent through that UN mechanism (no commercial goods, no aid sent outside it). It is not UNRWA's count, which ended on 16 January 2025: the two are never one series.
- **Read before use:** Trucks of aid that reached their intended destination inside Gaza that day, as verified by the UN2720 Mechanism (UNOPS). It says nothing about distribution to families, and it covers only cargo sent through that UN mechanism (no commercial goods, no aid sent outside it). It is not UNRWA's truck count, which ended on 16 January 2025: the two are never one series.
- **Read before use:** Pallets of aid picked up from a crossing that day and driven into Gaza, counted by the UN2720 Mechanism (UNOPS). Collected is not delivered: part of it was intercepted on the road before it reached its destination. It covers only cargo sent through that UN mechanism. It is not UNRWA's count, which ended on 16 January 2025: the two are never one series.
- **Read before use:** Tonnes of aid picked up from a crossing that day and driven into Gaza, counted by the UN2720 Mechanism (UNOPS). Collected is not delivered: part of it was intercepted on the road before it reached its destination. It covers only cargo sent through that UN mechanism. It is not UNRWA's count, which ended on 16 January 2025: the two are never one series.
- **Read before use:** Trucks that picked up aid from a crossing that day and drove it into Gaza, counted by the UN2720 Mechanism (UNOPS). Collected is not delivered: part of it was intercepted on the road before it reached its destination. It covers only cargo sent through that UN mechanism. These trucks are smaller than the ones that unload at the crossing, so the two truck counts do not compare. It is not UNRWA's truck count, which ended on 16 January 2025: the two are never one series.
- **Ask:** MCP `databank(category="aid_access", indicator="aid_un2720.collected.pallets")` · REST `/v2/databank/aid_access?indicator=aid_un2720.collected.pallets`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `aid_un2720.arrived.pallets` | UN2720: aid pallets that reached their destination in Gaza, per day · آلية 2720: مشاطيح المساعدات اللي وصلت وجهتها جوّا غزة، باليوم | pallet | 395 | 2025-05-21 | 2026-08-31 | 1 |
| `aid_un2720.arrived.tonnes` | UN2720: tonnes of aid that reached their destination in Gaza, per day · آلية 2720: وزن المساعدات اللي وصلت وجهتها جوّا غزة بالطن، باليوم | tonne | 395 | 2025-05-21 | 2026-08-31 | 1 |
| `aid_un2720.arrived.trucks` | UN2720: trucks of aid that reached their destination in Gaza, per day · آلية 2720: شاحنات المساعدات اللي وصلت وجهتها جوّا غزة، باليوم | truck | 395 | 2025-05-21 | 2026-08-31 | 1 |
| `aid_un2720.collected.pallets` | UN2720: aid pallets collected from Gaza's crossings, per day · آلية 2720: مشاطيح المساعدات اللي انستلمت من معابر غزة، باليوم | pallet | 417 | 2025-05-21 | 2026-08-31 | 1 |
| `aid_un2720.collected.tonnes` | UN2720: tonnes of aid collected from Gaza's crossings, per day · آلية 2720: وزن المساعدات اللي انستلمت من معابر غزة بالطن، باليوم | tonne | 417 | 2025-05-21 | 2026-08-31 | 1 |
| `aid_un2720.collected.trucks` | UN2720: trucks of aid collected from Gaza's crossings, per day · آلية 2720: الشاحنات اللي استلمت مساعدات من معابر غزة، باليوم | truck | 417 | 2025-05-21 | 2026-08-31 | 1 |
| `aid_un2720.offloaded.pallets` | UN2720: aid pallets offloaded at Gaza's crossings, per day · آلية 2720: مشاطيح المساعدات اللي نزلت على معابر غزة، باليوم | pallet | 333 | 2025-05-19 | 2026-08-31 | 1 |
| `aid_un2720.offloaded.tonnes` | UN2720: tonnes of aid offloaded at Gaza's crossings, per day · آلية 2720: وزن المساعدات اللي نزلت على معابر غزة بالطن، باليوم | tonne | 333 | 2025-05-19 | 2026-08-31 | 1 |
| `aid_un2720.offloaded.trucks` | UN2720: aid trucks offloaded at Gaza's crossings, per day · آلية 2720: شاحنات المساعدات اللي نزّلت حمولتها على معابر غزة، باليوم | truck | 333 | 2025-05-19 | 2026-08-31 | 1 |

## Trucks entering Gaza, looted and delivered, by week (Gaza Chamber of Commerce)

الشاحنات الداخلة إلى غزة والمنهوبة والواصلة، أسبوعياً (غرفة تجارة غزة)

- **Key:** `gazacham_trucks_weekly` · **publisher:** Gaza Chamber of Commerce and Industry — Gaza Movement of Goods weekly reports (`gaza_chamber`)
- **Rows:** 146 held · 146 a question can reach · 0 exportable · 0 older values kept
- **Span:** 2024-08-01 → 2026-09-07 · **series:** 3 · **cadence:** irregular
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-09-07)
- **Terms:** no-license-found · partners: withheld (no-redistribution); the figure is cited with its source · terms: https://gazacham.ps/InformationCenter/Reports
- **Credit:** Trucks into Gaza: Gaza Chamber of Commerce and Industry, Gaza Movement of Goods weekly reports (gazacham.ps). All rights reserved.
- **Scope:** Every truck the Chamber recorded entering Gaza, commercial and humanitarian, all crossings, by week; looted and delivered trucks for the weeks a report states them. Weeks of March to mid-May 2025 are zero by the reports' own sentences (the crossings closed on 2 March 2025).
- **Read before use:** Stated with the looted trucks for 18 weeks of May to September 2025 (week 43 states only the looted); with them it makes the week's trucks entered.
- **Read before use:** A week's count, dated by the week's first day (its last day is in the row): every truck the Gaza Chamber of Commerce recorded entering Gaza, commercial and humanitarian, through all crossings. The weeks of March to mid-May 2025 are zero because the reports state the crossings were closed; a zero is the report's sentence, not a missing figure. It is not UN2720's count (only UN-coordinated aid) nor UNRWA's (ended January 2025): never one series.
- **Read before use:** Stated by the reports for 19 weeks, 20 May to 28 September 2025; the other weeks have no figure, which is not zero. Looted here is the Chamber's word for trucks taken on the road or from warehouses before they reached the people or traders they were sent to.
- **Ask:** MCP `databank(category="aid_access", indicator="aid_gazacham.trucks_entered")` · REST `/v2/databank/aid_access?indicator=aid_gazacham.trucks_entered`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `aid_gazacham.trucks_delivered` | Trucks that reached their destination after entering Gaza, in the week beginning on this date (Gaza Chamber of Commerce) · الشاحنات التي وصلت إلى وجهتها بعد دخولها قطاع غزة، في الأسبوع الذي يبدأ بهذا التاريخ (غرفة تجارة وصناعة غزة) | truck | 18 | 2025-05-27 | 2025-09-22 | 1 |
| `aid_gazacham.trucks_entered` | Trucks that entered Gaza in the week beginning on this date, all crossings (Gaza Chamber of Commerce) · الشاحنات التي دخلت قطاع غزة في الأسبوع الذي يبدأ بهذا التاريخ، من كل المعابر (غرفة تجارة وصناعة غزة) | truck | 109 | 2024-08-01 | 2026-09-07 | 1 |
| `aid_gazacham.trucks_looted` | Trucks looted before reaching their destination after entering Gaza, in the week beginning on this date (Gaza Chamber of Commerce) · الشاحنات التي نُهبت قبل وصولها إلى وجهتها بعد دخولها قطاع غزة، في الأسبوع الذي يبدأ بهذا التاريخ (غرفة تجارة وصناعة غزة) | truck | 19 | 2025-05-20 | 2025-09-22 | 1 |
