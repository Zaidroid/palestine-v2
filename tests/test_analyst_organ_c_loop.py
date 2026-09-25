"""Organ C in the analyst loop (P2-A.1) — a control, not a second writer.

    ./.venv/bin/python -m pytest tests/test_analyst_organ_c_loop.py -q

What must hold, and why each one is here:

  the division of labour   organ C writes provenance only. The ingest
                           (ingest/sources/moh_gaza.py) is the one writer of
                           the gaza_moh_daily series; organ C reads the same
                           bulletin with its own reader and says, per bulletin,
                           whether the series holds what the bulletin states.
                           Every test here that exercises `read` also proves it
                           issued nothing but SELECTs.
  the verdict vocabulary   agree · series-gap (the 08-09 daily break) ·
                           disagree (a different number, or a 48-hour count
                           filed as a day's) · not-in-series · refused (the
                           reader's validator will not stand behind it — the
                           7 June 1,730,128, which the series holds).
  "previous" is by date    a bulletin is judged against the latest ACCEPTED
                           reading dated before it, never against whatever was
                           read last and never against a refused one.
  its measured domain      bulletins posted before the gold set's year are
                           declined: one 2025 misread, accepted, refused all
                           203 bulletins of 2026 in the first dry run.
  the loop wiring          organ C gets a watermark, provenance rows and a
                           heartbeat summary like organ A; its cursor trails
                           ingestion by two ingest cycles; --dry-run reads from
                           the real watermark and writes nothing at all.

Everything that would write is a fake. The last two tests read production
through a READ ONLY connection and skip where there is no database.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analyst import loop, organ_c, store                           # noqa: E402
from analyst.organs import (AGREE, DISAGREE, NOT_IN_SERIES, REFUSED,  # noqa: E402
                            SERIES_FIELDS, SERIES_GAP, MoHBulletinOrgan, Reading,
                            by_name, compare, verdict_of)

GOLD = ROOT / "tests" / "gold" / "moh_c.jsonl"
MOH_SOURCE, OTHER_SOURCE, DATASET = 1975, 7, 41

# 2026-09-22 — the newest gold bulletin (claim 124147), as archived.
BULLETIN = """
🇵🇸 وزارة الصحة الفلسطينية – غزة 🇵🇸
🔴 التقرير الإحصائي اليومي لعدد الشهداء والجرحى جرّاء العدوان الإسرائيلي على قطاع غزة
⭕ بلغ إجمالي ما وصل إلى مستشفيات قطاع غزة خلال الـ 24 ساعة الماضية:
- 5 شهداء (4 شهداء جدد، 1 شهيد متأثر بإصابته).
- 25 إصابة
🔴*منذ وقف إطلاق النار (11 أكتوبر 2025 حتى اليوم):*
- إجمالي الشهداء: 1,399 شهيد
- إجمالي الإصابات: 4,863 إصابة
- إجمالي حالات الانتشال: 834 شهيد
🔴*الحصيلة التراكمية منذ بداية العدوان:*
- إجمالي الشهداء: 73,919 شهيد
- إجمالي الإصابات: 174,977 إصابة
وزارة الصحة
22 سبتمبر 2026
"""
POSTED = datetime(2026, 9, 22, 8, 39, 17, tzinfo=timezone.utc)

# The day before, verbatim (claim 114878).
EARLIER = """
🇵🇸 وزارة الصحة الفلسطينية – غزة 🇵🇸
🔴 التقرير الإحصائي اليومي لعدد الشهداء والجرحى جرّاء العدوان الإسرائيلي على قطاع غزة

⭕ بلغ إجمالي ما وصل إلى مستشفيات قطاع غزة خلال الـ 24 ساعة الماضية:
- 4 شهداء (1شهيد متأثر بإصابته، 3 شهيد انتشال) .
- 17 إصابة

🔴*منذ وقف إطلاق النار (11 أكتوبر 2025 حتى اليوم):*
- إجمالي الشهداء: 1,394 شهيد
- إجمالي الإصابات: 4,839 إصابة
- إجمالي حالات الانتشال: 834 حالة

