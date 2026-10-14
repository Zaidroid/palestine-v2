# Historical · تاريخي

Measured on the store at 2026-10-14 18:07 UTC by `ops/databank_index.py`. [Back to the index](README.md)

## Locality populations in 1922, 1931, 1945 and 2016, and what became of each place (Palestine Open Maps)

سكان البلدات في 1922 و1931 و1945 و2016، ومصير كل بلدة (خرائط فلسطين المفتوحة)

- **Key:** `v1_historical_palopenmaps` · **publisher:** Palestine Open Maps (`palopenmaps`)
- **Rows:** 6,548 held · 6,548 a question can reach · 6,548 exportable · 9,100 older values kept
- **Span:** 1922-01-01 → 2016-01-01 · **series:** 2 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** closed collection: complete, nothing more will come (last information 2016-01-01)
- **Terms:** ODbL-1.0 · partners: yes (share-alike) · terms: https://data.palopenmaps.org/copyright
- **Credit:** Locality data: Palestine Open Maps (palopenmaps.org) and contributors, ODbL 1.0 — derived databases must remain ODbL.
- **Ask:** MCP `databank(category="historical", indicator="historical.population")` · REST `/v2/databank/historical?indicator=historical.population`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `historical.locality_status` | Locality status (remaining, depopulated, abandoned…) and its date (Palestine Open Maps) · وضع التجمّع السكاني (باقٍ، مهجَّر، مهجور…) وتاريخه (Palestine Open Maps) |  | 2,490 | 1935-01-01 | 2005-08-22 | 2,486 |
| `historical.population` | Locality population in 1922, 1931, 1945 or 2016 (Palestine Open Maps) · عدد سكان التجمّع في 1922 أو 1931 أو 1945 أو 2016 (Palestine Open Maps) | persons | 4,058 | 1922-01-01 | 2016-01-01 | 2,183 |

## Cited figures: one publisher's statement per row, with its document

أرقام مقتبسة: تصريح ناشر واحد في كل سجل، مع وثيقته

