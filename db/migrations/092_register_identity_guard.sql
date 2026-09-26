-- 092 — register datasets: one CURRENT row per identity, whatever its date (audit DATABANK-V03, F339).
--
-- 052's unique index is (dataset_id, identity_key, occurred_at): a hypertable's unique index must carry its
-- partitioning column. For the six datasets whose identity leaves the date OUT — they are registers, not series:
-- schools by school_id, heritage sites by name, land orders and outposts by name, infrastructure by geo_key, IODA
-- outages by their exact start — a new v1 generation stamped with a new "masquerade" date passes that index, and
-- only the loader's in-memory guard stops it. This trigger is the database's own refusal: a keyed row may not be
-- inserted while a CURRENT row of the same dataset already holds that key. A correction still works — the loader
-- closes the old row (sys_period ends) in the same transaction before it inserts the new one.
--
-- The register list is data, not code: dataset.attrs.identity_scope = 'register'.
--
-- Rollback: DROP TRIGGER observation_register_identity_trg ON observation;
--           DROP FUNCTION observation_register_identity();
--           UPDATE dataset SET attrs = attrs - 'identity_scope' WHERE attrs->>'identity_scope' = 'register';

UPDATE dataset SET attrs = COALESCE(attrs, '{}'::jsonb) || '{"identity_scope": "register"}'::jsonb
 WHERE key IN ('v1_connectivity_ioda', 'v1_culture_heritage_composite', 'v1_education_hdx',
               'v1_infrastructure_hdx', 'v1_land_ocha', 'v1_land_peace_now');

CREATE OR REPLACE FUNCTION observation_register_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.identity_key IS NULL OR upper(NEW.sys_period) IS NOT NULL THEN
    RETURN NEW;
  END IF;
  IF EXISTS (SELECT 1 FROM dataset d WHERE d.dataset_id = NEW.dataset_id
                AND d.attrs->>'identity_scope' = 'register')
     AND EXISTS (SELECT 1 FROM observation o
                  WHERE o.dataset_id = NEW.dataset_id AND o.identity_key = NEW.identity_key
                    AND upper(o.sys_period) IS NULL) THEN
    RAISE EXCEPTION 'register dataset % already holds a current row for identity % (092: close it first)',
                    NEW.dataset_id, NEW.identity_key USING ERRCODE = 'unique_violation';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS observation_register_identity_trg ON observation;
CREATE TRIGGER observation_register_identity_trg
  BEFORE INSERT ON observation
  FOR EACH ROW EXECUTE FUNCTION observation_register_identity();
