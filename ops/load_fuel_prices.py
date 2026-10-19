"""Load the believed official fuel prices into the databank.

    .venv/bin/python -m ops.load_fuel_prices
    .venv/bin/python -m ops.load_fuel_prices --dry-run

`fuel_price_believed` (a view over `fuel_price_report`, migration 071) is the
only source. One observation per product and effective date, in the
`fuel_prices_official` dataset (migration 128), on the West Bank place. The
identity is (dataset, product, effective date); a re-run updates the value and
provenance and never duplicates. The 2003→2026 history is filled by
ops/backfill_fuel_prices.py writing reports; the view and this loader follow.

Nothing is believed here: the belief rule is SQL (migration 071).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timezone

from resolve.db import connect

DATASET = "fuel_prices_official"
PLACE = 2  # West Bank; Gaza has no official consumer fuel price
INDICATOR = "fuel.price.official.{}"

UPSERT = """
INSERT INTO observation (dataset_id, place_id, indicator, value_num, unit,
                         occurred_at, occurred_precision, reported_at, raw_ref,
                         attrs, identity_key, v1_stable_id)
VALUES (%(dataset_id)s, %(place_id)s, %(indicator)s, %(value)s, %(unit)s,
        %(occurred)s, 'day', %(reported)s, %(raw_ref)s, %(attrs)s::jsonb,
        %(identity)s, %(stable)s)
ON CONFLICT (dataset_id, v1_stable_id, occurred_at)
    WHERE (v1_stable_id IS NOT NULL AND upper(sys_period) IS NULL)
DO UPDATE SET value_num = EXCLUDED.value_num,
              unit = EXCLUDED.unit,
              occurred_precision = EXCLUDED.occurred_precision,
              reported_at = EXCLUDED.reported_at,
              raw_ref = EXCLUDED.raw_ref,
              attrs = EXCLUDED.attrs
"""


def believed(conn):
    return conn.execute("""
        SELECT b.effective_from, b.product, b.price, p.unit, b.named_units,
               b.distinct_texts, b.outlets, b.urls, b.first_published
        FROM fuel_price_believed b
        JOIN fuel_price_product p USING (product)
        ORDER BY b.effective_from, b.product
    """).fetchall()


def load(dry_run: bool = False) -> int:
    with connect() as conn:
        row = conn.execute("SELECT dataset_id FROM dataset WHERE key = %s", (DATASET,)).fetchone()
        if not row:
            raise SystemExit("dataset fuel_prices_official missing: apply migration 128")
        dataset_id = row[0]
        rows = believed(conn)
        if dry_run:
            print(f"{len(rows)} believed rows; dataset {dataset_id}; no write")
            return 0
        for (effective_from, product, price, units, named_units,
             distinct_texts, outlets, urls, first_published) in rows:
            occurred = datetime.combine(effective_from, time.min, tzinfo=timezone.utc)
            stable = f"{DATASET}:{product}:{effective_from.isoformat()}"
            identity = f"fuel|{product}|{effective_from.isoformat()}"
            attrs = {
                "outlets": outlets,
                "urls": urls,
                "distinct_texts": distinct_texts,
                "named_units": named_units,
                "authority": "Palestinian General Petroleum Corporation",
                "reader": "fuel_price@4",
            }
            conn.execute(UPSERT, {
                "dataset_id": dataset_id,
                "place_id": PLACE,
                "indicator": INDICATOR.format(product),
                "value": price,
                "unit": units,
                "occurred": occurred,
                "reported": first_published,
                "raw_ref": (urls[0] if urls else None),
                "attrs": json.dumps(attrs, ensure_ascii=False),
                "identity": identity,
                "stable": stable,
            })
        conn.commit()
        print(f"loaded {len(rows)} observations into {DATASET}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    return load(ap.parse_args().dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
