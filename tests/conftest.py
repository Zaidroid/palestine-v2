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
