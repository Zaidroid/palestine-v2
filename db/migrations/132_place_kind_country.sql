-- 132 — a place can be a country (2026-10-19).
--
-- 45,197 UNHCR rows name the host country of Palestinian refugees and asylum
-- seekers in attrs only (name and ISO3); the gazetteer had no kind for a
-- country, so the diaspora could not be asked for by place. This adds the
-- kind; migration 133 adds the 116 countries and places the rows. The two are
-- separate because a new enum value cannot be used in the transaction that
-- adds it.
ALTER TYPE place_kind ADD VALUE IF NOT EXISTS 'country';
