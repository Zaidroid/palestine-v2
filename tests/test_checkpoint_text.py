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


# ══ the 2026-09-25 system audit: inversions and lost facts ═══════════════════
# Every line below reproduced on the parser as it stood before this section was
# written. `must` is what the line says; `must_not` is the value the parser used
# to serve instead — the inversion itself, pinned so it cannot come back.

def _full(text: str) -> set[tuple[str, str, str]]:
    """{(direction, axis, value)} for one line."""
    return {(f.direction, f.axis, f.value) for f in read(text).facts}


def _ax(text: str) -> set[tuple[str, str]]:
    return {(f.axis, f.value) for f in read(text).facts}


def _check(text, must, must_not):
    got = _ax(text)
    for m in must:
        assert m in got, f"{text!r}: missing {m}, got {got}"
    for m in must_not:
        assert m not in got, f"{text!r}: must not read {m}, got {got}"


# ── F001/F005: 'ما' after بعد/قبل/زي/مثل/حسب… is a conjunction, not "not" ─────
@pytest.mark.parametrize("text,must,must_not", [
    ("بعد ما سكروا الحاجز", [("flow", "closed")], [("flow", "open")]),
    ("زي ما هو مسكر", [("flow", "closed")], [("flow", "open")]),
    ("الحاجز زي ما هو مسكر من الصبح", [("flow", "closed")], [("flow", "open")]),
    ("حسب ما سمعت مسكر", [("flow", "closed")], [("flow", "open")]),
    ("عطارة حسب ما سمعت مسكر", [("flow", "closed")], [("flow", "open")]),
    ("حسب ما قالوا مغلق", [("flow", "closed")], [("flow", "open")]),
    ("مثل ما كان مغلق", [("flow", "closed")], [("flow", "open")]),
    ("مثل ما هو مغلق", [("flow", "closed")], [("flow", "open")]),
    ("بعد ما فتحوا الحاجز سالك", [("flow", "open")], [("flow", "closed")]),
    ("بعد ما فتح الحاجز الوضع هدي", [("flow", "open")], [("flow", "closed")]),
    # The negating ما is untouched.
    ("بس ما في جيش", [("absence", "idf")], [("presence", "idf")]),
    ("النبي الياس ما زال مغلق", [("flow", "closed")], [("flow", "open")]),
])
def test_relative_ma_is_not_a_negator(text, must, must_not):
    _check(text, must, must_not)


def test_negating_ma_still_negates():
    assert _ax("ما كان مسكر") == {("flow", "open")}
    assert facts_of("مراح رياح مش سالك") == "bot:closed"


# ── F006/F098: not knowing, and "if", are not reports ──────────────────────────
@pytest.mark.parametrize("text", [
    "ما بعرف اذا حوارة سالك",
    "مابعرف اذا حوارة سالك",
    "حد بعرف اذا حوارة سالك",
    "حدا بعرف اذا حوارة سالك",
    "مش عارف سالك",
    "مش عارف اذا الحاجز سالك ولا لا",
    "اذا فتح الحاجز خبرونا",
    "لو فتح الحاجز خبرونا",
    "اذا سالك احكولنا",
    "اذا فتح حوارة بنمشي",
    "ازا فتح الحاجز خبرونا",
])
def test_hedges_and_conditionals_are_not_evidence(text):
    r = read(text)
    assert not r.is_evidence, f"{text!r} -> {r.modality} {_ax(text)}"
    assert ("flow", "open") not in _ax(text)


def test_a_conditional_clause_does_not_cancel_the_report_before_it():
    """"Huwara is closed; if it opens I'll tell you" — the report stands, the
    hypothetical adds nothing."""
    for line in ("حوارة مسكر، اذا فتح بخبركم", "حوارة مسكر اذا فتح بخبركم"):
        assert _ax(line) == {("flow", "closed")}, line
    # "لو سمحت" is "please", not "if".
    assert _ax("لو سمحت حوارة سالك") == {("flow", "open")}


