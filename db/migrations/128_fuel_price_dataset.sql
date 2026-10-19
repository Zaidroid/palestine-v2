-- 128 — the Petroleum Corporation's official monthly maximum fuel prices,
-- as a databank dataset (the same source → dataset → indicator_def → observation
-- path as every other category).
--
-- Zaid, 2026-09-23: track "live updated prices of fuel in palestine".
-- Zaid, 2026-10-18: treat it like all datasets, and backfill the longest
-- historical series from the archive.
--
-- WHAT THE NUMBER IS. The Palestinian General Petroleum Corporation
-- (الهيئة العامة للبترول, Ministry of Finance) sets the MAXIMUM consumer price
-- of petrol 95/98, diesel, kerosene and cooking-gas cylinders for the West Bank,
-- once a month, sometimes again mid-month. It is a regulated ceiling, not a
-- pump-by-pump observation. Gaza has no official consumer price at all.
--
-- HOW IT IS BELIEVED. One article is one transcription (cascade/fuel_price.py);
-- a price is served only when two independent outlets transcribe the same
-- number for the same product and effective date, and at least one names the
-- authority (migration 071). The observations are loaded from
-- fuel_price_believed by ops/load_fuel_prices.py.
--
-- The source row is the authority, not the outlets; the outlets ride in
-- observation.attrs (urls, outlets, distinct_texts). The 2003 window is the
-- archive's oldest fuel-price headline; the backfill fills it.

BEGIN;

INSERT INTO source (key, name, kind, license_spdx, commercial_use, attribution_text,
                    authority_rank, reliability, independence_group, active,
                    redistribution, home_place_id)
VALUES ('psc_petroleum',
        'الهيئة العامة للبترول — Palestinian General Petroleum Corporation (official monthly maximum prices)',
        'manual', 'NONE', false,
        'Official monthly maximum consumer prices set by the Palestinian General Petroleum Corporation (Ministry of Finance); transcribed from Palestinian outlets.',
        0, 1.0, 'psc', true, 'attribution', 2)
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name,
       attribution_text = EXCLUDED.attribution_text,
       authority_rank = EXCLUDED.authority_rank,
       reliability = EXCLUDED.reliability,
       independence_group = EXCLUDED.independence_group,
       active = EXCLUDED.active,
       redistribution = EXCLUDED.redistribution,
       home_place_id = EXCLUDED.home_place_id;

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs,
                     license_spdx, redistribution, attribution_text)
SELECT 'fuel_prices_official',
       'Palestinian General Petroleum Corporation — official monthly maximum consumer fuel prices, West Bank',
       source_id, 'fuel', 'monthly', true,
       '{"scope_note":"الحد الأقصى الرسمي الشهري الذي تحدده الهيئة العامة للبترول للضفة الغربية؛ ليس سعر مضخة، وقد تبيع المحطات أقل. غزة بلا سعر استهلاكي رسمي.","publisher_window_from":"2003-02-25","belief":"two independent outlets, one naming the Petroleum Corporation","reader":"fuel_price@4"}'::jsonb,
       NULL, NULL,
       'Official monthly maximum consumer prices: Palestinian General Petroleum Corporation, transcribed from Palestinian outlets.'
FROM source WHERE key = 'psc_petroleum'
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name,
       source_id = EXCLUDED.source_id,
       v1_category = EXCLUDED.v1_category,
       cadence = EXCLUDED.cadence,
       active = EXCLUDED.active,
       attrs = EXCLUDED.attrs;

INSERT INTO concept (key, parent, name_en, name_ar, definition, notes)
VALUES ('fuel.price.official', NULL,
        'Official maximum fuel price (Palestinian General Petroleum Corporation)',
        'الحد الأقصى الرسمي لأسعار المحروقات (الهيئة العامة للبترول)',
        'The monthly maximum consumer price set by the Palestinian General Petroleum Corporation for the West Bank; a regulated ceiling, not a pump price. Gaza has no official consumer fuel price.',
        'Believed when two independent outlets transcribe the same number for the same effective date and at least one names the authority (fuel_price_believed).')
ON CONFLICT (key) DO UPDATE
   SET name_en = EXCLUDED.name_en,
       name_ar = EXCLUDED.name_ar,
       definition = EXCLUDED.definition,
       notes = EXCLUDED.notes;

INSERT INTO unit_def (key, name_en, name_ar, dimension, notes)
VALUES ('ILS_per_cylinder', 'shekels per cylinder', 'شيكل للأسطوانة', 'price_per_item',
        'A price for one gas cylinder of the size the indicator names (2.5/5/12/48 kg). Not per kilogram: the cylinder is the unit the Petroleum Corporation prices, and its weight is in the indicator, not in a density.')
