"""UCDP's own supply line (ops/fetch_ucdp.py) and the conflict spec's cut from v1.

Everything here is offline. The fixtures under tests/fixtures/supply_ucdp/ are
real rows saved on 2026-10-12: eleven events from GED 26.1 and ten from GED
25.1 (the release the store holds, through v1's HDX extract), seven candidate
events from the three files UCDP listed that day, the frozen v1 records of the
seven sampled events the store holds, and the two entries of UCDP's download
page that carry the links. No network, no database.
"""
from __future__ import annotations

import gzip
import json
from collections import Counter
from pathlib import Path

import pytest

from ingest import databank
from ingest.databank import EventRow, load_spec
from ops import fetch_ucdp as fu
from ops import fetchlib as fl

ROOT = Path(__file__).resolve().parent.parent
FX = Path(__file__).resolve().parent / "fixtures" / "supply_ucdp"
HEAD = {"last_modified": "Mon, 08 Jun 2026 19:54:24 GMT", "etag": '"1dcf780988cee5a"'}
CANDIDATES = (("26.01.26.06", "candidate_26_01_26_06_sample.csv", "Mon, 20 Jul 2026 17:46:11 GMT"),
              ("26.0.7", "candidate_26_0_7_sample.csv", "Thu, 20 Aug 2026 22:26:48 GMT"),
              ("26.0.8", "candidate_26_0_8_sample.csv", "Sun, 20 Sep 2026 20:44:14 GMT"))


def rows_of(name):
    with open(FX / name, "rb") as fh:
        return fu.read_events(fh)


@pytest.fixture(scope="module")
def held():
    """UCDP id → the frozen v1 record, for the seven sampled held events."""
    data = json.loads((FX / "frozen_sample.json").read_text())["data"]
    return {r["id"].split("-", 1)[1]: r for r in data}


@pytest.fixture(scope="module")
def release(held):
    rows, seen = rows_of("ged261_sample.csv")
    load, revision = fu.build_release(rows, seen, version="26.1",
                                      url="https://ucdp.uu.se/downloads/ged/ged261-csv.zip",
                                      head=HEAD, held=held, fetched_at="2026-10-12T20:00:00+00:00")
    return rows, load, revision


def candidate_files():
    return [{"version": v, "url": f"https://ucdp.uu.se/downloads/candidateged/{n}",
             "last_modified": lm, "rows": rows_of(n)[0]} for v, n, lm in CANDIDATES]


# ── the download page ────────────────────────────────────────────────────────

def test_the_download_page_names_the_release_and_the_candidate_files():
    page = fu.parse_downloads_page((FX / "downloads_page.html").read_text(encoding="utf-8"))
    assert page["release"] == {"version": "26.1",
                               "url": "https://ucdp.uu.se/downloads/ged/ged261-csv.zip"}
    assert [c["version"] for c in page["candidates"]] == ["26.0.8", "26.0.7", "26.01.26.06"]
    assert all(c["url"].endswith(".csv") for c in page["candidates"])     # never the xlsx


def test_the_highest_release_on_the_page_wins_and_a_page_without_one_is_an_error():
    html = ('<a href="/downloads/ged/ged251-csv.zip">old</a>'
            '<a href="https://ucdp.uu.se/downloads/ged/ged271-csv.zip">new</a>')
    assert fu.parse_downloads_page(html)["release"]["version"] == "27.1"
    with pytest.raises(ValueError):
        fu.parse_downloads_page("<html>maintenance</html>")


# ── scope: v1's two rules ────────────────────────────────────────────────────

def test_the_scope_is_v1s_text_filter_and_its_israel_proper_rule():
    rows, seen = rows_of("ged251_sample.csv")
    by = {r["id"]: r for r in rows}
    assert seen == {"rows_global": 10, "last_year": 2023} and len(rows) == 10
    assert fu.region_of(by["178019"]) == "West Bank" and fu.in_scope(by["178019"])
    assert fu.region_of(by["498841"]) == "Gaza Strip"
    assert fu.region_of(by["238985"]) == "East Jerusalem" and fu.in_scope(by["238985"])
    # a Palestinian dyad at a place called only "Israel": v1 left it out
    assert fu.is_palestinian(by["177076"]) and fu.region_of(by["177076"]) == "Israel"
    assert not fu.in_scope(by["177076"])
    # "PIJ - Civilians" in Jerusalem names neither Palestine, Gaza nor the West
    # Bank in any field v1 read, so v1 never took it. The scope is unchanged.
    assert not fu.is_palestinian(by["177265"]) and not fu.in_scope(by["177265"])
    assert not fu.in_scope({**by["178019"], "country_id": "652"})          # another country


