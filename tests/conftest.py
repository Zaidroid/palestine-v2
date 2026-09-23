"""Make bare `pytest tests/` work.

test_arabic.py and test_ingest.py are standalone scripts ending in
`raise SystemExit(main())`, which fires at collection and kills the whole
run with `INTERNALERROR> SystemExit: 0`. HANDOFF.md's answer was a warning
paragraph and an 11-file explicit list that has already drifted twice —
first silently missing two new test files, then missing test_fuel_image.py.
A list a human must remember to update is not a fix; a collector that
cannot pick up the scripts is.
"""
collect_ignore = ["test_arabic.py", "test_ingest.py", "eval_geo.py"]

import pytest                                                        # noqa: E402


@pytest.fixture(autouse=True)
def _clear_rate_limit_buckets():
    """TestClient is not a localhost caller, so its requests count against the
    per-address limiter like a real client's. Running several test files back to
    back then fails on `429` instead of on the behaviour under test — measured
    2026-09-23, when a four-file run tripped the write class and a single-file
    run of the same test passed. Cleared per test; the limiter has its own tests
    that build the state they need.
    """
    from serve import ratelimit
    for book in ratelimit._buckets.values():       # keep the class keys: the
        book.clear()                               # middleware indexes them
    yield
    for book in ratelimit._buckets.values():
        book.clear()
