"""Build the open-data release — the only sanctioned way this leaves as a file.

Zaid is open-sourcing the project (2026-08-08), non-commercial, small circle
to begin with. This exists so that the data half of that release is correct
by construction instead of by somebody remembering, because the failure mode
is a single `pg_dump` that ships 2,602 rows nobody granted us the right to
redistribute — and once a repository is public that cannot be taken back.

THREE THINGS IT REFUSES TO GET WRONG.

  1. It reads `databank_bulk`, never `databank_serving`. Serving answers
     queries with credited facts; bulk hands over a database. A licence
     governs the second.

  2. It writes WITHHELD.md beside the data. An export that is quietly short
     reads as "this is everything", and a reader comparing it against the API
     would find rows here that are missing there with no explanation. Law 4:
     what is absent is counted, by reason.

  3. It refuses to run if the release would contain share-alike rows without
     the release itself declaring a compatible licence. 6,562 rows are ODbL
     or CC-BY-SA, and ODbL's share-alike binds a derived database whether or
     not money changes hands — going open source TRIGGERS that obligation
     rather than avoiding it. Pass --license to state what the release is
     offered under; the check reads it.

THREE COPYLEFTS, NONE COMPATIBLE. Measured when the guard first fired:
19,139 bulk rows are share-alike, under ODbL-1.0 (6,548), CC-BY-SA (14) and
WHO's CC-BY-NC-SA-3.0-IGO (12,577). Those three cannot coexist inside one
relicensed database — ODbL and CC-BY-SA are incompatible copylefts, and the
NC one cannot enter a non-NC release at all. So a single-licence aggregate of
this databank is not merely inadvisable, it is impossible.

The standard answer, and the default here, is a COLLECTION: each source's
rows in their own file under their own licence, nothing relicensed, no
derived database formed. ODbL itself draws that line (a Collective Database
is not a Derivative Database). It is also the honest description of what this
databank is — a set of other people's measurements, kept together and
credited, not a new work.

Run:  .venv/bin/python -m ops.export_open_data                      # collection
      .venv/bin/python -m ops.export_open_data --license ODbL-1.0   # one aggregate
      .venv/bin/python -m ops.export_open_data --license CC-BY-4.0 --exclude-share-alike
"""
from __future__ import annotations

import csv
from collections import Counter
import gzip
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolve.db import connect                                   # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "open-release"

# THE MEMORIAL GATE, and why an export needs one the API already has.
#
# 73,077 rows are named people: name_ar, name_en, date of birth, age, sex.
# The licence permits it — Tech4Palestine publishes the roster as public
# domain precisely so the names are known, and reducing the dead to a number
# is the erasure this databank exists against.
#
# But serve/app.py already decided (2026-08-05) that READING those names
# should be a deliberate act: /v2/databank/martyrs_snapshot_2023 returns
# aggregates unless you pass memorial=true, and says so in the response. A
# bulk CSV in a public repository is a different act from an API that makes
# you ask — it is scraped, mirrored, indexed, and cannot be withdrawn.
#
# So the export honours the same gate. Not because the data is secret, but
# because the platform made a decision and an export that silently overrides
# it is the platform disagreeing with itself. --include-memorial is how you
# make the same deliberate choice the API asks for.
MEMORIAL_FILTER = ("NOT (v1_category = 'martyrs_snapshot_2023' "
                   "AND indicator = 'martyrs.identified_killed')")

# A release licence is compatible with the share-alike rows inside it only if
# it carries the same copyleft. This is deliberately a short, conservative
# list: guessing that two copyleft licences are compatible is how a project
# ends up in breach of both.
SHARE_ALIKE_OK = {
    "ODbL-1.0": {"ODbL-1.0"},
    "CC-BY-SA-4.0": {"CC-BY-SA", "CC-BY-SA-3.0-IGO", "CC-BY-SA-4.0"},
}

