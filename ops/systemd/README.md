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
