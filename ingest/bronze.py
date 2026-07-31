"""P0.9 — bronze store: immutable, content-addressed raw payload archive.

Every fetch archives its raw bytes here BEFORE parsing (ARCHITECTURE §3.6
principle 6). That is what makes transforms re-runnable without re-fetching —
the thing v1 cannot do, because it overwrites `all-data.json` in place.

Layout:  data/bronze/<source_key>/<sha256[:2]>/<sha256>.<ext>[.gz]

Content-addressed, so re-fetching unchanged upstream data is a no-op: the same
bytes produce the same ref and nothing is written twice.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRONZE = ROOT / "data" / "bronze"

# Text-ish payloads are gzipped; anything else is stored verbatim.
_COMPRESS = {"json", "ndjson", "csv", "xml", "html", "txt", "geojson", "yaml"}


@dataclass(frozen=True)
class BronzeRef:
    """Pointer to an archived payload. `ref` is what goes in claim.raw_ref."""
    ref: str          # bronze://<source_key>/<sha256>
    path: Path
    sha256: str
    size: int
    existed: bool     # True if this exact content was already archived

    def __str__(self) -> str:
        return self.ref


def _meta_path(p: Path) -> Path:
    return p.with_suffix(p.suffix + ".meta.json")


def put(
    source_key: str,
    payload: bytes | str,
    ext: str = "json",
    *,
    url: str | None = None,
    etag: str | None = None,
    fetched_at: datetime | None = None,
) -> BronzeRef:
    """Archive a payload. Idempotent: identical bytes → identical ref, no rewrite."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if not source_key or "/" in source_key:
        raise ValueError(f"invalid source_key: {source_key!r}")

    digest = hashlib.sha256(payload).hexdigest()
    compress = ext.lower() in _COMPRESS
    name = f"{digest}.{ext}" + (".gz" if compress else "")
    path = BRONZE / source_key / digest[:2] / name

    if path.exists():
        return BronzeRef(f"bronze://{source_key}/{digest}", path, digest, len(payload), True)

    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file then rename — an interrupted fetch must never leave a
    # truncated payload sitting at a content-addressed path that claims to be whole.
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    try:
        if compress:
            with gzip.open(tmp, "wb", compresslevel=6) as fh:
                fh.write(payload)
        else:
            tmp.write_bytes(payload)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)

    _meta_path(path).write_text(json.dumps({
        "source_key": source_key,
        "sha256": digest,
        "size": len(payload),
        "url": url,
        "etag": etag,
        "fetched_at": (fetched_at or datetime.now(timezone.utc)).isoformat(),
        "ext": ext,
    }, ensure_ascii=False, indent=1))

    return BronzeRef(f"bronze://{source_key}/{digest}", path, digest, len(payload), False)


def get(ref: str) -> bytes:
    """Read a payload back by ref. Raises FileNotFoundError if absent."""
    if not ref.startswith("bronze://"):
        raise ValueError(f"not a bronze ref: {ref!r}")
    source_key, digest = ref[len("bronze://"):].split("/", 1)
    d = BRONZE / source_key / digest[:2]
    for p in sorted(d.glob(f"{digest}.*")):
        if p.name.endswith(".meta.json"):
            continue
        return gzip.decompress(p.read_bytes()) if p.suffix == ".gz" else p.read_bytes()
    raise FileNotFoundError(ref)


def stats() -> dict:
    """Per-source archive size, for the pipeline report."""
    out: dict[str, dict] = {}
    if not BRONZE.exists():
        return out
    for src in sorted(BRONZE.iterdir()):
        if not src.is_dir():
            continue
        files = [p for p in src.rglob("*") if p.is_file() and not p.name.endswith(".meta.json")]
        out[src.name] = {"objects": len(files), "bytes": sum(p.stat().st_size for p in files)}
    return out