# ── the stable id ────────────────────────────────────────────────────────────

def test_v1s_stable_id_is_a_hash_of_the_content_and_ucdps_id_is_not_in_it(held):
    for rec in held.values():
        assert fu.v1_stable_id(rec) == rec["stable_id"]
    rec = held["178019"]
    assert fu.v1_stable_id({**rec, "id": "ucdp-1"}) == rec["stable_id"]     # the id is stripped
    later = json.loads(json.dumps(rec))
    later["sources"][0]["fetched_at"] = "2027-01-01T00:00:00.000Z"
    assert fu.v1_stable_id(later) == rec["stable_id"]                       # so is the fetch time
    revised = json.loads(json.dumps(rec))
    revised["metrics"]["killed"] += 1
    assert fu.v1_stable_id(revised) != rec["stable_id"]                     # a correction is a new id


def test_every_held_id_is_rebuilt_from_ged_25_1s_own_row(held):
    """The reproduction the brief asks for: UCDP's CSV row, through a port of
    v1's two transforms and v1's hash, gives the id the store holds. 32.0 must
    be written 32 as JavaScript does (180353), and v1's gazetteer pass filled
    `governorate` where UCDP names none (176952, 238985)."""
    rows, _ = rows_of("ged251_sample.csv")
    rebuilt = {r["id"]: fu.v1_stable_id(fu.v1_unified_record(r, held[r["id"]]["location"]))
               for r in rows if r["id"] in held}
    assert rebuilt == {uid: rec["stable_id"] for uid, rec in held.items()} and len(rebuilt) == 7
    assert held["180353"]["location"]["lat"] == 32 and held["176952"]["location"]["governorate"] == "jerusalem"


def test_two_events_v1_could_not_tell_apart_shared_one_id():
    """348278 and 348283 are two UCDP events of 2012-11-18 in Gaza town with
    every field v1 read the same. One hash, so v1 kept one: 183 real events of
    GED 25.1 never reached the store this way."""
    rows, _ = rows_of("ged251_sample.csv")
    by = {r["id"]: r for r in rows}
    assert by["348278"]["relid"] != by["348283"]["relid"]
    assert fu.v1_stable_id(fu.v1_unified_record(by["348278"])) == \
        fu.v1_stable_id(fu.v1_unified_record(by["348283"]))


def test_a_held_event_keeps_its_id_and_any_other_event_is_named_by_ucdps_id(held):
    assert fu.stable_id_for("178019", held) == "c0fb2dff8f228167310d959a0000f5b1"
    assert fu.stable_id_for("583677", held) == "ucdp-ged:583677"
    assert fu.stable_id_for(583677, {}) == "ucdp-ged:583677"


def test_the_frozen_corpus_holds_7638_ucdp_events_and_every_id_is_its_hash():
    held = fu.load_held()
    assert len(held) == 7638 and fu.held_through(held) == "2024-12-31"
    assert all(fu.v1_stable_id(r) == r["stable_id"] for r in held.values())
    assert len({r["stable_id"] for r in held.values()}) == 7638


# ── the release ──────────────────────────────────────────────────────────────

def test_only_events_after_the_held_period_are_given_to_the_loader(release):
    _, load, revision = release
    assert [r["ucdp_id"] for r in load["data"]] == ["583677"]
    [rec] = load["data"]
    assert rec["date"] == "2025-05-31" and rec["stable_id"] == "ucdp-ged:583677"
    assert "ucdp_vs_held" not in rec
    assert load["metadata"]["coverage"] == {"first": "2025-05-31", "last": "2025-05-31"}
    assert load["metadata"]["release_counts"] == {
        "rows_global": 11, "rows_country_666": 11, "palestine_related": 10, "in_scope": 9,
        "release_last_year": 2025, "dated_after_the_held_period": 1,
        "inside_the_held_period": 8}
    assert {r["ucdp_id"] for r in revision["data"]} == {
        "178019", "238985", "180353", "348278", "348283", "498841", "176952", "601560"}


