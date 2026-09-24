"""Give the gazetteer the places the incident channels actually name.

    python ops/promote_named_localities.py --from proj.ndjson [--from more.ndjson] [--min-count 2]
    python ops/promote_named_localities.py --from proj.ndjson --apply
    python ops/promote_named_localities.py --alias 'جلجليا=555' --alias 'كفرذان=51' --apply

WHY
---
All 1,443 servable localities came from v1's list; 457 of them have no Arabic
key at all, and real villages the channels report from every week (بتير,
Ramallah's المغير, Ramallah's برقة, خلة الحمص, جنبا) have no servable row. The
Palestine Open Maps reference set (2,584 rows, servable=false, no aliases)
holds most of them with the Arabic spelling — sitting in the same table,
reachable by nothing.

WHAT
----
Takes the names the projection (`ops/place_measure.py --out`) could not
resolve, with the governorate each message stated, and for each one:

  1. finds an Open Maps row with that Arabic name inside that governorate
     (its admin2 was set from the polygon by migration 077);
  2. if a servable locality already sits within 1,500 m of it with a matching
     English name or no Arabic key, that existing row takes the keys;
     otherwise the Open Maps row itself is promoted to servable;
  3. writes the keys: as `place_alias` rows (origin `palopenmaps`) when the key
     is free; as `attrs.twin_keys` on the row when the key already belongs to a
     place in ANOTHER governorate (`place_alias.alias_norm` is unique, so the
     second المغير can never hold the first one's key — the resolver reaches
     it through the governorate hint, see `resolve.geo._twin_in`). A key owned
     by another place in the SAME governorate is left alone and reported.

`--alias NAME=PLACE_ID` adds a spelling the channels use for a place that
already exists (جلجليا for جلجيليا). Same key rules.

Dry run by default; nothing is deleted, no existing row loses a key. Every
promoted row carries `quality_note` and `attrs.promoted` naming this script.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.arabic import fold_for_match, is_generic_alias, normalize, variants   # noqa: E402
from resolve.db import connect                                                    # noqa: E402
from resolve.geo import governorate_pcode                                         # noqa: E402

_PAREN = re.compile(r"\s*\([^)]*\)")
NOTE = "promoted from palopenmaps (P0-C.1b, 2026-09-24): named by incident channels; admin2 from polygon (077)"


def keys_for(name: str) -> list[str]:
    out: list[str] = []
    norm = normalize(name)
    for k in variants(name):
        # A folded key shorter than four letters ("عين" from "مخيم العين") is
        # a fragment, not a name; the normalised form alone may be that short.
        if k and len(k) >= 2 and not is_generic_alias(k) and k not in out \
                and (k == norm or len(k) >= 4):
            out.append(k)
    for k in list(out):
        if k.endswith("ا") and len(k) >= 3:
            sw = k[:-1] + "ه"
        elif k.endswith("ه") and len(k) >= 3:
            sw = k[:-1] + "ا"
        else:
            continue
        if sw not in out:
            out.append(sw)
    return out


def fold_en(s: str | None) -> str:
    s = re.sub(r"[^a-z]+", " ", (s or "").lower()).strip()
    s = re.sub(r"\b(al|el|ad|as|at|ash|camp|khirbat|khirbet|khallet|khallat)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def similar(a: str | None, b: str | None) -> float:
    a, b = fold_en(a), fold_en(b)
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def unresolved_from(paths: list[str], min_count: int) -> list[tuple[str, str, int]]:
    """(name, governorate, count) for every candidate of a row that did not
    land on a named place. Only the first two candidates of a row count: the
    later readers' offerings are guesses."""
    c: Counter = Counter()
    for path in paths:
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("precision") == "named" or not row.get("governorate"):
                continue
            for name, _how in (row.get("candidates") or [])[:2]:
                c[(name, row["governorate"])] += 1
    return [(n, g, k) for (n, g), k in c.most_common() if k >= min_count]


