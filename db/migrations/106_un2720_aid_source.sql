-- 106 · the UN2720 Mechanism as a source, and its daily aid dataset
-- 2026-10-12 (written by the supply agent; numbered and reviewed the same evening)
--
--
-- A source row and a dataset row for the UN2720 Mechanism's Monitoring &
-- Tracking Dashboard (ops/fetch_un2720.py, db/mappings/aid_un2720.yaml): trucks,
-- pallets and tonnes of UN-coordinated aid offloaded at Gaza's crossings,
-- collected from them and arrived at their destination, per day, from
-- 2025-05-19. It is a second series beside UNRWA's truck log
-- (v1_aid_access_unrwa_aid_trucks, ends 2025-01-16), under another definition
-- and after a gap of 122 days: never a continuation of it.
--
-- Terms, as read on 2026-10-12: NO licence and no terms of use are stated on
-- un2720.org, info.un2720.org or tracking.un2720.org. The only rights line is
-- the footer "(c) UN2720 Mechanism for Gaza". The Mechanism is run by UNOPS;
-- UNOPS's own website terms (https://www.unops.org/terms-of-use) allow
-- "personal, non-commercial use, without any right to resell or redistribute",
-- and nothing on the UN2720 sites says they cover this dashboard. So the row
-- is `ask`, commercial_use = false, share_alike unknown (false), and
-- terms_verified_at records what was read, not a verdict. Public tier serves
-- with attribution; partner and bulk tiers withhold (v_withheld). Moving it
-- off `ask` takes an answer from UNOPS, not a second reading.
--
-- Rollback: DELETE FROM dataset WHERE key = 'un2720_aid_daily' AND NOT EXISTS
--             (SELECT 1 FROM observation o JOIN dataset d USING (dataset_id)
--               WHERE d.key = 'un2720_aid_daily');
--           DELETE FROM source WHERE key = 'un2720' AND NOT EXISTS (SELECT 1 FROM dataset d
--             JOIN source s USING (source_id) WHERE s.key = 'un2720');
--           (with rows loaded, deactivate instead: UPDATE source SET active = false WHERE key = 'un2720')

INSERT INTO source (key, name, kind, authority_rank, license_spdx, commercial_use, share_alike,
                    attribution_required, attribution_text, redistribution, terms_url, terms_verified_at,
                    terms_evidence, active)
SELECT 'un2720', 'UN2720 Mechanism for Gaza (UNOPS) — Monitoring & Tracking Dashboard', 'api', 4,
       'no-license-found', false, false, true,
       'Aid movements into Gaza: UN2720 Mechanism for Gaza (UNOPS), Monitoring & Tracking Dashboard (tracking.un2720.org). No licence is stated; counts only consignments processed through the UN2720 Mechanism.',
       'ask',
       'https://info.un2720.org/',
       '2026-10-12T19:00:00Z',
       'Read 2026-10-12: no licence or terms of use on un2720.org, info.un2720.org or tracking.un2720.org; the only rights line is the footer "© UN2720 Mechanism for Gaza". The dashboard''s disclaimers say: "Data presented on this dashboard include only humanitarian relief consignments processed through the UN2720 Mechanism." and "They remain subject to change, reflecting the movement of consignments and the dynamic nature of the context." UNOPS''s website terms (unops.org/terms-of-use) grant "personal, non-commercial use, without any right to resell or redistribute"; nothing on the UN2720 sites applies them to the dashboard. Redistribution is "ask" until UNOPS answers.',
       true
 WHERE NOT EXISTS (SELECT 1 FROM source WHERE key = 'un2720');

-- The dataset row, with its real name and cadence. (The loader would create
-- it on the first run as "v1 aid_un2720 — un2720", cadence 'migration'; made
-- here it keeps this name, and the loader's upsert only confirms the category.)
INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs)
SELECT 'un2720_aid_daily',
       'UN2720 Mechanism — aid offloaded, collected and arrived in Gaza, per day',
       s.source_id, 'aid_access', 'daily', true,
       jsonb_build_object(
         'publisher_window_from', '2025-05-19',
         'not_a_continuation_of', 'v1_aid_access_unrwa_aid_trucks',
         'scope_note', 'Only humanitarian consignments processed through the UN2720 Mechanism. Three stages of one journey (offloaded, collected, arrived): never added together. The publisher revises past days and caps the window at its last verified day.')
  FROM source s
 WHERE s.key = 'un2720'
   AND NOT EXISTS (SELECT 1 FROM dataset WHERE key = 'un2720_aid_daily');
