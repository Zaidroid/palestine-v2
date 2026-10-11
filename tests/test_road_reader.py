"""v2's own road reader: the names (resolve/road_names.py), the message
(cascade/road_message.py) and the two doors (ingest/sources/roads.py).

    .venv/bin/python -m pytest tests/test_road_reader.py -q

Pure: no database. Every message below is one a channel sent; the register is a
handful of rows shaped like the real ones. What each test names is a way v1's
whitelist parser lost or misfiled a reading (audit 2026-10-11, findings 01, 02).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cascade.road_message import read_message, subjects_of  # noqa: E402
from ingest.sources import roads  # noqa: E402
from resolve.road_names import assemble, key_of  # noqa: E402

# (place_id, merged_into, servable, name_ar, name_en, v1 key, board names)
PLACES = [
    (1, None, True, "عطارة", "Atara", "عطاره", []),
    (2, None, True, "عين سينيا", "Ein Sinya", "عين_سينيا", []),
    (3, None, True, "دير شرف", "Deir Sharaf", "دير_شرف", []),
    (4, None, True, "عناب", "Enav", "عناب", []),
    (5, None, True, "الرام", "Ar-Ram", "الرام", []),
    (6, None, True, "سنجل", "Sinjil", "سنجل", []),
    (7, None, True, "النبي يونس", "Nabi Yunus", "النبي_يونس", []),
    (8, None, True, "سعير", "Sa'ir", "سعير", []),
    (9, None, True, "الفوار", "Al-Fawwar", "الفوار", []),
    (10, None, True, "جسر الملك حسين", "King Hussein Bridge", "جسر الملك حسين", []),
    (11, None, True, "مفرق الـ17 – عصيرة", "The 17 junction", None, ["الـ 17 - عصيرة"]),
    (12, None, True, "جيت", "Jit", "دوار_جيت", []),
    (13, None, True, "سلواد يبرود", "Silwad-Yabroud", "سلواد_يبرود", []),
    (14, 3, False, "دير شرف هسا اجو الجيش", None, "دير_شرف_هسا_اجو_الجيش", []),   # merged scrap
    (15, None, False, "بعد الدوار", None, "بعد_الدوار", []),                       # hidden scrap
    (16, None, True, "حزما", "Hizma", "حزما", []),
    (17, None, True, "جبع", "Jaba'", "جبع", []),
]
ALIASES = [("ديرشرف بدون", 3), ("صره بحري", 3)]        # lines v1 stored as aliases
ROAD_ALIASES = [("عين سينا", 2, "spelling"), ("ديرشرف", 3, "spelling"), ("17", 11, "weak"),
                ("يبرود", 13, "name"), ("معبر الكرامة", 10, "name")]
TOWNS = ["رام الله", "عين يبرود", "بيت لحم"]


@pytest.fixture(scope="module")
def lex():
    return assemble(PLACES, ALIASES, ROAD_ALIASES, {2: 900, 3: 700}, TOWNS)


def got(text, lex, **kw) -> dict:
    """{place_id: "dir:value …"} for the assertions in a message."""
    out = {}
    for r in read_message(text, lex, **kw):
        if r.modality == "assertion":
            out[r.place_id] = " ".join(sorted(
                f"{f.direction[:3]}:{'-' if f.axis == 'absence' else ''}{f.value}" for f in r.facts))
    return out


# ── the names ────────────────────────────────────────────────────────────────

def test_a_name_is_found_wherever_it_stands(lex):
    assert got("ازمه خانقه عالمربعه وعين سينيا", lex) == {2: "bot:congested"}
    assert got("سكرو دير شرف", lex) == {3: "bot:closed"}


def test_a_spelling_is_a_name_once_it_is_written_into_the_register(lex):
    """113 spellings one letter from a registered name carried 6,699 mentions
    that v1 filed under nothing."""
    assert got("عين سينا مسكر", lex) == {2: "bot:closed"}
    assert got("ديرشرف سالك", lex) == {3: "bot:open"}
    assert got("عين سنيا مسكر", lex) == {}          # not written in: not guessed


def test_the_article_a_fused_letter_and_a_stretched_one_fold_away(lex):
    assert key_of("المربّعه") == key_of("مربعه") == key_of("عالمربععععه")
    assert got("وعطاره سالكه", lex) == {1: "bot:open"}
    assert got("عطااااره سالكه", lex) == {1: "bot:open"}


def test_a_town_that_contains_a_road_name_is_read_past(lex):
    """"رام" was Ar-Ram 3,402 times in 90,000 messages."""
    assert got("رام الله سالك", lex) == {}
    assert got("الرام مسكر", lex) == {5: "bot:closed"}
    assert got("عين يبرود سالك", lex) == {}          # not the Yabrud gate
    assert got("يبرود سالك", lex) == {13: "bot:open"}


def test_a_line_stored_as_a_name_is_not_a_name(lex):
    """"ديرشرف بدون", kept as an alias, read "ديرشرف بدون جيش" as the army PRESENT."""
    assert got("ديرشرف بدون جيش", lex) == {3: "bot:-idf"}
    assert got("دير شرف هسا اجو الجيش", lex) == {3: "bot:idf"}


def test_a_weak_name_needs_a_road_word(lex):
    assert got("حاجز 17 مسكر", lex) == {11: "bot:closed"}
    assert got("١٧ مريت عنه ما في حاجز ولا جيش", lex)[11].startswith("bot:-idf")
    assert got("17 دقيقة على عناب ازمه", lex) == {4: "bot:congested"}
    assert got("جيت من طريق عناب سالك", lex) == {}   # "I came by the Enav road"
    assert got("دوار جيت سالك", lex) == {12: "bot:open"}


def test_a_hidden_row_gives_no_name(lex):
    assert got("بعد الدوار ازمه", lex) == {}


# ── the message ──────────────────────────────────────────────────────────────

def test_a_list_shares_one_status(lex):
    assert got("عطاره وعين سينيا سالكات", lex) == {1: "bot:open", 2: "bot:open"}
    assert got("النبي يونس وسعير مغلقات", lex) == {7: "bot:closed", 8: "bot:closed"}


def test_each_name_keeps_its_own_status(lex):
    assert got("عناب سالك دير شرف مسكر", lex) == {4: "bot:open", 3: "bot:closed"}
    assert got("سالك عطاره مسكر عين سينيا", lex) == {1: "bot:open", 2: "bot:closed"}


def test_a_name_that_only_says_which_way_is_not_the_subject(lex):
    assert got("عين سينيا حاجز للخارج من عطاره الان", lex) == {2: "out:idf"}
    assert got("شرطه للي رايح على عين سينيا بعد الاشاره", lex) == {}
    assert got("حادث بين حزما وجبع والشارع مسكر", lex) == {}
    assert got("جنب بوابة الفوار عليها ديماكس 🛑🛑", lex) == {}
    assert got("حاجز بعد دير شرف", lex) == {3: "bot:idf"}      # near it, and a checkpoint


def test_a_part_of_a_place_is_not_the_place(lex):
    """"بوابة سنجل المحول" is not Sinjil's main gate; the register holds one row."""
    assert got("بوابة سنجل المحول مغلقة ❌\nبوابة سنجل رئيسية سالكة ✔️", lex) == {6: "bot:open"}


