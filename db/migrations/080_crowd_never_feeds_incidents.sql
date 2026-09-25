-- 080 — a crowd report is never read as news.
--
-- Audit 2026-09-25, F012 (critical). source.feeds_incidents defaults to true
-- (037) and crowd/engine.register() never set it, so every crowd submitter was
-- a news source: a stranger's note "قوات الاحتلال تقتحم بلدة حوارة واغلاق مدخل
-- البلدة" became, within one classifier tick, a believed raid at Huwara and a
-- road_closure 'closed' — outside the P2.4 gate, with no corroboration, and
-- able to join a real event's dedup window as a second "source".
--
-- The engine now registers crowd sources with feeds_incidents = false and the
-- classifier's claim query excludes kind 'crowd' outright; this turns it off
-- for the submitters that already exist.
--
-- Rollback (exact: nothing ever set a crowd source's flag to false before 080):
--   UPDATE source SET feeds_incidents = true WHERE kind = 'crowd';

UPDATE source SET feeds_incidents = false WHERE kind = 'crowd' AND feeds_incidents;