# ── F002: a negator fused to its waw is still a negator ───────────────────────
@pytest.mark.parametrize("text,must,must_not", [
    ("عطارة ومش سالك", [("flow", "closed")], [("flow", "open")]),
    ("حوارة ومش سالك", [("flow", "closed")], [("flow", "open")]),
    ("سالكة وما في جيش", [("flow", "open"), ("absence", "idf")], [("presence", "idf")]),
    ("حوارة سالك وبدون تفتيش", [("absence", "inspection")], [("presence", "inspection")]),
    ("عطارة مسكر وبلا جيش", [("flow", "closed"), ("absence", "idf")], [("presence", "idf")]),
    ("المربعة سالكة وبدون جيش", [("flow", "open"), ("absence", "idf")], [("presence", "idf")]),
    ("جبع سالك مافي جيش", [("absence", "idf")], [("presence", "idf")]),
    ("سالك مافيش جيش", [("absence", "idf")], [("presence", "idf")]),
    ("عطارة سالكة ومافيش جيش", [("absence", "idf")], [("presence", "idf")]),
    ("وما زال مغلق", [("flow", "closed")], [("flow", "open")]),
])
def test_fused_waw_negators(text, must, must_not):
    _check(text, must, must_not)


def test_fused_negator_keeps_per_direction_lanes():
    assert _full("حوارة سالك للداخل ومش سالك للخارج") == {
        ("inbound", "flow", "open"), ("outbound", "flow", "closed")}


# ── F003: emoji bind to the direction they stand beside, not dict order ───────
@pytest.mark.parametrize("text,expect", [
    ("الداخل ✅ الخارج ❌", {("inbound", "flow", "open"), ("outbound", "flow", "closed")}),
    ("جبع دخول ✅ خروج ❌", {("inbound", "flow", "open"), ("outbound", "flow", "closed")}),
    ("بيت ايل الداخل❌ الخارج✅", {("inbound", "flow", "closed"), ("outbound", "flow", "open")}),
    ("✅ الداخل ❌ الخارج", {("inbound", "flow", "open"), ("outbound", "flow", "closed")}),
    ("عطارة ✅ للداخل ❌ للخارج", {("inbound", "flow", "open"), ("outbound", "flow", "closed")}),
    # 🔴 is an attention marker here, so outbound is simply not reported —
    # and above all not served open.
    ("للداخل 🟢 للخارج 🔴", {("inbound", "flow", "open")}),
    # An enumerated pair still shares its emoji.
    ("الداخل والخارج ✅", {("both", "flow", "open")}),
    ("✅ الداخل والخارج", {("both", "flow", "open")}),
])
def test_emoji_bind_per_direction(text, expect):
    assert _full(text) == expect


def test_conflicting_emoji_without_direction_take_the_most_restrictive():
    """Order in EMOJI_FLOW decided this before: ✅ listed first, so ✅❌ was open."""
    assert _ax("حوارة ❌✅") == {("flow", "closed")}
    assert _ax("حوارة ✅❌") == {("flow", "closed")}


# ── F019: "opened fire" is not "opened" ───────────────────────────────────────
@pytest.mark.parametrize("text", [
    "الجيش فتح النار على المركبات عند حاجز حوارة",
    "فتحوا النار على الشباب عند الحاجز",
    "العسكر فتحوا النار",
    "وفتحوا النار على السيارات",
])
def test_opening_fire_is_not_an_open_checkpoint(text):
    assert ("flow", "open") not in _ax(text)


def test_opening_the_checkpoint_is_still_open():
    assert _ax("فتحوا الحاجز") == {("flow", "open")}


# ── F020/F097: closure forms the lexicon did not know ─────────────────────────
@pytest.mark.parametrize("text", [
    "الحواجز مسكرين", "الحاجز مقفول", "البوابة مقفولة",
    "اغلقت قوات الاحتلال حاجز حوارة", "الاحتلال يغلق حاجز عورتا",
    "سكروه", "حوارة مغلقان", "سكرو الحاجز", "الطريق مقطوع",
    "منعوا الناس من المرور",
    "حوارة وزعترة مغلقان وبيت فوريك سالك",
])
def test_closure_forms_read_closed(text):
    assert read(text).flow_for("both") is not None, text
    assert read(text).flow_for("both").value == "closed", _full(text)


