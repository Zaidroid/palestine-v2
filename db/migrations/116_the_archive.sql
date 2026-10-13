-- 116 · the archive: every news text and report the house holds, whole and searchable
-- 2026-10-13
--
-- Zaid, 13 October: the news should "cover everything", so that a question for
-- an infographic (what a lighter cost in Gaza, how many children were detained
-- in the West Bank) can be answered from what is held, "as much as possible
-- from 1948". Measured that day: the store's news began in the summer of 2026,
-- v1 kept 19,185 articles and 36,832 channel posts that no v2 reader could
-- search, and the search itself matched exact letters, newest first, with no
-- date range.
--
-- This is the place those texts go. It is a third thing beside the live
-- readings and the databank, and it is kept apart from both on purpose:
--
--   * NOT `claim`. The classifier reads every unclassified claim every five
--     minutes and turns West Bank posts into incidents on the live map. A
--     million posts from 2023 must never be offered to it.
--   * NOT `source`. That table drives the poller, the silence alarms and the
--     licence listing. A publisher the archive reads gets a row in
--     `archive_source`; `source_key` links the two where the same publisher is
--     in both.
--
-- Three tables and one trigger. Nothing existing is altered and no existing
-- table is locked.
--
--   archive_source     one row per publisher feed (a channel, an outlet, a
--                      report series): what it is and under what terms.
--   document           one row per text. `terms` is the search vector; it is
--                      written by ingest/archive.py from ingest/archive_text.py
--                      (Arabic words folded and lightly stemmed in one place,
--                      the same way for a stored text and for a question; the
--                      database's own Arabic stemmer was measured the same day
--                      and sends «ولاعة», «الولاعات» and «ولاعات» to three
--                      different stems). `terms_version` says which rule wrote it.
--   document_history   the prior text of a document whose words changed (a
--                      post edited, an article corrected). No text is lost.
--   archive_load       what each reader has already brought, so a nightly run
--                      reads only what is new.
--
-- Who may see a row is not decided here. No route serves this table yet; the
-- house reads it with ops/ask_archive.py. A partner door needs the licence
-- tier applied per publisher and is a later, separate step.
--
-- Rollback: DROP TABLE document_history, document, archive_load, archive_source;
--           DROP FUNCTION document_keep_prior();

CREATE TABLE IF NOT EXISTS archive_source (
  key            text PRIMARY KEY,                 -- tg:qudsn · web:middleeasteye · report:ocha_opt
  name           text NOT NULL,
  kind           text NOT NULL CHECK (kind IN ('channel', 'outlet', 'reports', 'chronology')),
  home_url       text,
  lang           text,
  source_key     text,                             -- source.key when the same publisher is in the registry
  license_spdx   text,                             -- NULL = no licence statement read yet
  terms_url      text,
  terms_note     text,
  attribution    text,
  attrs          jsonb NOT NULL DEFAULT '{}',
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document (
  doc_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source         text NOT NULL REFERENCES archive_source(key),
  external_id    text NOT NULL,                    -- the publisher's own id: post number, article URL
  kind           text NOT NULL CHECK (kind IN ('post', 'article', 'report', 'statement', 'entry')),
  url            text,
  title          text,
  body           text NOT NULL DEFAULT '',
  extra          text,                             -- searchable additions: a link preview's title and summary
  lang           text,
  published_at   timestamptz,
  published_precision text NOT NULL DEFAULT 'second'
                 CHECK (published_precision IN ('second', 'day', 'month', 'year')),
  via            text NOT NULL,                    -- the reader that brought this version
  via_rank       smallint NOT NULL DEFAULT 0,      -- a fuller reader outranks a thinner one
  content_hash   text NOT NULL,
  attrs          jsonb NOT NULL DEFAULT '{}',
  terms          tsvector,
  terms_version  smallint,
  first_seen     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source, external_id)
);

CREATE INDEX IF NOT EXISTS document_terms_idx ON document USING gin (terms);
CREATE INDEX IF NOT EXISTS document_published_idx ON document (published_at DESC);
CREATE INDEX IF NOT EXISTS document_source_published_idx ON document (source, published_at DESC);

CREATE TABLE IF NOT EXISTS document_history (
  history_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  doc_id         bigint NOT NULL,
  source         text NOT NULL,
  external_id    text NOT NULL,
  title          text,
  body           text NOT NULL,
  extra          text,
  via            text NOT NULL,
  content_hash   text NOT NULL,
  attrs          jsonb NOT NULL,
  valid_from     timestamptz NOT NULL,             -- when this version was written
  valid_to       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS document_history_doc_idx ON document_history (doc_id);

CREATE OR REPLACE FUNCTION document_keep_prior() RETURNS trigger AS $$
BEGIN
  IF NEW.content_hash IS DISTINCT FROM OLD.content_hash THEN
    INSERT INTO document_history (doc_id, source, external_id, title, body, extra, via,
                                  content_hash, attrs, valid_from)
    VALUES (OLD.doc_id, OLD.source, OLD.external_id, OLD.title, OLD.body, OLD.extra, OLD.via,
            OLD.content_hash, OLD.attrs, OLD.updated_at);
    NEW.updated_at := now();
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS document_keep_prior_trg ON document;
CREATE TRIGGER document_keep_prior_trg BEFORE UPDATE ON document
  FOR EACH ROW EXECUTE FUNCTION document_keep_prior();

CREATE TABLE IF NOT EXISTS archive_load (
  reader         text NOT NULL,                    -- tg_public · v1_news · v1_alerts · v2_claim
  item           text NOT NULL,                    -- a file name, or 'watermark'
  mark           text,                             -- the file's size+mtime, or the highest id read
  rows           integer NOT NULL DEFAULT 0,
  loaded_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (reader, item)
);

COMMENT ON TABLE document IS
  'The archive: one row per news text or report, whole, with its date, publisher and link. Written by ingest/archive.py; searched with ops/ask_archive.py. Kept apart from claim (the classifier never reads it) and from source (the poller and the alarms never see its publishers). 116.';
COMMENT ON COLUMN document.terms IS
  'Search vector. Arabic words are folded and stemmed by ingest/archive_text.py (terms_version says which rule); Latin words by the english configuration. A question must be turned into a tsquery by the same module.';
