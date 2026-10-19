# Infrastructure · البنية التحتية

Measured on the store at 2026-10-18 20:41 UTC by `ops/databank_index.py`. [Back to the index](README.md)

## Night lights over each governorate by month, 2012 on (World Bank, Black Marble)

أضواء الليل فوق كل محافظة شهرياً من 2012 (البنك الدولي، بلاك ماربل)

- **Key:** `nightlights_monthly` · **publisher:** World Bank Space2Stats — Black Marble night lights (data catalog 0066940) (`worldbank_space2stats`)
- **Rows:** 5,376 held · 5,376 a question can reach · 5,376 exportable · 0 older values kept
- **Span:** 2012-01-01 → 2025-12-01 · **series:** 2 · **cadence:** irregular
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2025-12-01)
- **Terms:** CC-BY-4.0 · partners: yes (attribution) · terms: https://datacatalog.worldbank.org/search/dataset/0066940
- **Credit:** Night lights: World Bank Space2Stats, from NASA's Black Marble (VNP46A3).
- **Scope:** The sum and the mean of night-time radiance per governorate and month, 2012 onward, from yearly files the World Bank releases about February of the next year.
- **Read before use:** Night-time light seen from space over this governorate in the month: NASA's Black Marble (VNP46A3), summed or averaged per governorate by the World Bank (Space2Stats), in nanowatts per square centimetre per steradian. It measures light, not electricity or population: a blackout, a displaced population and a destroyed city all darken it, and clouds, snow and the moon are corrected by NASA, imperfectly (the share of good-quality pixels is on the row). The World Bank releases a year's file about the February after it.
- **Ask:** MCP `databank(category="infrastructure", indicator="nightlights.radiance_mean")` · REST `/v2/databank/infrastructure?indicator=nightlights.radiance_mean`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `nightlights.radiance_mean` | Mean night-time radiance per pixel over the governorate in the month, nW/cm²/sr (World Bank Space2Stats, NASA Black Marble) · متوسط الإشعاع الضوئي الليلي لكل بكسل فوق المحافظة خلال الشهر، نانوواط/سم²/ستيراديان (البنك الدولي، بلاك ماربل من ناسا) | nW/cm2/sr | 2,688 | 2012-01-01 | 2025-12-01 | 16 |
| `nightlights.radiance_sum` | Sum of night-time radiance over the governorate in the month, nW/cm²/sr (World Bank Space2Stats, NASA Black Marble) · مجموع الإشعاع الضوئي الليلي فوق المحافظة خلال الشهر، نانوواط/سم²/ستيراديان (البنك الدولي، بلاك ماربل من ناسا) | nW/cm2/sr | 2,688 | 2012-01-01 | 2025-12-01 | 16 |

## Buildings destroyed in Gaza: homes, schools, mosques, to October 2025 (Tech for Palestine)

المباني المدمّرة في غزة: المساكن والمدارس والمساجد، حتى تشرين الأول 2025 (تك فور بالستاين)

- **Key:** `v1_infrastructure_tech4palestine` · **publisher:** Tech4Palestine (`tech4palestine`)
- **Rows:** 2,920 held · 2,920 a question can reach · 2,920 exportable · 2,920 older values kept
- **Span:** 2023-10-07 → 2025-10-05 · **series:** 4 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** ended by its publisher (last information 2025-10-05)
- **Terms:** Unlicense · partners: yes (open) · terms: https://github.com/TechForPalestine/palestine-datasets/blob/main/LICENSE
- **Credit:** Data: Tech4Palestine (data.techforpalestine.org), public domain (Unlicense); credited by choice.
- **Ask:** MCP `databank(category="infrastructure", indicator="infrastructure.damage.educational")` · REST `/v2/databank/infrastructure?indicator=infrastructure.damage.educational`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `infrastructure.damage.educational` | Educational buildings destroyed in Gaza, cumulative since 7 October 2023 (Tech for Palestine) · المباني التعليمية المدمَّرة في قطاع غزة، تراكمي منذ 7 أكتوبر 2023 (Tech for Palestine) | buildings | 730 | 2023-10-07 | 2025-10-05 | 1 |
| `infrastructure.damage.religious` | Mosques destroyed in Gaza, cumulative since 7 October 2023 (Tech for Palestine) · المساجد المدمَّرة في قطاع غزة، تراكمي منذ 7 أكتوبر 2023 (Tech for Palestine) | buildings | 730 | 2023-10-07 | 2025-10-05 | 1 |
| `infrastructure.damage.residential` | Housing units destroyed in Gaza, cumulative since 7 October 2023 (Tech for Palestine) · الوحدات السكنية المدمَّرة في قطاع غزة، تراكمي منذ 7 أكتوبر 2023 (Tech for Palestine) | units | 730 | 2023-10-07 | 2025-10-05 | 1 |
| `infrastructure.damage.unknown` |  | units | 730 | 2023-10-07 | 2025-10-05 | 1 |

