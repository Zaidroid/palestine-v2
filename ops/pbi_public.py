"""A small client for Power BI "publish to web" reports — the only door OCHA
oPt leaves open to its casualty and demolition registers.

WHY THIS EXISTS. v1 read these two reports by driving a headless Chromium
through the embed and recording the JSON the page happened to request
(`scripts/utils/browser-fetch.js`). When v1's image lost the `playwright`
package the two steps began failing in 0 s every night (31 nights by
2026-09-25) and nothing paged. The browser was never needed: a publish-to-web
report is served by a public, key-in-the-URL API that answers plain HTTP —

  GET  {cluster}/public/reports/{key}/modelsAndExploration   model + report ids
  POST {cluster}/public/reports/conceptualschema             entities, columns
  POST {cluster}/public/reports/querydata?synchronous=true   a semantic query

with the resource key (the `k` inside the embed's base64 `r=` parameter) as
the `X-PowerBI-ResourceKey` header. That is the same request the embed makes;
we write the query ourselves instead of hoping the page issues the one we
need, so a report redesign that moves a chart no longer changes what we read.

WHAT A QUERY RETURNS. Power BI's "DSR" envelope, delta-compressed: the first
row declares its schema in `S`; `R` is a bitmask of columns repeated from the
previous row, `Ø` a bitmask of nulls, `C` the remaining values in order, and a
column whose schema carries `DN` stores an index into `ValueDicts[DN]`.
`decode_dsr` undoes all four. A result the service marks incomplete (no `IC`,
or restart tokens present) is REFUSED rather than read short: a truncated
aggregate is a smaller number, not a missing one, and nothing downstream can
tell the difference.

No key, no account, no licence to accept: this is the public embed OCHA
publishes on ochaopt.org. The data's terms are the source row's, not this
module's.
"""
from __future__ import annotations

import base64
import gzip
import json
import re
import urllib.request

UA = "palestine-v2 databank (zsalem33@gmail.com)"

# The cluster the OCHA tenant's reports are served from, measured 2026-09-25
# from the embed page's `resolvedClusterUri`. Resolved again on every run
# (resolve_cluster); this is only the answer when the page cannot be read.
DEFAULT_CLUSTER = "https://wabi-north-europe-j-primary-api.analysis.windows.net"


class PbiError(Exception):
    """The report answered, but not with something we can trust."""


def resource_key(embed_url: str) -> str:
    """The `k` inside an embed URL's base64 `r=` parameter."""
    m = re.search(r"[?&]r=([A-Za-z0-9_\-=%]+)", embed_url)
    if not m:
        raise PbiError(f"no r= parameter in {embed_url!r}")
    raw = m.group(1).replace("%3D", "=")
    raw += "=" * (-len(raw) % 4)
    return json.loads(base64.b64decode(raw))["k"]


def _read(resp) -> bytes:
    body = resp.read()
    return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body


def _open(req, timeout):
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return _read(r)


def cluster_from_embed_html(html: str) -> str | None:
    """The API host the embed page itself would call ('-redirect' → '-api')."""
    m = re.search(r"resolvedClusterUri\s*=\s*'(https://[^']+)'", html)
    if not m:
        return None
    host = m.group(1).rstrip("/")
    return host.replace("-redirect.", "-api.")


def resolve_cluster(embed_url: str, timeout: int = 60, opener=_open) -> str:
    try:
        html = opener(urllib.request.Request(
            embed_url, headers={"User-Agent": UA}), timeout).decode(
                "utf-8", "replace")
        return cluster_from_embed_html(html) or DEFAULT_CLUSTER
    except OSError:
        return DEFAULT_CLUSTER


class Report:
    """One publish-to-web report: its model id, dataset id, report id."""

    def __init__(self, embed_url: str, *, timeout: int = 120, opener=_open):
        self.embed_url = embed_url
        self.key = resource_key(embed_url)
        self.timeout = timeout
        self._open = opener
        self.cluster = resolve_cluster(embed_url, timeout, opener)
        meta = json.loads(self._get(
            f"/public/reports/{self.key}/modelsAndExploration"
            "?preferReadOnlySession=true"))
        model = meta["models"][0]
        self.model_id = model["id"]
        self.dataset_id = model["dbName"]
        self.last_refresh = model.get("LastRefreshTime")
        self.report_id = meta["exploration"]["report"]["objectId"]
        # Every raw answer this report gave, in order — the fetcher archives
        # them in bronze so a transform can be re-run without re-fetching.
        self.raw: list[tuple[str, bytes]] = [("modelsAndExploration",
                                               json.dumps(meta).encode())]

    def _headers(self, json_body: bool = False) -> dict:
        h = {"X-PowerBI-ResourceKey": self.key, "User-Agent": UA}
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def _get(self, path: str) -> bytes:
        return self._open(urllib.request.Request(
            self.cluster + path, headers=self._headers()), self.timeout)

    def query(self, name: str, entity: str, select: list[dict],
              where: list[dict] | None = None, window: int = 30000) -> dict:
        """Run one semantic query; return {'columns': [...], 'rows': [...]}."""
        q = {"Version": 2,
             "From": [{"Name": "v", "Entity": entity, "Type": 0}],
             "Select": select}
        if where:
            q["Where"] = where
        body = {"version": "1.0.0", "queries": [{
            "Query": {"Commands": [{"SemanticQueryDataShapeCommand": {
                "Query": q,
                "Binding": {
                    "Primary": {"Groupings": [
                        {"Projections": list(range(len(select)))}]},
                    "DataReduction": {"DataVolume": 4,
                                      "Primary": {"Window": {"Count": window}}},
                    "Version": 1},
                "ExecutionMetricsKind": 1}}]},
            "QueryId": "",
            "ApplicationContext": {
                "DatasetId": self.dataset_id,
                "Sources": [{"ReportId": self.report_id, "VisualId": ""}]}}],
            "cancelQueries": [], "modelId": self.model_id}
        raw = self._open(urllib.request.Request(
            self.cluster + "/public/reports/querydata?synchronous=true",
            data=json.dumps(body).encode(), headers=self._headers(True)),
            self.timeout)
        self.raw.append((name, raw))
        return parse_querydata(json.loads(raw),
                               [s.get("Name", f"c{i}") for i, s in
                                enumerate(select)])


