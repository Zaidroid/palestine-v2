"""Collapse duplicate and non-name checkpoint places onto a canonical row.

    ./.venv/bin/python -m resolve.place_merge --dry-run
    ./.venv/bin/python -m resolve.place_merge --apply

v1's checkpoint matcher captured whole clauses as place names and kept every
spelling as its own canonical_key, so one gate exists up to 17 times. See
migration 013 for the full diagnosis and examples.

TWO SIGNALS, DELIBERATELY SEPARATE
  co-location — rows sharing an identical centroid are the same place. v1 knew
                this (it assigned them the same coordinates) and stored them
                separately anyway.
  non-name    — a "name" containing a status verb or presence noun is a
                sentence, not a place: "انسحب الجيش عن صرة" is a report.

They compose. Co-location decides WHAT merges; the non-name test decides WHICH
row survives, so a cluster never elects a sentence as its canonical form.

NOTHING IS DELETED. A fragment keeps its row, gains a merged_into pointer, and
is registered in place_alias — the misspelling is precisely what the next
message will contain, so throwing it away would lose real matching power. It
only stops being servable.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cascade.checkpoint_text import (CLEARING_WORDS, FLOW_WORDS, PRESENCE_WORDS,
                                     tokens)
from resolve.arabic import fold_for_match, is_generic_alias, normalize
from resolve.db import connect

CHECKPOINT_KINDS = ("checkpoint", "crossing", "road")

# Tokens that make a string a report rather than a name.
_NOT_NAME = set(FLOW_WORDS) | set(PRESENCE_WORDS) | set(CLEARING_WORDS)


def name_penalty(name: str | None) -> tuple[int, int, int]:
    """Sort key — lower is a better canonical name.

    (contains a status word, token count, character length). Status words come
    first because "عطارة شالو الحاجز بس" is disqualified as a NAME however
    short it is, while a merely long name is just a worse candidate.

    NOTE: callers rank on this only AFTER evidence weight. Ranking on name
    shape first elected "الكونتير" (2 observations) over "الكونتينر" (1,304) —
    the shorter string is a typo, and the well-attested spelling is both the
    correct one and the one a voice assistant should say back.
    """
    if not name:
        return (1, 99, 999)
    toks = tokens(normalize(name))
    has_status = int(any(t in _NOT_NAME for t in toks))
    return (has_status, len(toks), len(name))


def _key_tokens(name: str | None) -> set[str]:
    """Identifying tokens of a name, generic place-type words removed."""
    return {t for t in tokens(fold_for_match(name)) if len(t) >= 3}


def related(a: str | None, b: str | None) -> bool:
    """Whether two co-located names plausibly denote the same place.

    Sharing a centroid is not proof: v1 fell back to a town centroid when it
    had no precise fix, so "قلقيلية" (the town) and "مدخل قلقيلية" (its
    entrance checkpoint) sit on the same point while being different things.
    Requiring a shared identifying token — or one name containing the other —
    keeps variant spellings merging while leaving genuinely distinct places
    alone.
    """
    ta, tb = _key_tokens(a), _key_tokens(b)
    if ta & tb:
        return True
    na, nb = normalize(a), normalize(b)
    if na and nb and (na in nb or nb in na):
        return True
    # Near-identical spellings that share no whole token: الكونتير/الكونتينر.
    if ta and tb:
        for x in ta:
            for y in tb:
                if abs(len(x) - len(y)) <= 2 and (x in y or y in x):
                    return True
    return False


def is_not_a_name(name: str | None) -> bool:
    if not name:
        return True
    toks = tokens(normalize(name))
    return bool(toks) and any(t in _NOT_NAME for t in toks)


def plan(cur) -> list[dict]:
    """Group co-located checkpoint places and pick a canonical for each."""
    cur.execute(f"""
        SELECT p.place_id, p.name_ar, p.name_en, ST_AsText(p.centroid::geometry) pt,
               p.source_refs->>'v1_canonical_key' AS v1key,
               COALESCE(o.n, 0) AS obs
        FROM place p
        LEFT JOIN (SELECT place_id, COUNT(*) n FROM state_observation
                   GROUP BY place_id) o ON o.place_id = p.place_id
        WHERE p.kind IN {CHECKPOINT_KINDS} AND p.centroid IS NOT NULL
          AND p.merged_into IS NULL
        ORDER BY p.place_id""")
    clusters: dict[str, list[dict]] = {}
    for pid, ar, en, pt, v1key, obs in cur.fetchall():
        clusters.setdefault(pt, []).append(
            {"place_id": pid, "name_ar": ar, "name_en": en,
             "v1key": v1key, "obs": obs})

    out = []
    for pt, members in clusters.items():
        if len(members) < 2:
            continue
        # EVIDENCE FIRST, name shape second. A sentence is still disqualified
        # up front (name_penalty[0]), but among real names the spelling the
        # community actually uses wins — that is the one worth serving back.
        ranked = sorted(members, key=lambda m: (name_penalty(m["name_ar"])[0],
                                                -m["obs"],
                                                name_penalty(m["name_ar"])[1:],
                                                m["place_id"]))
        canon = ranked[0]
        frags, unrelated = [], []
        for m in ranked[1:]:
            # A sentence fragment always folds into the cluster; a distinct
            # name at the same coordinates does not.
            (frags if is_not_a_name(m["name_ar"]) or related(canon["name_ar"], m["name_ar"])
             else unrelated).append(m)
        if frags:
            out.append({"point": pt, "canonical": canon,
                        "fragments": frags, "unrelated": unrelated})
    return out


def move_evidence(cur, fid: int, canon: int) -> int:
    """Re-point a fragment's observations at the canonical place.

    The fragment an observation came from is kept on the row: a merge later
    judged wrong (the ranking once elected الكونتير, 2 obs, over الكونتينر,
    1,304) must be undoable without re-parsing raw lines (F540). The FIRST
    pre-merge id survives a chain of merges.
    """
    cur.execute("""UPDATE state_observation
                      SET place_id = %s,
                          attrs = attrs || jsonb_build_object(
                              'place_id_before_merge',
                              COALESCE(attrs->'place_id_before_merge', to_jsonb(place_id)),
                              'merged_by', 'place_merge')
                   WHERE place_id=%s""", (canon, fid))
    moved = cur.rowcount
    cur.execute("DELETE FROM state_current WHERE place_id=%s", (fid,))
    cur.execute("DELETE FROM place_state_cadence WHERE place_id=%s", (fid,))
    return moved


def keep_spellings(cur, frag: dict, canon: int, stats: dict) -> None:
    """Index a fragment's spellings against the canonical row — FIRST WRITER
    WINS, like every other loader.

    This was `ON CONFLICT (alias_norm) DO UPDATE SET place_id = canonical`,
    which repointed a key whoever owned it. `related()` merges "قلقيلية" into
    "مدخل قلقيلية" (they share a token), so the TOWN's curated key would have
    moved to the entrance checkpoint, and "اقتحام قلقيلية", insights and
    route_between would have answered with a gate — origin still
    'checkpoint_db', nothing recording the move (F316, 2026-09-25). The keys
    the fragment itself owned are already repointed by apply(); a key owned
    by anyone else stays theirs and is reported, never taken.
    """
    for nm in (frag["name_ar"], frag["name_en"], frag["v1key"]):
        key = normalize(nm)
        if not key or is_not_a_name(nm) or is_generic_alias(key):
            continue
        cur.execute("""INSERT INTO place_alias (alias_norm, place_id, origin, confidence)
                       VALUES (%s,%s,'checkpoint_db',0.6)
                       ON CONFLICT (alias_norm) DO NOTHING""", (key, canon))
        if cur.rowcount:
            stats["aliases"] += cur.rowcount
            continue
        cur.execute("""SELECT a.place_id FROM place_alias a
                        JOIN place p0 ON p0.place_id = a.place_id
                       WHERE a.alias_norm = %s
                         AND COALESCE(p0.merged_into, p0.place_id) <> %s""", (key, canon))
        other = cur.fetchone()
        if other:
            stats.setdefault("keys_left_with_owner", []).append((key, other[0]))


def apply(cur, groups: list[dict]) -> dict:
    stats = {"clusters": 0, "fragments": 0, "observations_moved": 0,
             "aliases": 0, "aliases_repointed": 0, "keys_left_with_owner": []}
    for g in groups:
        canon = g["canonical"]["place_id"]
        for frag in g["fragments"]:
            fid = frag["place_id"]
            # Re-point evidence at the canonical place BEFORE marking the
            # fragment, so a crash mid-run cannot strand observations on a row
            # that is no longer servable.
            stats["observations_moved"] += move_evidence(cur, fid, canon)

            # Aliases must follow the merge. P0.16 already indexed every
            # fragment's spellings against the FRAGMENT row, so without this
            # the strings still resolve — to a place that is no longer
            # servable. One of them was plain "atara", pointing at the sentence
            # "عطارة شالو الحاجز بس".
            cur.execute("""UPDATE place_alias SET place_id=%s WHERE place_id=%s""",
                        (canon, fid))
            stats["aliases_repointed"] += cur.rowcount

            # Keep every spelling as a way IN. A fragment name that is a whole
            # sentence is not indexed — it would match far too much — but a
            # variant spelling is exactly what we want to catch next time.
            keep_spellings(cur, frag, canon, stats)

            cur.execute("""UPDATE place SET merged_into=%s, servable=false,
                                  quality_note=%s, updated_at=now()
                           WHERE place_id=%s""",
                        (canon,
                         "sentence fragment" if is_not_a_name(frag["name_ar"])
                         else "spelling variant",
                         fid))
            stats["fragments"] += 1
        stats["clusters"] += 1

    # Names that are reports rather than names, but had no co-located twin to
    # merge into. They stay resolvable and stop being answers.
    cur.execute(f"""
        SELECT place_id, name_ar FROM place
        WHERE kind IN {CHECKPOINT_KINDS} AND merged_into IS NULL AND servable""")
    lone = [(pid, nm) for pid, nm in cur.fetchall() if is_not_a_name(nm)]
    for pid, _ in lone:
        cur.execute("""UPDATE place SET servable=false,
                              quality_note='name is a report, not a place',
                              updated_at=now() WHERE place_id=%s""", (pid,))
    stats["unservable_names"] = len(lone)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes")
    ap.add_argument("--dry-run", action="store_true", help="show the plan only")
    a = ap.parse_args()

    with connect() as conn, conn.cursor() as cur:
        groups = plan(cur)
        frag_total = sum(len(g["fragments"]) for g in groups)
        print(f"{len(groups)} co-located clusters · {frag_total} fragments to merge\n")
        for g in sorted(groups, key=lambda g: -sum(f["obs"] for f in g["fragments"]))[:12]:
            c = g["canonical"]
            print(f"  KEEP  {c['name_ar']}  ({c['obs']} obs)")
            for f in g["fragments"][:4]:
                tag = "sentence" if is_not_a_name(f["name_ar"]) else "variant"
                print(f"    <- [{tag:<8}] {f['name_ar']}  ({f['obs']} obs)")
            if len(g["fragments"]) > 4:
                print(f"    <- … {len(g['fragments']) - 4} more")
            # Keys a fragment's names would have taken from a place OUTSIDE the
            # cluster: they stay with their owner. Said before --apply, so a
            # town-named fragment is a visible question, not a silent move.
            for f in g["fragments"]:
                for nm in (f["name_ar"], f["name_en"], f["v1key"]):
                    key = normalize(nm)
                    if not key or is_not_a_name(nm):
                        continue
                    cur.execute("""SELECT a.place_id, p.name_ar, p.kind::text
                                     FROM place_alias a JOIN place p ON p.place_id = a.place_id
                                    WHERE a.alias_norm = %s AND a.place_id <> ALL(%s)""",
                                (key, [c["place_id"]] + [x["place_id"] for x in g["fragments"]]))
                    row = cur.fetchone()
                    if row:
                        print(f"    !! key {key!r} stays with {row[2]} {row[0]} {row[1]!r}")

        if not a.apply:
            print("\n(dry run — pass --apply to write)")
            return 0
        stats = apply(cur, groups)
        conn.commit()
        print(f"\nmerged {stats['fragments']} fragments in {stats['clusters']} clusters · "
              f"moved {stats['observations_moved']} observations · "
              f"repointed {stats['aliases_repointed']} aliases · "
              f"added {stats['aliases']} · "
              f"left {len(stats['keys_left_with_owner'])} keys with their owner")
        print(f"also unservable: {stats['unservable_names']} lone names that are reports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
