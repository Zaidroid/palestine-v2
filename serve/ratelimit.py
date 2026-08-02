"""A cap on how much one visitor can ask for, so nobody can spoil it for everyone.

Without this, one script — malicious or just badly written — can hold every
worker busy and make the API useless for the people it exists for. That matters
more here than for most services, because the thing being denied is somebody
trying to find out whether a road is open.

THREE CLASSES, BECAUSE THE COSTS ARE NOT ALIKE

  read      generous. Reading is cheap, it is the point of the system, and
            being stingy here would push a frontend into caching badly.
  write     moderate. A crowd report costs a database write and it is a claim
            somebody has to live with, but a person standing in a queue may
            genuinely report several times.
  register  strict. Creating an account is the cheapest thing to automate and
            the most expensive to undo, since every registration is a row that
            stays forever under the retention rule.

Registration being open is a deliberate choice and it is safe for a reason that
is structural rather than procedural: every unverified submitter shares ONE
independence unit and scores 0.85 x 0.20 = 0.17, below every confidence floor.
A thousand sign-ups carry the weight of one anonymous stranger. So the limit
here is about disk and noise, not about trust — the trust question was already
answered by the architecture.

THE CLIENT IP IS NOT THE SOCKET
Behind Cloudflare every connection arrives from the tunnel on localhost. Using
the socket address would put the whole internet in one bucket and rate-limit
the planet as a single visitor. `CF-Connecting-IP` is the real client, and it is
trusted ONLY because nothing but the tunnel can reach the port — the API binds
to 127.0.0.1, so a forged header cannot arrive from outside.

LOCAL CALLERS ARE EXEMPT
The MCP server, the watchdog and /health all call this API over localhost. Rate
limiting our own health checks would mean the monitoring trips the limit and
then reports the system as unhealthy.
"""
from __future__ import annotations

import time
from collections import OrderedDict

# requests, per seconds. Chosen to be invisible to any honest use — a phone
# refreshing a map, a frontend loading twenty endpoints, an agent working
# through a question — and to bite a scraper immediately.
LIMITS = {
    "read":     (120, 60),      # 2/second sustained
    "write":    (20, 60),
    "register": (3, 3600),      # three accounts an hour from one address
}

# Bounded so the limiter cannot become the memory leak it exists to prevent.
# Oldest-seen addresses are evicted first; an evicted scraper simply starts a
# fresh bucket, which is the correct trade against unbounded growth.
MAX_TRACKED = 20_000

_buckets: dict[str, OrderedDict[str, list]] = {k: OrderedDict() for k in LIMITS}


def classify(path: str, method: str) -> str:
    if path.endswith("/crowd/register"):
        return "register"
    if method not in ("GET", "HEAD", "OPTIONS"):
        return "write"
    return "read"


def client_ip(request) -> str:
    # Order matters: CF-Connecting-IP is the single address Cloudflare vouches
    # for. X-Forwarded-For is a list a client can prepend to, so it is only
    # consulted when the Cloudflare header is absent, and only its last hop.
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def is_local(ip: str) -> bool:
    return ip in ("127.0.0.1", "::1", "localhost", "unknown")


def check(ip: str, cls: str, now: float | None = None) -> tuple[bool, int]:
    """Returns (allowed, retry_after_seconds)."""
    if is_local(ip):
        return True, 0
    now = now if now is not None else time.monotonic()
    limit, window = LIMITS[cls]
    book = _buckets[cls]

    hits = book.get(ip)
    if hits is None:
        hits = []
        book[ip] = hits
        if len(book) > MAX_TRACKED:
            book.popitem(last=False)
    book.move_to_end(ip)

    cutoff = now - window
    # A sliding window rather than a fixed one: fixed windows let a caller send
    # a full allowance at 11:59:59 and another at 12:00:00, which is double the
    # limit at exactly the moment a burst hurts most.
    hits[:] = [t for t in hits if t > cutoff]
    if len(hits) >= limit:
        return False, max(1, int(hits[0] + window - now) + 1)
    hits.append(now)
    return True, 0


def stats() -> dict:
    return {cls: {"tracked_addresses": len(b), "limit": LIMITS[cls][0],
                  "window_seconds": LIMITS[cls][1]}
            for cls, b in _buckets.items()}
