"""The scout's reviewed memory must parse, and must stay internally honest.

WHY THIS FILE EXISTS
`db/scout/verdicts.yaml` is the file that stops the scout re-proposing settled
questions and re-chasing debunked ghosts. On 2026-08-07 a hand-edit put a bare
`TLS:` inside a multi-line plain scalar; the file stopped parsing, and the
Sunday 04:30 sweep would have died on the second statement of main() — quietly,
until somebody read an alert. The file is prose written by humans under time
pressure, so it WILL be edited badly again. These tests make that a red build
instead of a dead job.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
VERDICTS = ROOT / "db" / "scout" / "verdicts.yaml"
SECTIONS = {"adopted", "debunked", "rejected", "dead_upstream",
            "assessed_orgs", "candidates"}


@pytest.fixture(scope="module")
def verdicts() -> dict:
    return yaml.safe_load(VERDICTS.read_text())


def test_verdicts_yaml_parses(verdicts) -> None:
    """The guard that makes the 2026-08-07 outage unrepeatable."""
    assert isinstance(verdicts, dict) and verdicts


def test_every_section_is_known(verdicts) -> None:
    """A typo'd section name would silently hold zero verdicts — which reads,
    to the scout, exactly like a source nobody has ever assessed."""
    unknown = set(verdicts) - SECTIONS
    assert not unknown, f"unknown verdict sections: {sorted(unknown)}"


def test_every_candidate_carries_a_verdict(verdicts) -> None:
    missing = [k for k, v in (verdicts.get("candidates") or {}).items()
               if not (isinstance(v, dict) and str(v.get("verdict", "")).strip())]
    assert not missing, f"candidates with no verdict: {missing}"


def test_settled_sources_are_not_also_candidates(verdicts) -> None:
    """The file's own law: a candidate leaves in exactly one of three ways.
    Appearing in two sections means one of them is stale, and the scout would
    act on whichever it read first."""
    settled = set(verdicts.get("adopted") or {}) \
        | set(verdicts.get("debunked") or {}) \
        | set(verdicts.get("rejected") or {})
    both = settled & set(verdicts.get("candidates") or {})
    assert not both, f"listed as both settled and candidate: {sorted(both)}"


def test_debunked_and_rejected_carry_their_evidence(verdicts) -> None:
    """A verdict without its reason is folklore: the next reader cannot tell a
    measured finding from a hunch, and re-chases it."""
    for section, field in (("debunked", "finding"), ("rejected", "reason")):
        for key, entry in (verdicts.get(section) or {}).items():
            assert isinstance(entry, dict), f"{section}.{key} is not a mapping"
            assert str(entry.get(field, "")).strip(), \
                f"{section}.{key} has no {field}"


def test_the_method_law_is_still_recorded() -> None:
    """Set 2026-08-07 after a scout reached a backend with a key lifted from a
    JS bundle. It lives in a comment, so no parse test would notice its
    deletion."""
    text = VERDICTS.read_text()
    assert "METHOD LAW" in text
    assert "never extract credentials" in text.lower()


def test_scout_refuses_a_broken_memory(tmp_path, monkeypatch) -> None:
    """Refusal is the behaviour under test — not that it parses today."""
    from ops import source_scout

    bad = tmp_path / "verdicts.yaml"
    bad.write_text("candidates:\n  x:\n    verdict: a plain scalar\n"
                   "      TLS: with a mapping colon inside it\n")
    monkeypatch.setattr(source_scout, "VERDICTS", bad)
    with pytest.raises(SystemExit) as e:
        source_scout.load_verdicts()
    assert "not valid YAML" in str(e.value) and "line" in str(e.value)