def test_every_release_event_says_which_release_and_none_says_candidate(release):
    _, load, revision = release
    for rec in load["data"] + revision["data"]:
        assert rec["ucdp_release"] == "26.1" and rec["quality"] == {"score": 0.95}
        assert "ucdp_candidate" not in rec and "ucdp_candidate_version" not in rec
        assert rec["sources"][0]["name"] == "UCDP-GED" and rec["sources"][0]["license"] == "CC BY 4.0"
        assert "date_precision" not in rec       # t_conflict would take it verbatim


def test_the_revision_file_says_what_the_release_did_to_each_held_event(release):
    _, _, revision = release
    status = {r["ucdp_id"]: r["ucdp_vs_held"] for r in revision["data"]}
    assert status == {"178019": "identical", "180353": "identical", "176952": "identical",
                      "348278": "identical", "238985": "revised", "498841": "revised",
                      "348283": "not_held", "601560": "not_held"}
    by = {r["ucdp_id"]: r for r in revision["data"]}
    assert by["178019"]["stable_id"] == "c0fb2dff8f228167310d959a0000f5b1"   # held id kept
    assert by["498841"]["stable_id"] == "bd94f895a06fdd6186ad554f60b19be0"   # also when revised
    assert by["348283"]["stable_id"] == "ucdp-ged:348283"
    h = revision["metadata"]["held"]
    assert (h["frozen_corpus_events"], h["in_release"], h["identical"], h["revised"]) == (7, 6, 4, 2)
    # UCDP's month-long row for Gaza, October 2023: 4,731 deaths in 25.1, 2,911 in 26.1
    assert by["498841"]["metrics"]["killed"] == 2911 and by["498841"]["ucdp_date_prec"] == 4
    assert by["498841"]["ucdp_date_end"] == "2023-10-31"
    assert (h["killed_as_held"], h["killed_as_release_reads_them"]) == (4738, 2917)
    assert h["revised_fields"]["killed"] == 2 and h["revised_fields"]["any_stored_field"] == 2
    # the event the release no longer has, and the two it has that the store does not
    assert h["absent_from_release"] == 1 and h["absent_killed"] == 18
    assert h["absent"][0]["ucdp_id"] == "496209" and h["absent"][0]["day"] == "2023-10-20"
    assert (h["not_held"], h["not_held_killed"]) == (2, 16)
    assert h["not_held_same_content_as_a_held_event"] == 1                   # 348283, the twin
    assert "NOT loaded" in revision["metadata"]["holds"]


def test_the_release_states_its_vintage_and_licence_as_the_publisher_does(release):
    _, load, _ = release
    m = load["metadata"]
    assert m["vintage"] == "2026-03-30" and m["published"] == "2026-06-08"
    assert "Data extracted from UCDP systems on 2026-03-30" in m["vintage_basis"]
    assert m["vintage_url"] == "https://ucdp.uu.se/downloads/ged/ged261.pdf"
    assert m["license"].startswith("CC BY 4.0") and "Sundberg and Melander (2013)" in m["attribution"]


def test_a_release_the_table_does_not_know_dates_itself_by_its_file(held):
    rows, seen = rows_of("ged261_sample.csv")
    load, _ = fu.build_release(rows, seen, version="27.1", url="https://x/ged271-csv.zip",
                               head=HEAD, held=held, fetched_at="t")
    m = load["metadata"]
    assert m["vintage"] == "2026-06-08" and m["vintage_basis"].startswith("HTTP Last-Modified")
    assert m["vintage_url"] == "https://x/ged271-csv.zip"


def test_with_nothing_held_every_event_is_new_and_nothing_is_held_back():
    rows, seen = rows_of("ged261_sample.csv")
    load, revision = fu.build_release(rows, seen, version="26.1", url="u", head=HEAD,
                                      held={}, fetched_at="t")
    assert len(load["data"]) == 9 and revision["data"] == []
    assert all(r["stable_id"] == f"ucdp-ged:{r['ucdp_id']}" for r in load["data"])


# ── the candidates ───────────────────────────────────────────────────────────

