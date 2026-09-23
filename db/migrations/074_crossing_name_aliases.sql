-- 074 — the English spelling a traveller actually types.
--
-- Found by the partner's own QA pass on 2026-09-23: asking checkpoint_status
-- for "Zaatara" answered about عطارة (Atara), 11 km away, in the opposite
-- state. The real checkpoint is زعتره, whose registered Latin name is
-- "Za'tara (Tapuach)" — so the apostrophe-free spelling matched nothing
-- exactly, fell through to the fuzzy path, and the fuzzy path picked the
-- nearest Latin lookalike with a score of 0.738 that nothing surfaced.
--
-- The locality زعترة already has 'zatarah' as an alias. These rows give the
-- checkpoint its own Latin spellings so the common one is an EXACT hit rather
-- than a guess, which is also what stops the fuzzy path from being reached.
INSERT INTO place_alias (alias_norm, place_id, origin, confidence) VALUES
  ('zaatara',            1489, 'manual', 0.95),
  ('zaatara checkpoint', 1489, 'manual', 0.95),
  ('zotara',             1489, 'manual', 0.9),
  ('zatar',              1489, 'manual', 0.85),
  ('tapuach',            1489, 'manual', 0.85)
ON CONFLICT (alias_norm) DO NOTHING;

-- The alias must point at the checkpoint that the checkpoint layer serves, not
-- at a merged-away row: `place_merge` re-points aliases, and a stale one hands
-- out a dead place_id.
UPDATE place_alias pa SET place_id = 1489
 WHERE pa.alias_norm IN ('zaatara', 'zaatara checkpoint', 'zotara', 'zatar', 'tapuach')
   AND pa.place_id <> 1489;
