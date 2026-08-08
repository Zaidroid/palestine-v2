-- 055 — three tiers, because "commercial" was answering two questions at once
--
-- `databank_commercial` means "you may sell this". For 178,049 rows that is
-- the whole story. For 6,562 it is half of one: Palestine Open Maps (ODbL,
-- 6,548 rows — the entire Nakba and Mandate-era corpus) and UNOSAT
-- (CC-BY-SA, 14 rows) permit commercial use AND require that a derived
-- database be released under the same licence. Both facts are true; only one
-- was reachable.
--
-- A customer who queries databank_commercial today, builds a product on it,
-- and ships it closed is in breach — and nothing we gave them said so. That
-- is not their mistake.
--
-- databank_commercial STAYS, as an alias for the permissive tier, so
-- G5.5-G5.8 keep testing what they have always tested and no endpoint
-- changes. What changes is that the share-alike rows are no longer inside it
-- pretending to be unencumbered; they have their own door, and its name says
-- what walking through it costs.

CREATE OR REPLACE VIEW v_tier_open AS
SELECT * FROM databank_serving
WHERE redistribution IN ('open', 'attribution');
COMMENT ON VIEW v_tier_open IS
  'Redistributable with credit and no further obligation. The free public '
  'tier''s natural extent.';

CREATE OR REPLACE VIEW v_tier_commercial_permissive AS
SELECT * FROM databank_serving
WHERE commercial_use AND NOT share_alike;
COMMENT ON VIEW v_tier_commercial_permissive IS
  'Sellable with no copyleft obligation attached. This is what a customer '
  'expects the word "commercial" to mean, and now it is the only thing it '
  'means.';

CREATE OR REPLACE VIEW v_tier_commercial_sharealike AS
SELECT * FROM databank_serving
WHERE commercial_use AND share_alike;
COMMENT ON VIEW v_tier_commercial_sharealike IS
  'Sellable, but a derived DATABASE must carry the same licence (ODbL-1.0, '
  'CC-BY-SA). Separate from the permissive tier because the obligation '
  'travels with the data and the buyer has to be able to see it before they '
  'build on it. 6,562 rows at 2026-08-08 — almost all of Palestine Open '
  'Maps'' Mandate-era gazetteer.';

-- The alias. Deliberately NARROWED to the permissive tier: everything that
-- was in it and is not now is a row that carried an obligation the view did
-- not mention.
CREATE OR REPLACE VIEW databank_commercial AS
SELECT * FROM v_tier_commercial_permissive;
COMMENT ON VIEW databank_commercial IS
  'Sellable subset, permissive only (055). Kept as an alias so G5.5-G5.8 and '
  'every existing consumer are unchanged; share-alike rows moved to '
  'v_tier_commercial_sharealike, where their obligation is in the name.';
