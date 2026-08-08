"""Format v2 is a registry, and every spec conforms to it.

The thing being defended: a reviewed document that describes behaviour no code
performs. Three of those were live on 2026-08-08 — `place.min_resolved_pct` in
20 specs, `source_routing.default` in 21, and the latlon rung of
`place.fallback` in 4 — and all three had been reviewed, approved and
believed. A reviewer cannot tell a real key from a decorative one by reading
YAML. These tests are how the machine tells them apart.
"""
from __future__ import annotations

import pytest
import yaml

from ingest.spec import (IDENTITY_FIELDS, R, SpecInvalid, SPECS,   # noqa: F401
                         validate, validate_or_raise)


def _specs():
    return sorted(SPECS.glob("*.yaml"))


def _load(p):
    return yaml.safe_load(p.read_text())


@pytest.mark.parametrize("path", _specs(), ids=lambda p: p.stem)
def test_every_spec_is_valid_format_v2(path):
    problems = validate(_load(path), path.stem)
    assert not problems, "\n".join(str(p) for p in problems)


def test_no_spec_contains_an_unregistered_key():
    """The registry is complete, not merely consistent. If a spec grows a key
    nobody registered, this fails before the loader ever reads it."""
    unknown = []
    for p in _specs():
        unknown += [str(x) for x in validate(_load(p), p.stem)
                    if "unknown key" in x.message]
    assert not unknown, unknown


def test_no_registered_key_is_unimplemented():
    """The D6 rule, from the other side. A key may sit in the registry marked
    `unimplemented` only as a temporary, deliberate state — and no spec may
    use it while it does. If this list is ever non-empty, the specs using
    those keys are refused, which is the point."""
    dead = [p for p, k in R.items() if k.cls == "unimplemented"]
    used = []
    for p in _specs():
        spec = _load(p)
        for problems in [validate(spec, p.stem)]:
            used += [str(x) for x in problems if "NOT IMPLEMENTED" in x.message]
    assert not used, (f"registry marks {dead} unimplemented and specs still "
                      f"declare them: {used}")


def test_identity_fields_are_names_the_renderer_knows():
    """A field name identity_key_for cannot render raises mid-run, after the
    corpus is half-read and the collision counters are already populated."""
    for p in _specs():
        spec = _load(p)
        idents = [spec.get("identity")] + [
            (d.get("overrides") or {}).get("identity")
            for d in spec.get("datasets") or []]
        for ident in [i for i in idents if i]:
            for f in ident.get("fields") or []:
                assert f in IDENTITY_FIELDS, f"{p.stem}: identity field {f!r}"


def test_description_never_reaches_attrs():
    """Law 6, asserted rather than remembered. `description` is bulk text; it
    stays in bronze and raw_ref points there."""
    for p in _specs():
        spec = _load(p)
        paths = list(spec.get("attrs_passthrough") or [])
        for d in spec.get("datasets") or []:
            paths += list((d.get("overrides") or {}).get("attrs_passthrough")
                          or [])
        for path in paths:
            assert str(path).split(".")[-1] != "description", \
                f"{p.stem}: {path}"


def test_every_drop_is_measured():
    """A drop the reviewer cannot size is an invitation to lose data quietly.
    Defensive drops declare 0 — which is itself a claim, and a checkable one."""
    for p in _specs():
        for d in _load(p).get("drop") or []:
            assert "measured" in d, f"{p.stem}: drop {d.get('reason')!r}"


def test_validator_refuses_an_unknown_key():
    spec = {"category": "x", "shape": "observation", "status": "reviewed",
            "records_measured": 1, "min_resolved_pct": 0.9}
    with pytest.raises(SpecInvalid) as e:
        validate_or_raise(spec, "x")
    assert "unknown key" in str(e.value)


def test_validator_suggests_the_key_you_meant():
    """A typo in a reviewed document currently reads as silence. The
    suggestion is what turns 'unknown key' into a two-second fix."""
    spec = {"category": "x", "shape": "observation", "status": "reviewed",
            "place": {"min_located_pctt": 0.9}}
    problems = validate(spec, "x")
    assert any("min_located_pct'?" in str(p) for p in problems), problems


def test_validator_refuses_an_empty_identity():
    """The 2026-08-07 freeze, in one assertion: an identity naming nothing
    maps every row of a dataset to one key, and a key that cannot separate two
    rows does not de-duplicate them — it deletes the second."""
    spec = {"category": "x", "shape": "observation", "status": "reviewed",
            "identity": {"fields": [], "attrs": []},
            "expect": {"min_records": 1, "max_observations": 2}}
    problems = validate(spec, "x")
    assert any("DELETES" in str(p) for p in problems), problems


def test_validator_refuses_a_floor_above_the_measurement():
    spec = {"category": "x", "shape": "observation", "status": "reviewed",
            "records_measured": 100,
            "identity": {"fields": ["indicator"]},
            "expect": {"min_records": 200, "max_observations": 300}}
    problems = validate(spec, "x")
    assert any("can only fail" in str(p) for p in problems), problems


def test_validator_accepts_a_provenance_only_source_without_a_dataset():
    """conflict names Zochrot, Palestine Remembered, Atlas of Palestine and
    Wikidata in by_name so their licences are asserted, and gives them no
    dataset on purpose. An orphan check that cannot see that would force four
    fictional datasets into the schema."""
    spec = {"category": "x", "shape": "observation", "status": "reviewed",
            "provenance_only": ["zochrot"],
            "source_routing": {"by_name": {"Zochrot village page": "zochrot",
                                           "UCDP-GED": "ucdp"}},
            "datasets": [{"key": "x_ucdp", "source": "ucdp"}],
            "identity": {"fields": ["indicator"]},
            "expect": {"min_records": 1, "max_observations": 2}}
    assert not [p for p in validate(spec, "x") if "no dataset" in p.message]


def test_the_loader_refuses_an_invalid_spec_before_reading_a_record(tmp_path,
                                                                    monkeypatch):
    """Validation is a GATE, not a linter you remember to run."""
    import ingest.databank as db
    bad = tmp_path / "bogus.yaml"
    bad.write_text(yaml.safe_dump({
        "category": "bogus", "shape": "observation", "status": "reviewed",
        "records_measured": 1, "notes": "x",
        "identity": {"fields": ["indicator"]},
        "expect": {"min_records": 1, "max_observations": 2},
        "place": {"strategy": "region", "min_resolved_pct": 1.0},
    }))
    monkeypatch.setattr(db, "SPECS", tmp_path)
    with pytest.raises(SpecInvalid):
        db.load_spec("bogus")
