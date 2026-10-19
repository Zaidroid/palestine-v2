# Funding · التمويل

Measured on the store at 2026-10-18 20:41 UTC by `ops/databank_index.py`. [Back to the index](README.md)

## Humanitarian funding flows: paid, committed, pledged (OCHA Financial Tracking Service)

تدفقات التمويل الإنساني: المدفوع والملتزم به والمتعهّد به (خدمة التتبع المالي، أوتشا)

- **Key:** `v1_funding_unfts` · **publisher:** UN OCHA Financial Tracking Service (`unfts`)
- **Rows:** 10,465 held · 10,465 a question can reach · 10,465 exportable · 842 older values kept
- **Span:** 2013-05-27 → 2026-10-17 · **series:** 4 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-10-17)
- **Terms:** CC-BY-IGO-3.0 · partners: yes (attribution) · terms: https://data.humdata.org/dataset/pse-requirements-and-funding-data
- **Credit:** Funding flows: UN OCHA Financial Tracking Service (fts.unocha.org), licensed CC-BY-IGO-3.0.
- **Read before use:** A contribution that UN OCHA's Financial Tracking Service parked on a parent flow and has since allocated in full. The row shows the whole contribution, and the same money is already counted in its child flows under paid, commitment or pledge: never add this series to those. Some child flows are outside this databank (another country, no country, or a usage year not reached yet); child_flows_fetched beside child_flow_count says how many are here.
- **Ask:** MCP `databank(category="funding", indicator="funding.paid")` · REST `/v2/databank/funding?indicator=funding.paid`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `funding.commitment` | Humanitarian funding, commitment, US$ per flow (OCHA Financial Tracking Service) · التمويل الإنساني، التزام، بالدولار الأمريكي لكل تحويل (خدمة التتبّع المالي، أوتشا) | USD | 2,541 | 2013-05-27 | 2026-10-13 | 0 |
| `funding.paid` | Humanitarian funding, paid contribution, US$ per flow (OCHA Financial Tracking Service) · التمويل الإنساني، مساهمة مدفوعة، بالدولار الأمريكي لكل تحويل (خدمة التتبّع المالي، أوتشا) | USD | 7,333 | 2014-03-31 | 2026-10-17 | 1 |
| `funding.parked_parent` | Humanitarian funding, parent contribution already counted in its child flows, US$ per flow (OCHA Financial Tracking Service) · التمويل الإنساني، مساهمة أصلية محسوبة في تحويلاتها الفرعية، بالدولار الأمريكي لكل تحويل (خدمة التتبّع المالي، أوتشا) | USD | 554 | 2015-01-09 | 2026-10-15 | 0 |
| `funding.pledge` | Humanitarian funding, pledge, US$ per flow (OCHA Financial Tracking Service) · التمويل الإنساني، تعهّد، بالدولار الأمريكي لكل تحويل (خدمة التتبّع المالي، أوتشا) | USD | 37 | 2015-01-01 | 2026-08-06 | 0 |