@pytest.mark.parametrize("text,expect", [
    ("ممنوع الدخول", {("inbound", "flow", "closed")}),
    ("الدخول ممنوع", {("inbound", "flow", "closed")}),
    ("منعو الدخول", {("inbound", "flow", "closed")}),
    ("ممنوع الخروج", {("outbound", "flow", "closed")}),
    ("منعوا الدخول والخروج", {("both", "flow", "closed")}),
    ("ممنوع الدخول لنابلس من حوارة", {("inbound", "flow", "closed")}),
    ("الجيش منع الدخول والخروج من حوارة",
     {("both", "flow", "closed"), ("both", "presence", "idf")}),
])
def test_entry_bans_are_closures_for_their_direction(text, expect):
    assert _full(text) == expect


def test_dual_closure_in_a_corpus_line():
    """Claim 450: 'Jit junction and Sarra checkpoint closed (dual) both ways,
    settlers present' — the closure was lost and only the settlers survived."""
    got = _full("مفرق جيت وحاجز صرّة مغلقان بالاتجاهين مع تواجد للمستـ.ـوطنين")
    assert ("both", "flow", "closed") in got
    assert ("both", "presence", "settlers") in got


def test_new_vocabulary_forms():
    assert _ax("فتحو الحاجز") == {("flow", "open")}
    assert _ax("بفتشوا") == {("presence", "inspection")}
    assert _ax("حوارة سلكت") == {("flow", "open")}
    assert _ax("الحركة طبيعية على حوارة") == {("flow", "open")}


# ── F021/F015: a lifted closure / a cleared jam is OPEN ───────────────────────
@pytest.mark.parametrize("text", [
    "تم رفع الاغلاق عن حاجز حوارة", "انتهى الاغلاق على حوارة", "خلص الاغلاق",
    "راحت الزحمة", "انتهت الازمة على عورتا", "خلصت الازمة",
    "انتهت الازمه", "خلصت الازمه", "راحت الازمه", "خلصت الازمة عالحاجز",
    "انتهت الزحمه", "خلصت الزحمة سالك", "الازمه خلصت",
])
def test_clearing_a_closure_or_jam_is_open(text):
    assert _ax(text) == {("flow", "open")}, _ax(text)


def test_clearing_verb_that_belongs_to_the_army_leaves_the_jam():
    """'jam, and the army left' — the verb clears the army, not the jam."""
    got = _ax("ازمه وراح الجيش")
    assert ("flow", "congested") in got and ("absence", "idf") in got
    assert _ax("لا زالت الازمه") == {("flow", "congested")}


# ── F013/F024: راح is also "going to" and "went to"; تركوا is "left (people)" ─
@pytest.mark.parametrize("text", [
    "راح يسكروا الحاجز", "راح يسكروا", "راح يسكروا حوارة",
    "راح يسكر الحاجز كمان شوي", "رح يسكروا الحاجز", "راح الجيش يسكر",
    "تركوا الناس واقفين على الحاجز ساعتين",
])
def test_a_forecast_or_an_unrelated_departure_is_not_open(text):
    got = _ax(text)
    assert ("flow", "open") not in got, got
    assert ("absence", "idf") not in got, got
    assert not read(text).is_evidence, got


@pytest.mark.parametrize("text", ["الجيش راح يسكر الحاجز", "الجيش راح عالحاجز"])
def test_the_army_going_to_do_something_is_still_there(text):
    assert _ax(text) == {("presence", "idf")}


def test_the_army_leaving_still_clears():
    for line in ("راح الجيش", "الجيش راح", "انسحب الجيش عن صرة"):
        assert _ax(line) == {("flow", "open"), ("absence", "idf")}, line


