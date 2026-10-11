"""Road channels, read by v2: every message, its own matcher, its own register.

    .venv/bin/python -m ingest.sources.roads --dry-run            # read, write nothing
    .venv/bin/python -m ingest.sources.roads                      # what the timer does
    .venv/bin/python -m ingest.sources.roads --since 2026-07-31   # the backfill
    .venv/bin/python -m ingest.sources.roads --reread --since 2026-07-31   # after the register grew
    .venv/bin/python -m ingest.sources.roads --candidates         # names waiting for a yes

WHY (audit 2026-10-11, findings 01, 02 and 07)
Until this module, v2 knew a road report only after v1's whitelist parser had
decided which checkpoint it was about. That parser takes the words before the
first status word and looks them up whole: 84% of road messages matched nothing
in it, a misspelt name lost its reading (113 spellings, 6,699 mentions), a
reply that named nothing was filed under whichever name contained its words,
and the names it did not hold piled up in a table nothing promoted from
(20,268 of them). v2 re-read the status of the lines v1 let through, and that
was all: the matcher, the candidates and the vocabulary lived in the PoC.

This reads the messages themselves — cascade/road_message.py over
resolve/road_names.py — against a register that is v2's (place, place_alias,
road_alias), and keeps v2's own list of names it could not place
(road_candidate). Measured on the roads gold (tests/gold/roads.jsonl; the
score is in ops/roads-gold-score.json and `learn.roads_gold --score` redraws
it): v1's parser, the control it had to beat, reads 0.72 of what a person
reads at 0.81 precision.

WHERE THE MESSAGES COME FROM
Two doors, one cursor. A source flagged `feeds_roads` whose messages v2's own
poller stores arrives as claims; every other road channel arrives through the
spool v1's monitor tees to disk (`V1_ROOT/…/data/tee`, every message it sees).
A message is read once whichever door it came through (`ingest_seen`, keyed
`road:<msg_id>`). Moving a channel from v1's poller to v2's is one line in
`.env` (V2_TELEGRAM_CHANNELS) and nothing here changes.

WHAT IT WRITES, AND WHAT IT LEAVES ALONE
The same rows ingest/sources/checkpoints.py wrote — checkpoint_flow and the
four presence kinds, assertions, one per (place, direction, axis, value),
credited to the channel that filed them — marked `attrs.reader = 'v2'`.
While this reader is on, the importer keeps writing its archival row per v1
update (v1's verdict, the control) and writes no facts. A fact the importer
already wrote for the same message and place is never written twice, so the
backfill adds only what v1's matcher lost.

WHEN THE REGISTER GROWS
A message is read once, against the register as it stood. A name registered
afterwards (ops/road_register.py) is read from then on, and its past is still
in the messages: `--reread` goes back over messages already read and writes
only the facts that are not there yet — for a new place, its whole history;
for a place that already had the reading, nothing. It counts no candidate
twice and marks nothing as read.

THE SWITCH
On once migration 097 has given the register its tables. `ROADS_READER=off`
in `.env` holds it back and the importer writes the facts again, as before.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cascade.checkpoint_text import (DIRECTION_WORDS, FLOW_WORDS, PRESENCE_WORDS,  # noqa: E402
                                     _lex, _noun_kind, read, tokens)
from cascade.road_message import FILLERS, NOT_NAMES, parts_of, read_message  # noqa: E402
from resolve.arabic import normalize  # noqa: E402
from resolve.db import connect, env_value, v1_path  # noqa: E402
from resolve.road_names import Lexicon, fold_token, load as load_lexicon  # noqa: E402

SPOOL = v1_path("services/westbank-alerts/data/tee")
READER = "v2"
FLOW_KIND = "checkpoint_flow"
PRESENCE_KIND = {"idf": "checkpoint_idf", "police": "checkpoint_police",
                 "settlers": "checkpoint_settlers", "inspection": "checkpoint_inspection"}
ALL_KINDS = (FLOW_KIND, *PRESENCE_KIND.values())

READER_LOCK = 20261011          # advisory lock: one road-reader run at a time

# The timer reads from the start of yesterday: a message teed late, or a tick
# missed over midnight, is still inside the window.
WINDOW = timedelta(days=1)

@dataclass
class Message:
    channel: str
    msg_id: int
    at: datetime
    text: str
    reply_to: int | None = None
    claim_id: int | None = None


def enabled(cur) -> bool:
    """On once migration 097 has given the register its tables, unless held back."""
    mode = (env_value("ROADS_READER") or "auto").strip().lower()
    if mode in ("off", "0", "false", "no", "v1"):
        return False
    cur.execute("""SELECT to_regclass('road_alias') IS NOT NULL
                      AND to_regclass('road_candidate') IS NOT NULL""")
    return bool(cur.fetchone()[0])


# ── the two doors ────────────────────────────────────────────────────────────

def spool_messages(since: datetime, spool: Path | None = None) -> tuple[dict, int]:
    """Road-channel messages v1's monitor teed to disk since `since`, and how
    many lines were torn (a power loss mid-write leaves one; it is skipped and
    counted, never fatal)."""
    out: dict[tuple[str, int], Message] = {}
    torn = 0
    floor = since.date().isoformat()
    for f in sorted(glob.glob(str((spool or SPOOL) / "*.ndjson"))):
        if Path(f).stem < floor:
            continue
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    if str(r.get("is_checkpoint_channel")) != "True":
                        continue
                    text = (r.get("text") or "").strip()
                    if not text or text == "None":
                        continue
                    at = datetime.fromisoformat(r["date"])
                    mid = int(r["msg_id"])
                    rid = r.get("reply_to_id")
                    reply = int(rid) if rid not in (None, "", "None") else None
                except (ValueError, KeyError, TypeError):
                    torn += 1
                    continue
                if at.tzinfo is None:
                    at = at.replace(tzinfo=timezone.utc)
                if at >= since:
                    ch = str(r["channel"]).lower()
                    out[(ch, mid)] = Message(ch, mid, at, text, reply)
    return out, torn


def claim_messages(cur, since: datetime) -> dict:
    """Messages of road sources that v2's own poller stored."""
    cur.execute("""
        SELECT c.claim_id, s.key, c.external_id, c.reported_at, c.raw_text,
               c.attrs->>'reply_to'
          FROM claim c JOIN source s USING (source_id)
         WHERE s.feeds_roads AND s.kind = 'telegram' AND c.reported_at >= %s
           AND coalesce(c.raw_text, '') <> ''""", (since,))
    out = {}
    for claim_id, key, ext, at, text, reply in cur.fetchall():
        if not (ext or "").isdigit():
            continue
        ch = key.removeprefix("tg_")
        out[(ch, int(ext))] = Message(ch, int(ext), at, text.strip(),
                                      int(reply) if (reply or "").isdigit() else None, claim_id)
    return out


