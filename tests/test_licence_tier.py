"""F-81 — what may leave the building, per tool and per datum.

    ./.venv/bin/python -m pytest tests/test_licence_tier.py -q

The door being shut (F-80) says who may call. This file is about what they may
carry away once they do, and the property it defends is narrow and easy to lose:

  Our derived observations are ours to give. Somebody else's WORDING is not.

Every source feeding `latest_news` and `search` is graded `no-redistribution`
(measured: 20 sources, 67,193 messages over 30 characters, median body 376
chars). A partner release that returns those bodies in full is republishing
other people's articles, and no key we issue can grant a licence we do not hold.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import app as A                                        # noqa: E402
from serve import licence as L                                    # noqa: E402
from serve import mcp_http as m                                   # noqa: E402
from serve.app import app                                         # noqa: E402

client = TestClient(app)


def call(name, tier="partner", **args):
    """One tools/call through the HTTP transport, at a chosen tier."""
    return m._handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": name, "arguments": args}},
                     None, tier)


def payload(reply):
    import json
    return json.loads(reply["result"]["content"][0]["text"])


# ── every public tool is graded, or the build fails ──────────────────────────

def test_every_public_tool_carries_a_licence_grade():
    """A tool that ships ungraded is a tool whose output nobody can lawfully
    use. The grading table is the gate, so a new tool cannot arrive without a
    licence decision — that decision is the F-81 work itself, not paperwork
    after it."""
    ungraded = set(m.PUBLIC_TOOLS) - set(L.TOOLS)
    assert not ungraded, f"public tools with no licence grade: {sorted(ungraded)}"


def test_the_grading_table_does_not_grade_tools_that_do_not_exist():
    """The other direction: a stale entry for a removed tool makes the table
    claim coverage it does not have."""
    from serve.mcp_server import TOOLS
    assert not set(L.TOOLS) - set(TOOLS)


def test_the_route_reports_full_coverage_and_names_any_gap():
    r = client.get("/v2/licence/tools")
    assert r.status_code == 200
    d = r.json()
    assert d["graded"] == d["public_tools"], d["ungraded"]
    assert d["ungraded"] == []
    # A subset that does not name its total is the defect this system keeps
    # finding in its own payloads.
    assert len(d["tools"]) == d["public_tools"]


# ── the grades are read, not typed ───────────────────────────────────────────

def test_grades_come_from_the_database_not_from_this_module():
    """A licence grade asserted in code is a grade that can disagree with
    /v2/databank/licenses forever without anyone noticing. Re-grading a source
    must move this table, which is only true if it is read per call."""
    seen = {}

    def fake_q(sql, params=()):
        if "state_observation" in sql:
            return [{"g": "no-redistribution"}]
        if "claim c" in sql:
            return [{"g": "no-redistribution"}]
        if "databank_internal" in sql:
            return [{"g": "attribution"}]
        if "located" in sql:
            return [{"g": "open"}]
        seen["sources"] = True
        return [{"key": "open_meteo", "redistribution": "share-alike",
                 "license_spdx": "x", "attribution_text": "x",
                 "verified_on": None},
                {"key": "ioda", "redistribution": "open", "license_spdx": "x",
                 "attribution_text": "x", "verified_on": None}]

    graded = L.grade_tools(fake_q)
    assert seen.get("sources"), "the source grades were never read"
    # The stub inverted both: weather graded share-alike and IODA graded open.
    # If either number were typed in this module, this assertion would fail.
    assert graded["weather_now"]["grade"] == "share-alike"
    assert graded["connectivity_now"]["grade"] == "open"


def test_a_copied_coordinate_keeps_its_grade_but_a_reduction_does_not():
    """The line 066 drew holds for a value we COMPUTED and not for one we
    COPIED. A checkpoint's flow is our belief over other people's claims and is
    ours to give; the coordinate printed beside it is a gazetteer row, so its
    licence travels. Same stub, two different answers, decided only by whether
    the tool echoes a coordinate."""
    def fake_q(sql, params=()):
        if "located" in sql:
            return [{"g": "share-alike"}]        # every servable place is ODbL
        if "state_observation" in sql or "claim c" in sql:
            return [{"g": "no-redistribution"}]
        if "databank_internal" in sql:
            return [{"g": "attribution"}]
        return []

    g = L.grade_tools(fake_q)
    # Echoes a resolved coordinate -> the ODbL obligation propagates.
    assert g["where_is"]["grade"] == "share-alike"
    assert g["insights"]["grade"] == "share-alike"
    # Reduces claims and prints no coordinate -> ours, despite the same
    # `no-redistribution` channels underneath.
    assert g["area_history"]["grade"] == "open"
    assert g["incidents_summary"]["grade"] == "open"


def test_checkpoint_coordinates_are_not_graded_as_odbl():
    """Measured 2026-09-24 over the SERVABLE located gazetteer, following each
    station to the anchor its centroid was copied from: checkpoints, roads and
    crossings are `v1_checkpoints` and hand-entered geography (open), while 402
    fuel stations are OpenStreetMap (ODbL). So a checkpoint tool is open and a
    name-resolving tool, which can land on a station, is share-alike. Grading
    them alike would be wrong in one direction or the other."""
    d = client.get("/v2/licence/tools").json()
    by = {t["tool"]: t for t in d["tools"]}
    assert by["checkpoint_status"]["grade"] == "open"
    assert by["crossings"]["grade"] == "open"
    assert by["checkpoints_summary"]["grade"] == "open"
    # And the name-resolving tools, which can reach an ODbL station, are not.
    assert by["where_is"]["grade"] == "share-alike"
    assert by["insights"]["grade"] == "share-alike"


def test_the_unservable_odbl_gazetteer_does_not_encumber_the_live_tools():
    """2,584 Palestine Open Maps localities are ODbL AND servable=false — they
    exist so a live report naming طنطورة does not resolve to a village destroyed
    in 1948, and `resolve/geo.py` filters them out. A grade that counted rows no
    tool can return would assert an obligation a partner does not actually have,
    which is the mirror image of the error this table prevents."""
    def fake_q(sql, params=()):
        if "located" in sql:
            # The servable gazetteer only; if the WHERE clause dropped
            # `p.servable`, the live query would find share-alike here.
            assert "p.servable" in sql, "the gazetteer query stopped filtering servable"
            return [{"g": "open"}]
        return []

    g = L.grade_tools(fake_q)
    assert g["where_is"]["grade"] == "open"


def test_a_stations_grade_follows_the_anchor_its_centroid_came_from():
    """`palhub_loader.py` builds each fuel station by copying the centroid of
    the place it resolved to, so `"source": "palhub"` says where the NAME came
    from, not the geometry — there is no palhub coordinate dataset to hold a
    licence. Grading those 186 rows `ask` on an unmatched key would invent an
    obligation over coordinates taken from our own open gazetteer."""
    sqls = []

    def fake_q(sql, params=()):
        sqls.append(sql)
        if "located" in sql:
            return [{"g": "open"}]
        return []

    L.grade_tools(fake_q)
    geo = " ".join(s for s in sqls if "located" in s)
    assert "geo_anchor_place_id" in geo, \
        "the gazetteer grade no longer follows a station to its anchor"


def test_can_i_travel_carries_no_geometry_so_it_is_not_encumbered():
    """Routing runs over ODbL OpenStreetMap roads, but the payload is a verdict,
    named checkpoints, a distance and a duration — verified against the live
    tool. A number derived from an ODbL map is a fact about a journey, not an
    extract of the database. If a future change adds geometry, this test is the
    one that should fail."""
    out = payload(call("can_i_travel", tier="partner",
                       origin="رام الله", destination="نابلس"))
    import json as _json
    body = _json.dumps(out, ensure_ascii=False, default=str)
    assert '"lat"' not in body and '"lon"' not in body, \
        "can_i_travel now emits coordinates: re-grade it against the gazetteer"
    assert out["licence"]["emits"] == L.DERIVED


def test_a_payload_is_as_redistributable_as_its_worst_datum():
    assert L._worst(["open", "attribution"]) == "attribution"
    assert L._worst(["attribution", "no-redistribution"]) == "no-redistribution"
    assert L._worst(["open", "ask", "attribution"]) == "ask"
    assert L._worst([]) == "open"


def test_ask_is_not_inside_the_partner_tier():
    """A publisher whose terms nobody has read has not agreed. IODA states All
    Rights Reserved on every API response and the letter to them is drafted and
    unsent (source_permission: ioda, not_asked) — a partner release is the wrong
    place to discover which way that goes."""
    assert "ask" not in L.PARTNER_ALLOWED
    d = client.get("/v2/licence/tools").json()
    conn = next(t for t in d["tools"] if t["tool"] == "connectivity_now")
    assert conn["grade"] == "ask"
    assert conn["partner_tier"] == "cited_fact_only"


def test_a_derived_observation_over_odbl_geometry_is_not_open():
    """ODbL's whole mechanism is that copyleft travels INTO a derived database.
    A coordinate we echoed out of Palestine Open Maps is still ODbL-encumbered,
    and calling it `open` because we did the computing around it is the error
    that costs a partner their licence. `full` is still right — ODbL rows are
    sellable — but the obligation has to be visible before they build."""
    d = client.get("/v2/licence/tools").json()
    w = next(t for t in d["tools"] if t["tool"] == "where_is")
    assert w["grade"] == "share-alike"
    assert w["partner_tier"] == "full"      # sellable, with the obligation named
    assert "share-alike" in w["underlying_grades"]


# ── the cut, where it actually matters ───────────────────────────────────────

def test_a_partner_gets_an_excerpt_of_a_channels_wording_not_the_body():
    out = payload(call("latest_news", tier="partner", limit=5))
    lic = out["licence"]
    assert lic["emits"] == L.VERBATIM
    assert lic["tier"] == "partner"
    for it in out["items"]:
        assert len(it["text"]) <= L.EXCERPT_CHARS + 1     # +1 for the ellipsis
        if it.get("excerpted"):
            # A cut that does not announce itself reads as a short message.
            assert it["full_text_chars"] > L.EXCERPT_CHARS


def test_the_house_still_reads_the_whole_message():
    """The classifiers, the analyst and Fawwaz are inside the system, not
    consumers of it: they need the body to produce the answers the partner tier
    serves. Cutting them would break the thing being licensed."""
    out = payload(call("latest_news", tier="house", limit=5))
    assert out["licence"]["tier"] == "house"
    assert not any(it.get("excerpted") for it in out["items"])


def test_the_cut_is_stated_in_the_payload_and_never_silent():
    out = payload(call("latest_news", tier="partner", limit=10))
    lic = out["licence"]
    assert "excerpted_items" in lic and "refused" in lic
    assert str(L.EXCERPT_CHARS) in lic["refused"]
    assert "no-redistribution" in lic["refused"]


def test_the_spoken_answer_carries_the_same_cut_as_the_payload():
    """`latest_news` quotes the newest message INSIDE `answer`, so a cut applied
    only to `items` is defeated by one f-string. The answer a voice assistant
    reads aloud is a republication too."""
    out = payload(call("latest_news", tier="partner", limit=3))
    for key in ("answer", "answer_en"):
        if out.get(key):
            assert len(out[key]) <= L.EXCERPT_CHARS + 1


def test_search_is_cut_the_same_way_as_latest_news():
    """Two doors onto the same corpus. A control on one of them is not a
    control."""
    out = payload(call("search", tier="partner", text="حاجز", hours=72))
    if out.get("items"):
        assert out["licence"]["emits"] == L.VERBATIM
        for it in out["items"]:
            assert len(it["text"]) <= L.EXCERPT_CHARS + 1


def test_the_rest_route_cuts_too_because_it_is_public_on_its_own():
    """The MCP tool reads /v2/news/latest, and that route answers the open
    internet by itself. A cut in the MCP layer alone is decoration — measured
    2026-09-24, the route served full bodies to an unauthenticated caller."""
    r = client.get("/v2/news/latest", params={"limit": 5})
    assert r.status_code == 200
    d = r.json()
    assert d["licence"]["emits"] == L.VERBATIM
    for it in d["items"]:
        assert len(it["text"]) <= L.EXCERPT_CHARS + 1


def test_a_caller_cannot_talk_its_way_into_the_house_tier():
    """The tier is decided from who is calling, never from an argument. A tool
    that took `tier` as a parameter would hand the decision to the caller."""
    import inspect
    from serve.mcp_server import TOOLS
    for name, (fn, _, schema) in TOOLS.items():
        assert "tier" not in inspect.signature(fn).parameters, name
        assert "tier" not in (schema.get("properties") or {}), name


def test_a_derived_tool_is_not_cut():
    """The live tracker is the clean core and the whole reason a partner tier
    exists at all. Cutting it would be as wrong as not cutting the news."""
    out = payload(call("checkpoints_summary", tier="partner"))
    assert out["licence"]["emits"] == L.DERIVED
    assert "excerpted_items" not in out["licence"]


def test_an_unknown_tool_is_labelled_ungraded_rather_than_clean():
    """The failure mode to avoid is a missing grade reading as permission."""
    out = L.apply("not_a_tool", {"answer": "x"}, "partner")
    assert out["licence"]["graded"] is False
    assert "do not redistribute" in out["licence"]["note"]


def test_labelling_never_takes_down_an_answer_about_a_road():
    """A licence bug must degrade to an unlabelled answer, never to no answer:
    the thing being denied would be somebody finding out whether a road is
    open."""
    out = L.apply("latest_news", {"answer": "x", "items": "not a list"},
                  "partner")
    assert out["answer"] == "x"
    out2 = L.apply("latest_news", {"error": "boom"}, "partner")
    assert out2 == {"error": "boom"}


# ── the licence block must not contradict the payload under it ───────────────
# Reported by an external reviewer who compared the block against the payload
# beside it, 2026-09-24. Each of these is a contradiction found that way.

def test_a_share_alike_tool_says_so_in_its_own_payload():
    """A grade that names a copyleft and a payload that never mentions it leaves
    the reader to discover the obligation after they have shipped. The table
    said `share-alike`; the per-call block said nothing."""
    out = payload(call("where_is", tier="partner", place="نابلس"))
    lic = out["licence"]
    assert lic["grade"] == "share-alike"
    # `full` means sellable — which is true, and exactly why the obligation has
    # to travel beside it rather than be inferred from the tier name.
    assert lic["partner_tier"] == "full"
    joined = " ".join(lic.get("obligations") or [])
    assert "SHARE-ALIKE" in joined and "DERIVED DATABASE" in joined


def test_a_metadata_tool_does_not_claim_to_be_computed_from_reports():
    """`coverage` describes what THIS SYSTEM holds; `licenses` is our own
    register; `licence_tools` is this table; `data_gaps` measures our own
    freshness; `stream_info` describes our transport. None of them reduces
    anybody's reports, and saying so was boilerplate that was simply false."""
    for tool in ("coverage", "data_gaps", "licenses", "licence_tools",
                 "stream_info"):
        assert L.TOOLS[tool]["emits"] == L.METADATA, tool
        out = payload(call(tool, tier="house"))
        note = out["licence"]["emits_note"].lower()
        assert "reports" not in note, f"{tool} still claims to reduce reports"
        assert "this system" in note


