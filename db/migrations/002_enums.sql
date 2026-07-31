-- 002 — controlled vocabularies. Enums (not TEXT+CHECK) so bad values fail at
-- write time; ALTER TYPE ... ADD VALUE extends them without a rewrite.

CREATE TYPE place_kind AS ENUM (
  'region','governorate','city','town','village','locality','neighborhood','camp',
  'checkpoint','crossing','road','station','facility','hospital','school','other'
);

-- How precisely a claim/observation was located. Ordered coarse-last.
CREATE TYPE place_precision AS ENUM (
  'exact','street','station','town','admin2','admin1','region','unknown'
);

-- ARCHITECTURE §3.4: precision is NOT NULL everywhere, so an annual bucket is
-- ('2026-01-01','year') and can never be misread as a day-precision date.
CREATE TYPE time_precision AS ENUM ('exact','hour','day','month','year','unknown');

CREATE TYPE event_status AS ENUM ('believed','retracted','superseded','merged');

CREATE TYPE source_kind AS ENUM (
  'telegram','rss','api','file','satellite','crowd','manual','derived'
);
