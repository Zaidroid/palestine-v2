# Plan 09 · Telegram poller and ingestion framework (the scarce account)

Phase 4 — Silent failures: ingestion, feeds, operations. Read `00-README.md` first (setup, rules, the per-task loop).

## Scope

- **Files you may edit:** `ingest/telegram_poller.py`, `ingest/discover_channels.py`, `ingest/setup_session.py`, `ingest/engine.py`, `ingest/framework.py`, `ingest/spec.py`, `ingest/bronze.py`, `ingest/sources/rss_news.py`, `ingest/sources/checkpoints.py`, `ingest/sources/palhub_roads.py`, `ingest/sources/palhub_loader.py`, `tests/test_poller.py`, `tests/test_engine.py`, `tests/test_palhub_roads.py`, `tests/test_palhub_backlog.py`, `tests/test_ingest_hardening.py`, `tests/test_ingest.py`
- **Tests to run after every task:** `tests/test_poller.py tests/test_engine.py tests/test_palhub_roads.py tests/test_palhub_backlog.py tests/test_ingest_hardening.py` (with the local DB sourced), then the full suite once at the end of the file.
- **Area rules:** Hard rules 3 and 4 are the priority: FloodWaitError honoured everywhere (including media download) with no retry storm; one Telethon client per session file enforced by a lock that discovery/--status/CLI modes all take; exit codes that systemd policy relies on must be reachable. Never add a join or a subscription. The v1 checkpoint import cursor must not skip late rows or re-insert boundary rows (use ingest_seen or a (channel,msg_id) key); do not touch /opt/stacks/palestine (read-only by rule). Tests must mock Telethon — never create a real client.

- Confirmed tasks: 11 · verify-first tasks: 22 · refuted (skip): 2

## A. Confirmed tasks (independently verified — do these first, in order)

### INGEST-01 · F007 · critical · data-integrity
**The v1 import cursor is MAX(observed_at) of a kind the crowd also writes with now(), and v1 rows inserted out of timestamp order are skipped forever**

- **Where:** `ingest/sources/checkpoints.py:146`
- **What goes wrong:** Tick at 12:00:00 imports v1 rows dated <= 11:59:50. A crowd report on checkpoint_status lands at 12:00:30 (observed_at=now()). v1 writes a channel message dated 12:00:10 at 12:00:40. Next tick: since=12:00:30, so the 12:00:10 report never imports and nothing counts it. Without the crowd the same loss occurs whenever v1 inserts across channels out of message-date order (catch-up after the 8-hour outage the ledger records), the HANDOFF §4 paging trap in another coat. Hard rule 2.
- **Fix:** Key the cursor on v1's rowid (SELECT rowid ... WHERE rowid > ?) or record (source_channel, source_msg_id, canonical_key) in ingest_seen and page by rowid; at minimum scope the MAX to `attrs ? 'canonical_key'`. Needs main-server to validate; add a rolled-back DB test like tests/test_palhub_backlog.py.
- **Evidence (audited code):**
```
:146-148 `cur.execute("SELECT MAX(observed_at) FROM state_observation WHERE state_kind=%s", (LEGACY_KIND,)); since = cur.fetchone()[0]` then :155 `sql += " WHERE timestamp > ?"`. crowd/engine.py:271-276 inserts state_observation rows with `observed_at` = `now()` for any crowd-reportable kind, and db/migrations/030_crowd_engine.sql:126 makes checkpoint_status crowd-reportable: `WHERE state_kind IN ('checkpoint_status', 'checkpoint_flow');`. No ingest_seen or UNIQUE guards this importer (023 explains why there is no UNIQUE on state_observation).
```
- **Verifier's check:** Code confirmed. ingest/sources/checkpoints.py:146-148 sets since = MAX(observed_at) over every state_kind='checkpoint_status' row, with no modality or canonical_key scope. :155 then filters v1 with 'timestamp > since'. crowd/engine.py:271-276 inserts state_observation with observed_at=now(). That includes rate_limited rows, which are still written. Migration 030:126 makes checkpoint_status crowd_reportable, no later migration turns it off, and 035 maps it to checkpoint places, so a resolvable name succeeds. /v2/crowd/register is open by decision (3/hr per IP) and /v2/crowd/report allows 20/min …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### INGEST-02 · F213 · medium · data-integrity
**Hard rule 4 (one Telethon client per session file) is enforced by nothing: discovery, --status and the poller's CLI modes all open the live session with no lock and no check that the service is stopped**

