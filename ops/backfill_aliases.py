"""Backfill the alias keys a place already has the evidence for.

WHY THIS EXISTS
---------------
`resolve_place` can only reach a place through `place_alias`. Two loaders wrote
rows whose names never became keys:

  * `v1_known_locations` (servable, the rows the serving layer actually uses)
    carries rich LATIN transliterations and often NO Arabic key at all. Place
    696 "Bayt Rima" had four aliases, every one of them Latin — so the Arabic
    the news channels actually write, `بيت ريما`, resolved to nothing and the
    incident fell back to the governorate centre in Ramallah.

  * `palopenmaps` (non-servable, 2,584 rows) carries the Arabic name in
    `name_ar` and has zero aliases, because that loader never called
    `_add_aliases`. The Arabic spelling the system needed was sitting in the
    database, on a row nobody could reach.

  * Governorate rows got only an OCHA key, which for 15 of 16 is Latin-only.
    "Nablus" therefore resolved to the governorate polygon while "نابلس"
    resolved to the city — the two spellings of one name answering ~5 km apart.

Measured 2026-09-24, before this script: 758 servable places had no Arabic key,
481 had no Latin key.

WHAT IT DOES — two passes, both additive
----------------------------------------
  1. SELF-HEAL. A place's own `name_ar` / `name_en` columns become keys.
  2. TWIN-JOIN. A servable place still missing a language borrows it from a
     co-located row that has it, but only when the two are confidently the
     same place: name similarity plus distance, and never when two candidate
     twins disagree about the name.

SAFETY
------
`place_alias.alias_norm` is the primary key, so a key can only belong to one
place. Every insert is ON CONFLICT DO NOTHING: an existing mapping is never
stolen or rewritten. Re-running is a no-op. Nothing is deleted, no existing row
is UPDATEd, and `servable` is not touched — a non-servable twin lends its
spelling, it does not become servable.

Usage:  python ops/backfill_aliases.py [--apply]     (default is a dry run)
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolve.arabic import fold_for_match, is_generic_alias, normalize, variants
from resolve.db import connect

ARABIC = re.compile(r"[\u0600-\u06FF]")
LATIN = re.compile(r"[A-Za-z]")

# Twin acceptance. A twin must be both NAMED alike and CLOSE. The thresholds
# are deliberately asymmetric: an exact transliteration match tolerates the
# 2-3 km offset between two gazetteers' idea of a village centre, while a
# loose name match has to be almost on top of it.
TWIN_RULES = ((0.92, 3000), (0.75, 400), (0.60, 150))   # (min similarity, max metres)
TWIN_RADIUS = 3000
BACKFILL_CONF = 0.80        # below curated pcbs (0.85); above observed guesses


def fold_en(s: str | None) -> str:
    """Compare transliterations, not spellings. `Bayt Ur al-Tahta`,
    `Beit Ur et Tahta` and `Bayt ūr at taḩtā` are one village written by three
    romanisation schemes; the article and the y/i, ay/ei splits are noise."""
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"[''`\u2019\u02bb\u02bc\u2018-]", " ", s)
    s = re.sub(r"\b(al|el|as|ash|at|ad|az|an|ar|il)\b", " ", s)
    s = s.replace("bayt", "beit").replace("ayn", "ein")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(s.split())


def similar(a: str | None, b: str | None) -> float:
    fa, fb = fold_en(a), fold_en(b)
    if not fa or not fb:
        return 0.0
    return difflib.SequenceMatcher(None, fa, fb).ratio()


def keys_for(name: str) -> list[str]:
    """The alias keys a name should own. Mirrors load_gazetteer._add_aliases:
    a generic noun must never become a key, or it matches every phrase that
    happens to contain the plain word."""
    out, seen = [], set()
    for k in (*variants(name), fold_for_match(name), normalize(name)):
        if not k or len(k) < 2 or k in seen or is_generic_alias(k):
            continue
        seen.add(k)
        out.append(k)
    return out


def _insert(cur, place_id: int, name: str, origin: str, apply: bool) -> list[str]:
    """Returns the keys that would be (or were) newly created for this place."""
    made = []
    for key in keys_for(name):
        cur.execute("SELECT place_id FROM place_alias WHERE alias_norm = %s", (key,))
        row = cur.fetchone()
        if row is not None:
            continue                      # already owned — by us or by someone else
        if apply:
            cur.execute("""
                INSERT INTO place_alias (alias_norm, place_id, confidence, origin)
                VALUES (%s, %s, %s, %s) ON CONFLICT (alias_norm) DO NOTHING""",
                        (key, place_id, BACKFILL_CONF, origin))
            if not cur.rowcount:
                continue
        made.append(key)
    return made


def missing(cur, pattern: str) -> list[tuple]:
    """Servable, un-merged places with no alias key in the given script."""
    cur.execute(f"""
        SELECT p.place_id, p.name_ar, p.name_en, p.kind::text,
               ST_Y(p.centroid::geometry), ST_X(p.centroid::geometry)
        FROM place p
        WHERE p.servable AND p.merged_into IS NULL
          AND NOT EXISTS (SELECT 1 FROM place_alias a
                          WHERE a.place_id = p.place_id AND a.alias_norm ~ '{pattern}')
        ORDER BY p.place_id""")
    return cur.fetchall()


AR_KEY = r"[\u0600-\u06FF]"
EN_KEY = r"^[a-z0-9 ]+$"


def self_heal(cur, apply: bool) -> tuple[int, int]:
    places = keys = 0
    for pattern, col, script in ((AR_KEY, 1, ARABIC), (EN_KEY, 2, LATIN)):
        for row in missing(cur, pattern):
            name = row[col]
            if not name or not script.search(name):
                continue
            made = _insert(cur, row[0], name, "backfill_self", apply)
            if made:
                places += 1
                keys += len(made)
    return places, keys


def twin_join(cur, apply: bool) -> tuple[int, int, int, int]:
    places = keys = ambiguous = orphan = 0
    for pattern, col, script, other in ((AR_KEY, 1, ARABIC, 2), (EN_KEY, 2, LATIN, 1)):
        for pid, nar, nen, kind, lat, lon in missing(cur, pattern):
            own = (nar, nen)[col - 1]
            if own and script.search(own):
                continue                  # self-heal already covered this one
            mine = (nar, nen)[other - 1]  # the language we DO have, to match on
            cur.execute(f"""
                SELECT place_id, name_ar, name_en,
                       ST_Distance(centroid, ST_MakePoint(%s,%s)::geography) AS d
                FROM place
                WHERE place_id <> %s AND merged_into IS NULL
                  AND {'name_ar' if col == 1 else 'name_en'} IS NOT NULL
                  AND {'name_ar' if col == 1 else 'name_en'} <> ''
                  AND ST_DWithin(centroid, ST_MakePoint(%s,%s)::geography, %s)
                ORDER BY d LIMIT 12""", (lon, lat, pid, lon, lat, TWIN_RADIUS))

            accepted = []
            for cid, car, cen, dist in cur.fetchall():
                theirs_match = (car, cen)[other - 1]     # match on the shared language
                theirs_give = (car, cen)[col - 1]        # borrow the missing one
                if not theirs_give:
                    continue
                s = similar(mine, theirs_match)
                if any(s >= ms and dist <= md for ms, md in TWIN_RULES):
                    accepted.append((s, dist, theirs_give))

            if not accepted:
                orphan += 1
                continue
            # Two twins that disagree about the name are not evidence, they are
            # a question. Skip rather than pick one and be confidently wrong.
            distinct = {fold_for_match(t[2]) if col == 1 else fold_en(t[2])
                        for t in accepted}
            if len(distinct) > 1:
                ambiguous += 1
                continue
            accepted.sort(key=lambda t: (-t[0], t[1]))
            made = _insert(cur, pid, accepted[0][2], "backfill_twin", apply)
            if made:
                places += 1
                keys += len(made)
    return places, keys, ambiguous, orphan


def name_governorates(cur, apply: bool) -> tuple[int, int]:
    """Every governorate keeps a name of its own.

    Runs independently of the city repoint, and idempotently, so the
    governorate is reachable whether or not its bare key has already moved:
    `nablus governorate` and `محافظة نابلس` always resolve to the polygon,
    while the bare `nablus` / `نابلس` resolve to the city a person means.
    """
    cur.execute("""SELECT place_id, name_ar, name_en FROM place
                   WHERE kind = 'governorate' AND merged_into IS NULL""")
    places = keys = 0
    for gid, gar, gen in cur.fetchall():
        made = []
        if gen:
            made += _insert(cur, gid, f"{gen} governorate", "backfill_self", apply)
        if gar:
            made += _insert(cur, gid, f"محافظة {gar}", "backfill_self", apply)
        if made:
            places += 1
            keys += len(made)
    return places, keys


def donate_spellings(cur, apply: bool) -> tuple[int, int, int, int]:
    """Let an unreachable row lend its SPELLING to the servable place it duplicates.

    The first three passes assume the servable row is missing a language. The
    larger case is different and is what the rebuild exposed: the servable row
    HAS an Arabic name, and the channels write a different orthography of it.

        برقا  (alif)        palopenmaps 5197, not servable, no aliases
        برقة  (ta marbuta)  v1_known_locations 668, servable, is what we serve

    Folding normalises ة to ه, not to ا, so those two never meet, and 55
    incidents naming برقا fell back to the governorate centre. The same shape
    covers ابو فلاح vs خربة أبو فلاح and المزرعه vs المزرعة الشرقية.

    palopenmaps is 2,584 rows of exactly this: real Palestinian localities,
    loaded with no aliases and marked non-servable, sitting on top of the
    servable gazetteer as a second spelling of it. Those spellings are the
    useful part — they are closer to what people actually type than the
    transliteration-derived keys we serve.

    So the row is NOT made servable and nothing is merged. Its name becomes an
    alias key pointing at the servable twin, on the same evidence the twin-join
    uses: name similarity plus distance, and never when two servable candidates
    disagree.
    """
    cur.execute("""
        SELECT place_id, name_ar, name_en,
               ST_Y(centroid::geometry), ST_X(centroid::geometry)
        FROM place
        WHERE NOT servable AND merged_into IS NULL
          AND COALESCE(name_ar, '') <> ''
        ORDER BY place_id""")
    donors = cur.fetchall()

    places = keys = ambiguous = orphan = 0
    for pid, nar, nen, lat, lon in donors:
        cur.execute("""
            SELECT place_id, name_ar, name_en, kind::text,
                   ST_Distance(centroid, ST_MakePoint(%s,%s)::geography) AS d
            FROM place
            WHERE servable AND merged_into IS NULL AND place_id <> %s
              AND kind IN ('locality', 'governorate')
              AND ST_DWithin(centroid, ST_MakePoint(%s,%s)::geography, %s)
            ORDER BY d LIMIT 12""", (lon, lat, pid, lon, lat, TWIN_RADIUS))

        accepted = []
        for cid, car, cen, ckind, dist in cur.fetchall():
            # Match on BOTH languages and take the better: the two gazetteers
            # romanise differently (Burqa/Burqah) and spell Arabic differently
            # (برقا/برقة), but they rarely disagree in both at once.
            s = max(similar(nen, cen), similar(nar, car))
            if any(s >= ms and dist <= md for ms, md in TWIN_RULES):
                accepted.append((s, dist, cid, ckind))
        if not accepted:
            orphan += 1
            continue
        if len({t[2] for t in accepted}) > 1:
            # Two different servable places both look like this one. Which
            # village the channel meant is a real question; guessing it would
            # put incidents in the wrong town, which is the defect we are here
            # to fix.
            ambiguous += 1
            continue
        accepted.sort(key=lambda t: (-t[0], t[1]))
        target = accepted[0][2]
        made = _insert(cur, target, nar, "backfill_twin", apply)
        if nen:
            made += _insert(cur, target, nen, "backfill_twin", apply)
        if made:
            places += 1
            keys += len(made)
    return places, keys, ambiguous, orphan


def repoint_city_names(cur, apply: bool) -> tuple[int, list[str]]:
    """Make an English city name answer where its Arabic twin answers.

    The OCHA admin loader wrote `nablus`, `ramallah`, ... onto the GOVERNORATE
    polygon; PCBS wrote `نابلس`, `رام الله` onto the CITY. `alias_norm` is the
    primary key, so the city could never take the Latin spelling and the two
    scripts of one name answered ~5 km apart: measured 2026-09-24, insights for
    "Nablus" with a 2 km radius returned Awarta and Beit Furik instead of the
    city's own gates.

    A governorate keeps every key that is unambiguously about the governorate
    (`nablus governorate`, the Arabic form, anything with no city twin). Only
    the bare city name moves, and only when a servable locality of the same
    name exists inside that governorate. The governorate stays reachable — the
    resolver's `context` carries admin2, and admin-level callers pass pcodes,
    not prose.
    """
    cur.execute("""
        SELECT a.alias_norm, g.place_id, g.name_en, l.place_id, l.name_ar
        FROM place_alias a
        JOIN place g ON g.place_id = a.place_id AND g.kind = 'governorate'
        JOIN place l ON l.kind = 'locality' AND l.servable AND l.merged_into IS NULL
                    AND lower(trim(l.name_en)) = lower(trim(g.name_en))
                    -- `محافظة شمال غزة` is the governorate itself, filed as a
                    -- locality. Moving the English key onto it would be a
                    -- rename, not a repoint.
                    AND coalesce(l.name_ar, '') NOT LIKE '%محافظة%'
        WHERE a.alias_norm = lower(trim(g.name_en))
        ORDER BY a.alias_norm""")
    moves = cur.fetchall()
    # One governorate, one city. If the name matches several servable localities
    # we have no basis to choose, so the key stays on the polygon.
    counts: dict[str, int] = {}
    for key, _gid, _gen, _lid, _lar in moves:
        counts[key] = counts.get(key, 0) + 1
    done = []
    for key, gid, gen, lid, lar in moves:
        if counts[key] != 1:
            continue
        # The governorate must not become unreachable by name. Give it the
        # disambiguated forms FIRST — a caller who means the whole governorate
        # has to be able to say so — then hand the bare city name to the city.
        for repl in (f"{key} governorate", f"محافظة {lar}" if lar else None):
            if repl:
                _insert(cur, gid, repl, "backfill_self", apply)
        if apply:
            cur.execute("UPDATE place_alias SET place_id = %s, origin = %s "
                        "WHERE alias_norm = %s", (lid, "backfill_city", key))
        done.append(f"{key}: gov {gid} -> locality {lid} ({lar})")
    return len(done), done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the aliases (default: report only)")
    args = ap.parse_args()

    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM place_alias")
        before = cur.fetchone()[0]

        # Order matters: name the governorates and move the city names FIRST,
        # so the freed governorate keys are available to self-heal in the
        # same run.
        gp, gk = name_governorates(cur, args.apply)
        rc, rmoves = repoint_city_names(cur, args.apply)
        sp, sk = self_heal(cur, args.apply)
        tp, tk, amb, orph = twin_join(cur, args.apply)
        dp, dk, damb, dorph = donate_spellings(cur, args.apply)

        if args.apply:
            conn.commit()
        cur.execute("SELECT count(*) FROM place_alias")
        after = cur.fetchone()[0]

        print(f"{'APPLIED' if args.apply else 'DRY RUN'}")
        print(f"  gov names : {gp:5d} governorates, {gk:5d} keys")
        print(f"  city keys : {rc:5d} moved from governorate to city")
        for m in rmoves:
            print(f"              {m}")
        print(f"  self-heal : {sp:5d} places, {sk:5d} keys")
        print(f"  twin-join : {tp:5d} places, {tk:5d} keys "
              f"({amb} ambiguous skipped, {orph} with no twin)")
        print(f"  donated   : {dp:5d} places, {dk:5d} keys "
              f"({damb} ambiguous skipped, {dorph} with no servable twin)")
        print(f"  aliases   : {before} -> {after}")
        if not args.apply:
            print("  (nothing written — re-run with --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
