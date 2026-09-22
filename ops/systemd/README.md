# systemd units, in version control

Copies of everything installed under `/etc/systemd/system/palestine-v2-*`.

## Why these are here

The nightly backup covers the database. It does not cover the twelve unit files
and eight drop-ins that decide *when anything runs at all* — those lived only in
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
    sudo systemctl enable --now palestine-v2-poller.service
    sudo systemctl enable --now palestine-v2-{checkpoints,news,fuel,external}.timer
    sudo systemctl enable --now palestine-v2-{backup,restore-test,watchdog}.timer
    sudo systemctl enable --now palestine-v2-{accuracy,checkpoint-learn}.timer
    sudo systemctl enable --now palestine-v2-analyst.service

## Checking they have not drifted

    diff -r <(ls /etc/systemd/system/palestine-v2-*) <(ls ops/systemd/palestine-v2-*)
    for f in ops/systemd/palestine-v2-*.{service,timer}; do
      diff -q "$f" "/etc/systemd/system/$(basename "$f")" || echo "DRIFT: $f"
    done

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

`palestine-v2-watchdog.service` carries `SuccessExitStatus=0 1` in the base unit
rather than a drop-in: the watchdog exits 1 when it *finds* a fault, which is a
successful run with a bad result. Without it, every detected fault would also
mark the watchdog failed and raise a second alarm about the alarm.

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
