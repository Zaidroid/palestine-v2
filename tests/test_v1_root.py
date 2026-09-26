"""P1-C.7 — v1's stack behind ONE setting (V1_ROOT), with a no-v1 mode.

A fresh clone has no /opt/stacks/palestine. Before this, twenty files read the
path directly; now they all go through resolve.db.v1_path(), and V1_ROOT=none
points every v1 path at a directory that does not exist, so each caller's own
"v1 absent" handling runs instead of an import crash."""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from resolve import db

ROOT = Path(__file__).resolve().parent.parent
V1_LITERAL = "/opt/stacks/palestine"

# Modules that read v1 at import time or in their main path (the 17 rewritten).
MODULES = [
    "ops.vault_snapshots", "ops.v1_field_health", "ops.nakba_gazetteer",
    "ops.v1_liveness", "ops.freeze_corpus", "ops.evidence", "ops.press_links",
    "ops.t2_category_audit", "ops.watchdog", "ops.fuel_signal_survey",
    "ops.minimax_alarm", "ops.gap_radar", "ingest.discover_channels",
    "ingest.sources.palhub_loader", "ingest.sources.checkpoints",
    "ingest.databank", "resolve.load_gazetteer",
]


@pytest.fixture
def clean_env(monkeypatch):
    for k in ("V1_ROOT", "PALESTINE_V1_ROOT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(db, "_env", lambda: {})
    return monkeypatch


def test_default_is_the_live_stack(clean_env):
    assert db.v1_root() == Path(V1_LITERAL)
    assert db.v1_path("data", "x.db") == Path(V1_LITERAL) / "data" / "x.db"


def test_relocated_by_one_setting(clean_env, tmp_path):
    clean_env.setenv("V1_ROOT", str(tmp_path))
    assert db.v1_path("public/data/unified") == tmp_path / "public/data/unified"


def test_older_name_still_honoured(clean_env, tmp_path):
    clean_env.setenv("PALESTINE_V1_ROOT", str(tmp_path))
    assert db.v1_root() == tmp_path


def test_env_file_setting_read(monkeypatch, tmp_path):
    for k in ("V1_ROOT", "PALESTINE_V1_ROOT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(db, "_env", lambda: {"V1_ROOT": str(tmp_path)})
    assert db.v1_root() == tmp_path


@pytest.mark.parametrize("word", ["none", "off", "NONE"])
def test_no_v1_mode_points_nowhere(clean_env, word):
    clean_env.setenv("V1_ROOT", word)
    assert db.v1_root() is None
    p = db.v1_path("public", "data", "unified")
    assert p.is_relative_to(db.NO_V1)
    assert not p.exists()


def test_every_v1_reader_imports_without_v1():
    code = ("import importlib, sys\n"
            f"mods = {MODULES!r}\n"
            "bad = []\n"
            "for m in mods:\n"
            "    try:\n"
            "        importlib.import_module(m)\n"
            "    except BaseException as e:\n"
            "        bad.append(f'{m}: {e!r}')\n"
            "print('\\n'.join(bad))\n"
            "sys.exit(1 if bad else 0)\n")
    env = {**os.environ, "V1_ROOT": "none"}
    env.pop("PALESTINE_V1_ROOT", None)
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def test_no_code_reads_the_literal_path():
    """Only resolve/db.py may spell v1's path in code; comments and docstrings
    may still name it for a reader."""
    offenders = []
    for sub in ("ops", "ingest", "resolve", "serve", "cascade", "learn", "analyst", "tests"):
        for f in sorted((ROOT / sub).rglob("*.py")):
            if f.name == "test_v1_root.py" or f == ROOT / "resolve" / "db.py":
                continue
            src = f.read_text(encoding="utf-8")
            if V1_LITERAL not in src:
                continue
            tree = ast.parse(src)
            docs = _docstring_nodes(tree)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and V1_LITERAL in node.value and id(node) not in docs):
                    offenders.append(f"{f.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, offenders
