"""Regression cases for the checkpoint reader.

Every case here is a real line from the v1 corpus that was parsed WRONG at some
point — either by v1, or by an earlier version of this module. They are kept as
tests because each one represents a specific way Arabic road-status text defeats
a naive parser, and several of them invert meaning rather than merely lose it.

    ./.venv/bin/python -m pytest tests/test_checkpoint_text.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cascade.checkpoint_text import read  # noqa: E402


def facts_of(text: str) -> str:
    r = read(text)
    if r.modality != "assertion":
        return r.modality.upper()
    return " ".join(f"{f.direction[:3]}:{f.value}"
                    for f in sorted(r.facts, key=lambda x: (x.direction, x.axis, x.value)))


# ── questions are not evidence ────────────────────────────────────────────────
# v1 stored all of these as facts; 4,566 lines like the first became `open`.
@pytest.mark.parametrize("text", [
    "بوابة دورا فاتحة؟",           # "is the Dura gate open?"
    "النبي يونس لسا فاتحة ؟",      # "is Nabi Yunis still open?"
    "شو وضع شافي شمرون",           # "what's the status of Shavei Shomron" (no ?)
    "اي حاجز سالك المربعه ولا عورتا ؟",
    "عطارة للخارج كيف",            # interrogative particle LAST
    "كيف عورتا للخارج",
])
def test_questions_are_not_evidence(text):
    assert read(text).modality == "question"
    assert not read(text).is_evidence


# ── direction is per-clause, and can differ within one line ───────────────────
@pytest.mark.parametrize("text,expect", [
    # "Anabta: inspection outbound, flowing inbound" — v1 tagged the OUTBOUND
    # fact with direction=inbound and dropped the inbound fact entirely.
    ("🔴عنبتا تفتيش للخارج، سالك للداخل.", "inb:open out:inspection"),
    ("حوارة سالك للداخل ومغلق للخارج",     "inb:open out:closed"),
    ("عناب (عنبتا): الداخل: سالك - الخارج مغلق", "inb:open out:closed"),
    # No separator at all — direction binds positionally.
    ("عناب سالك ل الداخل مغلق للخارج",     "inb:open out:closed"),
    ("دير شرف ازمه للخارج مع تفتيش و للداخل سالك",
     "inb:open out:congested out:inspection"),
    # A single direction governs every status in the clause.
    ("جبع ازمة وتفتيش للخارج", "out:congested out:inspection"),
])
def test_direction_binding(text, expect):
    assert facts_of(text) == expect


# ── flow and presence are separate axes ───────────────────────────────────────
@pytest.mark.parametrize("text,expect", [
    # "Ein Shibli opened, with inspection" — v1 returned `inspection` alone,
    # losing the fact that it is passable.
    ("عين شبلي فتحت مع تفتيش ⚠️", "bot:open bot:inspection"),
    ("🔴المربعة تواجد للمستوطنين يرجى الحذر.", "bot:settlers"),
])
def test_axes_are_independent(text, expect):
    assert facts_of(text) == expect


# ── negation, and the traps around it ─────────────────────────────────────────
@pytest.mark.parametrize("text,expect", [
    ("مراح رياح مش سالك", "bot:closed"),          # genuine negation
    # "ما زال" / "لا زالت" mean STILL, not NOT. Reading the particle as a
    # negator turned "still closed" into open.
    ("النبي الياس ما زال مغلق❌", "bot:closed"),
    ("عين سينيا لا زالت مغلق❌", "bot:closed"),
    # "لا" before an adjective is the discourse "no", not negation.
    ("لا مسكر", "bot:closed"),
])
def test_negation(text, expect):
    assert facts_of(text) == expect


def test_absence_is_recorded_not_discarded():
    """"بدون جيش" used to be thrown away, and P1.3 measured the cost: 28.31% of
    all presence mentions in the corpus are negated, and they are the only
    statements of absence anybody ever makes. Without them `present` was the
    only value presence could take, so it could never be contradicted and the
    served state was `unknown` for 99.5% of places."""
    r = read("حومش سالك بدون جيش")
    assert r.flow_for("both").value == "open"
    assert r.absence_for("both") == ["idf"]
    # The original protection still holds: absence must never read as presence.
    assert r.presence_for("both") == []


def test_a_negator_is_consumed_by_the_word_it_reaches_first():
    """"المربعة بدون جيش سالكة" — "without army, FLOWING". The بدون belongs to
    جيش, which sits between it and سالكة. Reading two tokens back inverted the
    road to CLOSED: the most expensive error this parser can make, produced by
    a line that is good news twice over."""
    r = read("المربعة بدون جيش سالكة")
    assert r.flow_for("both").value == "open"
    assert r.absence_for("both") == ["idf"]


def test_phrase_match_respects_token_boundaries():
    """"حومش سالك" ("Homesh is flowing") contains the characters of "مش سالك"
    ("not flowing") across a word boundary. Substring matching inverted it."""
    assert facts_of("حومش سالك") == "bot:open"
    assert facts_of("حومش سالك ✅") == "bot:open"
    assert facts_of("مش سالك") == "bot:closed"


def test_emoji_attached_to_word_does_not_hide_it():
    """Channels append emoji with no space; the token must still be found."""
    assert facts_of("بني نعيم سالكه✔️✔️✔️") == "bot:open"
    assert facts_of("ياسوف: ❌ مغلق") == "bot:closed"


def test_bare_noun_is_not_a_status():
    """v1 maps حاجز ("checkpoint") to idf, so naming a checkpoint reported
    soldiers at it. Only the predicative use counts."""
    assert facts_of("عابود حاجز") == "bot:idf"          # "there's a checkpoint"
    assert facts_of("المربعه في حاجز") == "bot:idf"
    assert facts_of("حاجز قلنديا سالك") == "bot:open"   # naming, not reporting


def test_withdrawal_clears_presence():
    """v1 stored "the army withdrew from Sarra" as a place NAME.

    A withdrawal now asserts BOTH that the road opened and that the army is
    gone — the second at lower confidence, since the verb may attach to a
    different entity than the one named."""
    r = read("انسحب الجيش عن صرة")
    assert r.flow_for("both").value == "open"
    assert r.absence_for("both") == ["idf"]
    assert r.presence_for("both") == []
    assert facts_of("عطارة شالو الحاجز") == "bot:open"


def test_most_restrictive_flow_wins_per_direction():
    r = read("دير شرف فاتح بس البوابة مسكرة")
    assert r.flow_for("both").value == "closed"


def test_nothing_is_silently_dropped():
    """A line we cannot read is still a Reading, never an exception."""
    for text in ["", "   ", "قلنديا", "🔴🔴", None]:
        r = read(text)
        assert r.modality in ("unparsed", "assertion", "question")
        assert not (r.modality == "unparsed" and r.facts)


# ── negation inside a PHRASE ─────────────────────────────────────────────────
# Single tokens were negation-checked from the start; the phrase table was not,
# so "ما فيه جيش على الحاجز" — somebody standing at the checkpoint saying the
# army is NOT there — was read as `presence: idf`. The phrase matched inside its
# own negation. Two costs, and the second is larger: a caution is manufactured
# out of good news, AND the absence is discarded, when a negated mention is the
# only way anybody ever states that soldiers have gone (P1.3: 28.31% of all
# presence mentions in the corpus are negated).

def test_negated_presence_phrase_is_absence_not_presence():
    for line in ("ما فيه جيش على الحاجز", "ما في محسوم ع جبع",
                 "ما فيه شرطه هناك"):
        r = read(line)
        axes = {(f.axis, f.value) for f in r.facts}
        assert not any(a == "presence" for a, _ in axes), f"{line} -> {axes}"
        assert any(a == "absence" for a, _ in axes), f"{line} -> {axes}"


def test_unnegated_presence_phrase_is_unchanged():
    """The fix must not cost the case the phrase existed for."""
    assert ("presence", "idf") in {(f.axis, f.value) for f in read("فيه جيش على الحاجز").facts}


def test_negated_flow_phrase_flips():
    assert ("flow", "open") in {(f.axis, f.value) for f in read("ما في ازمه").facts}


# ── vocabulary found by sampling what v1 read and we did not ────────────────

def test_machsom_is_read_only_when_something_was_PUT_there():
    """محسوم (Hebrew מחסום) is a NOUN meaning checkpoint, like حاجز.

    "حطو محسوم" says one was erected — that is a sighting. A bare
    "اللبن الشرقي محسوم" is genuinely ambiguous between "there is a checkpoint
    here" and "the road is blocked", and v1 resolves it by asserting `closed`,
    which is a caution invented from a noun. We decline it on purpose.
    """
    assert ("presence", "idf") in {(f.axis, f.value) for f in read("جبع حطو محسوم هلكيت").facts}
    bare = read("اللبن الشرقي محسوم")
    assert not any(f.axis == "flow" for f in bare.facts), \
        "a bare noun must not become a flow verdict"


def test_zaatim_is_congestion():
    for line in ("جبع زاطم", "المشاة زاطم", "الكونتينر باتجاه الجنوب زاطم"):
        assert ("flow", "congested") in {(f.axis, f.value) for f in read(line).facts}, line


def test_elongation_for_emphasis_still_reaches_the_lexicon():
    """normalize() strips tatweel but not a genuinely repeated letter.

    "زااااااااااطم" and "ازززمه" are real lines from the channels. They missed
    the lexicon entirely and fell through to `unparsed`.
    """
    for line in ("عين سينيا للخارج زااااااااااطم", "بيت فوريك ازززمه",
                 "وجبع زاطمممممم"):
        assert ("flow", "congested") in {(f.axis, f.value) for f in read(line).facts}, line


def test_collapsing_never_overrides_a_direct_hit():
    """Collapse is a LAST resort, after the literal forms have had their turn."""
    assert ("flow", "open") in {(f.axis, f.value) for f in read("سالك").facts}
    assert ("flow", "closed") in {(f.axis, f.value) for f in read("مسكر").facts}


# ── the direction audit (2026-08-03): binding is clause-wide, not per-status ─
def _fd(text):
    """{(axis, value): (direction, explicit)} for one line."""
    return {(f.axis, f.value): (f.direction, f.direction_explicit)
            for f in read(text).facts}


def test_topic_comment_order_does_not_invert():
    """"بيت ايل الداخل سالك الخارج تفتيش" — inbound open, outbound inspection.

    The old tie-break preferred the FOLLOWING direction, on the theory that
    prefix order always carries a separator. It does not, and سالك went to
    الخارج — serving OPEN for the direction the text says is under inspection.
    v1's inversion class, recreated in v2, caught by the hand-scored audit.
    """
    f = _fd("بيت ايل الداخل سالك الخارج تفتيش")
    assert f[("flow", "open")] == ("inbound", True)
    assert f[("presence", "inspection")] == ("outbound", True)


def test_postfix_order_still_binds_forward():
    f = _fd("سالك للداخل تفتيش للخارج")
    assert f[("flow", "open")] == ("inbound", True)
    assert f[("presence", "inspection")] == ("outbound", True)


def test_alternating_line_keeps_both_facts():
    """"العبيدية للداخل سالك للخارج ازمة" — the misbound `open` used to lose
    the severity collapse against `congested` and the inbound fact VANISHED."""
    f = _fd("العبيدية للداخل سالك للخارج ازمة")
    assert f[("flow", "open")] == ("inbound", True)
    assert f[("flow", "congested")] == ("outbound", True)


def test_shared_direction_is_still_shared():
    f = _fd("حاجز صرة سالكه للداخل وخارج ازمه وتفتيش")
    assert f[("flow", "open")] == ("inbound", True)
    assert f[("flow", "congested")] == ("outbound", True)
    assert f[("presence", "inspection")] == ("outbound", True)


def test_enumerated_directions_are_one_both():
    """"مسكر للي داخل والخارج" is one statement of both, not two anchors —
    it served closed-inbound and unknown-outbound."""
    f = _fd("جسر اودلا مسكر للي داخل والخارج")
    assert f[("flow", "closed")] == ("both", True)
    f = _fd("الداخل والخارج مغلق")
    assert f[("flow", "closed")] == ("both", True)


def test_both_sides_dialect_forms():
    f = _fd("عين شبلي بطيء عالجهتين")
    assert f[("flow", "slow")] == ("both", True)
    f = _fd("جبع شرطة لداخل الرام")
    assert f[("presence", "police")] == ("inbound", True)


def test_the_army_standing_is_not_a_traffic_jam():
    """"الجيش واقف على المدخل" — واقف is a flow word only when its subject is
    the road. A soldier standing still manufactured a jam."""
    vals = {(f.axis, f.value) for f in read("بيتا فيها اقتحام والجيش واقف على المدخل 🔴").facts}
    assert ("presence", "idf") in vals
    assert ("flow", "congested") not in vals
    # The traffic standing IS a jam.
    assert ("flow", "congested") in {(f.axis, f.value)
                                     for f in read("السير واقف على حاجز قلنديا").facts}


def test_forbidding_passage_is_a_closure():
    f = _fd("الجيش تحت جسر اودلا ومنعو المرور في الاتجاهين")
    assert f[("flow", "closed")] == ("both", True)
    assert ("presence", "idf") in f


def test_a_fuel_line_at_a_crossing_is_not_a_closure():
    """"الجلمة :سولار❌بنزين❌" — the ❌ is about diesel. Emoji glued to words
    used to fuse them into one unmatchable token, so the fuel nouns were
    invisible and the crossing served as closed."""
    r = read("الجلمة :سولار❌بنزين❌")
    assert not r.facts
    # Plain emoji shorthand still reads.
    assert ("flow", "closed") in {(f.axis, f.value) for f in read("الفحص❌❌❌").facts}


def test_a_dispute_about_the_status_is_a_question():
    r = read("الي بحكي انو عورتا سالك يعطينا دليل لانو في بيحكو أنها ازمه وتفتيش")
    assert r.modality == "question"


def test_wala_fi_negates_the_existential():
    """"ولا في مستوطنين" — "and there are NO settlers" — recorded settlers
    PRESENT. لا stays a discourse marker everywhere except directly before
    the existential في/فيه."""
    vals = {(f.axis, f.value) for f in read("بس جيش و لا في مستوطنين بضربو عالسيارات").facts}
    assert ("presence", "idf") in vals
    assert ("absence", "settlers") in vals
    assert ("presence", "settlers") not in vals
    # "لا مسكر" is still "no, it's closed".
    assert ("flow", "closed") in {(f.axis, f.value) for f in read("لا مسكر").facts}


def test_clearing_scopes_to_the_adjacent_noun():
    """"راح الجيش اجو المستوطين بكسرو بالسيارات" — the army left AND the
    settlers arrived. The line-wide cleared flag marked the arriving settlers
    absent, and the departure inferred `open` over an active attack."""
    vals = {(f.axis, f.value) for f in read("راح الجيش اجو المستوطين بكسرو بالسيارات").facts}
    assert ("absence", "idf") in vals
    assert ("presence", "settlers") in vals
    assert ("flow", "open") not in vals
    # Verb after the noun still clears it; a lone withdrawal still opens.
    vals = {(f.axis, f.value) for f in read("تحت جسر اودلا الجيش انسحب").facts}
    assert ("absence", "idf") in vals and ("flow", "open") in vals
