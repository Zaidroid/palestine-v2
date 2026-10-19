# Prisoners · الأسرى

Measured on the store at 2026-10-18 20:41 UTC by `ops/databank_index.py`. [Back to the index](README.md)

## Palestinians held by Israel by month, 2011 on: children, women, administrative detention and more (Addameer)

الأسرى لدى إسرائيل شهرياً من 2011: الأطفال والنساء والإداريون وغيرهم (الضمير)

- **Key:** `v1_prisoners_addameer` · **publisher:** Addameer Prisoner Support and Human Rights Association (addameer.ps) (`addameer`)
- **Rows:** 1,681 held · 1,681 a question can reach · 0 exportable · 35 older values kept
- **Span:** 2011-01-01 → 2026-10-01 · **series:** 13 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-10-01)
- **Terms:** no-license-found · partners: withheld (no-redistribution); the figure is cited with its source · terms: none found
- **Credit:** Data: Addameer Prisoner Support and Human Rights Association (addameer.ps).
- **Read before use:** Addameer's running count of arrests by Israeli forces in the West Bank, Jerusalem included, since 7 October 2023, as its monthly statistics page gives it on the month's date. It counts arrests, not people: a person arrested twice counts twice. Addameer rounds it (to the hundred or the thousand). Gaza's detainees are counted apart (the unlawful combatants).
- **Read before use:** Addameer's running count of Palestinian prisoners who died in Israeli custody since 1967, those who died after 7 October 2023 included, as its monthly page gives it. Two months carry the figure (April 2025 and August 2026).
- **Ask:** MCP `databank(category="prisoners", indicator="prisoners.administrative")` · REST `/v2/databank/prisoners?indicator=prisoners.administrative`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `prisoners.administrative` | Palestinian administrative detainees held by Israel (HaMoked; Addameer) · المعتقلون الإداريون الفلسطينيون في سجون الاحتلال (هموكيد؛ الضمير) | persons | 170 | 2011-01-01 | 2026-10-01 | 0 |
| `prisoners.arrests_since_7_october_2023` | Arrests in the West Bank, Jerusalem included, since 7 October 2023, a running count (Addameer) · حالات الاعتقال في الضفة الغربية بما فيها القدس منذ 7 تشرين الأول 2023، عدد تراكمي (الضمير) | arrests | 9 | 2024-08-01 | 2026-10-01 | 0 |
| `prisoners.child` | Palestinian child prisoners held by Israel (Addameer) · الأسرى الأطفال الفلسطينيون في سجون الاحتلال (الضمير) | persons | 170 | 2011-01-01 | 2026-10-01 | 0 |
| `prisoners.deaths_in_custody_since_1967` | Palestinian prisoners who died in Israeli custody since 1967, a running count (Addameer) · الأسرى الفلسطينيون الذين استشهدوا في سجون الاحتلال منذ عام 1967، عدد تراكمي (الضمير) | persons | 2 | 2025-04-01 | 2026-08-01 | 0 |
| `prisoners.female` | Palestinian women prisoners held by Israel (Addameer) · الأسيرات الفلسطينيات في سجون الاحتلال (الضمير) | persons | 170 | 2011-01-01 | 2026-10-01 | 0 |
| `prisoners.from_1948` | Palestinian prisoners from the 1948 territories held by Israel (Addameer) · أسرى الأراضي المحتلة عام 1948 في سجون الاحتلال (الضمير) | persons | 168 | 2011-01-01 | 2026-10-01 | 0 |
| `prisoners.gaza` | Palestinian prisoners from the Gaza Strip held by Israel; from November 2024 those held as 'unlawful combatants' are counted apart (Addameer) · الأسرى من قطاع غزة في سجون الاحتلال، ومنذ تشرين الثاني 2024 يُعدّ المحتجزون بصفة «مقاتل غير شرعي» على حدة (الضمير) | persons | 154 | 2011-01-01 | 2026-10-01 | 0 |
| `prisoners.jerusalem` | Palestinian prisoners from Jerusalem held by Israel (Addameer) · الأسرى المقدسيون في سجون الاحتلال (الضمير) | persons | 168 | 2011-01-01 | 2026-10-01 | 0 |
| `prisoners.legislative_council` | Members of the Palestinian Legislative Council held by Israel (Addameer) · نواب المجلس التشريعي الفلسطيني الأسرى في سجون الاحتلال (الضمير) | persons | 168 | 2011-01-01 | 2026-10-01 | 0 |
| `prisoners.life_sentence` | Palestinian prisoners serving life sentences in Israeli prisons (Addameer) · الأسرى المحكومون بالسجن المؤبد في سجون الاحتلال (الضمير) | persons | 168 | 2011-01-01 | 2026-10-01 | 0 |
| `prisoners.pre_oslo` | Palestinian prisoners held since before the Oslo Accords of 1993 (Addameer) · الأسرى القدامى المعتقلون منذ ما قبل اتفاق أوسلو عام 1993 (الضمير) | persons | 148 | 2012-08-01 | 2026-10-01 | 0 |
| `prisoners.total` | Palestinians held in Israeli prisons, total (HaMoked; Addameer) · إجمالي الأسرى والمعتقلين الفلسطينيين في سجون الاحتلال (هموكيد؛ الضمير) | persons | 170 | 2011-01-01 | 2026-10-01 | 0 |
| `prisoners.unlawful_combatants` | Palestinians held by Israel under the 'unlawful combatants' law, mostly from Gaza (HaMoked; Addameer) · الفلسطينيون المحتجزون بموجب قانون «المقاتل غير الشرعي»، وأغلبهم من قطاع غزة (هموكيد؛ الضمير) | persons | 16 | 2024-11-01 | 2026-10-01 | 0 |