- **Where:** `ingest/discover_channels.py:178`
- **What goes wrong:** An operator (or the weekly maintenance agent) runs `python -m ingest.discover_channels --all` or `setup_session --status` while palestine-v2-poller is active. Two MTProto clients now use one auth key from one session SQLite; per the project's own rule this is the pattern that invalidates the account, and even short of that a second `--once` run races store() (SELECT-then-INSERT on claim_dedup, :243-286) and writes duplicate claim rows that ON CONFLICT DO NOTHING then hides.
- **Fix:** Take an exclusive fcntl.flock on `SESSION.with_suffix('.lock')` in a shared helper used by telegram_poller.run(), discover_channels.discover()/probe_liveness() and setup_session.status()/sign_in(); on contention print which pid holds it and exit non-zero (discover may offer `--stop-poller` that runs systemctl stop, waits for the lock, and restarts on exit). Test the helper with two processes in tests/test_poller.py.
- **Evidence (audited code):**
```
session = str(ROOT / "data" / "session" / "v2_ingest")
    ...
    client = TelegramClient(session, api_id, api_hash)
    await client.start()
(discover_channels.py:178-187; again at :292 in probe_liveness); setup_session.status() opens the same path (setup_session.py:145-150 via _client); the poller's `--once`/`--backfill` (telegram_poller.py:520-531) run the same run() against the same SESSION (:70). None of them checks `systemctl is-active palestine-v2-poller`, takes a lock on the session path, or stops the unit. docs/HANDOFF.md:27-29: 'Two Telethon clients must never share one session file... Discovery STOPS the poller first'. docs/DECISIONS.md:101 records the burst limit tripping 'durin …
```
- **Verifier's check:** Evidence quoted accurately: ingest/discover_channels.py:178-187 builds TelegramClient on data/session/v2_ingest and calls start(); probe_liveness does the same at :292-294; ingest/setup_session.py:72-77 (_client, used by status() at :150) opens the same SESSION (:39); the poller's --once/--backfill (:520-531) run run() against SESSION (:70,:402). grep for flock|fcntl|is-active|systemctl|.lock across ingest/ and ops/watchdog.py/maintain returns nothing — no lock, no unit check, no stop. Telethon's SQLite session only serialises concurrent writes; it does not stop a second process from reading t …
- **Already in the release plan:** HANDOFF §1 rule 4 and DECISIONS.md:101 (2026-07-31 ops) state the rule and the stop-the-poller procedure; ops/maintenance-prompt.md:17 forbids the agent from running Telethon while the poller runs. No plan item tracks code enforcement.
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### INGEST-03 · F217 · medium · performance
**The poller still downloads every @palhubappfuel photo (hundreds to ~1,000 GetFile requests and empty claims per day) for a vertical retired on 2026-09-23 that nothing consumes**

- **Where:** `ingest/telegram_poller.py:101`
- **What goes wrong:** Whether @palhubappfuel is still in V2_TELEGRAM_CHANNELS cannot be verified in this checkout (.env), but docs/PLAN-2026-09-21 §67 counts 15,892 never-classified tg_palhubappfuel claims and the 09-22 entry counts daily photo volume. If it is, the scarcest account issues up to ~1,000 media requests a day and the claim hypertable gains ~1,000 empty-text rows a day (each one also a bronze json object and a lang detector call) for images no job reads, while the news channels' catch-up shares the same cycle and stagger budget.
- **Fix:** Empty MEDIA_CHANNELS (or gate it on a registry flag) now that the image vertical is retired; if the channel stays polled for the crowd-fuel text messages, skip claims whose text is empty and that carry no media the project reads. Confirm on main-server with `SELECT count(*) FROM claim WHERE source_id=(SELECT source_id FROM source WHERE key='tg_palhubappfuel') AND ingested_at > now()-interval '1 day'`.
- **Evidence (audited code):**
```
MEDIA_CHANNELS = {"palhubappfuel"}
(line 101); archive_media downloads every photo up to MEDIA_PER_CYCLE=150 per cycle (:202-229); store() writes a claim with raw_text '' for each photo-only message (:241-287). The only consumer of attrs.media_ref is ingest/sources/palhub_fuel_image.py, whose unit and script are in ops/retired/ (ops/retired/ingest-fuel-images.sh, ops/retired/systemd/palestine-v2-fuel-images.*); docs/DECISIONS.md 2026-09-22 measured 'palhubappfuel posted 288-1,040 messages a day 09-14..09-22, all photos'.
```
- **Verifier's check:** Code side confirmed. ingest/telegram_poller.py:101 MEDIA_CHANNELS = {'palhubappfuel'}; archive_media (:198-229) downloads every photo up to MEDIA_PER_CYCLE=150 (:114) per cycle; store() writes raw_text '' for photo-only messages (:241, `or ""`), plus a bronze json object (:257) and a detect_quietly('') call (:267); no CHECK on raw_text exists in any migration (grep). The only reader of attrs.media_ref outside the poller is ingest/sources/palhub_fuel_image.py (grep --include=*.py/*.sql/*.sh), whose unit and script live in ops/retired/ (ingest-fuel-images.sh, systemd/palestine-v2-fuel-images.{se …
- **Already in the release plan:** docs/PLAN-2026-09-24 §4 R3 lists fuel availability as retired; migration 070 retires the vertical; the poller side is not mentioned
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### INGEST-04 · F218 · medium · data-integrity
**Cursor state file is written non-atomically and only on cycles that stored something; a truncated file resets every cursor to 0 and starts a 2,000-message-per-channel-per-cycle history walk**

- **Where:** `ingest/telegram_poller.py:144`
- **What goes wrong:** Power loss or SIGKILL (TimeoutStopSec default 90 s during a long FloodWait sleep) lands mid write_text. On restart the file does not parse, every channel starts at min_id=0, and each cycle issues MAX_PAGES=20 GetHistory requests per channel (up to 2,000 messages, each costing a claim_dedup SELECT) until the whole history is re-walked; because every batch dedups to written==0, total stays 0 and the advanced cursors are never persisted, so the next restart begins from 0 again. On a 14-channel list that is ~280 history requests per ~45 s cycle on the fragile account.
- **Fix:** Write to a temp file and os.replace (the bronze pattern at ingest/bronze.py:72-79); save whenever any cursor changed, not only when total>0; on a corrupt file, refuse to start from 0 silently (log loudly and, if a .bak exists, use it). Cover with a test that corrupts the file and asserts the poller does not fall back to 0.
- **Evidence (audited code):**
```
def _save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1, sort_keys=True))
(lines 142-144); `_load_state` returns {} on JSONDecodeError (:135-139); the loop saves only `if total: _save_state(state)` (:508-509) although state[ch] advances at :472 whenever store() ran, including when every message was a dedup hit and written == 0.
```
- **Verifier's check:** Mechanism confirmed. ingest/telegram_poller.py:142-144 uses Path.write_text (truncate then write) while ingest/bronze.py:70-79 does tmp + os.replace; _load_state (:135-139) returns {} on JSONDecodeError (probe: a truncated or empty file -> {}); the loop saves only `if total:` (:508-509) although state[ch] advances at :472 whenever store() ran, including all-dedup cycles with written == 0; the unit sets no TimeoutStopSec (grep ops/systemd) so the 90s default applies while a FloodWait sleep of fw.seconds+5 (:483) can run far longer, making SIGKILL mid-life possible. After a corrupt file every ch …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### INGEST-05 · F219 · medium · data-integrity
**Source identity and the poll cursor are keyed on the mutable Telegram username, not the channel id: a rename silently darkens the channel and, once fixed in .env, re-ingests its whole history as a second witness**

