"""P1.5 — fuel signal survey.

Measures whether the Telegram channels actually carry enough fuel/station
chatter to sustain a live "which station has diesel right now" product with an
hour-scale half-life. This is the Phase 1 viability gate: if the volume is not
there, the honest product is "last known + age" and the crowd socket moves up
the roadmap (ARCHITECTURE §6), not a live availability feed.

Reads v1's corpus.db, alerts.db and news.db READ-ONLY. Writes a report to
ops/fuel-signal-survey.md.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from resolve.arabic import normalize  # noqa: E402

V1 = Path("/opt/stacks/palestine/services/westbank-alerts/data")
OUT = Path(__file__).resolve().parent / "fuel-signal-survey.md"

# Vocabulary, normalized at match time so spelling variants collapse.
# Split by what each term would let us DO, not just by topic.
VOCAB = {
    # the commodity itself
    "commodity": ["بنزين", "سولار", "ديزل", "محروقات", "وقود", "كاز", "بنزينة"],
    # cooking gas is a separate supply chain and a separate crisis
    "cooking_gas": ["غاز الطبخ", "اسطوانة غاز", "اسطوانات غاز", "جرة غاز", "غاز منزلي"],
    # a station being referred to at all
    "station": ["محطة محروقات", "محطات المحروقات", "محطة بنزين", "محطة الوقود",
                "محطات الوقود", "كازية", "بنزينة"],
    # availability — the thing a live feed must detect
    "available": ["متوفر", "متوفرة", "يتوفر", "وصل", "وصلت", "تعبئة", "متاح",
                  "فتحت", "يوجد سولار", "يوجد بنزين"],
    # unavailability
    "empty": ["نفد", "نفذ", "خلص", "خلصت", "مغلقة", "لا يوجد", "معدوم", "انتهى"],
    # queues — a strong proxy for "has fuel, but slow"
    "queue": ["طابور", "طوابير", "ازدحام", "ضغط", "انتظار", "دور"],
    # crisis framing — useful for context, useless for a station-level answer
    "crisis": ["أزمة الوقود", "أزمة المحروقات", "شح", "نقص الوقود", "ازمة وقود"],
    "price": ["سعر", "أسعار", "شيكل", "تسعيرة"],
}
NORM = {cat: [normalize(t) for t in terms] for cat, terms in VOCAB.items()}
ACTIONABLE = ("commodity", "cooking_gas", "station", "available", "empty", "queue")


def ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def categorize(text: str) -> set[str]:
    n = normalize(text)
    return {cat for cat, terms in NORM.items() if any(t in n for t in terms)}


def survey_corpus() -> dict:
    """Rate must be normalised PER CHANNEL by that channel's own observed span.

    corpus.db is a per-channel backfill of the last N messages before the
    2026-06-11 scrape, NOT a uniform time series: a7walstreet spans 0.8 days
    while maannews spans 142. Dividing total hits by the corpus-wide span
    understated the fuel rate by ~150x on the first run of this survey.
    """
    db = ro(V1 / "corpus" / "corpus.db")
    rows = db.execute("SELECT channel, date, text FROM messages").fetchall()
    db.close()

    spans: dict[str, tuple[str, str]] = {}
    for ch, date, _ in rows:
        a, b = spans.get(ch, (date, date))
        spans[ch] = (min(a, date), max(b, date))

    hits, by_channel, by_month, by_cat = [], Counter(), Counter(), Counter()
    mentions = Counter()   # any fuel/station mention, the looser signal
    for ch, date, text in rows:
        cats = categorize(text)
        if not cats:
            continue
        by_cat.update(cats)
        if cats & {"commodity", "cooking_gas", "station"}:
            mentions[ch] += 1
        # "Actionable" = mentions the commodity/station AND a state we could
        # turn into a live answer. Crisis/price chatter alone is journalism.
        if cats & {"commodity", "cooking_gas", "station"} and cats & {"available", "empty", "queue"}:
            hits.append((ch, date, text))
            by_channel[ch] += 1
            by_month[date[:7]] += 1
    def span_days(ch: str) -> float:
        a, b = spans[ch]
        try:
            d = (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 86400
        except ValueError:
            d = 0.0
        return max(d, 0.5)   # floor: a sub-12h window cannot imply a huge rate

    rates = {ch: mentions[ch] / span_days(ch) for ch in mentions}
    return {"total": len(rows), "hits": hits, "by_channel": by_channel,
            "by_month": by_month, "by_cat": by_cat, "mentions": mentions,
            "spans": {ch: span_days(ch) for ch in mentions}, "rates": rates}


def survey_alerts() -> dict:
    db = ro(V1 / "alerts.db")
    rows = db.execute(
        "SELECT source, timestamp, raw_text FROM alerts WHERE raw_text IS NOT NULL"
    ).fetchall()
    db.close()
    hits, by_channel = [], Counter()
    for src, ts, text in rows:
        cats = categorize(text)
        if cats & {"commodity", "cooking_gas", "station"}:
            hits.append((src, ts, text))
            by_channel[src] += 1
    return {"total": len(rows), "hits": hits, "by_channel": by_channel}


def main() -> int:
    c = survey_corpus()
    a = survey_alerts()

    months = sorted(c["by_month"])
    rate = sum(c["rates"].values())          # per-channel rates, summed
    top = sorted(c["rates"].items(), key=lambda kv: -kv[1])

    L = []
    L.append("# P1.5 — fuel signal survey\n")
    L.append(f"**Measured:** {datetime.utcnow().date()} · sources: v1 corpus.db, alerts.db (read-only)\n")
    L.append("## Verdict\n")
    verdict = ("VIABLE" if rate >= 20 else
               "MARGINAL" if rate >= 5 else "TOO SPARSE")
    L.append(f"**{verdict}** — ~{rate:.1f} fuel/station messages per day across all channels.\n")
    L.append("Gate in IMPLEMENTATION_PLAN P1.5: flag to Zaid if < ~20/day.\n")
    L.append("> **Measurement caveat.** corpus.db is a per-channel backfill, not a")
    L.append("> uniform time series — `a7walstreet` spans 0.8 days, `maannews` 142.")
    L.append("> Rates are therefore per-channel (hits / that channel's own span) and")
    L.append("> summed. The first run of this survey divided by the corpus-wide span")
    L.append("> and reported 0.1/day, understating the real rate ~150x.")
    L.append("> The dominant channel's window is under 24h, so the interval is wide;")
    L.append("> live measurement (needs P1.1) is required to confirm.\n")
    L.append("### Rate by channel (hits / channel's own observed span)\n")
    L.append("| channel | msgs | span (d) | fuel | fuel/day |\n|:--|--:|--:|--:|--:|")
    for ch, r in top[:12]:
        L.append(f"| {ch} | {c['total'] and ''} | {c['spans'][ch]:.1f} | {c['mentions'][ch]} | **{r:.1f}** |")
    L.append("")
    L.append(f"**Concentration risk:** the top channel carries "
             f"{100*top[0][1]/max(rate,0.01):.0f}% of the signal.\n")

    L.append("## Corpus (21k messages, 32 channels, 2023-10 → 2026-06)\n")
    L.append(f"- messages scanned: **{c['total']}**")
    L.append(f"- actionable fuel messages: **{len(c['hits'])}**")
    L.append(f"- messages mentioning fuel/stations: **{sum(c['mentions'].values())}**\n")

    L.append("### Vocabulary category hits (any message)\n")
    L.append("| category | messages |\n|:--|--:|")
    for cat, n in c["by_cat"].most_common():
        L.append(f"| {cat} | {n} |")
    L.append("")

    L.append("### Actionable hits by channel\n")
    L.append("| channel | messages |\n|:--|--:|")
    for ch, n in c["by_channel"].most_common(12):
        L.append(f"| {ch} | {n} |")
    L.append("")

    L.append("### By month\n")
    L.append("| month | actionable |\n|:--|--:|")
    for m in months[-14:]:
        L.append(f"| {m} | {c['by_month'][m]} |")
    L.append("")

    L.append("## Live alert stream (13k classified security messages)\n")
    L.append(f"- alerts with raw_text: **{a['total']}**")
    L.append(f"- mentioning fuel/stations: **{len(a['hits'])}**\n")
    L.append("These passed the *security* classifier, so this is a lower bound on")
    L.append("fuel chatter — the classifier has no fuel path and discards the rest.\n")
    if a["by_channel"]:
        L.append("| channel | fuel mentions |\n|:--|--:|")
        for ch, n in a["by_channel"].most_common(10):
            L.append(f"| {ch} | {n} |")
        L.append("")

    L.append("## Sample actionable messages\n")
    for ch, date, text in c["hits"][:12]:
        snippet = " ".join(text.split())[:160]
        L.append(f"- `{ch}` {date[:10]} — {snippet}")
    L.append("")

    OUT.write_text("\n".join(L), encoding="utf-8")

    print(f"corpus scanned:      {c['total']}")
    print(f"actionable fuel msgs:{len(c['hits'])}")
    print(f"rate (recent):       {rate:.1f}/day  -> {verdict}")
    print(f"alerts w/ fuel:      {len(a['hits'])} of {a['total']}")
    print(f"\ncategory hits: {dict(c['by_cat'].most_common())}")
    print(f"top channels:  {dict(c['by_channel'].most_common(6))}")
    print(f"\nreport -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