def test_the_checkpoint_tools_explain_the_osm_credit_instead_of_hiding_it():
    """They return this platform's OWN checkpoint coordinates and a `km`
    computed over OpenStreetMap roads, and their attribution credits OSM. The
    grade is `open` because ODbL calls a computed distance a PRODUCED WORK
    (attribution owed, your database is your own) — not because OSM is being
    copied. The reviewer read the credit and the grade as contradictory; the
    fix is to state the distinction, not to hide either half."""
    out = payload(call("checkpoints_near", tier="partner", place="نابلس",
                       limit=3))
    lic = out["licence"]
    assert lic["grade"] == "open"
    joined = " ".join(lic.get("obligations") or [])
    assert "PRODUCED WORK" in joined
    assert "OpenStreetMap" in " " + str(out.get("source", ""))
    # And the coordinates really are ours: the gazetteer query that decides this
    # grades checkpoint/crossing/road without OSM provenance.
    assert "checkpoint" in L.GEO_CHECKPOINT_KINDS


def test_the_incident_bearing_profile_does_not_deny_its_own_coordinates():
    """`place_profile` says it resolves a place name; when that place has
    incidents, every incident row carries a latitude and longitude. Its note
    used to assert the payload carried no coordinate, which is false for
    exactly the payloads where it matters."""
    sample = payload(call("place_profile", tier="partner", place="حوارة"))
    note = sample["licence"].get("note", "")
    assert "no coordinate" not in note.lower()
    # Either it carries coordinates, or the note does not claim it never can.
    body = json.dumps(sample, ensure_ascii=False)
    if '"lat"' in body:
        assert "DOES carry coordinates" in note


