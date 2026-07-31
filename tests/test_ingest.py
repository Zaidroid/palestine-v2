"""Gate 0 tests for the ingestion skeleton (P0.9–P0.12).

The load-bearing assertions are the contract ones: they prove the v1
silent-null class of bug cannot be represented in v2.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import bronze
from ingest.framework import (BaseFetcher, FetchResult, SkipRun, SkipUnchanged,
                              SourceContractError, Status, load_registry)

REG = load_registry()
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


# ── bronze ────────────────────────────────────────────────────────────────────
print("--- bronze store ---")
r1 = bronze.put("_selftest", '{"a":1}', "json", url="http://x")
r2 = bronze.put("_selftest", '{"a":1}', "json")
r3 = bronze.put("_selftest", '{"a":2}', "json")
check("identical content -> identical ref", r1.ref == r2.ref)
check("identical content not rewritten", r2.existed is True)
check("different content -> different ref", r1.ref != r3.ref)
check("roundtrip read", bronze.get(r1.ref) == b'{"a":1}')
check("gzip applied to json", r1.path.suffix == ".gz")
check("stats reports objects", bronze.stats().get("_selftest", {}).get("objects", 0) >= 2)


# ── the contract ──────────────────────────────────────────────────────────────
print("--- silent-null contract ---")
try:
    FetchResult("x", Status.OK, records=None)
    check("ok+null records rejected", False, "constructor allowed it")
except ValueError:
    check("ok+null records rejected", True)

try:
    FetchResult("x", Status.FAILED)
    check("failed without reason rejected", False)
except ValueError:
    check("failed without reason rejected", True)

check("ok+0 records is representable", FetchResult("x", Status.OK, records=0).records == 0)


# ── fetchers ──────────────────────────────────────────────────────────────────
print("--- fetcher runner ---")

class Undeclared(BaseFetcher):
    key = "not_in_registry"
    def fetch(self): return []

try:
    Undeclared(REG); check("undeclared source refused", False)
except SourceContractError:
    check("undeclared source refused", True)


class Empty(BaseFetcher):
    key = "ocha_admin"           # expect.min_records=10, allow_empty unset
    def fetch(self): return []

res = Empty(REG).run()
check("empty without allow_empty -> FAILED", res.status is Status.FAILED, res.status.value)
check("failure carries a reason", bool(res.reason))


class TooFew(BaseFetcher):
    key = "ocha_admin"
    def fetch(self): return [{"a": 1}] * 3      # below min_records=10

res = TooFew(REG).run()
check("below min_records -> FAILED", res.status is Status.FAILED, res.status.value)


class TooMany(BaseFetcher):
    key = "v1_checkpoints"       # max_records=2000
    def fetch(self): return [{"a": 1}] * 5000

res = TooMany(REG).run()
check("above max_records -> FAILED", res.status is Status.FAILED, res.status.value)


class EmptyAllowed(BaseFetcher):
    key = "nasa_firms"           # allow_empty: true
    def fetch(self): return []

res = EmptyAllowed(REG).run()
check("empty WITH allow_empty -> OK", res.status is Status.OK and res.records == 0,
      f"{res.status.value}/{res.records}")


class Good(BaseFetcher):
    key = "ocha_admin"
    def fetch(self):
        self.archive('{"ok":true}', "json")
        return [{"name": "x", "pcode": "PS01"}] * 50

res = Good(REG).run()
check("valid fetch -> OK with count", res.status is Status.OK and res.records == 50)
check("raw archived to bronze", len(res.raw_refs) == 1)


class Boom(BaseFetcher):
    key = "ocha_admin"
    def fetch(self): raise RuntimeError("upstream exploded")

res = Boom(REG).run()
check("exception -> FAILED not crash", res.status is Status.FAILED)
check("exception reason captured", "upstream exploded" in (res.reason or ""))


class Unchanged(BaseFetcher):
    key = "ocha_admin"
    def fetch(self): raise SkipUnchanged("304")

check("SkipUnchanged -> UNCHANGED", Unchanged(REG).run().status is Status.UNCHANGED)


class Skipped(BaseFetcher):
    key = "ocha_admin"
    def fetch(self): raise SkipRun("cadence not due")

check("SkipRun -> SKIPPED", Skipped(REG).run().status is Status.SKIPPED)


# ── registry governance ───────────────────────────────────────────────────────
print("--- registry governance ---")
check("every source declares license+attribution+expect",
      all(all(k in v for k in ("license", "attribution", "expect")) for v in REG.values()))
check("every license declares commercial_use",
      all("commercial_use" in v["license"] for v in REG.values()))
check("ACLED is marked non-commercial (loop-only)",
      REG["acled"]["license"]["commercial_use"] is False)
check("B'Tselem is marked non-commercial", REG["btselem"]["license"]["commercial_use"] is False)


# ── report ────────────────────────────────────────────────────────────────────
print("--- pipeline report ---")
from ops.pipeline_report import build      # noqa: E402
rep = build([FetchResult("a", Status.OK, records=5),
             FetchResult("b", Status.FAILED, reason="boom")])
check("report counts ok/failed", rep["summary"]["ok"] == 1 and rep["summary"]["failed"] == 1)
try:
    bad = FetchResult("c", Status.OK, records=0); bad.records = None   # force the v1 shape
    build([bad]); check("report refuses silent null", False)
except ValueError:
    check("report refuses silent null", True)


# ── cleanup + summary ─────────────────────────────────────────────────────────
import shutil
shutil.rmtree(bronze.BRONZE / "_selftest", ignore_errors=True)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