## Palestinians held by Israel by month and status, 2008 on (HaMoked)

الأسرى لدى إسرائيل شهرياً حسب الوضع، من 2008 (هموكيد)

- **Key:** `v1_prisoners_hamoked` · **publisher:** HaMoked (`hamoked`)
- **Rows:** 1,100 held · 1,100 a question can reach · 0 exportable · 0 older values kept
- **Span:** 2008-05-01 → 2026-10-01 · **series:** 5 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-10-01)
- **Terms:** no-license-found · partners: withheld (no-redistribution); the figure is cited with its source · terms: none found
- **Credit:** Detention figures: HaMoked, sourced from IPS.
- **Ask:** MCP `databank(category="prisoners", indicator="prisoners.administrative")` · REST `/v2/databank/prisoners?indicator=prisoners.administrative`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `prisoners.administrative` | Palestinian administrative detainees held by Israel (HaMoked; Addameer) · المعتقلون الإداريون الفلسطينيون في سجون الاحتلال (هموكيد؛ الضمير) | persons | 220 | 2008-05-01 | 2026-10-01 | 0 |
| `prisoners.remand` | Palestinian remand detainees held by Israel (HaMoked) · الموقوفون الفلسطينيون في سجون الاحتلال (هموكيد) | persons | 220 | 2008-05-01 | 2026-10-01 | 0 |
| `prisoners.sentenced` | Sentenced Palestinian prisoners held by Israel (HaMoked) · الأسرى الفلسطينيون المحكومون في سجون الاحتلال (هموكيد) | persons | 220 | 2008-05-01 | 2026-10-01 | 0 |
| `prisoners.total` | Palestinians held in Israeli prisons, total (HaMoked; Addameer) · إجمالي الأسرى والمعتقلين الفلسطينيين في سجون الاحتلال (هموكيد؛ الضمير) | persons | 220 | 2008-05-01 | 2026-10-01 | 0 |
| `prisoners.unlawful_combatants` | Palestinians held by Israel under the 'unlawful combatants' law, mostly from Gaza (HaMoked; Addameer) · الفلسطينيون المحتجزون بموجب قانون «المقاتل غير الشرعي»، وأغلبهم من قطاع غزة (هموكيد؛ الضمير) | persons | 220 | 2008-05-01 | 2026-10-01 | 0 |

