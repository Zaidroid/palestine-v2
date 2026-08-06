-- 051 — the water category becomes real (the water recovery, 2026-08-06).
--
-- v1's 25,049-row "water" category was measured to be NO LOSS (water.yaml,
-- water_gho.yaml carry the arithmetic): its content is GHO/WDI data the
-- databank already serves with identity. What was actually missing:
--   1. ONE GHO code with PSE data (WSH_SANITATION_OD) — now dataset
--      who_gho_wash, fetched by v2 itself (ops/fetch_gho_wash.py).
--   2. A serving surface: /v2/databank/water served nothing while the
--      complete JMP WASH access series sat inside v1_health_who.
-- v_water mirrors serve/app.py's water-domain rule: the category's own
-- datasets plus health's wsh_* series. One fact, one storage row, two
-- category doors; indicator names keep their home namespace.

CREATE OR REPLACE VIEW v_water AS
SELECT occurred_at, occurred_precision, indicator, value_num, value_text,
       unit, place_id, attrs, source_name, license_spdx, attribution_text
FROM databank_serving
WHERE v1_category = 'water' OR indicator LIKE 'health.wsh%';
