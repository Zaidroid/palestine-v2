-- 073 — fuel prices: what may be served as TODAY's price.
--
-- Two measured defects of 072, and the serving rule this series needs:
--
-- 1. THE COPY RULE WAS TOO BROAD. 072 refused any agreement resting on one
--    text. Right for an inferred reading (a shared number, a positional
--    pairing, a cylinder size carried from an earlier clause — an inference
--    repeated over copies of one text is one reading), wrong for a line that
--    states its pairing outright: "السولار: 8.39 شيكل/لتر" reads the same in
--    every faithful reprint of the official list, and 072 refused September's
--    diesel and kerosene for exactly that. Reader fuel_price@3 records per
--    product whether the pairing was inferred; only inferred readings are
--    grouped by text.
--
-- 2. THE NEWEST BELIEVED PRICE IS NOT ALWAYS THE CURRENT ONE. Measured the
--    same day: kerosene's newest believed price was August's 8.56 while
--    September's list said 8.39 and had not yet reached two outlets. Serving
--    8.56 as today's price would have been a stale value presented as current,
--    which is the one thing this system refuses everywhere else.
--
-- fuel_price_current therefore asks, per product: what is the NEWEST list
-- that mentions it at all? If that list's price is believed — or every outlet
-- on it restates the last believed price — it is served. If the newest list
-- is single-outlet or split, the value is withheld and the reported numbers
-- and the last confirmed price are shown beside it. And a price is today's
-- only in the month it was set for: from the 1st of the next month until a
-- new list is read, the old one is `awaiting_list`, not current.

DROP VIEW IF EXISTS fuel_price_current;
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
           CASE
             -- @3 evidence: {"clause": ..., "inferred": bool}. A stated pairing
             -- is its own reading whatever the wording; an inferred one is
             -- grouped with every other copy of the same text.
             WHEN jsonb_typeof(r.evidence -> p.key) = 'object'
                  AND NOT (r.evidence -> p.key ->> 'inferred')::boolean
               THEN 'unit:' || r.independence_unit
             WHEN jsonb_typeof(r.evidence -> p.key) = 'object'
               THEN fuel_price_text_key(r.evidence -> p.key ->> 'clause')
             ELSE fuel_price_text_key(r.evidence ->> p.key)       -- @2 rows
           END AS text_key
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

CREATE VIEW fuel_price_current AS
WITH today AS (SELECT (now() AT TIME ZONE 'Asia/Hebron')::date AS d),
newest AS (                        -- the newest list that mentions the product
    SELECT v.product, max(v.effective_from) AS eff
      FROM fuel_price_votes v, today
     WHERE v.effective_from <= today.d
     GROUP BY v.product),
reported AS (
    SELECT v.product,
           jsonb_agg(jsonb_build_object('price', v.price, 'outlets', v.units,
                                        'names_authority', v.named_units > 0,
                                        'sources', to_jsonb(v.outlets))
                     ORDER BY v.units DESC, v.price) AS reported,
           count(*) AS n_prices,
           min(v.price) AS lo, max(v.price) AS hi
      FROM fuel_price_votes v JOIN newest n ON n.product = v.product AND n.eff = v.effective_from
     GROUP BY v.product),
believed_at_newest AS (
    SELECT b.product, b.price, b.units, b.outlets, b.urls
      FROM fuel_price_believed b JOIN newest n ON n.product = b.product AND n.eff = b.effective_from),
last_confirmed AS (
    SELECT DISTINCT ON (b.product) b.product, b.effective_from, b.price, b.units, b.outlets, b.urls
      FROM fuel_price_believed b, today
     WHERE b.effective_from <= today.d
     ORDER BY b.product, b.effective_from DESC),
judged AS (
    SELECT p.product, p.name_ar, p.name_en, p.unit, p.sort, n.eff AS newest_list,
           r.reported, lc.price AS last_confirmed_price, lc.effective_from AS last_confirmed_from,
           CASE
             WHEN n.eff IS NULL                                      THEN 'no_data'
             WHEN bn.price IS NOT NULL                               THEN 'confirmed'
             -- nobody on the newest list says anything but the last believed price
             WHEN r.n_prices = 1 AND r.lo = lc.price                 THEN 'confirmed'
             WHEN r.n_prices > 1                                     THEN 'conflicting'
             ELSE 'unconfirmed'
           END AS reading,
           CASE WHEN bn.price IS NOT NULL THEN bn.price
                WHEN r.n_prices = 1 AND r.lo = lc.price THEN lc.price END AS price,
           CASE WHEN bn.price IS NOT NULL THEN n.eff
                WHEN r.n_prices = 1 AND r.lo = lc.price THEN lc.effective_from END AS effective_from,
           COALESCE(bn.units, CASE WHEN r.n_prices = 1 AND r.lo = lc.price THEN lc.units END) AS outlets_agreeing,
           COALESCE(bn.urls,  CASE WHEN r.n_prices = 1 AND r.lo = lc.price THEN lc.urls END)  AS source_urls
      FROM fuel_price_product p
      LEFT JOIN newest n            ON n.product = p.product
      LEFT JOIN reported r          ON r.product = p.product
      LEFT JOIN believed_at_newest bn ON bn.product = p.product
      LEFT JOIN last_confirmed lc   ON lc.product = p.product)
SELECT j.product, j.name_ar, j.name_en, j.unit, j.sort,
       -- a price is today's only in the month it was set for
       CASE WHEN j.reading = 'confirmed'
                 AND date_trunc('month', j.newest_list) = date_trunc('month', t.d)
            THEN 'confirmed'
            WHEN j.reading IN ('confirmed', 'unconfirmed', 'conflicting')
                 AND date_trunc('month', j.newest_list) < date_trunc('month', t.d)
            THEN 'awaiting_list'
            ELSE j.reading END                                   AS status,
       CASE WHEN j.reading = 'confirmed'
                 AND date_trunc('month', j.newest_list) = date_trunc('month', t.d)
            THEN j.price END                                     AS price,
       j.effective_from, j.newest_list, j.outlets_agreeing, j.source_urls,
       j.reported, j.last_confirmed_price, j.last_confirmed_from, t.d AS as_of_date
  FROM judged j, today t;

COMMENT ON VIEW fuel_price_current IS
  'Per product: the price served as today''s, or NULL with a status saying why (unconfirmed, conflicting, awaiting_list, no_data).';