def test_candidate_events_are_flagged_and_carry_their_file_and_ucdps_doubt(release):
    rows, _, _ = release
    doc = fu.build_candidates(candidate_files(), fetched_at="t", release={
        "version": "26.1", "last_year": 2025, "ids": {r["id"] for r in rows}})
    recs = {r["ucdp_id"]: r for r in doc["data"]}
    assert sorted(recs) == ["610884", "613219", "635139", "636063", "636688", "639483"]
    assert "620657" not in recs                              # country 666, outside the scope
    for rec in recs.values():
        assert rec["ucdp_candidate"] is True and rec["stable_id"] == f"ucdp-ged:{rec['ucdp_id']}"
        assert "ucdp_release" not in rec and "quality" not in rec
        assert rec["date"] >= "2026-01-01"
    assert recs["613219"]["ucdp_candidate_version"] == "26.01.26.06"
    assert recs["636688"]["ucdp_candidate_version"] == "26.0.7"
    assert recs["639483"]["ucdp_candidate_version"] == "26.0.8"
    assert recs["610884"]["ucdp_code_status"] == "Check deaths"
    assert recs["636688"]["date"] == "2026-06-25" and recs["636688"]["ucdp_date_end"] == "2026-07-11"
    assert recs["613219"]["metrics"]["killed"] == 0          # UCDP lists it with no death yet
    m = doc["metadata"]
    assert m["after_release"] == "26.1" and m["vintage"] == "2026-09-20"
    assert m["counts"]["by_code_status"] == {"Check deaths": 1, "Clear": 5}
    assert [f["kept"] for f in m["files"]] == [2, 2, 2]
    assert "Not all events in UCDP Candidate will make it" in m["provisional"]


def test_an_event_in_two_candidate_files_is_read_from_the_newer_one():
    """UCDP re-extracts a quarter when it bundles it. No real pair existed on
    2026-10-12 (the three files shared no id), so the older copy is made here
    by changing one death count on a real row."""
    files = candidate_files()
    newer = next(r for r in files[2]["rows"] if r["id"] == "639483")
    files[1]["rows"] = files[1]["rows"] + [{**newer, "deaths_b": "9", "best": "9"}]
    doc = fu.build_candidates(files, fetched_at="t",
                              release={"version": "26.1", "last_year": 2025, "ids": set()})
    rec = next(r for r in doc["data"] if r["ucdp_id"] == "639483")
    assert rec["metrics"]["killed"] == 2 and rec["ucdp_candidate_version"] == "26.0.8"
    assert doc["metadata"]["counts"]["skipped"] == {"superseded_by_newer_file": 1}
    assert len(doc["data"]) == 6


def test_a_candidate_event_the_release_already_covers_is_not_kept():
    files = candidate_files()
    by_id = fu.build_candidates(files, fetched_at="t", release={
        "version": "26.1", "last_year": 2025, "ids": {"639483"}})
    assert "639483" not in {r["ucdp_id"] for r in by_id["data"]}
    assert by_id["metadata"]["counts"]["skipped"] == {"id_in_release": 1}
    by_year = fu.build_candidates(files, fetched_at="t", release={
        "version": "27.1", "last_year": 2026, "ids": set()})
    assert by_year["data"] == []
    assert by_year["metadata"]["counts"]["skipped"] == {"dated_inside_release": 6}


def test_a_row_is_from_a_release_or_from_a_candidate_file_never_both():
    row = rows_of("ged261_sample.csv")[0][0]
    for kw in ({}, {"release": "26.1", "candidate": "26.0.8"}):
        with pytest.raises(ValueError):
            fu.to_record(row, held={}, url="u", fetched_at="t", **kw)


# ── a newer release is a decision ────────────────────────────────────────────

def test_a_newer_release_on_the_page_stops_the_fetch_and_is_ledgered(monkeypatch, tmp_path, capsys):
    html = (FX / "downloads_page.html").read_text(encoding="utf-8").replace("ged261", "ged271")
    calls = []
    monkeypatch.setattr(fl, "get", lambda url, timeout=120: calls.append(url) or html.encode())
    monkeypatch.setattr(fl, "EVENTS", tmp_path / "fetch-events.ndjson")
    monkeypatch.setattr(fu, "RAW", tmp_path / "raw")
    assert fu.main([]) == 1
    assert calls == [fu.DOWNLOADS]                            # nothing was downloaded
    [line] = (tmp_path / "fetch-events.ndjson").read_text().splitlines()
    assert json.loads(line)["outcome"] == "pending" and json.loads(line)["label"] == "ucdp:ged"
    assert not (tmp_path / "raw").exists()
    assert "PENDING" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        fu.main(["--any-release"])                            # looking is a dry run only
    assert fu.LOADS_RELEASE == "26.1"