## Arrests and administrative orders by month, 2016 to January 2024 (the prisoner institutions' joint report)

الاعتقالات وأوامر الاعتقال الإداري شهرياً، 2016 إلى كانون الثاني 2024 (التقرير المشترك لمؤسسات الأسرى)

- **Key:** `arrests_joint_monthly` · **publisher:** Addameer Prisoner Support and Human Rights Association (addameer.ps) (`addameer`)
- **Rows:** 272 held · 272 a question can reach · 0 exportable · 0 older values kept
- **Span:** 2016-01-01 → 2024-01-01 · **series:** 13 · **cadence:** irregular
- **Freshness:** closed collection: complete, nothing more will come (last information 2024-01-01)
- **Terms:** no-license-found · partners: withheld (no-redistribution); the figure is cited with its source · terms: none found
- **Credit:** Data: Addameer Prisoner Support and Human Rights Association (addameer.ps).
- **Scope:** The joint monthly report's lead sentence: arrests, children, women, Jerusalem, administrative orders (new, renewed), January 2016 to January 2024 as Addameer indexes it; West Bank only from October 2023. Year, half-year and two-month reports are not read as months.
- **Read before use:** The Palestinian prisoner institutions' joint monthly report (the Commission of Detainees' Affairs, the Prisoners' Society, Addameer; some years Al Mezan and the Wadi Hilweh centre), as Addameer indexes it: the arrests Israeli forces made in the month, from the report's lead sentence. It counts arrest cases, not people: a person arrested twice counts twice. Months the index does not hold as a month's report are missing, not zero (the year, half-year and two-month reports are not read as months). Where a report's title prints a different figure from its text, the text's is held and the title's sits beside it (title_says).
- **Read before use:** The Palestinian prisoner institutions' joint monthly report (the Commission of Detainees' Affairs, the Prisoners' Society, Addameer; some years Al Mezan and the Wadi Hilweh centre), as Addameer indexes it: the arrests Israeli forces made in the month, from the report's lead sentence. It counts arrest cases, not people: a person arrested twice counts twice. Months the index does not hold as a month's report are missing, not zero (the year, half-year and two-month reports are not read as months). Where a report's title prints a different figure from its text, the text's is held and the title's sits beside it (title_says). From October 2023 the reports count the West Bank, Jerusalem included, only: these months are a series of their own.
- **Ask:** MCP `databank(category="prisoners", indicator="arrests_joint.total")` · REST `/v2/databank/prisoners?indicator=arrests_joint.total`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `arrests_joint.admin_orders` | Administrative detention orders issued by Israel in the month (the occupied territory) (prisoner institutions' joint report) · أوامر الاعتقال الإداري التي أصدرها الاحتلال خلال الشهر (الأرض المحتلة) (التقرير المشترك لمؤسسات الأسرى) | count | 43 | 2016-01-01 | 2022-03-01 | 0 |
| `arrests_joint.admin_orders_new` | New administrative detention orders issued in the month (the occupied territory) (prisoner institutions' joint report) · أوامر الاعتقال الإداري الجديدة خلال الشهر (الأرض المحتلة) (التقرير المشترك لمؤسسات الأسرى) | count | 32 | 2016-01-01 | 2021-04-01 | 0 |
| `arrests_joint.admin_orders_new_west_bank` | New administrative detention orders issued in the month (the West Bank, Jerusalem included) (prisoner institutions' joint report) · أوامر الاعتقال الإداري الجديدة خلال الشهر (الضفة الغربية بما فيها القدس) (التقرير المشترك لمؤسسات الأسرى) | count | 1 | 2024-01-01 | 2024-01-01 | 1 |
| `arrests_joint.admin_orders_renewed` | Administrative detention orders renewed in the month (the occupied territory) (prisoner institutions' joint report) · أوامر الاعتقال الإداري المجدّدة خلال الشهر (الأرض المحتلة) (التقرير المشترك لمؤسسات الأسرى) | count | 8 | 2020-01-01 | 2021-04-01 | 0 |
| `arrests_joint.admin_orders_renewed_west_bank` | Administrative detention orders renewed in the month (the West Bank, Jerusalem included) (prisoner institutions' joint report) · أوامر الاعتقال الإداري المجدّدة خلال الشهر (الضفة الغربية بما فيها القدس) (التقرير المشترك لمؤسسات الأسرى) | count | 1 | 2024-01-01 | 2024-01-01 | 1 |
| `arrests_joint.admin_orders_west_bank` | Administrative detention orders issued by Israel in the month (the West Bank, Jerusalem included) (prisoner institutions' joint report) · أوامر الاعتقال الإداري التي أصدرها الاحتلال خلال الشهر (الضفة الغربية بما فيها القدس) (التقرير المشترك لمؤسسات الأسرى) | count | 1 | 2024-01-01 | 2024-01-01 | 1 |
| `arrests_joint.children` | Arrests of children by Israeli forces in the month (the occupied territory) (prisoner institutions' joint report) · حالات اعتقال الأطفال خلال الشهر (الأرض المحتلة) (التقرير المشترك لمؤسسات الأسرى) | arrests | 56 | 2016-01-01 | 2022-11-01 | 0 |
| `arrests_joint.children_west_bank` | Arrests of children by Israeli forces in the month (the West Bank, Jerusalem included) (prisoner institutions' joint report) · حالات اعتقال الأطفال خلال الشهر (الضفة الغربية بما فيها القدس) (التقرير المشترك لمؤسسات الأسرى) | arrests | 1 | 2024-01-01 | 2024-01-01 | 1 |
| `arrests_joint.jerusalem` | Arrests by Israeli forces in Jerusalem in the month (the occupied territory) (prisoner institutions' joint report) · حالات الاعتقال في القدس خلال الشهر (الأرض المحتلة) (التقرير المشترك لمؤسسات الأسرى) | arrests | 34 | 2016-07-01 | 2020-11-01 | 0 |
| `arrests_joint.total` | Arrests by Israeli forces in the month (the occupied territory) (prisoner institutions' joint report) · حالات الاعتقال التي نفّذتها قوات الاحتلال خلال الشهر (الأرض المحتلة) (التقرير المشترك لمؤسسات الأسرى) | arrests | 59 | 2016-01-01 | 2022-11-01 | 0 |
| `arrests_joint.total_west_bank` | Arrests by Israeli forces in the month (the West Bank, Jerusalem included) (prisoner institutions' joint report) · حالات الاعتقال التي نفّذتها قوات الاحتلال خلال الشهر (الضفة الغربية بما فيها القدس) (التقرير المشترك لمؤسسات الأسرى) | arrests | 1 | 2024-01-01 | 2024-01-01 | 1 |
| `arrests_joint.women` | Arrests of women by Israeli forces in the month (the occupied territory) (prisoner institutions' joint report) · حالات اعتقال النساء خلال الشهر (الأرض المحتلة) (التقرير المشترك لمؤسسات الأسرى) | arrests | 34 | 2016-07-01 | 2022-11-01 | 0 |
| `arrests_joint.women_west_bank` | Arrests of women by Israeli forces in the month (the West Bank, Jerusalem included) (prisoner institutions' joint report) · حالات اعتقال النساء خلال الشهر (الضفة الغربية بما فيها القدس) (التقرير المشترك لمؤسسات الأسرى) | arrests | 1 | 2024-01-01 | 2024-01-01 | 1 |
