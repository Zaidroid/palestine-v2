"""P0.10 — fetcher framework.

The whole point of this file is one rule:

    A fetch that returns nothing, and did not DECLARE that it may return
    nothing, is a FAILURE — not a success with a null count.

v1 has 8 of 37 ETL tasks reporting `status: "ok"` with `records: null`. A no-op
and a success are the same signal there. Here they are structurally different
values, and the framework — not the individual fetcher — decides which one you
got. A fetcher cannot report success it did not earn.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Sequence

import httpx
import yaml

from . import bronze

log = logging.getLogger("ingest")
ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "ingest" / "sources" / "registry.yaml"
STATE_PATH = ROOT / "data" / "bronze" / "_fetch_state.json"

# Identify ourselves to free upstreams we do not pay for. Overpass and several
# OCHA endpoints reject or throttle anonymous clients.
USER_AGENT = "palestine-data-platform/2.0 (+https://github.com/Zaidroid/palestine-data-backend)"


class Status(str, Enum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"        # deliberately not run (cadence, disabled)
    UNCHANGED = "unchanged"    # HTTP 304 / identical content hash


@dataclass
class FetchResult:
    """Outcome of one fetch. There is no state where `status` is OK and
    `records` is None — the constructor forbids it."""
    source_key: str
    status: Status
    records: int | None = None
    reason: str | None = None
    raw_refs: list[str] = field(default_factory=list)
    duration_ms: int = 0
    schema_drift: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if self.status is Status.OK and self.records is None:
            raise ValueError(
                f"{self.source_key}: status=ok requires a record count. "
                "This is the v1 silent-null bug; it is not permitted here."
            )
        if self.status in (Status.FAILED, Status.SKIPPED) and not self.reason:
            raise ValueError(f"{self.source_key}: status={self.status.value} requires a reason")

    def to_dict(self) -> dict:
        return {
            "source": self.source_key, "status": self.status.value,
            "records": self.records, "reason": self.reason,
            "raw_refs": self.raw_refs, "duration_ms": self.duration_ms,
            "schema_drift": self.schema_drift, "started_at": self.started_at,
        }


class SourceContractError(RuntimeError):
    """Raised when a fetch violates its registry contract."""


def load_registry() -> dict[str, dict]:
    if not REGISTRY_PATH.exists():
        return {}
    doc = yaml.safe_load(REGISTRY_PATH.read_text()) or {}
    return {s["key"]: s for s in doc.get("sources", [])}


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1, sort_keys=True))


def schema_fingerprint(records: Sequence[dict]) -> str:
    """Hash of the sorted union of field names — cheap upstream-drift detector."""
    keys: set[str] = set()
    for r in records[:500]:
        if isinstance(r, dict):
            keys.update(r.keys())
    return hashlib.sha256("|".join(sorted(keys)).encode()).hexdigest()[:16]


class BaseFetcher:
    """Subclass and implement `fetch()`. Everything else is handled here.

    Subclasses MUST NOT construct their own FetchResult for the success path —
    return the records and let `run()` judge them against the contract.
    """

    #: registry key; must exist in registry.yaml
    key: str = ""

    def __init__(self, registry: dict[str, dict] | None = None) -> None:
        if not self.key:
            raise ValueError(f"{type(self).__name__} must set `key`")
        reg = registry if registry is not None else load_registry()
        if self.key not in reg:
            raise SourceContractError(
                f"'{self.key}' is not declared in registry.yaml. Every source must "
                "declare its license, attribution and expected record range."
            )
        self.cfg = reg[self.key]
        for req in ("license", "attribution", "expect"):
            if req not in self.cfg:
                raise SourceContractError(f"'{self.key}' registry entry is missing '{req}'")

    # ---- subclass API -------------------------------------------------------

    def fetch(self) -> Iterable[dict]:
        """Return the records. Archive raw payloads with `self.archive(...)`."""
        raise NotImplementedError

    def archive(self, payload: bytes | str, ext: str = "json", **kw) -> str:
        ref = bronze.put(self.key, payload, ext, **kw)
        self._refs.append(ref.ref)
        return ref.ref

    def http_get(self, url: str, *, timeout: float = 30.0, retries: int = 3, **kw) -> httpx.Response:
        """GET with conditional request (ETag/Last-Modified) and backoff.

        A 304 is returned to the caller as-is; raise SkipUnchanged from `fetch()`
        if you want the run to report UNCHANGED.
        """
        state = _load_state().get(self.key, {})
        headers = {"User-Agent": USER_AGENT, **dict(kw.pop("headers", {}))}
        if et := state.get("etag"):
            headers["If-None-Match"] = et
        if lm := state.get("last_modified"):
            headers["If-Modified-Since"] = lm

        last: Exception | None = None
        for attempt in range(retries):
            try:
                r = httpx.get(url, timeout=timeout, headers=headers,
                              follow_redirects=True, **kw)
                if r.status_code < 500:
                    if r.status_code == 200:
                        s = _load_state()
                        s.setdefault(self.key, {}).update({
                            "etag": r.headers.get("ETag"),
                            "last_modified": r.headers.get("Last-Modified"),
                            "fetched_at": datetime.now(timezone.utc).isoformat(),
                        })
                        _save_state(s)
                    return r
                last = RuntimeError(f"HTTP {r.status_code}")
            except Exception as exc:                    # noqa: BLE001 — retry any transport error
                last = exc
            # Full jitter backoff; polite to upstreams we do not pay for.
            time.sleep(min(30.0, (2 ** attempt)) * (0.5 + random.random() / 2))
        raise RuntimeError(f"{self.key}: GET {url} failed after {retries} attempts: {last}")

    def http_post(self, url: str, *, data=None, json_body=None, timeout: float = 60.0,
                  retries: int = 3, **kw) -> httpx.Response:
        """POST with backoff. Used where an API refuses GET (Overpass returns
        406 for a GET without the right Accept negotiation)."""
        headers = {"User-Agent": USER_AGENT, **dict(kw.pop("headers", {}))}
        last: Exception | None = None
        for attempt in range(retries):
            try:
                r = httpx.post(url, data=data, json=json_body, timeout=timeout,
                               headers=headers, follow_redirects=True, **kw)
                if r.status_code < 500:
                    return r
                last = RuntimeError(f"HTTP {r.status_code}")
            except Exception as exc:                    # noqa: BLE001
                last = exc
            time.sleep(min(30.0, (2 ** attempt)) * (0.5 + random.random() / 2))
        raise RuntimeError(f"{self.key}: POST {url} failed after {retries} attempts: {last}")

    # ---- runner -------------------------------------------------------------

    def run(self) -> FetchResult:
        self._refs: list[str] = []
        t0 = time.monotonic()
        expect = self.cfg.get("expect", {}) or {}
        allow_empty = bool(self.cfg.get("allow_empty", False))

        try:
            records = list(self.fetch())
        except SkipUnchanged as exc:
            return FetchResult(self.key, Status.UNCHANGED, records=0, reason=str(exc) or "not modified",
                               raw_refs=self._refs, duration_ms=int((time.monotonic() - t0) * 1000))
        except SkipRun as exc:
            return FetchResult(self.key, Status.SKIPPED, reason=str(exc) or "skipped",
                               raw_refs=self._refs, duration_ms=int((time.monotonic() - t0) * 1000))
        except Exception as exc:                        # noqa: BLE001 — any failure is a failure
            log.exception("%s: fetch raised", self.key)
            return FetchResult(self.key, Status.FAILED, reason=f"{type(exc).__name__}: {exc}",
                               raw_refs=self._refs, duration_ms=int((time.monotonic() - t0) * 1000))

        n = len(records)
        ms = int((time.monotonic() - t0) * 1000)

        # ---- THE CONTRACT ----------------------------------------------------
        if n == 0 and not allow_empty:
            return FetchResult(self.key, Status.FAILED, reason=(
                "returned 0 records and the registry does not set allow_empty. "
                "If empty is legitimate for this source, declare it explicitly."
            ), raw_refs=self._refs, duration_ms=ms)

        lo, hi = expect.get("min_records"), expect.get("max_records")
        if lo is not None and n < lo:
            return FetchResult(self.key, Status.FAILED,
                               reason=f"returned {n} records, below declared min_records={lo}",
                               raw_refs=self._refs, duration_ms=ms)
        if hi is not None and n > hi:
            return FetchResult(self.key, Status.FAILED,
                               reason=f"returned {n} records, above declared max_records={hi} "
                                      "(upstream shape may have changed)",
                               raw_refs=self._refs, duration_ms=ms)

        # ---- schema drift (warn, do not fail) --------------------------------
        drift = None
        fp = schema_fingerprint(records)
        state = _load_state()
        prev = state.get(self.key, {}).get("schema_fp")
        if prev and prev != fp:
            drift = f"{prev} -> {fp}"
            log.warning("%s: upstream schema changed (%s)", self.key, drift)
        state.setdefault(self.key, {})["schema_fp"] = fp
        _save_state(state)

        self.records = records
        return FetchResult(self.key, Status.OK, records=n, raw_refs=self._refs,
                           duration_ms=ms, schema_drift=drift)


class SkipUnchanged(Exception):
    """Raise from fetch() when upstream reports 304 / identical content."""


class SkipRun(Exception):
    """Raise from fetch() when this source should not run now (cadence, disabled)."""
