# P1.5 — fuel signal survey

**Measured:** 2026-07-31 · sources: v1 corpus.db, alerts.db (read-only)

## Verdict

**MARGINAL** — ~18.6 fuel/station messages per day across all channels.

Gate in IMPLEMENTATION_PLAN P1.5: flag to Zaid if < ~20/day.

> **Measurement caveat.** corpus.db is a per-channel backfill, not a
> uniform time series — `a7walstreet` spans 0.8 days, `maannews` 142.
> Rates are therefore per-channel (hits / that channel's own span) and
> summed. The first run of this survey divided by the corpus-wide span
> and reported 0.1/day, understating the real rate ~150x.
> The dominant channel's window is under 24h, so the interval is wide;
> live measurement (needs P1.1) is required to confirm.

### Rate by channel (hits / channel's own observed span)

| channel | msgs | span (d) | fuel | fuel/day |
|:--|--:|--:|--:|--:|
| a7walstreet |  | 0.8 | 10 | **13.1** |
| ahwalaltreq |  | 5.7 | 13 | **2.3** |
| qudsn |  | 9.8 | 11 | **1.1** |
| alkofiyatv |  | 10.2 | 9 | **0.9** |
| safaps |  | 12.5 | 6 | **0.5** |
| palinfo |  | 7.8 | 3 | **0.4** |
| maannews |  | 142.5 | 25 | **0.2** |
| eyeonpalestine2 |  | 68.2 | 9 | **0.1** |
| alqastalps |  | 22.6 | 1 | **0.0** |
| road_jehad |  | 979.7 | 2 | **0.0** |

**Concentration risk:** the top channel carries 70% of the signal.

## Corpus (21k messages, 32 channels, 2023-10 → 2026-06)

- messages scanned: **21058**
- actionable fuel messages: **12**
- messages mentioning fuel/stations: **89**

### Vocabulary category hits (any message)

| category | messages |
|:--|--:|
| queue | 411 |
| empty | 369 |
| available | 285 |
| price | 119 |
| crisis | 108 |
| commodity | 89 |
| station | 22 |

### Actionable hits by channel

| channel | messages |
|:--|--:|
| safaps | 3 |
| a7walstreet | 2 |
| alkofiyatv | 2 |
| maannews | 2 |
| eyeonpalestine2 | 1 |
| palinfo | 1 |
| qudsn | 1 |

### By month

| month | actionable |
|:--|--:|
| 2026-04 | 3 |
| 2026-05 | 2 |
| 2026-06 | 7 |

## Live alert stream (13k classified security messages)

- alerts with raw_text: **13275**
- mentioning fuel/stations: **31**

These passed the *security* classifier, so this is a lower bound on
fuel chatter — the classifier has no fuel path and discards the rest.

| channel | fuel mentions |
|:--|--:|
| qudsn | 9 |
| a7walstreet | 5 |
| safaps | 5 |
| alkofiyatv | 5 |
| palinfo | 2 |
| aljazeera_ar | 2 |
| rt_arabic | 1 |
| alqastalps | 1 |
| ahwalaltreq | 1 |

## Sample actionable messages

- `a7walstreet` 2026-06-10 — مرحبا في حدا بعرف اذا متوفر سولار بطولكرم أو لاء
- `a7walstreet` 2026-06-10 — متوفر ⛽️ بنزين ⛽️ وسولار ⛽️ في عورتا 🥇🥇عند أحمد البسام المحروقات عورتا شارع العقبه فوق مدرسة بنات عورتا الثانوية ب 210 متر 0556639765
- `alkofiyatv` 2026-06-07 — عاجل | القناة 12 العبرية: بحسب التقديرات، بدأ المنفذون عملية إطلاق النار في محطة وقود بكوخاف يائير، ثم واصلوا إلى تسور يتسحاق وتسور ناتان، قبل أن يصلوا لاحقا إل
- `alkofiyatv` 2026-06-04 — متابعة | وزارة الصحة: - نحذر من تسارع تفاقم أزمة الأدوية والمخزون الدوائي والمخبري والمستهلكات الطبية، ونؤكد أن أكثر من ثلث الأصناف الدوائية الموجودة في قائمة ا
- `eyeonpalestine2` 2026-04-24 — “White Privilege and the Victimhood Narrative!” Global artist Julian Casablancas boldly calls out American Zionists, describing the situation as “brainwashing” 
- `maannews` 2026-04-12 — وكالة معا | طائرة تزويد بالوقود من طراز KC-135 Stratotanker تابعة لسلاح الجو الأمريكي، والتي تضررت على ما يبدو في السعودية، وصلت إلى بريطانيا. آثار الأضرار تبدو
- `maannews` 2026-04-08 — وكالة معا | أفيغدور ليبرمان : إسرائيل حققت 3 أهداف خلال هذه الحرب - نهب الخزينة العامة، ورفع أسعار المواد الغذائية والوقود، وتحويل مليارات الشواقل إلى المتهربين
- `palinfo` 2026-06-07 — الإعلام العبري: بحسب التقديرات، بدأ المنفذون عملية إطلاق النار في محطة وقود بـ"كوخاف يائير"، ثم واصلوا إلى "تسور يتسحاق" و"تسور ناتان"، قبل أن يصلوا لاحقا إلى "
- `qudsn` 2026-06-04 — وزارة الصحة: - نحذر من تسارع تفاقم أزمة الأدوية والمخزون الدوائي والمخبري والمستهلكات الطبية، ونؤكد أن أكثر من ثلث الأصناف الدوائية الموجودة في قائمة الأدوية ال
- `safaps` 2026-06-02 — 🔴 متابعة صفا| الناطق العسكري باسم كتائب الشهيد عز الدين القسام أبو عبيدة: ▪️ عدونا الجبان يتوهم إضعافنا باغتيال قادتنا لكن دماءهم هي الوقود الذي يحرك سفينتنا لت
- `safaps` 2026-05-31 — 🔴 متابعة صفا| الدفاع المدني في غزة: ▪️ ارتفعت نسبة حوادث الحرائق خلال الفترة الأخيرة سواء الناتجة عن اهمال المواطنين لاجراءات السلامة والوقاية، أو الناتجة عن ال
- `safaps` 2026-05-31 — 🔴 متابعة صفا| فصائل المقاومة الفلسطينية: ▪️ يواصل العدو الصهيوني حربه المسعورة على قطاع غزة عبر القتل والاغتيالات والمجازر والمذابح واستهداف رجال الشرطة الفلسطي