def test_a_status_on_the_line_below(lex):
    assert got("عناب سالك لداخل✅\nمغلق للخارج❌", lex) == {4: "inb:open out:closed"}
    assert got("بوابات النبي يونس وسعير\nاليوم الاثنين مغلقه طول اليوم", lex) == {
        7: "bot:closed", 8: "bot:closed"}
    # …but not when the line below is about something else
    assert got("عطاره سالك\nالطنيب مسكر", lex) == {1: "bot:open"}
    # …and never under a title
    assert got("أحوال الطرق عطاره والجوار\n⛔ مغلقة جزئياً", lex) == {}


def test_a_question_is_not_a_reading(lex):
    rs = read_message("عطاره وعين سينيا كيف؟", lex)
    assert {(r.place_id, r.modality) for r in rs} == {(1, "question"), (2, "question")}
    assert got("دير شرف فتحت ولا لسا", lex) == {}


def test_a_detour_is_not_a_report(lex):
    """The ✅ at the end of "go round by…" is not those checkpoints open."""
    assert got("روح ع عطاره في ازمه طويله\nاو بتلف ع عناب وبترجع على دير شرف↪️✅", lex) == {
        1: "bot:congested"}


# ── the answer that names nothing ────────────────────────────────────────────

def test_a_reply_is_about_what_was_asked(lex):
    """v1 filed 361 replies "حاجز للخارج" under Avnei Hefetz, as open."""
    assert got("حاجز للخارج", lex, parent="عطاره كيف؟") == {1: "out:idf"}
    assert got("سالك", lex, parent="شو وضع عين سينا") == {2: "bot:open"}
    assert got("سالك", lex) == {}


