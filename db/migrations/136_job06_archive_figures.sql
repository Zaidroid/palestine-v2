-- 136 — JOB-06, the figures lake (2026-10-20): the DeepSeek harness read every
-- body in the archive overnight (2.8 M texts, 284,728 figure sentences in 29
-- families, docs/jobs/JOB-06-RETURN.md) and pilot-reviewed ten series. Claude
-- re-read all 343 kept rows (db/reference/job06_review.yaml): four hold up as
-- series and are loaded by ops/load_job_returns.py; four are statements, not
-- series, and go to the cited figures (db/reference/cited_figures.yaml, I);
-- two are noise and are not loaded.
--
--   units                  trees, dunums, days, beds (the registry carries them
--                          too; created here first, as 130 and 135 did).
--   settlements_press_events  gains settlements.trees_uprooted_reported (one
--                          incident, trees, on the village) and
--                          settlements.land_seizure_order_reported (one military
--                          order or declaration, dunums, on the village).
--   settlements_press_tallies  NEW: the Palestinian authorities' tallies of
--                          trees damaged as the press printed them — the
--                          Colonization and Wall Resistance Commission by the
--                          month (2025 →, with governorate splits) and the
--                          Ministry of Agriculture by the week —
--                          settlements.trees_damaged_stated and _olive_stated.
--   gaza_supply_press      NEW: the Gaza Government Media Office's running
--                          count of trucks entered since the ceasefire of
--                          10 Oct 2025 against the agreed 600 a day
--                          (aid.gaza.ceasefire_trucks_entered_cumulative /
--                          _agreed_cumulative), aid trucks on a stated day
--                          (aid.gaza.aid_trucks_entered_day_stated), and the
--                          Petroleum Authority's cooking-gas shipments
--                          (energy.gaza.cooking_gas_trucks_entered).

BEGIN;

INSERT INTO unit_def (key, name_en, name_ar, dimension, notes) VALUES
 ('trees',  'trees',  'أشجار', 'count', 'Trees counted one by one: uprooted, cut, burned or poisoned. Olive, almond, vines and fruit trees alike unless the row says which.'),
 ('dunums', 'dunums', 'دونم',  'area',  'The dunum of Palestinian land records, 1,000 m². A military order prints "7.498 دونم" for 7 dunums and 498 m²: the dot is a decimal point.'),
 ('days',   'days',   'أيام',  'time',  'Calendar days, as in days a crossing was open or closed in a month.'),
 ('beds',   'beds',   'أسرّة', 'count', 'Hospital beds in service.')
ON CONFLICT (key) DO UPDATE
   SET name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar, dimension = EXCLUDED.dimension, notes = EXCLUDED.notes;

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs, attribution_text)
SELECT 'settlements_press_tallies',
       'Trees damaged in the West Bank as the Palestinian authorities tallied them, read from the archive''s news texts and reviewed (2025 →)',
       source_id, 'settlements', 'monthly', true,
       '{"scope_note": "One row per tally and place: the Colonization and Wall Resistance Commission''s monthly and yearly counts of trees uprooted, cut, burned or poisoned (with its governorate split when printed), the Ministry of Agriculture''s weekly documentation, and one official''s September 2026 figure, each as a Palestinian outlet printed the sentence. Read from the archive by the DeepSeek harness (docs/jobs/JOB-06-RETURN.md) and re-read row by row by Claude (db/reference/job06_review.yaml). A tally repeated by several outlets over several months is one row, dated at its period. The monthly and the weekly counts are different authorities with different methods: never summed together, and neither is summed with the incident rows of settlements_press_events.", "scope_note_ar": "صف لكل حصيلة ومكان: عدّ هيئة مقاومة الجدار والاستيطان الشهري والسنوي للأشجار المقتلعة أو المقطوعة أو المحروقة أو المسمومة (مع توزيعه على المحافظات حين يُطبع)، وتوثيق وزارة الزراعة الأسبوعي، ورقم مسؤول واحد لأيلول 2026، كلٌّ كما طبعت الجملةَ صحيفةٌ فلسطينية. قُرئت من الأرشيف ثم روجعت صفًا صفًا. الحصيلة التي تكررها صحف عدة على أشهر صف واحد بتاريخ فترتها. العدّ الشهري والأسبوعي جهتان مختلفتان بمنهجين مختلفين: لا يُجمعان، ولا يُجمع أيّ منهما مع صفوف الحوادث.", "reader": "JOB-06 lake + Claude re-read 2026-10-20"}'::jsonb,
       'Trees damaged, tallied by the Colonization and Wall Resistance Commission and the Ministry of Agriculture: read from Palestinian news texts in the archive, reviewed.'
