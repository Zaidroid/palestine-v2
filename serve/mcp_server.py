"""MCP server — one surface for Fawwaz, Sameera, Claude, or any agent.

    ./.venv/bin/python -m serve.mcp_server            # stdio (agent spawns it)

Speaks MCP over stdio with no SDK dependency — the protocol is small, and a
hand-rolled server has no version drift with whatever hermes ships.

DESIGN FOR A VOICE BOT
Every tool returns a short `answer` string in Arabic AND the structured data.
A voice assistant can read `answer` aloud verbatim; a UI can use the rest. That
keeps the phrasing — especially how uncertainty is expressed — in one place
rather than re-invented by each agent.

UNCERTAINTY IS SPOKEN, NOT DROPPED
When a reading has decayed the answer says so ("آخر تحديث قبل ساعتين") instead
of asserting a stale value. For fuel during a shortage that difference is a
wasted tank of petrol; for a checkpoint it can be worse. The serving layer
already refuses to assert stale state — this makes sure the voice layer repeats
the caveat rather than smoothing it away.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from psycopg.rows import dict_row

from resolve.db import dsn
from resolve.geo import resolve_place

PROTOCOL = "2024-11-05"
FUEL_AR = {"fuel_diesel": "سولار", "fuel_gasoline": "بنزين", "cooking_gas": "غاز"}


def q(sql: str, params: tuple = ()) -> list[dict]:
    with psycopg.connect(dsn(), row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _age_ar(minutes: int | None) -> str:
    if minutes is None:
        return "غير معروف"
    if minutes < 60:
        return f"قبل {int(minutes)} دقيقة"
    if minutes < 1440:
        return f"قبل {int(minutes // 60)} ساعة"
    return f"قبل {int(minutes // 1440)} يوم"


# ── tools ────────────────────────────────────────────────────────────────────

def fuel_near(place: str | None = None, lat: float | None = None,
              lon: float | None = None, fuel: str = "diesel", limit: int = 5) -> dict:
    """Where can I get diesel/petrol right now?"""
    kind = {"diesel": "fuel_diesel", "سولار": "fuel_diesel",
            "gasoline": "fuel_gasoline", "petrol": "fuel_gasoline",
            "بنزين": "fuel_gasoline", "gas": "cooking_gas", "غاز": "cooking_gas"
            }.get(fuel.lower(), "fuel_diesel")

    if lat is None or lon is None:
        if not place:
            return {"error": "need either place or lat/lon"}
        r = resolve_place(place, learn=False)
        if not r:
            return {"answer": f"ما عرفت وين {place}", "error": "place not resolved"}
        row = q("SELECT ST_Y(centroid::geometry) la, ST_X(centroid::geometry) lo "
                "FROM place WHERE place_id=%s", (r.place_id,))[0]
        lat, lon, place = row["la"], row["lo"], (r.name_ar or r.name_en or place)

    rows = q("""
        SELECT s.name_ar, s.name_en, s.value, s.confidence, s.age_minutes,
               s.staleness_band, s.last_known_value,
               p.attrs->>'geo_precision' AS geo_precision,
               p.source_refs->>'palhub_region' AS region,
               ST_Distance(s.centroid, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography)/1000 km
        FROM state_serving s JOIN place p ON p.place_id=s.place_id
        WHERE s.state_kind=%s AND s.value='available'
        ORDER BY km ASC LIMIT %s""", (lon, lat, kind, limit))

    label = FUEL_AR.get(kind, kind)
    if not rows:
        total = q("SELECT COUNT(*) n FROM state_serving WHERE state_kind=%s", (kind,))[0]["n"]
        answer = (f"ما في ولا محطة فيها {label} حالياً حسب آخر تحديث "
                  f"(تم فحص {total} محطة).")
    else:
        parts = []
        for r in rows[:3]:
            nm = r["name_ar"] or r["name_en"]
            approx = "" if (r["geo_precision"] or "station") in ("station", "town") \
                else " (الموقع تقريبي)"
            parts.append(f"{nm} على بعد {r['km']:.0f} كم{approx}")
        answer = (f"في {len(rows)} محطة فيها {label}: " + "، ".join(parts) +
                  f". آخر تحديث {_age_ar(rows[0]['age_minutes'])}.")

    return {
        "answer": answer,
        "fuel": label, "origin": place or f"{lat:.4f},{lon:.4f}",
        "count": len(rows),
        "stations": [{
            "name": r["name_ar"] or r["name_en"], "region": r["region"],
            "distance_km": round(r["km"], 1), "value": r["value"],
            "confidence": round(float(r["confidence"]), 2),
            "age_minutes": r["age_minutes"], "staleness_band": r["staleness_band"],
            "location_precise": (r["geo_precision"] or "station") in ("station", "town"),
        } for r in rows],
        "source": "Palhub - احوال الوقود (Telegram)",
    }


def fuel_summary() -> dict:
    rows = q("""SELECT state_kind,
                       COUNT(*) FILTER (WHERE value='available') avail, COUNT(*) total
                FROM state_serving WHERE state_kind LIKE 'fuel%%' GROUP BY 1""")
    fresh = q("SELECT MAX(observed_at) t FROM state_current WHERE state_kind LIKE 'fuel%%'")[0]["t"]
    age = None
    if fresh:
        age = int((datetime.now(timezone.utc) - fresh).total_seconds() // 60)
    bits = [f"{FUEL_AR.get(r['state_kind'], r['state_kind'])}: {r['avail']} من {r['total']} محطة"
            for r in rows]
    return {"answer": "وضع الوقود بالضفة — " + "، ".join(bits) + f". آخر تحديث {_age_ar(age)}.",
            "totals": {r["state_kind"]: {"available": r["avail"], "total": r["total"]} for r in rows},
            "feed_age_minutes": age,
            "source": "Palhub - احوال الوقود (Telegram)"}


def latest_news(area: str | None = None, limit: int = 8) -> dict:
    """Most recent messages, optionally filtered to an area."""
    if area:
        rows = q("""
            SELECT c.raw_text, c.reported_at, s.name AS src
            FROM claim c JOIN source s ON s.source_id=c.source_id
            WHERE c.raw_text ILIKE %s AND length(c.raw_text) > 30
            ORDER BY c.reported_at DESC LIMIT %s""", (f"%{area}%", limit))
    else:
        rows = q("""
            SELECT c.raw_text, c.reported_at, s.name AS src
            FROM claim c JOIN source s ON s.source_id=c.source_id
            WHERE length(c.raw_text) > 30
            ORDER BY c.reported_at DESC LIMIT %s""", (limit,))
    if not rows:
        return {"answer": f"ما في أخبار جديدة عن {area}." if area else "ما في أخبار جديدة.",
                "items": []}
    head = " ".join(rows[0]["raw_text"].split())[:180]
    return {"answer": f"آخر خبر: {head}",
            "count": len(rows),
            "items": [{"text": " ".join(r["raw_text"].split())[:400],
                       "source": r["src"], "at": r["reported_at"].isoformat()} for r in rows]}


def coverage() -> dict:
    """What this system currently knows — so an agent can answer honestly."""
    src = q("""SELECT s.name, s.key, COUNT(c.*) claims, MAX(c.reported_at) newest
               FROM source s LEFT JOIN claim c ON c.source_id=s.source_id
               GROUP BY 1,2 HAVING COUNT(c.*)>0 ORDER BY 3 DESC""")
    st = q("""SELECT state_kind, COUNT(*) n FROM state_serving GROUP BY 1 ORDER BY 2 DESC""")
    pl = q("""SELECT kind::text, COUNT(*) n FROM place GROUP BY 1 ORDER BY 2 DESC""")
    return {"answer": f"عندي {sum(r['claims'] for r in src)} رسالة من {len(src)} مصدر، "
                      f"و{sum(r['n'] for r in st)} حالة مباشرة.",
            "sources": [{"name": r["name"], "claims": r["claims"],
                         "newest": r["newest"].isoformat() if r["newest"] else None} for r in src],
            "live_states": {r["state_kind"]: r["n"] for r in st},
            "places": {r["kind"]: r["n"] for r in pl}}


TOOLS = {
    "fuel_near": (fuel_near, "Which stations have diesel/petrol right now, nearest first. "
                             "Give `place` (Arabic or English name) or lat/lon.",
                  {"type": "object", "properties": {
                      "place": {"type": "string", "description": "e.g. نابلس, Ramallah"},
                      "lat": {"type": "number"}, "lon": {"type": "number"},
                      "fuel": {"type": "string", "enum": ["diesel", "gasoline", "gas"]},
                      "limit": {"type": "integer"}}}),
    "fuel_summary": (fuel_summary, "West-Bank-wide fuel availability totals.",
                     {"type": "object", "properties": {}}),
    "latest_news": (latest_news, "Most recent ingested messages, optionally filtered by area.",
                    {"type": "object", "properties": {
                        "area": {"type": "string"}, "limit": {"type": "integer"}}}),
    "coverage": (coverage, "What sources and data this system currently holds.",
                 {"type": "object", "properties": {}}),
}


# ── MCP stdio loop ───────────────────────────────────────────────────────────

def _reply(rid: Any, result: dict) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result},
                                ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error(rid: Any, code: int, msg: str) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid,
                                 "error": {"code": code, "message": msg}},
                                ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, rid = req.get("method"), req.get("id")

        if method == "initialize":
            _reply(rid, {"protocolVersion": PROTOCOL,
                         "capabilities": {"tools": {}},
                         "serverInfo": {"name": "palestine-v2", "version": "2.0.0"}})
        elif method == "tools/list":
            _reply(rid, {"tools": [{"name": n, "description": d, "inputSchema": s}
                                   for n, (_, d, s) in TOOLS.items()]})
        elif method == "tools/call":
            p = req.get("params", {})
            name = p.get("name")
            if name not in TOOLS:
                _error(rid, -32602, f"unknown tool: {name}")
                continue
            try:
                out = TOOLS[name][0](**(p.get("arguments") or {}))
            except Exception as exc:                    # noqa: BLE001
                out = {"error": str(exc), "answer": "صار خطأ بالنظام."}
            _reply(rid, {"content": [{"type": "text",
                                      "text": json.dumps(out, ensure_ascii=False, default=str)}]})
        elif method in ("notifications/initialized", "initialized"):
            continue
        elif rid is not None:
            _error(rid, -32601, f"method not found: {method}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