# ── names nobody registered ──────────────────────────────────────────────────

def candidate_names(text: str, lex: Lexicon) -> list[tuple[str, str, str]]:
    """(key, as written, the line) for each short line that reports a status about
    a name the register does not hold: the words before the first status word,
    which is how these channels write "<place> <status>". And each part of a
    registered place that has no row of its own ("حزما البلد")."""
    out = list(parts_of(text, lex))
    for line in text.split("\n"):
        toks = tokens(normalize(line))
        if not 2 <= len(toks) <= 7 or lex.scan(line):
            continue
        k = next((i for i, t in enumerate(toks)
                  if _lex(t, FLOW_WORDS) or _lex(t, PRESENCE_WORDS) or _noun_kind(t)), None)
        if not k or k > 4 or read(line).modality != "assertion":
            continue
        written = [t for t in toks[:k] if not _lex(t, DIRECTION_WORDS)]
        name = [fold_token(t) for t in written]
        if name and not all(t in FILLERS or t in NOT_NAMES or t.isdigit() for t in name):
            out.append((" ".join(name), " ".join(written), line.strip()[:200]))
    return out


# ── the run ──────────────────────────────────────────────────────────────────

def _road_sources(cur) -> tuple[dict[str, int], dict[str, int]]:
    cur.execute("SELECT key, source_id, home_place_id FROM source WHERE feeds_roads")
    ids, homes = {}, {}
    for key, sid, home in cur.fetchall():
        ch = key.removeprefix("tg_")
        ids[ch] = sid
        if home:
            homes[ch] = home
    return ids, homes


def _ensure_source(cur, channel: str, ids: dict[str, int]) -> int:
    """A road channel v1 began polling since the register was written."""
    if channel not in ids:
        cur.execute("""
            INSERT INTO source (key, name, kind, license_spdx, commercial_use, attribution_text,
                                authority_rank, feeds_incidents, feeds_roads)
            VALUES (%s, %s, 'telegram', 'NONE', false, %s, 4, false, true)
            ON CONFLICT (key) DO UPDATE SET feeds_roads = true
            RETURNING source_id""",
            (f"tg_{channel}", f"Telegram @{channel}", f"Telegram channel @{channel}"))
        ids[channel] = cur.fetchone()[0]
    return ids[channel]


