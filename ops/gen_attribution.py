"""Generate ATTRIBUTION.md from the database, never by hand.

Every source we serve requires credit, and a hand-maintained credits file is
a promise that decays: a source is added, the file is not updated, and the
attribution obligation is quietly broken by an omission nobody notices. This
reads the same rows the API serves, so the credits and the data cannot
disagree.

Grouped by what each licence OBLIGES rather than by what it is called, because
that is the shape of the reader's question. The share-alike section is the one
that matters most and is easiest to miss: those rows can be used commercially
AND require a derived database to carry the same licence.

Run:  .venv/bin/python -m ops.gen_attribution           # print
      .venv/bin/python -m ops.gen_attribution --write   # write ATTRIBUTION.md
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolve.db import connect                                   # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "ATTRIBUTION.md"

SECTIONS = [
    ("share-alike", "Share-alike — credit AND copyleft",
     "These may be used commercially, **and a derived database must be "
     "released under the same licence**. If you build a database on these "
     "rows and distribute it, it inherits their terms. Served through "
     "`v_tier_commercial_sharealike`, deliberately not through the "
     "permissive commercial tier."),
    ("share-alike-nc", "Share-alike, non-commercial",
     "Credit, copyleft AND no commercial use (CC-BY-NC-SA and the WHO GHO "
     "terms). A derived database inherits the licence and may not be sold."),
    ("attribution", "Attribution — credit required",
     "Redistributable, commercially or otherwise, provided the credit below "
     "travels with the data."),
    # The section key is (redistribution, commercial_use) — IODA and OONI were
    # listed as 'redistributable, commercially or otherwise' while the registry
    # holds CC-BY-NC / All Rights Reserved (audit F146).
    ("attribution-nc", "Attribution — non-commercial only",
     "Credit required AND no commercial use. Served only through the "
     "non-commercial tiers; a sale built on these rows breaches their terms."),
    ("open", "Public domain — credit given by choice",
     "No attribution is required. It is given anyway, because a source that "
     "put its work in the public domain still did the work."),
    ("no-redistribution", "Not redistributed",
     "Held for internal analysis, corroboration, or display under fair "
     "dealing. These rows are **not** served through the databank's public "
     "surface and are not for sale. Listed so the omission is visible."),
    ("ask", "Terms unread or conversation required",
     "Quarantined by default: unread terms are never treated as permission."),
]


# WHAT THE OPENING SENTENCE MAY CALL AN OBSERVATION. A projection
# (indicator_def.projection, migration 115) is a model's output dated up to
# 2101: counted with the rest, the file opened "spanning 1922 to 2101" the
# night the UN's projection was loaded. Its values are counted and dated apart,
# and said to be what they are. Before the migration the column does not exist
# and nothing is a projection.
SPAN_SQL = """
SELECT count(*) FILTER (WHERE NOT p),
       (min(occurred_at) FILTER (WHERE NOT p))::date,
       (max(occurred_at) FILTER (WHERE NOT p))::date,
       count(*) FILTER (WHERE p),
       count(DISTINCT indicator) FILTER (WHERE p),
       (min(occurred_at) FILTER (WHERE p))::date,
       (max(occurred_at) FILTER (WHERE p))::date
  FROM (SELECT occurred_at, indicator, {projection} AS p FROM databank_serving) s"""
DECLARED = "indicator IN (SELECT indicator FROM indicator_def WHERE projection)"


def span(cur) -> tuple:
    """(observations, first day, last day, projected values, projection series,
    their first day, their last day)."""
    cur.execute("""SELECT count(*) FROM information_schema.columns
                    WHERE table_name = 'indicator_def' AND column_name = 'projection'""")
    cur.execute(SPAN_SQL.format(projection=DECLARED if cur.fetchone()[0] else "false"))
    return tuple(cur.fetchone())


def opening(total, lo, hi, projected=0, series=0, lo_p=None, hi_p=None) -> str:
    said = (f"The Palestine databank serves **{total:,} observations** spanning "
            f"**{lo} to {hi}** from the sources below. Every row carries its "
            "source and licence in the API response; this file is the same "
            "information in one place.")
    if projected:
        said += (f" It also holds **{projected:,} projected values** in {series:,} series "
                 f"for {lo_p:%Y} to {hi_p:%Y}: a model's output, not observations, "
                 "served only when asked for by name. They are not in the count or "
                 "the span above; the rows counted beside each source below include them.")
    return said


def build() -> str:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT CASE WHEN redistribution = 'attribution' AND commercial_use IS FALSE
                        THEN 'attribution-nc'
                        WHEN redistribution = 'share-alike' AND commercial_use IS FALSE
                        THEN 'share-alike-nc'
                        ELSE redistribution END AS grade,
                   source_name, license_spdx,
                   attribution_text, terms_url, terms_verified_at::date,
                   count(*) AS n
            FROM databank_serving
            GROUP BY 1,2,3,4,5,6 ORDER BY 1, 7 DESC""")
        served = cur.fetchall()
        total, lo, hi, projected, series, lo_p, hi_p = span(cur)
        cur.execute("""SELECT source_key, status, scope FROM source_permission
                       WHERE status <> 'granted' ORDER BY source_key""")
        pending = cur.fetchall()

    by_grade: dict[str, list] = {}
    for row in served:
        by_grade.setdefault(row[0] or "ask", []).append(row)

    L = [
        "# Attribution",
        "",
        opening(total, lo, hi, projected, series, lo_p, hi_p),
        "",
        "> Generated from the database by `ops/gen_attribution.py`. Do not "
        "edit by hand — a hand-maintained credits file breaks silently the "
        "first time a source is added and nobody remembers.",
        "",
    ]
    for grade, title, blurb in SECTIONS:
        rows = by_grade.get(grade)
        if not rows:
            continue
        L += [f"## {title}", "", blurb, ""]
        for _g, name, spdx, attr, url, verified, n in rows:
            L.append(f"**{name}** — {spdx} · {n:,} rows")
            if attr:
                L.append(f"  <br>{attr}")
            bits = []
            if url:
                bits.append(f"[terms]({url})")
            bits.append(f"terms read {verified}" if verified
                        else "**terms not yet read at the publisher**")
            L += ["  <br><sub>" + " · ".join(bits) + "</sub>", ""]

    if pending:
        L += ["## Requested, not yet granted", "",
              "Data we would like to include and have no permission for. "
              "Nothing from these publishers is in the databank.", ""]
        for key, status, scope in pending:
            L.append(f"- **{key}** — {status.replace('_', ' ')}"
                     + (f": {scope}" if scope else ""))
        L.append("")

    L += ["---", "",
          f"<sub>Generated {datetime.now(timezone.utc):%Y-%m-%d}. "
          "Corrections: the licence a publisher states always wins over the "
          "one recorded here — tell us and it is fixed.</sub>", ""]
    return "\n".join(L)


def main(argv: list[str]) -> int:
    text = build()
    if "--write" in argv:
        OUT.write_text(text)
        print(f"wrote {OUT} ({len(text.splitlines())} lines)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
