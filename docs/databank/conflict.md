# Conflict · النزاع

Measured on the store at 2026-10-18 20:41 UTC by `ops/databank_index.py`. [Back to the index](README.md)

## Attacks on health care, aid workers, schools, food and water systems (Insecurity Insight)

الاعتداءات على الرعاية الصحية وعمّال الإغاثة والمدارس وأنظمة الغذاء والمياه (إنسكيوريتي إنسايت)

- **Key:** `insecurity_insight_incidents` · **publisher:** Insecurity Insight — State of Palestine incident data (`insecurity_insight`)
- **Rows:** 0 held · 24,300 a question can reach · 24,300 exportable · 0 older values kept · 27,945 event records
- **Span:** ? → ? · **series:** 0 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** not judged by the radar (the live tier's own rollup)
- **Terms:** CC-BY-SA-4.0 · partners: yes (share-alike) · terms: https://data.humdata.org/dataset/b36e1975-4428-4caa-9b00-e0d8793130d0
- **Credit:** Incident data: Insecurity Insight (insecurityinsight.org) via HDX, CC BY-SA. Not a complete or representative list; not independently verified.
- **Ask:** its records are events: see [events](events.md)

## Georeferenced conflict events since 1989 (UCDP, event table)

أحداث النزاع بمواقعها منذ 1989 (UCDP، جدول الأحداث)

- **Key:** `v1_conflict_ucdp` · **publisher:** UCDP Georeferenced Event Dataset (`ucdp`)
- **Rows:** 0 held · 11,876 a question can reach · 11,876 exportable · 0 older values kept · 11,968 event records
- **Span:** ? → ? · **series:** 0 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** not judged by the radar (the live tier's own rollup)
- **Terms:** CC-BY-4.0 · partners: yes (attribution) · terms: https://ucdp.uu.se/downloads/
- **Credit:** Conflict events: Uppsala Conflict Data Program (UCDP), Georeferenced and Candidate Events datasets, CC BY 4.0. UCDP Georeferenced Event Dataset (GED) and UCDP Candidate Events Dataset, Uppsala University (ucdp.uu.se). Sundberg & Melander (2013), Journal of Peace Research 50(4); Davies, Pettersson & Öberg (2026), Journal of Peace Research; candidate events: Hegre, Croicu, Eck & Högbladh (2020), Research & Politics.
- **Ask:** its records are events: see [events](events.md)

## Political violence, demonstrations and attacks on civilians, by month and governorate (ACLED)

العنف السياسي والمظاهرات والاعتداءات على المدنيين، شهرياً حسب المحافظة (أكليد)

- **Key:** `acled_hdx_monthly` · **publisher:** ACLED — Armed Conflict Location & Event Data Project (HDX monthly aggregates) (`acled`)
- **Rows:** 10,400 held · 0 a question can reach · 0 exportable · 55 older values kept
- **Span:** 2016-01-01 → 2026-10-01 · **series:** 5 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-10-01)
- **Terms:** LicenseRef-ACLED-EULA · partners: withheld (internal); the figure is cited with its source · terms: https://acleddata.com/terms-of-use
- **Credit:** ACLED — Armed Conflict Location & Event Data Project (acleddata.com), via HDX. Held under ACLED's Terms of Use; not served.
- **Ask:** MCP `databank(category="conflict", indicator="acled.civilian_targeting.events")` · REST `/v2/databank/conflict?indicator=acled.civilian_targeting.events`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `acled.civilian_targeting.events` | Events targeting civilians per month, by governorate (ACLED) · أحداث استهداف المدنيين شهريًا حسب المحافظة (ACLED) | events | 2,080 | 2016-01-01 | 2026-10-01 | 16 |
| `acled.civilian_targeting.fatalities` | Reported fatalities in events targeting civilians per month, by governorate (ACLED) · قتلى أحداث استهداف المدنيين شهريًا حسب المحافظة (ACLED) | persons | 2,080 | 2016-01-01 | 2026-10-01 | 16 |
| `acled.demonstrations.events` | Demonstrations per month, by governorate (ACLED) · المظاهرات شهريًا حسب المحافظة (ACLED) | events | 2,080 | 2016-01-01 | 2026-10-01 | 16 |
| `acled.political_violence.events` | Political violence events per month, by governorate (ACLED) · أحداث العنف السياسي شهريًا حسب المحافظة (ACLED) | events | 2,080 | 2016-01-01 | 2026-10-01 | 16 |
| `acled.political_violence.fatalities` | Reported fatalities from political violence per month, by governorate (ACLED) · قتلى أحداث العنف السياسي شهريًا حسب المحافظة (ACLED) | persons | 2,080 | 2016-01-01 | 2026-10-01 | 16 |

## Gaza's daily toll since 7 October 2023: killed, children, medics, press, civil defence (Tech for Palestine)

حصيلة غزة اليومية منذ 7 تشرين الأول 2023: الشهداء والأطفال والطواقم الطبية والصحفيون والدفاع المدني (تك فور بالستاين)

- **Key:** `t4p_gaza_daily` · **publisher:** Tech4Palestine (`tech4palestine`)
- **Rows:** 9,189 held · 9,189 a question can reach · 9,189 exportable · 8 older values kept
- **Span:** 2023-10-07 → 2026-10-15 · **series:** 13 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-10-15)
- **Terms:** Unlicense · partners: yes (open) · terms: https://github.com/TechForPalestine/palestine-datasets/blob/main/LICENSE
- **Credit:** Data: Tech4Palestine (data.techforpalestine.org), public domain (Unlicense); credited by choice.
- **Ask:** MCP `databank(category="conflict", indicator="conflict.gaza_cumulative_killed_children")` · REST `/v2/databank/conflict?indicator=conflict.gaza_cumulative_killed_children`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `conflict.gaza_cumulative_injured` | Injured in Gaza, cumulative since 7 October 2023 (Gaza Ministry of Health via Tech for Palestine) · الإصابات في قطاع غزة، تراكمي منذ 7 أكتوبر 2023 (وزارة الصحة في غزة عبر Tech for Palestine) | persons | 53 | 2026-08-09 | 2026-10-15 | 1 |
| `conflict.gaza_cumulative_killed` | Killed in Gaza, cumulative since 7 October 2023 (Gaza Ministry of Health via Tech for Palestine) · الشهداء في قطاع غزة، تراكمي منذ 7 أكتوبر 2023 (وزارة الصحة في غزة عبر Tech for Palestine) | persons | 53 | 2026-08-09 | 2026-10-15 | 1 |
| `conflict.gaza_cumulative_killed_children` | Children killed in Gaza, cumulative since 7 October 2023 (Tech for Palestine) · الشهداء الأطفال في قطاع غزة، تراكمي منذ 7 أكتوبر 2023 (Tech for Palestine) | persons | 1,065 | 2023-10-07 | 2026-10-15 | 1 |
| `conflict.gaza_cumulative_killed_civil_defence` | Civil defence personnel killed in Gaza, cumulative since 7 October 2023 (Tech for Palestine) · شهداء الدفاع المدني في قطاع غزة، تراكمي منذ 7 أكتوبر 2023 (Tech for Palestine) | persons | 1,065 | 2023-10-07 | 2026-10-15 | 1 |
| `conflict.gaza_cumulative_killed_medical` | Medical personnel killed in Gaza, cumulative since 7 October 2023 (Tech for Palestine) · شهداء الطواقم الطبية في قطاع غزة، تراكمي منذ 7 أكتوبر 2023 (Tech for Palestine) | persons | 1,065 | 2023-10-07 | 2026-10-15 | 1 |
| `conflict.gaza_cumulative_killed_press` | Journalists killed in Gaza, cumulative since 7 October 2023 (Tech for Palestine) · الشهداء الصحفيون في قطاع غزة، تراكمي منذ 7 أكتوبر 2023 (Tech for Palestine) | persons | 1,065 | 2023-10-07 | 2026-10-15 | 1 |
| `conflict.gaza_cumulative_killed_women` | Women killed in Gaza, cumulative since 7 October 2023 (Tech for Palestine) · الشهيدات من النساء في قطاع غزة، تراكمي منذ 7 أكتوبر 2023 (Tech for Palestine) | persons | 1,065 | 2023-10-07 | 2026-10-15 | 1 |
| `conflict.gaza_cumulative_massacres` | Massacres (multiple-fatality events) in Gaza, cumulative since 7 October 2023 (Tech for Palestine) · المجازر (أحداث سقط فيها عدة شهداء) في قطاع غزة، تراكمي منذ 7 أكتوبر 2023 (Tech for Palestine) | events | 1,065 | 2023-10-07 | 2026-10-15 | 1 |
| `conflict.gaza_daily_injured` | Injured in Gaza per bulletin day (Tech for Palestine) · الإصابات في قطاع غزة حسب يوم التقرير (Tech for Palestine) | persons | 1,021 | 2023-10-11 | 2026-10-15 | 1 |
| `conflict.gaza_daily_killed` | Killed in Gaza per bulletin day, may include retroactive additions (Tech for Palestine) · الشهداء في قطاع غزة حسب يوم التقرير، وقد يشمل إضافات بأثر رجعي (Tech for Palestine) | persons | 1,046 | 2023-10-07 | 2026-10-15 | 1 |
| `conflict.gaza_daily_killed_committee` | Deaths recognised by the judicial committee in Gaza, per bulletin day (Tech for Palestine) · شهداء اعتمدتهم اللجنة القضائية في قطاع غزة حسب يوم التقرير (Tech for Palestine) | persons | 44 | 2025-01-11 | 2026-10-10 | 1 |
| `conflict.gaza_daily_killed_new` | Newly killed in Gaza per bulletin day, during or after the 2025 truce (Tech for Palestine) · الشهداء الجدد في قطاع غزة حسب يوم التقرير، أثناء هدنة 2025 أو بعدها (Tech for Palestine) | persons | 494 | 2025-01-11 | 2026-10-15 | 1 |
| `conflict.gaza_daily_killed_succumbed` | Died of earlier wounds in Gaza, per bulletin day (Tech for Palestine) · شهداء متأثرون بجراحهم في قطاع غزة حسب يوم التقرير (Tech for Palestine) | persons | 88 | 2025-01-26 | 2026-10-14 | 1 |

