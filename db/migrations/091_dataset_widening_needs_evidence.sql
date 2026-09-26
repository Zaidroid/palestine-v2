-- 091 — a dataset may narrow its source's licence freely, but widening it needs evidence (audit DATABANK-V19, F547).
--
-- 054's check fired only when license_spdx was set, so
--   UPDATE dataset SET commercial_use = true, redistribution = 'open' WHERE key = …
-- succeeded with no evidence and moved rows into the commercial tier. A NARROWING (commercial_use false, a
-- 'no-redistribution' or 'ask' grade, share-alike obligations) stays free — UCDP's dataset row narrows to
-- non-commercial until its terms are read, and that caution must never need paperwork. Anything that GRANTS
-- (commercial use, no share-alike obligation, an open / attribution / share-alike grade) needs the evidence
-- triple, exactly as a licence identifier already did. Measured 2026-09-26: the three datasets that override
-- today pass (UCDP narrows; education and infrastructure carry evidence).
--
-- Rollback: ALTER TABLE dataset DROP CONSTRAINT dataset_widening_needs_evidence;

ALTER TABLE dataset ADD CONSTRAINT dataset_widening_needs_evidence CHECK (
    (commercial_use IS NOT TRUE
     AND share_alike IS NOT FALSE
     AND (redistribution IS NULL OR redistribution IN ('no-redistribution', 'ask')))
    OR (terms_evidence IS NOT NULL AND terms_url IS NOT NULL AND terms_verified_at IS NOT NULL));
