"""P2.1/P2.2 — one submission path, for every field tier 1 tracks.

    from crowd.engine import register, submit
    reg = register("abu_khaled", channel="http")     # token shown ONCE
    submit(handle, token, "fuel_diesel", "محطة العطاري رام الله", "available")

There is no fuel submission and no checkpoint submission. There is `submit`,
and which fields it accepts is a row in `state_kind_config`. Making a new kind
crowd-reportable is an UPDATE, not a deploy — that is commitment 2 of the scope,
made structural so it cannot quietly stop being true.

WHAT A SUBMISSION BECOMES
A `claim` (immutable — what a person SAID) and a `state_observation` (what we
take it to mean). Exactly what a Telegram channel produces, in the same
vocabulary, so a crowd report and a channel report corroborate or contradict
each other directly with nothing in between. If a crowd report could only be
expressed in its own words it could never confirm anything, and the whole
exercise would be a suggestion box.

Everything downstream is untouched and unaware: copy-collapse groups colluders,
the noisy-OR combines independent units, Loop A weights each reporter by what
they have earned, and the three serving gates refuse anything under-evidenced.
The engine adds identity and a door; it does not add a second way to believe
things.

WHAT THE DOOR REFUSES, AND WHAT IT KEEPS
Refusal never means deletion. A rate-limited or invalid report is still written
to `claim`, and to `state_observation` with `modality='rate_limited'` or
`'rejected'`. `REFRESH_SQL` counts only `modality='assertion'`, so these are
recorded, queryable, and structurally incapable of reaching a served value. The
retention rule has no exception for reports we did not like, and the abuse
loops need to be able to see them.

WHERE THE P2.4 GATE IS NOT
It is not here. A lone report at 14:02 may be one of three by 14:09, so gating
at the door would mean going back and editing a record of what somebody said.
The asymmetry is applied when belief is computed — see crowd/belief.py — which
means a report simply starts counting the moment it stops being alone.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analyst.lang import detect_quietly               # noqa: E402
from ingest import bronze                              # noqa: E402
from resolve.db import connect                         # noqa: E402
from resolve.geo import (_Ambiguous, resolve_for_state_kind,  # noqa: E402,F401
                         resolve_place)

# A submitter's place phrase must resolve at least this well before the report
# is believed. Lower than the parsers use, because a person naming where they
# are standing is more reliable than a phrase pulled out of a news sentence —
# but not zero, because "the checkpoint" resolves to whatever is alphabetically
# first and a confidently wrong location is the failure this project keeps
# finding.
MIN_PLACE_CONFIDENCE = 0.55

TOKEN_BYTES = 32
UNVERIFIED_GROUP = "crowd:unverified"



@dataclass
class Result:
    ok: bool
    status: str                 # accepted | rate_limited | rejected
    detail: str
    claim_id: int | None = None
    place_id: int | None = None
    place_name: str | None = None
    state_kind: str | None = None
    value: str | None = None
    counts_toward_belief: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ── identity ─────────────────────────────────────────────────────────────────

def register(handle: str, channel: str = "http", note: str = "") -> dict:
    """Create a submitter. Returns the token ONCE; only its hash is stored.

    The submitter's source row starts in the shared 'crowd:unverified'
    independence group. That is the whole defence against one person with five
    phones: any number of accounts in that group count as ONE observer, so a
    ring gets the weight of one anonymous stranger — 0.85 x 0.21 = 0.18, below
    every confidence floor in the system. Nothing here names sock puppets; they
    simply never had the standing to move anything.

    `reliability` is left NULL, exactly as it is for every other source. Loop A
    measures it or it stays unmeasured; it is never seeded.
    """
    handle = handle.strip().lower()
    if not handle or len(handle) < 3 or len(handle) > 40:
        raise ValueError("handle must be 3-40 characters")
    if not all(c.isalnum() or c in "_-." for c in handle):
        raise ValueError("handle may contain letters, digits, _ - . only")
    if channel not in ("http", "mcp", "telegram", "import"):
        raise ValueError(f"unknown channel {channel!r}")

    token = secrets.token_urlsafe(TOKEN_BYTES)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM submitter WHERE handle = %s", (handle,))
        if cur.fetchone():
            raise ValueError(f"handle {handle!r} is taken")
        cur.execute("""
            INSERT INTO source (key, name, kind, license_spdx, commercial_use,
                                attribution_text, authority_rank,
                                independence_group, independence_note, active)
            VALUES (%s, %s, 'crowd', 'NONE', false, 'Crowd report', 5, %s,
                    'Unverified submitter — shares one independence unit with '
                    'every other unverified submitter until independence is '
                    'earned.', true)
            RETURNING source_id""",
            (f"crowd_{handle}", f"Crowd submitter @{handle}", UNVERIFIED_GROUP))
        source_id = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO submitter (source_id, handle, secret_hash, channel, note)
            VALUES (%s, %s, %s, %s, %s)""",
            (source_id, handle, _hash(token), channel, note or None))
        conn.commit()
    return {"handle": handle, "source_id": source_id, "token": token,
            "independence": UNVERIFIED_GROUP,
            "note": "Store the token now — only its hash is kept."}