## Gaza Ministry of Health daily reports: killed, injured, and more, from February 2024

تقارير وزارة الصحة في غزة اليومية: الشهداء والجرحى وغيرها، من شباط 2024

- **Key:** `gaza_moh_daily` · **publisher:** Telegram @MOHMediaGaza (`tg_mohmediagaza`)
- **Rows:** 5,846 held · 5,846 a question can reach · 0 exportable · 254 older values kept
- **Span:** 2024-02-14 → 2026-10-18 · **series:** 30 · **cadence:** daily
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-10-18)
- **Terms:** NONE · partners: withheld (no-redistribution); the figure is cited with its source · terms: none found
- **Credit:** Telegram channel @MOHMediaGaza
- **Ask:** MCP `databank(category="conflict", indicator="gaza.moh.deaths.cumulative")` · REST `/v2/databank/conflict?indicator=gaza.moh.deaths.cumulative`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `gaza.moh.aid_seekers.deaths.cumulative` | Aid seekers killed in Gaza who reached hospital, running total (Gaza Ministry of Health) · شهداء لقمة العيش ممن وصلوا مستشفيات قطاع غزة، الإجمالي التراكمي (وزارة الصحة في غزة) | count | 92 | 2025-06-02 | 2025-10-10 | 1 |
| `gaza.moh.aid_seekers.deaths.daily` | Aid seekers killed in Gaza and brought to hospital, 24-hour bulletin (Gaza Ministry of Health) · شهداء المساعدات الواصلون إلى مستشفيات قطاع غزة، تقرير 24 ساعة (وزارة الصحة في غزة) | count | 59 | 2025-06-16 | 2025-10-04 | 1 |
| `gaza.moh.aid_seekers.injuries.cumulative` | Aid seekers injured in Gaza who reached hospital, running total (Gaza Ministry of Health) · إصابات منتظري المساعدات ممن وصلوا مستشفيات قطاع غزة، الإجمالي التراكمي (وزارة الصحة في غزة) | count | 114 | 2025-06-07 | 2025-10-10 | 1 |
| `gaza.moh.aid_seekers.injuries.daily` | Aid seekers injured in Gaza and brought to hospital, 24-hour bulletin (Gaza Ministry of Health) · إصابات منتظري المساعدات الواصلة إلى مستشفيات قطاع غزة، تقرير 24 ساعة (وزارة الصحة في غزة) | count | 59 | 2025-06-16 | 2025-10-04 | 1 |
| `gaza.moh.deaths.cumulative` | Killed in Gaza, cumulative toll since 7 October 2023 (Gaza Ministry of Health) · الشهداء في قطاع غزة، الحصيلة التراكمية منذ 7 أكتوبر 2023 (وزارة الصحة في غزة) | count | 826 | 2024-02-14 | 2026-10-18 | 1 |
| `gaza.moh.deaths.daily` | Killed in Gaza and brought to hospital, 24-hour bulletin (Gaza Ministry of Health) · الشهداء الواصلون إلى مستشفيات قطاع غزة، تقرير 24 ساعة (وزارة الصحة في غزة) | count | 707 | 2024-02-14 | 2026-10-18 | 1 |
| `gaza.moh.deaths.period` | Killed in Gaza and brought to hospital, bulletin of 48 hours or more (Gaza Ministry of Health) · الشهداء الواصلون إلى مستشفيات قطاع غزة، تقرير يغطي 48 ساعة أو أكثر (وزارة الصحة في غزة) | count | 88 | 2024-08-12 | 2026-10-17 | 1 |
| `gaza.moh.deaths.since_ceasefire` | Killed in Gaza since the 11 October 2025 ceasefire, running total (Gaza Ministry of Health) · الشهداء في قطاع غزة منذ وقف إطلاق النار في 11 أكتوبر 2025، تراكمي (وزارة الصحة في غزة) | count | 272 | 2025-10-16 | 2026-10-18 | 1 |
| `gaza.moh.deaths.since_resumption` | Killed in Gaza since 18 March 2025, running total (Gaza Ministry of Health) · الشهداء في قطاع غزة منذ 18 مارس 2025، تراكمي (وزارة الصحة في غزة) | count | 194 | 2025-03-22 | 2025-10-10 | 1 |
| `gaza.moh.deaths_committee.daily` | Deaths added by the judicial committee, 24-hour bulletin (Gaza Ministry of Health) · شهداء أضافتهم اللجنة القضائية إلى الحصيلة التراكمية، تقرير 24 ساعة (وزارة الصحة في غزة) | count | 14 | 2025-03-23 | 2026-02-07 | 1 |
| `gaza.moh.deaths_committee.period` | Deaths added by the judicial committee, bulletin of 48 hours or more (Gaza Ministry of Health) · شهداء أضافتهم اللجنة القضائية إلى الحصيلة التراكمية، تقرير يغطي 48 ساعة أو أكثر (وزارة الصحة في غزة) | count | 25 | 2025-01-11 | 2026-10-17 | 1 |
| `gaza.moh.deaths_new.daily` | Newly killed in Gaza, 24-hour bulletin (Gaza Ministry of Health) · الشهداء الجدد في قطاع غزة، تقرير 24 ساعة (وزارة الصحة في غزة) | count | 174 | 2025-01-27 | 2026-10-18 | 1 |
| `gaza.moh.deaths_new.period` | Newly killed in Gaza, bulletin of 48 hours or more (Gaza Ministry of Health) · الشهداء الجدد في قطاع غزة، تقرير يغطي 48 ساعة أو أكثر (وزارة الصحة في غزة) | count | 59 | 2025-01-26 | 2026-10-17 | 1 |
| `gaza.moh.deaths_succumbed.daily` | Died of earlier wounds in Gaza, 24-hour bulletin (Gaza Ministry of Health) · شهداء متأثرون بجراحهم في قطاع غزة، تقرير 24 ساعة (وزارة الصحة في غزة) | count | 58 | 2025-01-21 | 2026-10-14 | 1 |
| `gaza.moh.deaths_succumbed.period` | Died of earlier wounds in Gaza, bulletin of 48 hours or more (Gaza Ministry of Health) · شهداء متأثرون بجراحهم في قطاع غزة، تقرير يغطي 48 ساعة أو أكثر (وزارة الصحة في غزة) | count | 14 | 2025-01-26 | 2026-10-10 | 1 |
| `gaza.moh.famine.deaths.cumulative` | Deaths from famine and malnutrition in Gaza, running total (Gaza Ministry of Health) · وفيات المجاعة وسوء التغذية في قطاع غزة، الإجمالي التراكمي (وزارة الصحة في غزة) | count | 36 | 2025-07-27 | 2025-10-04 | 1 |
| `gaza.moh.famine.deaths.daily` | Deaths from famine and malnutrition in Gaza, 24-hour bulletin (Gaza Ministry of Health) · وفيات المجاعة وسوء التغذية في قطاع غزة، تقرير 24 ساعة (وزارة الصحة في غزة) | count | 8 | 2025-07-27 | 2025-08-08 | 1 |
| `gaza.moh.famine.deaths_children.cumulative` | Child deaths from famine and malnutrition in Gaza, running total (Gaza Ministry of Health) · وفيات الأطفال بسبب المجاعة وسوء التغذية في قطاع غزة، الإجمالي التراكمي (وزارة الصحة في غزة) | count | 36 | 2025-07-27 | 2025-10-04 | 1 |
| `gaza.moh.famine.deaths_children.daily` | Child deaths from famine and malnutrition in Gaza, 24-hour bulletin (Gaza Ministry of Health) · وفيات الأطفال بسبب المجاعة وسوء التغذية في قطاع غزة، تقرير 24 ساعة (وزارة الصحة في غزة) | count | 1 | 2025-08-05 | 2025-08-05 | 1 |
| `gaza.moh.injuries.cumulative` | Injured in Gaza, cumulative toll since 7 October 2023 (Gaza Ministry of Health) · الإصابات في قطاع غزة، الحصيلة التراكمية منذ 7 أكتوبر 2023 (وزارة الصحة في غزة) | count | 825 | 2024-02-14 | 2026-10-18 | 1 |
| `gaza.moh.injuries.daily` | Injured in Gaza and brought to hospital, 24-hour bulletin (Gaza Ministry of Health) · الإصابات الواصلة إلى مستشفيات قطاع غزة، تقرير 24 ساعة (وزارة الصحة في غزة) | count | 727 | 2024-02-14 | 2026-10-18 | 1 |
| `gaza.moh.injuries.period` | Injured in Gaza and brought to hospital, bulletin of 48 hours or more (Gaza Ministry of Health) · الإصابات الواصلة إلى مستشفيات قطاع غزة، تقرير يغطي 48 ساعة أو أكثر (وزارة الصحة في غزة) | count | 96 | 2024-08-12 | 2026-10-17 | 1 |
| `gaza.moh.injuries.since_ceasefire` | Injured in Gaza since the 11 October 2025 ceasefire, running total (Gaza Ministry of Health) · الإصابات في قطاع غزة منذ وقف إطلاق النار في 11 أكتوبر 2025، تراكمي (وزارة الصحة في غزة) | count | 272 | 2025-10-16 | 2026-10-18 | 1 |
| `gaza.moh.injuries.since_resumption` | Injured in Gaza since 18 March 2025, running total (Gaza Ministry of Health) · الإصابات في قطاع غزة منذ 18 مارس 2025، تراكمي (وزارة الصحة في غزة) | count | 194 | 2025-03-22 | 2025-10-10 | 1 |
| `gaza.moh.massacres.daily` | Massacres in Gaza, 24-hour bulletin (Gaza Ministry of Health) · المجازر في قطاع غزة، تقرير 24 ساعة (وزارة الصحة في غزة) | count | 287 | 2024-02-14 | 2025-01-18 | 1 |
| `gaza.moh.massacres.period` | Massacres in Gaza, bulletin of 48 hours or more (Gaza Ministry of Health) · المجازر في قطاع غزة، تقرير يغطي 48 ساعة أو أكثر (وزارة الصحة في غزة) | count | 16 | 2024-08-12 | 2025-01-11 | 1 |
| `gaza.moh.period.hours` | Hours covered by a Gaza Ministry of Health bulletin longer than one day (48, 72…) · عدد الساعات التي يغطيها تقرير وزارة الصحة في غزة حين يتجاوز 24 ساعة (48، 72…) | count | 94 | 2024-08-12 | 2026-10-17 | 1 |
| `gaza.moh.recovered.daily` | Bodies recovered in Gaza, 24-hour bulletin (Gaza Ministry of Health) · الشهداء المنتشَلون في قطاع غزة، تقرير 24 ساعة (وزارة الصحة في غزة) | count | 189 | 2025-01-23 | 2026-10-18 | 1 |
| `gaza.moh.recovered.period` | Bodies recovered in Gaza, bulletin of 48 hours or more (Gaza Ministry of Health) · الشهداء المنتشَلون في قطاع غزة، تقرير يغطي 48 ساعة أو أكثر (وزارة الصحة في غزة) | count | 42 | 2025-01-26 | 2026-10-03 | 1 |
| `gaza.moh.recovered.since_ceasefire` | Bodies recovered in Gaza since the 11 October 2025 ceasefire, running total (Gaza Ministry of Health) · الشهداء المنتشَلون في قطاع غزة منذ وقف إطلاق النار في 11 أكتوبر 2025، تراكمي (وزارة الصحة في غزة) | count | 268 | 2025-10-16 | 2026-10-18 | 1 |

