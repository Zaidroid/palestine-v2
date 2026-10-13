"""Ask the archive a question (read-only).

    .venv/bin/python -m ops.ask_archive 'ولاعة OR قداحة OR lighter' --from 2023-10-07
    .venv/bin/python -m ops.ask_archive '"اعتقال الأطفال"' --months
    .venv/bin/python -m ops.ask_archive 'مياه غزة' --source tg:qudsn,tg:safaps --limit 40 --oldest
    .venv/bin/python -m ops.ask_archive --held                       # what the archive holds, by publisher

A question is words (all must appear), OR between alternatives, "quotes" for
words side by side, a leading - to exclude, brackets to group. Arabic and
English words are matched in every form the rule in ingest/archive_text.py
brings together; broken plurals are not, so list them: `أسير OR أسرى`.

The answer is what is held, never more: the number of texts that match, the
months they fall in (with --months; a month that is absent has no matching
text, which is not the same as nothing having happened), and the texts
themselves with date, publisher and link, each cut around the matching word.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest import archive_text as T                           # noqa: E402
from resolve.db import connect                                  # noqa: E402


def _where(a) -> tuple[str, list]:
    conds, params = ["d.terms @@ to_tsquery('english', %s)"], [T.question(a["question"])]
    if a.get("date_from"):
        conds.append("d.published_at >= %s::timestamptz")
        params.append(a["date_from"])
    if a.get("date_to"):
        conds.append("d.published_at < %s::timestamptz + interval '1 day'")
        params.append(a["date_to"])
    if a.get("source"):
        conds.append("d.source = ANY(%s)")
        params.append([s.strip() for s in a["source"].split(",") if s.strip()])
    for col in ("kind", "lang"):
        if a.get(col):
            conds.append(f"d.{col} = %s")
            params.append(a[col])
    return " AND ".join(conds), params


def search(conn, question: str, *, date_from: str | None = None, date_to: str | None = None,
           source: str | None = None, kind: str | None = None, lang: str | None = None,
           limit: int = 20, oldest: bool = False, bucket: str | None = None, full: bool = False) -> dict:
    """The one way the archive is asked. Returns counts, the span, optional
    buckets (month | year | source) and the matching texts."""
    a = {"question": question, "date_from": date_from, "date_to": date_to, "source": source,
         "kind": kind, "lang": lang}
    where, params = _where(a)
    wanted = T.question_keys(question)
    n, first, last, publishers = conn.execute(
        f"SELECT count(*), min(d.published_at), max(d.published_at), count(DISTINCT d.source)"
        f"  FROM document d WHERE {where}", params).fetchone()
    out: dict = {"question": question, "asked_as": T.question(question), "matches": n,
                 "publishers": publishers, "first": first and first.isoformat(),
                 "last": last and last.isoformat(),
                 "filters": {k: v for k, v in a.items() if v and k != "question"}}
    if bucket in ("month", "year"):
        out["by_" + bucket] = [
            {bucket: b.strftime("%Y-%m" if bucket == "month" else "%Y"), "texts": c, "publishers": p}
            for b, c, p in conn.execute(
                f"SELECT date_trunc('{bucket}', d.published_at) b, count(*), count(DISTINCT d.source)"
                f"  FROM document d WHERE {where} AND d.published_at IS NOT NULL GROUP BY 1 ORDER BY 1", params)]
    elif bucket == "source":
        out["by_source"] = [
            {"source": s, "name": nm, "texts": c, "first": f and f.date().isoformat(), "last": l and l.date().isoformat()}
            for s, nm, c, f, l in conn.execute(
                f"SELECT d.source, s.name, count(*), min(d.published_at), max(d.published_at)"
                f"  FROM document d JOIN archive_source s ON s.key = d.source WHERE {where}"
                f" GROUP BY 1, 2 ORDER BY 3 DESC", params)]
    rows = conn.execute(
        f"SELECT d.doc_id, d.source, s.name, d.kind, d.url, d.title, d.body, d.extra, d.published_at, d.lang"
        f"  FROM document d JOIN archive_source s ON s.key = d.source WHERE {where}"
        f" ORDER BY d.published_at {'ASC' if oldest else 'DESC'} NULLS LAST LIMIT %s", [*params, limit]).fetchall()
    out["texts"] = []
    for doc_id, src, name, kind_, url, title, body, extra, at, lang_ in rows:
        whole = "\n".join(x for x in (title, body, extra) if x)
        out["texts"].append({
            "doc_id": doc_id, "date": at and at.isoformat(), "source": src, "publisher": name, "kind": kind_,
            "lang": lang_, "url": url, "title": title,
            "text": whole if full else T.snippet(whole, wanted), "chars": len(whole)})
    return out


def held(conn) -> dict:
    rows = conn.execute(
        "SELECT d.source, s.name, s.kind, count(*), min(d.published_at), max(d.published_at),"
        "       count(*) FILTER (WHERE length(d.body) > 1500)"
        "  FROM document d JOIN archive_source s ON s.key = d.source GROUP BY 1, 2, 3 ORDER BY 4 DESC").fetchall()
    n, first, last = conn.execute("SELECT count(*), min(published_at), max(published_at) FROM document").fetchone()
    by_year = conn.execute("SELECT extract(year FROM published_at)::int, count(*) FROM document"
                           " WHERE published_at IS NOT NULL GROUP BY 1 ORDER BY 1").fetchall()
    return {"documents": n, "first": first and first.isoformat(), "last": last and last.isoformat(),
            "by_year": {str(y): c for y, c in by_year},
            "publishers": [{"source": s, "name": nm, "kind": k, "texts": c, "long_texts": lg,
                            "first": f and f.date().isoformat(), "last": l and l.date().isoformat()}
                           for s, nm, k, c, f, l, lg in rows]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Ask the archive a question (read-only).")
    ap.add_argument("question", nargs="?")
    ap.add_argument("--from", dest="date_from")
    ap.add_argument("--to", dest="date_to")
    ap.add_argument("--source", help="publisher keys, comma-separated (tg:qudsn,web:middleeasteye)")
    ap.add_argument("--kind", choices=["post", "article", "report", "statement", "entry"])
    ap.add_argument("--lang")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--oldest", action="store_true", help="oldest first")
    ap.add_argument("--months", action="store_const", const="month", dest="bucket")
    ap.add_argument("--years", action="store_const", const="year", dest="bucket")
    ap.add_argument("--sources", action="store_const", const="source", dest="bucket")
    ap.add_argument("--full", action="store_true", help="whole texts, not a cut around the word")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--held", action="store_true", help="what the archive holds, by publisher")
    a = ap.parse_args()
    if not a.held and not a.question:
        ap.error("give a question, or --held")
    with connect() as conn:
        conn.execute("SET default_transaction_read_only = on")
        try:
            out = held(conn) if a.held else search(
                conn, a.question, date_from=a.date_from, date_to=a.date_to, source=a.source, kind=a.kind,
                lang=a.lang, limit=a.limit, oldest=a.oldest, bucket=a.bucket, full=a.full)
        except T.BadQuestion as e:
            print(f"cannot ask that: {e}", file=sys.stderr)
            return 2
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        return 0
    if a.held:
        print(f"{out['documents']:,} texts, {out['first'] and out['first'][:10]} to {out['last'] and out['last'][:10]}")
        print("by year: " + "  ".join(f"{y}:{c:,}" for y, c in out["by_year"].items()))
        for p in out["publishers"]:
            print(f"  {p['texts']:>9,}  {p['source']:<28} {p['first']} → {p['last']}  long texts {p['long_texts']:,}  {p['name']}")
        return 0
    print(f"{out['matches']:,} texts match, from {out['publishers']} publisher(s), "
          f"{out['first'] and out['first'][:10]} to {out['last'] and out['last'][:10]}   [{out['asked_as']}]")
    for key in ("by_month", "by_year"):
        for b in out.get(key, []):
            print(f"  {b.get('month') or b.get('year')}  {b['texts']:>6,}  {'#' * min(60, b['texts'])}")
    for s in out.get("by_source", []):
        print(f"  {s['texts']:>7,}  {s['source']:<28} {s['first']} → {s['last']}  {s['name']}")
    for t in out["texts"]:
        print(f"\n{(t['date'] or '?')[:10]} · {t['publisher']} · {t['kind']} · {t['url'] or ''}")
        print("  " + t["text"].replace("\n", "\n  "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
