-- 001 — extensions. Order matters: postgis before any geometry column.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- fuzzy alias matching (resolve/geo.py)
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- exclusion constraints on sys_period
