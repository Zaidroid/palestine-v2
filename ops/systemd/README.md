# systemd units, in version control

Copies of everything installed under `/etc/systemd/system/palestine-v2-*`.

## Why these are here

The nightly backup covers the database. It does not cover the unit files and
drop-ins that decide *when anything runs at all* — those lived only in
`/etc`, owned by root, on the same disk the backups exist to survive losing. A
restore would have brought back every row and left nothing to collect the next
one, and the gap would only have been discovered during a rebuild, which is the
worst moment to discover it.

They are copies, not the installed originals: systemd reads `/etc`. Treat this
directory as the record, and keep the two in step.

## Installing

    sudo cp ops/systemd/palestine-v2-*.{service,timer} /etc/systemd/system/
    for d in ops/systemd/*.d; do
      sudo mkdir -p "/etc/systemd/system/$(basename "$d")"
      sudo cp "$d"/*.conf "/etc/systemd/system/$(basename "$d")/"
    done
    sudo systemctl daemon-reload
    # the three daemons, then EVERY timer in this directory — the list is the
    # directory, never a hand-typed subset (audit F159/F279: the old block
    # enabled a retired timer and left ten live ones out)
    sudo systemctl enable --now palestine-v2-{api,poller,analyst}.service
    sudo systemctl enable --now $(basename -a ops/systemd/*.timer)

Timers in this directory today: accuracy, backup, checkpoint-learn, checkpoints, crowd, databank, external, gaza, maintain-retry, maintain, mcp-audit, measure-review, news, palhub-roads, press-links, restore-test, rollup, scout, valhalla-ip, watchdog.

## Checking they have not drifted

    # every file here, drop-ins included, against /etc (audit F279)
    (cd ops/systemd && find . -type f -name '*.service' -o -type f -name '*.timer' -o -type f -name '*.conf') \
      | sed 's#^\./##' | while read -r f; do
          diff -q "ops/systemd/$f" "/etc/systemd/system/$f" >/dev/null 2>&1 || echo "DRIFT: $f"
        done
    # and anything installed that this directory does not carry
    ls /etc/systemd/system/palestine-v2-* 2>/dev/null | xargs -n1 basename \
      | while read -r u; do [ -e "ops/systemd/$u" ] || echo "UNTRACKED: $u"; done

## What the drop-ins carry

The `.d/` directories hold the P3.1 wiring, kept separate from the base units so
the monitoring can be reviewed as one change rather than scattered across twelve
files:

  * `onfailure.conf` — `OnFailure=palestine-v2-alert@%n.service` on every unit.
    Before this, only the two backup units reported failure; everything else
    failed into the journal, where nothing was reading.
  * `palestine-v2-poller.service.d/watchdog.conf` — `OnFailure=`, plus
    `RestartPreventExitStatus=2`. Exit 2 means the Telegram session is no longer
    authorised; restarting cannot fix that, and reconnecting an unauthorised
    session repeatedly is exactly what would put the account at risk.
  * `palestine-v2-poller.service.d/unbuffered.conf` — `PYTHONUNBUFFERED=1`, so a
    long-running service's output reaches the journal before it exits.

`palestine-v2-watchdog.service` carries `SuccessExitStatus=0 3` in the base unit
rather than a drop-in: the watchdog exits 3 when it *finds* a fault, which is a
successful run with a bad result, and 1 when it itself crashed (audit F066).
Without it, every detected fault would also mark the watchdog failed and raise
a second alarm about the alarm. `palestine-v2-mcp-audit.service` likewise
accepts exit 1 (criticals found).

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

## Retired: fuel from the archived cards (F-05, 2026-09-22 → retired 2026-09-23)

The `palestine-v2-fuel-images` unit and its drop-in are gone from this
directory (audit F159): the fuel-card vertical was retired on 2026-09-23. The
paragraph below is kept as history of how it worked.

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
