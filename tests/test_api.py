"""Every route, actually called. The test that was missing.

    .venv/bin/python -m pytest tests/test_api.py -q

WHY THIS FILE EXISTS
`/v2/fuel/stations` returned 500 on every request for two days — from the
commit that introduced it (bac07b2, P1) until it was found by hand. One missing
`::text` cast made Postgres raise IndeterminateDatatype on `$1 IS NULL`, and
nothing noticed, because the entire test suite reached the database and the
belief model directly and never issued a single HTTP request. 173 pytest checks
and 53 SQL gates all passed while the flagship per-station fuel endpoint — the
first thing any frontend would call — was dead.

So the rule here is coverage BY CONSTRUCTION: the route table is read from the
live app, and every route must be exercised. Adding a route without adding a
sample makes `test_every_route_is_covered` fail. A hand-maintained list of
paths would drift the same way the hand-maintained PREFER_PLACE_KIND dict did
(migration 035), and drift silently in exactly the same way.

WHAT THIS DOES AND DOES NOT ASSERT
It asserts each route ANSWERS — a 2xx, or a deliberate 4xx for bad input. It
does not assert the numbers are right; that is what the SQL gates and the
belief tests are for. This layer only catches the class of failure they
structurally cannot see: the query that never runs, the serialiser that chokes,
the parameter that cannot be bound.

Data-independence matters: fuel went silent on 2026-08-01 when the source
switched to images, so a test asserting "stations are returned" would now fail
for a reason that is not a bug. These assert the SHAPE holds when the data is
empty, which is the state an honest system spends a lot of its time in.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from serve.app import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

# Ramallah, and a point in the Jordan Valley with nothing near it. Coordinates
# are supplied rather than resolved so a rename in `place` cannot turn a
# transport failure into a geocoding failure.
LAT, LON = 31.9038, 35.2034
EMPTY_LAT, EMPTY_LON = 31.55, 35.50

# path -> list of query-string variants to exercise. Every route in the app must
# appear as a key; the coverage test enforces it.
CASES: dict[str, list[dict]] = {
    "/":                        [{}],
    "/health":                  [{}, {"verbose": "true"}],
    "/v2":                      [{}],
    "/v2/services":             [{}],
    "/v2/limits":               [{}],
    "/v2/coverage":             [{}],
    "/v2/connectivity":         [{}],
    "/v2/weather":              [{}, {"place": "رام الله"}],
    "/v2/crossings":            [{}, {"area": "غزة"}],
    "/v2/crowd/fields":         [{}],
    "/v2/crowd/pending":        [{}],
    "/v2/stream/status":        [{}],
    "/v2/news/latest":          [{}, {"limit": 3}, {"area": "نابلس"}],
    "/v2/checkpoints/summary":  [{}],
    "/v2/databank/categories":  [{}],
    "/v2/databank/radar":       [{}],
    # as_of exercises the sys_period path — the value it returns for July is
    # asserted exactly in test_databank_asof_serves_superseded_value.
    "/v2/databank/{category}":  [{"category": "prisoners"},
                                 {"category": "prisoners",
                                  "indicator": "prisoners.child",
                                  "as_of": "2026-07-15"},
                                 {"category": "conflict",
                                  "indicator":
                                  "conflict.westbank_cumulative_killed"},
                                 {"category": "water"},
                                 {"category": "no_such_category"}],
    "/v2/export/checkpoints.csv":     [{}],
    "/v2/export/checkpoints.geojson": [{}],
    "/v2/export/incidents.csv":       [{}, {"days": 7}],
    "/v2/export/incidents.geojson":   [{}, {"days": 7}],
    "/v2/export/fuel.csv":            [{}],
    "/v2/incidents/summary":    [{}, {"hours": 6}],
    "/v2/incidents/recent":     [{}, {"hours": 6, "limit": 5},
                                 {"lat": LAT, "lon": LON, "radius_km": 10}],
    "/v2/history/area":         [{}, {"days": 7}, {"state_kind": "checkpoint_status"}],
    # Both variants of the filter, because it was the None branch of exactly
    # this shape of optional filter that 500'd everywhere it was uncast.
    "/v2/fuel/stations":        [{}, {"region": "أريحا"}, {"only_available": "true"},
                                 {"region": "أريحا", "only_available": "true"},
                                 {"region": "no-such-region-ﻻ"}],
    "/v2/fuel/summary":         [{}],
    "/v2/fuel/nearby":          [{"lat": LAT, "lon": LON},
                                 {"lat": LAT, "lon": LON, "fuel": "diesel"},
                                 {"lat": EMPTY_LAT, "lon": EMPTY_LON}],
    "/v2/checkpoints/nearby":   [{"lat": LAT, "lon": LON},
                                 {"lat": LAT, "lon": LON, "include_unknown": "true"},
                                 {"lat": EMPTY_LAT, "lon": EMPTY_LON}],
    # `direction` is inbound/outbound/both — compass points are refused with a
    # 400, which is correct and is asserted in test_bad_enum_is_refused.
    "/v2/checkpoints/status":   [{"name": "حوارة"},
                                 {"name": "حوارة", "direction": "outbound"},
                                 {"name": "حوارة", "direction": "both"}],
    "/v2/geo/resolve":          [{"q": "حوارة"}, {"q": "رام الله", "state_kind": "fuel_diesel"}],
    "/v2/history/place":        [{"place_id": 1}],
    "/v2/patterns/place":       [{"place_id": 1}],
    "/v2/route":                [{"from_lat": LAT, "from_lon": LON,
                                  "to_lat": 32.2211, "to_lon": 35.2544}],
    "/v2/route/between":        [{"origin": "رام الله", "destination": "نابلس"}],
    # SSE, and correctly infinite: `snapshot` means "send current state ON
    # CONNECT", not "send it and hang up". A plain GET never returns, so it gets
    # a dedicated streaming test instead of a row here.
    "/v2/stream":               [],
    # POSTs are exercised for REJECTION only — see test_write_routes_reject.
    "/v2/crowd/register":       [],
    "/v2/crowd/report":         [],
}

GET_CASES = [(p, params) for p, variants in CASES.items() for params in variants]


def _routes() -> set[str]:
    return {r.path for r in app.routes
            if getattr(r, "methods", None) and r.path.startswith(("/v2", "/health", "/"))
            and r.path not in ("/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect")}


def test_every_route_is_covered() -> None:
    """A new route without a sample here fails the build, not production."""
    missing = _routes() - set(CASES)
    assert not missing, f"routes with no smoke case: {sorted(missing)}"


@pytest.mark.parametrize("path,params", GET_CASES, ids=lambda v: str(v)[:40])
def test_route_answers(path: str, params: dict) -> None:
    r = client.get(path, params=params)
    # 500 is the failure this file exists to catch. A 404/422 from a route that
    # was given valid input is equally a bug, so only 2xx passes here.
    assert r.status_code == 200, (
        f"{path} {params} -> {r.status_code}: {r.text[:400]}")
    assert r.headers["content-type"].split(";")[0] in (
        "application/json", "text/event-stream",
        # P4.2 exports; geo+json for maps, csv for spreadsheets.
        "text/csv", "application/geo+json"), r.headers["content-type"]


@pytest.mark.parametrize("path,params", [
    ("/v2/checkpoints/status", {}),          # name is required
    ("/v2/geo/resolve", {}),                 # q is required
    ("/v2/history/place", {}),               # place_id is required
    ("/v2/fuel/nearby", {"lat": LAT}),       # lon is required
    ("/v2/route", {"from_lat": LAT}),        # the other three are required
])
def test_missing_required_params_are_422_not_500(path: str, params: dict) -> None:
    """Bad input must be refused, not crashed on."""
    assert client.get(path, params=params).status_code == 422


@pytest.mark.parametrize("path,params", [
    ("/v2/fuel/nearby", {"lat": "north", "lon": LON}),
    ("/v2/history/place", {"place_id": "الظاهرية"}),
    ("/v2/incidents/summary", {"hours": "many"}),
])
def test_wrong_types_are_422_not_500(path: str, params: dict) -> None:
    assert client.get(path, params=params).status_code == 422


def test_unknown_place_id_is_handled_not_crashed() -> None:
    """A place_id that does not exist is a normal answer, not an exception."""
    for path in ("/v2/history/place", "/v2/patterns/place"):
        r = client.get(path, params={"place_id": 99_999_999})
        assert r.status_code in (200, 404), f"{path} -> {r.status_code}: {r.text[:200]}"


def test_route_between_unknown_place_is_refused_cleanly() -> None:
    r = client.get("/v2/route/between",
                   params={"origin": "لا يوجد مكان بهذا الاسم", "destination": "نابلس"})
    assert r.status_code in (200, 404, 422), r.text[:300]
    if r.status_code == 200:
        # If it answers 200 it must NOT have invented a route.
        assert not r.json().get("routes"), "routed from a place that does not exist"


def test_write_routes_reject_bad_credentials() -> None:
    """The report path must refuse an unknown submitter rather than 500."""
    r = client.post("/v2/crowd/report", params={
        "handle": "no-such-submitter", "token": "wrong",
        "state_kind": "checkpoint_status", "place": "حوارة", "value": "open"})
    assert r.status_code in (401, 403, 422), f"{r.status_code}: {r.text[:300]}"


def test_register_is_reachable_but_not_exercised() -> None:
    """Registration is rate-limited to 3/hour and creates real rows.

    Calling it for real would spend the live budget and leave test submitters in
    `submitter`, so this only asserts the route rejects a malformed handle. The
    happy path is covered against a rolled-back transaction in test_crowd.py.
    """
    r = client.post("/v2/crowd/register", params={"handle": ""})
    assert r.status_code in (400, 422, 429), f"{r.status_code}: {r.text[:200]}"


def test_bad_enum_is_refused() -> None:
    r = client.get("/v2/checkpoints/status",
                   params={"name": "حوارة", "direction": "north"})
    assert r.status_code in (400, 422), f"{r.status_code}: {r.text[:200]}"


def test_routing_engine_is_the_routing_engine() -> None:
    """Guards a port collision, not an outage.

    `VALHALLA_URL` was set to 127.0.0.1:8002 in .env — a host port belonging to
    honcho-api-1, a different application on this machine, which answered every
    routing request with a well-formed 404. Both route endpoints returned 503
    for anything that loaded .env, while production worked because its unit
    sets no VALHALLA_URL and fell through to the correct default in code.

    Reachability alone would not have caught it: something WAS listening.
    """
    import httpx
    url = os.environ.get("VALHALLA_URL", "http://172.22.0.2:8002")
    try:
        r = httpx.get(f"{url}/status", timeout=10.0)
    except Exception as exc:                                    # noqa: BLE001
        pytest.skip(f"valhalla unreachable at {url}: {exc}")
    assert r.status_code == 200, f"{url} -> {r.status_code}"
    assert r.json().get("version"), (
        f"{url} answered but names no valhalla version — wrong service")


def test_stream_opens_and_sends_a_snapshot() -> None:
    """SSE never returns, so read the opening events and hang up.

    The connection staying open is the feature — a subscriber that reconnects
    every poll would defeat the point. So this asserts the handshake and the
    opening snapshot arrive, then closes rather than waiting for a change that
    may be minutes away.

    The generator is driven directly rather than through TestClient, which
    collects a response body before returning it and therefore never returns at
    all for a stream that is designed not to end.
    """
    import asyncio

    from serve.stream import event_source

    async def first_two() -> list[str]:
        gen = event_source(snapshot=True)
        try:
            return [await anext(gen), await anext(gen)]
        finally:
            await gen.aclose()

    hello, snapshot = asyncio.run(first_two())
    assert hello.startswith("event: hello"), hello[:120]
    assert snapshot.startswith("event: snapshot"), snapshot[:120]
    payload = json.loads(snapshot.split("data:", 1)[1].strip())
    assert payload["asserted"] == len(payload["states"])
    # An empty snapshot is legitimate — it is what an honest system sends when
    # nothing is currently assertable — but the key must be present either way,
    # or a client cannot distinguish "nothing asserted" from "field missing".
    assert isinstance(payload["states"], list)


# REST read routes with no MCP tool, and why. Anything not listed here must
# have one, so a new read endpoint cannot quietly become frontend-only.
MCP_EXEMPT = {
    "/", "/v2", "/health",          # service metadata, not data
    "/v2/limits", "/v2/services",   # ditto
    "/v2/stream",                   # an agent cannot hold an SSE socket open;
                                    # `stream_info` describes it instead
    "/v2/crowd/pending",            # moderation surface, human-only
    # The crowd WRITE path is deliberately absent from MCP entirely: an agent
    # that can file reports is the sock-puppet problem P2.4 exists for, running
    # at machine speed. See the note at the foot of the TOOLS registry.
    "/v2/crowd/register", "/v2/crowd/report", "/v2/crowd/fields",
    # Covered by can_i_travel, which answers the journey rather than the maths.
    "/v2/route", "/v2/route/between",
    # Covered by checkpoint_status / checkpoints_near / fuel_near.
    "/v2/checkpoints/status", "/v2/checkpoints/nearby", "/v2/fuel/nearby",
    "/v2/fuel/stations",
    # Covered by place_history / place_pattern / area_history, which resolve the
    # name themselves so an agent never has to hold a place_id.
    "/v2/history/place", "/v2/history/area", "/v2/patterns/place",
    "/v2/stream/status", "/v2/geo/resolve",
    # Bulk export is a file-download surface for humans and GIS tools; an
    # agent reads the same data through the query tools row by row.
    "/v2/export/checkpoints.csv", "/v2/export/checkpoints.geojson",
    "/v2/export/incidents.csv", "/v2/export/incidents.geojson",
    "/v2/export/fuel.csv",
}


def test_mcp_read_surface_is_at_parity_with_rest() -> None:
    """"One place to read everything" must not mean "unless you are an agent".

    Two surfaces that drift end with nobody knowing which is authoritative.
    MCP had 16 tools against 30 routes and was missing crossings and place
    resolution outright — an agent asked about Rafah had no way to answer.
    """
    from serve.mcp_server import TOOLS

    covered = {
        "/v2/coverage": "coverage", "/v2/crossings": "crossings",
        "/v2/weather": "weather_now", "/v2/connectivity": "connectivity_now",
        "/v2/news/latest": "latest_news", "/v2/incidents/recent": "incidents_near",
        "/v2/incidents/summary": "incidents_summary",
        "/v2/checkpoints/summary": "checkpoints_summary",
        "/v2/fuel/summary": "fuel_summary",
        "/v2/databank/categories": "databank",
        "/v2/databank/{category}": "databank",
        "/v2/databank/radar": "data_gaps",
    }
    missing = _routes() - MCP_EXEMPT - set(covered)
    assert not missing, f"REST routes with no MCP tool and no exemption: {sorted(missing)}"
    for path, tool in covered.items():
        assert tool in TOOLS, f"{path} claims MCP tool {tool!r}, which does not exist"


def test_mcp_never_exposes_the_crowd_write_path() -> None:
    """An agent must not be able to file a crowd report.

    P2.4 gates reassuring values behind independent units precisely because one
    actor with many voices is the failure mode. A tool would hand that to any
    agent with a socket.
    """
    from serve.mcp_server import TOOLS

    banned = {"report", "submit", "register", "crowd"}
    for name in TOOLS:
        assert not any(b in name.lower() for b in banned), \
            f"MCP tool {name!r} looks like a write path"


def test_health_reports_faults_honestly() -> None:
    """/health must go degraded when the watchdog has faults, not always-200-ok.

    Fuel has been silent since the palhub channel switched to images on
    2026-08-01; a /health that still said "ok" through that would be worse than
    no /health at all.
    """
    body = client.get("/health").json()
    assert body["status"] in ("ok", "degraded", "down"), body.get("status")
    assert body["jobs_total"] > 0 and body["feeds_total"] > 0
    if body.get("faults"):
        assert body["status"] != "ok", "faults present but status still ok"


def test_stale_states_are_not_served_as_current() -> None:
    """The decay gate, checked through HTTP rather than through SQL.

    With fuel silent for over a day, every station must read `unknown`. If this
    starts failing because fuel came back, that is fine — but it must never fail
    because a 27-hour-old reading is being presented as today's.
    """
    body = client.get("/v2/fuel/summary").json()
    for fuel, t in body["totals"].items():
        stale_hours = 27
        if t["total"] and t["available"]:
            r = client.get("/v2/fuel/stations", params={"only_available": "true"})
            for st in r.json()["stations"]:
                for f in st["fuels"].values():
                    if f["value"] == "available":
                        assert (f["age_minutes"] or 0) < stale_hours * 60, (
                            f"{fuel}: serving a {f['age_minutes']}-minute-old "
                            f"'available' as current")


def test_exports_carry_the_honesty_columns() -> None:
    """An export that drops staleness_band lets a week-old "open" travel the
    world looking fresh. The columns are the contract, so they are asserted."""
    csv_head = client.get("/v2/export/checkpoints.csv").text.splitlines()[0]
    for col in ("staleness_band", "age_minutes", "confidence", "last_known_flow"):
        assert col in csv_head, f"checkpoints.csv lost {col}"
    fuel_head = client.get("/v2/export/fuel.csv").text.splitlines()[0]
    assert "staleness_band" in fuel_head

    gj = client.get("/v2/export/checkpoints.geojson").json()
    assert gj["type"] == "FeatureCollection" and gj["features"], "empty export"
    props = gj["features"][0]["properties"]
    assert "staleness_band" in props and "flow" in props
    assert gj["features"][0]["geometry"]["coordinates"][0] is not None

    inc = client.get("/v2/export/incidents.geojson", params={"days": 30}).json()
    assert inc["type"] == "FeatureCollection"
    assert all(f["properties"]["confidence"] is not None for f in inc["features"])


def test_databank_asof_serves_superseded_value() -> None:
    """T2.4's whole point, through the public surface: what did Addameer
    report for children in detention as of 15 July? 350 — a value revised
    upstream on 1 August, absent from the current surface at that date+value,
    reachable only at its own time."""
    r = client.get("/v2/databank/prisoners",
                   params={"indicator": "prisoners.child",
                           "as_of": "2026-07-15"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(i["value_num"] == 350 for i in items), items
    r = client.get("/v2/databank/prisoners",
                   params={"indicator": "prisoners.child"})
    current = [(i["occurred_at"][:10], i["value_num"]) for i in r.json()["items"]]
    assert ("2026-07-01", 350.0) not in current, current


def test_databank_categories_carry_licenses() -> None:
    r = client.get("/v2/databank/categories")
    assert r.status_code == 200
    ds = r.json()["datasets"]
    assert len(ds) >= 25
    assert all(d["attribution"] and d["license"] for d in ds)
    # the tier decision, visible: sellable is a real partition
    assert {d["sellable"] for d in ds} == {True, False}


def test_martyrs_serves_aggregates_by_default_names_by_intent() -> None:
    """Serving posture (2026-08-05): the license permits per-name serving of
    60,199 dead; decency defaults to aggregates and makes reading names a
    deliberate act, not a row dump."""
    r = client.get("/v2/databank/martyrs_snapshot_2023")
    body = r.json()
    assert body["memorial"] is False
    assert body["identified_total"] > 60000
    assert "items" not in body                      # no names by default
    r = client.get("/v2/databank/martyrs_snapshot_2023",
                   params={"memorial": "true",
                           "indicator": "martyrs.identified_killed",
                           "limit": 2})
    names = [i["value_text"] for i in r.json()["items"]]
    assert all(names), names                        # real names, deliberately

def test_westbank_cumulative_series_is_served_and_sellable() -> None:
    """Phase 4 brick 1: the WB series v1's unified transform destroys is
    served from the raw tree — region-grade, day precision, public domain."""
    r = client.get("/v2/databank/conflict",
                   params={"indicator": "conflict.westbank_cumulative_killed"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items, "WB cumulative series missing from serving surface"
    # the indicator param is a PREFIX filter, so _killed also returns
    # _killed_children — assert on the exact series
    killed = [i for i in items
              if i["indicator"] == "conflict.westbank_cumulative_killed"]
    assert killed, "exact killed series absent"
    latest = max(killed, key=lambda i: i["occurred_at"])
    assert latest["value_num"] >= 1108          # monotonic cumulative
    # attribution is response-level (the set of source credits), not per row
    assert any("Tech4Palestine" in a for a in r.json()["attribution"])
    assert all(i["attrs"].get("flash_source") in ("un", "fill")
               for i in items[:20])

def test_water_is_a_domain_one_fact_served_once() -> None:
    """The water recovery (2026-08-06): the category serves its own dataset
    plus health's JMP WASH access series — both namespaces visible, no fact
    duplicated (each indicator+date+dim appears exactly once)."""
    r = client.get("/v2/databank/water", params={"limit": 2000})
    assert r.status_code == 200
    items = r.json()["items"]
    spaces = {i["indicator"].split(".")[0] for i in items}
    assert spaces == {"water", "health"}, spaces
    keys = [(i["indicator"], i["occurred_at"], i["attrs"].get("code"))
            for i in items]
    assert len(keys) == len(set(keys)), "a fact is served twice"
    assert any(i["indicator"].startswith("water.wsh_sanitation_od")
               for i in items)
    assert any(i["indicator"] == "health.wsh_water_basic.residenceareatype_totl"
               for i in items)

def test_gap_radar_measures_on_data_dates_not_mtimes() -> None:
    """The June-9 lesson as a contract: the radar reports per-dataset
    freshness from the data's own dates against a learned rhythm, declares
    dead upstreams with evidence, and ranks open gaps."""
    r = client.get("/v2/databank/radar")
    assert r.status_code == 200
    d = r.json()
    assert d["counts"]["datasets"] >= 25
    by_status = {x["dataset"]: x for x in d["datasets"]}
    dead = by_status["v1_aid_access_unrwa_aid_trucks"]
    assert dead["status"] == "dead_upstream" and dead["dead_reason"]
    for x in d["datasets"]:
        assert x["status"] in ("fresh", "late", "stalled", "dead_upstream",
                               "closed_corpus", "unmeasured")
        if x["status"] in ("fresh", "late", "stalled"):
            assert x["age_days"] is not None and x["allowance_days"] > 0
    assert all(g["severity"] >= g2["severity"]
               for g, g2 in zip(d["gaps"], d["gaps"][1:])), "gaps unranked"
    assert "era_grid" in d and "1922–1947" in next(iter(d["era_grid"].values()))