## Mandate-era village boundaries and the Separation Barrier's segments (HDX)

حدود القرى أيام الانتداب ومقاطع جدار الفصل (HDX)

- **Key:** `v1_infrastructure_hdx` · **publisher:** Humanitarian Data Exchange (`hdx`)
- **Rows:** 603 held · 603 a question can reach · 603 exportable · 1,547 older values kept
- **Span:** 2026-08-07 → 2026-08-07 · **series:** 2 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-10-18)
- **Terms:** CC-BY-IGO-3.0 · partners: yes (attribution) · terms: https://data.humdata.org/dataset/occupied-palestinian-territory-closures-barriers
- **Credit:** Closures and barriers: OCHA occupied Palestinian territory via HDX, CC-BY-IGO 3.0.
- **Read before use:** The 261 segments of the West Bank Separation Barrier as OCHA mapped it in January 2018, each with its length: 464 km constructed, 51 km under construction and 196 km projected, so the total includes what was only planned. A 2018 map, not today's. The same segments are also held as land.checkpoint; the two are never added.
- **Read before use:** One row per village boundary polygon as drawn under the British Mandate (342 of them, from the Palestinian Authority's Ministry of Planning, published by OCHA): a historical map layer, not a count of people and not today's localities. Some of the villages lie outside the West Bank.
- **Ask:** MCP `databank(category="infrastructure", indicator="infrastructure.locality_record")` · REST `/v2/databank/infrastructure?indicator=infrastructure.locality_record`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `infrastructure.barrier_segment` | West Bank Separation Barrier segments, length in km (OCHA, January 2018) · مقاطع جدار الفصل في الضفة الغربية، الطول بالكيلومتر (أوتشا، كانون الثاني 2018) | km | 261 | 2026-08-07 | 2026-08-07 | 1 |
| `infrastructure.locality_record` | Village boundaries as drawn under the British Mandate (PA Ministry of Planning via OCHA) · حدود القرى كما رُسمت في عهد الانتداب البريطاني (وزارة التخطيط الفلسطينية عبر أوتشا) | localities | 342 | 2026-08-07 | 2026-08-07 | 12 |

## Structures damaged in Gaza by satellite assessment (UNOSAT)

المنشآت المتضررة في غزة بتقييم الأقمار الصناعية (يونوسات)

- **Key:** `v1_infrastructure_unosat` · **publisher:** UNOSAT (UNITAR) (`unosat`)
- **Rows:** 14 held · 14 a question can reach · 14 exportable · 0 older values kept
- **Span:** 2023-10-10 → 2025-10-11 · **series:** 1 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2025-10-11)
- **Terms:** CC-BY-SA · partners: yes (share-alike) · terms: https://data.humdata.org/dataset/unosat-gaza-governorate-damage-assessment-gaza-strip
- **Credit:** Satellite damage assessments: UNOSAT (UNITAR) via HDX (CC-BY-SA).
- **Read before use:** UNOSAT's satellite damage assessments, as its datasets on HDX give them. Three of the fourteen (10 and 15 October 2023, 22 September 2025) cover Gaza governorate only and the rest the whole Strip (attrs.assessment_scope says which), so the series is not one line: 41,221 on 22 September 2025 sits between 192,812 and 198,273. UNOSAT's assessment of 16 June 2026 is not on HDX; it is held in the cited figures.
- **Ask:** MCP `databank(category="infrastructure", indicator="infrastructure.satellite_damage_assessment")` · REST `/v2/databank/infrastructure?indicator=infrastructure.satellite_damage_assessment`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `infrastructure.satellite_damage_assessment` | Structures affected in Gaza per UNOSAT satellite assessment · المباني المتضررة في غزة حسب تقييمات يونوسات بالأقمار الصناعية | structures | 14 | 2023-10-10 | 2025-10-11 | 1 |