def test_full_text_chars_is_the_message_length_not_the_route_cap():
    """The route caps every body at NEWS_TEXT_CHARS before the licence layer
    sees it, so `len(text)` was that cap wearing the name of a fact: every
    excerpted item reported exactly 500. A number labelled "full" must be the
    full length, or the reason for its absence must be named."""
    assert A.NEWS_TEXT_CHARS == 500
    r = client.get("/v2/news/latest", params={"limit": 25})
    for it in r.json()["items"]:
        assert "text_full_chars" in it, "the true length is not reported"
        assert it["text_full_chars"] >= len(it["text"].rstrip("…"))
        if it.get("excerpted"):
            assert it["full_text_chars"] > L.EXCERPT_CHARS, \
                "an excerpt whose 'full' length is the cut length"
            if it["full_text_chars"] == A.NEWS_TEXT_CHARS:
                # Legitimate: the route capped it. Name that rather than passing
                # the cap off as the message length.
                assert it.get("truncated_by_route") is True


def test_connectivity_attribution_is_read_from_the_registry_not_typed():
    """It said 'CC BY-NC 4.0' while the registry said All Rights Reserved and
    `redistribution = ask` — two contradictory licence claims in ONE payload.
    The string was an assumption recorded with no terms_url (migration 053) and
    migration 067 replaced it by reading IODA's own API."""
    p = payload(call("connectivity_now", tier="partner"))
    assert "CC BY-NC" not in json.dumps(p, ensure_ascii=False), \
        "a superseded licence claim is back"
    assert p.get("license") == "LicenseRef-IODA-All-Rights-Reserved"
    assert p.get("redistribution") == "ask"
    assert p["licence"]["grade"] == "ask"
    # The registry's own wording: a copyright line with no grant of any kind,
    # which is why the grade is `ask` rather than `attribution`.
    assert "Copyright" in str(p.get("attribution", ""))
    assert "Georgia Tech" in str(p.get("attribution", ""))