- **Where:** `ingest/telegram_poller.py:150`
- **What goes wrong:** A polled channel changes its @username. get_entity(old) fails at startup -> UNRESOLVED and the channel is dark until noticed. The operator updates .env to the new name: _ensure_source creates a second source row, state has no cursor for the new key, _fetch_since walks the entire history from id 0 in 2,000-message chunks and every message is inserted again under the new source_id (no dedup hit). Corroboration now sees the same channel as two units for every historical event, and the account pays for the full re-walk.
- **Fix:** Resolve each channel to its numeric channel_id once and key source (a `telegram_id` column or key tg_<channel_id>) and the cursor on that id, keeping the username as an alias in attrs; ingest by entity id. Backfill existing tg_* rows with their ids (migration) and refuse to create a second source for a known id.
- **Evidence (audited code):**
```
key = f"tg_{channel.lower()}"
(line 150, _ensure_source), cursor `last = state.get(ch, 0)` (:463) keyed on the .env string, get_entity(ch) by username (:413), and external_id = str(m.id) which is only unique per channel (:242). claim_dedup's PK is (source_id, external_id) (db/migrations/005_claim.sql:43), so a new source row means no dedup.
```
- **Verifier's check:** Confirmed. ingest/telegram_poller.py:150 keys source on `tg_{channel.lower()}` (INSERT ... ON CONFLICT (key) DO NOTHING, :151-156), :463 keys the cursor on the .env string, :413 resolves by username, :242 external_id = str(m.id); claim_dedup PK is (source_id, external_id) (db/migrations/005_claim.sql:43) and source has no telegram/channel id column (grep migrations). Telethon-1.36.0 client/users.py:336-337 sends string entities to _get_entity_from_string, which always issues ResolveUsernameRequest (:556) — a renamed username raises and lands in UNRESOLVED (:416), and since [3] nothing retries, …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### INGEST-06 · F221 · medium · accuracy
**Forwarded messages are recorded (attrs.fwd_from) but never used: a report forwarded through N news channels is counted as N independent witnesses**

- **Where:** `ingest/telegram_poller.py:269`
- **What goes wrong:** Channel A reports a raid; channels B and C forward A's message verbatim (Telegram marks fwd_from=A's channel_id on both). The classifier files three reports from three units and the event serves as 'corroborated by 3 independent sources' and reaches the confidence tier that reassures a traveller, on the strength of one witness.
- **Fix:** In the corroboration key, map a claim whose attrs.fwd_from names a channel we also poll (or any forwarded claim) onto the origin's unit: e.g. unit = 'fwd:'||attrs->>'fwd_from' when present; count the origin once. This is deterministic and needs no fit; the statistical copy detection of P0-C.5 remains for un-forwarded copies. Measurable now on main-server: `SELECT count(*) FILTER (WHERE attrs->>'fwd_from' IS NOT NULL), count(*) FROM claim WHERE source_id IN (news sources)`.
- **Evidence (audited code):**
```
attrs = {"channel": channel, "views": getattr(m, "views", None),
                     "fwd_from": _fwd_id(m),
(lines 268-269, _fwd_id at :292-300 returns the origin channel_id). grep over the repository finds no other reader of fwd_from. The classifier's independence unit is `COALESCE(s.independence_group, 'src:' || s.source_id::text)` (ingest/sources/news_incidents.py:424) and learn/source_independence.py measures agreement only over checkpoint co-observations (docstring lines 6-10), so news channels have NULL independence_group (docs/PLAN-2026-09-24 §4 R2).
```
- **Verifier's check:** Confirmed. attrs.fwd_from is written at ingest/telegram_poller.py:252 and :269 via _fwd_id (:292-300, returns the origin channel_id/user_id); grep over all .py/.sql/.sh outside tests finds no other reader. The classifier's independence unit is ingest/sources/news_incidents.py:424 `COALESCE(s.independence_group, 'src:' || s.source_id::text) AS unit`, units are counted distinct per cluster at :523 (`units = {m[2] for m in cluster}`) and drive _confidence(len(units)) at :525 and the merge path at :576-588, so three channels carrying one forwarded message are three units. learn/source_independence …
- **Already in the release plan:** docs/PLAN-2026-09-24 §4 R2 ('News channels never tested for copying... the 25% multi-source share is inflated') and §7 P0-C.5; the ingest-side fwd_from signal is not mentioned there
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### INGEST-07 · F222 · medium · accuracy
**Message edits and deletions are invisible: a corrected or retracted report keeps feeding events with its original wording**

