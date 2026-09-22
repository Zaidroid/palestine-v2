"""Turn archived palhub fuel cards into observations. QUARANTINED.

    .venv/bin/python -m ingest.sources.palhub_fuel_image
    .venv/bin/python -m ingest.sources.palhub_fuel_image --limit 200

The poller archives @palhubappfuel's rendered cards into bronze and records the
ref on the claim. This reads those images, OCRs them, and writes what they say.

WRITTEN UNDER THE TEXT FEED'S SOURCE, DELIBERATELY
Rows go in as source `telegram_fuel` — the SAME source_id the tee-spool loader
uses — not as the poller's `tg_palhubappfuel`. Those two source rows are the
same Telegram channel read two ways, and letting both feed belief would hand
one witness two votes. Copy-collapse exists to catch that, but relying on a
downstream defence for a duplicate WE created is backwards: a channel is one
witness whether we read its words or its pictures.

EVERYTHING HERE IS `quarantined` AND NOTHING PROMOTES IT
Every card in a sweep carries the same "آخر تحديث", so that timestamp is when
the card was RENDERED and says nothing about when any station was seen. This is
exactly the shape of the palhub ROAD bulletin, whose timestamps looked live
while the median checkpoint was 24 hours old (P6.1) — measured, quarantined,
and still quarantined. The same discipline applies until the same measurement
is done, and the measurement is possible: on 2026-08-01 between 09:14 and 18:20
the channel posted text bulletins AND cards, so the two can be compared
directly on the same stations at the same minute. That overlap is the only
held-out baseline this feed will ever have.

WHAT IS WRITTEN, AND WHAT IS REFUSED
  available     for a named station whose pill is present.
  unavailable   for EVERY station in a region when the card says
                "لا توجد محطة متوفر فيها وقود حالياً في هذه المدينة" — the one
                negative the card states rather than implies.
  nothing       for the "N محطة أخرى بلا وقود" count. It is recorded on the
                sweep row as context and never becomes a station verdict:
                Bethlehem's card implies eleven stations where we hold ten, so
                the subtraction is already known to be wrong somewhere, and an
                off-by-one would put "no diesel" on a station that has it.

A station's missing pill is SILENCE, not `unavailable`. The card lists what is
there; it never says what is absent.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from cascade.fuel_image import ocr_passes, parse_card   # noqa: E402
from ingest import bronze                              # noqa: E402
from resolve.belief import refresh as belief_refresh   # noqa: E402
from resolve.db import connect                         # noqa: E402

# The two kinds this loader owns. Named so the belief refresh can be scoped to
# them: belief_refresh writes state_current, and a loader must never write
# outside the kinds it is responsible for.
FUEL_KINDS = ("fuel_diesel", "fuel_gasoline")

# The tee loader's source. Same channel, one witness — see the module docstring.
SOURCE_KEY = "telegram_fuel"
POLLER_SOURCE_KEY = "tg_palhubappfuel"

# F-05, 2026-09-22 — THE PROMOTION, AND HOW IT IS UNDONE.
#
# `quarantined` is collected-but-never-believed (migration 033): resolve/belief
# counts only `assertion`, so a quarantined row can never reach a served value.
# The text feed this loader deliberately shares a source with (one channel is
# one witness, see above) died on 2026-08-28 and cannot supply the held-out
# comparison this quarantine was waiting for. That leaves a choice between a
# vertical with no readings at all and readings whose provenance is written on
# the row. Zaid's default (ZAID-1) is to serve them, flagged.
#
# So `--serve` writes `assertion`; every served row carries its basis and its
# warning in attrs, and `/v2/fuel/*` shows both. A run WITHOUT `--serve` still
# writes `quarantined` — which is what makes this reversible by number rather
# than by memory: the old modality is one flag away, and the reason the
# promotion happened is recorded here rather than assumed.
MODALITY_QUARANTINED = "quarantined"
MODALITY_SERVING = "assertion"
SERVING_BASIS = "image_ocr"
SERVING_WARNING = "read from a rendered card; may be stale or wrong"

# What a bare run writes. The safe path stays the default; serving is asked for.
MODALITY = MODALITY_QUARANTINED

# The parse is a template match on a fixed render, not a judgement about the
# world, so the confidence describes OCR reliability and nothing more. It is
# recorded for the eventual comparison; it gates nothing while quarantined.
PARSE_CONFIDENCE = 0.90

# Commit every N cards rather than once at the end.
#
# OCR is two tesseract runs per card at roughly half a second each, so a
# thousand-card backlog is fifteen minutes inside a single transaction. The
# first full run was killed at the ten-minute mark and every card it had read
# was rolled back — fifteen minutes of CPU for nothing, and the cursor left
# exactly where it started. Batching makes the work durable as it goes, which
# matters more than transactional tidiness for a loader whose unit of work is
# one independent image.
COMMIT_EVERY = 25


def _stations_by_region(cur) -> dict[str, list[tuple[int, str]]]:
    cur.execute("""SELECT source_refs->>'palhub_region', place_id, name_ar
                     FROM place
                    WHERE kind = 'station' AND source_refs ? 'palhub_region'
                      AND name_ar IS NOT NULL""")
    out: dict[str, list[tuple[int, str]]] = {}
    for region, pid, name in cur.fetchall():
        out.setdefault(region, []).append((pid, name))
    return out


def run(limit: int | None = None, verbose: bool = False, serve: bool = False,
        since_hours: int | None = None) -> dict:
    """Read the archived cards and write what they say.

    `serve` writes them as `assertion` (believed, served, flagged) instead of
    `quarantined`; `since_hours` refuses cards older than the window, because
    the observation time on a card is when it was RENDERED and a card from three
    weeks ago is not evidence about now. Both default to the safe behaviour.
    """
    modality = MODALITY_SERVING if serve else MODALITY_QUARANTINED
    stats = {"cards": 0, "not_a_card": 0, "no_region": 0, "observations": 0,
             "all_dry_regions": 0, "unmatched": 0, "ocr_failed": 0,
             "skipped_old": 0, "modality": modality}
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT source_id FROM source WHERE key = %s", (SOURCE_KEY,))
        row = cur.fetchone()
        if not row:
            raise SystemExit(f"source {SOURCE_KEY!r} is missing — run the tee loader first")
        fuel_source_id = row[0]

        cur.execute("SELECT source_id FROM source WHERE key = %s", (POLLER_SOURCE_KEY,))
        row = cur.fetchone()
        if not row:
            print(f"no {POLLER_SOURCE_KEY} source yet — has the poller run?")
            return stats
        poller_source_id = row[0]

        by_region = _stations_by_region(cur)
        regions = sorted(by_region)

        # ingest_seen is keyed on the FUEL source, so a re-run is a no-op and a
        # backfill cannot double-count. Same cursor table the tee loader uses,
        # for the same reason: 762,609 duplicate fuel rows were once created by
        # a loader that only claimed to be idempotent.
        cur.execute("SELECT external_id FROM ingest_seen WHERE source_id = %s",
                    (fuel_source_id,))
        seen = {r[0] for r in cur.fetchall()}

        # NEWEST FIRST when serving: a fuel reading is asserted for
        # `max_assert_seconds` (3 h, state_kind_config) after the card's own
        # timestamp, so a card from yesterday is history the moment it is read.
        # The measurement path keeps the old backlog order, which is what a
        # catch-up and the quarantined comparison want.
        order = "DESC" if serve else "ASC"
        cur.execute(f"""
            SELECT claim_id, external_id, reported_at, attrs->>'media_ref'
              FROM claim
             WHERE source_id = %s AND attrs->>'media_ref' IS NOT NULL
               AND (%s::int IS NULL
                    OR reported_at > now() - make_interval(hours => %s::int))
             ORDER BY reported_at {order}""", (poller_source_id, since_hours, since_hours))
        rows = cur.fetchall()

        pending = [r for r in rows if f"img:{r[1]}" not in seen]
        if limit:
            pending = pending[:limit]

        done = 0
        for claim_id, ext_id, reported_at, ref in pending:
            try:
                blob = bronze.get(ref)
            except (OSError, ValueError) as exc:
                if verbose:
                    print(f"  bronze read failed for {ref}: {exc}")
                stats["ocr_failed"] += 1
                continue

            # tesseract wants a path. NamedTemporaryFile rather than a fixed
            # name so concurrent runs cannot read each other's bytes.
            with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
                tmp.write(blob)
                tmp.flush()
                texts = ocr_passes(tmp.name)
            if not texts:
                # Marked seen so an unreadable blob is not re-OCRed every run
                # forever. This loses no DATA — bronze keeps the bytes under the
                # retain-everything rule — it only stops burning CPU on
                # something that will not change. The first such blob was a
                # 926 KB MP4 the poller had mislabelled as a photo.
                stats["ocr_failed"] += 1
                _mark(cur, fuel_source_id, ext_id)
                continue

            card = parse_card(texts, known_regions=regions)
            if not card.is_card:
                stats["not_a_card"] += 1
                _mark(cur, fuel_source_id, ext_id)
                continue
            region = card.region_matched
            if not region:
                stats["no_region"] += 1
                # NOT marked seen. A card whose region we could not read is a
                # parser gap to come back to, not a message to forget.
                if verbose:
                    print(f"  region unresolved: {card.region_raw!r}")
                continue

            # Re-parse with THIS region's stations as the candidate set. The
            # first pass only had to find the region; matching names against
            # two-to-thirty known stations is what makes an OCR slip harmless.
            names = [n for _, n in by_region.get(region, [])]
            card = parse_card(texts, known_stations=names, known_regions=regions)
            ids = {n: pid for pid, n in by_region.get(region, [])}
            stats["cards"] += 1
            stats["unmatched"] += len(card.unmatched)

            attrs_common = {
                "via": "image", "card_region": region, "claim_id": claim_id,
                "others_dry": card.others_dry, "notes": card.notes or None,
                # F-05: when these rows are SERVED, the provenance travels on
                # the row itself — a served reading must never be mistakable for
                # a text bulletin's. `basis` above stays what the CARD said
                # (a pill, or the region-wide "no station has fuel"); this is
                # what WE did with it.
                "modality_basis": SERVING_BASIS if serve else None,
                "warning": SERVING_WARNING if serve else None,
            }

            if card.region_all_dry:
                stats["all_dry_regions"] += 1
                for pid, _name in by_region.get(region, []):
                    for kind in ("fuel_diesel", "fuel_gasoline"):
                        _write(cur, pid, kind, "unavailable",
                               "لا توجد محطة متوفر فيها وقود", reported_at,
                               fuel_source_id,
                               {**attrs_common, "basis": "region_all_dry"},
                               modality=modality)
                        stats["observations"] += 1
            else:
                for st in card.stations:
                    pid = ids.get(st.name_matched or "")
                    if pid is None:
                        continue
                    for kind in st.fuels:
                        _write(cur, pid, kind, "available", st.name_raw,
                               reported_at, fuel_source_id,
                               {**attrs_common, "basis": "pill",
                                "match_score": st.match_score,
                                "crisis": st.crisis},
                               modality=modality)
                        stats["observations"] += 1

            _mark(cur, fuel_source_id, ext_id)
            done += 1
            if done % COMMIT_EVERY == 0:
                conn.commit()
                if verbose:
                    print(f"  ... {done}/{len(pending)} cards, "
                          f"{stats['observations']} observations")
        if serve:
            # Nothing is served until belief has seen it. Same scoped refresh the
            # tee loader does, and the same lock-free reason: this process owns
            # these two kinds for the length of the run.
            stats["belief_rows"] = belief_refresh(FUEL_KINDS, conn=conn)
            if verbose:
                print(f"  belief refreshed: {stats['belief_rows']} rows")
        conn.commit()
    return stats


def _write(cur, place_id, state_kind, value, raw_value, observed_at,
           source_id, attrs, modality: str = MODALITY) -> None:
    cur.execute("""
        INSERT INTO state_observation
            (place_id, state_kind, value, raw_value, observed_at, source_id,
             confidence, modality, attrs)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (place_id, state_kind, value, raw_value, observed_at, source_id,
         PARSE_CONFIDENCE, modality, json.dumps(attrs, ensure_ascii=False)))


