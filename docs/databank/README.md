# The databank index · فهرس بنك البيانات

Every area, dataset and series of the Palestine databank, measured on the store at 2026-10-14 18:07 UTC. Regenerate with `.venv/bin/python -m ops.databank_index` (read-only; a minute or two).

## What is held

| | |
|---|---:|
| Observations held (current values) | 515,712 |
| … that a question can reach | 365,529 |
| … exportable as a file | 322,563 |
| … withheld from partners, the figure cited | 53,366 |
| Older values kept after a correction (never deleted) | 90,033 |
| Datasets · sources · series with rows | 62 · 112 · 3,538 |
| Event records (incidents, attacks, depopulated places) | 49,297 |
| Live readings (checkpoints, fuel, weather, internet, power) | 2,138,560 |
| Crowd messages read by the live tier | 145,446 |
| Archive texts (headlines, articles, posts, reports, chronologies) | 2,365,149 |
| Places in the register | 4,946 |

## How to ask it

- **MCP** (`https://live-api.zaidlab.xyz/mcp`): `databank(category, indicator)` for rows, `series(indicator)` for one series through time, `compare(indicators, place)`, `correlate(a, b)`, `licence(scope="sources")` for terms. Answers come in Arabic and English with their source and licence.
- **REST:** `/v2/databank/categories`, `/v2/databank/indicators`, `/v2/databank/where?indicator=…`, `/v2/databank/{category}?indicator=…`, `/v2/databank/radar` (freshness of every dataset).
- **The archive** (no API yet): `.venv/bin/python -m ops.ask_archive 'words' --months`.
- **Three words never blurred:** a value; `unknown` (nobody credible looked); `no source` (nothing measures it).

## Areas

| Area | | Datasets | Rows held | Series | Span |
|---|---|---:|---:|---:|---|
| [Live tier](live.md) | الراصد الحي | 1 | 176,810 | 56 | 2026-06-09 → 2026-10-13 |
| [Martyrs Snapshot 2023](martyrs_snapshot_2023.md) | الشهداء بأسمائهم | 1 | 72,882 | 2 | 2023-10-07 → 2026-10-13 |
| [Aid Access](aid_access.md) | وصول المساعدات | 3 | 53,640 | 16 | 2023-10-21 → 2026-09-07 |
| [Food](food.md) | الغذاء | 5 | 47,833 | 1,307 | 2007-01-01 → 2026-09-13 |
| [Refugees](refugees.md) | اللاجئون | 5 | 46,875 | 69 | 1976-01-01 → 2026-07-31 |
| [Conflict](conflict.md) | النزاع | 10 | 29,780 | 60 | 2016-01-01 → 2026-10-14 |
| [Casualties](casualties.md) | الضحايا | 3 | 17,275 | 59 | 2000-10-02 → 2026-10-01 |
| [Health](health.md) | الصحة | 4 | 15,926 | 1,431 | 1975-01-01 → 2026-10-01 |
| [Economic](economic.md) | الاقتصاد | 7 | 14,226 | 290 | 1950-01-01 → 2026-07-19 |
| [Funding](funding.md) | التمويل | 1 | 10,462 | 4 | 2013-05-27 → 2026-10-10 |
| [Infrastructure](infrastructure.md) | البنية التحتية | 4 | 8,913 | 9 | 2012-01-01 → 2026-08-07 |
| [Historical](historical.md) | تاريخي | 3 | 6,653 | 49 | 1922-01-01 → 2026-10-08 |
| [Settlements](settlements.md) | المستوطنات | 2 | 4,421 | 142 | 1967-01-01 → 2024-05-01 |
| [Prisoners](prisoners.md) | الأسرى | 3 | 3,053 | 31 | 2008-05-01 → 2026-10-01 |
| [Connectivity](connectivity.md) | الاتصال | 2 | 2,381 | 2 | 2017-02-09 → 2026-10-13 |
| [Education](education.md) | التعليم | 1 | 2,359 | 1 | 2026-08-05 → 2026-08-05 |
| [Demolitions](demolitions.md) | عمليات الهدم | 1 | 924 | 5 | 2009-01-01 → 2026-01-01 |
| [Land](land.md) | الأرض | 3 | 735 | 3 | 2025-06-30 → 2026-10-12 |
| [Culture](culture.md) | التراث | 1 | 337 | 3 | 2026-08-05 → 2026-10-12 |
| [PCBS (Palestinian Central Bureau of Statistics)](pcbs.md) | الجهاز المركزي للإحصاء الفلسطيني | 1 | 152 | 3 | 1996-01-01 → 2026-01-01 |
| [Water](water.md) | المياه | 1 | 75 | 3 | 2000-01-01 → 2024-01-01 |