# ── the nightly posture: unchanged files stand, a shrunken answer is refused ──

def _night(monkeypatch, tmp_path, *, on_disk_events, moved=False):
    """One night's candidate half, against a candidate.json already on disk."""
    listing = fu.parse_downloads_page((FX / "downloads_page.html").read_text(encoding="utf-8"))
    names = {f"https://ucdp.uu.se/downloads/candidateged/GEDEvent_v{v.replace('.', '_')}.csv": (n, lm)
             for v, n, lm in CANDIDATES}
    monkeypatch.setattr(fu, "RAW", tmp_path / "raw")
    monkeypatch.setattr(fl, "EVENTS", tmp_path / "fetch-events.ndjson")
    fl.write_atomic(tmp_path / "raw" / "candidate.json", {"metadata": {
        "after_release": "26.1", "parser": fu.PARSER, "vintage": "2026-09-20",
        "counts": {"events": on_disk_events},
        "files": [{"url": u, "http_last_modified": "Sat, 01 Aug 2026 00:00:00 GMT" if moved else lm}
                  for u, (_, lm) in names.items()]}, "data": []})
    downloads = []
    monkeypatch.setattr(fu, "_head", lambda url: {"last_modified": names[url][1], "etag": None})

    def get(url):
        downloads.append(url)
        return (FX / names[url][0]).read_bytes(), {"last_modified": names[url][1], "etag": None}
    monkeypatch.setattr(fu, "_get", get)
    from ingest import bronze
    monkeypatch.setattr(bronze, "put", lambda key, blob, ext, **kw: type("R", (), {"ref": "bronze://test"})())
    ok = fu._attempt("ucdp:candidate", False, lambda: fu.fetch_candidates(
        listing, {"version": "26.1", "last_year": 2025, "ids": set()},
        dry=False, staged=None, force=False, fetched_at="t"))
    ledger = [json.loads(x) for x in (tmp_path / "fetch-events.ndjson").read_text().splitlines()]
    return ok, downloads, ledger, json.loads((tmp_path / "raw" / "candidate.json").read_text())


def test_candidate_files_that_did_not_move_are_not_downloaded_again(monkeypatch, tmp_path):
    ok, downloads, ledger, doc = _night(monkeypatch, tmp_path, on_disk_events=6)
    assert ok and downloads == []
    assert ledger == [{"label": "ucdp:candidate", "at": ledger[0]["at"], "outcome": "ok",
                       "rows": 6, "unchanged": True}]
    assert doc["data"] == []                                  # the file on disk stands


def test_a_candidate_file_that_moved_is_read_again_and_written(monkeypatch, tmp_path):
    ok, downloads, ledger, doc = _night(monkeypatch, tmp_path, on_disk_events=6, moved=True)
    assert ok and len(downloads) == 3
    assert [r["ucdp_id"] for r in doc["data"]] == ["613219", "610884", "636688", "635139",
                                                   "636063", "639483"]
    assert doc["metadata"]["bronze"] == ["bronze://test"] * 3
    assert ledger[-1]["outcome"] == "ok" and ledger[-1]["rows"] == 6
    assert ledger[-1]["data_through"] == "2026-08-31"


def test_a_candidate_answer_far_smaller_than_the_file_on_disk_is_refused(monkeypatch, tmp_path):
    """100 events on disk for this release, 6 in tonight's answer: yesterday's
    file is the better one, and the ledger says a fetch was refused."""
    ok, downloads, ledger, doc = _night(monkeypatch, tmp_path, on_disk_events=100, moved=True)
    assert ok is None and len(downloads) == 3
    assert doc["data"] == [] and doc["metadata"]["counts"]["events"] == 100
    assert ledger[-1]["outcome"] == "refused" and ledger[-1]["floor"] == 80


# ── what the loader makes of a record ────────────────────────────────────────