- **Where:** `ingest/telegram_poller.py:343`
- **What goes wrong:** A news channel posts 'شهيد برصاص الاحتلال في بيتا' and edits it ten minutes later to 'إصابة' (injured), or deletes it after a correction. The poller has already stored the first text; the edit is never fetched (min_id excludes seen ids), the deletion leaves no trace, the death event stays served and counted under 'death' precision.
- **Fix:** Track the newest edit_date seen per channel and, each cycle, also request messages by id for the last K stored ids (get_messages(ids=[...])) or subscribe to events.MessageEdited/MessageDeleted while connected; on an edit insert a NEW claim with external_id '<id>:e<edit_date>' and attrs.supersedes=<claim_id>, on a deletion insert a marker claim; have the classifier prefer the newest claim per (source, message id) and demote events whose only claims are retracted. Needs a small migration for the supersedes convention and a classifier change.
- **Evidence (audited code):**
```
msgs = [m for m in await client.get_messages(
            ent, limit=PAGE, min_id=cursor, reverse=True) if m.id > cursor]
(lines 342-343) is the only read path; nothing records edit_date, no MessageEdited/MessageDeleted handling exists anywhere in the repository (grep for edit_date, grouped_id, MessageEdited returns nothing outside tests/test_maintain_due.py). claim is immutable by hard rule 5, so the design needs a superseding claim, not an update, and none is produced.
```
- **Verifier's check:** Confirmed. The only read paths are get_messages(min_id=cursor, reverse=True) at ingest/telegram_poller.py:342-343 and the backfill get_messages(limit=backfill) at :423; both fetch by id above the cursor, so an edited message (same id) is never re-read and a deleted one leaves no trace. grep for edit_date|MessageEdited|MessageDeleted|grouped_id|supersedes across .py/.sql finds nothing except an unrelated comment in db/migrations/072_fuel_price_copies.sql:17 (the finding's mention of tests/test_maintain_due.py is immaterial). claim is immutable (005_claim.sql:1-3,46-47; docs/HANDOFF.md rule 5), …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### INGEST-08 · F223 · medium · safety
**The exit-2 'deauthorised, do not restart' path is dead: startup deauth returns 1, and the mid-run check reads Telethon's cached flag**

- **Where:** `ingest/telegram_poller.py:404`
- **What goes wrong:** (a) The session is revoked or the account banned while the poller runs: AuthKeyUnregisteredError/UserDeactivatedBanError (both UnauthorizedError, i.e. RPCError) surface per channel in the generic handler at :484, three all-fail cycles later the poller exits 1 (:497), systemd restarts it; at startup is_user_authorized() is False and :406 returns 1 again; Restart=on-failure with StartLimitIntervalSec=0 then reconnects the dead session every 30 s doubling to every 15 min, forever, with an OnFailure alarm on every attempt. (b) The Telethon 404 path (_disconnect(error=AuthKeyNotFound)) makes is_connected() False, _reconnect() calls connect() and then is_user_authorized() returns the cached True without a request, so Deauthorised is never raised. Exit 2 is unreachable in both real cases.
- **Fix:** Return 2 at :406. In _reconnect and in the per-channel handler, treat telethon.errors.UnauthorizedError (and AuthKeyError) as Deauthorised and exit 2 immediately rather than counting it as a channel failure; reset `client._authorized = None` (or call get_me() inside try/except UnauthorizedError) before the check in _reconnect so it is a real request. Add fake-client tests for both exit codes.
- **Evidence (audited code):**
```
if not await client.is_user_authorized():
        print("Not authorised. Run: ./.venv/bin/python -m ingest.setup_session --request-code")
        return 1
(lines 404-406) and in _reconnect:
            if not await client.is_user_authorized():
                raise Deauthorised("session is no longer authorised")
(lines 377-378). Telethon 1.36 users.py:213-221: `if self._authorized is None: try GetStateRequest; self._authorized = True except RPCError: False; return self._authorized` and _authorized is only reset in __init__ (telegrambaseclient.py:416), _on_login and log_out. The unit relies on exit 2: ops/systemd/palestine-v2-poller.service.d/watchdog.conf:11 `RestartPreventExitStatus=2`; the …
```
- **Verifier's check:** Confirmed on both paths. Startup: ingest/telegram_poller.py:404-406 returns 1, not the 2 the docstring (:38-40) and ops/systemd/palestine-v2-poller.service.d/watchdog.conf:11 (RestartPreventExitStatus=2) rely on; the unit has Restart=on-failure, StartLimitIntervalSec=0, RestartSec=30/RestartSteps=5/RestartMaxDelaySec=900 (service:31,38,43-45) and OnFailure=palestine-v2-alert@%n (watchdog.conf:5), so a deauthorised session is reconnected every 30s->15min forever with an alarm per attempt. Mid-run: Telethon-1.36.0 client/users.py:213-221 caches _authorized; grep shows it is set only in telegramb …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### INGEST-09 · F225 · medium · operability
**A database outage is treated as a channel failure: Telegram is polled and media downloaded every cycle for work that cannot be stored, then the exit/restart loop re-fetches the whole backlog each life**

- **Where:** `ingest/telegram_poller.py:471`
- **What goes wrong:** palestine-v2-db is restarted for 40 minutes. Every ~45 s the poller fetches up to 20 pages per channel and downloads up to 150 photos, fails to store, and after three cycles exits 1; systemd restarts it (30 s, 60 s, ... up to 900 s) and each life repeats the full re-fetch of a growing backlog. The account spends hundreds of GetHistory/GetFile requests on nothing, and the watchdog only learns of it when the poller's last_ok goes stale.
- **Fix:** Above the channel loop, run a one-row `SELECT 1` through resolve.db.connect(); on failure sleep with backoff and do not touch Telegram (count toward the same 3-cycle exit). Keep the fetched batch across a store() failure instead of discarding it, so the next cycle retries store() without re-fetching. Test with a fake connect that raises.
- **Evidence (audited code):**
```
fresh = await _fetch_since(client, ent, last)   # oldest first
                if fresh:
                    refs, cutoff = await archive_media(client, ch, fresh)
                    ...
                        total += store(ch, fresh, refs)
(lines 464-471); store() opens the connection inside (:238) so a DB outage raises there, is caught at :484 as a channel failure, and after 3 cycles the process exits 1 (:493-497). The only pre-loop health check is `client.is_connected()` (:446). ops/heartbeat.fail also needs the DB, so the exit is unrecorded (heartbeat.py:98-105).
```
- **Verifier's check:** Confirmed. store() opens connect() inside (:238 -> resolve/db.py:47-53, psycopg.connect raises on outage); the exception is caught at :484-486 as a channel failure. archive_media runs before store (:466 vs :471), so photos are downloaded for messages that cannot be stored; `fresh` is a local and state[ch] (:472) is not reached, so the batch is discarded and re-fetched (up to 20 pages, :341-353) next cycle. The only pre-loop check is client.is_connected() (:446). beat() and fail() swallow DB errors (ops/heartbeat.py:80-88, 98-105), so the fail() at :494 is unrecorded. Nuance that makes it worse …
- **Already in the release plan:** docs/HANDOFF.md §4 names the shape ('a transport failure is not a channel failure and must be checked separately, above the loop') for the Telegram transport only
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### INGEST-10 · F226 · medium · operability
**A poller with zero resolved channels beats a healthy heartbeat forever; a channel that fails to resolve at startup is never retried**

