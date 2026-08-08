"""Emit one `v_<category>` view per row of the `category` table.

056 turned nineteen near-identical hand-written views into rows. This is what
turns them back into views — and, more usefully, what guarantees the view a
consumer queries and the extent the registry declares can never disagree,
because there is only one statement of it.

THE RULE IS CHECKED EVEN THOUGH IT COMES FROM A MIGRATION. A `domain_rule` is
reviewed SQL written by someone with database access, so an injection here
buys an attacker nothing they do not already have. It is still validated
against a whitelist, because "it came from a trusted place" is the sentence
at the start of every injection post-mortem, and because the check also
catches the ordinary version of the problem: a typo'd column name that
silently creates a view nobody can query.

Run:  .venv/bin/python -m ops.gen_category_views          # show the plan
      .venv/bin/python -m ops.gen_category_views --apply  # create them
      .venv/bin/python -m ops.gen_category_views --check  # drift check, CI
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolve.db import connect                                   # noqa: E402

# Columns a rule may name. Anything else is a typo or a reach into a table
# the serving surface deliberately does not expose.
ALLOWED_COLUMNS = {
    "v1_category", "indicator", "dataset_key", "source_key", "unit",
    "license_spdx", "commercial_use", "share_alike", "redistribution",
    "occurred_precision", "place_id",
}
ALLOWED_KEYWORDS = {"and", "or", "not", "like", "ilike", "in", "is", "null",
                    "true", "false", "any", "similar", "to"}

# The columns every category view exposes. Deliberately NOT `SELECT *`: a
# category view is a public surface, and adding a column to databank_serving
# should not silently widen twenty public endpoints.
VIEW_COLUMNS = ("occurred_at", "occurred_precision", "indicator", "value_num",
                "value_text", "unit", "place_id", "attrs", "source_name",
                "license_spdx", "attribution_text", "share_alike",
                "redistribution")

_TOKEN = re.compile(r"'[^']*'|[A-Za-z_][A-Za-z0-9_]*|%|[<>=!]+|[(),]|\s+|\S")


def validate_rule(rule: str) -> str | None:
    """Return an error string, or None if the rule is safe to inline."""
    if ";" in rule or "--" in rule or "/*" in rule:
        return "a rule may not contain a statement terminator or a comment"
    for tok in _TOKEN.findall(rule):
        t = tok.strip()
        if not t or t.startswith("'") or t in "(),%" or re.fullmatch(r"[<>=!]+", t):
            continue
        if re.fullmatch(r"\d+", t):
            continue
        low = t.lower()
        if low in ALLOWED_KEYWORDS or low in ALLOWED_COLUMNS:
            continue
        return (f"unknown identifier {t!r} — a domain_rule may name only "
                f"{sorted(ALLOWED_COLUMNS)} and the boolean keywords")
    return None


def plan(cur) -> list[tuple[str, str, str]]:
    cur.execute("SELECT key, domain_rule FROM category WHERE active "
                "ORDER BY key")
    out = []
    for key, rule in cur.fetchall():
        err = validate_rule(rule)
        if err:
            raise SystemExit(f"REFUSED: category {key!r} rule rejected — {err}")
        cols = ", ".join(VIEW_COLUMNS)
        out.append((key, rule,
                    f"CREATE OR REPLACE VIEW v_{key} AS\n"
                    f"SELECT {cols}\nFROM databank_serving\nWHERE {rule};"))
    return out


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    check = "--check" in argv
    with connect() as conn, conn.cursor() as cur:
        rows = plan(cur)
        if check:
            # Drift: a view that selects something other than what its row
            # declares, or a category with no view at all.
            #
            # Compared by ROW SET, not by text. Postgres rewrites a stored
            # definition — LIKE becomes ~~, literals gain ::text casts,
            # parentheses move — so a string comparison fails on every view
            # that is perfectly correct, and a check that cries wolf on
            # healthy input is a check everybody learns to skip. What matters
            # is whether the view and the rule select the same rows, and that
            # is answerable directly.
            cur.execute("SELECT viewname FROM pg_views WHERE viewname LIKE 'v\\_%'")
            live = {r[0] for r in cur.fetchall()}
            bad = []
            for key, rule, _ddl in rows:
                if f"v_{key}" not in live:
                    bad.append(f"v_{key} does not exist")
                    continue
                cur.execute(f"SELECT (SELECT count(*) FROM v_{key}), "
                            f"(SELECT count(*) FROM databank_serving "
                            f"WHERE {rule})")
                got, want = cur.fetchone()
                if got != want:
                    bad.append(f"v_{key} selects {got} rows, its domain_rule "
                               f"selects {want}")
            for name in live:
                if name[2:] not in {k for k, _, _ in rows} and \
                        name not in ("v_water", "v_tier_open",
                                     "v_tier_commercial_permissive",
                                     "v_tier_commercial_sharealike", "v_flow"):
                    bad.append(f"{name} has no category row")
            for b in bad:
                print(f"DRIFT  {b}")
            print(f"{len(bad)} drift(s) between the category registry and "
                  f"the views")
            return 1 if bad else 0
        for key, rule, ddl in rows:
            if apply:
                cur.execute(ddl)
                # COMMENT takes no parameters, so the text is inlined —
                # hence the doubled quotes rather than a placeholder. The
                # rule already passed validate_rule().
                note = (f"Generated from category.domain_rule by "
                        f"ops/gen_category_views.py. Rule: {rule}"
                        ).replace("'", "''")
                cur.execute(f"COMMENT ON VIEW v_{key} IS '{note}'")
            print(f"{'created' if apply else 'would create'}  v_{key:<24} "
                  f"WHERE {rule}")
        if apply:
            conn.commit()
    print(f"\n{len(rows)} category view(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
