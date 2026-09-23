-- 072 — fuel prices: a copy is not a second reading, and a re-read replaces the old read.
--
-- Two defects 071 had, both measured on its first day of data:
--
-- 1. COPIES. khaberni.com's 2026-08-01 story is maannews.net's word for word.
--    Two outlets printing one wire text agree by copying, and if the reader
--    misreads that text it misreads both copies identically — so their
--    agreement proves nothing about the reading. 071 counted them as two.
--    Now every report stores, per product, the clause the price was read from;
--    a price is believed only when two independent outlets agree AND the
--    clauses behind the agreement are not all the same text.
--
-- 2. STALE READS. fuel_price@1 dated masarnews' 2026-09-06 mid-month cut to
--    2026-09-01, beside the real 8.15 for that day. @2 reads it correctly as
--    2026-09-07, but 071's "latest word per outlet" was keyed on the effective
--    date, so the @1 row stayed a live vote for the 1st. Now the newest reading
--    of each DOCUMENT (outlet + content) supersedes its older readings before
--    any voting happens. The old rows stay in the table; they stop voting.

ALTER TABLE fuel_price_report ADD COLUMN IF NOT EXISTS evidence jsonb NOT NULL DEFAULT '{}'::jsonb;

-- Punctuation, spacing and the two spellings of the shekel are not a
-- different text; a different word is.
CREATE OR REPLACE FUNCTION fuel_price_text_key(t text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT md5(regexp_replace(replace(coalesce(t, ''), 'شيقل', 'شيكل'),
                            '[[:space:][:punct:]،؛ـ]', '', 'g'))
$$;

DROP VIEW IF EXISTS fuel_price_conflicts;
DROP VIEW IF EXISTS fuel_price_believed;
DROP VIEW IF EXISTS fuel_price_votes;

CREATE VIEW fuel_price_votes AS
WITH current_reading AS (          -- the newest reading of each document
    SELECT DISTINCT ON (outlet, content_sha256) *
      FROM fuel_price_report
     ORDER BY outlet, content_sha256, fetched_at DESC, report_id DESC),
latest AS (                        -- one vote per independent unit per (date, product)
    SELECT DISTINCT ON (r.independence_unit, r.effective_from, p.key)
           r.independence_unit, r.outlet, r.url, r.published_at, r.effective_from,
           r.attribution, p.key AS product, p.value::numeric AS price,
           fuel_price_text_key(r.evidence ->> p.key) AS text_key
      FROM current_reading r
      CROSS JOIN LATERAL jsonb_each_text(r.prices) p
     WHERE r.verdict = 'prices'
     ORDER BY r.independence_unit, r.effective_from, p.key, r.fetched_at DESC, r.report_id DESC)
SELECT effective_from, product, price,
       count(*)                                        AS units,
       count(*) FILTER (WHERE attribution = 'named')   AS named_units,
       count(DISTINCT text_key)                        AS distinct_texts,
       array_agg(outlet ORDER BY published_at NULLS LAST, outlet)                  AS outlets,
       array_remove(array_agg(url ORDER BY published_at NULLS LAST, outlet), NULL) AS urls,
       min(published_at)                               AS first_published
  FROM latest
 GROUP BY effective_from, product, price;

CREATE VIEW fuel_price_believed AS
SELECT v.*
  FROM fuel_price_votes v
 WHERE v.units >= 2 AND v.named_units >= 1 AND v.distinct_texts >= 2
   AND NOT EXISTS (
         SELECT 1 FROM fuel_price_votes r
          WHERE r.effective_from = v.effective_from AND r.product = v.product
            AND r.price <> v.price AND r.units >= 2);

CREATE VIEW fuel_price_conflicts AS
SELECT effective_from, product,
       array_agg(price ORDER BY price) AS prices,
       array_agg(units ORDER BY price) AS units
  FROM fuel_price_votes
 WHERE units >= 2
 GROUP BY effective_from, product
HAVING count(*) > 1;

COMMENT ON VIEW fuel_price_believed IS
  'Two independent outlets agree, one names the Petroleum Corporation, the agreement is not one copied text, and no two-unit rival exists.';