COLUMNS = ("occurred_at", "occurred_precision", "indicator", "value_num",
           "value_text", "unit", "place_id", "v1_category", "dataset_key",
           "source_key", "source_name", "license_spdx", "attribution_text",
           "share_alike", "redistribution", "attrs")


def export_collection(include_memorial: bool = False) -> int:
    """One file per source, each under its own licence. Nothing relicensed.

    This is the default because it is the only shape that can hold all of it:
    three incompatible copylefts live in this databank and no aggregate
    licence exists that satisfies them together. It is also the truest
    description of the thing — other people's measurements, kept together
    and credited, rather than a new work claiming a licence of its own.
    """
    mem_sql = "true" if include_memorial else MEMORIAL_FILTER
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("by-source/*.csv.gz"):
        stale.unlink()
    (OUT / "by-source").mkdir(exist_ok=True)
    manifest, total = [], 0
    with connect() as conn, conn.cursor() as cur:
        # One file per (source, LICENCE TUPLE), not per source (audit V13,
        # 2026-09-26): licence is dataset-grained since 054, and `hdx` already
        # carries two tuples (education CC-BY-4.0, infrastructure
        # CC-BY-IGO-3.0) — the old fetchone() wrote one of them over the whole
        # file. A source with one tuple keeps its plain file name.
        cur.execute("""SELECT DISTINCT source_key, source_name, license_spdx,
                              attribution_text, terms_url, share_alike
                       FROM databank_bulk ORDER BY 1, 3, 4""")
        tuples = cur.fetchall()
        per_key = Counter(t[0] for t in tuples)
        seen: Counter = Counter()
        for key, name, lic, attribution, terms, share_alike in tuples:
            seen[key] += 1
            fname = (f"{key}.csv.gz" if per_key[key] == 1 else
                     f"{key}__{re.sub(r'[^a-z0-9]+', '-', (lic or 'unlicensed').lower()).strip('-')}"
                     f"-{seen[key]}.csv.gz")
            cur.execute(f"SELECT {', '.join(COLUMNS)} FROM databank_bulk "
                        f"WHERE source_key = %s AND {mem_sql} "
                        "AND license_spdx IS NOT DISTINCT FROM %s "
                        "AND attribution_text IS NOT DISTINCT FROM %s "
                        "AND terms_url IS NOT DISTINCT FROM %s "
                        "AND share_alike IS NOT DISTINCT FROM %s "
                        "ORDER BY v1_category, indicator, occurred_at",
                        (key, lic, attribution, terms, share_alike))
            rows = cur.fetchall()
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(COLUMNS)
            for r in rows:
                w.writerow([json.dumps(x, ensure_ascii=False, default=str)
                            if isinstance(x, dict) else x for x in r])
            (OUT / "by-source" / fname).write_bytes(
                gzip.compress(buf.getvalue().encode()))
            manifest.append({"file": f"by-source/{fname}", "rows": len(rows),
                             "source_key": key, "source_name": name,
                             "license_spdx": lic, "attribution": attribution,
                             "terms_url": terms, "share_alike": share_alike})
            total += len(rows)
        cur.execute("""SELECT v1_category, source_name, license_spdx, rows_held,
                              from_date, to_date, reason, permission_status,
                              terms_url FROM v_withheld ORDER BY rows_held DESC""")
        withheld = cur.fetchall()

    (OUT / "manifest.json").write_text(json.dumps(
        {"shape": "collection", "generated":
         f"{datetime.now(timezone.utc):%Y-%m-%d}", "rows": total,
         "note": "Each file carries its own source's licence. Nothing is "
                 "relicensed and no derived database is formed — three "
                 "incompatible copylefts (ODbL, CC-BY-SA, CC-BY-NC-SA) live "
                 "here and no single aggregate licence can hold them.",
         "files": manifest}, indent=1, ensure_ascii=False))
    _write_withheld(withheld, total, include_memorial)
    sa = [m for m in manifest if m["share_alike"]]
    print(f"  by-source/            {len(manifest)} files, {total:,} rows")
    print(f"  manifest.json         each file under its own licence")
    print(f"  WITHHELD.md           {sum(x[3] for x in withheld):,} rows held back")
    print(f"\n  {len(sa)} source(s) carry share-alike and keep their own "
          "licence in their own file:")
    for m in sa:
        print(f"    {m['source_key']:<16} {m['license_spdx']:<22} "
              f"{m['rows']:>6} rows")
    return 0


