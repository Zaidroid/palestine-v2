"""Deliver an alarm to a human. Telegram, over a BOT — never the agent2 account.

    from ops.notify import send
    send("telegram-poller has not run in 20 minutes")

    .venv/bin/python -m ops.notify --test      # prove the wiring end to end

WHY THIS EXISTS
The poller died on 2026-08-02 at 14:10 and stayed dead for SEVENTEEN HOURS.
Every detection mechanism worked perfectly: the unit exited non-zero, systemd's
OnFailure fired the alarm three times, the watchdog reported `not_running` for
1,051 consecutive minutes, and ops/alerts.ndjson recorded all of it. Detection
was never the gap. The alarm went into a file and a journal, and nobody reads a
file. There was no doorbell.

A BOT, NOT THE ACCOUNT
ops/alert.py has said since P3.1 that alarms must not go over the agent2
Telegram account — "the scarcest asset in the project", and machine chatter is
how it gets rate-limited or banned. That still holds, and a bot is not a
loophole around it: a BotFather bot is a separate identity with its own token,
it uses the plain HTTPS Bot API rather than MTProto, and it opens no Telethon
session. There is no session file to share, so the rule that two clients must
never share one session is not even in play. If the bot gets throttled, agent2
is untouched.

THIS MUST NEVER BREAK WHAT IT WATCHES
Monitoring that can take down the thing it monitors is worse than no
monitoring. Every failure here is swallowed and reported as a return value:
a wrong token, no network, a hung Telegram, a missing config. The watchdog's
own exit status must depend on what it FOUND, never on whether the message got
out — the same rule ops/with-heartbeat.sh already applies to the heartbeat
write.

UNCONFIGURED IS A NORMAL STATE, NOT AN ERROR
Until the two values are set the alarm still lands in ops/alerts.ndjson and the
journal exactly as before. Nothing regresses, delivery is simply absent, and
`--test` says so plainly instead of pretending.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# From @BotFather (`/newbot`), and from the bot itself once you have sent it a
# message: https://api.telegram.org/bot<TOKEN>/getUpdates shows your chat id.
TOKEN_VAR = "ALERT_BOT_TOKEN"
CHAT_VAR = "ALERT_CHAT_ID"

# Short. The watchdog runs on a timer and a hung request must not hold it open —
# a missed alarm costs less than a monitor that stops running.
TIMEOUT_SECONDS = 10

API = "https://api.telegram.org/bot{token}/sendMessage"


def _env(name: str) -> str | None:
    """Environment first, then .env — systemd units do not source .env."""
    v = os.environ.get(name)
    if v:
        return v.strip()
    f = ROOT / ".env"
    if not f.exists():
        return None
    for line in f.read_text().splitlines():
        line = line.strip()
        if line.startswith(f"{name}=") and not line.startswith("#"):
            return line.split("=", 1)[1].strip()
    return None


def configured() -> bool:
    return bool(_env(TOKEN_VAR) and _env(CHAT_VAR))


def send(text: str, *, silent: bool = False) -> dict:
    """Deliver `text`. Returns {"ok": bool, "reason": str}. Never raises."""
    token, chat = _env(TOKEN_VAR), _env(CHAT_VAR)
    if not token or not chat:
        return {"ok": False, "reason": f"unconfigured ({TOKEN_VAR}/{CHAT_VAR})"}

    # 4096 is Telegram's hard limit and a truncated alarm still names the fault.
    body = urllib.parse.urlencode({
        "chat_id": chat,
        "text": text[:3900],
        "disable_notification": "true" if silent else "false",
    }).encode()

    try:
        req = urllib.request.Request(API.format(token=token), data=body)
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:
            payload = json.loads(r.read().decode())
        return ({"ok": True, "reason": ""} if payload.get("ok")
                else {"ok": False, "reason": str(payload.get("description"))[:200]})
    except urllib.error.HTTPError as exc:
        # The body carries Telegram's actual complaint ("chat not found",
        # "Unauthorized"), which is the whole diagnostic. The status alone is
        # not enough to fix anything.
        try:
            why = json.loads(exc.read().decode()).get("description", "")
        except Exception:                                       # noqa: BLE001
            why = exc.reason
        return {"ok": False, "reason": f"HTTP {exc.code}: {str(why)[:200]}"}
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true",
                    help="send a test message and report exactly what happened")
    ap.add_argument("message", nargs="*", default=None)
    a = ap.parse_args()

    if not configured():
        print(f"NOT CONFIGURED. Set {TOKEN_VAR} and {CHAT_VAR} in .env.\n\n"
              f"  1. Message @BotFather on Telegram, send /newbot, follow it.\n"
              f"     It replies with a token like 123456:AAH....\n"
              f"  2. Send your new bot any message (it cannot message you first).\n"
              f"  3. Open https://api.telegram.org/bot<TOKEN>/getUpdates and read\n"
              f"     result[0].message.chat.id — that is {CHAT_VAR}.\n\n"
              f"Alarms keep landing in ops/alerts.ndjson meanwhile; only "
              f"delivery is missing.", file=sys.stderr)
        return 1

    text = " ".join(a.message) if a.message else (
        "palestine-v2 alert test — if you can read this, the doorbell works.")
    r = send(text)
    print("sent" if r["ok"] else f"FAILED: {r['reason']}",
          file=sys.stdout if r["ok"] else sys.stderr)
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
