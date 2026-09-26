"""DATABANK-V13 (audit 2026-09-25, F140): the open-data collection wrote one
file per SOURCE with a licence picked by fetchone(), although licence is
dataset-grained (054) — `hdx` carries CC-BY-4.0 (education) and CC-BY-IGO-3.0
(infrastructure) under one source key. Now one file per licence tuple."""
from __future__ import annotations

import csv
import gzip
import io
import json

from ops import export_open_data as ex


def test_DATABANK_V13_every_file_holds_exactly_the_licence_its_manifest_names(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "OUT", tmp_path)
    ex.export_collection()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    files = manifest["files"]
    hdx = [f for f in files if f["source_key"] == "hdx"]
    assert len(hdx) == 2 and len({f["license_spdx"] for f in hdx}) == 2
    names = [f["file"] for f in files]
    assert len(names) == len(set(names))
    if "license_spdx" in ex.COLUMNS:
        col = ex.COLUMNS.index("license_spdx")
        for f in hdx:
            rows = list(csv.reader(io.StringIO(gzip.decompress(
                (tmp_path / f["file"]).read_bytes()).decode())))[1:]
            assert rows and {r[col] for r in rows} == {f["license_spdx"]}