🔴*الحصيلة التراكمية منذ بداية العدوان:*
- إجمالي الشهداء: 73,914 شهيد
- إجمالي الإصابات: 174,952 إصابة

وزارة الصحة
 21 سبتمبر 2026
"""
EARLIER_POSTED = datetime(2026, 9, 21, 8, 59, 16, tzinfo=timezone.utc)

# A 48-hour bulletin, verbatim but for the rubble sentence (2026-04-25, claim
# 11757): its 32 injuries are two days' count, and the series holds them as
# that DAY's — the cascade read `خلال الساعات ال 24 الماضية` inside the deaths
# line as a daily header.
WINDOW_48 = """
🇵🇸 وزارة الصحة الفلسطينية – غزة 🇵🇸

🔴 التقرير الإحصائي اليومي لعدد الشهداء والجرحى جرّاء العدوان الإسرائيلي على قطاع غزة

⭕ بلغ إجمالي من وصلوا إلى مستشفيات قطاع غزة خلال الـ 48 ساعة الماضية.
• عدد الشهداء: 17 شهيد( منهم 13 شهيد خلال الساعات ال 24 الماضية)
• عدد الإصابات: 32 إصابة

🔴 منذ وقف إطلاق النار (11 أكتوبر):
• إجمالي عدد الشهداء: 809
• إجمالي عدد الإصابات: 2,267
• إجمالي حالات الانتشال: 761

🔴 الإحصائية التراكمية منذ بداية العدوان في 7 أكتوبر 2023:
• العدد التراكمي للشهداء: 72,585
• العدد التراكمي للإصابات: 172,370

وزارة الصحة
25 ابريل 2026
"""
WINDOW_48_POSTED = datetime(2026, 4, 25, 7, 32, 47, tzinfo=timezone.utc)

WRITES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "ALTER", "CREATE", "DROP")


def _read(text=BULLETIN, posted=POSTED):
    return organ_c.read(text, posted)


def _held(reading, *, daily=True, **override) -> list[tuple]:
    """Observation rows as the ingest would have written them from `reading`."""
    rows = []
    for field_name, indicator in SERIES_FIELDS.items():
        if field_name in ("last_24h_killed", "last_24h_injured") and not daily:
            continue
        value = override.get(field_name, reading.get(field_name))
        if value is not None:
            rows.append((indicator, value, "124147"))
    return rows


class _Cur:
    """Answers the organ's four queries from fixtures; remembers every one."""

    def __init__(self, *, series=None, prior=None, summary_rows=None):
        self.series = series or {}          # day (date) -> [(indicator, value, claim_id)]
        self.prior = prior                  # (as_of, cum_killed, cum_injured) or None
        self.summary_rows = summary_rows or []
        self.sql: list[str] = []
        self._one = None
        self._all: list = []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self._one, self._all = None, []
        if "FROM source" in sql:
            self._one = (MOH_SOURCE,)
        elif "FROM dataset" in sql:
            self._one = (DATASET,)
        elif "FROM analyst_run" in sql and "accepted" in sql:
            as_of = params[1]
            if self.prior and self.prior[0] < as_of:
                self._one = self.prior
        elif "FROM observation" in sql:
            day = params[1].date() if hasattr(params[1], "date") else params[1]
            self._all = list(self.series.get(day, []))
        elif "DISTINCT ON (claim_id)" in sql:
            self._all = list(self.summary_rows)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all

    def wrote(self) -> list[str]:
        return [s for s in self.sql if s.lstrip().split(None, 1)[0].upper() in WRITES]


def _claim(text=BULLETIN, posted=POSTED, source=MOH_SOURCE, cid=124147):
    return {"claim_id": cid, "ingested_at": posted, "reported_at": posted,
            "source_id": source, "raw_text": text, "lang": "ar", "attrs": {},
            "claim_type": "unclassified"}


# ── registration ─────────────────────────────────────────────────────────────

def test_organ_c_is_registered_deterministic_pure_and_patient():
    organ = by_name("moh")
    assert isinstance(organ, MoHBulletinOrgan)
    assert organ.needs_model is False          # never gated on the gaming PC
    assert organ.pure is True                  # the Reading is its only record
    assert organ.version.startswith(organ_c.VERSION)
    assert organ.batch >= store.BATCH
    # Two cycles of the hourly MoH ingest (ops/ingest-gaza.sh: 3600 s).
    assert organ.settle_seconds >= 2 * 3600


