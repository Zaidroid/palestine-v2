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
    ("attribution", "Attribution — credit required",
     "Redistributable, commercially or otherwise, provided the credit below "
     "travels with the data."),
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


def build() -> str:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT redistribution, source_name, license_spdx,
                   attribution_text, terms_url, terms_verified_at::date,
                   count(*) AS n
            FROM databank_serving
            GROUP BY 1,2,3,4,5,6 ORDER BY 1, 7 DESC""")
        served = cur.fetchall()
        cur.execute("SELECT count(*), min(occurred_at)::date, "
                    "max(occurred_at)::date FROM databank_serving")
        total, lo, hi = cur.fetchone()
        cur.execute("""SELECT source_key, status, scope FROM source_permission
                       WHERE status <> 'granted' ORDER BY source_key""")
        pending = cur.fetchall()

    by_grade: dict[str, list] = {}
    for row in served:
        by_grade.setdefault(row[0] or "ask", []).append(row)

    L = [
        "# Attribution",
        "",
        f"The Palestine databank serves **{total:,} observations** spanning "
        f"**{lo} to {hi}** from the sources below. Every row carries its "
        "source and licence in the API response; this file is the same "
        "information in one place.",
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
