# Casualties · الضحايا

Measured on the store at 2026-10-14 18:11 UTC by `ops/databank_index.py`. [Back to the index](README.md)

## Palestinians killed, one row per person, 2000 to September 2023 (B'Tselem)

الشهداء، سجلّ لكل شخص، من 2000 إلى أيلول 2023 (بتسيلم)

- **Key:** `btselem_fatalities` · **publisher:** B'Tselem (`btselem`)
- **Rows:** 11,124 held · 11,124 a question can reach · 0 exportable · 0 older values kept
- **Span:** 2000-10-02 → 2023-09-24 · **series:** 1 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** waiting for the publisher's permission (last information 2023-09-24)
- **Terms:** LicenseRef-BTselem · partners: withheld (no-redistribution); the figure is cited with its source · terms: https://www.btselem.org/about_btselem/license_to_use
- **Credit:** Data: B'Tselem (btselem.org), licensed CC-BY-NC 4.0.
- **Ask:** MCP `databank(category="casualties", indicator="fatalities.person")` · REST `/v2/databank/casualties?indicator=fatalities.person`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `fatalities.person` | Person killed (B'Tselem fatalities database) · شخص قُتل (قاعدة بيانات بتسيلم) | persons | 11,124 | 2000-10-02 | 2023-09-24 | 17 |

## Palestinians killed by Israelis, by month, area, perpetrator, age and governorate (OCHA)

الفلسطينيون الذين قتلهم إسرائيليون، شهرياً حسب المنطقة والفاعل والعمر والمحافظة (أوتشا)

- **Key:** `ocha_fatalities_monthly` · **publisher:** UN OCHA oPt — Data on Casualties (`ocha_casualties`)
- **Rows:** 6,102 held · 6,102 a question can reach · 0 exportable · 0 older values kept
- **Span:** 2008-01-01 → 2026-10-01 · **series:** 27 · **cadence:** daily
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-10-01)
- **Terms:** UN-ToU-NC · partners: withheld (no-redistribution); the figure is cited with its source · terms: https://www.ochaopt.org/page/terms-use
- **Credit:** Palestinian fatalities: UN OCHA oPt, Protection of Civilians database.
- **Scope:** Counted by month from the casualty report's incident table (names never read). Gaza's dead since 7 October 2023 are not in OCHA's record.
- **Read before use:** OCHA oPt's verified record of Palestinians killed by Israelis (military forces, non-military security forces such as police, settlers, civilians), counted by the month of death from its incident table, January 2008 on. Gaza's dead since 7 October 2023 are NOT in it: OCHA records them only once verified, so its Gaza figures end in 2023 and a month after that is the West Bank and Israel only. A month with none recorded is 0; the newest month is partial.
- **Ask:** MCP `databank(category="casualties", indicator="ocha_monthly.killed")` · REST `/v2/databank/casualties?indicator=ocha_monthly.killed`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `ocha_monthly.killed` | Palestinians killed by Israelis in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 0 |
| `ocha_monthly.killed_armed_group_members` | Palestinians killed by Israelis whom OCHA records as members of armed groups, in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون وتسجّلهم أوتشا أعضاء في جماعات مسلحة، خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 0 |
| `ocha_monthly.killed_by_israeli_forces` | Palestinians killed by Israeli military forces in the month (OCHA) · الفلسطينيون الذين قتلتهم القوات العسكرية الإسرائيلية خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 0 |
| `ocha_monthly.killed_by_israeli_security` | Palestinians killed by Israeli non-military security forces (police, guards) in the month (OCHA) · الفلسطينيون الذين قتلتهم قوات أمن إسرائيلية غير عسكرية (شرطة، حراس) خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 0 |
| `ocha_monthly.killed_by_other_or_disputed` | Palestinians killed by Israeli civilians, or by a perpetrator OCHA records as disputed or unknown, in the month (OCHA) · الفلسطينيون الذين قتلهم مدنيون إسرائيليون، أو من تسجّل أوتشا هويته مختلفاً عليها أو مجهولة، خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 0 |
| `ocha_monthly.killed_by_settlers` | Palestinians killed by Israeli settlers in the month (OCHA) · الفلسطينيون الذين قتلهم مستوطنون إسرائيليون خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 0 |
| `ocha_monthly.killed_children` | Palestinian children killed by Israelis in the month (OCHA) · الأطفال الفلسطينيون الذين قتلهم إسرائيليون خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 0 |
| `ocha_monthly.killed_civilians` | Palestinians killed by Israelis whom OCHA records as civilians, in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون وتسجّلهم أوتشا مدنيين، خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 0 |
| `ocha_monthly.killed_gaza_strip` | Palestinians killed by Israelis in the Gaza Strip in the month, to 2023 (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في قطاع غزة خلال الشهر، حتى 2023 (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 0 |
| `ocha_monthly.killed_gov_bethlehem` | Palestinians killed by Israelis in Bethlehem governorate in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في محافظة بيت لحم خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 1 |
| `ocha_monthly.killed_gov_deir_al_balah` | Palestinians killed by Israelis in Deir Al-Balah governorate in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في محافظة دير البلح خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 1 |
| `ocha_monthly.killed_gov_gaza` | Palestinians killed by Israelis in Gaza governorate in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في محافظة غزة خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 1 |
| `ocha_monthly.killed_gov_hebron` | Palestinians killed by Israelis in Hebron governorate in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في محافظة الخليل خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 1 |
| `ocha_monthly.killed_gov_jenin` | Palestinians killed by Israelis in Jenin governorate in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في محافظة جنين خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 1 |
| `ocha_monthly.killed_gov_jericho` | Palestinians killed by Israelis in Jericho governorate in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في محافظة أريحا خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 1 |
| `ocha_monthly.killed_gov_jerusalem` | Palestinians killed by Israelis in Jerusalem governorate in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في محافظة القدس خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 1 |
| `ocha_monthly.killed_gov_khan_younis` | Palestinians killed by Israelis in Khan Younis governorate in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في محافظة خان يونس خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 1 |
| `ocha_monthly.killed_gov_nablus` | Palestinians killed by Israelis in Nablus governorate in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في محافظة نابلس خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 1 |
| `ocha_monthly.killed_gov_north_gaza` | Palestinians killed by Israelis in North Gaza governorate in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في محافظة شمال غزة خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 1 |
| `ocha_monthly.killed_gov_qalqilya` | Palestinians killed by Israelis in Qalqilya governorate in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في محافظة قلقيلية خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 1 |
| `ocha_monthly.killed_gov_rafah` | Palestinians killed by Israelis in Rafah governorate in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في محافظة رفح خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 1 |
| `ocha_monthly.killed_gov_ramallah` | Palestinians killed by Israelis in Ramallah governorate in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في محافظة رام الله خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 1 |
| `ocha_monthly.killed_gov_salfit` | Palestinians killed by Israelis in Salfit governorate in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في محافظة سلفيت خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 1 |
| `ocha_monthly.killed_gov_tubas` | Palestinians killed by Israelis in Tubas governorate in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في محافظة طوباس خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 1 |
| `ocha_monthly.killed_gov_tulkarm` | Palestinians killed by Israelis in Tulkarm governorate in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في محافظة طولكرم خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 1 |
| `ocha_monthly.killed_israel` | Palestinians killed by Israelis inside Israel in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون داخل إسرائيل خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 0 |
| `ocha_monthly.killed_west_bank` | Palestinians killed by Israelis in the West Bank, East Jerusalem included, in the month (OCHA) · الفلسطينيون الذين قتلهم إسرائيليون في الضفة الغربية بما فيها القدس الشرقية خلال الشهر (أوتشا) | persons | 226 | 2008-01-01 | 2026-10-01 | 0 |

## Palestinian casualties since 2008: yearly totals and splits (OCHA)

الضحايا الفلسطينيون منذ 2008: المجاميع السنوية وتفصيلها (أوتشا)

- **Key:** `v1_casualties_ocha_casualties` · **publisher:** UN OCHA oPt — Data on Casualties (`ocha_casualties`)
- **Rows:** 49 held · 49 a question can reach · 0 exportable · 59 older values kept
- **Span:** 2008-01-01 → 2026-01-01 · **series:** 31 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-10-14)
- **Terms:** UN-ToU-NC · partners: withheld (no-redistribution); the figure is cited with its source · terms: https://www.ochaopt.org/page/terms-use
- **Credit:** Palestinian fatalities: UN OCHA oPt, Protection of Civilians database.
- **Read before use:** Palestinian fatalities verified by UN OCHA since 2008. It EXCLUDES the Gaza war dead: those killed in Gaza and Israel in the hostilities since 7 October 2023 are added only once OCHA has verified them (the Gaza Ministry of Health toll is in the conflict category). The newest year is partial.
- **Read before use:** One total for 2008 to date, split by region, governorate, sex and age or weapon: not a year's figure. Verified by UN OCHA. It EXCLUDES the Gaza war dead: those killed in Gaza and Israel in the hostilities since 7 October 2023 are added only once OCHA has verified them (the Gaza Ministry of Health toll is in the conflict category).
- **Ask:** MCP `databank(category="casualties", indicator="casualties.annual_total")` · REST `/v2/databank/casualties?indicator=casualties.annual_total`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `casualties.annual_total` | Palestinian fatalities per year, verified by OCHA (since 2008) · الشهداء الفلسطينيون سنويًا بتوثيق أوتشا (منذ 2008) | fatalities | 19 | 2008-01-01 | 2026-01-01 | 0 |
| `casualties.demographic.boys` | Palestinian fatalities since 2008, OCHA-verified total, by sex and age: boys · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب الجنس والعمر: فتيان | fatalities | 1 | 2008-01-01 | 2008-01-01 | 0 |
| `casualties.demographic.girls` | Palestinian fatalities since 2008, OCHA-verified total, by sex and age: girls · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب الجنس والعمر: فتيات | fatalities | 1 | 2008-01-01 | 2008-01-01 | 0 |
| `casualties.demographic.men` | Palestinian fatalities since 2008, OCHA-verified total, by sex and age: men · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب الجنس والعمر: رجال | fatalities | 1 | 2008-01-01 | 2008-01-01 | 0 |
| `casualties.demographic.not_available` | Palestinian fatalities since 2008, OCHA-verified total, by sex and age: not available · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب الجنس والعمر: غير متوفر | fatalities | 1 | 2008-01-01 | 2008-01-01 | 0 |
| `casualties.demographic.women` | Palestinian fatalities since 2008, OCHA-verified total, by sex and age: women · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب الجنس والعمر: نساء | fatalities | 1 | 2008-01-01 | 2008-01-01 | 0 |
| `casualties.governorate.bethlehem` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: Bethlehem · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: بيت لحم | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.governorate.deir_al_balah` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: Deir al-Balah · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: دير البلح | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.governorate.gaza` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: Gaza · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: غزة | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.governorate.hebron` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: Hebron · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: الخليل | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.governorate.israel` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: in Israel · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: داخل إسرائيل | fatalities | 1 | 2008-01-01 | 2008-01-01 | 0 |
| `casualties.governorate.jenin` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: Jenin · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: جنين | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.governorate.jericho` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: Jericho · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: أريحا | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.governorate.jerusalem` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: Jerusalem · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: القدس | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.governorate.khan_younis` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: Khan Younis · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: خان يونس | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.governorate.nablus` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: Nablus · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: نابلس | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.governorate.north_gaza` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: North Gaza · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: شمال غزة | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.governorate.not_listed` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: not listed · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: غير مذكورة | fatalities | 1 | 2008-01-01 | 2008-01-01 | 0 |
| `casualties.governorate.qalqiliya` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: Qalqiliya · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: قلقيلية | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.governorate.rafah` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: Rafah · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: رفح | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.governorate.ramallah` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: Ramallah · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: رام الله | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.governorate.salfit` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: Salfit · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: سلفيت | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.governorate.tubas` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: Tubas · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: طوباس | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.governorate.tulkarm` | Palestinian fatalities since 2008, OCHA-verified total, by governorate: Tulkarm · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المحافظة: طولكرم | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.region.gaza_strip` | Palestinian fatalities since 2008, OCHA-verified total, by region: Gaza Strip · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المنطقة: قطاع غزة | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.region.israel` | Palestinian fatalities since 2008, OCHA-verified total, by region: in Israel · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المنطقة: داخل إسرائيل | fatalities | 1 | 2008-01-01 | 2008-01-01 | 0 |
| `casualties.region.not_listed` | Palestinian fatalities since 2008, OCHA-verified total, by region: not listed · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المنطقة: غير مذكورة | fatalities | 1 | 2008-01-01 | 2008-01-01 | 0 |
| `casualties.region.west_bank` | Palestinian fatalities since 2008, OCHA-verified total, by region: West Bank · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب المنطقة: الضفة الغربية | fatalities | 1 | 2008-01-01 | 2008-01-01 | 1 |
| `casualties.weapon.airstrikes_including_drones` | Palestinian fatalities since 2008, OCHA-verified total, by weapon: air strikes, including drones · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب السلاح: غارات جوية، ومنها الطائرات المسيّرة | fatalities | 1 | 2008-01-01 | 2008-01-01 | 0 |
| `casualties.weapon.live_ammunition` | Palestinian fatalities since 2008, OCHA-verified total, by weapon: live ammunition · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب السلاح: الذخيرة الحية | fatalities | 1 | 2008-01-01 | 2008-01-01 | 0 |
| `casualties.weapon.other` | Palestinian fatalities since 2008, OCHA-verified total, by weapon: other · الشهداء الفلسطينيون منذ 2008، مجموع ما وثّقه أوتشا، حسب السلاح: وسائل أخرى | fatalities | 1 | 2008-01-01 | 2008-01-01 | 0 |