# ── query building blocks ────────────────────────────────────────────────────

def col(prop: str, name: str | None = None) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Source": "v"}},
                       "Property": prop}, "Name": name or prop}


def group(prop: str, base: str, name: str | None = None) -> dict:
    """A report-defined group ('SA (groups)') over its base column."""
    return {"GroupRef": {"Expression": {"SourceRef": {"Source": "v"}},
                         "Property": prop,
                         "GroupedColumns": [{"Column": {
                             "Expression": {"SourceRef": {"Source": "v"}},
                             "Property": base}}]},
            "Name": name or prop}


def agg(prop: str, fn: int = 0, name: str | None = None) -> dict:
    """fn: 0 sum, 1 avg, 2 count, 3 min, 4 max, 5 count-not-null."""
    return {"Aggregation": {"Expression": {"Column": {
        "Expression": {"SourceRef": {"Source": "v"}}, "Property": prop}},
        "Function": fn}, "Name": name or f"agg{fn}({prop})"}


def not_in(prop: str, literals: list[str]) -> dict:
    """WHERE prop NOT IN (…) — literals in Power BI's own spelling
    ("null", "'Eviction'")."""
    return {"Condition": {"Not": {"Expression": {"In": {
        "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "v"}},
                                    "Property": prop}}],
        "Values": [[{"Literal": {"Value": v}}] for v in literals]}}}}}


# ── the DSR envelope ─────────────────────────────────────────────────────────

def decode_dsr(ds: dict) -> list[list]:
    """Flatten one DSR data set into rows, undoing R/Ø/ValueDicts.

    Written against the envelope's documented behaviour and pinned by the
    fixtures in tests/fixtures/supply_lines/ — every rule below is exercised
    there by a real answer from OCHA's reports.
    """
    dicts = ds.get("ValueDicts") or {}
    rows: list[list] = []
    schema: list[dict] | None = None
    prev: list | None = None
    for ph in ds.get("PH") or []:
        for _, members in sorted(ph.items()):
            for r in members:
                if "S" in r:
                    schema = r["S"]
                if schema is None:
                    raise PbiError("row before any schema")
                rmask, nmask = r.get("R", 0), r.get("Ø", 0)
                # A row either lists its values positionally in `C`, or —
                # for an ungrouped aggregate — keys each one by its column
                # name ({"S": [{"N": "M0"}], "M0": 1790121600000}).
                values = iter(r["C"]) if "C" in r else None
                row = []
                for i, c in enumerate(schema):
                    if rmask >> i & 1:
                        if prev is None:
                            raise PbiError("repeat bit on the first row")
                        v = prev[i]
                    elif nmask >> i & 1:
                        v = None
                    else:
                        if values is None:
                            if c["N"] not in r:
                                raise PbiError(f"no value for {c['N']}")
                            v = r[c["N"]]
                        else:
                            try:
                                v = next(values)
                            except StopIteration:
                                raise PbiError("row shorter than its schema")
                        if "DN" in c and isinstance(v, int):
                            v = dicts[c["DN"]][v]
                    row.append(v)
                rows.append(row)
                prev = row
    return rows


def parse_querydata(payload: dict, names: list[str]) -> dict:
    try:
        result = payload["results"][0]["result"]
    except (KeyError, IndexError, TypeError):
        raise PbiError(f"no result in the answer: {str(payload)[:200]}")
    if "error" in result or "data" not in result:
        raise PbiError(f"the service refused the query: "
                       f"{json.dumps(result.get('error') or result)[:300]}")
    dsr = result["data"]["dsr"]
    if dsr.get("DataShapes"):                      # the service's own error
        raise PbiError(f"data shape error: {json.dumps(dsr['DataShapes'])[:300]}")
    ds = dsr["DS"][0]
    if not ds.get("IC") or ds.get("RT"):
        # Incomplete: the window cut the answer. Refuse — see the docstring.
        raise PbiError("the answer is incomplete (IC false / restart tokens) "
                       "— refusing a truncated aggregate")
    return {"columns": names, "rows": decode_dsr(ds)}
