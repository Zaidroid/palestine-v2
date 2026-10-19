# Land · الأرض

Measured on the store at 2026-10-18 20:41 UTC by `ops/databank_index.py`. [Back to the index](README.md)

## Structures demolished per day, West Bank and East Jerusalem (Good Shepherd Collective)

المنشآت المهدومة يومياً في الضفة والقدس الشرقية (مجموعة الراعي الصالح)

- **Key:** `v1_land_goodshepherd` · **publisher:** Good Shepherd Collective (`goodshepherd`)
- **Rows:** 279 held · 279 a question can reach · 0 exportable · 272 older values kept
- **Span:** 2025-06-30 → 2026-10-15 · **series:** 1 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-10-15)
- **Terms:** LicenseRef-Liberation-License · partners: withheld (no-redistribution); the figure is cited with its source · terms: none found
- **Credit:** Data: Good Shepherd Collective (goodshepherdcollective.org).
- **Read before use:** The Good Shepherd Collective's republication of UN OCHA's demolition record for the West Bank and East Jerusalem: the same demolitions as OCHA's own series in the demolitions category, so the two are never added. Days before 8 September 2025 were stored by the old system with a minimum of 1 structure and can no longer be checked.
- **Ask:** MCP `databank(category="land", indicator="land.demolition")` · REST `/v2/databank/land?indicator=land.demolition`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `land.demolition` | Structures demolished per day, West Bank and East Jerusalem (Good Shepherd Collective, from OCHA) · المباني المهدومة باليوم في الضفة الغربية والقدس الشرقية (غود شيبرد، عن أوتشا) | structures | 279 | 2025-06-30 | 2026-10-15 | 1 |

## Separation Barrier segments (OCHA, January 2018)

مقاطع جدار الفصل (أوتشا، كانون الثاني 2018)

- **Key:** `v1_land_ocha` · **publisher:** UN OCHA oPt (`ocha`)
- **Rows:** 261 held · 261 a question can reach · 261 exportable · 261 older values kept
- **Span:** 2026-10-12 → 2026-10-12 · **series:** 1 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-10-18)
- **Terms:** CC-BY-IGO-3.0 · partners: yes (attribution) · terms: https://data.humdata.org/dataset/state-of-palestine-humanitarian-access
- **Credit:** Data: UN OCHA oPt (ochaopt.org), licensed CC-BY 3.0 IGO.
- **Read before use:** These rows are the 261 segments of the West Bank Separation Barrier as OCHA mapped it in January 2018 (constructed, under construction or projected), not checkpoints: the series' key is a misnomer kept for compatibility. It is a 2018 map, not today's. The same segments are also held as infrastructure.barrier_segment, so the two are never added.
- **Ask:** MCP `databank(category="land", indicator="land.checkpoint")` · REST `/v2/databank/land?indicator=land.checkpoint`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `land.checkpoint` | West Bank Separation Barrier segments (OCHA, January 2018) · مقاطع جدار الفصل في الضفة الغربية (أوتشا، كانون الثاني 2018) | sites | 261 | 2026-10-12 | 2026-10-12 | 1 |

## Israeli settlement built-up areas in the West Bank (Peace Now via OCHA)

المناطق المبنية في المستوطنات الإسرائيلية في الضفة (السلام الآن عبر أوتشا)

- **Key:** `v1_land_peace_now` · **publisher:** Peace Now — Settlement Watch (`peace_now`)
- **Rows:** 199 held · 199 a question can reach · 0 exportable · 199 older values kept
- **Span:** 2026-10-12 → 2026-10-12 · **series:** 1 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-10-18)
- **Terms:** no-license-found · partners: withheld (no-redistribution); the figure is cited with its source · terms: none found
- **Credit:** Settlement data: Peace Now (Settlement Watch).
- **Read before use:** One row per settlement built-up area, with its name and its area in dunums, as Peace Now's data stood at the end of 2018 (published by OCHA). The file says nothing about a settlement's legal status or type, and it is not today's list.
- **Ask:** MCP `databank(category="land", indicator="land.settlement")` · REST `/v2/databank/land?indicator=land.settlement`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `land.settlement` | Israeli settlement built-up areas in the West Bank (Peace Now via OCHA, end of 2018) · المناطق المبنية للمستوطنات الإسرائيلية في الضفة الغربية (السلام الآن عبر أوتشا، نهاية 2018) | sites | 199 | 2026-10-12 | 2026-10-12 | 1 |
