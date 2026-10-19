"""Backfill the official fuel-price reports from archived article bodies.

    .venv/bin/python -m ops.backfill_fuel_prices --dry-run
    .venv/bin/python -m ops.backfill_fuel_prices --from 2002-01-01

One archived article is one transcription, exactly as the live reader treats
it: cascade/fuel_price.parse, then the same fuel_price_report row. The belief
rule is SQL (migration 071); fuel_price_believed recomputes, and
ops/load_fuel_prices.py carries it into the databank. Nothing is believed here.

This is the history path: the 2,773 fuel-price headlines the archive holds from
2002 to 2026. Bodies are fetched separately (ops.fetch_articles) and parsed
here; a dry run reports the verdicts before anything is written.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from resolve.db import connect
from cascade import fuel_price
from ingest.sources.fuel_prices import _row, _INSERT

TOPIC = r"المحروقات|أسعار الوقود|اسعار الوقود|البنزين|السولار|أسعار الغاز|اسعار الغاز"
LOCAL = timezone(timedelta(hours=3))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from")
    ap.add_argument("--to", dest="date_to")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with connect() as conn:
        sql = """SELECT d.doc_id, d.source, d.url, d.published_at, d.body
                 FROM document d
                 WHERE d.body IS NOT NULL AND d.body <> ''
                   AND d.title ~* %s"""
        params: list = [TOPIC]
        if args.date_from:
            sql += " AND d.published_at >= %s"
            params.append(args.date_from)
        if args.date_to:
            sql += " AND d.published_at < %s"
            params.append(args.date_to)
        sql += " ORDER BY d.published_at"
        if args.limit:
            sql += " LIMIT %s"
            params.append(args.limit)
        rows = conn.execute(sql, params).fetchall()
        sources = {key: source_id for key, source_id in
                   conn.execute("SELECT key, source_id FROM source").fetchall()}

        verdicts: dict[str, int] = {}
        written = 0
        for doc_id, source_key, url, published, body in rows:
            local_day = published.astimezone(LOCAL).date() if published else None
            ann = fuel_price.parse(body, local_day)
            verdicts[ann.verdict] = verdicts.get(ann.verdict, 0) + 1
            if args.dry_run:
                continue
            domain = (urlparse(url).netloc.lower().removeprefix("www.")
                      if url else (source_key or "").removeprefix("web:"))
            row = _row(ann, outlet=domain, unit=f"web:{domain}", text=body,
                       url=url, published=published,
                       source_id=sources.get(source_key), bronze_ref=None)
            conn.execute(_INSERT, row)
            written += 1
        if not args.dry_run:
            conn.commit()
        print(f"articles {len(rows)}  written {written}  verdicts {verdicts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