def authenticate(cur, handle: str, token: str) -> tuple[int | None, str]:
    """Returns (source_id, reason). source_id is None when refused."""
    cur.execute("""SELECT source_id, secret_hash, status, blocked_reason
                   FROM submitter WHERE handle = %s""", (handle.strip().lower(),))
    row = cur.fetchone()
    if not row:
        return None, "unknown handle"
    source_id, secret_hash, status, blocked_reason = row
    # Constant-time: a timing difference here would let an attacker learn a
    # token one character at a time.
    if not secrets.compare_digest(secret_hash, _hash(token)):
        return None, "bad token"
    if status != "active":
        return None, f"submitter is {status}" + (f": {blocked_reason}" if blocked_reason else "")
    return source_id, "ok"


# ── submission ───────────────────────────────────────────────────────────────

def _kind_config(cur, state_kind: str) -> dict | None:
    cur.execute("""SELECT state_kind, crowd_reportable, crowd_values,
                          crowd_gated_values, crowd_min_units, crowd_max_per_hour
                   FROM state_kind_config WHERE state_kind = %s""", (state_kind,))
    r = cur.fetchone()
    if not r:
        return None
    return {"state_kind": r[0], "reportable": r[1], "values": r[2],
            "gated": r[3], "min_units": r[4], "max_per_hour": r[5]}


def reportable_kinds() -> list[dict]:
    """What the engine currently accepts. Driven entirely by configuration, so
    this is the honest answer rather than a list maintained beside one."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT state_kind, crowd_values, crowd_gated_values,
                              crowd_min_units, crowd_max_per_hour
                       FROM state_kind_config
                       WHERE crowd_reportable ORDER BY state_kind""")
        return [{"state_kind": k, "values": v, "gated_values": g,
                 "min_units_for_gated": u, "max_per_hour": h}
                for k, v, g, u, h in cur.fetchall()]


def _rate_limited(cur, source_id: int, place_id: int, state_kind: str,
                  cap: int) -> int:
    cur.execute("""
        SELECT count(*) FROM state_observation
         WHERE source_id = %s AND place_id = %s AND state_kind = %s
           AND observed_at > now() - interval '1 hour'""",
        (source_id, place_id, state_kind))
    return cur.fetchone()[0]