def test_a_negated_withdrawal_is_not_a_withdrawal():
    """'the army did NOT withdraw' served army absent and the road open."""
    for line in ("ما انسحب الجيش", "الجيش ما انسحب من حوارة", "الجيش لسا ما راح"):
        got = _ax(line)
        assert ("flow", "open") not in got and ("absence", "idf") not in got, (line, got)
        assert ("presence", "idf") in got, (line, got)


# ── F022: "open or not" is a question ─────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "عورتا سالك ولا لا", "عورتا سالك ولا", "حوارة سالك او مسكر",
    "سالك ولا مش سالك", "حوارة سالك او لا",
])
def test_open_or_not_is_a_question(text):
    assert read(text).modality == "question", _ax(text)


def test_wala_fi_after_a_status_is_a_reassurance_not_a_question():
    assert _ax("حوارة سالك ولا في زحمة") == {("flow", "open")}
    # The genuinely ambiguous "open or jammed" stays a question.
    assert read("حوارة سالك ولا زحمة").modality == "question"


# ── F014/F023: the spellings people actually type for "there is no …" ────────
@pytest.mark.parametrize("text,must,must_not", [
    ("لا يوجد جيش", [("absence", "idf")], [("presence", "idf")]),
    ("لا يوجد جيش على الحاجز", [("absence", "idf")], [("presence", "idf")]),
    ("لا جيش ولا تفتيش", [("absence", "idf"), ("absence", "inspection")],
     [("presence", "idf"), ("presence", "inspection")]),
    ("لا في جيش ولا تفتيش", [("absence", "idf"), ("absence", "inspection")],
     [("presence", "inspection")]),
    ("الحاجز مفتوح لا يوجد تفتيش", [("flow", "open"), ("absence", "inspection")],
     [("presence", "inspection")]),
    ("الجيش مش موجود", [("absence", "idf")], [("presence", "idf")]),
    ("جيش ما في", [("absence", "idf")], [("presence", "idf")]),
    ("مافي جيش على الحاجز", [("absence", "idf")], [("presence", "idf")]),
    ("مفيش جيش", [("absence", "idf")], [("presence", "idf")]),
    ("فش جيش", [("absence", "idf")], [("presence", "idf")]),
    ("ما في ولا جيش", [("absence", "idf")], [("presence", "idf")]),
    ("لا جيش ولا شرطة", [("absence", "idf"), ("absence", "police")],
     [("presence", "idf"), ("presence", "police")]),
    ("مافي ازمة", [("flow", "open")], [("flow", "congested")]),
    ("لا يوجد ازمة", [("flow", "open")], [("flow", "congested")]),
    ("لا يوجد ازمة على حوارة", [("flow", "open")], [("flow", "congested")]),
    ("سالك ولا جيش ولا شي", [("flow", "open"), ("absence", "idf")], [("presence", "idf")]),
    ("ولا جيش على حوارة", [("absence", "idf")], [("presence", "idf")]),
])
def test_negated_existentials(text, must, must_not):
    _check(text, must, must_not)


def test_a_fused_negator_is_consumed_by_the_word_after_it():
    """'army, no police' — the مافي belongs to شرطه, not to جيش."""
    got = _ax("جيش مافي شرطه")
    assert ("presence", "idf") in got and ("absence", "police") in got


# ── F122/F416: a vigil is not a jam; "at X checkpoint" is not a sighting ──────
def test_a_vigil_is_not_a_traffic_jam():
    for line in ("وقفة احتجاجية عند حاجز حوارة", "وقفة تضامنية على مدخل بيتا"):
        assert ("flow", "congested") not in _ax(line), line


def test_locative_fi_hajiz_is_not_a_sighting():
    assert _ax("ازمة في حاجز عطارة") == {("flow", "congested")}
    assert _ax("الوضع في حاجز حوارة سالك") == {("flow", "open")}
    assert _ax("في حاجز عورتا ازمه") == {("flow", "congested")}
    # The predicative/existential uses are kept.
    assert _ax("المربعه في حاجز") == {("presence", "idf")}
    assert _ax("في حاجز عند المدخل") == {("presence", "idf")}