FROM source WHERE key = 'press_archive'
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, source_id = EXCLUDED.source_id, v1_category = EXCLUDED.v1_category,
       cadence = EXCLUDED.cadence, active = EXCLUDED.active, attrs = EXCLUDED.attrs, attribution_text = EXCLUDED.attribution_text;

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs, attribution_text)
SELECT 'gaza_supply_press',
       'Trucks into Gaza since the ceasefire of 10 October 2025 as the Government Media Office counted them, and cooking-gas shipments as the Petroleum Authority announced them, read from the archive and reviewed',
       source_id, 'aid_access', 'irregular', true,
       '{"scope_note": "The Government Media Office in Gaza publishes a running count of trucks that entered the strip since the ceasefire of 10 October 2025 against the 600 a day the agreement set (the agreed figure is 600 × the days elapsed). One row per statement, dated the day the count ran to: trucks entered and trucks agreed, both cumulative, with the scope in attrs — the October 2025 statement counts aid trucks only, the 2026 statements count aid, commercial and fuel trucks together, so the series changes what it counts across the new year and is read with its scope. Beside it, aid trucks that entered on a stated day, and the General Petroleum Authority''s cooking-gas shipments, 2 to 6 truckloads each. Read from the archive by the DeepSeek harness (docs/jobs/JOB-06-RETURN.md), re-read row by row by Claude (db/reference/job06_review.yaml). The UN''s offloaded-truck counts (aid_un2720) and the Chamber''s (aid_gazacham) are the other counts; none is summed with another.", "scope_note_ar": "ينشر المكتب الإعلامي الحكومي في غزة عدًّا متراكمًا للشاحنات التي دخلت القطاع منذ وقف إطلاق النار في 10 تشرين الأول 2025 مقابل 600 شاحنة يوميًا نصّ عليها الاتفاق (المتفق عليه = 600 × الأيام المنقضية). صف لكل بيان بتاريخ اليوم الذي بلغه العدّ: ما دخل وما اتُّفق عليه، كلاهما تراكمي، والنطاق في الخصائص: بيان تشرين الأول 2025 يعدّ شاحنات المساعدات وحدها، وبيانات 2026 تعدّ المساعدات والتجارية والوقود معًا، فالسلسلة تغيّر ما تعدّه مع مطلع السنة وتُقرأ بنطاقها. وإلى جانبها شاحنات المساعدات التي دخلت في يوم مذكور، وشحنات غاز الطهي التي تعلنها هيئة البترول، من حمولتين إلى ست. قُرئت من الأرشيف ثم روجعت صفًا صفًا. عدّ الأمم المتحدة وعدّ الغرفة التجارية عدّان آخران، ولا يُجمع عدّ مع آخر.", "reader": "JOB-06 lake + Claude re-read 2026-10-20"}'::jsonb,
       'Trucks into Gaza (Government Media Office) and cooking-gas shipments (General Petroleum Authority): read from Palestinian news texts in the archive, reviewed.'
FROM source WHERE key = 'press_archive'
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, source_id = EXCLUDED.source_id, v1_category = EXCLUDED.v1_category,
       cadence = EXCLUDED.cadence, active = EXCLUDED.active, attrs = EXCLUDED.attrs, attribution_text = EXCLUDED.attribution_text;

UPDATE dataset
   SET attrs = attrs || '{"scope_note_trees_land": "Since 2026-10-20 (JOB-06) the dataset also holds one row per incident of trees uprooted, cut, burned or poisoned (settlements.trees_uprooted_reported, on the village when named, with the actor and the kind of tree in attrs) and one row per military seizure order or state-land declaration in dunums (settlements.land_seizure_order_reported). Both are floors: an incident no outlet printed is absent, and several outlets on one incident are one row.", "scope_note_trees_land_ar": "منذ 2026-10-20 تحمل المجموعة أيضًا صفًا لكل حادثة اقتلاع أو قطع أو حرق أو تسميم للأشجار (على القرية إن سُمّيت، والفاعل ونوع الشجر في الخصائص) وصفًا لكل أمر وضع يد عسكري أو إعلان أراضي دولة بالدونم. كلاهما حدّ أدنى: ما لم تطبعه الصحافة غائب، وعدة صحف على حادثة واحدة صف واحد."}'::jsonb
 WHERE key = 'settlements_press_events';

INSERT INTO indicator_def (indicator, concept_key, name_en, name_ar, canonical_unit,
                           measure_kind, polarity, grain, place_grain, status,
                           source_spec, notes, serve_warning, serve_warning_ar, ask_by_name, projection)