- **Where:** `ingest/telegram_poller.py:490`
- **What goes wrong:** A fresh session file or a transient network error at startup makes every get_entity fail (a FloodWait on ResolveUsername is also caught by that generic except and the loop keeps calling get_entity for the remaining channels). entities is {}; `{} and ...` is falsy, so the else branch beats every cycle with channels=0 and claims=0. systemd says active, /health says ok, the watchdog says ok, and no claim is ingested until someone restarts the unit. With a partial failure the unresolved channels stay dark for the life of the process with only `channels: N` in a detail column nothing reads.
- **Fix:** Treat `not entities` as a fatal startup condition (fail() + return 1). Re-raise FloodWaitError in the resolve loop and sleep it. Keep a set of unresolved channels and retry get_entity every K cycles; include them in the beat detail and have the watchdog compare detail.channels with the configured count (see the watchdog-detail finding).
- **Evidence (audited code):**
```
if entities and failures == len(entities):
            dead_cycles += 1
            ...
        else:
            dead_cycles = 0
            beat(HEARTBEAT, int(interval), _GRACE,
                 {"channels": len(entities), "claims": total,
                  "channel_failures": failures})
(lines 490-506). Entities are resolved once at :411-417 with `except Exception as exc: print(f"  UNRESOLVED @{ch}: {exc}")` and nothing revisits them; ops/watchdog.job_checks (ops/watchdog.py:370-382) reads status and last_error only, never detail.
```
- **Verifier's check:** Confirmed. ingest/telegram_poller.py:490 `if entities and failures == len(entities)` is falsy for entities == {} (scratchpad verify/state_probe.py prints 'beat(channels=0)'), so the else branch (:498-506) beats every cycle with channels=0, claims=0. Channels are resolved exactly once at :411-417 with a generic except that prints UNRESOLVED and moves on (a FloodWaitError on ResolveUsername is swallowed there too, and Telethon's client-side flood guard then makes every remaining get_entity fail as well, so a single flood at startup darkens the whole list for the life of the process); nothing rev …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### INGEST-11 · F438 · low · correctness
**Fuel-station locality anchor is resolved with no kind preference and an existing station is returned without checking its anchor (retired feed, still importable)**

- **Where:** `ingest/sources/palhub_loader.py:70`
- **What goes wrong:** Dormant while retired; if re-enabled, a station whose locality string matches a checkpoint alias is placed on the checkpoint's centroid with precision 'town'.
- **Fix:** prefer_kind='locality' on the anchor lookup; leave the file retired and say so in its docstring.
- **Evidence (audited code):**
```
:70 `a = resolve_place(locality, conn=conn, learn=False)` (no prefer_kind, so a checkpoint or road alias can anchor a station); :83-88 returns an existing `place_id` by palhub_name even when the current locality/region differ; :200-203 clamps only skew > 60 s and keeps 0..60 s of negative age. HANDOFF §2 marks the fuel-availability units retired 2026-09-23.
```
- **Verifier's check:** I tried to refute all three sub-claims and could not. (1) ingest/sources/palhub_loader.py:70 calls `resolve_place(locality, conn=conn, learn=False)` with no context, so `prefer_kind` is None. In resolve/geo.py:181-205 `_prefer` then ranks a checkpoint (1.0) above a locality (0.8). I checked this with a throwaway script: two exact rows, one checkpoint and one locality, come back ['checkpoint','locality'] without context and ['locality','checkpoint'] with prefer_kind='locality'. The containment branch also weights a checkpoint above a locality (KIND_W checkpoint 1.1 vs locality 1.0, geo.py:303-3 …
- **Already in the release plan:** HANDOFF §2 (fuel{,-images} timers retired 2026-09-23, migration 070); DECISIONS 2026-09-23 ZAID; PLAN-2026-09-21 §8 F-09. These cover the retirement only; the anchor-kind defect itself is recorded nowhere.
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

## B. Verify-first tasks (reported by one reader, not independently checked)

For each: reproduce it with a failing test first. If you cannot reproduce it, do NOT change code — add one line to `SKIPPED.md` with the id and why.

- **INGEST-V01 · F138 · medium** — engine.resolve_date: a record with no date silently takes v1's fetch stamp as occurred_at at the spec's default precision — `ingest/engine.py:188`
  - scenario: One UN FTS flow (funding is read live from v1) arrives with `date: null` → stored as occurred_at 2026-09-25T03:00:12Z, precision day → counted fresh by T7 and the gap radar; the ingest-date costume law 1 exists to strip, put back on by the fallback.
  - suggested fix: When `raw is None` and no rule fired, return `(_fetch_day(rec) or "", "unknown", reported)`, or refuse the row under a declared drop reason (`no_date`) so the spec must size it.
