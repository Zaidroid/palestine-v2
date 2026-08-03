-- 039 — checkpoint identity hygiene, from the hand-scored accuracy audit.
--
-- (1) Two canonical checkpoints carry a STATUS WORD fossilized into their
--     display name: v1 minted its registry keys from whole report lines, and
--     the merge that collapsed the phantoms kept these as the survivors.
--     "صرة بحري" is "Sarra, flowing-freely" — بحري is what one reporter said
--     about it once, not what it is called. Besides being wrong on screen,
--     the polluted name breaks the crowd path: a submitter typing صرة cannot
--     fold-match "صرة بحري", so their report would land on the LOCALITY of
--     the same name — a row no channel writes to, where it corroborates
--     nothing. name_en was already clean in both cases.
UPDATE place SET name_ar = 'صرة'       WHERE place_id = 1480 AND name_ar = 'صرة بحري';
UPDATE place SET name_ar = 'الكونتينر' WHERE place_id = 1604 AND name_ar = 'الكونتينر بحري اتجاهين';

-- (2) 650 observations sit on four merged-away places, all quarantined palhub
--     rows written AFTER place_merge ran: the resolver kept honoring aliases
--     that point at merged-away rows and handed out the dead place_id.
--     resolve/geo.py now follows merged_into at lookup; this re-points what
--     already landed wrong, with the same statement place_merge.apply() uses.
UPDATE state_observation o
   SET place_id = p.merged_into
  FROM place p
 WHERE p.place_id = o.place_id
   AND p.merged_into IS NOT NULL;

-- Same hole, other tables that address places directly.
UPDATE state_current sc
   SET place_id = p.merged_into
  FROM place p
 WHERE p.place_id = sc.place_id
   AND p.merged_into IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM state_current c2
                   WHERE c2.place_id = p.merged_into
                     AND c2.state_kind = sc.state_kind
                     AND c2.direction = sc.direction);
DELETE FROM state_current sc
 USING place p
 WHERE p.place_id = sc.place_id AND p.merged_into IS NOT NULL;