def _write_withheld(withheld, n_released: int,
                    include_memorial: bool = False) -> None:
    stamp = f"{datetime.now(timezone.utc):%Y-%m-%d}"
    (OUT / "WITHHELD.md").write_text("\n".join([
        "# What this release does not contain", "",
        f"Generated {stamp} by `ops/export_open_data.py`.", "",
        "The databank holds these records and answers questions about them "
        "through the API, where each is a credited fact. They are **not in "
        "this release**, because a file is a database and a database is what "
        "a licence governs. Every one is a publisher who has not granted a "
        "redistribution right, or one whose terms nobody has read yet.", "",
        "| category | source | licence | rows | span | why |",
        "|---|---|---|---:|---|---|",
        *[f"| {c} | {s} | `{l}` | {n:,} | {f} → {t} | {why} |"
          for c, s, l, n, f, t, why, _st, _u in withheld],
        "",
        f"**{sum(x[3] for x in withheld):,} rows withheld**, "
        f"{n_released:,} released.", "",
        "Generated from the database, not maintained by hand. If a permission "
        "arrives the rows appear in the next release and leave this page "
        "automatically.", "",
        *([] if include_memorial else [
            "## The memorial roster", "",
            "**73,077 named records are also absent** — every identified "
            "person killed, with name, date of birth, age and sex. The "
            "licence permits publishing them: Tech4Palestine releases the "
            "roster as public domain precisely so the names are known, and "
            "reducing the dead to a number is the erasure this record exists "
            "against.", "",
            "They are held back from the FILE because the API already "
            "decided that reading them should be a deliberate act — "
            "`/v2/databank/martyrs_snapshot_2023` returns aggregates unless "
            "you pass `memorial=true`. A bulk CSV in a public repository is "
            "a different act from an API that makes you ask: it is scraped, "
            "mirrored, indexed, and cannot be withdrawn. The aggregate "
            "totals are included; `--include-memorial` includes the names, "
            "and is meant to be the same deliberate choice.", ""]),
    ]))


