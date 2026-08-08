-- 057 — the eleven letters become a ledger
--
-- Eleven publishers hold data we want and terms that forbid taking it:
-- Airwars, PCHR, Al Mezan, JDECO, Peace Now, PWA, B'Tselem, DCIP, WSRC,
-- PERC, MoH Ramallah. For each, the answer is not in a licence file — it is
-- in a conversation nobody has had yet.
--
-- Today that state lives in a plan document and in my memory of writing it.
-- Neither can be queried, and neither stops the obvious accident: a source
-- whose terms say "ask" gets marked commercial because someone remembers a
-- friendly email. A grant is a DATED, SCOPED, EXPIRING artifact with text
-- you can quote back, and it belongs in the database beside the licence it
-- overrides.
--
-- SENDING IS ZAID'S. The drafts are mine; `status` moves to 'asked' only
-- when he sends, and to 'granted' only with `grant_text` filled in — the
-- constraint below makes an undocumented grant unrepresentable rather than
-- merely discouraged.

CREATE TABLE IF NOT EXISTS source_permission (
    source_key    text PRIMARY KEY,
    status        text NOT NULL DEFAULT 'not_asked',
    scope         text,           -- what exactly was requested or granted
    asked_at      date,
    answered_at   date,
    expires_at    date,           -- a grant with an end date; NULL = open
    grant_text    text,           -- the operative sentence of the permission
    contact       text,
    letter_path   text,           -- the draft in db/scout/letters/
    notes         text,
    updated_at    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT source_permission_status CHECK (status IN (
        'not_asked', 'asked', 'granted', 'refused', 'no_reply')),

    -- A grant nobody can quote is not a grant. This is the whole point of
    -- the table: it makes "I'm sure they said yes" unstorable.
    CONSTRAINT granted_needs_text CHECK (
        status <> 'granted'
        OR (grant_text IS NOT NULL AND answered_at IS NOT NULL
            AND scope IS NOT NULL)),
    CONSTRAINT asked_needs_date CHECK (
        status = 'not_asked' OR asked_at IS NOT NULL)
);

COMMENT ON TABLE source_permission IS
  'The licence-letter ledger. A publisher''s terms say what anyone may do; '
  'this says what WE were told we may do, when, by whom, and until when.';
COMMENT ON COLUMN source_permission.expires_at IS
  'A grant that expires is the normal case for research access. Gate G5.12 '
  'treats an expired grant as no grant.';

-- The eleven, as drafted. Every one 'not_asked' — that is the true state,
-- and writing it down is what turns "I should chase those" into a queryable
-- backlog with an owner.
INSERT INTO source_permission (source_key, status, scope, letter_path, notes)
VALUES
 ('airwars', 'not_asked',
  'Bulk civilian-harm incident records for Gaza and the West Bank, for a '
  'public non-commercial databank with attribution.',
  'db/scout/letters/airwars.md',
  'CC-BY-NC on the site; bulk redistribution needs explicit consent.'),
 ('pchr', 'not_asked',
  'Weekly report data as structured records rather than PDFs, with '
  'attribution.', 'db/scout/letters/pchr.md',
  'No machine-readable terms published; the reports themselves are public.'),
 ('al_mezan', 'not_asked',
  'Violation database extracts with attribution.',
  'db/scout/letters/al_mezan.md', NULL),
 ('jdeco', 'not_asked',
  'Electricity supply and outage series for the West Bank — the only '
  'first-party source for the proposed energy category.',
  'db/scout/letters/jdeco.md',
  'Utility, not a publisher; likely needs a named contact rather than a '
  'terms page.'),
 ('peace_now_gis', 'not_asked',
  'Settlement Watch GIS layers (boundaries, outposts) beyond the tabular '
  'series already held.', 'db/scout/letters/peace_now_gis.md',
  'The tabular source is already recorded no-license-found (050); this asks '
  'for the geometry specifically.'),
 ('pwa', 'not_asked',
  'Confirmation of the reference year for water data ALREADY granted — the '
  'smallest ask on this list and the one blocking a dataset we can '
  'otherwise use.', 'db/scout/letters/pwa.md',
  'Permission exists; only the vintage is ambiguous.'),
 ('btselem_bulk', 'not_asked',
  'Bulk access to the fatalities database, which their licence calls '
  '"expansive use, which requires express written consent".',
  'db/scout/letters/btselem_bulk.md',
  'See 053''s terms_evidence for btselem: the licence names this exact case.'),
 ('dcip', 'not_asked',
  'Child-fatality records with attribution.', 'db/scout/letters/dcip.md', NULL),
 ('wsrc', 'not_asked',
  'Water Sector Regulatory Council performance indicators.',
  'db/scout/letters/wsrc.md', NULL),
 ('perc', 'not_asked',
  'Palestinian Energy and Natural Resources Authority / regulator series '
  'for the energy category.', 'db/scout/letters/perc.md', NULL),
 ('moh_ramallah', 'not_asked',
  'West Bank health facility and service data — the counterpart to the Gaza '
  'MoH series we already consume via Tech4Palestine.',
  'db/scout/letters/moh_ramallah.md',
  'Gaza MoH is recorded no-license-found (050) and consumed through T4P''s '
  'public-domain compilation; the West Bank ministry has no such route.')
ON CONFLICT (source_key) DO NOTHING;