def test_prepositional_dakhil_is_not_a_direction():
    assert _full("الجيش داخل البلد") == {("both", "presence", "idf")}
    assert _full("جيش خارج المخيم") == {("both", "presence", "idf")}
    # The direction uses are kept.
    assert _full("جسر اودلا مسكر للي داخل والخارج") == {("both", "flow", "closed")}
    assert _full("سالك داخل") == {("inbound", "flow", "open")}


# ── F123: the later state in a sequence is the current one ────────────────────
@pytest.mark.parametrize("text", [
    "كان مغلق الصبح وهلا سالك", "حوارة كان مغلق الصبح وهلا سالك",
    "انفتح الحاجز بعد اغلاق ساعتين", "فتح الحاجز بعد اغلاق دام ساعة",
])
def test_a_past_state_does_not_outrank_the_present_one(text):
    assert _ax(text) == {("flow", "open")}, _ax(text)


def test_a_lone_past_state_is_kept():
    assert _ax("الصبح كان مسكر") == {("flow", "closed")}


# ── F415/F432/F433/F436: lexicon hygiene ──────────────────────────────────────
def test_every_lexicon_key_is_already_normalised():
    """Tokens arrive normalize()d (ئ→ي, ة→ه); a key that is not can never match."""
    from cascade import checkpoint_text as ct
    from resolve.arabic import normalize
    for name in ("FLOW_WORDS", "PRESENCE_WORDS", "DIRECTION_WORDS"):
        bad = [k for k in getattr(ct, name) if normalize(k) != k]
        assert not bad, f"{name}: {bad}"
    for name in ("CLEARING_WORDS", "NEGATORS", "CONTINUATIVES", "QUESTION_OPENERS"):
        bad = [k for k in getattr(ct, name) if normalize(k) != k]
        assert not bad, f"{name}: {bad}"
    assert not [p for p, _, _ in ct.PHRASES if normalize(p) != p]
    assert not [p for p in ct.QUESTION_PHRASES if normalize(p) != p]


def test_hamza_spellings_of_slow():
    for line in ("عين شبلي بطئ", "بطيئ", "الحركة بطيئة"):
        assert _ax(line) == {("flow", "slow")}, line


def test_the_army_stationed_is_not_a_closure():
    assert _ax("الجيش موقوف على المدخل") == {("presence", "idf")}
    assert _ax("السير موقوف") == {("flow", "closed")}


def test_yellow_means_what_palhub_means():
    """cascade/palhub_roads.py maps 🟡 to congested, deliberately, so the two
    lanes do not read agreement as conflict."""
    from cascade.palhub_roads import EMOJI_HINT
    assert _ax("عورتا 🟡") == {("flow", EMOJI_HINT["🟡"])}


def test_not_normal_is_not_closed():
    for line in ("الوضع غير طبيعي", "مش عادي الوضع"):
        assert ("flow", "closed") not in _ax(line), line


# ── F417/F434: sentence boundaries, and a '?' inside a link ───────────────────
def test_a_full_stop_ends_the_negators_reach():
    assert _ax("بدون. مسكر") == {("flow", "closed")}
    assert _ax("ما في اشي جديد. سالك") == {("flow", "open")}
    # The censorship dot inside a word is not a boundary.
    assert ("presence", "settlers") in _ax("تواجد للمستـ.ـوطنين")


def test_a_question_mark_inside_a_link_is_not_a_question():
    r = read("حوارة سالك https://t.me/roads?start=1")
    assert r.modality == "assertion"
    assert _ax("حوارة سالك https://t.me/roads?start=1") == {("flow", "open")}


def test_a_newline_is_a_boundary_even_on_a_two_direction_line():
    """_presplit_waw rebuilt the line with single spaces, so a line break
    stopped separating clauses whenever two direction words were present."""
    assert _full("عطارة ما\nسالك للداخل ومسكر للخارج") == {
        ("inbound", "flow", "open"), ("outbound", "flow", "closed")}
