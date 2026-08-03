-- 038 — the Gaza health ministry is not a West Bank news channel, and
--        re-classification must not leave the previous generation being served.
--
-- (1) tg_mohmediagaza is the Gaza MoH spokesman. Everything it posts is Gaza;
--     the incident classifier is a WEST BANK movement tracker and rejects Gaza
--     geography on purpose. The reject caught 6,497 of its 7,330 claims — and
--     the 4 that slipped through include claim 9516: 118 killed on شارع
--     الرشيد, filed under NABLUS because the governorate matcher found نابلس
--     inside النابلسي, the Gaza roundabout the bodies were recovered from
--     (#37). Its numbers still flow through cascade/moh_gaza.py, which is what
--     that channel is FOR. Same pattern as 037: whether a source feeds the
--     classifier is a column, not a property of which channels happen to exist.
UPDATE source SET feeds_incidents = false WHERE key = 'tg_mohmediagaza';

DELETE FROM claim_classification cc
 USING claim c, source s
 WHERE cc.claim_id = c.claim_id
   AND s.source_id = c.source_id
   AND s.key = 'tg_mohmediagaza';

-- (2) Claims of every non-news source lose their event links. 037 deleted the
--     fuel bulletins' classifications but left claim.event_id set, and the 77
--     phantom "closure" events those links anchored stayed status='believed'
--     and publicly served. claim.event_id is the one field 005 sanctions
--     updating on a claim.
UPDATE claim c SET event_id = NULL
  FROM source s
 WHERE s.source_id = c.source_id
   AND NOT s.feeds_incidents
   AND c.event_id IS NOT NULL;

-- (3) One-time sweep of stale event generations. Five classifier version
--     bumps ran incrementally: each re-clustered the same claims into NEW
--     events and moved the pointers, leaving 982 believed-but-unreferenced
--     events — /v2/incidents was serving nearly every incident twice. An
--     event of the news classifier's that neither a claim nor a
--     classification references is a conclusion nothing stands behind.
--     Deleting a conclusion is not data loss: every underlying claim stays
--     (037's distinction). fire_detection events are untouched — satellite
--     detections stand alone by design and carry classifier='firms'.
--     news_incidents.py now performs this same sweep after every run, so this
--     cannot accumulate again.
DELETE FROM event e
 WHERE e.attrs->>'classifier' = 'news'
   AND NOT EXISTS (SELECT 1 FROM claim c WHERE c.event_id = e.event_id)
   AND NOT EXISTS (SELECT 1 FROM claim_classification cc
                   WHERE cc.event_id = e.event_id);

-- (4) Closure observations derived from a now-deleted event follow it. These
--     rows are machine-derived conclusions (they carry from_event), not
--     source evidence — the append-only rule protects what a witness said,
--     not what we once concluded from it.
DELETE FROM state_observation so
 WHERE so.attrs ? 'from_event'
   AND NOT EXISTS (SELECT 1 FROM event e
                   WHERE e.event_id = (so.attrs->>'from_event')::bigint);
