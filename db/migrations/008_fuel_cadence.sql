-- 008 — retune fuel half-lives to the MEASURED feed cadence.
--
-- ARCHITECTURE §3.5 guessed 3h for fuel, reasoning that "stations run dry
-- within hours". That is true of the physical world but wrong for this feed:
-- palhubappfuel posts a COMPLETE state snapshot for all 14 regions every
-- ~30 minutes (observed 2026-07-31: 11:31, 11:37, 12:00, 12:07, 12:30).
--
-- So a reading is authoritative until the next sweep, and staleness is a
-- property of the FEED rather than of any individual station. Half-life is set
-- to 45 min — 1.5 sweeps — so a station stays confident across one missed
-- sweep and decays quickly once the feed genuinely stops.
--
-- Rollback: restore 10800/10800/21600 for the three fuel kinds.
UPDATE state_kind_config
   SET half_life_seconds = 2700,
       note = '45min = 1.5x the measured ~30min palhub sweep cadence'
 WHERE state_kind IN ('fuel_diesel','fuel_gasoline');

UPDATE state_kind_config
   SET half_life_seconds = 5400,
       note = '90min — cooking gas is not in the palhub sweep; slower signal'
 WHERE state_kind = 'cooking_gas';
