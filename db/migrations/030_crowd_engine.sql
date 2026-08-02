-- 030 — P2. The crowd reporting ENGINE.
--
-- Zaid's scope, verbatim: "a system/engine with self improvement automated
-- system to track crowd reports for all fields that we can track in this tier".
-- Three commitments follow, and this migration is what makes them structural
-- rather than aspirational:
--
--   1. AN ENGINE, NOT AN ENDPOINT. One submission and scoring path. There is no
--      fuel form and no checkpoint form; there is one path, and which fields it
--      accepts is a matter of configuration.
--   2. ALL FIELDS. A new state kind becomes crowd-reportable by setting a flag
--      and listing its vocabulary in state_kind_config — no new code.
--   3. SELF-IMPROVING, AUTOMATICALLY. Reputation and independence are measured
--      from outcomes on a timer, by the loops that already exist.
--
-- WHY SO LITTLE IS BEING ADDED
-- Almost nothing new is needed, and that is the point. A crowd report is a
-- `state_observation` with a crowd `source_id`; from there the existing
-- machinery already does the work — copy-collapse groups colluding reporters,
-- the noisy-OR combines independent ones, Loop A weights them by what they have
-- earned, and the three serving gates refuse to publish anything
-- under-evidenced. The corroboration model was written generic over sources
-- before there was a crowd to apply it to, so the crowd path plugs in rather
-- than being bolted on.
--
-- ============================================================================
-- THE HARD PART: ONE PERSON WITH FIVE PHONES
-- ============================================================================
-- Copy-collapse showed nine channels agreeing 99.5% of the time are ONE
-- observer. A crowd is that same problem with an adversary in place of a
-- copy-paste bot: five accounts run by one person look exactly like five
-- independent confirmations, and noisy-OR would take them to 0.97.
--
-- The answer is the mirror of the rule this project already applies to
-- reputation. Reputation is EARNED, never seeded — a newcomer's Wilson lower
-- bound is 0.21 no matter how right they have been so far. So:
--
--     INDEPENDENCE IS EARNED, NEVER ASSUMED.
--
-- Every new submitter starts in the shared independence group
-- 'crowd:unverified'. A hundred fresh accounts in that group are ONE unit, so
-- a sock-puppet ring gets exactly the weight of one anonymous stranger:
--
--     0.85 (single unit) x 0.21 (unearned trust) = 0.18
--
-- which is below every confidence floor in state_kind_config (0.25-0.35). A
-- ring cannot move a served value at all — not because a rule names sock
-- puppets, but because it never had the standing to. Genuine independent
-- citizens are also throttled to one unit while unverified, which is
-- over-conservative and is the correct direction to be wrong in.
--
-- Separation is then earned the same way copy-collapse grants it to channels:
-- learn/crowd_independence.py promotes a submitter to their own unit once they
-- have enough co-observed history AND their agreement with every other crowd
-- submitter sits below the copy threshold. An adversary can only earn five
-- units by making five accounts behave like five genuinely different observers
-- over time, which is indistinguishable from actually being five people.
--
-- ============================================================================
-- P2.4: THE ASYMMETRY, AND WHY IT LIVES IN BELIEF RATHER THAN AT THE DOOR
-- ============================================================================
-- Zaid decides the policy; this is the mechanism and the proposed default.
--
-- The two failure directions do not cost the same. A false "closed" sends a
-- family the long way round: wasted time and fuel. A false "open" sends them
-- TOWARD a checkpoint that is shut, or an army position — a wasted journey at
-- best and a confrontation at worst. Same for fuel: a false "no diesel" costs a
-- detour, a false "has diesel" spends a tank that could not be spared.
--
-- So the reassuring values are the guarded ones. `crowd_gated_values` lists,
-- per kind, the values a crowd report may not carry ALONE — it may corroborate
-- them freely, and it may raise a caution alone. Everything else is unchanged.
--
-- The gate is applied when belief is COMPUTED, not when the report is written.
-- That matters: corroboration arrives later, and a report that was lone at
-- 14:02 may be one of three by 14:09. Gating at the door would require going
-- back and editing an observation — mutating a record of what somebody said —
-- and this system does not do that. Gating in the belief step means the same
-- report simply starts counting the moment it is no longer alone.