def test_every_tool_that_carries_an_obligation_says_which_kind_it_is():
    """Obligations are the part a reader acts on. A payload may carry two
    different ones (a Produced Work's attribution and a Derivative Database's
    copyleft); each must be nameable, and the two kinds must be distinguishable
    rather than one blob of boilerplate.

    Counted from the SPECS, not by calling every tool: most tools need
    arguments, so calling them with none returns an error payload that carries no
    licence block and the count would silently under-report."""
    declared = {t: spec["obligations"] for t, spec in L.TOOLS.items()
                if spec.get("obligations")}
    assert len(declared) >= 3, f"almost nothing declares an obligation: {declared}"
    for tool, obs in declared.items():
        for ob in obs:
            assert isinstance(ob, str) and len(ob) > 60, (tool, ob)
            assert "PRODUCED WORK" in ob, (tool, ob)
    # The OTHER kind — the copyleft that travels into a partner's database — is
    # attached from the measured grade rather than declared per tool, because
    # whether it applies is a property of the sources, not of the code. Both
    # kinds must exist and must be distinguishable, or the reader cannot tell
    # "cite us" from "license your database the same way".
    assert "PRODUCED WORK" in L._OSM_PRODUCED_WORK
    assert "DERIVED DATABASE" in L._SHARE_ALIKE_OBLIGATION
    assert L._OSM_PRODUCED_WORK != L._SHARE_ALIKE_OBLIGATION
    # And the copyleft one reaches a real payload, from the grade.
    out = payload(call("where_is", tier="partner", place="نابلس"))
    obs = " ".join(out["licence"]["obligations"])
    assert "DERIVED DATABASE" in obs


