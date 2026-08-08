"""Identity is law: every migrating spec declares one, and it is injective.

WHY THIS FILE EXISTS
On 2026-08-07 v1 re-hashed every stable_id and the databank re-inserted 19,451
observations. The guard written that day — a declared natural key per dataset —
then silently FROZE five datasets, because a key that cannot tell two rows
apart does not de-duplicate, it deletes: the second row is skipped as "already
held", the run reports success, and the dataset can never grow again.
infrastructure sat at 5,840 rows / 4 keys looking perfectly healthy.

Both failures are the same shape — a guard whose failure mode is silence — so
both are tested here, at the layer where they are cheap to catch:

  * every migrating spec HAS an identity and a max_observations tripwire
    (the eleven specs that had neither are the eleven that doubled)
  * every declared identity is INJECTIVE over what the spec actually emits
    (the check that would have caught the freeze the day it was introduced)
  * a collision allowance is a MEASURED number, never a round one
  * the loader refuses a spec that declares neither

The injectivity test dry-runs the real loader against v1's real corpus, so it
skips where v1 is absent (CI, laptops) — as the other integration tests do.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ingest import databank
from ingest.databank import SPECS, SpecRefused, load_spec

V1 = Path("/opt/stacks/palestine/public/data/unified")
needs_v1 = pytest.mark.skipif(not V1.exists(), reason="v1 corpus absent")


def migrating_specs() -> list[str]:
    out = []
    for p in sorted(SPECS.glob("*.yaml")):
        spec = yaml.safe_load(p.read_text())
        if spec.get("status") == "reviewed" and spec.get("migrate") is not False:
            out.append(p.stem)
    return out


@pytest.mark.parametrize("category", migrating_specs())
def test_every_migrating_spec_declares_identity_and_a_tripwire(category) -> None:
    spec = load_spec(category)          # load_spec itself refuses without them
    has_identity = bool(spec.get("identity")) or any(
        (d.get("overrides") or {}).get("identity")
        for d in spec.get("datasets", []))
    assert has_identity, f"{category}: no identity"
    assert spec["expect"]["max_observations"] > 0


@pytest.mark.parametrize("category", migrating_specs())
def test_identity_fields_are_names_the_loader_knows(category) -> None:
    """A typo'd field name would silently contribute an empty string to every
    key — i.e. a coarser identity than the spec claims, which is the freeze."""
    known = {"indicator", "occurred_at", "occurred_at_exact", "place_id",
             "value_num"}
    spec = load_spec(category)
    idents = [spec.get("identity")] + [
        (d.get("overrides") or {}).get("identity")
        for d in spec.get("datasets", [])]
    for ident in [i for i in idents if i]:
        unknown = set(ident.get("fields", [])) - known
        assert not unknown, f"{category}: unknown identity fields {unknown}"


@pytest.mark.parametrize("category", migrating_specs())
def test_collision_allowances_are_measured_not_round(category) -> None:
    """`allow_collisions: 1000` would be somebody's guess. The declared
    numbers in this project are 1, 4 and 24,550 — each traced to a counted
    upstream fact in the spec's own comment."""
    spec = load_spec(category)
    idents = [spec.get("identity")] + [
        (d.get("overrides") or {}).get("identity")
        for d in spec.get("datasets", [])]
    for ident in [i for i in idents if i]:
        n = ident.get("allow_collisions")
        if n:
            assert n % 100 != 0 or n < 100, \
                f"{category}: allow_collisions={n} looks chosen, not measured"


@needs_v1
@pytest.mark.parametrize("category", migrating_specs())
def test_identity_is_injective_over_what_the_spec_emits(category) -> None:
    """THE INVARIANT. A dry run fails loudly if any dataset's identity maps
    two emitted rows onto one key beyond its declared allowance."""
    report = databank.run(category, dry_run=True)      # raises on collision
    assert report["observations_emitted"] >= 0


def test_loader_refuses_a_spec_with_no_identity(tmp_path, monkeypatch) -> None:
    """Refusal is the behaviour under test, not a side effect."""
    spec = tmp_path / "phantom.yaml"
    spec.write_text("category: phantom\nstatus: reviewed\n"
                    "expect: {min_records: 1, max_observations: 10}\n")
    monkeypatch.setattr(databank, "SPECS", tmp_path)
    with pytest.raises(SpecRefused, match="no `identity:`"):
        load_spec("phantom")


def test_loader_refuses_a_spec_with_no_tripwire(tmp_path, monkeypatch) -> None:
    spec = tmp_path / "phantom.yaml"
    spec.write_text("category: phantom\nstatus: reviewed\n"
                    "identity: {fields: [indicator]}\n"
                    "expect: {min_records: 1}\n")
    monkeypatch.setattr(databank, "SPECS", tmp_path)
    with pytest.raises(SpecRefused, match="max_observations"):
        load_spec("phantom")


def test_one_renderer_for_identity() -> None:
    """The first guard compared a Python-rendered key to a SQL-rendered one;
    106.0 != 106 made it fail OPEN and re-insert 998 of 1,000 rows. There is
    now exactly one renderer, and both the loader and the backfill use it."""
    ident = {"fields": ["indicator", "occurred_at", "value_num"],
             "attrs": ["donor"]}
    k = databank.identity_key_for(
        ident, "ds", indicator="a.b", occurred_at="2026-01-01T00:00:00+00:00",
        place_id=None, value_num=106.0, attrs={"donor": "X"})
    assert k == "ds|a.b|2026-01-01|106.0|X"
    # a missing attr contributes an empty segment, never the string "None"
    k2 = databank.identity_key_for(ident, "ds", indicator="a.b",
                                   occurred_at="2026-01-01", place_id=None,
                                   value_num=None, attrs={})
    assert k2 == "ds|a.b|2026-01-01||"