def test_a_reply_takes_the_direction_that_was_asked(lex):
    assert got("مغلق\nالداخل فاتح", lex, parent="كيف عناب للخارج") == {4: "inb:open out:closed"}


def test_a_reply_with_a_subject_of_its_own_inherits_nothing(lex):
    assert got("الطنيب شرطة من عشر دقايق", lex, parent="في اشي على دير شرف؟") == {}
    assert got("سالك", lex, parent="عطاره ولا عين سينيا احسن؟") == {}        # two were asked
    assert got("سالك", lex, parent="بلف ع عناب احسن") == {}                  # none was the subject
    assert subjects_of("عين سينيا حاجز للخارج من عطاره", lex).keys() == {2}


def test_the_checkpoint_is_what_was_asked_about_but_the_town_is_not(lex):
    """"الحاجز سالك" answers for the checkpoint asked about. "البلد سالك" is the
    town road, a different row where the register holds one, and nobody's
    where it does not."""
    assert got("الحاجز سالك", lex, parent="كيف عطاره؟") == {1: "bot:open"}
    assert got("البوابة مسكرة", lex, parent="شو وضع سنجل") == {6: "bot:closed"}
    assert got("البلد سالك", lex, parent="كيف عطاره؟") == {}
    assert got("حجز عادي مفتوح", lex, parent="كيف عطاره؟") == {}
    assert roads.candidate_names("البلد فاتح", lex) == []          # nor a name waiting for a yes


def test_a_crossings_channel_is_about_the_crossing_only_when_it_says_so(lex):
    assert got("تم فتح البوابة ودخول المسافرين", lex, home=10) == {10: "inb:open"}
    assert got("حجز عادي ما في بشهر 8", lex, home=10) == {}
    assert got("انت واضح فاضي", lex, home=10) == {}


# ── the two doors ────────────────────────────────────────────────────────────

def test_the_spool_door(tmp_path):
    day = tmp_path / "2026-10-11.ndjson"
    rows = [
        {"channel": "A7walStreet", "msg_id": "10", "date": "2026-10-11T06:00:00+00:00",
         "text": "عطاره سالك", "is_checkpoint_channel": "True", "reply_to_id": "None"},
        {"channel": "a7walstreet", "msg_id": "11", "date": "2026-10-11T06:01:00+00:00",
         "text": "سالك", "is_checkpoint_channel": "True", "reply_to_id": "10"},
        {"channel": "qudsn", "msg_id": "12", "date": "2026-10-11T06:02:00+00:00",
         "text": "خبر", "is_checkpoint_channel": "False", "reply_to_id": "None"},
        {"channel": "a7walstreet", "msg_id": "13", "date": "2026-10-11T06:03:00+00:00",
         "text": "None", "is_checkpoint_channel": "True", "reply_to_id": "None"},
    ]
    day.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
                   + '{"channel": "a7walstreet", "msg_id": "14", "da\x00\x00\n', encoding="utf-8")
    (tmp_path / "2026-10-09.ndjson").write_text(json.dumps(
        {"channel": "a7walstreet", "msg_id": "1", "date": "2026-10-09T06:00:00+00:00",
         "text": "قديم", "is_checkpoint_channel": "True"}) + "\n", encoding="utf-8")
    msgs, torn = roads.spool_messages(datetime(2026, 10, 10, tzinfo=timezone.utc), tmp_path)
    assert sorted(msgs) == [("a7walstreet", 10), ("a7walstreet", 11)]
    assert msgs[("a7walstreet", 11)].reply_to == 10
    assert torn == 1                       # the torn line is counted, never fatal


def test_names_nobody_registered_are_kept_for_a_yes(lex):
    names = roads.candidate_names("المهلل سالك", lex)
    assert names and names[0][1] == "المهلل"
    assert roads.candidate_names("بس سالك", lex) == []             # a filler names nothing
    assert roads.candidate_names("عطاره سالك", lex) == []          # already registered
    parts = roads.candidate_names("بوابة سنجل المحول مغلقة", lex)
    assert parts and "سنجل" in parts[0][1] and "المحول" in parts[0][1]