# ── the two surfaces must agree ──────────────────────────────────────────────

def test_the_tool_and_the_route_report_the_same_table():
    """Two surfaces that drift end with nobody knowing which is authoritative —
    and for a licence claim that is the most expensive drift available."""
    rest = client.get("/v2/licence/tools").json()
    tool = payload(call("licence_tools", tier="house"))
    assert tool["public_tools"] == rest["public_tools"]
    assert tool["partner_tier_counts"] == rest["partner_tier_counts"]
    assert {t["tool"]: t["grade"] for t in tool["tools"]} == \
           {t["tool"]: t["grade"] for t in rest["tools"]}


def test_the_grade_never_contradicts_the_databank_licence_register():
    """Both read `source.redistribution`. If a databank source is graded
    `no-redistribution` there, a databank tool may not advertise `full` here."""
    reg = client.get("/v2/databank/licenses").json()
    worst = L._worst([r["redistribution"] for r in reg["licenses"]
                      if r.get("redistribution")])
    d = client.get("/v2/licence/tools").json()
    db = next(t for t in d["tools"] if t["tool"] == "databank")
    assert db["grade"] == worst
    assert db["partner_tier"] == "filtered"


def test_the_answer_states_the_warning_when_something_is_ungraded():
    """The pattern this system keeps having to relearn: a payload's summary
    sentence must not be cleaner than the payload under it."""
    d = dict(client.get("/v2/licence/tools").json())
    d["ungraded"] = ["pretend_tool"]
    from serve.mcp_en import licence_tools as render
    assert "do not redistribute" in render(d).lower()