-- ── 1. Which fields the crowd may report, and in what words ──────────────────
-- Commitment 2 lives here: a new kind becomes reportable by UPDATEing this
-- table, and no code changes.

ALTER TABLE state_kind_config
  ADD COLUMN IF NOT EXISTS crowd_reportable  boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS crowd_values      text[]  NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS crowd_gated_values text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS crowd_min_units   integer NOT NULL DEFAULT 2,
  ADD COLUMN IF NOT EXISTS crowd_max_per_hour integer NOT NULL DEFAULT 6;

COMMENT ON COLUMN state_kind_config.crowd_reportable IS
  'Whether the engine accepts crowd submissions for this kind. Off by default: '
  'a field becomes reportable by an explicit decision, never by being added.';

COMMENT ON COLUMN state_kind_config.crowd_values IS
  'The complete vocabulary a submitter may use. An enum, not free text — the '
  'engine rejects anything else, so no parser stands between a person and the '
  'record of what they said.';

COMMENT ON COLUMN state_kind_config.crowd_gated_values IS
  'P2.4. Values a crowd report may not assert ALONE, because being wrong in '
  'this direction is reassuring and reassurance is what gets someone hurt. '
  'Corroboration is always allowed; only sole authorship is withheld.';

COMMENT ON COLUMN state_kind_config.crowd_min_units IS
  'Independent units required before a gated value may be served. 2 means one '
  'crowd report plus any other independent observer — including one other '
  'crowd submitter who has EARNED their own unit.';

COMMENT ON COLUMN state_kind_config.crowd_max_per_hour IS
  'P2.2. Reports per submitter per place per hour. Above this the report is '
  'still stored — nothing is discarded — but recorded as rate_limited and left '
  'out of belief.';

-- The vocabulary of each kind, taken from what the parsers already produce, so
-- a crowd report and a channel report are the same statement in the same words
-- and corroborate each other directly. A crowd report that could not be
-- expressed in the same vocabulary could never confirm or contradict anything.
UPDATE state_kind_config SET
  crowd_reportable = true,
  crowd_values = ARRAY['open','congested','slow','closed'],
  -- 'open' is reassuring: it is the one that sends someone toward the
  -- checkpoint. 'congested' and 'slow' are cautions and are not gated.
  crowd_gated_values = ARRAY['open']
WHERE state_kind IN ('checkpoint_status', 'checkpoint_flow');

UPDATE state_kind_config SET
  crowd_reportable = true,
  crowd_values = ARRAY['present','absent'],
  -- 'absent' — "no army here" — is the reassuring direction. A sighting of
  -- soldiers is a caution and one person may raise it alone.
  crowd_gated_values = ARRAY['absent']
WHERE state_kind IN ('checkpoint_idf', 'checkpoint_police',
                     'checkpoint_settlers', 'checkpoint_inspection');

UPDATE state_kind_config SET
  crowd_reportable = true,
  crowd_values = ARRAY['available','unavailable'],
  -- 'available' spends a tank of fuel to find out it was wrong, during a
  -- shortage, which is the scenario this vertical exists for.
  crowd_gated_values = ARRAY['available'],
  -- Queues move. A station can genuinely change twice in an hour and someone
  -- standing in the queue is the best-placed person to say so.
  crowd_max_per_hour = 10
WHERE state_kind IN ('fuel_diesel', 'fuel_gasoline', 'cooking_gas');

UPDATE state_kind_config SET
  crowd_reportable = true,
  crowd_values = ARRAY['available','unavailable'],
  crowd_gated_values = ARRAY['available']
WHERE state_kind IN ('power', 'water', 'internet');

UPDATE state_kind_config SET
  crowd_reportable = true,
  crowd_values = ARRAY['open','closed'],
  crowd_gated_values = ARRAY['open']
WHERE state_kind = 'road_closure';