- **INGEST-V02 · F335 · medium** — checkpoints.py --full deletes ~all checkpoint observations across compressed chunks without raising the Timescale DML decompression limit (033 shows it aborts); the rebuild path is dead and rests on v1 retaining everything — `ingest/sources/checkpoints.py:141`
  - scenario: `python -m ingest.sources.checkpoints --full` (the documented 'rebuild all history from v1') runs the DELETE, Timescale decompresses >100,000 tuples, raises 'tuple decompression limit exceeded by operation', the transaction rolls back and the rebuild never happens — loud, but the recovery path a parser fix depends on is unusable. Separately, when it does run it is a statement-level DELETE of ~100k …
  - suggested fix: Never delete to rebuild: insert the re-parsed rows with attrs.parser_version and let belief select the newest parser generation (or mark superseded rows with modality='superseded'), preserving the earlier parse. Where DML on old chunks is unavoidable (place_merge, the road_closure sweep), execute `SET LOCAL timescaledb.max_tuples_decompressed_per_dml_transaction = 0` in the same transaction and bo …
- **INGEST-V03 · F121 · medium** — Cursor compared as a text string with microseconds truncated: boundary rows re-inserted every run or same-day rows skipped, depending on v1's timestamp format — `ingest/sources/checkpoints.py:156`
  - scenario: If v1 stores '2026-09-24T12:00:00.123456', the rows in the last imported second satisfy `> '2026-09-24T12:00:00'` on every 2-minute tick and are inserted again (the fuel-duplication shape). If v1 stores '2026-09-24 12:00:00', then 'T' (0x54) > ' ' (0x20) makes every later same-day row compare LOWER than the cursor and be skipped. v1's format is not verifiable in this checkout: check `SELECT typeof …
  - suggested fix: Same as the rowid/ingest_seen cursor above; until then compare on a value v1 itself wrote (rowid) rather than a re-formatted datetime.
- **INGEST-V04 · F122 · medium** — Unmatched v1 keys and unparseable timestamps are dropped permanently while the docstring promises a complete archive — `ingest/sources/checkpoints.py:162`
  - scenario: A checkpoint promoted from v1's 17,057 pending candidates (PLAN §4 R3) gets a v2 place row next week; every report v1 filed for it in the meantime is gone from v2 unless --full is run by hand, and the skip is only a stdout line (never a heartbeat field or alarm).
  - suggested fix: Write unmatched rows to a holding table (checkpoint_unmatched: canonical_key, raw row) or to a synthetic place per canonical_key with servable=false, and replay them when _place_map gains the key; count both skips in the heartbeat payload; fix the docstring meanwhile.