ON CONFLICT (key) DO UPDATE
   SET name_en = EXCLUDED.name_en,
       name_ar = EXCLUDED.name_ar,
       dimension = EXCLUDED.dimension,
       notes = EXCLUDED.notes;

INSERT INTO indicator_def (indicator, concept_key, name_en, name_ar, canonical_unit,
                           measure_kind, polarity, grain, place_grain, status,
                           source_spec, notes, serve_warning, serve_warning_ar,
                           ask_by_name, projection)
VALUES
 ('fuel.price.official.gasoline_95', 'fuel.price.official',
  'Official maximum price of petrol 95 in the West Bank, monthly (Petroleum Corporation)',
  'الحد الأقصى الرسمي لسعر بنزين 95 في الضفة الغربية، شهريًا (الهيئة العامة للبترول)',
  'ILS_per_litre', 'stock', -1, 'month', 'region', 'generated', 'fuel_prices_official',
  'The maximum consumer price set monthly by the Palestinian General Petroleum Corporation (Ministry of Finance); believed when two independent outlets transcribe the same number for the same effective date and at least one names the authority. West Bank only; Gaza has no official consumer fuel price; not a pump price.',
  'Official monthly maximum, West Bank only; not a pump price; Gaza has no official consumer fuel price.',
  'الحد الأقصى الرسمي الشهري الذي تحدده الهيئة العامة للبترول للضفة الغربية؛ ليس سعر مضخة، وقد تبيع المحطات أقل. غزة بلا سعر استهلاكي رسمي.', true, false),
 ('fuel.price.official.gasoline_98', 'fuel.price.official',
  'Official maximum price of petrol 98 in the West Bank, monthly (Petroleum Corporation)',
  'الحد الأقصى الرسمي لسعر بنزين 98 في الضفة الغربية، شهريًا (الهيئة العامة للبترول)',
  'ILS_per_litre', 'stock', -1, 'month', 'region', 'generated', 'fuel_prices_official',
  'The maximum consumer price set monthly by the Palestinian General Petroleum Corporation (Ministry of Finance); believed when two independent outlets transcribe the same number for the same effective date and at least one names the authority. West Bank only; Gaza has no official consumer fuel price; not a pump price.',
  'Official monthly maximum, West Bank only; not a pump price; Gaza has no official consumer fuel price.',
  'الحد الأقصى الرسمي الشهري الذي تحدده الهيئة العامة للبترول للضفة الغربية؛ ليس سعر مضخة، وقد تبيع المحطات أقل. غزة بلا سعر استهلاكي رسمي.', true, false),
 ('fuel.price.official.diesel', 'fuel.price.official',
  'Official maximum price of diesel in the West Bank, monthly (Petroleum Corporation)',
  'الحد الأقصى الرسمي لسعر السولار في الضفة الغربية، شهريًا (الهيئة العامة للبترول)',
  'ILS_per_litre', 'stock', -1, 'month', 'region', 'generated', 'fuel_prices_official',
  'The maximum consumer price set monthly by the Palestinian General Petroleum Corporation (Ministry of Finance); believed when two independent outlets transcribe the same number for the same effective date and at least one names the authority. West Bank only; Gaza has no official consumer fuel price; not a pump price.',
  'Official monthly maximum, West Bank only; not a pump price; Gaza has no official consumer fuel price.',
  'الحد الأقصى الرسمي الشهري الذي تحدده الهيئة العامة للبترول للضفة الغربية؛ ليس سعر مضخة، وقد تبيع المحطات أقل. غزة بلا سعر استهلاكي رسمي.', true, false),
 ('fuel.price.official.kerosene', 'fuel.price.official',
  'Official maximum price of kerosene in the West Bank, monthly (Petroleum Corporation)',
  'الحد الأقصى الرسمي لسعر الكاز في الضفة الغربية، شهريًا (الهيئة العامة للبترول)',
  'ILS_per_litre', 'stock', -1, 'month', 'region', 'generated', 'fuel_prices_official',
  'The maximum consumer price set monthly by the Palestinian General Petroleum Corporation (Ministry of Finance); believed when two independent outlets transcribe the same number for the same effective date and at least one names the authority. West Bank only; Gaza has no official consumer fuel price; not a pump price.',
  'Official monthly maximum, West Bank only; not a pump price; Gaza has no official consumer fuel price.',
  'الحد الأقصى الرسمي الشهري الذي تحدده الهيئة العامة للبترول للضفة الغربية؛ ليس سعر مضخة، وقد تبيع المحطات أقل. غزة بلا سعر استهلاكي رسمي.', true, false),
 ('fuel.price.official.lpg_2_5kg', 'fuel.price.official',
  'Official maximum price of a 2.5 kg cooking-gas cylinder in the West Bank, monthly (Petroleum Corporation)',
  'الحد الأقصى الرسمي لسعر أسطوانة غاز 2.5 كغم في الضفة الغربية، شهريًا (الهيئة العامة للبترول)',
  'ILS_per_cylinder', 'stock', -1, 'month', 'region', 'generated', 'fuel_prices_official',
  'The maximum consumer price set monthly by the Palestinian General Petroleum Corporation (Ministry of Finance); believed when two independent outlets transcribe the same number for the same effective date and at least one names the authority. West Bank only; Gaza has no official consumer fuel price; not a pump price.',
  'Official monthly maximum, West Bank only; not a pump price; Gaza has no official consumer fuel price.',
  'الحد الأقصى الرسمي الشهري الذي تحدده الهيئة العامة للبترول للضفة الغربية؛ ليس سعر مضخة، وقد تبيع المحطات أقل. غزة بلا سعر استهلاكي رسمي.', true, false),
 ('fuel.price.official.lpg_5kg', 'fuel.price.official',
  'Official maximum price of a 5 kg cooking-gas cylinder in the West Bank, monthly (Petroleum Corporation)',
  'الحد الأقصى الرسمي لسعر أسطوانة غاز 5 كغم في الضفة الغربية، شهريًا (الهيئة العامة للبترول)',
  'ILS_per_cylinder', 'stock', -1, 'month', 'region', 'generated', 'fuel_prices_official',
  'The maximum consumer price set monthly by the Palestinian General Petroleum Corporation (Ministry of Finance); believed when two independent outlets transcribe the same number for the same effective date and at least one names the authority. West Bank only; Gaza has no official consumer fuel price; not a pump price.',
  'Official monthly maximum, West Bank only; not a pump price; Gaza has no official consumer fuel price.',
  'الحد الأقصى الرسمي الشهري الذي تحدده الهيئة العامة للبترول للضفة الغربية؛ ليس سعر مضخة، وقد تبيع المحطات أقل. غزة بلا سعر استهلاكي رسمي.', true, false),
 ('fuel.price.official.lpg_12kg', 'fuel.price.official',
  'Official maximum price of a 12 kg cooking-gas cylinder in the West Bank, monthly (Petroleum Corporation)',
  'الحد الأقصى الرسمي لسعر أسطوانة غاز 12 كغم في الضفة الغربية، شهريًا (الهيئة العامة للبترول)',
  'ILS_per_cylinder', 'stock', -1, 'month', 'region', 'generated', 'fuel_prices_official',
  'The maximum consumer price set monthly by the Palestinian General Petroleum Corporation (Ministry of Finance); believed when two independent outlets transcribe the same number for the same effective date and at least one names the authority. West Bank only; Gaza has no official consumer fuel price; not a pump price.',
  'Official monthly maximum, West Bank only; not a pump price; Gaza has no official consumer fuel price.',
  'الحد الأقصى الرسمي الشهري الذي تحدده الهيئة العامة للبترول للضفة الغربية؛ ليس سعر مضخة، وقد تبيع المحطات أقل. غزة بلا سعر استهلاكي رسمي.', true, false),
 ('fuel.price.official.lpg_48kg', 'fuel.price.official',
  'Official maximum price of a 48 kg cooking-gas cylinder in the West Bank, monthly (Petroleum Corporation)',
  'الحد الأقصى الرسمي لسعر أسطوانة غاز 48 كغم في الضفة الغربية، شهريًا (الهيئة العامة للبترول)',
  'ILS_per_cylinder', 'stock', -1, 'month', 'region', 'generated', 'fuel_prices_official',
  'The maximum consumer price set monthly by the Palestinian General Petroleum Corporation (Ministry of Finance); believed when two independent outlets transcribe the same number for the same effective date and at least one names the authority. West Bank only; Gaza has no official consumer fuel price; not a pump price.',
  'Official monthly maximum, West Bank only; not a pump price; Gaza has no official consumer fuel price.',
  'الحد الأقصى الرسمي الشهري الذي تحدده الهيئة العامة للبترول للضفة الغربية؛ ليس سعر مضخة، وقد تبيع المحطات أقل. غزة بلا سعر استهلاكي رسمي.', true, false)
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
       projection = EXCLUDED.projection,
       updated_at = now();

COMMIT;
