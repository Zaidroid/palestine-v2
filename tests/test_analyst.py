"""P0 of THE LOCAL ANALYST — the properties that, if they stopped holding,
would put the component back in the state it was built to escape.

    ./.venv/bin/python -m pytest tests/test_analyst.py -q

Four subjects:

  the detector      a language code is a measurement or it is `und`; it is
                    never a confident guess about a URL, an emoji or a blank
  the loop          the watermark advances over claims an organ DECLINED, a
                    model organ is skipped rather than retried when the PC is
                    gaming, and one bad claim costs one claim
  the metrics       a rate over an empty denominator is None, never 1.0
  the wiring        the cadence the loop beats at, and the cadence the watchdog
                    judges it by, are the same two numbers

The DB-touching tests run inside a transaction that is rolled back, the way
tests/test_crowd.py does it: the thing under test is the SQL and the migration,
and a Python reimplementation of either would only prove itself safe.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analyst import backpressure, lang, loop, store              # noqa: E402
from analyst.organs import LanguageOrgan, Reading, by_name        # noqa: E402
from ops.watchdog import EXPECTED_JOBS                           # noqa: E402
from resolve.db import dsn                                       # noqa: E402


@pytest.fixture()
def tx():
    """A transaction that is always rolled back. Never commits."""
    conn = psycopg.connect(dsn())
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


# ── the detector ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("الاحتلال يقتحم بلدة سلوان ويعتقل شابين", "ar"),
    ("حاجز حوارة سالك باتجاه نابلس", "ar"),
    ("Israeli forces raided the town of Silwan overnight", "en"),
    ("הבכיר שנעצר בעזה - ראש הביטחון הכללי של חמאס", "he"),
])
def test_the_three_languages_the_sources_actually_carry(text, expected):
    assert lang.detect(text)[0] == expected


@pytest.mark.parametrize("text", [
    "",                                   # 30,080 image-only fuel claims
    None,
    "🚗🚗",
    "١٢٣ ٤٥٦",
    "https://wp.me/paCNSd-uev",           # lingua calls a bare URL ENGLISH
    "https://www.youtube.com/watch?v=wyMytTncahI",
])
def test_text_that_decides_nothing_is_und_and_not_a_guess(text):
    """The failure this wrapper exists for, measured on 20,000 live claims:
    nine of the first twenty-five non-Arabic verdicts were nothing but a URL.
    A link is not a sentence in any language, and `en` on one of those rows is
    the same confident fiction as the `ar` this whole organ replaces."""
    assert lang.detect(text)[0] == lang.UNDETERMINED


def test_a_language_never_comes_from_the_noise_around_the_words():
    """Emoji, digits and a URL in the same post as four Arabic words must not
    move the verdict — and must not be what the verdict is made of."""
    assert lang.detect("🟢⛽️ بخصوص المحروقات https://t.me/x 22")[0] == "ar"
    assert "http" not in lang.clean("see https://example.com/x now")


def test_the_answer_is_always_one_of_the_four_words():
    """A detector offered 75 languages finds Urdu in Arabic. The candidate set
    is a decision; widening it is a re-measurement, not a default."""
    for text in ("الاحتلال", "Ministry of Health in Gaza", "העיר", "...."):
        assert lang.detect(text)[0] in {"ar", "en", "he", lang.UNDETERMINED}


def test_every_verdict_carries_what_produced_it():
    code, detector = lang.detect("اقتحام مدينة طوباس")
    assert code == "ar"
    assert re.fullmatch(r"lingua@\d+\.\d+\.\d+", detector), detector


def test_a_missing_detector_never_stops_ingestion(monkeypatch):
    """detect_quietly is called on the INSERT path of the poller, the feeds and
    the crowd door. A collector that died because a language library could not
    be imported would be a far worse bug than the one being repaired."""
    monkeypatch.setattr(lang, "_detector", None)
    monkeypatch.setattr(lang, "_build",
                        lambda: (_ for _ in ()).throw(ImportError("no lingua")))
    assert lang.detect_quietly("أي نص") == (None, None)
    with pytest.raises(ImportError):
        lang.detect("أي نص")


# ── organ A against the real table ───────────────────────────────────────────

def _source(cur) -> int:
    cur.execute("""INSERT INTO source (key,name,kind,license_spdx,commercial_use,
                                       attribution_text,authority_rank)
                   VALUES ('_t_analyst','_t_analyst','telegram','NONE',false,'t',5)
                   RETURNING source_id""")
    return cur.fetchone()[0]


def _claim(cur, source_id: int, text: str, lang_value: str = "ar") -> dict:
    cur.execute("""INSERT INTO claim (source_id, external_id, raw_ref, raw_text,
                                      lang, claim_type, reported_at)
                   VALUES (%s,%s,'test:ref',%s,%s,'unclassified', now())
                   RETURNING claim_id, ingested_at, attrs""",
                (source_id, f"m{text[:12]}", text, lang_value))
    cid, ing, attrs = cur.fetchone()
    return {"claim_id": cid, "ingested_at": ing, "raw_text": text,
            "lang": lang_value, "attrs": attrs}


def test_organ_a_corrects_the_value_and_stamps_what_corrected_it(tx):
    """The whole licence for writing to an immutable table is in the second
    half of this assertion. A corrected value with no provenance would be a
    second unfalsifiable constant, which is what `lang='ar'` already was."""
    with tx.cursor() as cur:
        sid = _source(cur)
        claim = _claim(cur, sid, "Ministry of Health in Gaza: daily report")
        reading = LanguageOrgan().read(cur, claim)
        assert reading.verdict == "en"
        cur.execute("SELECT lang, attrs->>'lang_detector' FROM claim "
                    "WHERE claim_id=%s", (claim["claim_id"],))
        value, detector = cur.fetchone()
        assert value == "en"
        assert detector and detector.startswith("lingua@")


def test_organ_a_never_reads_a_claim_twice(tx):
    """The stamp is also the idempotence key: a row that carries a detector is
    never selected again, which is what makes the backfill resumable by simply
    being re-run."""
    organ = LanguageOrgan()
    with tx.cursor() as cur:
        sid = _source(cur)
        claim = _claim(cur, sid, "اقتحام بلدة سلوان واعتقال شابين")
        assert organ.wants(claim) is True
        organ.read(cur, claim)
        cur.execute("SELECT attrs FROM claim WHERE claim_id=%s", (claim["claim_id"],))
        claim["attrs"] = cur.fetchone()[0]
        assert organ.wants(claim) is False
        assert organ.read(cur, claim) is None


def test_the_record_of_a_reading_is_a_row(tx):
    """Provenance that is a log line cannot be aggregated, which is exactly how
    29,686 MiniMax failures stayed invisible for three months."""
    with tx.cursor() as cur:
        sid = _source(cur)
        claim = _claim(cur, sid, "غارة على غرب مدينة غزة")
        store.record_run(cur, claim_id=claim["claim_id"], organ="lang",
                         organ_version="a/1", outcome="ok", model="lingua@2.2.0",
                         verdict="ar", latency_ms=3)
        cur.execute("""SELECT organ, outcome, model, verdict, votes, agreed,
                              json_valid FROM analyst_run WHERE claim_id=%s""",
                    (claim["claim_id"],))
        organ, outcome, model, verdict, votes, agreed, json_valid = cur.fetchone()
        assert (organ, outcome, verdict) == ("lang", "ok", "ar")
        assert model.startswith("lingua@")
        # NULL, not False. A deterministic organ has nothing to vote on, and
        # `agreed=False` would report perfect disagreement on every row it
        # touches — a number the promotion gate in §5 would then read.
        assert votes is None and agreed is None and json_valid is None


def test_a_run_row_cannot_claim_a_status_that_does_not_exist(tx):
    with tx.cursor() as cur:
        sid = _source(cur)
        claim = _claim(cur, sid, "نشاط على مدينة طوباس")
        with pytest.raises(psycopg.errors.CheckViolation):
            store.record_run(cur, claim_id=claim["claim_id"], organ="lang",
                             organ_version="a/1", outcome="fine")


def test_the_watermark_does_not_walk_backwards(tx):
    """A rewind re-reads claims an organ has already answered and, for a model
    organ, re-pays for them. Rewinding is a human act, not a race."""
    with tx.cursor() as cur:
        cur.execute("SELECT now() AS t")
        t = cur.fetchone()[0]
        store.write_watermark(cur, "_t_organ", t, 500)
        store.write_watermark(cur, "_t_organ", t, 400)
        assert store.read_watermark(cur, "_t_organ") == (t, 500)
        store.write_watermark(cur, "_t_organ", t, 600)
        assert store.read_watermark(cur, "_t_organ") == (t, 600)


def test_a_rate_over_no_runs_is_unknown_and_not_perfect(tx):
    """analyst_health's whole argument in one row: a component with nothing to
    report must not report a 100% success rate."""
    with tx.cursor() as cur:
        sid = _source(cur)
        claim = _claim(cur, sid, "محاصرة منزل في شريقه")
        store.record_run(cur, claim_id=claim["claim_id"], organ="_t_organ",
                         organ_version="x/1", outcome="ok")
        cur.execute("""SELECT success_rate_1h, json_valid_rate_1h,
                              vote_agreement_1h FROM analyst_health
                        WHERE organ='_t_organ'""")
        success, json_valid, agreement = cur.fetchone()
        assert float(success) == 1.0
        assert json_valid is None and agreement is None


# ── the loop: backpressure and the cursor ────────────────────────────────────

class _FakeCur:
    def __init__(self): self.executed = []
    def execute(self, sql, params=None): self.executed.append((sql, params))
    def fetchone(self): return None
    def fetchall(self): return []
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _FakeConn:
    def __init__(self): self.commits = 0
    def cursor(self): return _FakeCur()
    def commit(self): self.commits += 1
    def rollback(self): pass
    def transaction(self):
        conn = self
        class _T:
            def __enter__(self): return conn
            def __exit__(self, *a): return False
        return _T()
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Organ:
    """A model organ that records every claim it was allowed to see."""
    needs_model = True
    name = "_t_model"
    version = "t/1"

    def __init__(self): self.seen = []

    def read(self, cur, claim):
        self.seen.append(claim["claim_id"])
        return Reading(verdict="x", model="a-model", json_valid=True,
                       agreed=True, votes=["x", "x", "x"])


def _stub_store(monkeypatch, batch, moved):
    monkeypatch.setattr(store, "connect", lambda: _FakeConn())
    monkeypatch.setattr(store, "read_watermark", lambda cur, organ: None)
    monkeypatch.setattr(store, "fetch_batch", lambda cur, after, limit=200: batch)
    monkeypatch.setattr(store, "record_run", lambda cur, **kw: None)
    monkeypatch.setattr(store, "backlog", lambda cur: {})
    monkeypatch.setattr(store, "health", lambda cur: {})
    monkeypatch.setattr(store, "write_watermark",
                        lambda cur, organ, ing, cid, note=None: moved.append((organ, cid)))


def test_a_gaming_pc_pauses_the_organ_and_moves_no_watermark(monkeypatch):
    """§1: if the port refuses — PC off or gaming — it sleeps and resumes.
    The watermark must not move, or the claims skipped during a game would be
    lost silently, which is the one outcome a deferrable class cannot have."""
    organ, moved = _Organ(), []
    _stub_store(monkeypatch, [{"claim_id": 1, "ingested_at": "t"}], moved)
    report = loop.tick([organ], probe=lambda: (False, "connection refused"))
    assert organ.seen == []
    assert moved == []
    assert report["organs"]["_t_model"]["paused"] == "connection refused"
    assert report["skipped"] == 1
    # And it is SAID, not merely done: a pause nobody can see is an outage.
    assert "refused" in loop._detail(report)["pc"]


def test_the_same_organ_runs_when_the_pc_is_free(monkeypatch):
    organ, moved = _Organ(), []
    _stub_store(monkeypatch, [{"claim_id": 7, "ingested_at": "t"},
                              {"claim_id": 8, "ingested_at": "t"}], moved)
    report = loop.tick([organ], probe=lambda: (True, "llama-swap is up"))
    assert organ.seen == [7, 8]
    assert moved == [("_t_model", 8)]
    assert report["processed"] == 2


def test_a_deterministic_organ_does_not_depend_on_a_machine_across_the_tailnet(monkeypatch):
    """Organ A needs no PC. A tick that probed anyway would make the language
    of a claim depend on whether Zaid is playing a game."""
    calls = []
    moved = []
    _stub_store(monkeypatch, [], moved)

    def probe():
        calls.append(1)
        return True, "should never be asked"

    loop.tick([LanguageOrgan()], probe=probe)
    assert calls == []


def test_the_cursor_advances_over_claims_the_organ_declined(monkeypatch):
    """The subtlest way this loop could break: filter in the fetch, and a batch
    where nothing qualifies returns nothing, the cursor has nowhere to go, and
    the organ re-scans the same stretch forever — busy, beating healthily, and
    permanently one row short of the next interesting claim."""
    class _Declines:
        needs_model = False
        name = "_t_decline"
        version = "t/1"
        def read(self, cur, claim): return None

    moved = []
    _stub_store(monkeypatch, [{"claim_id": 11, "ingested_at": "t"},
                              {"claim_id": 12, "ingested_at": "t"}], moved)
    report = loop.tick([_Declines()], probe=lambda: (True, ""))
    assert moved == [("_t_decline", 12)]
    assert report["processed"] == 0
    assert report["organs"]["_t_decline"]["scanned"] == 2


def test_one_bad_claim_costs_one_claim(monkeypatch):
    class _Explodes:
        needs_model = False
        name = "_t_boom"
        version = "t/1"
        def __init__(self): self.n = 0
        def read(self, cur, claim):
            self.n += 1
            if claim["claim_id"] == 2:
                raise ValueError("bad row")
            return Reading(verdict="ok")

    organ, moved, recorded = _Explodes(), [], []
    _stub_store(monkeypatch, [{"claim_id": i, "ingested_at": "t"} for i in (1, 2, 3)],
                moved)
    monkeypatch.setattr(store, "record_run",
                        lambda cur, **kw: recorded.append(kw["outcome"]))
    report = loop.tick([organ], probe=lambda: (True, ""))
    assert organ.n == 3                       # the batch was not abandoned
    assert report["errors"] == 1
    assert recorded == ["ok", "error", "ok"]  # the failure is a ROW
    assert moved == [("_t_boom", 3)]


# ── the probe itself ─────────────────────────────────────────────────────────

def test_a_refused_port_is_a_reason_and_never_an_exception():
    ok, why = backpressure.available("http://127.0.0.1:1", timeout=1.0)
    assert ok is False
    assert "did not answer" in why


def test_an_empty_running_list_is_still_a_usable_pc(monkeypatch):
    """llama-swap up with nothing resident is healthy: the first real call swaps
    a model in. Reading that as 'unavailable' would idle the analyst forever on
    a perfectly free machine."""
    import httpx

    class _R:
        status_code = 200
        def json(self): return {"running": []}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _R())
    ok, why = backpressure.available("http://x")
    assert ok is True and "no model resident" in why


def test_something_else_listening_on_the_port_is_not_the_pc(monkeypatch):
    """The lesson VALHALLA_URL taught this repo: a reachability check that does
    not identify what answered passes happily on a port collision."""
    import httpx

    class _R:
        status_code = 200
        def json(self): raise ValueError("not json")

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _R())
    ok, why = backpressure.available("http://x")
    assert ok is False and "something else is listening" in why


# ── what the heartbeat carries ───────────────────────────────────────────────

def test_the_heartbeat_detail_is_numbers_and_not_a_word():
    report = {"processed": 5, "errors": 0, "per_minute": 12.0, "skipped": 0,
              "pc": {"available": True, "detail": "llama-swap is up"},
              "backlog": {"lang": {"pending_claims": 17, "lag_minutes": 2.0}},
              "health": {"lang": {"success_rate_1h": 1.0,
                                  "json_valid_rate_1h": None,
                                  "vote_agreement_1h": None}}}
    d = loop._detail(report)
    assert d["processed"] == 5 and d["backlog"] == {"lang": 17}
    assert d["per_minute"] == 12.0
    assert d["pc"] == "llama-swap is up"
    # The rates the model organs will fill. None until a denominator exists —
    # never 1.0, which would read as a perfect score for work nobody has done.
    assert d["json_valid_rate_1h"] is None
    assert d["vote_agreement_1h"] is None


def test_the_analyst_is_on_the_board_the_pollers_are_on():
    """The DONE WHEN of P0's second half. ops/watchdog.py judges every job on
    this list, /health renders it, and a job that is not on it can go missing
    without leaving a row to find."""
    assert "analyst" in EXPECTED_JOBS
    assert EXPECTED_JOBS["analyst"] == (loop.INTERVAL, loop.GRACE)
    assert loop.HEARTBEAT == "analyst"


def test_only_deterministic_organs_are_registered():
    """A (language) and, since P2-A.1, C (the MoH bulletin as a control). B and
    D–G are designed, not built. A registry that quietly grew an unmeasured
    model organ would put a model's guesses into the record with no gold set
    behind them (§5) — so no registered organ may need the PC."""
    from analyst.organs import ORGANS
    assert [o.name for o in ORGANS] == ["lang", "moh"]
    assert all(o.needs_model is False for o in ORGANS)
    assert by_name("lang").needs_model is False
    with pytest.raises(KeyError):
        by_name("nope")


# ── the insert sites ─────────────────────────────────────────────────────────

INSERT_SITES = ["ingest/telegram_poller.py", "ingest/sources/rss_news.py",
                "crowd/engine.py"]


def test_no_writer_states_a_language_it_did_not_measure():
    """The defect itself, pinned. All three INSERTs carried a literal 'ar' —
    including the one that writes English MoH bulletins and the one that writes
    RSS — and 99,376 rows said Arabic with exactly as much evidence behind them
    as a blank column."""
    for rel in INSERT_SITES:
        body = (ROOT / rel).read_text()
        insert = body[body.index("INSERT INTO claim"):]
        insert = insert[:insert.index("RETURNING")]
        assert "'ar'" not in insert, f"{rel} states a language it did not measure"
        assert "detect_quietly" in body, f"{rel} does not measure the language"
