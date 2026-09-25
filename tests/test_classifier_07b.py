"""Audit 2026-09-25, area 07 — the classifier tasks left open after the cloud's
pass (CLASSIFIER-03 04 05 06 07 08 09 10 11 12 13 14 17). Pure read() probes,
plus the writer's helpers offline."""
from __future__ import annotations

import inspect
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cascade.news import read, siege_closes_a_road, when_stated          # noqa: E402
from ingest.sources import news_incidents as NI                          # noqa: E402
from resolve.arabic import normalize                                     # noqa: E402


def _r(t):
    return read(t)


# ── CLASSIFIER-07 (F096): the clause guard and anchors ───────────────────────
@pytest.mark.parametrize("text", [
    "سكرتير الحركة الاسيرة زار الطريق الى نابلس والتقى الاهالي",
    "في اجتماع مغلق تطرق الوزير الى شارع القدس في رام الله",
    "قطع الطريق على محاولات المستوطنين قرب حاجز حوارة جنوب نابلس",
])
def test_classifier_07_idioms_and_fragments_are_not_closures(text):
    r = _r(text)
    assert r.incident_type != "closure", (r.verdict, r.incident_type, r.matched)


@pytest.mark.parametrize("text", [
    "اغلاق حاجز حوارة جنوب نابلس",
    "قوات الاحتلال تغلق مدخل بلدة بيتا جنوب نابلس",
    "الشارع الرئيسي في بلدة سنجل مغلق بالسواتر الترابية",
])
def test_classifier_07_closures_still_read(text):
    r = _r(text)
    assert r.verdict == "incident" and r.incident_type == "closure" and r.is_closure, r


# ── CLASSIFIER-08/09 (F097/F190): settler acts, settlers not settlements ─────
@pytest.mark.parametrize("text", [
    "مستوطنون يقتلعون اشجار زيتون في بورين جنوب نابلس",
    "قام مستوطنون باقتلاع عشرات اشجار الزيتون في قريوت جنوب نابلس",
    "مستوطنون يقومون بتخريب خطوط المياه في قرية المغير شرق رام الله",
    "احراق مركبتين من قبل مستوطنين في بلدة ترمسعيا شمال رام الله",
])
def test_classifier_08_settler_verbal_nouns_are_settler_attacks(text):
    r = _r(text)
    assert r.incident_type == "settler_attack", (r.verdict, r.incident_type, r.reject_reason)


@pytest.mark.parametrize("text", [
    "قوات الاحتلال تقتحم قرية بورين قرب مستوطنة يتسهار وتعتدي على شاب بالضرب",
    "الاحتلال يعتقل شابا من بلدة بيتا قرب مستوطنة ايفتار جنوب نابلس",
])
def test_classifier_09_army_action_near_a_settlement_is_not_a_settler_attack(text):
    r = _r(text)
    assert r.incident_type != "settler_attack", (r.incident_type, r.matched)


# ── CLASSIFIER-10 (F192): the bare verbal noun اعتقال ────────────────────────
def test_classifier_10_bare_arrest_noun_reads():
    r = _r("اعتقال شاب من بلدة كوبر شمال رام الله")
    assert r.verdict == "incident" and r.incident_type == "arrest"


# ── CLASSIFIER-11/12 (F099/F100): anchored rejects ───────────────────────────
@pytest.mark.parametrize("text,itype", [
    ("اصيب شاب بعيار ناري في قدمه اليمنى قرب حاجز حوارة جنوب نابلس", "injury"),
    ("الاحتلال يهدم منازل في غور الاردن قرب اريحا", "demolition"),
    ("اعتقال طالب بجامعة بيرزيت من بلدة كوبر غرب رام الله", "arrest"),
    ("اصابة طالبة برصاص الاحتلال قرب مدخل بلدة سلواد شرق رام الله", "injury"),
    ("اصابة شاب بالرصاص على شارع غزة في رام الله", "injury"),
    ("اعتقال شاب بحجة عدم حيازة تصريح على حاجز قلنديا شمال القدس", "arrest"),
])
def test_classifier_11_12_short_reject_terms_are_whole_words(text, itype):
    r = _r(text)
    assert r.verdict == "incident" and r.incident_type == itype, (r.verdict, r.reject_reason, r.matched)


