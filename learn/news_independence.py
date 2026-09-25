"""Which NEWS channels copy each other (P0-C.5).

The road channels were measured long ago (learn/source_independence.py: nine
channels agree >=98% on checkpoint readings and count as ONE unit). The news
channels that feed incidents never were, so "reported by 3 channels" could be
one channel and two that repost it verbatim — the plan measured the multi-
source share at 25% and could not say how much of it was copying.

Measured on TEXT, because news channels report events, not readings: a claim of
channel B copies channel A when A posted a near-identical text (word-3-gram
Jaccard >= SIMILAR) in the hour before B (or up to 5 minutes after — clocks and
batches). copy_rate(B<-A) = B's claims that match A / B's claims. Two channels
are ONE unit when either copies the other at >= COPY_THRESHOLD over at least
MIN_MATCHES matches; groups close transitively (union-find), as for the roads.

    .venv/bin/python -m learn.news_independence            # report
    .venv/bin/python -m learn.news_independence --apply    # write groups

--apply only ever writes `newscopy:` groups onto sources whose group is NULL or
already `newscopy:`; a road copyset, palhub, or any crowd source is never touched.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resolve.arabic import normalize                                        # noqa: E402
from resolve.db import connect                                              # noqa: E402

DAYS = 30
SIMILAR = 0.6
COPY_THRESHOLD = 0.5
MIN_MATCHES = 30
BEFORE = timedelta(minutes=60)
AFTER = timedelta(minutes=5)
_URL = re.compile(r"https?://\S+|t\.me/\S+|@\w+")
_NOISE = re.compile(r"[^\w\s]", re.UNICODE)


def shingles(text: str, n: int = 3) -> frozenset:
    t = _NOISE.sub(" ", _URL.sub(" ", normalize(text or "")))
    w = [x for x in t.split() if not x.isdigit() or len(x) > 1]
    if len(w) < n:
        return frozenset([" ".join(w)]) if w else frozenset()
    return frozenset(" ".join(w[i:i + n]) for i in range(len(w) - n + 1))


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def copy_rates(claims: list[tuple[str, object, str]]) -> dict:
    """claims: (source_key, reported_at, text). Returns {(b, a): (matches, b_total)}."""
    by_src: dict[str, list] = defaultdict(list)
    for key, at, text in claims:
        sh = shingles(text)
        if len(sh) >= 3:                       # a one-word "عاجل" copies nothing
            by_src[key].append((at, sh))
    for v in by_src.values():
        v.sort(key=lambda x: x[0])
    times = {k: [x[0] for x in v] for k, v in by_src.items()}
    out = {}
    for b, bl in by_src.items():
        for a, al in by_src.items():
            if a == b:
                continue
            m = 0
            for at, sh in bl:
                lo = bisect_left(times[a], at - BEFORE)
                hi = bisect_left(times[a], at + AFTER)
                if any(jaccard(sh, al[i][1]) >= SIMILAR for i in range(lo, hi)):
                    m += 1
            out[(b, a)] = (m, len(bl))
    return out


class _Union:
    def __init__(self):
        self.p: dict[str, str] = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def groups_from(rates: dict) -> tuple[dict[str, str], list]:
    uf, merged = _Union(), []
    for (b, a), (m, n) in rates.items():
        uf.find(a); uf.find(b)
        if n and m >= MIN_MATCHES and m / n >= COPY_THRESHOLD:
            uf.union(a, b)
            merged.append((b, a, m, n))
    members: dict[str, list] = defaultdict(list)
    for k in uf.p:
        members[uf.find(k)].append(k)
    return {k: f"newscopy:{root}" for root, ks in members.items() if len(ks) > 1 for k in ks}, merged


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--days", type=int, default=DAYS)
    a = ap.parse_args()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT s.key, c.reported_at, c.raw_text
                         FROM claim c JOIN source s ON s.source_id = c.source_id
                        WHERE s.feeds_incidents AND s.kind IN ('telegram', 'rss') AND s.active
                          AND c.reported_at > now() - make_interval(days => %s)
                          AND c.raw_text IS NOT NULL""", (a.days,))
        claims = cur.fetchall()
        rates = copy_rates(claims)
        groups, merged = groups_from(rates)
        print(f"{len(claims):,} claims over {a.days} d; pairs with any copying:")
        for (b, x), (m, n) in sorted(rates.items(), key=lambda kv: -(kv[1][0] / max(1, kv[1][1]))):
            if m:
                print(f"  {b:<22} copies {x:<22} {m:>5}/{n:<6} {m / n:.0%}")
        print("groups:", json.dumps(groups, ensure_ascii=False, indent=1) if groups else "none")
        if a.apply:
            cur.execute("SELECT key, independence_group, kind FROM source WHERE key = ANY(%s)",
                        (sorted({k for k, _, _ in claims}),))
            for key, current, kind in cur.fetchall():
                if kind == "crowd" or (current and not current.startswith("newscopy:")):
                    continue                     # never touch a road copyset, palhub or crowd
                new = groups.get(key)
                if new != current:
                    note = (f"copies within its group at >={COPY_THRESHOLD:.0%} of claims "
                            f"(word-3-gram Jaccard >={SIMILAR}, 60 min), {a.days} d"
                            if new else "independent: no news peer above threshold")
                    cur.execute("""UPDATE source SET independence_group = %s, independence_note = %s,
                                          independence_measured_at = now() WHERE key = %s""",
                                (new, note, key))
                    print(f"  {key}: {current} -> {new}")
            conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