def _mark(cur, source_id, ext_id) -> None:
    # Prefixed so an image and a text bulletin with the same message id cannot
    # collide in a cursor table both loaders share.
    cur.execute("""INSERT INTO ingest_seen (source_id, external_id)
                   VALUES (%s,%s) ON CONFLICT DO NOTHING""",
                (source_id, f"img:{ext_id}"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--serve", action="store_true",
                    help="write as `assertion` (believed and served, flagged) "
                         "instead of `quarantined` — F-05; drop the flag to undo")
    ap.add_argument("--since-hours", type=int, default=None,
                    help="refuse cards rendered more than this long ago")
    a = ap.parse_args()
    s = run(limit=a.limit, verbose=a.verbose, serve=a.serve,
            since_hours=a.since_hours)
    for k, v in s.items():
        print(f"{k:20} {v}")
    if a.serve:
        print(f"\nSERVED: rows written as modality={s['modality']!r} with "
              f"modality_basis={SERVING_BASIS!r} and the warning "
              f"{SERVING_WARNING!r} on every row (F-05, ZAID-1 default). "
              f"Re-run without --serve to write quarantined rows again.")
    else:
        print(f"\nAll rows written with modality={s['modality']!r} — collected, "
              f"never believed. Pass --serve to promote (F-05), or read "
              f"docs/DECISIONS.md for why this default exists.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
