-- 012 — count OBSERVERS, not messages.
--
-- Every one of the 92,719 imported checkpoint observations was attributed to a
-- single synthetic source, `v1_checkpoint_parser`, so `independent_sources` was
-- hard-coded to 1 and `contradicted_by` to 0. Corroboration — the mechanism the
-- whole confidence model rests on — was inert for checkpoints.
--
-- Attributing each observation to its real channel is necessary but NOT
-- sufficient, because the channels are not independent. Measured over 32,607
-- co-observations (same place, same direction, within 10 minutes):
--
--     ahwalaltorq  ~ rsdrasd          672 pairs   100.0% agree
--     areenablus   ~ rsdrasd          672 pairs   100.0%
--     ahwalaltareq ~ areenablus       619 pairs   100.0%
--     roaddconditions ~ rsdrasd       679 pairs    99.9%
--     …                                            99.5%+
--     a7walstreet  ~ roaddconditions 1195 pairs    81.1%
--
-- Agreement at 100% across hundreds of independent chances is not seven
-- observers reaching the same conclusion; it is one observer copied seven
-- times. Counting them naively would multiply a single report's confidence
-- sevenfold — the exact failure mode corroboration is supposed to prevent.
-- Meanwhile a7walstreet, agreeing ~81%, is a genuinely separate observer and
-- its confirmation is worth far more.
--
-- So agreement is MEASURED and stored here, and channels above a threshold are
-- collapsed into one independence unit. Corroboration then counts distinct
-- units. The clustering itself (transitive closure over the pairs) runs in
-- Python — see learn/source_independence.py — because union-find is clearer
-- there than in recursive SQL; this migration owns the table it writes to.

CREATE TABLE source_agreement (
  source_a        INTEGER NOT NULL REFERENCES source(source_id) ON DELETE CASCADE,
  source_b        INTEGER NOT NULL REFERENCES source(source_id) ON DELETE CASCADE,
  state_kind      TEXT    NOT NULL,
  co_observations INTEGER NOT NULL CHECK (co_observations > 0),
  agreements      INTEGER NOT NULL CHECK (agreements >= 0),
  agreement_rate  REAL    NOT NULL CHECK (agreement_rate BETWEEN 0 AND 1),
  window_seconds  INTEGER NOT NULL,
  computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (source_a, source_b, state_kind),
  -- Store each pair once, in a canonical order.
  CHECK (source_a < source_b)
);
COMMENT ON TABLE source_agreement IS
  'Measured pairwise agreement between sources on co-observed state. Input to independence grouping; recomputed nightly.';

CREATE INDEX source_agreement_rate_idx ON source_agreement (state_kind, agreement_rate DESC);

-- Why a channel sits in the group it does — so a surprising confidence number
-- can be traced back to the measurement that caused it rather than guessed at.
ALTER TABLE source
  ADD COLUMN independence_note TEXT,
  ADD COLUMN independence_measured_at TIMESTAMPTZ;

COMMENT ON COLUMN source.independence_group IS
  'Sources sharing a group counted as ONE observer for corroboration. Derived from source_agreement, not hand-assigned.';

-- Channels observed carrying checkpoint reports. Registered up front so the
-- importer attributes to a real source rather than inventing one per run.
-- reliability stays NULL — it is measured by the learning loop, never seeded.
INSERT INTO source (key, name, kind, license_spdx, commercial_use,
                    attribution_text, authority_rank, independence_group)
SELECT 'tg_' || ch,
       'Telegram @' || ch,
       'telegram', 'NONE', false,
       'Telegram channel @' || ch, 4, NULL
FROM (VALUES
  ('a7walstreet'), ('ahwalaltreq'), ('road_jehad'), ('roaddconditions'),
  ('almasshta'), ('aljanoop48'), ('ahwalaltorq'), ('ahwalaltareq'),
  ('rsdrasd'), ('areenablus'), ('peopleofhebron'), ('ahwaltareq1'),
  ('khbnews1'), ('aljesernews'), ('jisrrrr'), ('ahwaltrkwhwagz_nablous')
) AS c(ch)
ON CONFLICT (key) DO NOTHING;