class Planner:
    def __init__(self, cur):
        self.cur = cur
        self.pom_by_pcode: dict[str, list[tuple]] = {}
        self.actions: list[dict] = []

    def pom_rows(self, pcode: str) -> list[tuple]:
        if pcode not in self.pom_by_pcode:
            self.cur.execute("""
                SELECT place_id, name_ar, name_en, servable
                  FROM place
                 WHERE source_refs->>'source' = 'palopenmaps' AND kind::text = 'locality'
                   AND admin2_pcode = %s AND name_ar IS NOT NULL AND centroid IS NOT NULL
                   AND merged_into IS NULL""", (pcode,))
            rows = []
            for pid, ar, en, servable in self.cur.fetchall():
                clean = _PAREN.sub("", ar).strip()
                rows.append((pid, ar, en, servable, set(keys_for(clean))))
            self.pom_by_pcode[pcode] = rows
        return self.pom_by_pcode[pcode]

    def owner(self, key: str) -> tuple | None:
        self.cur.execute("""
            SELECT p.place_id, p.name_ar, p.name_en, p.admin2_pcode, p.servable
              FROM place_alias a JOIN place p0 ON p0.place_id = a.place_id
              JOIN place p ON p.place_id = COALESCE(p0.merged_into, p0.place_id)
             WHERE a.alias_norm = %s""", (key,))
        return self.cur.fetchone()

    def neighbour(self, pom_id: int, pom_en: str | None) -> tuple | None:
        """A servable locality within 1,500 m that is the same place."""
        self.cur.execute("""
            SELECT p.place_id, p.name_ar, p.name_en,
                   ST_Distance(p.centroid::geography, q.centroid::geography) AS d,
                   EXISTS (SELECT 1 FROM place_alias a WHERE a.place_id = p.place_id
                              AND a.alias_norm ~ '[؀-ۿ]') AS has_ar
              FROM place p, place q
             WHERE q.place_id = %s AND p.servable AND p.merged_into IS NULL
               AND p.kind::text = 'locality' AND p.place_id <> q.place_id
               AND ST_DWithin(p.centroid::geography, q.centroid::geography, 1500)
             ORDER BY d LIMIT 5""", (pom_id,))
        for pid, ar, en, d, has_ar in self.cur.fetchall():
            # Name AND distance: a settlement 772 m from الزاوية with no Arabic
            # key is not الزاوية. "Taybeh" against "al-Tayyiba" passes at 0.5
            # once the articles are folded away.
            if similar(en, pom_en) >= 0.6:
                return (pid, ar, en, round(d))
        return None

    def plan_name(self, name: str, gov: str, count: int) -> None:
        pcode = governorate_pcode(self.cur, gov)
        keys = keys_for(name)
        if governorate_pcode(self.cur, name):
            self.actions.append({"name": name, "gov": gov, "n": count, "action": "skip",
                                 "why": "a governorate's own name (the city row answers)"})
            return
        if not pcode or not keys:
            self.actions.append({"name": name, "gov": gov, "n": count, "action": "skip",
                                 "why": "no governorate code" if not pcode else "no key"})
            return
        matches = [r for r in self.pom_rows(pcode) if set(keys) & r[4]]
        if not matches:
            self.actions.append({"name": name, "gov": gov, "n": count, "action": "skip",
                                 "why": "no Open Maps row of that name in the governorate"})
            return
        pom = matches[0]
        pid, ar, en, servable, pom_keys = pom
        target = self.neighbour(pid, en)
        if target:
            self.actions.append({"name": name, "gov": gov, "n": count, "action": "alias-existing",
                                 "target": target[0], "target_name": target[1] or target[2],
                                 "via_pom": pid, "metres": target[3],
                                 "keys": self.key_plan(keys, target[0], pcode)})
        else:
            self.actions.append({"name": name, "gov": gov, "n": count,
                                 "action": "already-servable" if servable else "promote",
                                 "target": pid, "target_name": ar, "target_en": en,
                                 "keys": self.key_plan(sorted(pom_keys | set(keys)), pid, pcode)})

    def plan_promote(self, place_id: int) -> None:
        self.cur.execute("SELECT name_ar, name_en, admin2_pcode, servable FROM place WHERE place_id = %s", (place_id,))
        row = self.cur.fetchone()
        if not row or not row[2]:
            self.actions.append({"name": str(place_id), "action": "skip", "why": "no such row or no admin2"})
            return
        clean = _PAREN.sub("", row[0] or "").strip()
        self.actions.append({"name": clean, "gov": row[2], "n": 0,
                             "action": "already-servable" if row[3] else "promote",
                             "target": place_id, "target_name": row[0], "target_en": row[1],
                             "keys": self.key_plan(keys_for(clean), place_id, row[2])})

    def plan_move(self, name: str, place_id: int) -> None:
        """Re-point an existing alias to another row of the same governorate —
        the city's bare name off the governorate polygon (as backfill_city did
        for every governorate but Jenin)."""
        self.cur.execute("SELECT name_ar, name_en, admin2_pcode FROM place WHERE place_id = %s", (place_id,))
        row = self.cur.fetchone()
        key = normalize(name)
        own = self.owner(key)
        if not row or not own:
            self.actions.append({"name": name, "action": "skip", "why": "no such row or no such alias"})
            return
        self.actions.append({"name": name, "gov": row[2], "n": 0, "action": "move-alias",
                             "target": place_id, "target_name": row[0] or row[1],
                             "from": own[0], "keys": [(key, f"move from {own[0]} {own[1] or own[2]}")]})

    def plan_alias(self, name: str, place_id: int) -> None:
        self.cur.execute("SELECT name_ar, name_en, admin2_pcode, servable FROM place WHERE place_id = %s", (place_id,))
        row = self.cur.fetchone()
        if not row:
            self.actions.append({"name": name, "action": "skip", "why": f"no place {place_id}"})
            return
        self.actions.append({"name": name, "gov": row[2], "n": 0, "action": "alias-existing",
                             "target": place_id, "target_name": row[0] or row[1],
                             "keys": self.key_plan(keys_for(name), place_id, row[2])})

    def key_plan(self, keys: list[str], target: int, pcode: str) -> list[tuple[str, str]]:
        plan = []
        for k in keys:
            own = self.owner(k)
            if own is None:
                plan.append((k, "alias"))
            elif own[0] == target:
                plan.append((k, "has"))
            elif own[3] != pcode:
                plan.append((k, "twin_key"))
            else:
                plan.append((k, f"taken-in-governorate by {own[0]} {own[1] or own[2]}"))
        return plan

    def apply(self) -> Counter:
        done: Counter = Counter()
        for a in self.actions:
            if a["action"] == "move-alias":
                key = a["keys"][0][0]
                self.cur.execute("""
                    UPDATE place_alias SET place_id = %s, origin = 'backfill_city'
                     WHERE alias_norm = %s AND place_id = %s""", (a["target"], key, a["from"]))
                done["moved"] += self.cur.rowcount
                continue
            if a["action"] not in ("promote", "alias-existing", "already-servable"):
                continue
            t = a["target"]
            if a["action"] == "promote":
                self.cur.execute("""
                    UPDATE place SET servable = true, quality_note = %s,
                           attrs = COALESCE(attrs, '{}'::jsonb) || %s::jsonb
                     WHERE place_id = %s AND NOT servable""",
                    (NOTE, json.dumps({"promoted": "P0-C.1b"}), t))
                done["promoted"] += self.cur.rowcount
            twin = []
            for k, what in a["keys"]:
                if what == "alias":
                    self.cur.execute("""
                        INSERT INTO place_alias (alias_norm, place_id, confidence, origin)
                        VALUES (%s, %s, 0.9, 'palopenmaps') ON CONFLICT (alias_norm) DO NOTHING""",
                        (k, t))
                    done["aliases"] += self.cur.rowcount
                elif what == "twin_key":
                    twin.append(k)
            if twin:
                self.cur.execute("""
                    UPDATE place SET attrs = COALESCE(attrs, '{}'::jsonb)
                        || jsonb_build_object('twin_keys',
                               (SELECT jsonb_agg(DISTINCT x) FROM jsonb_array_elements_text(
                                   COALESCE(attrs->'twin_keys', '[]'::jsonb) || %s::jsonb) AS x))
                     WHERE place_id = %s""", (json.dumps(twin, ensure_ascii=False), t))
                done["twin_keys"] += len(twin)
        return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="paths", action="append", default=[],
                    help="projection ndjson from ops/place_measure.py --out")
    ap.add_argument("--min-count", type=int, default=2)
    ap.add_argument("--alias", action="append", default=[], help="NAME=PLACE_ID")
    ap.add_argument("--promote", action="append", default=[], type=int,
                    help="promote this Open Maps row by id, keys from its own name")
    ap.add_argument("--alias-move", action="append", default=[],
                    help="NAME=PLACE_ID — re-point an existing alias to this row")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    with connect() as conn, conn.cursor() as cur:
        pl = Planner(cur)
        for name, gov, n in unresolved_from(a.paths, a.min_count) if a.paths else []:
            pl.plan_name(name, gov, n)
        for pid in a.promote:
            pl.plan_promote(pid)
        for spec in a.alias:
            name, _, pid = spec.partition("=")
            pl.plan_alias(name.strip(), int(pid))
        for spec in a.alias_move:
            name, _, pid = spec.partition("=")
            pl.plan_move(name.strip(), int(pid))
        by_action = Counter(x["action"] for x in pl.actions)
        print("plan:", dict(by_action))
        for x in pl.actions:
            if x["action"] == "skip":
                continue
            keys = ", ".join(f"{k}:{w}" for k, w in x["keys"])
            print(f"  {x['action']:16} {x['name']!r:26} {x.get('gov','')!s:9} n={x.get('n',0):<3} "
                  f"-> {x.get('target')} {x.get('target_name')!r} {('%dm' % x['metres']) if x.get('metres') else ''}  [{keys}]")
        skipped = [x for x in pl.actions if x["action"] == "skip"]
        if skipped:
            print(f"\nskipped {len(skipped)}:")
            for x in skipped[:60]:
                print(f"  {x['name']!r:26} {x.get('gov','')!s:9} n={x.get('n',0):<3} {x['why']}")
        if a.apply:
            done = pl.apply()
            conn.commit()
            print("\napplied:", dict(done))
        else:
            print("\ndry run — nothing written (add --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
