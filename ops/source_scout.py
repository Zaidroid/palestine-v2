"""The source scout, mechanical layer — the catalogs, swept weekly.

The gap radar (ops/gap_radar.py) says where the record thins; this says what
the open-data world currently OFFERS to thicken it — and, critically, what
appeared or changed since the last sweep. It is a discovery instrument, not
an ingester: nothing it finds touches the databank without a reviewed spec
(the T2 laws stand). Its judgment lives in db/scout/verdicts.yaml — the
reviewed memory of everything already adopted, rejected, or debunked — so a
settled question is never re-proposed and a ghost (the OCHA-on-HDX myth) is
never chased twice.

Sweep v1 covers HDX/CKAN — the one catalog with structured licenses,
timestamps, and org identity for nearly every humanitarian publisher. The
frontier beyond catalogs (ministry sites, civil-society archives, academic
datasets) belongs to the deep scout: Opus research passes whose findings are
reviewed into verdicts.yaml as candidates.

State: data/scout-state.json remembers every dataset id ever seen, so
`new: true` means genuinely never-seen — the flag that matters on a Monday.
Output: data/source-scout.json (served at /v2/databank/scout; the weekly
maintenance run reads it next to the radar).

Run: .venv/bin/python -m ops.source_scout
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
VERDICTS = ROOT / "db" / "scout" / "verdicts.yaml"
STATE = ROOT / "data" / "scout-state.json"
OUT = ROOT / "data" / "source-scout.json"
RADAR = ROOT / "data" / "gap-radar.json"

HDX = "https://data.humdata.org/api/3/action/package_search"

OPEN_LICENSES = {"cc-by", "cc-by-igo", "cc-by-sa", "cc0", "pddl", "odbl",
                 "cc-by-4.0", "other-pd", "odc-by"}

# keyword → databank category. Deliberately coarse; the point is routing a
# Monday reader's eye, not classification truth.
CATEGORY_HINTS = [
    (("casualt", "fatalit", "killed", "civilian impact"), "casualties"),
    (("demoli",), "demolitions"),
    (("conflict", "acled", "violence", "incident"), "conflict"),
    (("aid", "humanitarian access", "convoy", "truck"), "aid_access"),
    (("food", "market price", "ipc", "nutrition"), "food"),
    (("health", "hospital", "vaccin", "disease"), "health"),
    (("water", "wash", "sanitation"), "water"),
    (("econom", "gdp", "trade", "cpi", "inflation", "labour", "labor",
      "employ"), "economic"),
    (("fund", "financial tracking", "cash"), "funding"),
    (("refugee", "displace", "idp"), "refugees"),
    (("damage", "infrastructure", "building", "housing", "shelter"),
     "infrastructure"),
    (("internet", "connectivity", "telecom"), "connectivity"),
    (("school", "education"), "education"),
    (("settlement", "land use", "barrier", "closure"), "land"),
    (("detention", "prisoner", "detainee"), "prisoners"),
    (("energy", "electricity", "power", "fuel", "solar"), "energy"),
    (("population", "census", "demograph"), "pcbs"),
]


def categorize(text: str) -> list[str]:
    t = text.lower()
    return [cat for keys, cat in CATEGORY_HINTS
            if any(k in t for k in keys)] or ["uncategorized"]


def fetch_hdx_pse() -> list[dict]:
    """Every dataset HDX groups under the State of Palestine."""
    rows, start = [], 0
    while True:
        q = urllib.parse.urlencode({
            "fq": "groups:pse", "rows": 200, "start": start,
            "sort": "metadata_modified desc"})
        with urllib.request.urlopen(f"{HDX}?{q}", timeout=60) as r:
            batch = json.load(r)["result"]
        rows.extend(batch["results"])
        start += 200
        if start >= batch["count"] or start >= 1200:
            break
    return rows


def main() -> int:
    now = datetime.now(timezone.utc)
    verdicts = yaml.safe_load(VERDICTS.read_text())
    gaps = {}
    if RADAR.exists():
        radar = json.loads(RADAR.read_text())
        gaps = {g["subject"]: g for g in radar.get("gaps", [])}
        gap_categories = {x["category"] for x in radar.get("datasets", [])
                          if x["status"] in ("stalled", "dead_upstream")}
    else:
        gap_categories = set()
    # categories the project wants and does not have at all
    gap_categories |= {"energy", "demolitions", "aid_access",
                       "infrastructure", "casualties"}

    state = json.loads(STATE.read_text()) if STATE.exists() else {"seen": []}
    seen = set(state["seen"])
    assessed = verdicts.get("assessed_orgs") or {}

    packages = fetch_hdx_pse()
    candidates, watched = [], []
    for p in packages:
        org = p["organization"]["name"]
        pid = p["name"]
        lic = (p.get("license_id") or "").lower()
        modified = (p.get("last_modified") or p.get("metadata_modified")
                    or "")[:10]
        created = (p.get("metadata_created") or "")[:10]
        text = f'{p.get("title", "")} {" ".join(t["name"] for t in p.get("tags", []))} {(p.get("notes") or "")[:400]}'
        cats = categorize(text)
        formats = sorted({(r.get("format") or "").upper()
                          for r in p.get("resources", []) if r.get("format")})

        is_new = pid not in seen
        watermark = str(assessed.get(org, ""))
        post_watermark = not watermark or created > watermark or \
            modified > watermark

        score = 0
        why = []
        if any(c in gap_categories for c in cats):
            score += 3
            why.append("matches an open gap category")
        if lic in OPEN_LICENSES:
            score += 2
            why.append(f"open license ({lic})")
        if modified and (now.date().isoformat() <= modified or
                         (now.date() - datetime.fromisoformat(modified)
                          .date()).days <= 90):
            score += 2
            why.append(f"active (modified {modified})")
        if any(f in ("CSV", "JSON", "XLSX", "GEOJSON") for f in formats):
            score += 1
        if is_new:
            score += 2
            why.append("never seen by any previous sweep")

        entry = {
            "id": pid, "title": p.get("title"), "org": org,
            "url": f"https://data.humdata.org/dataset/{pid}",
            "license": p.get("license_id"),
            "modified": modified, "created": created,
            "formats": formats, "categories": cats,
            "score": score, "new": is_new, "why": ", ".join(why) or "catalog presence only",
        }
        seen.add(pid)
        if not post_watermark:
            continue                      # org assessed; nothing changed since
        if score >= 5:
            candidates.append(entry)
        elif score >= 3:
            watched.append(entry)

    candidates.sort(key=lambda e: (-e["score"], e["modified"]), reverse=False)
    candidates.sort(key=lambda e: -e["score"])
    report = {
        "swept_at": now.isoformat(),
        "catalog": "HDX group:pse",
        "packages_in_catalog": len(packages),
        "never_seen_before": sum(1 for c in candidates + watched if c["new"]),
        "candidates": candidates[:40],
        "watched": watched[:40],
        "verdicts_note": "adopted/debunked/rejected sources live in "
                         "db/scout/verdicts.yaml and are never re-proposed; "
                         "deep-scout findings are reviewed into the same "
                         "file. Nothing here ingests without a reviewed "
                         "spec.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    tmp.replace(OUT)
    STATE.write_text(json.dumps({"seen": sorted(seen),
                                 "last_swept": now.isoformat()}))

    print(f"source scout: {len(packages)} PSE datasets on HDX — "
          f"{len(report['candidates'])} candidates, {len(report['watched'])} "
          f"watched, {report['never_seen_before']} never seen before")
    for c in report["candidates"][:10]:
        flag = "NEW " if c["new"] else "    "
        print(f"  {flag}[{c['score']}] {c['org']:<28} {c['title'][:56]:<58} "
              f"{c['license'] or '?':<12} {c['modified']}")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
