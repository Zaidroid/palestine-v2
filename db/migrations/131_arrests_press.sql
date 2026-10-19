-- 131 — arrests as the prisoners' organisations count them, read from the
-- archive's statements (2026-10-19).
--
-- Zaid, 19 Oct: arrests by governorate and month was the fill he put first;
-- "how many kids got detained in the West Bank" was his own example. The
-- databank holds the joint institutions' PDFs to January 2024 and Addameer's
-- monthly stock; the archive holds the organisations' statements month by
-- month since 2014 and the Prisoners' Club's overnight statements since
-- October 2023. ops/extract_arrests.py reads them (headline first; a range,
-- a cumulative or a year is not a month; a figure scoped to one governorate
-- is that governorate's row); ops/load_arrests_press.py loads them with the
-- quote and the document on every row. Two authorities may count a month
-- differently: each keeps its row, the authority in attrs.

BEGIN;

INSERT INTO source (key, name, kind, license_spdx, commercial_use, attribution_text,
                    authority_rank, reliability, independence_group, active,
                    redistribution, share_alike, attribution_required)
VALUES ('prisoner_orgs_press',
        'Prisoners'' organisations'' tallies as printed by Palestinian outlets (Prisoners'' Club, Palestine Centre for Prisoner Studies, the joint institutions, the Commission of Detainees, Addameer, the Jerusalem governorate)',
        'derived', 'fair-use-attribution', false,
        'Arrest tallies: the Palestinian prisoners'' organisations'' monthly and daily statements, as printed by Palestinian outlets; each figure carries its statement and its document.',
        2, 0.75, 'prisoner_orgs', true, 'attribution', false, true)
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, license_spdx = EXCLUDED.license_spdx, attribution_text = EXCLUDED.attribution_text,
       reliability = EXCLUDED.reliability, redistribution = EXCLUDED.redistribution, active = EXCLUDED.active;

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs, attribution_text)
SELECT 'arrests_press',
       'Arrests as the prisoners'' organisations count them — monthly tallies (2014 →) and overnight statements (Oct 2023 →), read from the archive',
       source_id, 'prisoners', 'daily', true,
       '{"scope_note": "Monthly: the total, children and women arrested in a month as one of the organisations stated it (the Palestine Centre for Prisoner Studies, the Prisoners'' Club, the joint institutions, the Commission of Detainees, Addameer), on the West Bank or on one governorate when the statement is scoped to it (the Jerusalem governorate''s monthly report); two authorities for one month are two rows. Daily: the Prisoners'' Club''s overnight count (since last evening), one value a day; a day without a statement is absent, never zero. Machine-read from the archive by ops/extract_arrests.py; each row carries its quote and document.", "scope_note_ar": "شهريًا: مجموع المعتقلين والأطفال والنساء في الشهر كما أعلنته إحدى المؤسسات (مركز فلسطين لدراسات الأسرى، نادي الأسير، مؤسسات الأسرى في تقريرها المشترك، هيئة شؤون الأسرى، الضمير)، على الضفة الغربية أو على محافظة واحدة حين يخصّها البيان (تقرير محافظة القدس الشهري)؛ جهتان لشهر واحد صفّان. يوميًا: حصيلة نادي الأسير منذ مساء أمس، قيمة واحدة في اليوم؛ اليوم الذي لا بيان فيه غائب لا صفر. قُرئت آليًا من الأرشيف؛ كل صف يحمل اقتباسه ووثيقته.", "reader": "extract_arrests@1"}'::jsonb,
       'Arrest tallies: the prisoners'' organisations'' statements as printed by Palestinian outlets.'
FROM source WHERE key = 'prisoner_orgs_press'
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, source_id = EXCLUDED.source_id, v1_category = EXCLUDED.v1_category,
       cadence = EXCLUDED.cadence, active = EXCLUDED.active, attrs = EXCLUDED.attrs, attribution_text = EXCLUDED.attribution_text;

INSERT INTO indicator_def (indicator, concept_key, name_en, name_ar, canonical_unit,
                           measure_kind, polarity, grain, place_grain, status,
                           source_spec, notes, serve_warning, serve_warning_ar,
                           ask_by_name, projection)
VALUES
 ('prisoners.arrests_reported.total', 'detention',
  'Arrests in the month as the prisoners'' organisations counted them, by scope (West Bank or one governorate)',
  'الاعتقالات في الشهر كما أحصتها مؤسسات الأسرى، حسب النطاق (الضفة الغربية أو محافظة واحدة)',
  'arrests', 'flow', -1, 'month', 'governorate', 'generated', 'arrests_press',
  'The authority that counted is in attrs (pcps, pps, joint, commission, addameer, governorate_office); two authorities for one month are two rows. Read from the archive with the quote on every row.',
  'The organisations'' own monthly counts as printed; two organisations may count one month differently and both rows are kept; machine-read with the quote on every row.',
  'إحصاءات المؤسسات الشهرية كما طُبعت؛ قد تختلف جهتان في شهر واحد ويُحتفظ بالصفّين؛ قراءة آلية مع الاقتباس في كل صف.',
  false, false),
 ('prisoners.arrests_reported.children', 'detention',
  'Children arrested in the month as the prisoners'' organisations counted them',
  'الأطفال المعتقلون في الشهر كما أحصتهم مؤسسات الأسرى',
  'arrests', 'flow', -1, 'month', 'governorate', 'generated', 'arrests_press',
  'From the same statement as the month''s total; absent when the statement gives no figure.',
  'As printed; absent when the statement gives no figure.', 'كما طُبع؛ غائب حين لا يذكر البيان رقمًا.', false, false),
 ('prisoners.arrests_reported.women', 'detention',
  'Women arrested in the month as the prisoners'' organisations counted them',
  'النساء المعتقلات في الشهر كما أحصتهن مؤسسات الأسرى',
  'arrests', 'flow', -1, 'month', 'governorate', 'generated', 'arrests_press',
  'From the same statement as the month''s total; absent when the statement gives no figure.',
  'As printed; absent when the statement gives no figure.', 'كما طُبع؛ غائب حين لا يذكر البيان رقمًا.', false, false),
 ('prisoners.arrests_reported.overnight', 'detention',
  'Arrests since the previous evening as the Prisoners'' Club stated them, daily (West Bank)',
  'الاعتقالات منذ مساء أمس كما أعلنها نادي الأسير، يوميًا (الضفة الغربية)',
  'arrests', 'flow', -1, 'day', 'region', 'generated', 'arrests_press',
  'One value a day, the one most statements agree on; a day without a statement is absent (the archive holds the statement on about one day in four), so a monthly sum is a floor, never a total.',
  'A day without a statement is absent, not zero: summing days gives a floor, never the month''s total.',
  'اليوم الذي لا بيان فيه غائب لا صفر: جمع الأيام يعطي حدًا أدنى لا مجموع الشهر.', false, false)
ON CONFLICT (indicator) DO UPDATE
   SET concept_key = EXCLUDED.concept_key, name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar,
       canonical_unit = EXCLUDED.canonical_unit, measure_kind = EXCLUDED.measure_kind, polarity = EXCLUDED.polarity,
       grain = EXCLUDED.grain, place_grain = EXCLUDED.place_grain, status = EXCLUDED.status, source_spec = EXCLUDED.source_spec,
       notes = EXCLUDED.notes, serve_warning = EXCLUDED.serve_warning, serve_warning_ar = EXCLUDED.serve_warning_ar,
       ask_by_name = EXCLUDED.ask_by_name, projection = EXCLUDED.projection;

COMMIT;
