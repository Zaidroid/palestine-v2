-- 129 — the fuel price history from official sources, and PCBS's monthly CPI
-- by region (2026-10-19).
--
-- Zaid, 2026-10-19: "hunt official source" for the fuel price history, and
-- fill CPI by region. The archive's own transcriptions cannot meet the
-- two-outlet rule before 2026 (migration 071), so the history comes from two
-- official, licensed series instead, each kept as its own dataset so a row's
-- provenance and licence stay visible in databank_serving:
--
--   pcbs_fuel_monthly     PCBS's CPI dashboard, "Commodity Prices": the monthly
--                         AVERAGE consumer price of petrol 95/98, diesel,
--                         kerosene, heating diesel and the 12 kg cylinder, by
--                         region, 2019-01 →. For liquid fuels the average equals
--                         the official cap in a month the cap holds (Dec 2014:
--                         diesel 6.18, petrol 95 6.68, kerosene 6.18 against the
--                         announcement; Sep 2026 diesel 8.39 both sides) and
--                         blends two caps when one changes mid-month (Sep 2026
--                         petrol 95: caps 8.15 then 7.65 from the 7th, average
--                         7.78); the cylinder is priced DELIVERED to the home,
--                         2–3 ILS above the cap. A different concept,
--                         fuel.price.average.
--   worldbank_gfpd_fuel   The World Bank's Global Fuel Prices Database (ODbL):
--                         West Bank official prices, monthly 2016-12 → 2025-04,
--                         "collected from local news articles" by the Bank, the
--                         article links in the workbook's comments. The SAME
--                         measure as fuel_prices_official (the cap), compiled by
--                         one institution rather than believed from two outlets,
--                         so it rides on the same fuel.price.official.* indicators
--                         under its own dataset and licence. Oct 2020 cross-check:
--                         Bank 5.32 / 4.79 / 58 = WAFA's announcement 5.32 / 4.79 / 58.
--   pcbs_cpi_monthly      The same dashboard, "Overall CPI": the monthly index
--                         (base 2018 = 100) and PCBS's own month-on-month change,
--                         Palestine / West Bank / Gaza Strip / Jerusalem J1,
--                         1996-01 →. Year-on-year is computed from the index, not
--                         stored. Sep 2026 cross-check: Palestine 158.04, +4.69 %;
--                         Gaza 304.45, +11.36 % = the press release of 14 Oct.
--
-- The loaders are ops/fetch_pcbs_monthly.py and ops/fetch_worldbank_fuel.py;
-- both are idempotent on (dataset, stable id, month).

BEGIN;

-- The Bank's fuel database is a separate source: ODbL, share-alike, not the
-- CC-BY World Bank indicators API the `worldbank` source row stands for.
INSERT INTO source (key, name, kind, license_spdx, commercial_use, attribution_text,
                    authority_rank, reliability, independence_group, active,
                    redistribution, share_alike, attribution_required, terms_url)
VALUES ('worldbank_gfpd',
        'World Bank — Global Fuel Prices Database (official prices compiled from news announcements)',
        'file', 'ODbL-1.0', true,
        'Fuel prices: World Bank Global Fuel Prices Database (datacatalog.worldbank.org/search/dataset/0066829), ODbL 1.0; West Bank official prices compiled from Palestinian news announcements.',
        1, 0.9, 'worldbank', true, 'share-alike', true, true,
        'https://datacatalog.worldbank.org/search/dataset/0066829/global-fuel-prices-database')
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name,
       license_spdx = EXCLUDED.license_spdx,
       attribution_text = EXCLUDED.attribution_text,
       redistribution = EXCLUDED.redistribution,
       share_alike = EXCLUDED.share_alike,
       attribution_required = EXCLUDED.attribution_required,
       terms_url = EXCLUDED.terms_url,
       active = EXCLUDED.active;

INSERT INTO concept (key, parent, name_en, name_ar, definition, notes)
VALUES ('fuel.price.average', NULL,
        'Average consumer fuel price (PCBS Consumer Price Survey)',
        'متوسط سعر المحروقات للمستهلك (مسح أسعار المستهلك، الإحصاء الفلسطيني)',
        'The monthly average price PCBS records for a fuel item in its Consumer Price Survey, by region. Not the official maximum: for liquid fuels the two coincide in a month the cap holds (the cap is the price at every station) and the average blends two caps when one changes mid-month; the gas cylinder is priced delivered to the home, above the cap.',
        'Source: the PCBS CPI dashboard, Commodity Prices (items 072200102/03/04, 045300201, 045300101, 045200101). Cross-checked Dec 2014 and Sep 2026 against the Petroleum Corporation announcements.')