def run(since: datetime | None = None, dry_run: bool = False, force: bool = False,
        now: datetime | None = None, reread: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    since = since or (now - WINDOW).replace(hour=0, minute=0, second=0, microsecond=0)
    stats: Counter = Counter()
    with connect() as conn, conn.cursor() as cur:
        if not (force or enabled(cur)):
            return {"enabled": False}
        if not dry_run:
            # One reader at a time. A backfill takes minutes; the two-minute tick
            # that meets it steps aside (the messages are still unread next tick)
            # instead of reading the same messages twice or queueing behind it
            # with the belief refresh waiting.
            cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (READER_LOCK,))
            if not cur.fetchone()[0]:
                return {"enabled": True, "busy": True}
        lex = load_lexicon(cur)
        cur.execute("SELECT to_regclass('road_candidate') IS NOT NULL")
        migrated = bool(cur.fetchone()[0])
        if not (migrated or dry_run):
            return {"enabled": False}          # nothing to write to before 097
        ids, homes = _road_sources(cur) if migrated else ({}, {})

        msgs, torn = spool_messages(since)
        stats["torn_lines"] = torn
        stats["from_spool"] = len(msgs)
        if migrated:
            claims = claim_messages(cur, since)
            stats["from_claims"] = len(claims)
            msgs.update(claims)                      # v2's own copy wins

        seen: set[tuple[int, str]] = set()
        if migrated and ids and not reread:
            cur.execute("""SELECT source_id, external_id FROM ingest_seen
                            WHERE source_id = ANY(%s) AND external_id LIKE 'road:%%'
                              AND first_seen >= %s""", (list(ids.values()), since))
            seen = set(cur.fetchall())
        # What is already written for a message and a place: by the importer
        # always, and on a re-read by this reader too.
        cur.execute("""SELECT attrs->>'channel', attrs->>'msg_id', place_id, state_kind
                         FROM state_observation
                        WHERE state_kind = ANY(%s) AND observed_at >= %s
                          AND (attrs ? 'canonical_key'"""
                    + (" OR attrs->>'reader' = %s)" if reread else ")"),
                    (list(ALL_KINDS), since - timedelta(minutes=1), READER) if reread
                    else (list(ALL_KINDS), since - timedelta(minutes=1)))
        held = {(ch, mid, pid, kind) for ch, mid, pid, kind in cur.fetchall()}

        rows: list[tuple] = []
        newly: list[tuple[int, str]] = []
        cands: dict[str, dict] = {}
        places: set[int] = set()
        for (ch, mid), m in sorted(msgs.items(), key=lambda kv: kv[1].at):
            sid = ids.get(ch)
            if sid is None:
                sid = -1 if dry_run else _ensure_source(cur, ch, ids)
            ext = f"road:{mid}"
            if (sid, ext) in seen:
                stats["already_read"] += 1
                continue
            stats["messages"] += 1
            parent = msgs.get((ch, m.reply_to)) if m.reply_to else None
            readings = read_message(m.text, lex, parent=parent.text if parent else None,
                                    home=homes.get(ch))
            if not reread:
                newly.append((sid, ext))
            if not reread and (not readings or parts_of(m.text, lex)):
                for name, written, line in candidate_names(m.text, lex):
                    c = cands.setdefault(name, {"n": 0, "surface": written, "example": line,
                                                "channels": set(), "first": m.at, "last": m.at})
                    c["n"] += 1
                    c["channels"].add(ch)
                    c["last"] = max(c["last"], m.at)
            if not readings:
                continue
            stats["messages_with_readings"] += 1
            for r in readings:
                if r.modality != "assertion":
                    stats["questions"] += 1
                    continue
                stats[f"readings_via_{r.via}"] += 1
                for f in r.facts:
                    kind = FLOW_KIND if f.axis == "flow" else PRESENCE_KIND.get(f.value)
                    if not kind:
                        continue
                    if (ch, str(mid), r.place_id, kind) in held:
                        stats["facts_already_held"] += 1
                        continue
                    value = (f.value if f.axis == "flow"
                             else "absent" if f.axis == "absence" else "present")
                    attrs = {"channel": ch, "msg_id": mid, "raw_line": r.line[:300],
                             "reader": READER, "alias": r.alias, "via": r.via,
                             "clause": f.clause, "axis": f.axis}
                    if f.tag:
                        attrs["sighting"] = f.tag
                    if r.rivals:
                        attrs["rivals"] = list(r.rivals)
                    rows.append((r.place_id, kind, value, r.line[:200], m.at, sid, m.claim_id,
                                 f.confidence, f.direction, f.direction_explicit, "assertion",
                                 json.dumps(attrs, ensure_ascii=False)))
                    stats["facts"] += 1
                    stats["flow" if f.axis == "flow" else f.axis] += 1
                    places.add(r.place_id)
            if not dry_run and len(rows) >= 5000:
                _flush(cur, rows)
        stats["places"] = len(places)
        stats["candidate_names"] = len(cands)
        if not dry_run:
            _flush(cur, rows)
            if newly:
                cur.executemany("""INSERT INTO ingest_seen (source_id, external_id)
                                   VALUES (%s, %s) ON CONFLICT DO NOTHING""", newly)
            _accrue(cur, cands)
            conn.commit()
    out = dict(stats)
    out.update(enabled=True, dry_run=dry_run, reread=reread,
               since=since.isoformat(timespec="minutes"),
               top_candidates=[(c["surface"], c["n"]) for _, c in
                               sorted(cands.items(), key=lambda kv: -kv[1]["n"])[:8]])
    return out


