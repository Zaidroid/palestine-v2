-- 056 — nineteen copies of one view become nineteen rows
--
-- 049 wrote out nineteen views that differ only in a WHERE clause, and 051
-- had to hand-write a twentieth because water's rule is not
-- `v1_category = 'water'` — it is water's own datasets PLUS health's wsh_*
-- series, since one JMP fact lives in health's namespace and belongs on
-- water's door. That exception is the whole argument: the rules are DATA,
-- and one of them already refuses to fit the pattern.
--
-- At 21 categories a hand-written set is tedious. At the 40+ sources and new
-- families Wave A brings — energy, trade, environment — it is a migration
-- per category and a guaranteed drift between what the registry says a
-- category is and what its view selects.
--
-- So the rule becomes a row and ops/gen_category_views.py emits the views.
-- The generator REFUSES a rule it cannot parse (see its whitelist): a
-- domain_rule is reviewed SQL from a migration, never user input, and it is
-- still checked, because "it came from a trusted place" is how every
-- injection gets written.

CREATE TABLE IF NOT EXISTS category (
    key          text PRIMARY KEY,
    name_en      text NOT NULL,
    name_ar      text,
    domain_rule  text NOT NULL,
    active       boolean NOT NULL DEFAULT true,
    notes        text,
    created_at   timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE category IS
  'One row per servable category. domain_rule is the predicate over '
  'databank_serving that defines the category''s extent — usually '
  'v1_category = <key>, but water proves the general case is needed.';
COMMENT ON COLUMN category.domain_rule IS
  'A boolean SQL predicate over databank_serving columns. Validated against '
  'a whitelist by ops/gen_category_views.py before any view is created.';

-- Every category 049 wrote by hand, derived from what actually has rows.
INSERT INTO category (key, name_en, domain_rule, notes)
SELECT DISTINCT d.v1_category,
       initcap(replace(d.v1_category, '_', ' ')),
       format('v1_category = %L', d.v1_category),
       'ported from 049''s hand-written view'
FROM dataset d
WHERE d.v1_category IS NOT NULL
ON CONFLICT (key) DO NOTHING;

-- 051's exception, now a row rather than a migration. The comment that
-- justified it travels with it.
UPDATE category SET
    domain_rule = 'v1_category = ''water'' OR indicator LIKE ''health.wsh%''',
    name_ar = 'المياه',
    notes = 'Water''s extent is NOT its own datasets alone. The complete JMP '
            'WASH access series arrived inside v1_health_who and keeps its '
            'home namespace (health.wsh_*); one fact, one storage row, two '
            'category doors. This exception is why domain_rule is a rule and '
            'not a category name.'
 WHERE key = 'water';

-- Arabic labels for the categories that have them settled. The rest stay
-- NULL rather than machine-translated — a wrong Arabic label on a memorial
-- category is worse than none, and this is Zaid''s call, not the loader''s.
UPDATE category SET name_ar = v.ar FROM (VALUES
    ('casualties',   'الضحايا'),
    ('demolitions',  'عمليات الهدم'),
    ('refugees',     'اللاجئون'),
    ('prisoners',    'الأسرى'),
    ('education',    'التعليم'),
    ('health',       'الصحة'),
    ('historical',   'تاريخي'),
    ('land',         'الأرض'),
    ('settlements',  'المستوطنات'),
    ('aid_access',   'وصول المساعدات'),
    ('food',         'الغذاء'),
    ('economic',     'الاقتصاد'),
    ('culture',      'التراث'),
    ('connectivity', 'الاتصال'),
    ('conflict',     'النزاع'),
    ('funding',      'التمويل')
) AS v(key, ar) WHERE category.key = v.key;
