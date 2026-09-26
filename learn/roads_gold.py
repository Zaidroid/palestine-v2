"""P1-A.5 — the roads gold set: 200 road-channel messages read by a human seat.

    .venv/bin/python -m learn.roads_gold --sample      # draw tests/gold/roads-sample.jsonl
    .venv/bin/python -m learn.roads_gold --score       # v1's parser against the gold
    .venv/bin/python -m learn.roads_gold --show        # the last score

WHY IT EXISTS NOW
Organ D (free-text road parsing on the local model) waits for the PSU. The day
the GPU is back, D must be measured against something that was not written by
D, and the only thing that parses road messages today — v1's whitelist parser —
is the control it has to beat (plan P3: "v1's parser becomes the control until
v2 beats it on the roads gold"). Neither can be judged without a set of messages
a human read. This builds that set, and scores the control today.

THE FRAME
v1's tee spool (every message v1 sees, `is_checkpoint_channel` flagged) for the
last FRAME_DAYS days, road channels only, joined to what v1's parser extracted
from each message (`checkpoints.db` checkpoint_updates, by channel + msg_id).
Two strata, because they fail differently: messages v1 PARSED (precision: were
its readings right?) and messages it parsed NOTHING from (recall: 84 % of road
messages match none of its whitelist — how many of those carried a reading?).
Within each, channels are allocated by volume with a floor, and v1's long
`admin` bulletins are capped: one of them is 20+ readings to label.

THE GOLD LINE (tests/gold/roads.jsonl, one per sampled message)
    {"gold_id": "a7walstreet:123", "label_method": "read", "reader": "...",
     "is_road_report": true,
     "readings": [{"name": "as written", "canonical_key": "<v1 key or null>",
                   "direction": "inbound|outbound|both",
                   "kind": "flow|presence",
                   "value": "open|closed|congested|slow"          (flow)
                          | "idf|police|inspection|settlers"}],  (presence)
     "note": "..."}
canonical_key is v1's checkpoint key (tests/gold/roads-checkpoints.json lists
them); null when the message names a checkpoint v1's registry does not hold —
that is a registry gap, counted apart, never a parser miss.

THE SCORE
At the level of one reading = (checkpoint, direction, value): precision of v1's
readings, recall of the gold's registered readings, and — for checkpoints both
found — whether the value agrees. v1's blank direction reads as `both`.
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.db import v1_path  # noqa: E402

GOLD_DIR = ROOT / "tests" / "gold"
SAMPLE = GOLD_DIR / "roads-sample.jsonl"
GOLD = GOLD_DIR / "roads.jsonl"
REGISTRY = GOLD_DIR / "roads-checkpoints.json"
RESULT = ROOT / "ops" / "roads-gold-score.json"
SPOOL = v1_path("services/westbank-alerts/data/tee")
V1_DB = v1_path("services/westbank-alerts/data/checkpoints.db")

FRAME_DAYS = 14
N_PARSED, N_UNPARSED = 130, 70
ADMIN_CAP = 15
CHANNEL_FLOOR = 4
SEED = "roads-gold-v1"
FLOW = {"open", "closed", "congested", "slow"}
PRESENCE = {"idf", "police", "inspection", "settlers"}


def _v1(path: Path = V1_DB) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _norm_dir(d) -> str:
    return d if d in ("inbound", "outbound") else "both"


def frame(days: int = FRAME_DAYS, now: datetime | None = None) -> list[dict]:
    """Road-channel messages from the spool, each with v1's parse attached."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).date().isoformat()
    msgs: dict[tuple[str, int], dict] = {}
    for f in sorted(glob.glob(str(SPOOL / "*.ndjson"))):
        if Path(f).stem < since:
            continue
        for line in open(f, encoding="utf-8", errors="replace"):
            try:
                r = json.loads(line)
            except ValueError:
                continue                                  # a torn line
            text = (r.get("text") or "").strip()
            if not r.get("is_checkpoint_channel") or len(text) < 3:
                continue
            msgs[(r["channel"], int(r["msg_id"]))] = {
                "channel": r["channel"], "msg_id": int(r["msg_id"]),
                "date": r.get("date"), "text": text, "v1": [], "v1_source_type": None}
    with _v1() as c:
        rows = c.execute(
            "SELECT source_channel, source_msg_id, canonical_key, name_raw, status, "
            "       direction, raw_line, source_type FROM checkpoint_updates "
            "WHERE timestamp >= ?", (since,)).fetchall()
    for ch, mid, key, name, status, direction, line, stype in rows:
        m = msgs.get((ch, int(mid))) if mid is not None else None
        if m is None:
            continue
        m["v1"].append({"canonical_key": key, "name_raw": name, "status": status,
                        "direction": _norm_dir(direction), "raw_line": line})
        m["v1_source_type"] = stype
    return list(msgs.values())


def _allocate(pool: dict[str, list], n: int, rng: random.Random) -> list[dict]:
    """n messages across channels by volume, CHANNEL_FLOOR each where it can."""
    total = sum(len(v) for v in pool.values()) or 1
    quota = {ch: min(len(v), max(CHANNEL_FLOOR, round(n * len(v) / total)))
             for ch, v in pool.items()}
    while sum(quota.values()) > n:                         # trim the largest
        ch = max(quota, key=lambda k: quota[k])
        quota[ch] -= 1
    out = []
    for ch, v in sorted(pool.items()):
        out += rng.sample(v, quota[ch])
    return out