@pytest.mark.parametrize("text", [
    "حزب الله يعلن استهداف موقع في شمال فلسطين المحتلة بعد اصابة جنود",
    "نادي الاسير يطالب بالافراج عن المعتقلين المضربين عن الطعام في سجن عوفر",
])
def test_classifier_11_12_real_rejects_still_reject(text):
    assert _r(text).verdict == "rejected"


# ── CLASSIFIER-13 (F196): مدخل <city> ────────────────────────────────────────
def test_classifier_13_city_entrance_is_placed():
    r = _r("الاحتلال يغلق مدخل نابلس الشرقي")
    assert r.verdict == "incident" and r.incident_type == "closure"
    assert r.governorate == normalize("نابلس") and r.place_text


# ── CLASSIFIER-06 (F041): a house siege is not a road closure ────────────────
def test_classifier_06_a_house_siege_is_an_event_not_a_road_closure():
    house = _r("مستوطنون يحاصرون منزل عائلة في قصرة جنوب نابلس")
    town = _r("قوات الاحتلال تحاصر بلدة عزون شرق قلقيلية")
    assert house.incident_type == "siege" and not house.is_closure
    assert town.incident_type == "siege" and town.is_closure
    assert not siege_closes_a_road(normalize("حصار منزل الشهيد في جنين"))


# ── CLASSIFIER-05 (F040): the time the text states ──────────────────────────
def test_classifier_05_a_yesterday_evening_closure_is_dated_yesterday_evening():
    r = _r("أغلق الاحتلال حاجز بيت فوريك مساء أمس")
    assert r.when == {"offset_days": -1, "hour": 19, "precision": "hour"}
    posted = datetime(2026, 9, 25, 6, 0, tzinfo=timezone.utc)            # 09:00 local
    at, prec = NI.occurred_from(posted, r.when)
    assert prec == "hour" and at.date() == datetime(2026, 9, 24).date()
    assert at.astimezone(NI.HEBRON).hour == 19
    assert when_stated(normalize("اقتحمت قوات الاحتلال فجر اليوم بلدة يعبد")) == \
        {"offset_days": 0, "hour": 4, "precision": "hour"}
    assert when_stated(normalize("اعتقال شاب من نابلس")) is None
    # a band later than the posting has not happened: the posting time stands
    at2, _ = NI.occurred_from(posted, {"offset_days": 0, "hour": 19, "precision": "hour"})
    assert at2 == posted
    assert NI.occurred_from(posted, None) == (posted, "hour")


# ── CLASSIFIER-04 (F033): mirrors are one voice ─────────────────────────────
def test_classifier_04_a_verbatim_mirror_is_not_a_second_source():
    t0 = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    text = normalize("قوات الاحتلال تقتحم بلدة يعبد جنوب غرب جنين وتعتقل شابين")
    m = lambda cid, unit, txt, mins: (cid, t0.replace(minute=mins), unit, cid, None, "named", [], txt)
    units, collapsed = NI.independent_units([
        m(1, "src:1", text, 0), m(2, "src:2", text, 3),
        m(3, "src:3", normalize("اقتحام يعبد واعتقال شابين بعد محاصرة منزل"), 8)])
    assert units == {"src:1", "src:3"} and collapsed == 1


# ── CLASSIFIER-03 (F072): only assertions become belief ─────────────────────
def test_classifier_03_closure_refresh_reads_assertions_only():
    assert "modality = 'assertion'" in NI.REFRESH_CLOSURE_SQL


# ── CLASSIFIER-14/17 (F203/F477): the window and the key on join ────────────
def test_classifier_14_17_join_keeps_the_key_and_compares_with_the_last_report():
    src = inspect.getsource(NI.classify)
    join = src[src.index("UPDATE event"):src.index("stats[\"events_joined\"]")]
    assert '"stable_key"' not in join, "the join must not rewrite the stable key"
    assert "last_report_at" in join
    assert "last_report_at" in src[src.index("WHERE event_type = %s AND place_id = %s"):
                                   src.index("ORDER BY occurred_at")]