## West Bank toll since 7 October 2023: killed, injured, children, settler attacks (OCHA via Tech for Palestine)

حصيلة الضفة منذ 7 تشرين الأول 2023: الشهداء والجرحى والأطفال واعتداءات المستوطنين (أوتشا عبر تك فور بالستاين)

- **Key:** `v1_conflict_t4p_westbank` · **publisher:** Tech4Palestine (`tech4palestine`)
- **Rows:** 2,319 held · 2,319 a question can reach · 2,319 exportable · 2 older values kept
- **Span:** 2023-10-07 → 2026-09-28 · **series:** 8 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-09-28)
- **Terms:** Unlicense · partners: yes (open) · terms: https://github.com/TechForPalestine/palestine-datasets/blob/main/LICENSE
- **Credit:** Data: Tech4Palestine (data.techforpalestine.org), public domain (Unlicense); credited by choice.
- **Read before use:** Tech for Palestine's relay of UN OCHA's West Bank figures, a running total. A day whose row says flash_source 'fill' is not a day the UN reported: T4P carried the count forward between UN updates (29 of the 291 days held).
- **Ask:** MCP `databank(category="conflict", indicator="conflict.westbank_cumulative_injured")` · REST `/v2/databank/conflict?indicator=conflict.westbank_cumulative_injured`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `conflict.westbank_cumulative_displaced_children` | Children displaced in the West Bank, cumulative since 7 October 2023 (OCHA via Tech for Palestine) · الأطفال المهجَّرون في الضفة الغربية، تراكمي منذ 7 أكتوبر 2023 (أوتشا عبر Tech for Palestine) | persons | 288 | 2023-10-10 | 2026-09-28 | 1 |
| `conflict.westbank_cumulative_displaced_households` | Households displaced in the West Bank, cumulative since 7 October 2023 (OCHA via Tech for Palestine) · الأسر المهجَّرة في الضفة الغربية، تراكمي منذ 7 أكتوبر 2023 (أوتشا عبر Tech for Palestine) | households | 288 | 2023-10-10 | 2026-09-28 | 1 |
| `conflict.westbank_cumulative_displaced_persons` | People displaced in the West Bank, cumulative since 7 October 2023 (OCHA via Tech for Palestine) · المهجَّرون في الضفة الغربية، تراكمي منذ 7 أكتوبر 2023 (أوتشا عبر Tech for Palestine) | persons | 288 | 2023-10-10 | 2026-09-28 | 1 |
| `conflict.westbank_cumulative_injured` | Injured in the West Bank, cumulative since 7 October 2023 (OCHA via Tech for Palestine) · الإصابات في الضفة الغربية، تراكمي منذ 7 أكتوبر 2023 (أوتشا عبر Tech for Palestine) | persons | 291 | 2023-10-07 | 2026-09-28 | 1 |
| `conflict.westbank_cumulative_injured_children` | Children injured in the West Bank, cumulative since 7 October 2023 (OCHA via Tech for Palestine) · الإصابات بين الأطفال في الضفة الغربية، تراكمي منذ 7 أكتوبر 2023 (أوتشا عبر Tech for Palestine) | persons | 291 | 2023-10-07 | 2026-09-28 | 1 |
| `conflict.westbank_cumulative_killed` | Killed in the West Bank, cumulative since 7 October 2023 (OCHA via Tech for Palestine) · الشهداء في الضفة الغربية، تراكمي منذ 7 أكتوبر 2023 (أوتشا عبر Tech for Palestine) | persons | 291 | 2023-10-07 | 2026-09-28 | 1 |
| `conflict.westbank_cumulative_killed_children` | Children killed in the West Bank, cumulative since 7 October 2023 (OCHA via Tech for Palestine) · الشهداء الأطفال في الضفة الغربية، تراكمي منذ 7 أكتوبر 2023 (أوتشا عبر Tech for Palestine) | persons | 291 | 2023-10-07 | 2026-09-28 | 1 |
| `conflict.westbank_cumulative_settler_attacks` | Settler attacks in the West Bank, cumulative since 7 October 2023 (OCHA via Tech for Palestine) · اعتداءات المستوطنين في الضفة الغربية، تراكمي منذ 7 أكتوبر 2023 (أوتشا عبر Tech for Palestine) | attacks | 291 | 2023-10-07 | 2026-09-28 | 1 |

