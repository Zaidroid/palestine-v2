"""db/registry/names.yaml — the hand-written names of the databank's indicators.

No database: the file is read as it is on disk. ops/load_registry.py looks a
publisher's name up by the English text the rows carry with whitespace
collapsed, so a key holding a line break or a double space would never match
and its Arabic would silently never be written. An entry whose English is its
own key names nothing."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

NAMES = Path(__file__).resolve().parent.parent / "db" / "registry" / "names.yaml"


@pytest.fixture(scope="module")
def doc() -> dict:
    return yaml.safe_load(NAMES.read_text(encoding="utf-8"))


def _arabic_strings(doc: dict) -> list[tuple[str, str]]:
    out = [(k, v.get("ar") or "") for k, v in doc["names"].items()]
    out += list(doc["publisher_names"].items())
    out += list(doc["dimension_names"].items())
    return out


def test_the_file_parses_into_its_three_maps(doc):
    assert set(doc) == {"names", "publisher_names", "dimension_names"}
    for part in ("names", "publisher_names", "dimension_names"):
        assert isinstance(doc[part], dict) and doc[part], part


def test_every_named_indicator_has_an_english_name(doc):
    blank = [k for k, v in doc["names"].items()
             if not isinstance(v, dict) or not str(v.get("en") or "").strip()]
    assert blank == []


def test_no_name_is_its_own_key(doc):
    same = [k for k, v in doc["names"].items() if str(v.get("en") or "").strip() == k]
    assert same == []


def test_lookup_keys_are_whitespace_clean(doc):
    """`_clean` in ops/load_registry.py collapses whitespace on the carried
    name before the lookup; a key written any other way is unreachable."""
    for part in ("publisher_names", "dimension_names"):
        bad = [k for k in doc[part] if "\n" in k or "  " in k or k != k.strip()]
        assert bad == [], part


def test_every_arabic_value_is_a_real_string(doc):
    blank = [k for k, ar in _arabic_strings(doc) if not isinstance(ar, str) or not ar.strip()]
    assert blank == []


def test_no_arabic_name_calls_a_person_a_stitch(doc):
    """The film's word for a mark on the cloth is never a word for a martyr."""
    assert [k for k, ar in _arabic_strings(doc) if "غرزة" in ar] == []


def test_arabic_names_write_western_digits(doc):
    assert [k for k, ar in _arabic_strings(doc) if re.search("[٠-٩۰-۹]", ar)] == []
