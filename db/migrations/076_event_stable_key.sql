-- 076 — a stable identity for classifier events.
--
-- `news_incidents.py --rebuild` used to DELETE the classifier's events and
-- re-insert them, so every rebuild re-minted every event id (79,779–84,453 on
-- 2026-09-24) and nothing outside the database could reference an event. Events
-- now carry attrs.stable_key = sha1(classifier|type|place|name_key|first claim),
-- the rebuild resets counts instead of deleting rows, and a new cluster joins
-- the event that already carries its key. One key, one event.
CREATE UNIQUE INDEX IF NOT EXISTS event_stable_key_uniq
    ON event ((attrs->>'stable_key'))
    WHERE attrs ? 'stable_key';
