-- 097 — the road register becomes v2's own (2026-10-11).
--
-- Audit 2026-10-11, findings 01, 02 and 07. Which checkpoint a road message is
-- about was decided by v1's whitelist parser, inside the PoC, and v2 saw a
-- message only after that parser had let it through. Its names, its list of
-- names it could not place (20,268 of them, never promoted) and its "learned
-- vocabulary" lived in v1's SQLite. v2 held 11,030 aliases in place_alias, a
-- general gazetteer keyed one alias to one place across every kind, and 104
-- of them had ever been hit.
--
-- This gives the road register its own two tables and fills them from the day's
-- measurements, so that ingest/sources/roads.py (v2's own reader of the raw
-- messages) has a register to read. APPLYING THIS MIGRATION SWITCHES THAT READER
-- ON at the next two-minute tick (it looks for these tables); `ROADS_READER=off`
-- in .env switches it off again without touching anything here.
--
--   road_alias       a name the channels use for a road place: a spelling
--                    ("عين سينا" for عين سينيا), another name ("المدخل الشمالي
--                    لمدينة البيرة" for بيت ايل), or a weak name that counts only
--                    after a road word ("17"). One alias may serve two places.
--   road_candidate   a name written before a status that the register does not
--                    hold, counted as it recurs: v2's own list, for one human
--                    yes a week (ops/road_register.py). v1's table is not
--                    copied: its counts come from another parser, and the
--                    backfill recounts every message since 2026-07-31.
--   source.feeds_roads / home_place_id
--                    which sources are road channels, and the one place a
--                    channel is wholly about (the bridge's own channels).
--
-- What is NOT carried over from v1: its learned_vocab, all 28 rows of which are
-- place-name fragments recorded as statuses ("عورتا" = closed, "عين" = open).
--
-- THE REGISTER, CLEANED WITH WHAT WAS MEASURED
--   * 164 names and spellings from the audit: 80 spellings one letter or one space from
--     a registered name (96 found, 16 refused at the human look: عوريف is not
--     صوريف, بيت عوا is not بيت عور, ماشيه is a word), 83 other names read off
--     the messages and the roads gold.
--   * 426 names from v1's whitelist (known_checkpoints.json), so nothing v1's
--     matcher knew is unknown to v2's.
--   * 19 rows merged into the row they duplicate (082's procedure), and
--     4 sentences that v1 stored as places hidden without a merge.
--   * three sources that are no longer road sources set inactive, each with its
--     reason on the row, so the watchdog stops naming them every ten minutes.
--
-- Rollback (exact):
--   UPDATE place SET merged_into = NULL, servable = true,
--          quality_note = NULLIF(replace(quality_note, attrs->>'note_097', ''), ''),
--          attrs = attrs - 'merged_by' - 'aliases_moved_097' - 'note_097'
--    WHERE attrs->>'merged_by' = '097';
--   UPDATE place SET servable = true, quality_note = NULL, attrs = attrs - 'hidden_by'
--    WHERE attrs->>'hidden_by' = '097';
--   UPDATE state_observation SET place_id = (attrs->>'moved_from')::int,
--          attrs = attrs - 'moved_from' - 'moved_by' WHERE attrs->>'moved_by' = '097';
--   UPDATE source SET active = true, independence_note = NULL
--    WHERE key IN ('tg_almasshta', 'tg_areenablus', 'tg_palhubappfuel');
--   UPDATE source SET feeds_incidents = true WHERE feeds_roads;
--   ALTER TABLE source DROP COLUMN feeds_roads, DROP COLUMN home_place_id;
--   DROP TABLE road_candidate; DROP TABLE road_alias;
--   (rows the reader wrote: DELETE FROM state_observation WHERE attrs->>'reader' = 'v2';
--    DELETE FROM ingest_seen WHERE external_id LIKE 'road:%';)

-- 1. the register's own tables
CREATE TABLE IF NOT EXISTS road_alias (
    alias      text        NOT NULL,
    place_id   bigint      NOT NULL REFERENCES place(place_id),
    kind       text        NOT NULL CHECK (kind IN ('name', 'spelling', 'weak')),
    origin     text        NOT NULL,
    note       text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (alias, place_id)
);
COMMENT ON TABLE road_alias IS
  'Names the road channels use for a road place, beside place.name_ar/name_en and '
  'place_alias: spellings, other names, and weak names read only after a road word. '
  'Read by resolve/road_names.py; written by migrations and ops/road_register.py.';

CREATE TABLE IF NOT EXISTS road_candidate (
    name_norm  text        PRIMARY KEY,
    surface    text        NOT NULL,
    example    text        NOT NULL,
    mentions   integer     NOT NULL DEFAULT 0,
    channels   text[]      NOT NULL DEFAULT '{}',
    first_seen timestamptz NOT NULL,
    last_seen  timestamptz NOT NULL,
    status     text        NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending', 'alias', 'place', 'not_a_place')),
    place_id   bigint      REFERENCES place(place_id),
    decided_at timestamptz,
    decided_by text
);
COMMENT ON TABLE road_candidate IS
  'Names written before a status in a road message that the register does not hold, '
  'counted as they recur. Accrued by ingest/sources/roads.py; decided one at a time '
  'through ops/road_register.py (alias of a place, a new place, or not a place).';
CREATE INDEX IF NOT EXISTS road_candidate_pending_idx
    ON road_candidate (mentions DESC) WHERE status = 'pending';

-- 2. which sources are road channels
ALTER TABLE source ADD COLUMN IF NOT EXISTS feeds_roads boolean NOT NULL DEFAULT false;
ALTER TABLE source ADD COLUMN IF NOT EXISTS home_place_id bigint REFERENCES place(place_id);
COMMENT ON COLUMN source.feeds_roads IS
  'A road-conditions channel: its messages are read by ingest/sources/roads.py. Such a '
  'source never feeds the incident classifier (4,000 lines of road chat a day are not news).';
COMMENT ON COLUMN source.home_place_id IS
  'The one road place this channel is wholly about; a short message there that names '
  'no place is read as about it.';

UPDATE source SET feeds_roads = true, feeds_incidents = false
 WHERE key IN ('tg_a7walstreet', 'tg_ahwalaltareq', 'tg_ahwalaltorq', 'tg_ahwalaltreq', 'tg_ahwaltareq1', 'tg_ahwaltrkwhwagz_nablous', 'tg_aljanoop48', 'tg_aljesernews', 'tg_areenablus', 'tg_jisrrrr', 'tg_khbnews1', 'tg_peopleofhebron', 'tg_road_jehad', 'tg_roaddconditions', 'tg_rsdrasd', 'tg_almasshta');

UPDATE source s SET home_place_id = v.place_id
  FROM (VALUES
  ('tg_jisrrrr', 1792),
  ('tg_aljesernews', 1792),
  ('tg_khbnews1', 1792)
  ) AS v(key, place_id)
 WHERE s.key = v.key;

-- three that are road sources no longer (read at the publisher 2026-10-11)
UPDATE source s SET active = false, independence_note = v.why
  FROM (VALUES
  ('tg_almasshta', 'no longer a channel: t.me/almasshta resolves to a contact (read 2026-10-11); last report 2026-07-13'),
  ('tg_areenablus', 'stopped reporting roads on 2026-08-24; since 2026-09-07 it posts only a pointer to @hawajezaldefa and spam'),
  ('tg_palhubappfuel', 'the fuel cards stopped on 2026-10-03 19:38 UTC; the channel was renamed ''Palhub - احوال الطرق'' and is now a chat group')
  ) AS v(key, why)
 WHERE s.key = v.key;

-- 3. duplicates merge into the row they duplicate (082's procedure, verbatim)
CREATE TEMP TABLE m097 (loser bigint PRIMARY KEY, survivor bigint NOT NULL) ON COMMIT DROP;
INSERT INTO m097 VALUES
  (1788, 1521),
  (1554, 1639),
  (1519, 1828),
  (1572, 1489),
  (1583, 1532),
  (1761, 1660),
  (6865, 1498),
  (1744, 1578),
  (1735, 1464),
  (1830, 1741),
  (1740, 1596),
  (6874, 1759),
  (1575, 1633),
  (1820, 1821),
  (1640, 1631),
  (1676, 1617),
  (1506, 1492),
  (1503, 1597),
  (1658, 1473);

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM m097 m JOIN place p ON p.place_id = m.survivor
              WHERE p.merged_into IS NOT NULL OR NOT p.servable)
  THEN RAISE EXCEPTION '097: a survivor is merged or unservable'; END IF;
  IF EXISTS (SELECT 1 FROM m097 a JOIN m097 b ON a.survivor = b.loser)
  THEN RAISE EXCEPTION '097: a survivor is also a loser'; END IF;
END $$;

UPDATE place p
   SET attrs = COALESCE(p.attrs, '{}'::jsonb) || jsonb_build_object(
                 'merged_by', '097',
                 'note_097', ' · merged 097: duplicate of ' || m.survivor,
                 'aliases_moved_097', (SELECT COALESCE(jsonb_agg(a.alias_norm), '[]'::jsonb)
                                         FROM place_alias a WHERE a.place_id = p.place_id))
  FROM m097 m WHERE p.place_id = m.loser AND p.merged_into IS NULL;

UPDATE place p SET merged_into = m.survivor
  FROM m097 m WHERE p.merged_into = m.loser;

UPDATE place p
   SET merged_into = m.survivor, servable = false,
       quality_note = COALESCE(quality_note, '') || ' · merged 097: duplicate of ' || m.survivor
  FROM m097 m WHERE p.place_id = m.loser;

-- observations of the last two days (all the serving layer still reads) and beliefs
SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0;
UPDATE state_observation o
   SET place_id = m.survivor,
       attrs = COALESCE(o.attrs, '{}'::jsonb)
             || jsonb_build_object('moved_from', o.place_id, 'moved_by', '097')
  FROM m097 m
 WHERE o.place_id = m.loser AND o.observed_at >= now() - interval '2 days';

UPDATE state_current sc SET place_id = m.survivor
  FROM m097 m
 WHERE sc.place_id = m.loser
   AND NOT EXISTS (SELECT 1 FROM state_current c2
                    WHERE c2.place_id = m.survivor AND c2.state_kind = sc.state_kind
                      AND c2.direction IS NOT DISTINCT FROM sc.direction);
DELETE FROM state_current sc USING m097 m WHERE sc.place_id = m.loser;

DELETE FROM place_alias a USING m097 m
 WHERE a.place_id = m.loser
   AND EXISTS (SELECT 1 FROM place_alias b WHERE b.alias_norm = a.alias_norm AND b.place_id = m.survivor);
UPDATE place_alias a SET place_id = m.survivor FROM m097 m WHERE a.place_id = m.loser;

-- the board's wording follows the survivor, so the board's loader still finds it
UPDATE place s
   SET attrs = COALESCE(s.attrs, '{}'::jsonb)
             || jsonb_build_object('palhub_names',
                  (SELECT jsonb_agg(DISTINCT x) FROM jsonb_array_elements_text(
                     COALESCE(s.attrs->'palhub_names', '[]'::jsonb) || COALESCE(l.attrs->'palhub_names', '[]'::jsonb)) x))
  FROM m097 m, place l
 WHERE s.place_id = m.survivor AND l.place_id = m.loser AND l.attrs ? 'palhub_names';

-- 4. sentences v1 stored as places: hidden, kept, not merged (their few readings
--    are lines filed under the wrong thing)
UPDATE place p
   SET servable = false, quality_note = v.note,
       attrs = COALESCE(p.attrs, '{}'::jsonb) || jsonb_build_object('hidden_by', '097')
  FROM (VALUES
  (1591, 'بعد الدوار: a phrase, not a place'),
  (1577, 'من عين سينا لزعترة: a route, not a place'),
  (1505, 'للجنوب اندماج: a phrase, not a place'),
  (1791, 'سير: the word for traffic (كثافة سير), stored as a place named Tayasir')
  ) AS v(place_id, note)
 WHERE p.place_id = v.place_id AND p.merged_into IS NULL;
DELETE FROM state_current sc USING place p
 WHERE sc.place_id = p.place_id AND p.attrs->>'hidden_by' = '097';

-- 5. the names. A row whose place merged above lands on the survivor.
INSERT INTO road_alias (alias, place_id, kind, origin, note)
SELECT v.alias, COALESCE(p.merged_into, p.place_id), v.kind, v.origin, v.note
  FROM (VALUES
    ('عبن سينيا', 1462, 'spelling', 'audit-2026-10-11', '11 mentions; one letter from «عين سينيا»'),
    ('عين سنيا', 1462, 'spelling', 'audit-2026-10-11', '19 mentions; one letter from «عين سينيا»'),
    ('عين سين يا', 1462, 'spelling', 'audit-2026-10-11', '6 mentions; written as one word «عينسينيا»'),
    ('عين سينا', 1462, 'spelling', 'audit-2026-10-11', '778 mentions; one letter from «عين سينيا»'),
    ('عينا سينيا', 1462, 'name', 'audit-2026-10-11', NULL),
    ('بيرود سلواد', 1466, 'name', 'audit-2026-10-11', NULL),
    ('سلواد ويبرود', 1466, 'name', 'audit-2026-10-11', NULL),
    ('سلود يبرود', 1466, 'spelling', 'audit-2026-10-11', '33 mentions; one letter from «سلواد يبرود»'),
    ('يبرود', 1466, 'name', 'audit-2026-10-11', NULL),
    ('يبرود سلواد', 1466, 'name', 'audit-2026-10-11', NULL),
    ('يبرود وسلواد', 1466, 'name', 'audit-2026-10-11', NULL),
    ('عتاب', 1467, 'spelling', 'audit-2026-10-11', '24 mentions; one letter from «عناب»'),
    ('الصيرفي', 1469, 'name', 'audit-2026-10-11', NULL),
    ('دوار الصيرفي', 1469, 'name', 'audit-2026-10-11', NULL),
    ('عزريه', 1471, 'spelling', 'audit-2026-10-11', '16 mentions; one letter from «عيزريه»'),
    ('اودلا', 1472, 'name', 'audit-2026-10-11', NULL),
    ('اودله', 1472, 'name', 'audit-2026-10-11', NULL),
    ('جسر اودله', 1472, 'spelling', 'audit-2026-10-11', '6 mentions; one letter from «جسر اودلا»'),
    ('فرش الهوا', 1474, 'name', 'audit-2026-10-11', NULL),
    ('فرش هوا', 1474, 'spelling', 'audit-2026-10-11', '1479 mentions; one letter from «فرش هوي»'),
    ('عروتا', 1476, 'name', 'audit-2026-10-11', NULL),
    ('عورت', 1476, 'spelling', 'audit-2026-10-11', '11 mentions; one letter from «عورتا»'),
    ('عورته', 1476, 'spelling', 'audit-2026-10-11', '32 mentions; one letter from «عورتا»'),
    ('عبن شبلي', 1479, 'spelling', 'audit-2026-10-11', '8 mentions; one letter from «عين شبلي»'),
    ('عين شبله', 1479, 'spelling', 'audit-2026-10-11', '56 mentions; one letter from «عين شبلي»'),
    ('دير شوف', 1482, 'spelling', 'audit-2026-10-11', '15 mentions; one letter from «دير شرف»'),
    ('ديرشرف', 1482, 'spelling', 'audit-2026-10-11', '202 mentions; written as one word «ديرشرف»'),
    ('عش اغراب', 1488, 'spelling', 'audit-2026-10-11', '60 mentions; one letter from «عش غراب»'),
    ('زعترا', 1489, 'spelling', 'audit-2026-10-11', 'one letter from two registered names; chosen by hand'),
    ('اتسهار', 1490, 'spelling', 'audit-2026-10-11', '34 mentions; one letter from «يتسهار»'),
    ('ايتسهار', 1490, 'spelling', 'audit-2026-10-11', '5 mentions; one letter from «يتسهار»'),
    ('تسهار', 1490, 'spelling', 'audit-2026-10-11', '5 mentions; one letter from «يتسهار»'),
    ('سدة الفحص', 1499, 'name', 'audit-2026-10-11', NULL),
    ('مدخل الخليل الجنوبي الفحص', 1499, 'name', 'audit-2026-10-11', NULL),
    ('گرمه', 1500, 'spelling', 'audit-2026-10-11', '5 mentions; one letter from «كرمه»'),
    ('كونتنير', 1501, 'spelling', 'audit-2026-10-11', '5 mentions; one letter from «كونتير»'),
    ('كونتيتر', 1501, 'spelling', 'audit-2026-10-11', '11 mentions; one letter from «كونتينر»'),
    ('كونتينير', 1501, 'spelling', 'audit-2026-10-11', '43 mentions; one letter from «كونتينر»'),
    ('عطار', 1502, 'spelling', 'audit-2026-10-11', '7 mentions; one letter from «عطاره»'),
    ('ازعيم', 1504, 'spelling', 'audit-2026-10-11', '43 mentions; one letter from «زعيم»'),
    ('بني انعيم', 1508, 'spelling', 'audit-2026-10-11', '72 mentions; one letter from «بني نعيم»'),
    ('مربع', 1515, 'spelling', 'audit-2026-10-11', '10 mentions; one letter from «مربعه»'),
    ('ترمس عيا', 1517, 'spelling', 'audit-2026-10-11', '64 mentions; written as one word «ترمسعيا»'),
    ('ديرستيا', 1522, 'spelling', 'audit-2026-10-11', 'one letter from two registered names; chosen by hand'),
    ('مدخل ديرستيا', 1522, 'spelling', 'audit-2026-10-11', '198 mentions; one letter from «مدخل ديراستيا»'),
    ('راس حوره', 1533, 'spelling', 'audit-2026-10-11', '5 mentions; one letter from «راس جوره»'),
    ('برج عطارة', 1536, 'name', 'audit-2026-10-11', NULL),
    ('طلوع البرج', 1536, 'name', 'audit-2026-10-11', NULL),
    ('عطارة البرج', 1536, 'name', 'audit-2026-10-11', NULL),
    ('الباذان', 1569, 'name', 'audit-2026-10-11', NULL),
    ('باذان', 1569, 'spelling', 'audit-2026-10-11', '209 mentions; one letter from «بادان»'),
    ('طريق الباذان', 1569, 'name', 'audit-2026-10-11', NULL),
    ('واد الباذان', 1569, 'name', 'audit-2026-10-11', NULL),
    ('معرحات', 1570, 'spelling', 'audit-2026-10-11', '5 mentions; one letter from «معرجات»'),
    ('المدخل الشمالي البيرة', 1584, 'name', 'audit-2026-10-11', NULL),
    ('المدخل الشمالي للبيرة', 1584, 'name', 'audit-2026-10-11', NULL),
    ('المدخل الشمالي لمدينة البيرة', 1584, 'name', 'audit-2026-10-11', NULL),
    ('مدخل البيرة الشمالي', 1584, 'name', 'audit-2026-10-11', NULL),
    ('سلود', 1587, 'spelling', 'audit-2026-10-11', '9 mentions; one letter from «سلواد»'),
    ('قلنديه', 1589, 'spelling', 'audit-2026-10-11', '8 mentions; one letter from «قلنديا»'),
    ('شيلو وعيلي', 1596, 'spelling', 'audit-2026-10-11', '6 mentions; one letter from «شيلو عيلي»'),
    ('حاجز الهيئة', 1598, 'name', 'audit-2026-10-11', NULL),
    ('مخارج اريحا', 1598, 'name', 'audit-2026-10-11', NULL),
    ('مداخل اريحا', 1598, 'name', 'audit-2026-10-11', NULL),
    ('مداخل ومخارج اريحا', 1598, 'name', 'audit-2026-10-11', NULL),
    ('حلحلول', 1599, 'spelling', 'audit-2026-10-11', '8 mentions; one letter from «حلحول»'),
    ('عقبت حسنه', 1614, 'spelling', 'audit-2026-10-11', '6 mentions; one letter from «عقبه حسنه»'),
    ('عقبه حسنا', 1614, 'spelling', 'audit-2026-10-11', '10 mentions; one letter from «عقبه حسنه»'),
    ('ديرجرير', 1624, 'spelling', 'audit-2026-10-11', '5 mentions; written as one word «ديرجرير»'),
    ('اشارات عيون حرميه', 1633, 'spelling', 'audit-2026-10-11', '6 mentions; one letter from «اشارات عيون حراميه»'),
    ('عيون الحرمية', 1633, 'name', 'audit-2026-10-11', NULL),
    ('عيون حرميه', 1633, 'spelling', 'audit-2026-10-11', '52 mentions; one letter from «عيون حراميه»'),
    ('جماعبن', 1634, 'spelling', 'audit-2026-10-11', '5 mentions; one letter from «جماعين»'),
    ('زعترة حوارة', 1636, 'name', 'audit-2026-10-11', NULL),
    ('مرده', 1637, 'spelling', 'audit-2026-10-11', '9 mentions; one letter from «مردا»'),
    ('مردى', 1637, 'name', 'audit-2026-10-11', NULL),
    ('مردي', 1637, 'spelling', 'audit-2026-10-11', '43 mentions; one letter from «مردا»'),
    ('دير اب مشعل', 1642, 'spelling', 'audit-2026-10-11', '45 mentions; one letter from «دير ابو مشعل»'),
    ('رمزون شيلو', 1644, 'name', 'audit-2026-10-11', NULL),
    ('رمزونات شيلو', 1644, 'name', 'audit-2026-10-11', NULL),
    ('شيلو', 1644, 'name', 'audit-2026-10-11', NULL),
    ('اشارات ارئيل', 1645, 'name', 'audit-2026-10-11', NULL),
    ('اشارة ارئيل', 1645, 'name', 'audit-2026-10-11', NULL),
    ('دوار ارئيل', 1645, 'name', 'audit-2026-10-11', NULL),
    ('دوار ارايل', 1645, 'name', 'audit-2026-10-11', NULL),
    ('دوار اريئيل', 1645, 'name', 'audit-2026-10-11', NULL),
    ('دوار اريل', 1645, 'name', 'audit-2026-10-11', NULL),
    ('مفرق ارئيل', 1645, 'name', 'audit-2026-10-11', NULL),
    ('الفندق مدخل حجة', 1646, 'name', 'audit-2026-10-11', NULL),
    ('مدخل حجة', 1646, 'name', 'audit-2026-10-11', NULL),
    ('بيت عنون', 1663, 'spelling', 'audit-2026-10-11', '10 mentions; one letter from «بيت عينون»'),
    ('دير انظام', 1664, 'spelling', 'audit-2026-10-11', '5 mentions; one letter from «دير نظام»'),
    ('اشاره علي', 1666, 'spelling', 'audit-2026-10-11', '9 mentions; one letter from «اشاره عيلي»'),
    ('رمزون عيلي', 1666, 'name', 'audit-2026-10-11', NULL),
    ('عيلي', 1666, 'name', 'audit-2026-10-11', NULL),
    ('شويكي', 1683, 'spelling', 'audit-2026-10-11', '81 mentions; one letter from «شويكه»'),
    ('حمره', 1693, 'spelling', 'audit-2026-10-11', '30 mentions; one letter from «حمرا»'),
    ('بيرزيت', 1721, 'spelling', 'audit-2026-10-11', '84 mentions; written as one word «بيرزيت»'),
    ('عيسويه', 1728, 'spelling', 'audit-2026-10-11', '8 mentions; one letter from «عيساويه»'),
    ('البن الشرقية', 1739, 'name', 'audit-2026-10-11', NULL),
    ('اللبن الشرقي', 1739, 'name', 'audit-2026-10-11', NULL),
    ('معالي افرايم', 1741, 'name', 'audit-2026-10-11', NULL),
    ('معالي فرايم', 1741, 'spelling', 'audit-2026-10-11', '32 mentions; one letter from «معالي افرايم»'),
    ('معاليه فرايم', 1741, 'spelling', 'audit-2026-10-11', '9 mentions; one letter from «معاليه افرايم»'),
    ('معلي افرايم', 1741, 'spelling', 'audit-2026-10-11', '161 mentions; one letter from «معالي افرايم»'),
    ('دوار قدوميم', 1742, 'spelling', 'audit-2026-10-11', '15 mentions; one letter from «دوار كدوميم»'),
    ('عصيرة المساكن', 1753, 'name', 'audit-2026-10-11', NULL),
    ('الطيبة كرملو', 1759, 'name', 'audit-2026-10-11', NULL),
    ('طيبه كارملو', 1759, 'spelling', 'audit-2026-10-11', '5 mentions; one letter from «طيبه كارميلو»'),
    ('طيبه كراملو', 1759, 'spelling', 'audit-2026-10-11', '40 mentions; one letter from «طيبه كراميلو»'),
    ('طيبه كرميلو', 1759, 'spelling', 'audit-2026-10-11', '60 mentions; one letter from «طيبه كراميلو»'),
    ('كارميلو', 1759, 'name', 'audit-2026-10-11', NULL),
    ('كراملو', 1759, 'spelling', 'audit-2026-10-11', '20 mentions; one letter from «كراميلو»'),
    ('كراميلو', 1759, 'name', 'audit-2026-10-11', NULL),
    ('كرملو', 1759, 'name', 'audit-2026-10-11', NULL),
    ('كرملو الطيبة', 1759, 'name', 'audit-2026-10-11', NULL),
    ('كرملو طيبه', 1759, 'spelling', 'audit-2026-10-11', '48 mentions; one letter from «كرميلو طيبه»'),
    ('كرميلو', 1759, 'spelling', 'audit-2026-10-11', '64 mentions; one letter from «كراميلو»'),
    ('كفرعقب', 1760, 'spelling', 'audit-2026-10-11', '13 mentions; written as one word «كفرعقب»'),
    ('نبي لياس', 1762, 'spelling', 'audit-2026-10-11', '8 mentions; one letter from «نبي ياس»'),
    ('قلقيله', 1764, 'spelling', 'audit-2026-10-11', '6 mentions; one letter from «قلقيليه»'),
    ('مدخل قلقيلية الشرقي', 1764, 'name', 'audit-2026-10-11', NULL),
    ('اريحا dco', 1765, 'name', 'audit-2026-10-11', NULL),
    ('اريحا dso', 1765, 'spelling', 'audit-2026-10-11', '13 mentions; one letter from «اريحا dco»'),
    ('اريحا الجنوبي', 1765, 'name', 'audit-2026-10-11', NULL),
    ('مدخل اريحا الجنوبي', 1765, 'name', 'audit-2026-10-11', NULL),
    ('شافي شامرون', 1767, 'spelling', 'audit-2026-10-11', '5 mentions; one letter from «شافي شمرون»'),
    ('شافي شومرون', 1767, 'spelling', 'audit-2026-10-11', '73 mentions; one letter from «شافي شمرون»'),
    ('دوار معاليه ادوميم', 1769, 'spelling', 'audit-2026-10-11', '5 mentions; one letter from «دوار معالي ادوميم»'),
    ('دوار معلي ادوميم', 1769, 'spelling', 'audit-2026-10-11', '5 mentions; one letter from «دوار معالي ادوميم»'),
    ('معالي ادميم', 1769, 'spelling', 'audit-2026-10-11', '10 mentions; one letter from «معالي ادوميم»'),
    ('معالي ادوميم', 1769, 'name', 'audit-2026-10-11', NULL),
    ('معاليه ادوميم', 1769, 'spelling', 'audit-2026-10-11', '86 mentions; one letter from «معالي ادوميم»'),
    ('معلي ادوميم', 1769, 'spelling', 'audit-2026-10-11', '43 mentions; one letter from «معالي ادوميم»'),
    ('قراوة', 1770, 'name', 'audit-2026-10-11', NULL),
    ('جسر الاردن', 1792, 'name', 'audit-2026-10-11', NULL),
    ('جسر الكرامة', 1792, 'name', 'audit-2026-10-11', NULL),
    ('جسر اللنبي', 1792, 'name', 'audit-2026-10-11', NULL),
    ('معبر الكرامة', 1792, 'name', 'audit-2026-10-11', NULL),
    ('معبر اللنبي', 1792, 'name', 'audit-2026-10-11', NULL),
    ('برقا', 1799, 'spelling', 'audit-2026-10-11', '642 mentions; one letter from «برقه»'),
    ('واد قانا', 1826, 'name', 'audit-2026-10-11', NULL),
    ('واد كانا', 1826, 'spelling', 'audit-2026-10-11', '239 mentions; one letter from «واد قانا»'),
    ('17', 6853, 'weak', 'audit-2026-10-11', 'a bare number: read only after a road word or at the start of a line'),
    ('17 عصيرة', 6853, 'name', 'audit-2026-10-11', NULL),
    ('ال 17', 6853, 'name', 'audit-2026-10-11', NULL),
    ('حاجز 17', 6853, 'name', 'audit-2026-10-11', NULL),
    ('حاجز ال 17', 6853, 'name', 'audit-2026-10-11', NULL),
    ('طريق 17', 6853, 'name', 'audit-2026-10-11', NULL),
    ('مفرق 17', 6853, 'name', 'audit-2026-10-11', NULL),
    ('شبتين', 6857, 'name', 'audit-2026-10-11', NULL),
    ('مدخل شبتين', 6857, 'name', 'audit-2026-10-11', NULL),
    ('ام شقان', 6860, 'spelling', 'audit-2026-10-11', '6 mentions; one letter from «ام شقحان»'),
    ('بوابه ديرعمار', 6861, 'spelling', 'audit-2026-10-11', '7 mentions; written as one word «بوابهديرعمار»'),
    ('دير عمار', 6861, 'name', 'audit-2026-10-11', NULL),
    ('مدخل مردا الشرقي', 6863, 'name', 'audit-2026-10-11', NULL),
    ('مدخل مرده الشرقي', 6863, 'name', 'audit-2026-10-11', NULL),
    ('مدخل مردى الشرقي', 6863, 'name', 'audit-2026-10-11', NULL),
    ('دوار مخماس', 6864, 'name', 'audit-2026-10-11', NULL),
    ('مدخل اللدائن', 6871, 'name', 'audit-2026-10-11', NULL),
    ('دير دبوان', 6876, 'name', 'audit-2026-10-11', NULL),
    ('مجدل بني فضل', 6877, 'spelling', 'audit-2026-10-11', '5 mentions; one letter from «مجدل بني فاضل»'),
    ('شقبا', 6878, 'name', 'audit-2026-10-11', NULL),
    ('مدخل شقبا', 6878, 'name', 'audit-2026-10-11', NULL)
  ) AS v(alias, place_id, kind, origin, note)
  JOIN place p ON p.place_id = v.place_id
ON CONFLICT (alias, place_id) DO NOTHING;

-- v1's whitelist, whole
INSERT INTO road_alias (alias, place_id, kind, origin, note)
SELECT v.alias, COALESCE(p.merged_into, p.place_id), v.kind, v.origin, v.note
  FROM (VALUES
    ('عين سينيا', 1462, 'name', 'v1-whitelist', NULL),
    ('عين_سنيا', 1462, 'name', 'v1-whitelist', NULL),
    ('عين_سينا', 1462, 'name', 'v1-whitelist', NULL),
    ('عين_سينيا', 1462, 'name', 'v1-whitelist', NULL),
    ('مراح رباح', 1464, 'name', 'v1-whitelist', NULL),
    ('مراح رياح', 1464, 'name', 'v1-whitelist', NULL),
    ('مراح_رباح', 1464, 'name', 'v1-whitelist', NULL),
    ('مراح_رياح', 1464, 'name', 'v1-whitelist', NULL),
    ('جبع', 1465, 'name', 'v1-whitelist', NULL),
    ('سلواد يبرود', 1466, 'name', 'v1-whitelist', NULL),
    ('سلواد_يبرود', 1466, 'name', 'v1-whitelist', NULL),
    ('عناب', 1467, 'name', 'v1-whitelist', NULL),
    ('العيزرية', 1471, 'name', 'v1-whitelist', NULL),
    ('العيزريه', 1471, 'name', 'v1-whitelist', NULL),
    ('جسر اودلا', 1472, 'name', 'v1-whitelist', NULL),
    ('جسر_اودلا', 1472, 'name', 'v1-whitelist', NULL),
    ('النبي صالح', 1473, 'name', 'v1-whitelist', NULL),
    ('النبي_صالح', 1473, 'name', 'v1-whitelist', NULL),
    ('بوابة النبي صالح', 1473, 'name', 'v1-whitelist', NULL),
    ('بوابه_النبي_صالح', 1473, 'name', 'v1-whitelist', NULL),
    ('فرش الهوى', 1474, 'name', 'v1-whitelist', NULL),
    ('فرش_الهوا', 1474, 'name', 'v1-whitelist', NULL),
    ('فرش_الهوي', 1474, 'name', 'v1-whitelist', NULL),
    ('خربثا', 1475, 'name', 'v1-whitelist', NULL),
    ('خربثا المصباح', 1475, 'name', 'v1-whitelist', NULL),
    ('عورتا', 1476, 'name', 'v1-whitelist', NULL),
    ('زيف يطا', 1477, 'name', 'v1-whitelist', NULL),
    ('زيف_يطا', 1477, 'name', 'v1-whitelist', NULL),
    ('عين شبلي', 1479, 'name', 'v1-whitelist', NULL),
    ('عين_شبلي', 1479, 'name', 'v1-whitelist', NULL),
    ('صرة', 1480, 'name', 'v1-whitelist', NULL),
    ('صره', 1480, 'name', 'v1-whitelist', NULL),
    ('دير شرف', 1482, 'name', 'v1-whitelist', NULL),
    ('دير_شرف', 1482, 'name', 'v1-whitelist', NULL),
    ('جورة الشمعة', 1483, 'name', 'v1-whitelist', NULL),
    ('جوره_الشمعه', 1483, 'name', 'v1-whitelist', NULL),
    ('المنشية', 1484, 'name', 'v1-whitelist', NULL),
    ('المنشيه', 1484, 'name', 'v1-whitelist', NULL),
    ('دوار طقوع', 1485, 'name', 'v1-whitelist', NULL),
    ('دوار_تقوع', 1485, 'name', 'v1-whitelist', NULL),
    ('دوار_طقوع', 1485, 'name', 'v1-whitelist', NULL),
    ('تياسير', 1486, 'name', 'v1-whitelist', NULL),
    ('روابي', 1487, 'name', 'v1-whitelist', NULL),
    ('عش غراب', 1488, 'name', 'v1-whitelist', NULL),
    ('عش_الغراب', 1488, 'name', 'v1-whitelist', NULL),
    ('عش_غراب', 1488, 'name', 'v1-whitelist', NULL),
    ('زعترة', 1489, 'name', 'v1-whitelist', NULL),
    ('زعتره', 1489, 'name', 'v1-whitelist', NULL),
    ('خط يتساهر', 1490, 'name', 'v1-whitelist', NULL),
    ('يتساهر', 1490, 'name', 'v1-whitelist', NULL),
    ('يتسهار', 1490, 'name', 'v1-whitelist', NULL),
    ('حومش', 1491, 'name', 'v1-whitelist', NULL),
    ('حوميش', 1491, 'name', 'v1-whitelist', NULL),
    ('بزاريا', 1492, 'name', 'v1-whitelist', NULL),
    ('مدخل بزاريا', 1492, 'name', 'v1-whitelist', NULL),
    ('مدخل_بزاريا', 1492, 'name', 'v1-whitelist', NULL),
    ('دورا', 1495, 'name', 'v1-whitelist', NULL),
    ('النشاش', 1496, 'name', 'v1-whitelist', NULL),
    ('خلة المي', 1498, 'name', 'v1-whitelist', NULL),
    ('خله_المي', 1498, 'name', 'v1-whitelist', NULL),
    ('الفحص', 1499, 'name', 'v1-whitelist', NULL),
    ('كرمة', 1500, 'name', 'v1-whitelist', NULL),
    ('كرمه', 1500, 'name', 'v1-whitelist', NULL),
    ('الكنتينر', 1501, 'name', 'v1-whitelist', NULL),
    ('الكونتير', 1501, 'name', 'v1-whitelist', NULL),
    ('الكونتينر', 1501, 'name', 'v1-whitelist', NULL),
    ('كونتينر', 1501, 'name', 'v1-whitelist', NULL),
    ('عطارة', 1502, 'name', 'v1-whitelist', NULL),
    ('عطاره', 1502, 'name', 'v1-whitelist', NULL),
    ('الزعيم', 1504, 'name', 'v1-whitelist', NULL),
    ('حارس', 1507, 'name', 'v1-whitelist', NULL),
    ('بني نعيم', 1508, 'name', 'v1-whitelist', NULL),
    ('بني_نعيم', 1508, 'name', 'v1-whitelist', NULL),
    ('بيت ليد', 1510, 'name', 'v1-whitelist', NULL),
    ('بيت_ليد', 1510, 'name', 'v1-whitelist', NULL),
    ('رامين', 1511, 'name', 'v1-whitelist', NULL),
    ('جبارة', 1512, 'name', 'v1-whitelist', NULL),
    ('جباره', 1512, 'name', 'v1-whitelist', NULL),
    ('اماتين', 1514, 'name', 'v1-whitelist', NULL),
    ('المربع', 1515, 'name', 'v1-whitelist', NULL),
    ('المربعة', 1515, 'name', 'v1-whitelist', NULL),
    ('المربعه', 1515, 'name', 'v1-whitelist', NULL),
    ('ترمسعيا', 1517, 'name', 'v1-whitelist', NULL),
    ('دير بلوط', 1518, 'name', 'v1-whitelist', NULL),
    ('ديربلوط', 1518, 'name', 'v1-whitelist', NULL),
    ('سدة كفرالديك', 1520, 'name', 'v1-whitelist', NULL),
    ('كفر الديك', 1520, 'name', 'v1-whitelist', NULL),
    ('كفر_الديك', 1520, 'name', 'v1-whitelist', NULL),
    ('الزاوية', 1521, 'name', 'v1-whitelist', NULL),
    ('جسر الزاوية', 1521, 'name', 'v1-whitelist', NULL),
    ('النفق', 1526, 'name', 'v1-whitelist', NULL),
    ('حاجز النفق', 1526, 'name', 'v1-whitelist', NULL),
    ('سعير واد الشرق', 1528, 'name', 'v1-whitelist', NULL),
    ('سعير_واد_الشرق', 1528, 'name', 'v1-whitelist', NULL),
    ('البنانا', 1531, 'name', 'v1-whitelist', NULL),
    ('سلفيت الشمالي', 1532, 'name', 'v1-whitelist', NULL),
    ('سلفيت_الشمالي', 1532, 'name', 'v1-whitelist', NULL),
    ('رأس الجورة', 1533, 'name', 'v1-whitelist', NULL),
    ('راس_الجوره', 1533, 'name', 'v1-whitelist', NULL),
    ('جوريش', 1534, 'name', 'v1-whitelist', NULL),
    ('عطارة طلوع البرج', 1536, 'name', 'v1-whitelist', NULL),
    ('عطاره_طلوع_البرج', 1536, 'name', 'v1-whitelist', NULL),
    ('يتما', 1539, 'name', 'v1-whitelist', NULL),
    ('حاجز حزما', 1542, 'name', 'v1-whitelist', NULL),
    ('حزما', 1542, 'name', 'v1-whitelist', NULL),
    ('حزمه', 1542, 'name', 'v1-whitelist', NULL),
    ('الساوية', 1543, 'name', 'v1-whitelist', NULL),
    ('الساويه', 1543, 'name', 'v1-whitelist', NULL),
    ('سنجل', 1546, 'name', 'v1-whitelist', NULL),
    ('زواتا', 1550, 'name', 'v1-whitelist', NULL),
    ('طريق زواتا اتجاهين', 1550, 'name', 'v1-whitelist', NULL),
    ('بوابه القبلان اتجاهين', 1558, 'name', 'v1-whitelist', NULL),
    ('قبلان', 1558, 'name', 'v1-whitelist', NULL),
    ('جناتا تل الربيع', 1564, 'name', 'v1-whitelist', NULL),
    ('جناتا_تل_الربيع', 1564, 'name', 'v1-whitelist', NULL),
    ('العبيدية', 1566, 'name', 'v1-whitelist', NULL),
    ('الجلزون', 1568, 'name', 'v1-whitelist', NULL),
    ('البادان', 1569, 'name', 'v1-whitelist', NULL),
    ('وادي البادان', 1569, 'name', 'v1-whitelist', NULL),
    ('المعرجات', 1570, 'name', 'v1-whitelist', NULL),
    ('الفوار', 1576, 'name', 'v1-whitelist', NULL),
    ('واد السمن', 1578, 'name', 'v1-whitelist', NULL),
    ('واد_السمن', 1578, 'name', 'v1-whitelist', NULL),
    ('وادي السمن', 1578, 'name', 'v1-whitelist', NULL),
    ('النبي يونس', 1582, 'name', 'v1-whitelist', NULL),
    ('النبي_يونس', 1582, 'name', 'v1-whitelist', NULL),
    ('بيت ايل', 1584, 'name', 'v1-whitelist', NULL),
    ('بيت_ايل', 1584, 'name', 'v1-whitelist', NULL),
    ('بني زيد', 1586, 'name', 'v1-whitelist', NULL),
    ('مدخل بني زيد', 1586, 'name', 'v1-whitelist', NULL),
    ('سلواد', 1587, 'name', 'v1-whitelist', NULL),
    ('قلنديا', 1589, 'name', 'v1-whitelist', NULL),
    ('اشارات زعترة', 1594, 'name', 'v1-whitelist', NULL),
    ('اشارات_زعتره', 1594, 'name', 'v1-whitelist', NULL),
    ('شيلو', 1596, 'name', 'v1-whitelist', NULL),
    ('شيلو عيلي', 1596, 'name', 'v1-whitelist', NULL),
    ('شيلو_عيلي', 1596, 'name', 'v1-whitelist', NULL),
    ('شيلو_وعيلي', 1596, 'name', 'v1-whitelist', NULL),
    ('عيلي', 1596, 'name', 'v1-whitelist', NULL),
    ('عيلي - شيلو', 1596, 'name', 'v1-whitelist', NULL),
    ('عيلي شيلو', 1596, 'name', 'v1-whitelist', NULL),
    ('بوابة بورين', 1597, 'name', 'v1-whitelist', NULL),
    ('بوابه_بورين', 1597, 'name', 'v1-whitelist', NULL),
    ('بورين', 1597, 'name', 'v1-whitelist', NULL),
    ('حلحول', 1599, 'name', 'v1-whitelist', NULL),
    ('سعير', 1600, 'name', 'v1-whitelist', NULL),
    ('ترقوميا المصانع', 1605, 'name', 'v1-whitelist', NULL),
    ('ترقوميا_المصانع', 1605, 'name', 'v1-whitelist', NULL),
    ('بوابة دورا', 1606, 'name', 'v1-whitelist', NULL),
    ('بوابه_دورا', 1606, 'name', 'v1-whitelist', NULL),
    ('عابود', 1608, 'name', 'v1-whitelist', NULL),
    ('تقوع', 1609, 'name', 'v1-whitelist', NULL),
    ('كفل حارس', 1610, 'name', 'v1-whitelist', NULL),
    ('كفل_حارس', 1610, 'name', 'v1-whitelist', NULL),
    ('الفندق', 1611, 'name', 'v1-whitelist', NULL),
    ('خط يتساهر', 1612, 'name', 'v1-whitelist', NULL),
    ('خط يتسهار', 1612, 'name', 'v1-whitelist', NULL),
    ('خط_يتسهار', 1612, 'name', 'v1-whitelist', NULL),
    ('يتساهر', 1612, 'name', 'v1-whitelist', NULL),
    ('الخضر', 1613, 'name', 'v1-whitelist', NULL),
    ('عقبة حسنة', 1614, 'name', 'v1-whitelist', NULL),
    ('عقبه_حسنه', 1614, 'name', 'v1-whitelist', NULL),
    ('حلميش', 1615, 'name', 'v1-whitelist', NULL),
    ('بيت فوريك', 1616, 'name', 'v1-whitelist', NULL),
    ('بيت_فوريك', 1616, 'name', 'v1-whitelist', NULL),
    ('بوابة عزون', 1617, 'name', 'v1-whitelist', NULL),
    ('بوابه_عزون', 1617, 'name', 'v1-whitelist', NULL),
    ('عزون', 1617, 'name', 'v1-whitelist', NULL),
    ('عطارة البلد', 1618, 'name', 'v1-whitelist', NULL),
    ('عطاره_البلد', 1618, 'name', 'v1-whitelist', NULL),
    ('قراوة بديا', 1619, 'name', 'v1-whitelist', NULL),
    ('قراوه_بديا', 1619, 'name', 'v1-whitelist', NULL),
    ('دير جرير', 1624, 'name', 'v1-whitelist', NULL),
    ('إفرات', 1625, 'name', 'v1-whitelist', NULL),
    ('افرات', 1625, 'name', 'v1-whitelist', NULL),
    ('عين افرات', 1625, 'name', 'v1-whitelist', NULL),
    ('جوش عصيون', 1626, 'name', 'v1-whitelist', NULL),
    ('عصيون', 1626, 'name', 'v1-whitelist', NULL),
    ('مفرق عصيون', 1626, 'name', 'v1-whitelist', NULL),
    ('حوارة', 1630, 'name', 'v1-whitelist', NULL),
    ('حواره', 1630, 'name', 'v1-whitelist', NULL),
    ('بوابة بيتا', 1631, 'name', 'v1-whitelist', NULL),
    ('بوابه_بيتا', 1631, 'name', 'v1-whitelist', NULL),
    ('بيتا', 1631, 'name', 'v1-whitelist', NULL),
    ('عقربا', 1632, 'name', 'v1-whitelist', NULL),
    ('اشارات عيون الحرامية', 1633, 'name', 'v1-whitelist', NULL),
    ('اشارات_عيون_الحراميه', 1633, 'name', 'v1-whitelist', NULL),
    ('عيون الحرامية', 1633, 'name', 'v1-whitelist', NULL),
    ('عيون الحراميه', 1633, 'name', 'v1-whitelist', NULL),
    ('عيون_الحراميه', 1633, 'name', 'v1-whitelist', NULL),
    ('جماعين', 1634, 'name', 'v1-whitelist', NULL),
    ('حوارة تحت الجسر', 1635, 'name', 'v1-whitelist', NULL),
    ('حواره_تحت_الجسر', 1635, 'name', 'v1-whitelist', NULL),
    ('حوارة زعترة', 1636, 'name', 'v1-whitelist', NULL),
    ('حواره_زعتره', 1636, 'name', 'v1-whitelist', NULL),
    ('مردا', 1637, 'name', 'v1-whitelist', NULL),
    ('مرردا', 1637, 'name', 'v1-whitelist', NULL),
    ('التفافي حوارة', 1638, 'name', 'v1-whitelist', NULL),
    ('التفافي_حواره', 1638, 'name', 'v1-whitelist', NULL),
    ('بوابة حوارة', 1639, 'name', 'v1-whitelist', NULL),
    ('بوابه_حواره', 1639, 'name', 'v1-whitelist', NULL),
    ('دير أبو مشعل', 1642, 'name', 'v1-whitelist', NULL),
    ('دير_ابو_مشعل', 1642, 'name', 'v1-whitelist', NULL),
    ('اشارات شيلو', 1644, 'name', 'v1-whitelist', NULL),
    ('اشارات_شيلو', 1644, 'name', 'v1-whitelist', NULL),
    ('اشارات ارائيل', 1645, 'name', 'v1-whitelist', NULL),
    ('اشارات_ارائيل', 1645, 'name', 'v1-whitelist', NULL),
    ('حجة الفندق', 1646, 'name', 'v1-whitelist', NULL),
    ('حجه_الفندق', 1646, 'name', 'v1-whitelist', NULL),
    ('ترقوميا', 1647, 'name', 'v1-whitelist', NULL),
    ('دوار البلوطة', 1648, 'name', 'v1-whitelist', NULL),
    ('دوار_البلوطه', 1648, 'name', 'v1-whitelist', NULL),
    ('جسر حلحول', 1649, 'name', 'v1-whitelist', NULL),
    ('جسر_حلحول', 1649, 'name', 'v1-whitelist', NULL),
    ('بتما قبلان', 1650, 'name', 'v1-whitelist', NULL),
    ('بتما_قبلان', 1650, 'name', 'v1-whitelist', NULL),
    ('شقبا شبتين', 1651, 'name', 'v1-whitelist', NULL),
    ('شقبا_شبتبن', 1651, 'name', 'v1-whitelist', NULL),
    ('شقبا_شبتين', 1651, 'name', 'v1-whitelist', NULL),
    ('الزعتري', 1652, 'name', 'v1-whitelist', NULL),
    ('حسكا', 1653, 'name', 'v1-whitelist', NULL),
    ('راس بيت جالا', 1654, 'name', 'v1-whitelist', NULL),
    ('راس_بيت_جالا', 1654, 'name', 'v1-whitelist', NULL),
    ('تحت جسر بيت كاحل', 1655, 'name', 'v1-whitelist', NULL),
    ('تحت_جسر_بيت_كاحل', 1655, 'name', 'v1-whitelist', NULL),
    ('بيت امر الكلية', 1656, 'name', 'v1-whitelist', NULL),
    ('بيت_امر_الكليه', 1656, 'name', 'v1-whitelist', NULL),
    ('مراح معلا', 1659, 'name', 'v1-whitelist', NULL),
    ('مراح_معلا', 1659, 'name', 'v1-whitelist', NULL),
    ('ام السلمونا', 1660, 'name', 'v1-whitelist', NULL),
    ('ام سلمونه', 1660, 'name', 'v1-whitelist', NULL),
    ('ام_السلمونا', 1660, 'name', 'v1-whitelist', NULL),
    ('كوربة صايل', 1661, 'name', 'v1-whitelist', NULL),
    ('كوربه_صايل', 1661, 'name', 'v1-whitelist', NULL),
    ('العروب', 1662, 'name', 'v1-whitelist', NULL),
    ('بيت عينون', 1663, 'name', 'v1-whitelist', NULL),
    ('بيت_عينون', 1663, 'name', 'v1-whitelist', NULL),
    ('دير نظام', 1664, 'name', 'v1-whitelist', NULL),
    ('دير_نظام', 1664, 'name', 'v1-whitelist', NULL),
    ('بيت جالا', 1665, 'name', 'v1-whitelist', NULL),
    ('بيت_جالا', 1665, 'name', 'v1-whitelist', NULL),
    ('ب��ت_جالا', 1665, 'name', 'v1-whitelist', NULL),
    ('اشارات عيلي', 1666, 'name', 'v1-whitelist', NULL),
    ('اشارات_عيلي', 1666, 'name', 'v1-whitelist', NULL),
    ('سدة بديا قراوة', 1667, 'name', 'v1-whitelist', NULL),
    ('سده_بديا_قراوه', 1667, 'name', 'v1-whitelist', NULL),
    ('الكسارة', 1668, 'name', 'v1-whitelist', NULL),
    ('الكساره', 1668, 'name', 'v1-whitelist', NULL),
    ('اذنا', 1669, 'name', 'v1-whitelist', NULL),
    ('الهجرة', 1670, 'name', 'v1-whitelist', NULL),
    ('الهجره', 1670, 'name', 'v1-whitelist', NULL),
    ('بيت امر', 1671, 'name', 'v1-whitelist', NULL),
    ('بيت_امر', 1671, 'name', 'v1-whitelist', NULL),
    ('دخلة ولاد عرفات', 1672, 'name', 'v1-whitelist', NULL),
    ('دخله_ولاد_عرفات', 1672, 'name', 'v1-whitelist', NULL),
    ('اشارات 35', 1673, 'name', 'v1-whitelist', NULL),
    ('اشارات_35', 1673, 'name', 'v1-whitelist', NULL),
    ('بيتونيا', 1674, 'name', 'v1-whitelist', NULL),
    ('DCO', 1675, 'name', 'v1-whitelist', NULL),
    ('دي_سي_او', 1675, 'name', 'v1-whitelist', NULL),
    ('عتيل', 1677, 'name', 'v1-whitelist', NULL),
    ('مخيم_نور_شمس', 1678, 'name', 'v1-whitelist', NULL),
    ('نور شمس', 1678, 'name', 'v1-whitelist', NULL),
    ('نور_شمس', 1678, 'name', 'v1-whitelist', NULL),
    ('عنبتا', 1679, 'name', 'v1-whitelist', NULL),
    ('دير الغصون', 1680, 'name', 'v1-whitelist', NULL),
    ('دير_الغصون', 1680, 'name', 'v1-whitelist', NULL),
    ('قفين', 1681, 'name', 'v1-whitelist', NULL),
    ('بلعا', 1682, 'name', 'v1-whitelist', NULL),
    ('شويكة', 1683, 'name', 'v1-whitelist', NULL),
    ('شويكه', 1683, 'name', 'v1-whitelist', NULL),
    ('يعبد', 1684, 'name', 'v1-whitelist', NULL),
    ('قباطية', 1685, 'name', 'v1-whitelist', NULL),
    ('قباطيه', 1685, 'name', 'v1-whitelist', NULL),
    ('برقين', 1686, 'name', 'v1-whitelist', NULL),
    ('جلبون', 1687, 'name', 'v1-whitelist', NULL),
    ('الجلمة', 1688, 'name', 'v1-whitelist', NULL),
    ('الجلمه', 1688, 'name', 'v1-whitelist', NULL),
    ('دوتان', 1689, 'name', 'v1-whitelist', NULL),
    ('مسلية', 1690, 'name', 'v1-whitelist', NULL),
    ('مسليه', 1690, 'name', 'v1-whitelist', NULL),
    ('عرابة', 1691, 'name', 'v1-whitelist', NULL),
    ('عرابه', 1691, 'name', 'v1-whitelist', NULL),
    ('طمون', 1692, 'name', 'v1-whitelist', NULL),
    ('الحمرا', 1693, 'name', 'v1-whitelist', NULL),
    ('عقابا', 1694, 'name', 'v1-whitelist', NULL),
    ('الفارعة', 1695, 'name', 'v1-whitelist', NULL),
    ('الفارعه', 1695, 'name', 'v1-whitelist', NULL),
    ('بيت ساحور', 1696, 'name', 'v1-whitelist', NULL),
    ('بيت_ساحور', 1696, 'name', 'v1-whitelist', NULL),
    ('بيت فجار', 1697, 'name', 'v1-whitelist', NULL),
    ('بيت_فجار', 1697, 'name', 'v1-whitelist', NULL),
    ('الولجة', 1698, 'name', 'v1-whitelist', NULL),
    ('الولجه', 1698, 'name', 'v1-whitelist', NULL),
    ('نحالين', 1699, 'name', 'v1-whitelist', NULL),
    ('حوسان', 1700, 'name', 'v1-whitelist', NULL),
    ('بيت اولا', 1701, 'name', 'v1-whitelist', NULL),
    ('بيت_اولا', 1701, 'name', 'v1-whitelist', NULL),
    ('يطا', 1702, 'name', 'v1-whitelist', NULL),
    ('الظاهرية', 1703, 'name', 'v1-whitelist', NULL),
    ('الظاهريه', 1703, 'name', 'v1-whitelist', NULL),
    ('السموع', 1704, 'name', 'v1-whitelist', NULL),
    ('صوريف', 1705, 'name', 'v1-whitelist', NULL),
    ('الشيوخ', 1706, 'name', 'v1-whitelist', NULL),
    ('بيت كاحل', 1707, 'name', 'v1-whitelist', NULL),
    ('بيت_كاحل', 1707, 'name', 'v1-whitelist', NULL),
    ('خاراس', 1708, 'name', 'v1-whitelist', NULL),
    ('نوبا', 1709, 'name', 'v1-whitelist', NULL),
    ('تفوح', 1710, 'name', 'v1-whitelist', NULL),
    ('جيوس', 1711, 'name', 'v1-whitelist', NULL),
    ('كفر ثلث', 1712, 'name', 'v1-whitelist', NULL),
    ('كفر_ثلث', 1712, 'name', 'v1-whitelist', NULL),
    ('حبلة', 1713, 'name', 'v1-whitelist', NULL),
    ('حبله', 1713, 'name', 'v1-whitelist', NULL),
    ('عزبة الطبيب', 1714, 'name', 'v1-whitelist', NULL),
    ('عزبه_الطبيب', 1714, 'name', 'v1-whitelist', NULL),
    ('بديا', 1715, 'name', 'v1-whitelist', NULL),
    ('بروقين', 1716, 'name', 'v1-whitelist', NULL),
    ('كوبر', 1718, 'name', 'v1-whitelist', NULL),
    ('نعلين', 1719, 'name', 'v1-whitelist', NULL),
    ('بلعين', 1720, 'name', 'v1-whitelist', NULL),
    ('بير زيت', 1721, 'name', 'v1-whitelist', NULL),
    ('بير_زيت', 1721, 'name', 'v1-whitelist', NULL),
    ('العوجا', 1722, 'name', 'v1-whitelist', NULL),
    ('فصايل', 1723, 'name', 'v1-whitelist', NULL),
    ('النويعمة', 1724, 'name', 'v1-whitelist', NULL),
    ('النويعمه', 1724, 'name', 'v1-whitelist', NULL),
    ('دير حجلة', 1725, 'name', 'v1-whitelist', NULL),
    ('دير_حجله', 1725, 'name', 'v1-whitelist', NULL),
    ('الشيخ جراح', 1726, 'name', 'v1-whitelist', NULL),
    ('الشيخ_جراح', 1726, 'name', 'v1-whitelist', NULL),
    ('سلوان', 1727, 'name', 'v1-whitelist', NULL),
    ('العيساوية', 1728, 'name', 'v1-whitelist', NULL),
    ('العيساويه', 1728, 'name', 'v1-whitelist', NULL),
    ('شعفاط', 1729, 'name', 'v1-whitelist', NULL),
    ('ابو ديس', 1730, 'name', 'v1-whitelist', NULL),
    ('ابو_ديس', 1730, 'name', 'v1-whitelist', NULL),
    ('الرام', 1731, 'name', 'v1-whitelist', NULL),
    ('ياسوف', 1732, 'name', 'v1-whitelist', NULL),
    ('اسكاكا', 1733, 'name', 'v1-whitelist', NULL),
    ('انشية', 1734, 'name', 'v1-whitelist', NULL),
    ('انشيه', 1734, 'name', 'v1-whitelist', NULL),
    ('اللبن', 1739, 'name', 'v1-whitelist', NULL),
    ('اللبن الشرقية', 1739, 'name', 'v1-whitelist', NULL),
    ('اللبن الشرقيه', 1739, 'name', 'v1-whitelist', NULL),
    ('اللبن_الشرقيه', 1739, 'name', 'v1-whitelist', NULL),
    ('معالي أفرايم', 1741, 'name', 'v1-whitelist', NULL),
    ('معاليه افرايم', 1741, 'name', 'v1-whitelist', NULL),
    ('دوار كدوميم', 1742, 'name', 'v1-whitelist', NULL),
    ('كدوميم', 1742, 'name', 'v1-whitelist', NULL),
    ('عناتا', 1745, 'name', 'v1-whitelist', NULL),
    ('عناتتا', 1745, 'name', 'v1-whitelist', NULL),
    ('قصرة', 1746, 'name', 'v1-whitelist', NULL),
    ('قصره', 1746, 'name', 'v1-whitelist', NULL),
    ('قصرى', 1746, 'name', 'v1-whitelist', NULL),
    ('مدخل ناقوره', 1747, 'name', 'v1-whitelist', NULL),
    ('ناقورة', 1747, 'name', 'v1-whitelist', NULL),
    ('ناقوره', 1747, 'name', 'v1-whitelist', NULL),
    ('سبسطية', 1752, 'name', 'v1-whitelist', NULL),
    ('مداخل سبسطية', 1752, 'name', 'v1-whitelist', NULL),
    ('مداخل سبسطية اتجاهين', 1752, 'name', 'v1-whitelist', NULL),
    ('جيت', 1754, 'name', 'v1-whitelist', NULL),
    ('دوار جيت', 1754, 'name', 'v1-whitelist', NULL),
    ('دوار جيت اتجاهين', 1754, 'name', 'v1-whitelist', NULL),
    ('مفرق جيت', 1754, 'name', 'v1-whitelist', NULL),
    ('كفر لاقف', 1758, 'name', 'v1-whitelist', NULL),
    ('الطيبة كراميلو', 1759, 'name', 'v1-whitelist', NULL),
    ('كراميلو الطيبه', 1759, 'name', 'v1-whitelist', NULL),
    ('كفر عقب', 1760, 'name', 'v1-whitelist', NULL),
    ('النبي إلياس', 1762, 'name', 'v1-whitelist', NULL),
    ('النبي الياس', 1762, 'name', 'v1-whitelist', NULL),
    ('قلقيلية', 1764, 'name', 'v1-whitelist', NULL),
    ('مدخل قلقيلية', 1764, 'name', 'v1-whitelist', NULL),
    ('اريحا الجنوبي dco', 1765, 'name', 'v1-whitelist', NULL),
    ('شابي شمرون', 1767, 'name', 'v1-whitelist', NULL),
    ('شافي شمررون', 1767, 'name', 'v1-whitelist', NULL),
    ('شافي شمرون', 1767, 'name', 'v1-whitelist', NULL),
    ('شافي_شمرون', 1767, 'name', 'v1-whitelist', NULL),
    ('شفي شمرون', 1767, 'name', 'v1-whitelist', NULL),
    ('دوار معالي أدوميم', 1769, 'name', 'v1-whitelist', NULL),
    ('دوار معالي ادوميم', 1769, 'name', 'v1-whitelist', NULL),
    ('سدة قراوة', 1770, 'name', 'v1-whitelist', NULL),
    ('سده قراوه', 1770, 'name', 'v1-whitelist', NULL),
    ('قراوه بني حسان', 1770, 'name', 'v1-whitelist', NULL),
    ('الجسر', 1792, 'name', 'v1-whitelist', NULL),
    ('الكرامة', 1792, 'name', 'v1-whitelist', NULL),
    ('اللنبي', 1792, 'name', 'v1-whitelist', NULL),
    ('جسر الملك حسين', 1792, 'name', 'v1-whitelist', NULL),
    ('معبر الكرامه', 1792, 'name', 'v1-whitelist', NULL),
    ('استراحة أريحا', 1793, 'name', 'v1-whitelist', NULL),
    ('استراحة اريحا', 1793, 'name', 'v1-whitelist', NULL),
    ('الاستراحة', 1793, 'name', 'v1-whitelist', NULL),
    ('الاستراحه', 1793, 'name', 'v1-whitelist', NULL),
    ('دير إستيا', 1797, 'name', 'v1-whitelist', NULL),
    ('دير استيا', 1797, 'name', 'v1-whitelist', NULL),
    ('دير ستيا', 1797, 'name', 'v1-whitelist', NULL),
    ('دير_استيا', 1797, 'name', 'v1-whitelist', NULL),
    ('ديرستا', 1797, 'name', 'v1-whitelist', NULL),
    ('مدخل ديراستيا', 1797, 'name', 'v1-whitelist', NULL),
    ('برقة', 1799, 'name', 'v1-whitelist', NULL),
    ('مخصوم برقة', 1799, 'name', 'v1-whitelist', NULL),
    ('بيت إيبا', 1800, 'name', 'v1-whitelist', NULL),
    ('بيت ايبا', 1800, 'name', 'v1-whitelist', NULL),
    ('بيت_ايبا', 1800, 'name', 'v1-whitelist', NULL),
    ('حاجز شرق أريحا', 1822, 'name', 'v1-whitelist', NULL),
    ('حاجز شرق اريحا', 1822, 'name', 'v1-whitelist', NULL),
    ('شرق اريحا', 1822, 'name', 'v1-whitelist', NULL),
    ('إشارات عوفرا', 1825, 'name', 'v1-whitelist', NULL),
    ('اشارات عوفرا', 1825, 'name', 'v1-whitelist', NULL),
    ('عوفرا', 1825, 'name', 'v1-whitelist', NULL),
    ('وادي قانا', 1826, 'name', 'v1-whitelist', NULL),
    ('سيلة الظهر', 1827, 'name', 'v1-whitelist', NULL),
    ('سيله الظهر', 1827, 'name', 'v1-whitelist', NULL),
    ('رافات', 1828, 'name', 'v1-whitelist', NULL),
    ('مدخل رافات', 1828, 'name', 'v1-whitelist', NULL),
    ('قدوميم', 1829, 'name', 'v1-whitelist', NULL),
    ('حاجز شوفة', 1831, 'name', 'v1-whitelist', NULL),
    ('حاجز شوفه', 1831, 'name', 'v1-whitelist', NULL),
    ('شوفه', 1831, 'name', 'v1-whitelist', NULL),
    ('تئينيم', 1832, 'name', 'v1-whitelist', NULL),
    ('تانيم', 1832, 'name', 'v1-whitelist', NULL),
    ('معبر تئينيم', 1832, 'name', 'v1-whitelist', NULL),
    ('افني حيفتس', 1833, 'name', 'v1-whitelist', NULL),
    ('حاجز أفني حيفتس', 1833, 'name', 'v1-whitelist', NULL),
    ('الشيخ سعد', 1835, 'name', 'v1-whitelist', NULL),
    ('حاجز الشيخ سعد', 1835, 'name', 'v1-whitelist', NULL)
  ) AS v(alias, place_id, kind, origin, note)
  JOIN place p ON p.place_id = v.place_id
ON CONFLICT (alias, place_id) DO NOTHING;