-- weather is deliberately NOT crowd-reportable. Open-Meteo is a better observer
-- than a person at a window, the failure it guards against is heat risk rather
-- than a journey, and accepting reports the system has no use for trains
-- submitters that reporting does not matter.

-- ── 2. Who the submitters are ────────────────────────────────────────────────
-- A submitter IS a source (kind='crowd'), so every existing mechanism — Loop A,
-- copy-collapse, the noisy-OR, the serving gates — applies without knowing that
-- a crowd exists. This table holds only what is crowd-specific.

CREATE TABLE IF NOT EXISTS submitter (
  source_id      integer PRIMARY KEY REFERENCES source(source_id),
  handle         text        NOT NULL UNIQUE,
  secret_hash    text        NOT NULL,
  channel        text        NOT NULL CHECK (channel IN ('http','mcp','telegram','import')),
  created_at     timestamptz NOT NULL DEFAULT now(),
  last_seen_at   timestamptz,
  status         text        NOT NULL DEFAULT 'active'
                             CHECK (status IN ('active','blocked')),
  blocked_reason text,
  -- Set when learn/crowd_independence.py grants this submitter their own
  -- independence unit. NULL means they are still inside 'crowd:unverified' and
  -- count as a fraction of one observer alongside everyone else there.
  independent_since timestamptz,
  note           text
);

COMMENT ON TABLE submitter IS
  'Crowd reporters. One row per person, joined 1:1 to a source row so the rest '
  'of the system needs no concept of a crowd. Identity exists to make '
  'reputation and rate limiting possible, not to identify anybody: the handle '
  'is chosen and the secret is stored only as a hash.';

COMMENT ON COLUMN submitter.independent_since IS
  'When this submitter earned their own independence unit. NULL = still in the '
  'shared crowd:unverified group, where any number of accounts count as one '
  'observer. Independence is earned, never assumed — the mirror of the rule '
  'that makes reputation earned, and the defence against one person with five '
  'phones.';

COMMENT ON COLUMN submitter.secret_hash IS
  'sha256 of the submission token. The plaintext is shown once at registration '
  'and never stored, so a database leak cannot be used to submit as anybody.';

CREATE INDEX IF NOT EXISTS submitter_status_idx ON submitter (status)
  WHERE status <> 'active';

-- ── 3. Retaining what the engine refuses ─────────────────────────────────────
-- A rejected report is still something a person said, and the retention rule
-- has no exception for reports we did not like. `rate_limited` and `rejected`
-- join the modality vocabulary; REFRESH_SQL already filters on
-- modality='assertion', so these are recorded, queryable, available to the
-- abuse loops, and structurally incapable of reaching a served value.

ALTER TABLE state_observation DROP CONSTRAINT IF EXISTS state_observation_modality_check;
ALTER TABLE state_observation ADD CONSTRAINT state_observation_modality_check
  CHECK (modality IN ('assertion','question','unparsed','rate_limited','rejected'));

COMMENT ON COLUMN state_observation.modality IS
  'assertion = counts toward belief. question/unparsed = recorded, not '
  'believed. rate_limited/rejected = a crowd report the engine would not act '
  'on, kept because the retention rule has no exception for reports we did not '
  'like, and because the abuse loops need to see them.';

-- ── 4. The shared starting group ─────────────────────────────────────────────
-- Registered here rather than implied by a string literal in code, so that
-- `SELECT * FROM source_independence_group` shows the crowd's standing next to
-- the copysets it is modelled on.

INSERT INTO source (key, name, kind, license_spdx, commercial_use,
                    attribution_text, authority_rank, independence_group,
                    independence_note, active)
VALUES ('crowd_unverified_anchor',
        'Crowd — unverified submitters (shared independence unit)',
        'crowd', 'NONE', false, 'Crowd reports', 5, 'crowd:unverified',
        'Anchor row. Every new submitter joins this group until they earn '
        'their own unit, so any number of unverified accounts count as ONE '
        'observer. This is the defence against one person with five phones.',
        false)
ON CONFLICT (key) DO NOTHING;
