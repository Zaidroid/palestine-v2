-- 071 — fuel PRICES: the official monthly maximum, read from the news, believed on agreement.
--
-- Zaid, 2026-09-23: track "live updated prices of fuel in palestine".
--
-- WHAT THE NUMBER IS. The Palestinian General Petroleum Corporation (الهيئة
-- العامة للبترول, Ministry of Finance) sets the MAXIMUM consumer price of
-- petrol 95/98, diesel, kerosene and cooking-gas cylinders for the West Bank
-- ("المحافظات الشمالية"), once a month and sometimes again mid-month
-- (2026-09-07: petrol 95 cut 8.15 -> 7.65). It is a regulated ceiling, not a
-- pump-by-pump observation, and Gaza has no official consumer price at all —
-- so this series is the West Bank's and says so.
--
-- WHERE IT COMES FROM. There is no machine-readable feed. The list reaches the
-- public as news, reposted by every outlet within the hour. So one article is
-- one TRANSCRIPTION (cascade/fuel_price.py), and a price is believed only when
-- two independent outlets transcribed the same number for the same product and
-- the same effective date, and at least one of them named the authority.
-- Measured before this was written: a Telegram channel's unattributed "8.25"
-- (2026-08-30) was wrong, an Israeli price story reposted by two West Bank
-- channels (2026-09-03) named "وزارة المالية" too, and a rumour denial quoted
-- the rumoured 9.56. Agreement is the defence none of those survive.
--
-- APPEND-ONLY. Every transcription is kept, including refusals, so what the
-- reader saw and why it said no stays auditable. Idempotent on
-- (outlet, content, reader version): re-reading the same page is a no-op, a
-- new reader version re-reads and its rows sit beside the old.

CREATE TABLE IF NOT EXISTS fuel_price_product (
    product     text PRIMARY KEY,
    name_ar     text NOT NULL,
    name_en     text NOT NULL,
    unit        text NOT NULL CHECK (unit IN ('ILS/L', 'ILS/cylinder')),
    sort        smallint NOT NULL
);

INSERT INTO fuel_price_product (product, name_ar, name_en, unit, sort) VALUES
    ('gasoline_95', 'بنزين 95',            'Petrol 95',                    'ILS/L',        1),
    ('gasoline_98', 'بنزين 98',            'Petrol 98',                    'ILS/L',        2),
    ('diesel',      'سولار',               'Diesel',                       'ILS/L',        3),
    ('kerosene',    'كاز',                 'Kerosene',                     'ILS/L',        4),
    ('lpg_2_5kg',   'أسطوانة غاز 2.5 كغم', 'Cooking gas cylinder 2.5 kg',  'ILS/cylinder', 5),
    ('lpg_5kg',     'أسطوانة غاز 5 كغم',   'Cooking gas cylinder 5 kg',    'ILS/cylinder', 6),
    ('lpg_12kg',    'أسطوانة غاز 12 كغم',  'Cooking gas cylinder 12 kg',   'ILS/cylinder', 7),
    ('lpg_48kg',    'أسطوانة غاز 48 كغم',  'Cooking gas cylinder 48 kg',   'ILS/cylinder', 8)
ON CONFLICT (product) DO NOTHING;

CREATE TABLE IF NOT EXISTS fuel_price_report (
    report_id          bigserial PRIMARY KEY,
    outlet             text NOT NULL,          -- web domain, or the source key of a claim
    independence_unit  text NOT NULL,          -- COALESCE(independence_group, 'src:'||source_id) | 'web:'||domain
    source_id          integer REFERENCES source(source_id),
    claim_id           bigint,                 -- claim's PK is (claim_id, ingested_at); kept as a plain pointer
    url                text,
    published_at       timestamptz,
    fetched_at         timestamptz NOT NULL DEFAULT now(),
    content_sha256     text NOT NULL,
    bronze_ref         text,
    reader_version     text NOT NULL,
    verdict            text NOT NULL,          -- 'prices' or the reader's refusal code
    attribution        text CHECK (attribution IN ('named', 'implied')),
    effective_from     date,
    effective_basis    text CHECK (effective_basis IN ('explicit', 'period_start')),
    period_month       date,
    prices             jsonb NOT NULL DEFAULT '{}'::jsonb,
    detail             jsonb NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (outlet, content_sha256, reader_version),
    CHECK (verdict <> 'prices' OR (effective_from IS NOT NULL AND prices <> '{}'::jsonb
                                   AND attribution IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS fuel_price_report_eff_idx ON fuel_price_report (effective_from) WHERE verdict = 'prices';
CREATE INDEX IF NOT EXISTS fuel_price_report_url_idx ON fuel_price_report (url);

-- One vote per independent unit per (date, product): the unit's latest word.
CREATE OR REPLACE VIEW fuel_price_votes AS
WITH latest AS (
    SELECT DISTINCT ON (r.independence_unit, r.effective_from, p.key)
           r.independence_unit, r.outlet, r.url, r.published_at, r.effective_from,
           r.attribution, p.key AS product, p.value::numeric AS price
      FROM fuel_price_report r
      CROSS JOIN LATERAL jsonb_each_text(r.prices) p
     WHERE r.verdict = 'prices'
     ORDER BY r.independence_unit, r.effective_from, p.key, r.fetched_at DESC, r.report_id DESC)
SELECT effective_from, product, price,
       count(*)                                        AS units,
       count(*) FILTER (WHERE attribution = 'named')   AS named_units,
       array_agg(outlet ORDER BY published_at NULLS LAST, outlet)          AS outlets,
       array_remove(array_agg(url ORDER BY published_at NULLS LAST, outlet), NULL) AS urls,
       min(published_at)                               AS first_published
  FROM latest
 GROUP BY effective_from, product, price;

-- Believed: two independent units, at least one naming the authority, and no
-- rival price for the same (date, product) that ALSO has two units. A rival
-- with two units is a conflict, and a conflict is served as nothing.
CREATE OR REPLACE VIEW fuel_price_believed AS
SELECT v.*
  FROM fuel_price_votes v
 WHERE v.units >= 2 AND v.named_units >= 1
   AND NOT EXISTS (
         SELECT 1 FROM fuel_price_votes r
          WHERE r.effective_from = v.effective_from AND r.product = v.product
            AND r.price <> v.price AND r.units >= 2);

CREATE OR REPLACE VIEW fuel_price_conflicts AS
SELECT effective_from, product,
       array_agg(price ORDER BY price) AS prices,
       array_agg(units ORDER BY price) AS units
  FROM fuel_price_votes
 WHERE units >= 2
 GROUP BY effective_from, product
HAVING count(*) > 1;

COMMENT ON TABLE fuel_price_report IS
  'One transcription of a fuel price announcement per (outlet, content, reader). Append-only; refusals kept.';
COMMENT ON VIEW fuel_price_believed IS
  'A price two independent outlets agree on, one naming the Petroleum Corporation, with no two-unit rival.';