def test_the_fields_it_compares_are_the_ingests_own_indicators():
    """Built from cascade.moh_gaza.INDICATORS, so a rename there cannot leave
    organ C comparing a number with a different series of the same name."""
    from cascade.moh_gaza import INDICATORS
    assert set(SERIES_FIELDS.values()) == set(INDICATORS.values())


# ── what it declines ────────────────────────────────────────────────────────

def test_it_declines_other_sources_other_texts_and_years_it_was_not_measured_on():
    organ, cur = MoHBulletinOrgan(), _Cur()
    assert organ.read(cur, _claim(source=OTHER_SOURCE)) is None
    assert organ.read(cur, _claim(text="وزارة الصحة: بيان حول مستشفى الشفاء")) is None
    # A 2025 bulletin: the gold set is 2026 and the reader is not a control
    # outside what it was measured on.
    old = datetime(2025, 7, 25, 9, 0, tzinfo=timezone.utc)
    assert organ.read(cur, _claim(posted=old)) is None
    assert cur.wrote() == []


# ── the verdicts ─────────────────────────────────────────────────────────────

def test_a_bulletin_the_series_holds_exactly_is_agree():
    reading = _read()
    organ = MoHBulletinOrgan()
    cur = _Cur(series={POSTED.date(): _held(reading)})
    r = organ.read(cur, _claim())
    assert isinstance(r, Reading) and r.verdict == AGREE
    assert r.model == f"organ_c@{organ_c.VERSION}"
    # Deterministic: nothing voted, no JSON asked for. `agreed` is the §2.5
    # vote and must not be borrowed for agreement with the series.
    assert r.votes is None and r.agreed is None and r.json_valid is None
    assert r.raw["accepted"] is True and r.raw["as_of_date"] == "2026-09-22"
    assert {f["state"] for f in r.raw["fields"].values()} == {"agree"}
    assert r.raw["series_claims"] == [124147]
    assert cur.wrote() == []


def test_the_daily_break_is_a_series_gap_with_the_numbers_the_series_lacks():
    """The 08-09 break exactly: cumulative rows present, window rows absent."""
    reading = _read()
    organ = MoHBulletinOrgan()
    cur = _Cur(series={POSTED.date(): _held(reading, daily=False)})
    r = organ.read(cur, _claim())
    assert r.verdict == SERIES_GAP
    assert r.raw["fields"]["last_24h_killed"] == {"state": "missing", "read": 5, "held": None}
    assert r.raw["fields"]["last_24h_injured"] == {"state": "missing", "read": 25, "held": None}
    assert r.raw["fields"]["cum_killed"]["state"] == "agree"
    assert cur.wrote() == []


def test_a_different_number_in_the_series_is_a_disagreement():
    reading = _read()
    organ = MoHBulletinOrgan()
    cur = _Cur(series={POSTED.date(): _held(reading, cum_killed=73918)})
    r = organ.read(cur, _claim())
    assert r.verdict == DISAGREE
    assert r.raw["fields"]["cum_killed"] == {"state": "differ", "read": 73919, "held": 73918.0}


def test_a_48_hour_count_filed_as_a_day_is_a_disagreement():
    """2026-04-25 in production: the series holds 32 as the day's injuries,
    and 32 is two days' count."""
    reading = _read(WINDOW_48, WINDOW_48_POSTED)
    assert reading["window_hours"] == 48
    held = _held(reading, daily=False) + [("gaza.moh.injuries.daily", 32, "11757")]
    organ = MoHBulletinOrgan()
    cur = _Cur(series={WINDOW_48_POSTED.date(): held})
    r = organ.read(cur, _claim(WINDOW_48, WINDOW_48_POSTED, cid=11757))
    assert r.verdict == DISAGREE
    assert r.raw["fields"]["last_24h_injured"] == {"state": "extra", "read": None, "held": 32.0}
    # and a 48-hour window is never counted as a day the series LACKS
    assert "last_24h_killed" not in r.raw["fields"]


