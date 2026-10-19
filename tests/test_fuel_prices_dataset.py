"""The fuel price dataset is served like every other databank category.

Read-only assertions against the live store; the loader idempotency test writes
only the same 24+ rows it would re-write in a normal nightly run.
"""
from __future__ import annotations

from resolve.db import connect


def test_fuel_dataset_is_served():
    with connect() as c:
        c.execute("SET default_transaction_read_only = on")
        ds = c.execute("SELECT dataset_id FROM dataset WHERE key = 'fuel_prices_official'").fetchone()
        assert ds, "migration 128 is not applied"
        dataset_id = ds[0]

        believed = c.execute("SELECT count(*) FROM fuel_price_believed").fetchone()[0]
        obs = c.execute(
            "SELECT count(*) FROM observation WHERE dataset_id = %s AND upper_inf(sys_period)",
            (dataset_id,)).fetchone()[0]
        assert believed > 0
        assert obs == believed, (obs, believed)

        served = c.execute(
            "SELECT count(*) FROM databank_serving WHERE v1_category = 'fuel'").fetchone()[0]
        assert served >= believed

        rows = c.execute("""
            SELECT indicator, unit, place_id, v1_stable_id, identity_key, attrs
            FROM observation
            WHERE dataset_id = %s AND upper_inf(sys_period)
        """, (dataset_id,)).fetchall()
        assert len({r[0] for r in rows}) == 8
        assert {r[1] for r in rows} == {"ILS/L", "ILS/cylinder"}
        assert {r[2] for r in rows} == {2}
        assert all(r[3] and r[4] and r[5].get("outlets") for r in rows)


def test_loader_is_idempotent():
    from ops.load_fuel_prices import DATASET, load

    def count():
        with connect() as c:
            c.execute("SET default_transaction_read_only = on")
            return c.execute(
                "SELECT count(*) FROM observation o JOIN dataset d USING (dataset_id)"
                " WHERE d.key = %s AND upper_inf(o.sys_period)", (DATASET,)).fetchone()[0]

    before = count()
    load()
    load()
    assert count() == before


def test_known_october_2026_values():
    """The 1 October 2026 list, as the outlets agreed on it.

    8.17 / 8.99 / 90.00 are the confirmed values in fuel_price_current; a wrong
    observation would be a wrong number in every downstream story.
    """
    with connect() as c:
        c.execute("SET default_transaction_read_only = on")
        rows = c.execute("""
            SELECT indicator, value_num
            FROM databank_serving
            WHERE v1_category = 'fuel' AND occurred_at = '2026-10-01'
        """).fetchall()
    values = {r[0]: float(r[1]) for r in rows}
    assert round(values["fuel.price.official.gasoline_95"], 2) == 8.17
    assert round(values["fuel.price.official.diesel"], 2) == 8.99
    assert round(values["fuel.price.official.lpg_12kg"], 2) == 90.00
