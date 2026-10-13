"""Check the hand-edited names of Peace Now's settlement series and write them
where the registry loader reads them.

db/reference/peacenow_settlement_names.yaml is the file a person edits: one
entry per settlement that has a population figure, with Peace Now's DB_ID, the
name as its sheet writes it, the Arabic spelling and where that spelling was
printed. This step refuses a table that could not be stood behind (an id or a
name used twice, an Arabic name with Latin or Hebrew letters in it, a source
it does not know, a `printed` form that differs from the name by more than a
hamza) and writes one {en, ar} pair per series, by the table's one rule, into
the marked block of db/registry/names.yaml. No network. Deterministic: the
same table gives the same bytes.

  .venv/bin/python -m ops.build_settlement_names           # check and write
  .venv/bin/python -m ops.build_settlement_names --check   # check only: exit 1
                                                           #   if names.yaml is
                                                           #   not what the
                                                           #   table says
  .venv/bin/python -m ops.build_settlement_names --list    # id | English |
                                                           #   Arabic | basis

It is not part of the nightly: names.yaml is a committed, reviewed file, and
ops/load_registry.py reads it as it stands. tests/test_more_settlements.py
runs the check, so the two files cannot drift apart unnoticed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops.fetch_peacenow_settlements import indicator_of      # noqa: E402

SRC = ROOT / "db" / "reference" / "peacenow_settlement_names.yaml"
NAMES = ROOT / "db" / "registry" / "names.yaml"
BEGIN = ("  # >>> settlements.population_by_settlement.pn<DB_ID>: written by "
         "ops/build_settlement_names.py from\n"
         "  #     db/reference/peacenow_settlement_names.yaml. Edit that table, "
         "not this block.\n")
END = "  # <<< settlements.population_by_settlement.pn<DB_ID>\n"

# `from` -> how the report and a reader should hear it
FROM = {
    "arij": "printed: ARIJ 2023",
    "arwiki": "printed: Arabic Wikipedia (article title)",
    "arwiki_list": "printed: Arabic Wikipedia (list of settlements)",
    "ips": "printed: Institute for Palestine Studies",
    "watan": "printed: Dunia Al-Watan 2018",
    "city": "printed: the Arabic name of the city the row is inside",
    "transliterated": "transliterated",
}
_ARABIC_NAME = re.compile(r"^[ء-ي ()]+$")
_HAMZA = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا"})


def load(path: Path | None = None) -> dict:
    return yaml.safe_load((path or SRC).read_text(encoding="utf-8"))


def basis(entry: dict) -> str:
    """The fourth column: where the Arabic spelling comes from."""
    text = FROM[entry["from"]]
    return text + ", hamza added" if entry.get("printed") else text


def check(table: dict) -> list[str]:
    out: list[str] = []
    rule = table.get("rule") or {}
    if "{name}" not in str(rule.get("en")) or "{ar}" not in str(rule.get("ar")):
        out.append("rule: en needs {name} and ar needs {ar}")
    seen_id: dict = {}
    seen_name: dict = {}
    seen_ar: dict = {}
    for i, e in enumerate(table.get("settlements") or []):
        where = f"settlements[{i}] ({e.get('name')!r})"
        sid = e.get("id")
        if not isinstance(sid, int) or isinstance(sid, bool) or sid <= 0:
            out.append(f"{where}: id must be Peace Now's DB_ID, a whole number")
            continue
        for seen, key, what in ((seen_id, sid, "id"), (seen_name, e.get("name"), "name"),
                                (seen_ar, e.get("ar"), "Arabic name")):
            if key in seen:
                out.append(f"{where}: {what} {key!r} is also on {seen[key]}")
            seen[key] = where
        name, ar = e.get("name"), e.get("ar")
        if not isinstance(name, str) or not name.strip() or name != " ".join(name.split()):
            out.append(f"{where}: name must be the sheet's name, whitespace clean")
        if not isinstance(ar, str) or not _ARABIC_NAME.match(ar) or ar != " ".join(ar.split()):
            out.append(f"{where}: ar must be Arabic letters, spaces and brackets only, got {ar!r}")
        if e.get("from") not in FROM:
            out.append(f"{where}: from {e.get('from')!r} is not one of {sorted(FROM)}")
        whole = e.get("whole")
        if whole is not None and not (isinstance(whole, dict) and set(whole) == {"en", "ar"}
                                      and all(isinstance(v, str) and v.strip() for v in whole.values())):
            out.append(f"{where}: `whole` must be {{en: ..., ar: ...}}, the series' whole name")
        printed = e.get("printed")
        if printed is not None:
            if e.get("from") != "arij":
                out.append(f"{where}: `printed` is for ARIJ's own letters only")
            elif printed == ar or str(printed).translate(_HAMZA) != str(ar).translate(_HAMZA):
                out.append(f"{where}: `printed` {printed!r} differs from {ar!r} by more than a hamza")
    return out


def series_names(table: dict) -> dict[str, dict]:
    """indicator -> {en, ar}, by the table's rule, in DB_ID order."""
    rule = table["rule"]
    return {indicator_of(e["id"]): (dict(e["whole"]) if e.get("whole") else
                                    {"en": rule["en"].format(name=e["name"]),
                                     "ar": rule["ar"].format(ar=e["ar"])})
            for e in sorted(table["settlements"], key=lambda e: e["id"])}


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def block(table: dict) -> str:
    lines = [BEGIN]
    for ind, n in series_names(table).items():
        lines.append(f"  {ind}:\n    en: {_q(n['en'])}\n    ar: {_q(n['ar'])}\n")
    lines.append(END)
    return "".join(lines)


def placed(text: str, new: str) -> str:
    """names.yaml with its marked block replaced by `new`."""
    a, b = text.find(BEGIN), text.find(END)
    if a < 0 or b < a:
        raise SystemExit(f"{NAMES.name}: the marked block is missing; put these two "
                         f"comment lines under `names:` and run again:\n{BEGIN}{END}")
    return text[:a] + new + text[b + len(END):]


def listing(table: dict) -> list[tuple[int, str, str, str]]:
    names = series_names(table)
    return [(e["id"], names[indicator_of(e["id"])]["en"], names[indicator_of(e["id"])]["ar"],
             basis(e)) for e in sorted(table["settlements"], key=lambda e: e["id"])]


def main(argv: list[str]) -> int:
    table = load()
    problems = check(table)
    for p in problems:
        print(f"REFUSED  {p}")
    if problems:
        return 1
    if "--list" in argv:
        for sid, en, ar, how in listing(table):
            print(f"{sid} | {en} | {ar} | {how}")
        return 0
    text = NAMES.read_text(encoding="utf-8")
    want = placed(text, block(table))
    n = len(table["settlements"])
    if want == text:
        print(f"settlement names: {n} series, {NAMES.name} is what the table says")
        return 0
    if "--check" in argv:
        print(f"settlement names: {NAMES.name} is NOT what the table says; run "
              "python -m ops.build_settlement_names")
        return 1
    NAMES.write_text(want, encoding="utf-8")
    print(f"settlement names: {n} series written to {NAMES.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