## Gaza and West Bank cumulative tolls (Tech for Palestine, continued by the daily datasets)

الحصيلة التراكمية في غزة والضفة (تك فور بالستاين، تكملها المجموعات اليومية)

- **Key:** `v1_conflict_tech4palestine` · **publisher:** Tech4Palestine (`tech4palestine`)
- **Rows:** 2,076 held · 2,338 a question can reach · 2,338 exportable · 14 older values kept · 262 event records
- **Span:** 2023-10-07 → 2026-08-08 · **series:** 4 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** continued by a successor dataset (last information 2026-08-08)
- **Terms:** Unlicense · partners: yes (open) · terms: https://github.com/TechForPalestine/palestine-datasets/blob/main/LICENSE
- **Credit:** Data: Tech4Palestine (data.techforpalestine.org), public domain (Unlicense); credited by choice.
- **Read before use:** Tech for Palestine's relay of UN OCHA's West Bank figures, a running total. A day whose row says flash_source 'fill' is not a day the UN reported: T4P carried the count forward between UN updates (29 of the 291 days held).
- **Ask:** MCP `databank(category="conflict", indicator="conflict.gaza_cumulative_injured")` · REST `/v2/databank/conflict?indicator=conflict.gaza_cumulative_injured`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `conflict.gaza_cumulative_injured` | Injured in Gaza, cumulative since 7 October 2023 (Gaza Ministry of Health via Tech for Palestine) · الإصابات في قطاع غزة، تراكمي منذ 7 أكتوبر 2023 (وزارة الصحة في غزة عبر Tech for Palestine) | persons | 1,037 | 2023-10-07 | 2026-08-08 | 1 |
| `conflict.gaza_cumulative_killed` | Killed in Gaza, cumulative since 7 October 2023 (Gaza Ministry of Health via Tech for Palestine) · الشهداء في قطاع غزة، تراكمي منذ 7 أكتوبر 2023 (وزارة الصحة في غزة عبر Tech for Palestine) | persons | 1,037 | 2023-10-07 | 2026-08-08 | 1 |
| `conflict.westbank_cumulative_injured` | Injured in the West Bank, cumulative since 7 October 2023 (OCHA via Tech for Palestine) · الإصابات في الضفة الغربية، تراكمي منذ 7 أكتوبر 2023 (أوتشا عبر Tech for Palestine) | persons | 1 | 2026-08-08 | 2026-08-08 | 1 |
| `conflict.westbank_cumulative_killed` | Killed in the West Bank, cumulative since 7 October 2023 (OCHA via Tech for Palestine) · الشهداء في الضفة الغربية، تراكمي منذ 7 أكتوبر 2023 (أوتشا عبر Tech for Palestine) | persons | 1 | 2026-08-08 | 2026-08-08 | 1 |

