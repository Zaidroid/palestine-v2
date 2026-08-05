-- 043 — the heritage register's composite source gets its own quarantined row
--
-- T2.2 review finding (db/mappings/culture.yaml): every culture record names
-- the composite "UNESCO, Ministry of Tourism, NGO Reports", and licenses.json
-- aliases the PIECES of that string to `unesco` — CC-BY-SA-3.0-IGO,
-- commercial_use=true. Routing 329 rows there would grant a commercial UNESCO
-- licence to 312 sites that are National-Heritage-listed, not UNESCO-listed,
-- and whose own records say license 'varies'. Only 17 rows are genuinely
-- World Heritage Sites.
--
-- Quarantine-by-default (042's rule): the composite gets its own row at
-- 'varies' / commercial_use=false until Zaid establishes the real terms.

INSERT INTO source (key, name, kind, license_spdx, commercial_use,
                    attribution_text, authority_rank, active)
VALUES ('heritage_composite',
        'Palestinian heritage register (UNESCO / Ministry of Tourism / NGO reports)',
        'file', 'varies', false,
        'Heritage site data compiled from UNESCO, the Palestinian Ministry of Tourism and Antiquities, and NGO reports.',
        3, true)
ON CONFLICT (key) DO NOTHING;