VALUES
 ('settlements.trees_uprooted_reported', 'violence.settler',
  'Trees uprooted, cut, burned or poisoned in one incident, as the outlets reported it, on the village when named (archive, reviewed)',
  'أشجار اقتُلعت أو قُطعت أو حُرقت أو سُمّمت في حادثة واحدة كما نقلتها الصحافة، على القرية إن سُمّيت (الأرشيف، مراجَع)',
  'trees', 'flow', -1, 'day', 'locality', 'generated', 'settlements_press_events',
  'One row per incident; the actor (settlers or the army), the kind of tree, the qualifier ("more than", "about") and the quote in attrs. Several outlets on one incident are one row. 2026 so far; the lake holds 3,303 sentences back to 2003 for a later pass.',
  'A floor read from the press, reviewed: incidents no outlet printed are absent, and the authorities'' tallies (settlements.trees_damaged_stated) count far more than the incidents the press itemises.',
  'حدّ أدنى مقروء من الصحافة ومراجَع: الحوادث التي لم تطبعها الصحافة غائبة، وحصائل الجهات الرسمية تعدّ أكثر بكثير مما تفصّله الصحافة.', true, false),
 ('settlements.land_seizure_order_reported', 'land.confiscation',
  'Land in one Israeli military seizure order or state-land declaration, in dunums, on the village named, as the outlets reported it (archive, reviewed)',
  'الأرض في أمر وضع يد عسكري إسرائيلي واحد أو إعلان أراضي دولة، بالدونم، على القرية المسمّاة، كما نقلتها الصحافة (الأرشيف، مراجَع)',
  'dunums', 'flow', -1, 'day', 'locality', 'generated', 'settlements_press_events',
  'One row per order; the kind (order or declaration), the stated purpose, the order number when printed and the quote in attrs. "7.498 دونم" is 7 dunums and 498 m². July–October 2026 so far.',
  'A floor read from the press, reviewed: orders no outlet printed are absent. The Commission''s cumulative since October 2023 is a cited figure, not the sum of these rows.',
  'حدّ أدنى مقروء من الصحافة ومراجَع: الأوامر التي لم تطبعها الصحافة غائبة. مجموع الهيئة منذ تشرين الأول 2023 رقم مقتبس، لا حاصل جمع هذه الصفوف.', true, false),
 ('settlements.trees_damaged_stated', 'violence.settler',
  'Trees uprooted, cut, burned or poisoned in a period, as a Palestinian authority tallied it and the press printed it (Commission monthly and yearly, Ministry of Agriculture weekly)',
  'الأشجار المقتلعة أو المقطوعة أو المحروقة أو المسمومة في فترة، كما عدّتها جهة فلسطينية وطبعتها الصحافة (الهيئة شهريًا وسنويًا، وزارة الزراعة أسبوعيًا)',
  'trees', 'flow', -1, 'month', 'governorate', 'generated', 'settlements_press_tallies',
  'One row per tally and place: the authority, the period (period_from, period_to) and the quote in attrs; a weekly or half-year tally carries day precision at its first day and its last day in attrs. 2025 and 2026.',
  'A tally as one authority stated it, read from the press: the Commission''s months and the Ministry''s weeks are different methods and are never summed together.',
  'حصيلة كما أعلنتها جهة واحدة، مقروءة من الصحافة: أشهر الهيئة وأسابيع الوزارة منهجان مختلفان ولا يُجمعان.', false, false),
 ('settlements.trees_damaged_olive_stated', 'violence.settler',
  'Olive trees among the trees damaged in a period, as a Palestinian authority tallied it and the press printed it',
  'أشجار الزيتون من بين الأشجار المتضررة في فترة، كما عدّتها جهة فلسطينية وطبعتها الصحافة',
  'trees', 'flow', -1, 'month', 'governorate', 'generated', 'settlements_press_tallies',
  'The olive share of settlements.trees_damaged_stated, same rows and attrs; a tally that counts olive trees only (January 2026) appears here alone.',
  'A tally as one authority stated it, read from the press: the Commission''s months and the Ministry''s weeks are different methods and are never summed together.',
  'حصيلة كما أعلنتها جهة واحدة، مقروءة من الصحافة: أشهر الهيئة وأسابيع الوزارة منهجان مختلفان ولا يُجمعان.', true, false),
 ('aid.gaza.ceasefire_trucks_entered_cumulative', 'aid.access',
  'Gaza Strip: trucks that entered since the ceasefire of 10 October 2025, running total as the Government Media Office stated it (scope in attrs: aid only, or aid + commercial + fuel)',
  'قطاع غزة: الشاحنات التي دخلت منذ وقف إطلاق النار في 10 تشرين الأول 2025، مجموع تراكمي كما أعلنه المكتب الإعلامي الحكومي (النطاق في الخصائص: مساعدات فقط، أو مساعدات وتجارية ووقود)',
  'vehicles', 'cumulative', 1, 'day', 'region', 'generated', 'gaza_supply_press',
  'One row per statement, dated the day the count ran to. attrs.scope is "aid" (October 2025) or "all" (2026); the split into aid, commercial and fuel trucks is in attrs when the statement gives it. A running total: never summed across dates.',
  'A running total as the Gaza Government Media Office stated it, read from the press; the October 2025 count is aid trucks only and the 2026 counts include commercial and fuel trucks. Compare with aid.gaza.ceasefire_trucks_agreed_cumulative on the same day, never across dates.',
  'مجموع تراكمي كما أعلنه المكتب الإعلامي الحكومي في غزة، مقروء من الصحافة؛ عدّ تشرين الأول 2025 للمساعدات وحدها، وعدّ 2026 يشمل التجارية والوقود. يُقارن بالمتفق عليه في اليوم نفسه، لا عبر التواريخ.', false, false),
 ('aid.gaza.ceasefire_trucks_agreed_cumulative', 'aid.access',
  'Gaza Strip: trucks the ceasefire agreement provided for since 10 October 2025 (600 a day), running total as the Government Media Office stated it',
  'قطاع غزة: الشاحنات التي نصّ عليها اتفاق وقف إطلاق النار منذ 10 تشرين الأول 2025 (600 يوميًا)، مجموع تراكمي كما أعلنه المكتب الإعلامي الحكومي',
  'vehicles', 'cumulative', 1, 'day', 'region', 'generated', 'gaza_supply_press',
  'The denominator of the Media Office''s compliance figure: 600 × the days elapsed, as each statement printed it. Same rows as the entered count.',
  'The agreed figure as the Media Office stated it (600 a day since 10 October 2025); its ratio to the entered count on the same day is the Office''s compliance figure.',
  'الرقم المتفق عليه كما أعلنه المكتب (600 يوميًا منذ 10 تشرين الأول 2025)؛ نسبته إلى ما دخل في اليوم نفسه هي نسبة الالتزام التي يعلنها المكتب.', true, false),
 ('aid.gaza.aid_trucks_entered_day_stated', 'aid.access',
  'Gaza Strip: aid trucks that entered on one stated day, as the Government Media Office (or the outlet citing it) stated it',
  'قطاع غزة: شاحنات المساعدات التي دخلت في يوم مذكور، كما أعلنه المكتب الإعلامي الحكومي (أو الصحيفة الناقلة عنه)',
  'vehicles', 'flow', 1, 'day', 'region', 'generated', 'gaza_supply_press',
  'A handful of days (October 2025, April and May 2026); the day''s total with commercial trucks in attrs when the statement gives it. The UN''s daily offloaded counts (aid_un2720) are the series.',
  'A few stated days, not a daily series; the UN''s offloaded-truck counts are the daily series.',
  'أيام قليلة معلنة لا سلسلة يومية؛ عدّ الأمم المتحدة للشاحنات المفرَّغة هو السلسلة اليومية.', true, false),
 ('energy.gaza.cooking_gas_trucks_entered', 'energy.supply',
  'Gaza Strip: one cooking-gas shipment as the General Petroleum Authority announced it, in truckloads',
  'قطاع غزة: شحنة غاز طهي واحدة كما أعلنتها هيئة البترول العامة، بعدد الحمولات',
  'vehicles', 'flow', 1, 'day', 'region', 'generated', 'gaza_supply_press',
  'One row per announced shipment, 2 to 6 truckloads, May–September 2026; the quote in attrs. Shipments the press did not print are absent, so a month''s sum is a floor.',
  'Shipments as announced and printed, read from the press: a floor, not the month''s supply. The strip''s stated need (8,000 tonnes a month) is a cited figure.',
  'شحنات كما أُعلنت وطُبعت، مقروءة من الصحافة: حدّ أدنى لا إمداد الشهر. حاجة القطاع المعلنة (8,000 طن شهريًا) رقم مقتبس.', true, false)
ON CONFLICT (indicator) DO UPDATE
   SET concept_key = EXCLUDED.concept_key, name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar,
       canonical_unit = EXCLUDED.canonical_unit, measure_kind = EXCLUDED.measure_kind, polarity = EXCLUDED.polarity,
       grain = EXCLUDED.grain, place_grain = EXCLUDED.place_grain, status = EXCLUDED.status, source_spec = EXCLUDED.source_spec,
       notes = EXCLUDED.notes, serve_warning = EXCLUDED.serve_warning, serve_warning_ar = EXCLUDED.serve_warning_ar,
       ask_by_name = EXCLUDED.ask_by_name, projection = EXCLUDED.projection;

COMMIT;