def test_a_day_the_series_does_not_hold_at_all_is_not_in_series():
    organ = MoHBulletinOrgan()
    r = organ.read(_Cur(series={}), _claim())
    assert r.verdict == NOT_IN_SERIES and r.raw["series_claims"] == []


def test_a_bulletin_the_validator_refuses_is_refused_even_where_the_series_agrees():
    """7 June: the bulletin printed 1,730,128 injured, the ingest stored it,
    and the two agree. Agreement with a typo is not agreement with the truth,
    so the refusal wins the verdict — and the refused reading is never used
    as anyone's previous."""
    typo = BULLETIN.replace("174,977", "1,749,770")
    reading = _read(typo)
    organ = MoHBulletinOrgan()
    cur = _Cur(series={POSTED.date(): _held(reading)},
               prior=("2026-09-21", 73914, 174952))
    r = organ.read(cur, _claim(typo))
    assert r.verdict == REFUSED
    assert r.raw["accepted"] is False and r.raw["reasons"] == ["implausible-jump"]
    assert {f["state"] for f in r.raw["fields"].values()} == {"agree"}
    assert organ._accepted == {}


def test_verdict_precedence_is_worst_first():
    fields = {"a": {"state": "missing"}, "b": {"state": "differ"}}
    assert verdict_of(False, {"x": 1}, fields) == REFUSED
    assert verdict_of(True, {}, fields) == NOT_IN_SERIES
    assert verdict_of(True, {"x": 1}, fields) == DISAGREE
    assert verdict_of(True, {"x": 1}, {"a": {"state": "missing"}}) == SERIES_GAP
    assert verdict_of(True, {"x": 1}, {"a": {"state": "agree"}}) == AGREE


def test_compare_leaves_out_a_field_neither_side_holds():
    out = compare({"window_hours": 24, "cum_killed": 5}, {})
    assert out == {"cum_killed": {"state": "missing", "read": 5, "held": None}}


# ── "previous" ───────────────────────────────────────────────────────────────

def test_previous_is_the_latest_accepted_reading_dated_before_this_one():
    """By date, not by processing order: the 22nd read first must not become
    the 21st's previous — a later total would refuse the earlier day as a
    fall. And the organ's own stored rows count as well as this process's."""
    organ = MoHBulletinOrgan()
    cur = _Cur(series={})
    organ.read(cur, _claim())                                   # 22 Sep accepted
    assert "2026-09-22" in organ._accepted
    r = organ.read(cur, _claim(EARLIER, EARLIER_POSTED, cid=114878))
    assert r.raw["accepted"] is True, r.raw["reasons"]          # not judged against the 22nd
    # From the stored rows: a prior accepted 21 Sep row judges the 22nd.
    fresh = MoHBulletinOrgan()
    prev = fresh.previous(_Cur(prior=("2026-09-21", 73914, 174952)), "2026-09-22")
    assert prev == {"cum_killed": 73914, "cum_injured": 174952}
    assert fresh.previous(_Cur(prior=("2026-09-21", 73914, 174952)), "2026-09-21") is None


# ── the loop ─────────────────────────────────────────────────────────────────

