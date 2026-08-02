-- 017 — where our READING of a claim lives, separately from the claim.
--
-- `claim` is the immutable record of what a source asserted: "Never updated
-- after insert (except event_id on resolution)" (005). The news cascade wanted
-- to stamp its verdict onto `claim.claim_type`, which would have broken that —
-- and broken it in the way that matters, because a classification is not
-- something the source said. It is something we concluded, with a classifier
-- that will be wrong sometimes and will be improved repeatedly.
--
-- Keeping the two apart buys the thing the immutability rule exists for: the
-- classifier can be re-run over the whole corpus after every change, producing
-- a different answer, without any claim's record of what was actually posted
-- being altered. `classifier_version` makes those runs comparable, so a change
-- in yield can be attributed to the classifier rather than to the news.
--
-- Rejections are stored too, not just hits. Knowing that 347 of 949 claims were
-- rejected as Gaza/international/commentary is what tells you whether the
-- channel mix is worth polling — and a rejection reason that suddenly stops
-- appearing is how you notice the classifier broke.

CREATE TABLE claim_classification (
  claim_id           BIGINT      NOT NULL,
  classifier         TEXT        NOT NULL,
  classifier_version TEXT        NOT NULL,
  verdict            TEXT        NOT NULL CHECK (verdict IN ('incident','rejected','unclear')),
  incident_type      TEXT,
  reject_reason      TEXT,
  place_id           BIGINT      REFERENCES place(place_id),
  place_text         TEXT,
  governorate        TEXT,
  confidence         REAL        NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 1),
  event_id           BIGINT      REFERENCES event(event_id),
  classified_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (claim_id, classifier)
);
COMMENT ON TABLE claim_classification IS
  'Our reading of a claim, held apart from the immutable claim itself so the classifier can be re-run and revised without rewriting what a source said.';

CREATE INDEX claim_classification_verdict_idx ON claim_classification (verdict, classified_at DESC);
CREATE INDEX claim_classification_event_idx   ON claim_classification (event_id)
  WHERE event_id IS NOT NULL;
CREATE INDEX claim_classification_type_idx    ON claim_classification (incident_type)
  WHERE incident_type IS NOT NULL;