ON CONFLICT (key) DO UPDATE
   SET name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar,
       definition = EXCLUDED.definition, notes = EXCLUDED.notes;

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs, attribution_text)
SELECT 'pcbs_fuel_monthly',
       'PCBS — monthly average consumer fuel prices by region (CPI dashboard, Commodity Prices)',
       source_id, 'fuel', 'monthly', true,
       '{"scope_note": "Monthly average consumer price from PCBS''s Consumer Price Survey, by region (Palestine, West Bank, Gaza Strip, Jerusalem J1), 2019-01 onward. Liquid fuels equal the official maximum in a month the maximum holds, and blend two maxima when it changes mid-month; the 12 kg cylinder is priced delivered to the home, 2–3 ILS above the official maximum.", "scope_note_ar": "متوسط سعر المستهلك الشهري من مسح أسعار المستهلك في الإحصاء الفلسطيني، حسب المنطقة، من كانون الثاني 2019. المحروقات السائلة تساوي الحد الأقصى الرسمي في الشهر الذي يثبت فيه، وتمزج حدّين إذا تغيّر في منتصف الشهر؛ أسطوانة الغاز 12 كغم مسعّرة واصلة للمنزل، أعلى من الحد الأقصى بشيقلين إلى ثلاثة.", "reader": "fetch_pcbs_monthly@1", "dashboard": "https://pcbs.gov.ps/cpiDashboard/en"}'::jsonb,
       'Data: Palestinian Central Bureau of Statistics (pcbs.gov.ps), CC-BY-4.0.'
FROM source WHERE key = 'pcbs_direct'
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, source_id = EXCLUDED.source_id, v1_category = EXCLUDED.v1_category,
       cadence = EXCLUDED.cadence, active = EXCLUDED.active, attrs = EXCLUDED.attrs,
       attribution_text = EXCLUDED.attribution_text;

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs,
                     license_spdx, redistribution, attribution_text)
SELECT 'worldbank_gfpd_fuel',
       'World Bank Global Fuel Prices Database — West Bank official fuel prices, monthly 2016-12 → 2025-04',
       source_id, 'fuel', 'irregular', true,
       '{"scope_note": "The official (maximum) consumer price in the West Bank for petrol 95/98, diesel, kerosene and the 5/12/48 kg cylinders, monthly from December 2016, as the World Bank compiled it from Palestinian news announcements for its Global Fuel Prices Database. The same measure as fuel_prices_official, compiled by one institution; the Bank''s last month is April 2025.", "scope_note_ar": "السعر الرسمي (الحد الأقصى) للمستهلك في الضفة الغربية لبنزين 95 و98 والسولار والكاز وأسطوانات 5 و12 و48 كغم، شهريًا من كانون الأول 2016، كما جمعه البنك الدولي من إعلانات الصحافة الفلسطينية لقاعدة بياناته لأسعار الوقود. المقياس نفسه الذي تحمله fuel_prices_official، جُمع من مؤسسة واحدة؛ آخر شهر لدى البنك نيسان 2025.", "reader": "fetch_worldbank_fuel@1", "workbook": "https://datacatalogfiles.worldbank.org/ddh-published/0066829/DR0095290/Global_Fuel_Prices_Database.xlsx"}'::jsonb,
       'ODbL-1.0', 'share-alike',
       'Fuel prices: World Bank Global Fuel Prices Database, ODbL 1.0; West Bank official prices compiled from Palestinian news announcements.'
FROM source WHERE key = 'worldbank_gfpd'
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, source_id = EXCLUDED.source_id, v1_category = EXCLUDED.v1_category,
       cadence = EXCLUDED.cadence, active = EXCLUDED.active, attrs = EXCLUDED.attrs,
       license_spdx = EXCLUDED.license_spdx, redistribution = EXCLUDED.redistribution,
       attribution_text = EXCLUDED.attribution_text;

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs, attribution_text)
SELECT 'pcbs_cpi_monthly',
       'PCBS — Consumer Price Index by region, monthly, base 2018 = 100 (CPI dashboard, Overall CPI)',
       source_id, 'pcbs', 'monthly', true,
       '{"scope_note": "The monthly Consumer Price Index (base 2018 = 100) and PCBS''s own month-on-month change, for Palestine, the West Bank (Jerusalem J1 excluded), the Gaza Strip and Jerusalem J1, from January 1996. Year-on-year change is computed from the index twelve months apart, not stored.", "scope_note_ar": "الرقم القياسي الشهري لأسعار المستهلك (سنة الأساس 2018 = 100) والتغير الشهري كما يحسبه الإحصاء الفلسطيني، لفلسطين والضفة الغربية (باستثناء القدس J1) وقطاع غزة والقدس J1، من كانون الثاني 1996. التغير السنوي يُحسب من الرقم القياسي قبل اثني عشر شهرًا ولا يُخزّن.", "reader": "fetch_pcbs_monthly@1", "base_year": 2018, "dashboard": "https://pcbs.gov.ps/cpiDashboard/en"}'::jsonb,
       'Data: Palestinian Central Bureau of Statistics (pcbs.gov.ps), CC-BY-4.0.'
