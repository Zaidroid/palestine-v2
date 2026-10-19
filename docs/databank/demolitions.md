# Demolitions · عمليات الهدم

Measured on the store at 2026-10-18 20:41 UTC by `ops/databank_index.py`. [Back to the index](README.md)

## Demolitions in the West Bank: structures and people displaced, by year and locality (OCHA)

الهدم في الضفة: المنشآت والمهجّرون، سنوياً وحسب البلدة (أوتشا)

- **Key:** `v1_demolitions_ocha_demolitions` · **publisher:** UN OCHA oPt — Data on Demolitions (`ocha_demolitions`)
- **Rows:** 924 held · 924 a question can reach · 0 exportable · 2,691 older values kept
- **Span:** 2009-01-01 → 2026-01-01 · **series:** 5 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-10-17)
- **Terms:** UN-ToU-NC · partners: withheld (no-redistribution); the figure is cited with its source · terms: https://www.ochaopt.org/page/terms-use
- **Credit:** Demolitions: UN OCHA oPt.
- **Read before use:** One total per locality for 2009 to date, as OCHA publishes it: not a figure for one year. It counts the same demolitions as the yearly totals for the West Bank, so the two are never added.
- **Ask:** MCP `databank(category="demolitions", indicator="demolitions.locality.structures")` · REST `/v2/databank/demolitions?indicator=demolitions.locality.structures`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `demolitions.annual_total.affected` | People affected by demolitions in the West Bank per year (OCHA) · أشخاص تضرّروا من الهدم في الضفة الغربية سنويًا (أوتشا) | persons | 18 | 2009-01-01 | 2026-01-01 | 1 |
| `demolitions.annual_total.displaced` | People displaced by demolitions in the West Bank per year (OCHA) · أشخاص هُجّروا بسبب الهدم في الضفة الغربية سنويًا (أوتشا) | persons | 18 | 2009-01-01 | 2026-01-01 | 1 |
| `demolitions.annual_total.structures` | Structures demolished in the West Bank per year (OCHA) · مبانٍ هُدمت في الضفة الغربية سنويًا (أوتشا) | structures | 18 | 2009-01-01 | 2026-01-01 | 1 |
| `demolitions.locality.displaced` | People displaced by demolitions, by locality (OCHA) · أشخاص هُجّروا بسبب الهدم حسب التجمّع (أوتشا) | persons | 344 | 2009-01-01 | 2009-01-01 | 11 |
| `demolitions.locality.structures` | Structures demolished, by locality (OCHA) · مبانٍ هُدمت حسب التجمّع (أوتشا) | structures | 526 | 2009-01-01 | 2009-01-01 | 11 |