def draw(n_parsed: int = N_PARSED, n_unparsed: int = N_UNPARSED,
         msgs: list[dict] | None = None) -> list[dict]:
    rng = random.Random(SEED)
    msgs = sorted(msgs if msgs is not None else frame(),
                  key=lambda m: (m["channel"], m["msg_id"]))
    parsed = [m for m in msgs if m["v1"]]
    admin = [m for m in parsed if m["v1_source_type"] == "admin"]
    crowd = [m for m in parsed if m["v1_source_type"] != "admin"]
    unparsed = [m for m in msgs if not m["v1"]]
    admin_pick = rng.sample(admin, min(ADMIN_CAP, len(admin)))
    by_ch = defaultdict(list)
    for m in crowd:
        by_ch[m["channel"]].append(m)
    crowd_pick = _allocate(by_ch, n_parsed - len(admin_pick), rng)
    by_ch = defaultdict(list)
    for m in unparsed:
        by_ch[m["channel"]].append(m)
    unparsed_pick = _allocate(by_ch, n_unparsed, rng)
    out = []
    for stratum, picks in (("parsed:admin", admin_pick), ("parsed:crowd", crowd_pick),
                           ("unparsed", unparsed_pick)):
        for m in picks:
            out.append({"gold_id": f"{m['channel']}:{m['msg_id']}", "stratum": stratum,
                        "channel": m["channel"], "msg_id": m["msg_id"], "date": m["date"],
                        "text": m["text"], "v1": m["v1"]})
    return out


def write_sample() -> int:
    rows = draw()
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                      encoding="utf-8")
    with _v1() as c:
        reg = [dict(zip(("canonical_key", "name_ar", "name_en", "governorate",
                         "checkpoint_type"), r))
               for r in c.execute("SELECT canonical_key, name_ar, name_en, governorate, "
                                  "checkpoint_type FROM checkpoints ORDER BY canonical_key")]
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{len(rows)} messages → {SAMPLE.relative_to(ROOT)} "
          f"({Counter(r['stratum'] for r in rows)}); registry {len(reg)} checkpoints")
    return len(rows)


# ── scoring ──────────────────────────────────────────────────────────────────

def _triples(readings, *, gold: bool) -> set[tuple[str, str, str]]:
    out = set()
    for r in readings:
        key = r.get("canonical_key")
        if not key:
            continue
        value = r.get("value") if gold else r.get("status")
        out.add((key, _norm_dir(r.get("direction")), value))
    return out


def _rate(k: int, n: int) -> float | None:
    return round(k / n, 3) if n else None


def score(gold_rows: list[dict], sample_rows: list[dict]) -> dict:
    """v1's parser, scored against what the seat read."""
    v1_by_id = {r["gold_id"]: r["v1"] for r in sample_rows}
    tp = fp = fn = 0
    found_keys = gold_keys = value_ok = value_n = 0
    unregistered = 0
    report_agree = report_n = 0
    missed_msgs = []
    for g in gold_rows:
        v1 = v1_by_id.get(g["gold_id"])
        if v1 is None:
            continue
        report_n += 1
        report_agree += bool(v1) == bool(g.get("is_road_report"))
        G = _triples(g.get("readings") or [], gold=True)
        V = _triples(v1, gold=False)
        unregistered += sum(1 for r in g.get("readings") or [] if not r.get("canonical_key"))
        tp += len(G & V)
        fp += len(V - G)
        fn += len(G - V)
        gk = {(k, d) for k, d, _ in G}
        vk = {(k, d): v for k, d, v in V}
        gold_keys += len(gk)
        for k, d, v in G:
            if (k, d) in vk:
                found_keys += 1
                value_n += 1
                value_ok += vk[(k, d)] == v
        if G and not V:
            missed_msgs.append(g["gold_id"])
    return {
        "subject": "roads", "parser": "v1 whitelist (checkpoint_updates)",
        "gold_rows": len(gold_rows), "scored": report_n,
        "reading_precision": _rate(tp, tp + fp), "reading_recall": _rate(tp, tp + fn),
        "checkpoint_recall": _rate(found_keys, gold_keys),
        "value_agreement_when_found": _rate(value_ok, value_n),
        "is_road_report_agreement": _rate(report_agree, report_n),
        "gold_readings_unregistered": unregistered,
        "messages_with_readings_v1_missed": len(missed_msgs),
        "counts": {"tp": tp, "fp": fp, "fn": fn},
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def contract_scorer(gold_rows: list[dict]) -> list[dict]:
    """ops/gold_contract.SCORERS['roads']: v1's parser is the control; nothing
    serves on this gate yet, so the verdict is a measurement, not a door."""
    if not SAMPLE.exists():
        return [{"subject": "roads", "version": "v1-parser", "serving": True,
                 "servable": None, "scores": [], "gold": str(GOLD.relative_to(ROOT)),
                 "verdict": "gold present but its sample file is missing"}]
    s = score(gold_rows, load_jsonl(SAMPLE))
    return [{"subject": "roads", "version": "v1-parser", "serving": True,
             "servable": None, "gold": str(GOLD.relative_to(ROOT)), "scores": [s],
             "verdict": (f"control measured on {s['scored']} messages: reading precision "
                         f"{s['reading_precision']}, recall {s['reading_recall']}; "
                         f"{s['gold_readings_unregistered']} gold readings name checkpoints "
                         f"v1 does not hold")}]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args(argv)
    if a.sample:
        write_sample()
    if a.score:
        s = score(load_jsonl(GOLD), load_jsonl(SAMPLE))
        RESULT.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(s, ensure_ascii=False, indent=2))
    if a.show and RESULT.exists():
        print(RESULT.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