FROM source WHERE key = 'pcbs_direct'
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, source_id = EXCLUDED.source_id, v1_category = EXCLUDED.v1_category,
       cadence = EXCLUDED.cadence, active = EXCLUDED.active, attrs = EXCLUDED.attrs,
       attribution_text = EXCLUDED.attribution_text;

INSERT INTO indicator_def (indicator, concept_key, name_en, name_ar, canonical_unit,
                           measure_kind, polarity, grain, place_grain, status,
                           source_spec, notes, serve_warning, serve_warning_ar,
                           ask_by_name, projection)
VALUES
 ('economic.pcbs_cpi_monthly', 'economy.prices',
  'Consumer Price Index, monthly, base 2018 = 100 (PCBS), by region',
  'الرقم القياسي لأسعار المستهلك، شهريًا، سنة الأساس 2018 = 100 (الإحصاء الفلسطيني)، حسب المنطقة',
  'index', 'index', -1, 'month', 'region', 'generated', 'pcbs_cpi_monthly',
  'PCBS CPI dashboard, Overall CPI, monthly frequency. Palestine rows carry no place (national); Jerusalem J1 rides on the Jerusalem governorate with region in attrs.',
  'Base 2018 = 100; Gaza Strip and the West Bank are separate indices and are not comparable as levels, only as changes.',
  'سنة الأساس 2018 = 100؛ قطاع غزة والضفة الغربية رقمان قياسيان منفصلان لا يُقارنان كمستويات بل كتغيرات.',
  true, false),
 ('economic.pcbs_cpi_monthly_change', 'economy.prices',
  'Consumer Price Index, change on the previous month, percent (PCBS), by region',
  'التغير في الرقم القياسي لأسعار المستهلك عن الشهر السابق، بالنسبة المئوية (الإحصاء الفلسطيني)، حسب المنطقة',
  'percent', 'rate', -1, 'month', 'region', 'generated', 'pcbs_cpi_monthly',
  'PCBS''s own month-on-month percentage, as the dashboard and the monthly press release give it (e.g. September 2026: Palestine +4.69, Gaza Strip +11.36, West Bank +0.53, Jerusalem J1 +0.44).',
  'Month on the previous month, as PCBS publishes it; not annualised.',
  'التغير عن الشهر السابق كما ينشره الإحصاء الفلسطيني؛ غير محوَّل إلى معدل سنوي.',
  true, false),
 ('fuel.price.average.gasoline_95', 'fuel.price.average',
  'Average consumer price of petrol 95, monthly (PCBS Consumer Price Survey), by region',
  'متوسط سعر المستهلك لبنزين 95، شهريًا (مسح أسعار المستهلك، الإحصاء الفلسطيني)، حسب المنطقة',
  'ILS_per_litre', 'stock', -1, 'month', 'region', 'generated', 'pcbs_fuel_monthly',
  'PCBS item 072200102. Equals the official maximum in a month the maximum holds (the cap is the price at every station); blends two when it changes mid-month (Sep 2026: 8.15 then 7.65, average 7.78).',
  'A monthly average from PCBS''s price survey, not the announced maximum; for petrol the two coincide when the maximum holds all month.',
  'متوسط شهري من مسح الأسعار في الإحصاء، لا الحد الأقصى المعلن؛ وللبنزين يتطابق الاثنان حين يثبت الحد طوال الشهر.',
  true, false),
 ('fuel.price.average.gasoline_98', 'fuel.price.average',
  'Average consumer price of petrol 98, monthly (PCBS Consumer Price Survey), by region',
  'متوسط سعر المستهلك لبنزين 98، شهريًا (مسح أسعار المستهلك، الإحصاء الفلسطيني)، حسب المنطقة',
  'ILS_per_litre', 'stock', -1, 'month', 'region', 'generated', 'pcbs_fuel_monthly',
  'PCBS item 072200103.',
  'A monthly average from PCBS''s price survey, not the announced maximum; for petrol the two coincide when the maximum holds all month.',
  'متوسط شهري من مسح الأسعار في الإحصاء، لا الحد الأقصى المعلن؛ وللبنزين يتطابق الاثنان حين يثبت الحد طوال الشهر.',
  true, false),
 ('fuel.price.average.diesel', 'fuel.price.average',
  'Average consumer price of diesel, monthly (PCBS Consumer Price Survey), by region',
  'متوسط سعر المستهلك للسولار، شهريًا (مسح أسعار المستهلك، الإحصاء الفلسطيني)، حسب المنطقة',
  'ILS_per_litre', 'stock', -1, 'month', 'region', 'generated', 'pcbs_fuel_monthly',
  'PCBS item 072200104 («سولار - اسرائيل»). Equals the official maximum (Dec 2014: 6.18 on both sides; Sep 2026: 8.39 on both).',
  'A monthly average from PCBS''s price survey, not the announced maximum; for diesel the two coincide when the maximum holds all month.',
  'متوسط شهري من مسح الأسعار في الإحصاء، لا الحد الأقصى المعلن؛ وللسولار يتطابق الاثنان حين يثبت الحد طوال الشهر.',
  true, false),
 ('fuel.price.average.kerosene', 'fuel.price.average',
  'Average consumer price of kerosene, monthly (PCBS Consumer Price Survey), by region',
  'متوسط سعر المستهلك للكاز، شهريًا (مسح أسعار المستهلك، الإحصاء الفلسطيني)، حسب المنطقة',
  'ILS_per_litre', 'stock', -1, 'month', 'region', 'generated', 'pcbs_fuel_monthly',
  'PCBS item 045300201.',
  'A monthly average from PCBS''s price survey, not the announced maximum.',
  'متوسط شهري من مسح الأسعار في الإحصاء، لا الحد الأقصى المعلن.',
  true, false),
 ('fuel.price.average.heating_diesel', 'fuel.price.average',
  'Average consumer price of heating diesel, monthly (PCBS Consumer Price Survey), by region',
  'متوسط سعر المستهلك لسولار التدفئة، شهريًا (مسح أسعار المستهلك، الإحصاء الفلسطيني)، حسب المنطقة',
  'ILS_per_litre', 'stock', -1, 'month', 'region', 'generated', 'pcbs_fuel_monthly',
  'PCBS item 045300101. The Petroleum Corporation announces no separate heating-diesel price; this is the survey average only.',
  'A monthly average from PCBS''s price survey; no official maximum exists for this item.',
  'متوسط شهري من مسح الأسعار في الإحصاء؛ لا حدّ أقصى رسميًا لهذا الصنف.',
  true, false),
 ('fuel.price.average.lpg_12kg_delivered', 'fuel.price.average',
  'Average consumer price of a 12 kg gas cylinder delivered to the home, monthly (PCBS Consumer Price Survey), by region',
  'متوسط سعر المستهلك لأسطوانة غاز 12 كغم واصلة للمنزل، شهريًا (مسح أسعار المستهلك، الإحصاء الفلسطيني)، حسب المنطقة',
  'ILS_per_cylinder', 'stock', -1, 'month', 'region', 'generated', 'pcbs_fuel_monthly',
  'PCBS item 045200101 («اسطوانة غاز معبئة محلياً واصل للمنزل»). Priced delivered: 2–3 ILS above the official maximum at the distributor (Dec 2014: 66.25 against a cap of 63).',
  'Delivered to the home; above the official maximum, which is set at the distributor.',
  'واصلة للمنزل؛ أعلى من الحد الأقصى الرسمي المحدد عند الموزع.',
  true, false)
ON CONFLICT (indicator) DO UPDATE
   SET concept_key = EXCLUDED.concept_key,
       name_en = EXCLUDED.name_en,
       name_ar = EXCLUDED.name_ar,
       canonical_unit = EXCLUDED.canonical_unit,
       measure_kind = EXCLUDED.measure_kind,
       polarity = EXCLUDED.polarity,
       grain = EXCLUDED.grain,
       place_grain = EXCLUDED.place_grain,
       status = EXCLUDED.status,
       source_spec = EXCLUDED.source_spec,
       notes = EXCLUDED.notes,
       serve_warning = EXCLUDED.serve_warning,
       serve_warning_ar = EXCLUDED.serve_warning_ar,
       ask_by_name = EXCLUDED.ask_by_name,
       projection = EXCLUDED.projection;

COMMIT;