- **Key:** `cited_figures` · **publisher:** Cited figures (hand-entered, each with its publisher) (`cited_reference`)
- **Rows:** 105 held · 105 a question can reach · 105 exportable · 0 older values kept
- **Span:** 1947-12-31 → 2026-10-08 · **series:** 47 · **cadence:** irregular
- **Freshness:** closed collection: complete, nothing more will come (last information 2026-10-08)
- **Terms:** LicenseRef-Cited-Figures · partners: yes (attribution, non-commercial) · terms: none found
- **Credit:** Figures cited from named publications; each row names its publisher, its document and the day it was read.
- **Scope:** Hand-entered. One row is one publisher's figure with its document, URL, sentence and the day it was read. Several publishers on one question are several rows and are never added or averaged.
- **Read before use:** One publisher's figure per row, entered by hand with its document and the day it was read. Publishers disagree, and their figures are never added or averaged: read the publisher on each row.
- **Read before use:** A dated event as one named publisher states it, entered by hand: the row carries the publisher's sentence, the document and the day it was read.
- **Read before use:** A figure cited from one named publication, entered by hand: the row names the publisher, the document and the day it was read.
- **Read before use:** One publisher's figure per row, entered by hand with its document and the day it was read. Publishers count different things (villages, localities, towns) and their figures are never added or averaged.
- **Read before use:** UNOSAT's own stated share of the Gaza Strip's structures that are damaged, per satellite assessment, entered by hand from UNOSAT's products. From 1 April 2024 UNOSAT's totals add a 'possibly damaged' class, so the series is not like for like across that date.
- **Read before use:** UNOSAT's count of structures in the Gaza Strip, per satellite assessment, entered by hand from UNOSAT's products: a running total, never added across dates. From 1 April 2024 the total adds a 'possibly damaged' class, so the series is not like for like across that date.
- **Ask:** MCP `databank(category="historical", indicator="cited.unosat_gaza.share_of_structures_affected")` · REST `/v2/databank/historical?indicator=cited.unosat_gaza.share_of_structures_affected`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `cited.al_aqsa_1990.killed` | Killed in the al-Aqsa Mosque massacre, October 1990 (cited figures) · شهداء مجزرة المسجد الأقصى عام 1990 (أرقام مقتبسة) | persons | 1 | 1990-10-08 | 1990-10-08 | 1 |
| `cited.balad_al_shaykh_1947.killed` | Killed in the Balad al-Shaykh massacre, December 1947 (cited figures) · شهداء مجزرة بلد الشيخ عام 1947 (أرقام مقتبسة) | persons | 1 | 1947-12-31 | 1947-12-31 | 0 |
| `cited.dawayima_1948.killed` | Killed in the al-Dawayima massacre, October 1948 (cited figures) · شهداء مجزرة الدوايمة عام 1948 (أرقام مقتبسة) | persons | 1 | 1948-10-29 | 1948-10-29 | 0 |
| `cited.dawayima_1948.missing` | Missing after the al-Dawayima massacre, October 1948 (cited figures) · المفقودون بعد مجزرة الدوايمة عام 1948 (أرقام مقتبسة) | persons | 1 | 1948-10-29 | 1948-10-29 | 0 |
| `cited.deir_yassin_1948.killed` | Killed in the Deir Yassin massacre, April 1948 (cited figures) · شهداء مجزرة دير ياسين عام 1948 (أرقام مقتبسة) | persons | 3 | 1948-04-09 | 1948-04-09 | 0 |
| `cited.first_intifada.killed` | Palestinians killed in the First Intifada, 1987–1993 (cited figures) · شهداء الانتفاضة الأولى 1987–1993 (أرقام مقتبسة) | persons | 1 | 1987-12-09 | 1987-12-09 | 0 |
| `cited.gaza_2008_2009.killed` | Palestinians killed in the war on Gaza, December 2008 to January 2009 (cited figures) · شهداء العدوان على قطاع غزة 2008–2009 (أرقام مقتبسة) | persons | 1 | 2008-12-27 | 2008-12-27 | 1 |
| `cited.gaza_2012.killed` | Palestinians killed in the war on Gaza, November 2012 (cited figures) · شهداء العدوان على قطاع غزة 2012 (أرقام مقتبسة) | persons | 1 | 2012-11-14 | 2012-11-14 | 1 |
| `cited.gaza_2014.killed` | Palestinians killed in the war on Gaza, July to August 2014 (cited figures) · شهداء العدوان على قطاع غزة 2014 (أرقام مقتبسة) | persons | 1 | 2014-07-08 | 2014-07-08 | 1 |
| `cited.gaza_2021.killed` | Palestinians killed in the war on Gaza, May 2021 (cited figures) · شهداء العدوان على قطاع غزة 2021 (أرقام مقتبسة) | persons | 1 | 2021-05-10 | 2021-05-10 | 1 |
| `cited.gaza_blockade_2025.began` | Total blockade of Gaza, 2025: the day it began (cited figures) · الحصار الكامل على قطاع غزة 2025: يوم بدايته (أرقام مقتبسة) | events | 1 | 2025-03-02 | 2025-03-02 | 1 |
| `cited.gaza_blockade_2025.ended` | Total blockade of Gaza, 2025: the day the first aid trucks were let in again (cited figures) · الحصار الكامل على قطاع غزة 2025: يوم السماح بدخول أولى شاحنات المساعدات (أرقام مقتبسة) | events | 1 | 2025-05-19 | 2025-05-19 | 1 |
| `cited.gaza_ceasefire_2025_01.took_effect` | Gaza ceasefire of 19 January 2025: the day it took effect (cited figures) · وقف إطلاق النار في غزة، 19 يناير 2025: يوم دخوله حيّز التنفيذ (أرقام مقتبسة) | events | 1 | 2025-01-19 | 2025-01-19 | 1 |
| `cited.gaza_ceasefire_2025_10.took_effect` | Gaza ceasefire of 10 October 2025: the day it took effect (cited figures) · وقف إطلاق النار في غزة، 10 أكتوبر 2025: يوم دخوله حيّز التنفيذ (أرقام مقتبسة) | events | 1 | 2025-10-10 | 2025-10-10 | 1 |
| `cited.gaza_famine_2025.determined` | Famine in Gaza Governorate: the day the IPC Famine Review Committee determined it (cited figures) · المجاعة في محافظة غزة: يوم إعلانها من لجنة مراجعة المجاعة (IPC) (أرقام مقتبسة) | events | 1 | 2025-08-22 | 2025-08-22 | 1 |
| `cited.gaza_missing.persons` | People missing in Gaza since 7 October 2023, by publisher (cited figures) · المفقودون في قطاع غزة منذ 7 أكتوبر 2023، حسب الناشر (أرقام مقتبسة) | persons | 3 | 2024-12-29 | 2025-01-01 | 1 |
| `cited.gaza_under_rubble.bodies` | Bodies estimated to be under the rubble in Gaza, by publisher (cited figures) · الشهداء المقدَّر وجودهم تحت الأنقاض في قطاع غزة، حسب الناشر (أرقام مقتبسة) | persons | 3 | 2026-09-15 | 2026-10-08 | 1 |
| `cited.gaza_war_resumed_2025_03.killed` | Killed in Gaza when the war resumed on 18 March 2025, by publisher (cited figures) · الشهداء في قطاع غزة عند استئناف الحرب في 18 مارس 2025، حسب الناشر (أرقام مقتبسة) | persons | 2 | 2025-03-18 | 2025-03-19 | 1 |
| `cited.great_march_of_return.killed` | Palestinians killed in the Great March of Return, Gaza, 2018–2019 (cited figures) · شهداء مسيرات العودة الكبرى في قطاع غزة 2018–2019 (أرقام مقتبسة) | persons | 1 | 2018-03-30 | 2018-03-30 | 1 |
| `cited.ibrahimi_mosque_1994.killed` | Killed in the Ibrahimi Mosque massacre, Hebron, February 1994 (cited figures) · شهداء مجزرة الحرم الإبراهيمي في الخليل عام 1994 (أرقام مقتبسة) | persons | 1 | 1994-02-25 | 1994-02-25 | 1 |
| `cited.kafr_qasim_1956.killed` | Killed in the Kafr Qasim massacre, October 1956 (cited figures) · شهداء مجزرة كفر قاسم عام 1956 (أرقام مقتبسة) | persons | 1 | 1956-10-29 | 1956-10-29 | 0 |
| `cited.khan_yunis_1956.killed` | Killed in the Khan Yunis massacre, November 1956 (cited figures) · شهداء مجزرة خان يونس عام 1956 (أرقام مقتبسة) | persons | 1 | 1956-11-03 | 1956-11-03 | 1 |
| `cited.land_area.historic_palestine_km2` | Land area of historic Palestine, km² (cited figures) · مساحة فلسطين التاريخية بالكيلومتر المربع (أرقام مقتبسة) | km2 | 1 | 2021-01-01 | 2021-01-01 | 0 |
| `cited.land_area.west_bank_and_gaza_km2` | Land area of the West Bank and Gaza Strip, km² (cited figures) · مساحة الضفة الغربية وقطاع غزة بالكيلومتر المربع (أرقام مقتبسة) | km2 | 1 | 2021-01-01 | 2021-01-01 | 0 |
| `cited.land_day_1976.killed` | Killed on Land Day, 30 March 1976 (cited figures) · شهداء يوم الأرض، 30 مارس 1976 (أرقام مقتبسة) | persons | 1 | 1976-03-30 | 1976-03-30 | 0 |
| `cited.lydda_1948.expelled` | Expelled from Lydda and Ramle, July 1948 (cited figures) · المهجَّرون قسرًا من اللد والرملة عام 1948 (أرقام مقتبسة) | persons | 1 | 1948-07-12 | 1948-07-12 | 0 |
| `cited.lydda_1948.killed` | Killed in the Lydda massacre, July 1948 (cited figures) · شهداء مجزرة اللد عام 1948 (أرقام مقتبسة) | persons | 2 | 1948-07-12 | 1948-07-12 | 0 |
| `cited.nakba_1948.killed` | Palestinians killed in the Nakba, 1947–1949 (cited figures) · شهداء النكبة 1947–1949 (أرقام مقتبسة) | persons | 2 | 1948-01-01 | 1948-01-01 | 0 |
| `cited.nakba_1948.massacres` | Massacres committed in the Nakba, 1947–1949 (cited figures) · المجازر المرتكبة في النكبة 1947–1949 (أرقام مقتبسة) | events | 2 | 1948-01-01 | 1948-01-01 | 0 |
| `cited.nakba_1948.refugees` | Palestinians made refugees in the Nakba, 1947–1949 (cited figures) · اللاجئون الفلسطينيون في النكبة 1947–1949 (أرقام مقتبسة) | persons | 4 | 1948-01-01 | 1948-01-01 | 0 |
| `cited.nakba_1948.villages_destroyed` | Palestinian villages and localities destroyed or depopulated in the Nakba (cited figures) · القرى والتجمعات الفلسطينية المدمَّرة أو المهجَّرة في النكبة (أرقام مقتبسة) | localities | 4 | 1948-01-01 | 1948-01-01 | 0 |
| `cited.naksa_1967.displaced` | Palestinians displaced in the 1967 war (the Naksa) (cited figures) · النازحون الفلسطينيون في حرب 1967 (النكسة) (أرقام مقتبسة) | persons | 1 | 1967-06-05 | 1967-06-05 | 1 |
| `cited.qibya_1953.killed` | Killed in the Qibya massacre, October 1953 (cited figures) · شهداء مجزرة قبية عام 1953 (أرقام مقتبسة) | persons | 1 | 1953-10-14 | 1953-10-14 | 1 |
| `cited.rafah_1956.killed` | Killed in the Rafah massacre, November 1956 (cited figures) · شهداء مجزرة رفح عام 1956 (أرقام مقتبسة) | persons | 1 | 1956-11-12 | 1956-11-12 | 1 |
| `cited.sabra_shatila_1982.killed` | Killed in the Sabra and Shatila massacre, Lebanon, September 1982 (cited figures) · شهداء مجزرة صبرا وشاتيلا في لبنان عام 1982 (أرقام مقتبسة) | persons | 2 | 1982-09-16 | 1982-09-16 | 0 |
| `cited.safsaf_1948.killed` | Killed in the Safsaf massacre, October 1948 (cited figures) · شهداء مجزرة صفصاف عام 1948 (أرقام مقتبسة) | persons | 1 | 1948-10-29 | 1948-10-29 | 0 |
| `cited.saliha_1948.killed` | Killed in the Saliha massacre, October 1948 (cited figures) · شهداء مجزرة صلحا عام 1948 (أرقام مقتبسة) | persons | 1 | 1948-10-30 | 1948-10-30 | 0 |
| `cited.samu_1966.killed` | Killed in the Israeli raid on as-Samu, November 1966 (cited figures) · شهداء العدوان الإسرائيلي على السموع عام 1966 (أرقام مقتبسة) | persons | 1 | 1966-11-13 | 1966-11-13 | 1 |
| `cited.second_intifada.killed` | Palestinians killed in the Second Intifada, 2000–2008 (cited figures) · شهداء الانتفاضة الثانية 2000–2008 (أرقام مقتبسة) | persons | 1 | 2000-09-29 | 2000-09-29 | 0 |
| `cited.settlers.west_bank_and_east_jerusalem_population` | Israeli settlers in the West Bank, including East Jerusalem (cited figures) · عدد المستوطنين في الضفة الغربية بما فيها القدس الشرقية (أرقام مقتبسة) | persons | 1 | 2024-12-31 | 2024-12-31 | 1 |
| `cited.settlers.west_bank_population` | Israeli settlers in the West Bank, excluding East Jerusalem (cited figures) · عدد المستوطنين في الضفة الغربية دون القدس الشرقية (أرقام مقتبسة) | persons | 1 | 2024-01-01 | 2024-01-01 | 1 |
| `cited.tantura_1948.killed` | Killed in the Tantura massacre, May 1948 (cited figures) · شهداء مجزرة الطنطورة عام 1948 (أرقام مقتبسة) | persons | 1 | 1948-05-22 | 1948-05-22 | 0 |
| `cited.tel_al_zaatar_1976.killed` | Killed in the Tel al-Zaatar massacre, Lebanon, August 1976 (cited figures) · شهداء مجزرة تل الزعتر في لبنان عام 1976 (أرقام مقتبسة) | persons | 1 | 1976-08-12 | 1976-08-12 | 0 |
| `cited.unosat_gaza.share_of_structures_affected` | Share of the Gaza Strip's structures damaged, as UNOSAT states it (cited figures) · نسبة المباني المتضررة في قطاع غزة كما تذكرها يونوسات (أرقام مقتبسة) | percent | 14 | 2023-10-15 | 2026-06-16 | 1 |
| `cited.unosat_gaza.structures_affected` | Structures damaged or destroyed in the Gaza Strip, per UNOSAT assessment (cited figures) · المباني المتضررة أو المدمَّرة في قطاع غزة حسب تقييمات يونوسات (أرقام مقتبسة) | structures | 14 | 2023-10-15 | 2026-06-16 | 1 |
| `cited.unosat_gaza.structures_destroyed` | Structures destroyed in the Gaza Strip, per UNOSAT assessment (cited figures) · المباني المدمَّرة في قطاع غزة حسب تقييمات يونوسات (أرقام مقتبسة) | structures | 14 | 2023-10-15 | 2026-06-16 | 1 |
| `cited.west_bank_injured.persons` | Palestinians injured in the West Bank, by period, per OCHA (cited figures) · الجرحى الفلسطينيون في الضفة الغربية حسب الفترة، وفق أوتشا (أرقام مقتبسة) | persons | 3 | 2023-10-07 | 2025-01-01 | 1 |

## Historical events 1967 to 2000 (event table)

أحداث تاريخية 1967 إلى 2000 (جدول الأحداث)

- **Key:** `v1_historical_archives` · **publisher:** Historical Palestine archives (1948–2000) (`historical_archives`)
- **Rows:** 0 held · 0 a question can reach · 0 exportable · 0 older values kept · 30 event records
- **Span:** ? → ? · **series:** 0 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** not judged by the radar (the live tier's own rollup)
- **Terms:** varies · partners: ask · terms: none found
- **Credit:** Historical data compiled from public archives and academic sources.
- **Ask:** its records are events: see [events](events.md)