def _flush(cur, rows: list[tuple]) -> None:
    if rows:
        cur.executemany("""
            INSERT INTO state_observation
              (place_id, state_kind, value, raw_value, observed_at, source_id, claim_id,
               confidence, direction, direction_explicit, modality, attrs)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
        rows.clear()


def _accrue(cur, cands: dict[str, dict]) -> None:
    for name, c in cands.items():
        cur.execute("""
            INSERT INTO road_candidate (name_norm, surface, example, mentions, channels,
                                        first_seen, last_seen)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (name_norm) DO UPDATE SET
                mentions  = road_candidate.mentions + EXCLUDED.mentions,
                channels  = ARRAY(SELECT DISTINCT unnest(road_candidate.channels || EXCLUDED.channels)),
                last_seen = greatest(road_candidate.last_seen, EXCLUDED.last_seen),
                first_seen = least(road_candidate.first_seen, EXCLUDED.first_seen)""",
            (name, c["surface"], c["example"], c["n"], sorted(c["channels"]), c["first"], c["last"]))


def weekly_list(limit: int = 10) -> list[dict]:
    """The names waiting for one human yes: most written about in the last
    thirty days, undecided."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('road_candidate') IS NOT NULL")
        if not cur.fetchone()[0]:
            return []
        cur.execute("""
            SELECT surface, mentions, channels, example, first_seen::date, last_seen::date
              FROM road_candidate
             WHERE status = 'pending' AND last_seen > now() - interval '30 days'
             ORDER BY mentions DESC LIMIT %s""", (limit,))
        return [dict(zip(("name", "mentions", "channels", "example", "first_seen", "last_seen"), r))
                for r in cur.fetchall()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="read and count, write nothing")
    ap.add_argument("--since", help="YYYY-MM-DD: read the spool from this day (the backfill)")
    ap.add_argument("--force", action="store_true",
                    help="run although the switch is off (with --dry-run, before migration 097)")
    ap.add_argument("--reread", action="store_true",
                    help="go back over messages already read and write what the register, "
                         "as it stands now, adds (run after ops.road_register; needs --since)")
    ap.add_argument("--candidates", action="store_true", help="print the names waiting for a yes")
    a = ap.parse_args(argv)
    if a.candidates:
        for c in weekly_list():
            line = c["example"].replace("\n", " ⏎ ")[:60]
            print(f"{c['mentions']:5}  {c['name']:28} {','.join(c['channels'])[:40]:40} «{line}»")
        return 0
    since = (datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc) if a.since else None)
    if a.reread and not since:
        ap.error("--reread needs --since YYYY-MM-DD")
    s = run(since=since, dry_run=a.dry_run, force=a.force, reread=a.reread)
    if not s.get("enabled"):
        print("road reader is off (migration 097 not applied, or ROADS_READER=off)")
        return 0
    if s.get("busy"):
        print("road reader: another run holds the lock (a backfill?); this tick read nothing")
        return 0
    verb = "would write" if s["dry_run"] else "wrote"
    if s.get("reread"):
        print(f"road reader, re-reading since {s['since']}: {s.get('messages', 0)} messages, "
              f"{s.get('messages_with_readings', 0)} carry a reading")
    else:
        print(f"road reader since {s['since']}: {s.get('messages', 0)} new messages "
              f"({s.get('already_read', 0)} read before), {s.get('messages_with_readings', 0)} carry a reading")
    print(f"  {verb} {s.get('facts', 0)} facts on {s.get('places', 0)} places: "
          f"flow {s.get('flow', 0)}, presence {s.get('presence', 0)}, absence {s.get('absence', 0)}; "
          f"{s.get('facts_already_held', 0)} "
          + ("already written" if s.get("reread") else "left as the importer wrote them"))
    print(f"  by way of: the name {s.get('readings_via_name', 0)}, the line above "
          f"{s.get('readings_via_below', 0)}, the message replied to {s.get('readings_via_reply', 0)}, "
          f"the channel's own place {s.get('readings_via_channel', 0)}; "
          f"{s.get('questions', 0)} questions (not written)")
    if s.get("torn_lines"):
        print(f"  {s['torn_lines']} torn spool line(s) skipped")
    if s["top_candidates"]:
        print("  names it could not place: " + ", ".join(f"{n} ({c})" for n, c in s["top_candidates"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