class _FakeConn:
    def __init__(self, cur): self.cur, self.commits, self.rollbacks = cur, 0, 0
    def cursor(self): return self.cur
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1
    def transaction(self):
        class _T:
            def __enter__(s): return self
            def __exit__(s, *a): return False
        return _T()
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _CtxCur(_Cur):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_the_loop_gives_organ_c_a_watermark_provenance_and_a_summary(monkeypatch):
    reading = _read()
    cur = _CtxCur(series={POSTED.date(): _held(reading, daily=False)},
                  summary_rows=[(124147, SERIES_GAP, "2026-09-22")])
    organ = MoHBulletinOrgan()
    fetched, recorded, moved = [], [], []

    def fetch(c, after, limit=200, before=None):
        fetched.append((limit, before))
        return [_claim(), _claim(source=OTHER_SOURCE, cid=124148)]

    monkeypatch.setattr(store, "connect", lambda: _FakeConn(cur))
    monkeypatch.setattr(store, "read_watermark", lambda c, organ: None)
    monkeypatch.setattr(store, "fetch_batch", fetch)
    monkeypatch.setattr(store, "record_run", lambda c, **kw: recorded.append(kw))
    monkeypatch.setattr(store, "write_watermark",
                        lambda c, organ, ing, cid, note=None: moved.append((organ, cid)))
    monkeypatch.setattr(store, "backlog", lambda c: {"moh": {"pending_claims": 0, "lag_minutes": 120.0}})
    monkeypatch.setattr(store, "health", lambda c: {"moh": {"runs_1h": 1, "errors_1h": 0,
                                                             "success_rate_1h": 1.0}})

    report = loop.tick([organ], probe=lambda: pytest.fail("a deterministic tick asked the PC"))
    # its own bite, and a cursor that stops two ingest cycles short of now
    limit, before = fetched[0]
    assert limit == organ.batch
    lag = datetime.now(timezone.utc) - before
    assert timedelta(seconds=organ.settle_seconds - 5) < lag < timedelta(seconds=organ.settle_seconds + 60)
    # one provenance row, for the bulletin only; the watermark passes both
    assert [(r["organ"], r["outcome"], r["verdict"]) for r in recorded] == [("moh", "ok", SERIES_GAP)]
    assert recorded[0]["organ_version"] == organ.version
    assert moved == [("moh", 124148)]
    detail = loop._detail(report)
    assert detail["organs"]["moh"]["summary"]["newest"] == {
        "claim_id": 124147, "as_of_date": "2026-09-22", "verdict": SERIES_GAP}
    assert detail["organs"]["moh"]["backlog"] == 0
    assert cur.wrote() == []


def test_the_settle_bound_is_in_the_fetch_and_never_skips_a_claim():
    """A fresh claim is left for a later tick, not passed: the bound is in the
    SQL, so the cursor cannot move beyond a claim the organ has not seen."""
    cur = _Cur()
    cut = datetime(2026, 9, 25, 20, 0, tzinfo=timezone.utc)
    store.fetch_batch(cur, None, limit=10, before=cut)
    store.fetch_batch(cur, (cut, 5), limit=10, before=cut)
    store.fetch_batch(cur, (cut, 5), limit=10)
    assert all("ingested_at < %s" in s for s in cur.sql[:2])
    assert "ingested_at < %s" not in cur.sql[2]


def test_a_dry_run_reads_from_the_real_watermark_and_writes_nothing(monkeypatch):
    reading = _read()
    cur = _CtxCur(series={POSTED.date(): _held(reading)})
    conn = _FakeConn(cur)
    batches = [[_claim()], [_claim(source=OTHER_SOURCE, cid=124150)], []]

    monkeypatch.setattr(store, "connect_readonly", lambda: conn)
    monkeypatch.setattr(store, "connect", lambda: pytest.fail("dry run opened a writable connection"))
    monkeypatch.setattr(store, "read_watermark", lambda c, organ: (POSTED, 100))
    monkeypatch.setattr(store, "fetch_batch", lambda c, after, limit=200, before=None: batches.pop(0))
    monkeypatch.setattr(store, "record_run", lambda *a, **k: pytest.fail("dry run recorded"))
    monkeypatch.setattr(store, "write_watermark", lambda *a, **k: pytest.fail("dry run moved a cursor"))
    monkeypatch.setattr(loop, "beat", lambda *a, **k: pytest.fail("dry run beat"))

    from analyst.organs import LanguageOrgan
    report = loop.dry_run([LanguageOrgan(), MoHBulletinOrgan()], batches=5, show=None,
                          probe=lambda: pytest.fail("asked the PC"))
    moh = report["organs"]["moh"]
    assert moh["verdicts"] == {AGREE: 1} and moh["scanned"] == 2 and moh["idle"] == "caught up"
    assert moh["watermark"] == [str(POSTED), 100]
    assert moh["cursor_would_be"] == [str(POSTED), 124150]
    assert moh["rows"][0]["claim_id"] == 124147 and moh["rows"][0]["raw"]["accepted"] is True
    # organ A corrects claim.lang through the cursor: never run dry
    assert "skipped" in report["organs"]["lang"]
    assert conn.rollbacks == 1 and conn.commits == 0
    assert cur.wrote() == []