- **INGEST-V05 · F164 · medium** — Road messages bypass the claim layer: no claim row, no bronze, claim_id NULL, raw text truncated in attrs — `ingest/sources/checkpoints.py:180`
  - scenario: A disputed 'closed' at Huwara cannot be traced to the message that produced it (no claim, no bronze, text cut at 200/300 chars); the classifier version that read it is not recorded on the row; nothing links a road report to an incident at the same place; and v1's parser (place matching) is an unversioned dependency whose regressions land in v2 unmeasured.
  - suggested fix: Ingest road messages as claims (from v1's tee spool or a v2 subscription per PLAN P3) with bronze refs, write state_observation.claim_id, and stamp attrs.parser_version = checkpoint_text version so re-reads are attributable — the pattern news_incidents already follows.
- **INGEST-V06 · F123 · medium** — Parser confidence is stored but never used: an emoji-only or inferred `open` is believed at the same 0.85 as an explicit statement — `ingest/sources/checkpoints.py:204`
  - scenario: "الفحص❌❌❌" (0.65) and "شالو الحاجز" (inferred open, 0.72) become checkpoint_flow rows that state_current carries at base_confidence 0.85 — indistinguishable from 'مغلق بالاتجاهين'. The reassuring inference in particular is served at full single-source trust with no corroboration requirement, the asymmetry P2.4 was written for.
  - suggested fix: In unit_trust multiply by o.confidence (or by a floor of it), or add inferred/emoji readings to crowd_gated-style gating (require a second unit for value='open' when o.confidence < 0.8). Validate with learn/accuracy.py on main-server.
- **INGEST-V07 · F124 · medium** — Palhub name resolution ignores the area on a unique name hit and accepts a locality as a checkpoint — `ingest/sources/palhub_roads.py:150`
  - scenario: Palhub's 'المدخل الشرقي' under جنين resolves to the one gazetteer checkpoint of that name in another governorate; a name with no checkpoint row resolves to the town (the HANDOFF §4 'accepted, stored, incapable of mattering' trap). Today the rows are quarantined; but ops/measure_review.py pairs on place_id, so these rows silently leave the agreement metric, and on promotion (PLAN P1-A) they would p …
  - suggested fix: Filter NAME_SQL rows by admin2_pcode when the caller supplies one (add an optional admin2 argument to resolve_for_state_kind); in _resolve_uncached reject `r.kind != 'checkpoint'` and count `wrong_kind`; report unresolved AND wrong-kind counts per area in stats.
- **INGEST-V08 · F125 · medium** — A Palhub format change kills the feed silently: non-bulletins are marked seen forever and rejected lines have no threshold — `ingest/sources/palhub_roads.py:220`
  - scenario: Palhub prepends an emoji line or renames 'أزمة متوسطة'. Every claim is marked seen with zero readings, the heartbeat stays green, the watchdog sees the collector alive, and after the fix nothing can be re-read without deleting from ingest_seen — the HANDOFF §4 'absence of a complaint' shape, on the feed that lifted coverage 23% -> 64%.
  - suggested fix: Exit non-zero (so OnFailure fires) when claims > 0 and bulletins == 0, or rejected_lines/readings > 0.05; do not mark a non-bulletin from tg_palhubapproad as seen (leave it pending and count it); add a feed_cadence entry keyed on `written`.
- **INGEST-V09 · F215 · medium** — RSS reader cannot fail: a dead or empty feed prints 'FEED FAILED' and exits 0, so the unit, heartbeat and OnFailure all record success — `ingest/sources/rss_news.py:195`
  - scenario: qudsn.co moves its feed (docs/DECISIONS.md:103 records WAFA and Maan doing exactly that). Every 15 minutes httpx raises, the error is printed, main returns 0, with-heartbeat records ingest-external ok, and the one genuinely independent newsroom in the corroboration model disappears without an alarm; independent_sources on every subsequent event is lower than it should be and nobody knows why.
  - suggested fix: Return 1 from main() when any feed failed or returned 0 items (RSS feeds never legitimately have zero items), and record per-feed liveness (last item pubDate) in the heartbeat detail; add the RSS sources to the watchdog's silence check. Add tests for _parsed_at, _external_id and the exit status.
- **INGEST-V10 · F216 · medium** — spec.py validates nothing under registry.rules[].when, and load_registry.matches() returns True for a rule whose only keys are typos, so one misspelled key classifies every indicator — `ingest/spec.py:459`
  - scenario: A spec author writes `when: {regexp: '^demolitions'}` in the ordered registry rules. test_spec_format passes, the loader accepts it, and because first match wins (load_registry.classify docstring) every indicator after that rule takes its concept/measure_kind/polarity; registry.max_unclassified cannot catch it because nothing is unclassified. Served 'insights' then compare stocks against flows und …
  - suggested fix: Add a `_registry_when` checker to spec.py that refuses any key outside {prefix, regex, equals, not_prefix, unit} (mirroring _condition) and requires at least one; make matches() raise on unknown keys instead of ignoring them; add a test in tests/test_spec_format.py with a typo'd key. This is the same hole the file's docstring (lines 5-15) exists to close.
- **INGEST-V11 · F166 · medium** — feeds_incidents defaults to true for every new Telegram source, so the first road channel added to the v2 poller becomes a closure-incident factory — `ingest/telegram_poller.py:152`
  - scenario: P1-A.4 adds a Jenin road channel to V2_TELEGRAM_CHANNELS. Every 'حاجز X مغلق' bulletin (re-posted every few minutes) becomes a `closure` event at the checkpoint (containment resolves حواره inside the run-on capture) plus a road_closure state asserted for up to 24 h (036), one new event per 90-min gap, while 'سالك' lines are rejected as 'too short' — the 037 palhub failure (390 phantom incidents) r …
  - suggested fix: Make feeds_incidents an explicit column in both _ensure_source INSERTs (false unless the source is registered as a news channel), stop the station-word capture at a flow/status lexicon token, and add a test that a road bulletin is rejected by cascade.news as 'status bulletin'.
- **INGEST-V12 · F220 · medium** — The poller creates source rows without answering feeds_incidents, so any new status/bulletin channel added to .env feeds the incident classifier by default — `ingest/telegram_poller.py:152`
  - scenario: Decision D-4 adds north road channels or the crossings authority channel to V2_TELEGRAM_CHANNELS. Their structured bulletins ('حاجز X مغلق', 'المعبر مغلق') enter the classifier on the first cycle, exactly as @palhubappfuel's did on 2026-08-03 (11,730 claims -> 390 false incidents), and are served as closure/raid incidents near routes until someone notices and runs an UPDATE.
  - suggested fix: Make the channel list declarative: each entry carries feeds_incidents (and kind: news|roads|fuel|crossings) in registry.yaml or a small channels.yaml; _ensure_source writes the declared value and the poller refuses an undeclared channel. Until then, insert new sources with feeds_incidents=false and require an explicit flip.
- **INGEST-V13 · F224 · medium** — get_entity FloodWait at startup is swallowed and the loop keeps resolving the remaining channels inside the flood window — `ingest/telegram_poller.py:415`
  - scenario: A fresh session file (after a re-login) or a channel list with new names: the third ResolveUsername returns FLOOD_WAIT_1800; the loop prints it and 1.5 s later issues the fourth, fifth ... resolve calls, each a further request inside the flood. Every channel from the third on is then UNRESOLVED for the life of the process (see the zero-entities finding).
  - suggested fix: Catch FloodWaitError separately in the resolve loop, sleep fw.seconds, and retry the same channel; keep a retry schedule for channels that failed for other reasons.
- **INGEST-V14 · F228 · medium** — No test covers the account-safety paths: FloodWait handling (either handler), exit codes 1/2, the dead-cycle counter, store() idempotence or the media cutoff; the RSS reader has no tests at all — `tests/test_poller.py:27`
  - scenario: A future edit reorders the except clauses in run() or archive_media, or changes a return code, and the suite stays green; the regression reaches the production poller on the next `systemctl restart`, and hard rule 3 is violated with no red build.
  - suggested fix: Add fake-client tests: (1) FloodWaitError from get_messages causes one sleep and no further requests that cycle; (2) FloodWaitError from download_media propagates out of archive_media; (3) run() returns 2 when is_user_authorized is False at startup and when an UnauthorizedError surfaces mid-run; (4) three all-fail cycles return 1; (5) store() with a fake cursor writes each message once across two …
- **INGEST-V15 · F437 · low** — Time adverbs are ignored: a report about the morning is stamped at message time — `ingest/sources/checkpoints.py:167`
  - scenario: An 18:00 recollection of a morning closure is served as a closure observed at 18:00 with a fresh half-life — 'age changes the answer' (DESIGN.md law 1) is defeated at the source.
  - suggested fix: Detect الصبح/امبارح/قبل N ساعه/ساعات/من شوي and either back-date observed_at (bounded) or lower the modality to 'unparsed' with a note; measure the share on main-server first.
- **INGEST-V16 · F427 · low** — Per-place cadence is measured over all history and across copy channels, so the staleness band reflects copy lag, not reporting rhythm — `ingest/sources/checkpoints.py:260`
  - scenario: A place mentioned once a day but by nine copy channels within seconds has a median gap of seconds -> half-life 15 min -> 'expired' after 2 h, while a place reported every 30 min by one channel gets 45 min. A place busy in June and silent since keeps June's rhythm. Conservative in direction, but the band (which the API shows and QA questioned) is an artifact.
  - suggested fix: Compute gaps per independence unit (COALESCE(independence_group, source)) over a trailing 30-60 days and take the median across units; record observations and window in place_state_cadence.
- **INGEST-V17 · F439 · low** — The Palhub loader loads the whole ingest_seen set into Python on every tick although PENDING_SQL already excludes it — `ingest/sources/palhub_roads.py:211`
  - scenario: A 5-minute timer that fetches and hashes hundreds of thousands of ids to skip nothing; grows without a ceiling.
  - suggested fix: Delete the Python seen set; keep the SQL filter (tested).
- **INGEST-V18 · F440 · low** — belief_refresh runs on every Palhub tick under the global belief lock although nothing it writes can count — `ingest/sources/palhub_roads.py:279`
  - scenario: Every 5 minutes a full checkpoint_flow belief recompute contends with the 2-minute v1 sync for the advisory lock, for a source whose rows are structurally invisible to it.
  - suggested fix: Skip the refresh when MODALITY != 'assertion' or when written == 0.
- **INGEST-V19 · F480 · low** — RSS reader has no paging and no conditional GET: PalInfo's feed exposes 10 items per fetch on a 15-minute timer, so a busy quarter-hour drops items permanently — `ingest/sources/rss_news.py:113`
  - scenario: During a major incident PalInfo publishes 14 items between two runs; the four oldest never appear in any fetch and are lost with no signal. Every run also re-downloads ~170 KB that a 304 would have answered.
  - suggested fix: Send If-None-Match/If-Modified-Since (the framework already has this logic in BaseFetcher.http_get, :146-179) and record the feed's item count per run; when a fetch returns the maximum window and every item is new, log a 'window saturated' warning in the heartbeat detail; where the CMS supports it (WordPress: ?paged=2) page back until a seen guid appears.
- **INGEST-V20 · F481 · low** — Media-only and service messages become empty-text claims; grouped_id is not recorded, so albums cannot be reassembled and their caption is attached to one arbitrary member — `ingest/telegram_poller.py:241`
  - scenario: A news channel posts a 6-photo album with one caption naming the village and a death. Six claims are written; five have raw_text '' and cost a bronze object, a dedup lookup and a lingua call each, and are read once by every classifier version; nothing links the caption to its photos. On @palhubappfuel this is several hundred empty claims a day (see the media finding). Counts such as heartbeat 'cla …
  - suggested fix: Record grouped_id and edit_date in attrs; skip storing messages with empty text unless the channel is in MEDIA_CHANNELS or the message carries a document/link the project reads; when an album's caption arrives, store one claim for the group with the member ids in attrs.
- **INGEST-V21 · F482 · low** — The beat before a FloodWait sleep carries the fixed 900 s grace, so any flood longer than ~15 minutes is reported as not_running (scheduler stopped) rather than as a poller correctly waiting — `ingest/telegram_poller.py:481`
  - scenario: Telegram returns FLOOD_WAIT_3600. After 930 s the watchdog raises 'telegram-poller not_running — the scheduler is not firing it', the OnFailure/alert path pages, the operator restarts the unit (the documented reflex for not_running), and the fresh process immediately re-issues the request the flood forbade.
  - suggested fix: Pass grace=max(_GRACE, fw.seconds + int(interval) + 60) on that beat (COALESCE in the UPSERT keeps it) and restore _GRACE on the next normal beat; include the wait in last_error text so the status page says 'flood wait until HH:MM'.
- **INGEST-V22 · F582 · low** — test_ingest.py writes into the real bronze store (data/bronze/_selftest) and cleans up only on success — `tests/test_ingest.py:26`
  - scenario: A failing check midway (or a Ctrl-C) leaves `_selftest` objects in the production evidence store; `bronze.stats()` and the nightly inode/size measurements count them; the vault snapshot job may archive them.
  - suggested fix: At the top of the script set `bronze.BRONZE = Path(tempfile.mkdtemp())` (or a `PALESTINE_BRONZE` env override honoured by ingest/bronze.py) and drop the rmtree.

## C. Refuted — do not fix

- F032 v1 import cursor is a truncated-string comparison with no dedup: boundary rows are re-inserted (or lost) every 2-minute tick (`ingest/sources/checkpoints.py:155`) — Cannot be confirmed from this checkout. The code facts are right: ingest/sources/checkpoints.py:146-157 uses a string cursor `timestamp > since.strftime('%Y-%m-%dT%H:%M:%S')`, and _flush (:219-227) has no dedup. But which failure happens, if either, depends on v1's stored timestamp format, and neith …
- F042 FloodWaitError during media download is swallowed by a generic except and the loop immediately fires the next download (`ingest/telegram_poller.py:218`) — Evidence (a) is accurate: ingest/telegram_poller.py:216-221 catches Exception, and telethon FloodWaitError -> FloodError -> RPCError -> Exception (Telethon-1.36.0 errors/rpcbaseerrors.py:13,95; rpcerrorlist.py:1620), so the :473 handler never sees it. A fake-client probe (scratchpad verify/media_pro …
