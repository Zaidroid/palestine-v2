# PCBS (Palestinian Central Bureau of Statistics) · الجهاز المركزي للإحصاء الفلسطيني

Measured on the store at 2026-10-18 20:41 UTC by `ops/databank_index.py`. [Back to the index](README.md)

## Consumer price index, population and poverty, from PCBS itself

الرقم القياسي لأسعار المستهلك والسكان والفقر، من الإحصاء الفلسطيني نفسه

- **Key:** `v1_economic_pcbs_direct` · **publisher:** Palestinian Central Bureau of Statistics (PCBS) (`pcbs_direct`)
- **Rows:** 152 held · 152 a question can reach · 152 exportable · 0 older values kept
- **Span:** 1996-01-01 → 2026-01-01 · **series:** 3 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-01-01)
- **Terms:** CC-BY-4.0 · partners: yes (attribution) · terms: https://www.pcbs.gov.ps/en/reference/terms-of-use
- **Credit:** Data: Palestinian Central Bureau of Statistics (pcbs.gov.ps), CC-BY-4.0.
- **Ask:** MCP `databank(category="pcbs", indicator="economic.pcbs_cpi")` · REST `/v2/databank/pcbs?indicator=economic.pcbs_cpi`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `economic.pcbs_cpi` | Consumer Price Index · الرقم القياسي لأسعار المستهلك | index | 120 | 1996-01-01 | 2025-01-01 | 3 |
| `economic.pcbs_population` | Population · عدد السكان | persons | 30 | 2017-01-01 | 2026-01-01 | 2 |
| `economic.pcbs_poverty_rate` | Poverty rate · نسبة الفقر | percent | 2 | 2017-01-01 | 2023-01-01 | 0 |