def test_the_summary_is_the_newest_bulletin_and_the_last_thirty_days():
    today = datetime.now(timezone.utc).date()
    rows = [(1, AGREE, (today - timedelta(days=40)).isoformat()),
            (2, SERIES_GAP, (today - timedelta(days=2)).isoformat()),
            (3, SERIES_GAP, (today - timedelta(days=1)).isoformat())]
    s = MoHBulletinOrgan().summary(_Cur(summary_rows=rows))
    assert s["newest"]["claim_id"] == 3 and s["newest"]["verdict"] == SERIES_GAP
    assert s["last_30d"] == {SERIES_GAP: 2}
    assert MoHBulletinOrgan().summary(_Cur()) == {"newest": None, "last_30d": {}}


# ── against production, read only ────────────────────────────────────────────

def _readonly_or_skip():
    try:
        return store.connect_readonly()
    except Exception as exc:                                    # noqa: BLE001
        pytest.skip(f"no database here: {exc}")


def test_live_the_newest_gold_bulletin_is_held_by_the_series_on_its_totals():
    """Read only. Claim 124147 (22 Sep) through the real SQL: the ingest's
    cumulative and ceasefire rows for that day agree with organ C."""
    ctx = _readonly_or_skip()
    try:
        conn = ctx.__enter__()
    except Exception as exc:                                    # noqa: BLE001
        pytest.skip(f"no database here: {exc}")
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {store.CLAIM_COLUMNS} FROM claim WHERE claim_id = 124147")
            row = cur.fetchone()
            if row is None:
                pytest.skip("claim 124147 not in this database")
            claim = dict(zip([c.strip() for c in store.CLAIM_COLUMNS.split(",")], row))
            r = MoHBulletinOrgan().read(cur, claim)
        assert r is not None and r.raw["as_of_date"] == "2026-09-22"
        for f in ("cum_killed", "cum_injured", "since_ceasefire_killed", "since_ceasefire_injured"):
            assert r.raw["fields"][f]["state"] == "agree", (f, r.raw["fields"][f])
    finally:
        conn.rollback()
        ctx.__exit__(None, None, None)


def test_live_the_loop_judges_every_gold_bulletin_as_the_gold_set_filed_it():
    """Read only. The 201 gold bulletins, in posting order, through the organ
    exactly as the loop runs it: every unique day accepted or refused as the
    gold set says (198 served, 7 June refused). Reposts are judged against the
    day before, so they are accepted here; the gold set files them apart."""
    ctx = _readonly_or_skip()
    try:
        conn = ctx.__enter__()
    except Exception as exc:                                    # noqa: BLE001
        pytest.skip(f"no database here: {exc}")
    gold = [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines()]
    ids = [g["claim_id"] for g in gold]
    try:
        with conn.cursor() as cur:
            cur.execute(f"""SELECT {store.CLAIM_COLUMNS} FROM claim
                             WHERE claim_id = ANY(%s) ORDER BY reported_at, claim_id""", (ids,))
            cols = [c.strip() for c in store.CLAIM_COLUMNS.split(",")]
            claims = [dict(zip(cols, r)) for r in cur.fetchall()]
            if len(claims) != len(ids):
                pytest.skip(f"{len(claims)} of {len(ids)} gold claims in this database")
            organ = _ThisRunOnly()
            judged = {c["claim_id"]: organ.read(cur, c) for c in claims}
    finally:
        conn.rollback()
        ctx.__exit__(None, None, None)
    for g in gold:
        r = judged[g["claim_id"]]
        assert r is not None, g["claim_id"]
        assert r.raw["reading"] == g["reader"], f"{g['claim_id']} reader drifted from the gold"
        if not g.get("repost_of"):
            assert r.raw["accepted"] == g["verdict"]["ok"], g["claim_id"]


class _ThisRunOnly(MoHBulletinOrgan):
    """The live test must not depend on what production's analyst_run holds
    (the service may already have judged these days): "previous" comes from
    this run's own readings only, as it does in a dry run on a fresh organ."""
    def _previous_stored(self, cur, as_of):
        return None
