-- 099 — trust by place: where a wide source has earned its word (2026-10-11).
--
-- PalHub's board was earned out by VALUE CLASS over the whole West Bank
-- (decision A, 2026-09-25: `open` and `closed` asserted, `congested` held).
-- Measured per place on 2026-10-11 (42 days, 102,844 pairs against the road
-- channels): the board's `open` agrees 0.88 overall and 0.29 at زواتا; its
-- `closed` 0.72 overall and 0.00 at بيت ليد (the channels said open 92 times
-- in 92); its severe congestion 0.49 overall and 0.69 at قلنديا. The board
-- restates whatever its own users last set, however long ago, so it is right
-- where they pass often and repeats yesterday where they do not.
--
-- This table holds one row per (source, place, claim) that has been measured:
-- how often an independent channel said the same within the window, the bar
-- it was held to (the channels' own agreement on that value, less a band),
-- and the verdict. `moved` marks the rows where the measurement overrules the
-- class rule; ingest/sources/palhub_roads.py reads only those when it writes
-- the next reading. learn/place_trust.py fills it nightly. Nothing stored is
-- changed by it: a reading keeps the modality it was written with.
--
-- Rollback: DROP TABLE source_place_trust;  (the ingest then falls back to
-- the class rule, which is what ran before.)
CREATE TABLE IF NOT EXISTS source_place_trust (
  source_id      integer     NOT NULL REFERENCES source(source_id),
  place_id       bigint      NOT NULL REFERENCES place(place_id),
  claim_class    text        NOT NULL
                 CHECK (claim_class IN ('open', 'closed', 'congested_medium', 'congested_severe')),
  cells          integer     NOT NULL,      -- (hour) cells with at least one pair
  days           integer     NOT NULL,      -- distinct days those cells fall on
  agreement      real        NOT NULL,      -- share of cells where the channels said the same
  lower_bound    real        NOT NULL,      -- Wilson 95 %
  upper_bound    real        NOT NULL,
  bar            real        NOT NULL,      -- the channels' own agreement on the value, less the band
  heard          jsonb       NOT NULL,      -- what the channels said: {"open": n, "closed": n, ...}
  verdict        text        NOT NULL CHECK (verdict IN ('assert', 'hold')),
  moved          boolean     NOT NULL,      -- the measurement overrules the class rule here
  why            text        NOT NULL,
  window_days    integer     NOT NULL,
  window_minutes integer     NOT NULL,
  measured_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_id, place_id, claim_class)
);

COMMENT ON TABLE source_place_trust IS
  'Per place and claim, how a wide source (PalHub''s board) agrees with the independent road '
  'channels, and whether that overrules the class rule there (moved). Learned nightly by '
  'learn/place_trust.py; read by ingest/sources/palhub_roads.py when it writes a reading.';
