# Education · التعليم

Measured on the store at 2026-10-18 20:41 UTC by `ops/databank_index.py`. [Back to the index](README.md)

## West Bank school register (Ministry of Education and UNICEF via OCHA)

سجل مدارس الضفة (وزارة التربية واليونيسف عبر أوتشا)

- **Key:** `v1_education_hdx` · **publisher:** Humanitarian Data Exchange (`hdx`)
- **Rows:** 2,359 held · 2,359 a question can reach · 2,359 exportable · 2,359 older values kept
- **Span:** 2026-08-05 → 2026-08-05 · **series:** 1 · **cadence:** as its publisher updates (ported from the first system)
- **Freshness:** fresh: read on its own rhythm and within its allowance (last information 2026-10-18)
- **Terms:** CC-BY-4.0 · partners: yes (attribution) · terms: https://data.humdata.org/dataset/state-of-palestine-west-bank-schools
- **Credit:** School register: OCHA occupied Palestinian territory (source UNICEF Jerusalem) via HDX, CC-BY.
- **Read before use:** One row per school in the West Bank as the register stood in June 2015 (the file was last replaced on HDX in June 2021): it says where a school is and what it is called, not whether it is open today, and it holds no school in the Gaza Strip.
- **Ask:** MCP `databank(category="education", indicator="education.school_record")` · REST `/v2/databank/education?indicator=education.school_record`

| Series | Name | Unit | Rows | From | To | Places |
|---|---|---|---:|---|---|---:|
| `education.school_record` | West Bank school register (PA Ministry of Education and UNICEF via OCHA, June 2015) · سجلّ مدارس الضفة الغربية (وزارة التربية والتعليم واليونيسف عبر أوتشا، حزيران 2015) | schools | 2,359 | 2026-08-05 | 2026-08-05 | 12 |