Also: [events](events.md) · [the live tier](live.md) · [the news archive](archive.md) · [index.json](index.json)

## Every dataset

| Dataset | Area | Publisher | Rows | Series | Span | Freshness | Partners |
|---|---|---|---:|---:|---|---|---|
| [Aid consignments entering Gaza, Oct 2023 to Jan 2025 (UNRWA logistics log)](aid_access.md) `v1_aid_access_unrwa_aid_trucks` | aid_access | UNRWA Gaza Supply and Logistics dashboard | 50,059 | 4 | 2023-10-21 → 2025-01-16 | dead upstream | yes (attribution) |
| [Aid offloaded, collected and arrived in Gaza, per day (UN2720 Mechanism)](aid_access.md) `un2720_aid_daily` | aid_access | UN2720 Mechanism for Gaza (UNOPS) — Monitoring & Tracking Dashboard | 3,435 | 9 | 2025-05-19 → 2026-08-31 | fresh | withheld (ask); the figure is cited with its source |
| [Trucks entering Gaza, looted and delivered, by week (Gaza Chamber of Commerce)](aid_access.md) `gazacham_trucks_weekly` | aid_access | Gaza Chamber of Commerce and Industry — Gaza Movement of Goods weekly reports | 146 | 3 | 2024-08-01 → 2026-09-07 | fresh | withheld (no-redistribution); the figure is cited with its source |
| [Palestinians killed, one row per person, 2000 to September 2023 (B'Tselem)](casualties.md) `btselem_fatalities` | casualties | B'Tselem | 11,124 | 1 | 2000-10-02 → 2023-09-24 | awaiting permission | withheld (no-redistribution); the figure is cited with its source |
| [Palestinians killed by Israelis, by month, area, perpetrator, age and governorate (OCHA)](casualties.md) `ocha_fatalities_monthly` | casualties | UN OCHA oPt — Data on Casualties | 6,102 | 27 | 2008-01-01 → 2026-10-01 | fresh | withheld (no-redistribution); the figure is cited with its source |
| [Palestinian casualties since 2008: yearly totals and splits (OCHA)](casualties.md) `v1_casualties_ocha_casualties` | casualties | UN OCHA oPt — Data on Casualties | 49 | 31 | 2008-01-01 → 2026-01-01 | fresh | withheld (no-redistribution); the figure is cited with its source |
| [Political violence, demonstrations and attacks on civilians, by month and governorate (ACLED)](conflict.md) `acled_hdx_monthly` | conflict | ACLED — Armed Conflict Location & Event Data Project (HDX monthly aggregates) | 10,400 | 5 | 2016-01-01 → 2026-10-01 | fresh | withheld (internal); the figure is cited with its source |
| [Gaza's daily toll since 7 October 2023: killed, children, medics, press, civil defence (Tech for Palestine)](conflict.md) `t4p_gaza_daily` | conflict | Tech4Palestine | 9,166 | 13 | 2023-10-07 → 2026-10-13 | fresh | yes (open) |
| [Gaza Ministry of Health daily reports: killed, injured, and more, from February 2024](conflict.md) `gaza_moh_daily` | conflict | Telegram @MOHMediaGaza | 5,819 | 30 | 2024-02-14 → 2026-10-14 | fresh | withheld (no-redistribution); the figure is cited with its source |
| [West Bank toll since 7 October 2023: killed, injured, children, settler attacks (OCHA via Tech for Palestine)](conflict.md) `v1_conflict_t4p_westbank` | conflict | Tech4Palestine | 2,319 | 8 | 2023-10-07 → 2026-09-28 | fresh | yes (open) |
| [Gaza and West Bank cumulative tolls (Tech for Palestine, continued by the daily datasets)](conflict.md) `v1_conflict_tech4palestine` | conflict | Tech4Palestine | 2,076 | 4 | 2023-10-07 → 2026-08-08 | continued | yes (open) |
| [Attacks on health care, aid workers, schools, food and water systems (Insecurity Insight)](conflict.md) `insecurity_insight_incidents` | conflict | Insecurity Insight — State of Palestine incident data | 27,945 | 0 | ? → ? | live | yes (share-alike) |
| [B'Tselem events (served from the event table)](conflict.md) `v1_conflict_btselem` | conflict | B'Tselem | 6 | 0 | ? → ? | live | no-redistribution |
| [Good Shepherd Collective events (served from the event table)](conflict.md) `v1_conflict_goodshepherd` | conflict | Good Shepherd Collective | 0 | 0 | ? → ? | live | no-redistribution |
| [Depopulation of Palestinian localities, 1935 to 1967 (Palestine Open Maps, event table)](conflict.md) `v1_conflict_palopenmaps` | conflict | Palestine Open Maps | 1,163 | 0 | ? → ? | live | yes (share-alike) |
| [Georeferenced conflict events since 1989 (UCDP, event table)](conflict.md) `v1_conflict_ucdp` | conflict | UCDP Georeferenced Event Dataset | 11,968 | 0 | ? → ? | live | yes (attribution) |
| [Web censorship measurements, share anomalous per day (OONI)](connectivity.md) `v1_connectivity_ooni` | connectivity | OONI | 1,378 | 1 | 2017-02-09 → 2026-10-13 | fresh | yes (share-alike, non-commercial) |
| [Internet outages detected, with their duration (IODA)](connectivity.md) `v1_connectivity_ioda` | connectivity | IODA (Georgia Tech) internet outage detection | 1,003 | 1 | 2022-03-02 → 2026-10-13 | fresh | withheld (ask); the figure is cited with its source |
| [Heritage sites and their reported status (composite register)](culture.md) `v1_culture_heritage_composite` | culture | Palestinian heritage register (UNESCO / Ministry of Tourism / NGO reports) | 337 | 3 | 2026-08-05 → 2026-10-12 | closed corpus | withheld (ask); the figure is cited with its source |
| [Demolitions in the West Bank: structures and people displaced, by year and locality (OCHA)](demolitions.md) `v1_demolitions_ocha_demolitions` | demolitions | UN OCHA oPt — Data on Demolitions | 924 | 5 | 2009-01-01 → 2026-01-01 | fresh | withheld (no-redistribution); the figure is cited with its source |
| [Population projections 2024 to 2100, medium variant (UN World Population Prospects 2024)](economic.md) `un_wpp_2024_projection` | economic | UN DESA Population Division — World Population Prospects 2024 | 3,928 | 51 | 2024-01-01 → ? | projection | yes (attribution) |
| [Population estimates 1950 to 2023: births, deaths, ages, life expectancy (UN World Population Prospects 2024)](economic.md) `un_wpp_2024` | economic | UN DESA Population Division — World Population Prospects 2024 | 3,774 | 51 | 1950-01-01 → 2023-01-01 | fresh | yes (attribution) |
| [World Development Indicators for Palestine, 1960 on (World Bank)](economic.md) `v1_economic_worldbank` | economic | World Bank Open Data | 3,541 | 125 | 1960-01-01 → 2025-01-01 | fresh | yes (attribution) |
| [Unemployment and labour force participation by quarter, sex and age (ILO)](economic.md) `ilostat_quarterly` | economic | ILOSTAT (International Labour Organization) | 1,872 | 36 | 2000-01-01 → 2025-10-01 | fresh | yes (attribution) |
| [GDP, inflation, current account and population by year (IMF DataMapper)](economic.md) `v1_economic_imf` | economic | IMF DataMapper | 485 | 18 | 1993-01-01 → 2025-01-01 | fresh | yes (attribution, non-commercial) |
| [Commission paid in Gaza to turn a balance into cash, by day, week and month (Gaza Chamber of Commerce)](economic.md) `gazacham_cash` | economic | Gaza Chamber of Commerce and Industry — Gaza Movement of Goods weekly reports | 422 | 3 | 2025-01-01 → 2026-07-19 | fresh | withheld (no-redistribution); the figure is cited with its source |
| [PCBS-sourced indicators as the World Bank republishes them](economic.md) `v1_pcbs_pcbs` | economic | World Bank Open Data | 204 | 6 | 1990-01-01 → 2025-01-01 | fresh | yes (attribution) |
| [West Bank school register (Ministry of Education and UNICEF via OCHA)](education.md) `v1_education_hdx` | education | Humanitarian Data Exchange | 2,359 | 1 | 2026-08-05 → 2026-08-05 | fresh | yes (attribution) |
| [Monthly retail food prices by market, 2007 on (WFP)](food.md) `v1_food_wfp` | food | WFP Food Prices | 27,466 | 41 | 2007-01-01 → 2026-09-01 | fresh | yes (attribution) |
| [Household surveys on crops, livestock, income and needs (FAO DIEM)](food.md) `fao_diem_household_surveys` | food | FAO Data in Emergencies Monitoring System (DIEM) — household surveys | 13,696 | 623 | 2024-05-01 → 2026-07-03 | fresh | yes (attribution) |
| [Weekly market prices of 30 goods against pre-war, and the Gaza price index (Gaza Chamber of Commerce)](food.md) `gazacham_prices` | food | Gaza Chamber of Commerce and Industry — Gaza Movement of Goods weekly reports | 3,809 | 103 | 2024-08-29 → 2026-09-13 | fresh | withheld (no-redistribution); the figure is cited with its source |
| [Gaza market prices by day, as a market channel posts them (68 goods by area)](food.md) `market_channel_prices` | food | أسعار السوق - غزة (Telegram channel @asarsook) | 1,848 | 280 | 2024-11-19 → 2026-09-01 | closed corpus | withheld (no-redistribution); the figure is cited with its source |
| [People in each IPC phase of acute food insecurity in Gaza, by analysis and area (IPC)](food.md) `ipc_phases` | food | Integrated Food Security Phase Classification (IPC), via HDX | 1,014 | 260 | 2023-11-01 → 2026-07-01 | fresh | yes (open) |
| [Humanitarian funding flows: paid, committed, pledged (OCHA Financial Tracking Service)](funding.md) `v1_funding_unfts` | funding | UN OCHA Financial Tracking Service | 10,462 | 4 | 2013-05-27 → 2026-10-10 | fresh | yes (attribution) |
| [Health indicators by year, 1975 on: mortality, disease, services, water and sanitation (WHO GHO)](health.md) `v1_health_who` | health | WHO Global Health Observatory | 13,014 | 1405 | 1975-01-01 → 2025-01-01 | fresh | yes (share-alike, non-commercial) |
| [Attacks on health care by month, 2017 on: attacks, killed, injured, what was hit (WHO SSA)](health.md) `who_ssa_monthly` | health | WHO SSA | 2,912 | 26 | 2017-07-01 → 2026-10-01 | fresh | yes (attribution) |
| [Gaza Ministry of Health (served through the daily dataset)](health.md) `v1_health_gaza_moh` | health | Gaza Ministry of Health | 0 | 0 | ? → ? | live | no-redistribution |
| [Health facilities (HDX, event table)](health.md) `v1_health_hdx` | health | Humanitarian Data Exchange | 0 | 0 | ? → ? | live | ask |
| [Locality populations in 1922, 1931, 1945 and 2016, and what became of each place (Palestine Open Maps)](historical.md) `v1_historical_palopenmaps` | historical | Palestine Open Maps | 6,548 | 2 | 1922-01-01 → 2016-01-01 | closed corpus | yes (share-alike) |
| [Cited figures: one publisher's statement per row, with its document](historical.md) `cited_figures` | historical | Cited figures (hand-entered, each with its publisher) | 105 | 47 | 1947-12-31 → 2026-10-08 | closed corpus | yes (attribution, non-commercial) |
| [Historical events 1967 to 2000 (event table)](historical.md) `v1_historical_archives` | historical | Historical Palestine archives (1948–2000) | 30 | 0 | ? → ? | live | ask |
| [Night lights over each governorate by month, 2012 on (World Bank, Black Marble)](infrastructure.md) `nightlights_monthly` | infrastructure | World Bank Space2Stats — Black Marble night lights (data catalog 0066940) | 5,376 | 2 | 2012-01-01 → 2025-12-01 | fresh | yes (attribution) |
| [Buildings destroyed in Gaza: homes, schools, mosques, to October 2025 (Tech for Palestine)](infrastructure.md) `v1_infrastructure_tech4palestine` | infrastructure | Tech4Palestine | 2,920 | 4 | 2023-10-07 → 2025-10-05 | dead upstream | yes (open) |
| [Mandate-era village boundaries and the Separation Barrier's segments (HDX)](infrastructure.md) `v1_infrastructure_hdx` | infrastructure | Humanitarian Data Exchange | 603 | 2 | 2026-08-07 → 2026-08-07 | fresh | yes (attribution) |
| [Structures damaged in Gaza by satellite assessment (UNOSAT)](infrastructure.md) `v1_infrastructure_unosat` | infrastructure | UNOSAT (UNITAR) | 14 | 1 | 2023-10-10 → 2025-10-11 | fresh | yes (share-alike) |
| [Structures demolished per day, West Bank and East Jerusalem (Good Shepherd Collective)](land.md) `v1_land_goodshepherd` | land | Good Shepherd Collective | 275 | 1 | 2025-06-30 → 2026-10-08 | fresh | withheld (no-redistribution); the figure is cited with its source |
| [Separation Barrier segments (OCHA, January 2018)](land.md) `v1_land_ocha` | land | UN OCHA oPt | 261 | 1 | 2026-10-12 → 2026-10-12 | fresh | yes (attribution) |
| [Israeli settlement built-up areas in the West Bank (Peace Now via OCHA)](land.md) `v1_land_peace_now` | land | Peace Now — Settlement Watch | 199 | 1 | 2026-10-12 → 2026-10-12 | fresh | withheld (no-redistribution); the figure is cited with its source |
| [The live tier's daily rollup: reports per checkpoint and state per day, from 9 June 2026](live.md) `tier1_daily` | live | Palestine v2 tier-1 daily rollup | 176,810 | 56 | 2026-06-09 → 2026-10-13 | live | not in the databank's doors |
| [Gaza's dead identified by name (Ministry of Health list via Tech for Palestine)](martyrs_snapshot_2023.md) `v1_martyrs_snapshot_2023_tech4palestine` | martyrs_snapshot_2023 | Tech4Palestine | 72,882 | 2 | 2023-10-07 → 2026-10-13 | fresh | yes (open) |
| [Consumer price index, population and poverty, from PCBS itself](pcbs.md) `v1_economic_pcbs_direct` | pcbs | Palestinian Central Bureau of Statistics (PCBS) | 152 | 3 | 1996-01-01 → 2026-01-01 | fresh | yes (attribution) |
| [Palestinians held by Israel by month, 2011 on: children, women, administrative detention and more (Addameer)](prisoners.md) `v1_prisoners_addameer` | prisoners | Addameer Prisoner Support and Human Rights Association (addameer.ps) | 1,681 | 13 | 2011-01-01 → 2026-10-01 | fresh | withheld (no-redistribution); the figure is cited with its source |
| [Palestinians held by Israel by month and status, 2008 on (HaMoked)](prisoners.md) `v1_prisoners_hamoked` | prisoners | HaMoked | 1,100 | 5 | 2008-05-01 → 2026-10-01 | fresh | withheld (no-redistribution); the figure is cited with its source |
| [Arrests and administrative orders by month, 2016 to January 2024 (the prisoner institutions' joint report)](prisoners.md) `arrests_joint_monthly` | prisoners | Addameer Prisoner Support and Human Rights Association (addameer.ps) | 272 | 13 | 2016-01-01 → 2024-01-01 | closed corpus | withheld (no-redistribution); the figure is cited with its source |
| [People from Palestine counted by UNHCR, by country of asylum, category, sex and age, 1976 on](refugees.md) `unhcr_population_hdx` | refugees | UNHCR Operational Data Portal | 45,197 | 32 | 1976-01-01 → 2025-01-01 | fresh | yes (attribution) |
| [Palestinian refugees and asylum-seekers abroad, by country of asylum (UNHCR)](refugees.md) `v1_refugees_unhcr` | refugees | UNHCR Operational Data Portal | 1,157 | 1 | 2010-01-01 → 2025-01-01 | fresh | yes (attribution) |
| [Displacement events with the people displaced (IDMC)](refugees.md) `v1_refugees_idmc` | refugees | IDMC | 338 | 1 | 2025-01-01 → 2026-07-31 | fresh | yes (attribution) |
| [UNRWA-registered Palestine refugees by field, sex and age (December 2025)](refugees.md) `unrwa_registered_hdx` | refugees | UNRWA | 119 | 34 | 2025-12-01 → 2025-12-01 | dead upstream | yes (attribution) |
| [Registered refugees per camp (UNRWA camp pages)](refugees.md) `v1_refugees_unrwa` | refugees | UNRWA | 64 | 1 | 2026-06-10 → 2026-06-10 | closed corpus | yes (attribution, non-commercial) |
| [Population of 141 Israeli settlements by year, 1980 on (Peace Now)](settlements.md) `peacenow_settlement_population` | settlements | Peace Now — Settlement Watch | 4,370 | 141 | 1980-01-01 → 2024-05-01 | fresh | withheld (no-redistribution); the figure is cited with its source |
| [Israeli settlers in the West Bank, excluding East Jerusalem, by year since 1967 (Peace Now)](settlements.md) `v1_settlements_peace_now` | settlements | Peace Now — Settlement Watch | 51 | 1 | 1967-01-01 → 2024-01-01 | fresh | withheld (no-redistribution); the figure is cited with its source |
| [Water and sanitation: open defecation by area type (WHO GHO)](water.md) `who_gho_wash` | water | WHO Global Health Observatory | 75 | 3 | 2000-01-01 → 2024-01-01 | fresh | yes (share-alike, non-commercial) |