class _Pip:
    def resolve(self, lat, lon):
        return 18 if lat is not None else None


PLACES = {"region": {"Gaza Strip": 1, "West Bank": 2}, "governorate": {"Jerusalem": 11},
          "pcode": {}, "_pip": _Pip(), "_v1key": {}, "_commercial": {"ucdp": True}}


def test_t_conflict_reads_a_release_record_as_one_event_with_the_release_tag(release):
    _, load, _ = release
    spec = load_spec("conflict")
    [e] = databank.t_conflict(load["data"][0], spec, PLACES, Counter())
    assert isinstance(e, EventRow) and e.dataset_key == "v1_conflict_ucdp"
    assert e.event_type == "conflict.state_based" and e.v1_stable_id == "ucdp-ged:583677"
    assert (e.occurred_at, e.precision, e.confidence) == ("2025-05-31", "day", 0.95)
    assert (e.lat, e.lon, e.place_id, e.located) == (31.296999, 34.243439, 18, True)
    assert e.metrics == {"killed": 4, "unit": "persons"}
    assert e.attrs["ucdp_release"] == "26.1" and e.attrs["ucdp_id"] == "583677"
    assert e.attrs["name"] == "Rafah town" and e.attrs["region"] == "Gaza Strip"
    assert e.attrs["dyad_name"] == "Government of Israel - Hamas"
    assert "ucdp_candidate" not in e.attrs and "description" not in e.attrs


def test_t_conflict_reads_a_candidate_record_as_provisional(release):
    rows, _, _ = release
    doc = fu.build_candidates(candidate_files(), fetched_at="t", release={
        "version": "26.1", "last_year": 2025, "ids": {r["id"] for r in rows}})
    spec = load_spec("conflict")
    rec = next(r for r in doc["data"] if r["ucdp_id"] == "610884")
    [e] = databank.t_conflict(rec, spec, PLACES, Counter())
    assert e.v1_stable_id == "ucdp-ged:610884" and e.dataset_key == "v1_conflict_ucdp"
    assert e.attrs["ucdp_candidate"] is True
    assert e.attrs["ucdp_candidate_version"] == "26.01.26.06"
    assert e.attrs["ucdp_code_status"] == "Check deaths"
    assert "ucdp_release" not in e.attrs
    assert e.confidence == 0.7                    # no score claimed; the loader's default


# ── the spec ─────────────────────────────────────────────────────────────────

def test_the_conflict_spec_reads_the_frozen_copy_and_ucdps_release_never_v1():
    spec = load_spec("conflict")
    # the candidate events are fetched and not loaded: the loader cannot yet
    # revise or withdraw an event, and UCDP revises its candidates (2026-10-12)
    assert spec["input"] == {"root": "data", "glob": [
        "frozen/conflict.json.gz", "raw/ucdp/ged.json"]}
    assert "ged_revision" not in json.dumps(spec["input"])    # held back on purpose
    assert "candidate" not in json.dumps(spec["input"])
    assert spec["stable_id"] == "stable_id" and spec["transform"] == "python:t_conflict"
    for key in ("name", "ucdp_id", "ucdp_release", "ucdp_candidate",
                "ucdp_candidate_version", "ucdp_code_status"):
        assert key in spec["attrs_passthrough"]
    files = databank._input_files(spec["input"])
    assert files and files[0] == ROOT / "data" / "frozen" / "conflict.json.gz"


def test_no_other_source_in_the_frozen_copy_carries_a_key_added_to_the_passthrough():
    """The cumulative Tech4Palestine rows are observations compared by content;
    a new passthrough key present on them would read as 2,078 revisions."""
    spec = load_spec("conflict")
    added = [k for k in spec["attrs_passthrough"] if k == "name" or k.startswith("ucdp_")]
    assert len(added) == 9
    data = json.loads(gzip.decompress((ROOT / "data/frozen/conflict.json.gz").read_bytes()))["data"]
    assert len(data) == 10619
    others = [r for r in data if (r.get("sources") or [{}])[0].get("name") != "UCDP-GED"]
    assert len(others) == 2981
    assert not any(k in r for r in others for k in added)
    assert Counter((r.get("sources") or [{}])[0].get("name") for r in data)["UCDP-GED"] == 7638