def submit(handle: str, token: str, state_kind: str, place: str, value: str,
           direction: str = "both", note: str = "") -> Result:
    """The whole submission path, for every field. See the module docstring."""
    value = (value or "").strip().lower()
    with connect() as conn, conn.cursor() as cur:
        source_id, reason = authenticate(cur, handle, token)
        if source_id is None:
            return Result(False, "rejected", reason)

        cfg = _kind_config(cur, state_kind)
        if cfg is None:
            return Result(False, "rejected", f"unknown state kind {state_kind!r}")
        if not cfg["reportable"]:
            return Result(False, "rejected",
                          f"{state_kind} is not crowd-reportable")
        if value not in cfg["values"]:
            return Result(False, "rejected",
                          f"value must be one of {sorted(cfg['values'])}")
        if direction not in ("both", "inbound", "outbound"):
            return Result(False, "rejected", "direction must be both/inbound/outbound")

        try:
            res = resolve_for_state_kind(conn, place, state_kind)
        except _Ambiguous as amb:
            names = " / ".join(n for _, n in amb.options[:4])
            return Result(False, "rejected",
                          f"{place!r} matches {len(amb.options)} places — "
                          f"which one? {names}")
        if res is None or res.confidence < MIN_PLACE_CONFIDENCE:
            # Nothing is written: with no place there is no fact, only a string.
            # Told plainly so the submitter can name somewhere the system knows,
            # rather than being silently ignored.
            got = f" (best guess {res.name_ar or res.name_en} at {res.confidence:.2f})" if res else ""
            return Result(False, "rejected",
                          f"could not place {place!r} confidently{got}")

        # Everything below this line IS written, whatever the engine decides.
        cur.execute("""SELECT count(*) FROM state_observation
                        WHERE source_id=%s AND place_id=%s AND state_kind=%s
                          AND observed_at > now() - interval '1 hour'""",
                    (source_id, res.place_id, state_kind))
        recent = cur.fetchone()[0]
        over_cap = recent >= cfg["max_per_hour"]
        modality = "rate_limited" if over_cap else "assertion"

        payload = json.dumps({"handle": handle, "state_kind": state_kind,
                              "value": value, "place_text": place,
                              "place_id": res.place_id, "direction": direction,
                              "note": note, "modality": modality},
                             ensure_ascii=False)
        ref = bronze.put(f"crowd_{handle}", payload, "json")

        raw_text = f"[{state_kind}={value}] {place}" + (f" — {note}" if note else "")
        # The old rule here was "any character in the Arabic block means
        # Arabic", which called a note written in Hebrew English and could not
        # say `und` about a place name that is only digits. It is the same
        # detector the poller and the feeds use now, stamped the same way, so
        # one library version explains every language code in the corpus.
        code, detector = detect_quietly(raw_text)
        attrs = {"handle": handle, "state_kind": state_kind,
                 "value": value, "direction": direction,
                 "place_confidence": res.confidence,
                 "place_method": res.method, "note": note}
        if detector:
            attrs["lang_detector"] = detector
        cur.execute("""
            INSERT INTO claim (source_id, raw_ref, raw_text, lang, claim_type,
                               place_id, place_precision, place_phrase,
                               reported_at, attrs)
            VALUES (%s,%s,%s,%s,'crowd_report',%s,%s,%s, now(), %s)
            RETURNING claim_id""",
            (source_id, ref.ref, raw_text, code,
             res.place_id, res.precision, place,
             json.dumps(attrs, ensure_ascii=False)))
        claim_id = cur.fetchone()[0]

        # confidence here is the OBSERVATION's own quality (how well the place
        # resolved), not the reporter's standing. Standing is trust_weight and
        # is applied when belief is computed, by machinery that does not know a
        # crowd exists.
        cur.execute("""
            INSERT INTO state_observation
              (place_id, state_kind, value, raw_value, observed_at, source_id,
               claim_id, confidence, direction, direction_explicit, modality, attrs)
            VALUES (%s,%s,%s,%s, now(), %s,%s,%s,%s,%s,%s,%s)""",
            (res.place_id, state_kind, value, value, source_id, claim_id,
             float(res.confidence), direction, direction != "both", modality,
             json.dumps({"crowd": True, "handle": handle}, ensure_ascii=False)))

        cur.execute("UPDATE submitter SET last_seen_at = now() WHERE source_id = %s",
                    (source_id,))
        conn.commit()

    place_name = res.name_ar or res.name_en
    if over_cap:
        return Result(True, "rate_limited",
                      f"{recent} reports for this place in the last hour "
                      f"(cap {cfg['max_per_hour']}) — recorded, not counted",
                      claim_id, res.place_id, place_name, state_kind, value, False)

    gated = value in (cfg["gated"] or [])
    detail = f"recorded for {place_name}"
    if gated:
        detail += (f" — '{value}' needs {cfg['min_units']} independent units "
                   f"before it is served; corroboration will get it there")
    return Result(True, "accepted", detail, claim_id, res.place_id, place_name,
                  state_kind, value, True)
