-- 079 — a crowd report is never read as news.
--
-- 037 made "does this source feed the incident classifier" a column, default
-- TRUE "so a normal news channel needs no ceremony". The crowd engine (030)
-- inserts its sources without naming the column, so every registered
-- submitter — registration is open by decision, three accounts an hour per
-- address — was a news source. The engine appends the submitter's free-text
-- note to claim.raw_text, and ingest/sources/news_incidents.py selects every
-- claim whose source feeds_incidents. Audit F012, reproduced locally:
--
--     '[checkpoint_flow=closed] حوارة — قوات الاحتلال تقتحم بلدة حوارة واغلاق مدخل البلدة'
--         -> verdict incident, type raid, place حواره, confidence 0.7
--
-- Within one five-minute classifier tick a stranger's note became a BELIEVED
-- raid served by /v2/incidents/recent ("from one source"), and a closure note
-- also wrote a road_closure 'closed' assertion that the corridor reads as a
-- caution. The belief layer — the 0.17 an unverified submitter is worth, the
-- P2.4 gate — was never consulted on that path. Inside a real event's dedup
-- window the crowd claim also joined it as a second independence unit, so a
-- genuine single-source incident was served as corroborated.
--
-- A crowd report says what a person saw about ONE field, in that field's
-- vocabulary, and it enters belief through state_observation like any other
-- reading. Its note is kept (never parsed) and never becomes news.
--
-- Enforced by the schema, not by the one writer remembering: the same trap
-- (a rule that lives only in which rows happen to exist) is the reason 035 and
-- 037 exist. A trigger rather than a CHECK because a CHECK would make every
-- existing writer that omits the column (tests, fixtures) fail on the default,
-- while the thing to guarantee is simply that the flag can never be true.
--
-- WHAT THIS DOES NOT CLEAN UP: classifications and events the classifier has
-- already derived from crowd claims. Unlinking them means updating
-- claim.event_id, and this migration touches no evidence table; the sanctioned
-- path is the classifier's own rebuild, which re-reads only feeds_incidents
-- sources and lets the orphan sweep retire what nothing supports any more
-- (docs/HANDS: count first, then `news_incidents --rebuild`).
--
-- Rollback (exact: before this migration no crowd source had ever been set to
-- false — 037/038 name only telegram keys — so every crowd row held the
-- default TRUE):
--   DROP TRIGGER IF EXISTS source_crowd_never_feeds_incidents ON source;
--   DROP FUNCTION IF EXISTS source_crowd_never_feeds_incidents();
--   UPDATE source SET feeds_incidents = true WHERE kind = 'crowd';

UPDATE source SET feeds_incidents = false
 WHERE kind = 'crowd' AND feeds_incidents;

CREATE OR REPLACE FUNCTION source_crowd_never_feeds_incidents()
RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
  IF NEW.kind = 'crowd' THEN
    NEW.feeds_incidents := false;
  END IF;
  RETURN NEW;
END
$fn$;

DROP TRIGGER IF EXISTS source_crowd_never_feeds_incidents ON source;
CREATE TRIGGER source_crowd_never_feeds_incidents
  BEFORE INSERT OR UPDATE OF kind, feeds_incidents ON source
  FOR EACH ROW EXECUTE FUNCTION source_crowd_never_feeds_incidents();

COMMENT ON FUNCTION source_crowd_never_feeds_incidents() IS
  'A crowd source never feeds the incident classifier (079, audit F012): an '
  'open-registration submitter''s free-text note, read as news, became a '
  'believed incident and a road_closure assertion without ever meeting the '
  'belief layer.';
