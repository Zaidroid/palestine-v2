-- 022 — compress state_observation. Lossless, because "no data loss" is a rule.
--
-- WHAT WAS FOUND
-- The fuel loader polls 196 stations every 5 minutes and writes an observation
-- per station per run whether or not anything changed. Measured over the first
-- ~2 days of operation:
--
--     fuel_gasoline   381,032 rows across 196 places  (1,944 each)
--     fuel_diesel     381,032 rows
--     99.9% of them are byte-identical to the previous reading for that place
--     (380,790 of 381,032). Only 242 real value changes in the whole period.
--
-- That is ~743,000 rows/day, against 94,271 checkpoint_status rows covering two
-- MONTHS. The database grew 395 MB -> 574 MB in 19 hours.
--
-- WHY THIS IS A DATA-SAFETY PROBLEM AND NOT A TIDINESS ONE
-- The nightly off-site backup (ops/backup.py, added the same day) ships to a
-- 15 GiB Drive quota and keeps 30 dailies. The dump grew 12.0 MB -> 18.5 MB in
-- those same 19 hours. Extrapolated, 30 retained sets breach the quota in
-- roughly two months and the backup starts failing — so the growth rate quietly
-- disarms the thing protecting the data.
--
-- WHY COMPRESSION AND NOT PRUNING
-- The stated hard rule is that nothing is deleted or overwritten. A repeated
-- reading is not noise: "still 'open' at 14:35, checked 5 minutes ago" is a
-- genuine observation, and the staleness gates in state_serving depend on
-- exactly that recency. So the rows stay. TimescaleDB columnstore compression
-- keeps every row addressable and byte-identical on read while storing the
-- repeats once.
--
-- MEASURED on the real chunks before this was committed:
--     _hyper_2_11_chunk   31.2 MB ->  2.7 MB   11.7x
--     all closed chunks  ~178   MB -> ~17   MB  ~10x
--     database            574   MB -> 413   MB
--
-- Reads verified identical after compressing (row counts and date ranges).
--
-- A CAVEAT THAT ONLY SHOWED UP BY MEASURING THE BACKUP TOO
-- Compressing the old checkpoint chunks made the pg_dump BIGGER, not smaller:
-- 19.25 -> 22.61 bytes/row. Those chunks are text-heavy Arabic with little
-- repetition, and pg_dump's own gzip was already doing better on the raw rows
-- than columnstore does on blobs gzip cannot then re-compress.
--
-- The opposite is true for the fuel flood, which is the actual volume. Measured
-- in a scratch database restored from a real set, compressing the fuel-heavy
-- active chunk:
--     dump      21.21 MB -> 10.38 MB   (0.49x)
--     on disk    ~385 MB -> 23 MB
--
-- So compression is right here, but for the reason that 99.9% of the rows are
-- exact repeats — not because compression helps backups in general. On the
-- text-heavy chunks it costs a little; on the redundant numeric ones it halves
-- the dump and shrinks the disk ~15x, and those dominate everything.
--
-- CHUNK INTERVAL DROPS 7 DAYS -> 1 DAY
-- At 743k rows/day a 7-day chunk is ~1.3 GB and stays uncompressed until the
-- whole week closes, so the largest object in the database is always the one
-- the backup has to carry in full. Daily chunks close daily and compress two
-- days later. Only affects NEW chunks; existing ones keep their 7-day range.
--
-- WHAT THIS DOES NOT FIX
-- Writing 743k rows/day to record 242 changes is still the wrong shape, and
-- compression only makes it affordable. Whether the fuel loader should write a
-- full observation per poll, or a cheaper "still true at T" confirmation, is a
-- semantic decision that changes what the staleness gates can see -- it is
-- deliberately NOT made here. See docs/TIER1_COMPLETION_PLAN.md.
--
-- Idempotent: safe to re-run. Decompresses first so the settings can change.

-- Settings cannot be altered while chunks are compressed.
SELECT decompress_chunk(c, if_compressed => true)
FROM show_chunks('state_observation') c;

-- segmentby place_id+state_kind: the repeats we are collapsing are per place
-- per kind, and both are the columns every serving query filters on.
-- state_obs_id in orderby makes the ordering total, which TimescaleDB warns
-- about otherwise ("column state_obs_id should be used for segmenting or
-- ordering") and which keeps decompression deterministic.
ALTER TABLE state_observation SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'place_id, state_kind',
  timescaledb.compress_orderby   = 'observed_at DESC, state_obs_id'
);

SELECT set_chunk_time_interval('state_observation', INTERVAL '1 day');

SELECT remove_compression_policy('state_observation', if_exists => true);
SELECT add_compression_policy('state_observation', INTERVAL '2 days');

-- Compress what is already closed. The active chunk stays row-store so the
-- 5-minute writers are never inserting into a compressed chunk.
SELECT compress_chunk(c, if_not_compressed => true)
FROM show_chunks('state_observation', older_than => INTERVAL '2 days') c;