def main(argv: list[str]) -> int:
    lic = None
    if "--license" in argv:
        lic = argv[argv.index("--license") + 1]
    drop_sa = "--exclude-share-alike" in argv
    include_memorial = "--include-memorial" in argv
    collection = not lic

    if collection:
        return export_collection(include_memorial)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT license_spdx, count(*) FROM databank_bulk
                       WHERE share_alike GROUP BY 1 ORDER BY 2 DESC""")
        sa = cur.fetchall()
        sa_total = sum(n for _l, n in sa)
        if sa_total and not drop_sa:
            allowed = SHARE_ALIKE_OK.get(lic, set())
            bad = [l for l, _n in sa if l not in allowed]
            if bad:
                raise SystemExit(
                    f"REFUSED: this release would contain {sa_total} rows "
                    f"under {bad}, whose share-alike obliges a derived "
                    f"database to carry the same licence — and it is being "
                    f"offered under {lic}, which does not. ODbL and CC-BY-SA "
                    "bind a derived database whether or not it is sold, so "
                    "going open source triggers this rather than avoiding "
                    "it.\n"
                    f"  Either release under one of "
                    f"{sorted(k for k, v in SHARE_ALIKE_OK.items() if set(bad) <= v) or ['ODbL-1.0']}"
                    ", or pass --exclude-share-alike to leave those rows out "
                    "(and lose the entire Mandate-era gazetteer).")

        clauses = ([] if include_memorial else [MEMORIAL_FILTER]) \
            + (["NOT share_alike"] if drop_sa else [])
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        cur.execute(f"SELECT {', '.join(COLUMNS)} FROM databank_bulk {where} "
                    "ORDER BY v1_category, indicator, occurred_at")
        rows = cur.fetchall()

        cur.execute("""SELECT v1_category, source_name, license_spdx,
                              rows_held, from_date, to_date, reason,
                              permission_status, terms_url
                       FROM v_withheld ORDER BY rows_held DESC""")
        withheld = cur.fetchall()

        cur.execute("""SELECT DISTINCT source_name, license_spdx,
                              attribution_text, terms_url
                       FROM databank_bulk ORDER BY 1""")
        credits = cur.fetchall()

    OUT.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLUMNS)
    for r in rows:
        w.writerow([json.dumps(x, ensure_ascii=False, default=str)
                    if isinstance(x, dict) else x for x in r])
    (OUT / "observations.csv.gz").write_bytes(
        gzip.compress(buf.getvalue().encode()))

    stamp = f"{datetime.now(timezone.utc):%Y-%m-%d}"
    (OUT / "WITHHELD.md").write_text("\n".join([
        "# What this release does not contain", "",
        f"Generated {stamp} by `ops/export_open_data.py`.", "",
        "The databank holds these records and answers questions about them "
        "through the API, where each is a credited fact. They are **not in "
        "this file**, because a file is a database and a database is what a "
        "licence governs. Every one of them is a publisher who has not "
        "granted a redistribution right, or one whose terms nobody has read "
        "yet.", "",
        "| category | source | licence | rows | span | why |",
        "|---|---|---|---:|---|---|",
        *[f"| {c} | {s} | `{l}` | {n:,} | {f} → {t} | {why} |"
          for c, s, l, n, f, t, why, _st, _u in withheld],
        "",
        f"**{sum(x[3] for x in withheld):,} rows withheld** of "
        f"{sum(x[3] for x in withheld) + len(rows):,} held.", "",
        "This list is generated from the database, not maintained by hand. "
        "If a permission arrives, the rows appear in the next release and "
        "leave this page automatically.", "",
    ]))

    (OUT / "README.md").write_text("\n".join([
        "# Palestine databank — open data release", "",
        f"**{len(rows):,} observations**, released under `{lic}`, "
        f"generated {stamp}.", "",
        "Every row carries its source and that source's licence. See "
        "`WITHHELD.md` for what is deliberately absent and why — the export "
        "is never quietly short.", "",
        ("" if include_memorial else
         "The 73,077 named memorial records are NOT in this release; see "
         "`WITHHELD.md`. Their aggregate totals are."), "",
        "## Credit where it is owed", "",
        *[f"- **{n}** — `{l}`  \n  {a}" + (f"  \n  <{u}>" if u else "")
          for n, l, a, u in credits],
        "",
        "## If you build on this", "",
        (f"Rows marked `share_alike` are under ODbL or CC-BY-SA. A derived "
         f"**database** built on them must carry the same licence — that "
         f"obligation applies whether or not you charge for it. This release "
         f"is offered under `{lic}` for that reason."
         if not drop_sa and sa_total else
         "Share-alike rows were excluded from this release "
         "(`--exclude-share-alike`), so no copyleft obligation travels with "
         "it. The Mandate-era gazetteer is among what that leaves out."), "",
    ]))

    print(f"  observations.csv.gz   {len(rows):,} rows, licence {lic}")
    print(f"  WITHHELD.md           {sum(x[3] for x in withheld):,} rows, "
          f"{len(withheld)} datasets")
    print(f"  README.md             {len(credits)} sources credited")
    if sa_total and not drop_sa:
        print(f"\n  NOTE: {sa_total:,} share-alike rows are included, and "
              f"{lic} carries their obligation forward. That is the correct "
              "outcome, not a warning.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
