"""P5.3 — the cap that stands between the open internet and the database.

    ./.venv/bin/python -m pytest tests/test_ratelimit.py -q

A rate limiter fails in two directions and both are bad. Too loose and one
script makes the API useless for someone trying to find out whether a road is
open. Too tight — or wrong about who the caller is — and it refuses the people
it exists to serve, or refuses our own monitoring and then reports the system as
unhealthy.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve import ratelimit as rl                                # noqa: E402


class Req:
    def __init__(self, headers=None, host="127.0.0.1"):
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.client = type("C", (), {"host": host})()


def setup_function():
    for b in rl._buckets.values():
        b.clear()


# ── who the caller is ────────────────────────────────────────────────────────

def test_the_client_is_the_cloudflare_header_not_the_socket():
    """Behind the tunnel every connection arrives from localhost. Using the
    socket address would put the entire internet in one bucket and rate-limit
    the planet as a single visitor."""
    assert rl.client_ip(Req({"CF-Connecting-IP": "203.0.113.7"})) == "203.0.113.7"


def test_x_forwarded_for_uses_the_LAST_hop():
    """A client can prepend anything it likes to X-Forwarded-For. Only the last
    entry was added by infrastructure we control."""
    assert rl.client_ip(Req({"X-Forwarded-For": "1.2.3.4, 203.0.113.7"})) == "203.0.113.7"


def test_cloudflare_header_wins_over_a_forgeable_one():
    r = Req({"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": "9.9.9.9"})
    assert rl.client_ip(r) == "203.0.113.7"


def test_local_callers_are_exempt():
    """The MCP server, the watchdog and /health all call over localhost.
    Limiting our own health checks means the monitoring trips the limit and
    then reports the system as unhealthy."""
    for _ in range(500):
        ok, _ = rl.check("127.0.0.1", "read")
        assert ok


# ── the cap itself ───────────────────────────────────────────────────────────

def test_a_visitor_is_allowed_the_limit_then_refused():
    limit, _ = rl.LIMITS["read"]
    for i in range(limit):
        ok, _ = rl.check("203.0.113.1", "read")
        assert ok, f"honest request {i + 1} was refused"
    ok, retry = rl.check("203.0.113.1", "read")
    assert not ok and retry > 0, "a refusal must say when to come back"


def test_visitors_are_independent():
    """One scraper must not lock out everyone else — the failure that would
    make this worse than having no limiter at all."""
    limit, _ = rl.LIMITS["register"]
    for _ in range(limit + 3):
        rl.check("203.0.113.2", "register")
    ok, _ = rl.check("203.0.113.3", "register")
    assert ok


def test_the_window_slides_rather_than_resetting_on_the_hour():
    """A fixed window lets a caller send a full allowance at 11:59:59 and
    another at 12:00:00 — double the limit at exactly the moment a burst hurts.
    """
    limit, window = rl.LIMITS["write"]
    t = 1000.0
    for _ in range(limit):
        assert rl.check("203.0.113.4", "write", now=t)[0]
    assert not rl.check("203.0.113.4", "write", now=t + 1)[0]
    # Once the oldest hit ages out, exactly one slot frees up.
    assert rl.check("203.0.113.4", "write", now=t + window + 0.1)[0]


def test_writes_are_tighter_than_reads_and_registration_tightest():
    """Reading is the point of the system; creating an account is the cheapest
    thing to automate and the most expensive to undo, because every one is a row
    that stays forever under the retention rule."""
    assert rl.LIMITS["register"][0] < rl.LIMITS["write"][0] < rl.LIMITS["read"][0]


# ── routing requests to the right class ──────────────────────────────────────

def test_registration_is_classified_strictly():
    assert rl.classify("/v2/crowd/register", "POST") == "register"


def test_a_crowd_report_is_a_write_not_a_registration():
    assert rl.classify("/v2/crowd/report", "POST") == "write"


def test_reads_and_preflight_are_reads():
    for m in ("GET", "HEAD", "OPTIONS"):
        assert rl.classify("/v2/fuel/nearby", m) == "read"


def test_the_stream_is_a_read():
    """A long-lived SSE connection is one request. Classifying it as a write
    would let twenty phones exhaust the write budget by watching."""
    assert rl.classify("/v2/stream", "GET") == "read"


# ── it must not become the leak it prevents ──────────────────────────────────

def test_tracking_is_bounded():
    """An unbounded dict keyed by attacker-chosen addresses is a memory
    exhaustion bug inside the thing meant to prevent one."""
    for i in range(rl.MAX_TRACKED + 200):
        rl.check(f"198.51.100.{i}", "read")
    assert len(rl._buckets["read"]) <= rl.MAX_TRACKED


def test_eviction_drops_the_oldest_first():
    rl.check("203.0.113.10", "read")
    for i in range(rl.MAX_TRACKED + 5):
        rl.check(f"198.51.100.{i}", "read")
    assert "203.0.113.10" not in rl._buckets["read"]
