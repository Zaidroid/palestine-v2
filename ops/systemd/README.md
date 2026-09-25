# systemd units, in version control

Copies of everything installed under `/etc/systemd/system/palestine-v2-*`.

## Why these are here

The nightly backup covers the database. It does not cover the unit files and
drop-ins that decide *when anything runs at all* — those lived only in `/etc`,
owned by root, on the same disk the backups exist to survive losing. A
restore would have brought back every row and left nothing to collect the next
one, and the gap would only have been discovered during a rebuild, which is the
worst moment to discover it.

They are copies, not the installed originals: systemd reads `/etc`. Treat this
directory as the record, and keep the two in step.

What is here, counted 2026-09-25 (`ls ops/systemd`): 23 service units and 19 timers
— three daemons (`api`, `poller`, `analyst`), the `alert@` template every
`OnFailure=` points at, and nineteen timer-driven oneshots — plus the `.d/`
drop-in directories described below. The count was "twelve unit files and eight
drop-ins" until 2026-09-25, from the 2026-08-01 system; count again rather than
trusting this line. Retired units live in `ops/retired/systemd/` (the fuel
availability pair, 2026-09-23) and are never installed.

## Installing

A rebuild follows this block and nothing else, so it enables EVERY timer in
this directory by glob rather than by a list. The list it replaced (until
2026-09-25) named the retired `palestine-v2-fuel.timer`, which no longer
exists here, and never named ten live ones — crowd, databank, gaza, maintain,
maintain-retry, measure-review, palhub-roads, rollup, scout, valhalla-ip — so a
restored box ran without belief refresh, the databank sync or Gaza bulletins
while the operator believed the install was complete.

    cd ~/palestine-v2
    sudo cp ops/systemd/palestine-v2-*.service ops/systemd/palestine-v2-*.timer \
            /etc/systemd/system/
    for d in ops/systemd/palestine-v2-*.d; do
      # a drop-in for a unit that is not here (a retired one) is not installed
      [ -e "${d%.d}" ] || { echo "skip $d: no such unit in ops/systemd"; continue; }
      sudo mkdir -p "/etc/systemd/system/$(basename "$d")"
      sudo cp "$d"/*.conf "/etc/systemd/system/$(basename "$d")/"
    done
    sudo systemctl daemon-reload
    sudo systemctl enable --now palestine-v2-api.service palestine-v2-analyst.service
    sudo systemctl enable --now $(cd ops/systemd && ls palestine-v2-*.timer)
    # LAST, and only once data/session/ holds the AUTHORISED Telegram session
    # (restored from the backup set, or made with ingest.setup_session): a
    # poller started without one reconnects an unauthorised session, which is
    # the pattern HANDOFF §1 rule 3 exists to prevent.
    sudo systemctl enable --now palestine-v2-poller.service

The oneshot services are started by their timers and are not enabled
themselves; `palestine-v2-maintain-retry.timer` starts
`palestine-v2-maintain.service` only when no digest has landed in six days.

## Checking they have not drifted

Compare every file in both directions — units AND drop-ins — by the path
relative to each root. (The check that stood here until 2026-09-25 diffed two
`ls` listings with different path prefixes, so it could never come back clean,
and it compared `.service`/`.timer` only, so a drop-in installed in `/etc` with
no copy here — the backup unit's `memory.conf`, DECISIONS F-03 — was invisible.)

    cd ~/palestine-v2/ops/systemd
    ETC=/etc/systemd/system
    for f in palestine-v2-*.service palestine-v2-*.timer palestine-v2-*.d/*.conf; do
      case $f in *.d/*) [ -e "${f%%.d/*}" ] || continue ;; esac   # retired unit's orphan
      cmp -s "$f" "$ETC/$f" || echo "DRIFT or MISSING in /etc: $f"
    done
    (cd "$ETC" && ls -d palestine-v2-*.service palestine-v2-*.timer \
                        palestine-v2-*.d/*.conf 2>/dev/null) |
      while read -r f; do [ -e "$f" ] || echo "ONLY in /etc: $f"; done

Silence means in step. Nothing runs this on a schedule yet; it is a hand check
after any unit change.

## What the drop-ins carry

The `.d/` directories hold the P3.1 wiring, kept separate from the base units so
the monitoring could be reviewed as one change:

  * `onfailure.conf` — `OnFailure=palestine-v2-alert@%n.service`, on the units
    that predate it: `accuracy`, `api`, `checkpoint-learn`, `checkpoints`,
    `external`, `news`. Units written later carry the same line inline in the
    base file; `poller` carries it in `watchdog.conf`. Every service here except
    the `alert@` template itself has one or the other — check with
    `grep -l '^OnFailure=' palestine-v2-*.service palestine-v2-*.d/*.conf`.
    Before P3.1, only the two backup units reported failure; everything else
    failed into the journal, where nothing was reading.
  * `palestine-v2-poller.service.d/watchdog.conf` — `OnFailure=`, plus
    `RestartPreventExitStatus=2`. Exit 2 means the Telegram session is no longer
    authorised; restarting cannot fix that, and reconnecting an unauthorised
    session repeatedly is exactly what would put the account at risk. The base
    unit has NO start limit (`StartLimitIntervalSec=0`) and backs off from 30 s
    to a 15-minute ceiling instead — a deliberate reversal, 2026-08-02, recorded
    in the unit's own header: a three-strikes limit killed the poller for
    seventeen hours.
  * `palestine-v2-poller.service.d/unbuffered.conf` — `PYTHONUNBUFFERED=1`, so a
    long-running service's output reaches the journal before it exits.
  * `palestine-v2-fuel.service.d/` — an orphan: its unit was retired on
    2026-09-23 and lives in `ops/retired/systemd/`. The install loop above skips
    it.

Exit codes that are not failures are declared per unit with
`SuccessExitStatus=`: `palestine-v2-mcp-audit.service` treats exit 1 ("ran
fine, found criticals", already paged by the audit's own alert) as success.
The watchdog no longer does — `ops/watchdog.sh` exits 0 for "ran, found
faults" and 70 for "did not finish", so a watchdog that crashes now alarms
instead of being recorded as a success.

## Alarm delivery (F-04, 2026-09-22)

Every `OnFailure=` in this directory ends in `ops/alert.py`, which records the
alarm in `ops/alerts.ndjson` and then tries to put it in front of a human.
Until 2026-09-22 that second half reached nobody: `ops/notify.py` wanted
`ALERT_BOT_TOKEN` and `ALERT_CHAT_ID`, neither was set, and `send` returned
`unconfigured` — so the file and the journal were the whole channel.

Delivery now goes to the **house ntfy** first (`fawwaz-alerts` on main,
`http://127.0.0.1:8688`), with Telegram kept as a fallback for whoever sets the
pair. Three things about that server are worth knowing before changing config:

- it runs `NTFY_AUTH_DEFAULT_ACCESS=deny-all`, so a publish needs a **Bearer
  token**; the token is read at call time from
  `/home/zaid/lifeos/state.json` (`ntfy_token`) rather than copied here;
- **topics are per-user ACLs**, not free-form. `docker exec ntfy ntfy user list`
  is the source of truth. Publishing to a topic the user does not hold answers
  `403`, which looks exactly like a broken server;
- a `403` and a missing token are therefore both returned as reasons, never
  swallowed, and `ops/alerts.ndjson` keeps a receipt line
  (`delivery_of`, `delivered`, `channel`, `message_id`) after every alarm, so
  "did anyone hear this?" is answerable after the fact.

Set `NTFY_URL=off` to disable ntfy deliberately. Prove the wiring with:

```bash
.venv/bin/python -m ops.notify --whoami   # url / topic / token present?
.venv/bin/python -m ops.alert  --test     # a REAL alarm, down the real path
```

## Fuel from the archived cards (F-05, 2026-09-22) — RETIRED 2026-09-23

*History, kept as written.* These units were retired with the fuel
availability vertical on 2026-09-23 (migration 070) and live in
`ops/retired/systemd/`; nothing below runs any more. What follows is what the
units did.


`palestine-v2-fuel-images.{service,timer}` read `@palhubappfuel`'s rendered
cards — the tee spool's text bulletins died on 2026-08-28 and the cards are the
only fuel signal left. Every 10 minutes, up to 60 new cards from the last 6
hours, newest first: a fuel reading is only asserted for `max_assert_seconds`
(3 h), so reading yesterday's cards produces rows that are already expired, and
the channel posts a measured 28.6 cards an hour, so 60 is twelve times the
arrival rate without spending 11 minutes of CPU a run. The run is a no-op when
there is nothing new, and `/v2/fuel/summary` reports how many served readings
came off a card (`basis.image_ocr`) with the warning.

Two things about it are deliberate and worth keeping:

- it writes `--serve`, which means `modality='assertion'` — believed and served.
  That is the one flag that promotes or demotes this feed; drop it and the
  loader writes `quarantined` rows again, which cannot reach a served value.
- it refreshes belief for `fuel_diesel`/`fuel_gasoline` at the end of a run, the
  same scoped refresh the tee loader does, because nothing is served until
  belief has seen it.