## Depopulation of Palestinian localities, 1935 to 1967 (Palestine Open Maps, event table)

تهجير البلدات الفلسطينية، 1935 إلى 1967 (خرائط فلسطين المفتوحة، جدول الأحداث)

- **Key:** `v1_conflict_palopenmaps` · **publisher:** Palestine Open Maps (`palopenmaps`)
- **Rows:** 0 held · 589 a question can reach · 589 exportable · 0 older values kept · 1,163 event records
- **Span:** ? → ? · **series:** 0 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** not judged by the radar (the live tier's own rollup)
- **Terms:** ODbL-1.0 · partners: yes (share-alike) · terms: https://data.palopenmaps.org/copyright
- **Credit:** Locality data: Palestine Open Maps (palopenmaps.org) and contributors, ODbL 1.0 — derived databases must remain ODbL.
- **Ask:** its records are events: see [events](events.md)

## B'Tselem events (served from the event table)

أحداث بتسيلم (من جدول الأحداث)

- **Key:** `v1_conflict_btselem` · **publisher:** B'Tselem (`btselem`)
- **Rows:** 0 held · 0 a question can reach · 0 exportable · 0 older values kept · 6 event records
- **Span:** ? → ? · **series:** 0 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** not judged by the radar (the live tier's own rollup)
- **Terms:** LicenseRef-BTselem · partners: no-redistribution · terms: https://www.btselem.org/about_btselem/license_to_use
- **Credit:** Data: B'Tselem (btselem.org), licensed CC-BY-NC 4.0.
- **Ask:** its records are events: see [events](events.md)

## Good Shepherd Collective events (served from the event table)

أحداث مجموعة الراعي الصالح (من جدول الأحداث)

- **Key:** `v1_conflict_goodshepherd` · **publisher:** Good Shepherd Collective (`goodshepherd`)
- **Rows:** 0 held · 0 a question can reach · 0 exportable · 0 older values kept
- **Span:** ? → ? · **series:** 0 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** not judged by the radar (the live tier's own rollup)
- **Terms:** LicenseRef-Liberation-License · partners: no-redistribution · terms: none found
- **Credit:** Data: Good Shepherd Collective (goodshepherdcollective.org).
