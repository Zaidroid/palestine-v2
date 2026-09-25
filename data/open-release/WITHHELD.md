# What this release does not contain

Generated 2026-08-08 by `ops/export_open_data.py`.

The databank holds these records and answers questions about them through the API, where each is a credited fact. They are **not in this release**, because a file is a database and a database is what a licence governs. Every one is a publisher who has not granted a redistribution right, or one whose terms nobody has read yet.

| category | source | licence | rows | span | why |
|---|---|---|---:|---|---|
| connectivity | IODA (Georgia Tech) internet outage detection | `LicenseRef-IODA-All-Rights-Reserved` | 1,000 | 2022-03-02 → 2026-07-24 | the publisher's terms have not been read; quarantined by default rather than assumed |
| prisoners | HaMoked | `no-license-found` | 864 | 2008-05-01 → 2026-06-01 | the publisher grants no redistribution right, or grants one that is conditional and revocable |
| demolitions | UN OCHA oPt — Data on Demolitions | `UN-ToU-NC` | 847 | 2009-01-01 → 2009-01-01 | the publisher grants no redistribution right, or grants one that is conditional and revocable |
| culture | Palestinian heritage register (UNESCO / Ministry of Tourism / NGO reports) | `varies` | 329 | 2026-08-05 → 2026-08-05 | the publisher's terms have not been read; quarantined by default rather than assumed |
| land | Good Shepherd Collective | `LicenseRef-Liberation-License` | 237 | 2025-06-30 → 2026-07-30 | the publisher grants no redistribution right, or grants one that is conditional and revocable |
| land | Peace Now — Settlement Watch | `no-license-found` | 199 | 2026-08-05 → 2026-08-05 | the publisher grants no redistribution right, or grants one that is conditional and revocable |
| settlements | Peace Now — Settlement Watch | `no-license-found` | 51 | 1967-01-01 → 2024-01-01 | the publisher grants no redistribution right, or grants one that is conditional and revocable |
| casualties | UN OCHA oPt — Data on Casualties | `UN-ToU-NC` | 49 | 2008-01-01 → 2026-01-01 | the publisher grants no redistribution right, or grants one that is conditional and revocable |
| prisoners | Addameer Prisoner Support and Human Rights Association (addameer.ps) | `no-license-found` | 26 | 2022-10-01 → 2026-08-01 | the publisher grants no redistribution right, or grants one that is conditional and revocable |

**3,602 rows withheld**, 128,448 released.

Generated from the database, not maintained by hand. If a permission arrives the rows appear in the next release and leave this page automatically.

## The memorial roster

**73,077 named records are also absent** — every identified person killed, with name, date of birth, age and sex. The licence permits publishing them: Tech4Palestine releases the roster as public domain precisely so the names are known, and reducing the dead to a number is the erasure this record exists against.

They are held back from the FILE because the API already decided that reading them should be a deliberate act — `/v2/databank/martyrs_snapshot_2023` returns aggregates unless you pass `memorial=true`. A bulk CSV in a public repository is a different act from an API that makes you ask: it is scraped, mirrored, indexed, and cannot be withdrawn. The aggregate totals are included; `--include-memorial` includes the names, and is meant to be the same deliberate choice.
