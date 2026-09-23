-- Gate 1 (fuel) — the PRICE vertical, which replaced availability on 2026-09-23.
--
-- Availability's gate (G1.1-G1.9) was retired with it: tests/retired/.
-- These hold the serving contract of migrations 071-073: a number is served
-- as today's official price only when two independent outlets agree, one of
-- them naming the Petroleum Corporation, nobody credible disagrees, and the
-- list was set for the current month. Everything else is served as null with
-- a status that says why.

\echo '--- GP.1: no served price without two independent outlets, one naming the authority ---'
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' served price(s) with no confirmation behind them' END
  FROM fuel_price_current c
 WHERE c.price IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM fuel_price_believed b
                    WHERE b.product = c.product AND b.price = c.price
                      AND b.units >= 2 AND b.named_units >= 1 AND b.distinct_texts >= 2);

\echo '--- GP.2: a price is today''s only in the month its list was set for ---'
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' price(s) served from a previous month''s list' END
  FROM fuel_price_current
 WHERE price IS NOT NULL
   AND date_trunc('month', newest_list) <> date_trunc('month', as_of_date);

\echo '--- GP.3: a product whose newest list is contested is never served ---'
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' contested product(s) served anyway' END
  FROM fuel_price_current c
  JOIN fuel_price_conflicts f ON f.product = c.product AND f.effective_from = c.newest_list
 WHERE c.price IS NOT NULL;

\echo '--- GP.4: nothing is served from the future ---'
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' price(s) dated after today' END
  FROM fuel_price_current
 WHERE price IS NOT NULL AND effective_from > as_of_date;

\echo '--- GP.5: every accepted reading since @2 carries the text it was read from ---'
SELECT CASE WHEN count(*) = 0 THEN 'PASS'
            ELSE 'FAIL: ' || count(*) || ' accepted reading(s) with no evidence' END
  FROM fuel_price_report
 WHERE verdict = 'prices' AND reader_version <> 'fuel_price@1'
   AND (evidence = '{}'::jsonb
        OR EXISTS (SELECT 1 FROM jsonb_object_keys(prices) k WHERE NOT evidence ? k));

\echo '--- context: what is served now ---'
SELECT product, status, price, effective_from, outlets_agreeing FROM fuel_price_current ORDER BY sort;
