"""Deliver an alarm to a human. Telegram, over a BOT — never the agent2 account.

    from ops.notify import send
    send("telegram-poller has not run in 20 minutes")

    .venv/bin/python -m ops.notify --whoami   # which bot will this reach?
    .venv/bin/python -m ops.notify --test     # prove the wiring end to end

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

# Reuses @abed_hermes_bot rather than minting a new one — see EXTRA_ENV_FILES
# below for why the token still has to be set locally, and the sendMessage note
# for why sharing a bot with the Hermes gateway is safe.
TOKEN_VAR = "ALERT_BOT_TOKEN"
CHAT_VAR = "ALERT_CHAT_ID"

# Short. The watchdog runs on a timer and a hung request must not hold it open —
# a missed alarm costs less than a monitor that stops running.
TIMEOUT_SECONDS = 10

API = "https://api.telegram.org/bot{token}/sendMessage"


# Other .env files to search, in order, after this project's own.
#
# @abed_hermes_bot already exists, so reading its token where it lives would be
# better than copying it — one secret, one place, no half-rotations. It is not
# possible: that bot belongs to the Hermes install owned by the `admin` user
# (/home/admin/.hermes, mode 0700), and every palestine-v2 service runs as
# `zaid`. The isolation is correct and should not be weakened for an alarm
# channel. So the token has to be set locally, and the lookup below still
# prefers any shared file that IS readable.
EXTRA_ENV_FILES = (Path.home() / ".hermes" / ".env",)

# ONLY sendMessage IS USED, AND THAT MATTERS.
#
# Telegram permits exactly one getUpdates consumer per bot. The Hermes gateway
# long-polls @abed_hermes_bot continuously, so a second getUpdates caller would
# steal its updates and break a working assistant to deliver an alarm — the
# monitoring-takes-down-the-monitored failure, aimed at a different system.
# sendMessage has no such constraint: any number of senders can use one bot.
# Nothing in this module calls getUpdates, and nothing in it ever should.
# Finding the chat id is therefore a ONE-OFF human step done another way
# (@userinfobot, or whatever Hermes already has on file), never by polling.

# Names the same value goes by in different projects. Tried in order.
TOKEN_KEYS = (TOKEN_VAR, "TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN", "BOT_TOKEN",
              "HERMES_TELEGRAM_BOT_TOKEN", "TG_BOT_TOKEN")
CHAT_KEYS = (CHAT_VAR, "TELEGRAM_CHAT_ID", "TELEGRAM_ADMIN_CHAT_ID",
             "TELEGRAM_OWNER_ID", "CHAT_ID", "TG_CHAT_ID")


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse a .env into a dict. Never printed, never logged, never copied."""
    out: dict[str, str] = {}
    try:
        text = path.read_text()
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if v:
            out[k.strip()] = v
    return out


def _lookup(names: tuple[str, ...]) -> str | None:
    """First non-empty value among `names`, across env then the .env files."""
    for n in names:
        v = os.environ.get(n)
        if v and v.strip():
            return v.strip()
    for f in (ROOT / ".env", *EXTRA_ENV_FILES):
        vals = _read_env_file(f)
        for n in names:
            if vals.get(n):
                return vals[n]
    return None


def _env(name: str) -> str | None:
    """Kept for the two config vars this module names directly."""
    if name == TOKEN_VAR:
        return _lookup(TOKEN_KEYS)
    if name == CHAT_VAR:
        return _lookup(CHAT_KEYS)
    for f in (ROOT / ".env", *EXTRA_ENV_FILES):
        v = _read_env_file(f).get(name)
        if v:
            return v
    return os.environ.get(name)


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


def whoami() -> dict:
    """Ask Telegram which bot this token belongs to.

    Prints a USERNAME, never the token. The point is to confirm the alarm will
    arrive at @abed_hermes_bot rather than somewhere unexpected — a config that
    silently points at the wrong bot is exactly as bad as no config, and the
    only symptom is an alarm nobody receives.
    """
    token = _env(TOKEN_VAR)
    if not token:
        return {"ok": False, "reason": "no token found"}
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as r:
            p = json.loads(r.read().decode())
        if not p.get("ok"):
            return {"ok": False, "reason": str(p.get("description"))[:200]}
        me = p["result"]
        return {"ok": True, "username": me.get("username"), "name": me.get("first_name")}
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}


def _where(names: tuple[str, ...]) -> str | None:
    """Which key in which file supplied a value — for diagnostics, no value."""
    for n in names:
        if os.environ.get(n, "").strip():
            return f"environment:{n}"
    for f in (ROOT / ".env", *EXTRA_ENV_FILES):
        vals = _read_env_file(f)
        for n in names:
            if vals.get(n):
                return f"{f}:{n}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--whoami", action="store_true",
                    help="report which bot the discovered token belongs to")
    ap.add_argument("--test", action="store_true",
                    help="send a test message and report exactly what happened")
    ap.add_argument("message", nargs="*", default=None)
    a = ap.parse_args()

    if a.whoami:
        print(f"token from : {_where(TOKEN_KEYS) or 'NOT FOUND'}")
        print(f"chat id from: {_where(CHAT_KEYS) or 'NOT FOUND'}")
        w = whoami()
        print(f"bot        : @{w['username']} ({w['name']})" if w["ok"]
              else f"bot        : FAILED — {w['reason']}")
        return 0 if w["ok"] else 1

    if not configured():
        print(f"NOT CONFIGURED. Set {TOKEN_VAR} and {CHAT_VAR} in "
              f"{ROOT}/.env (chmod 600).\n\n"
              f"Reuse @abed_hermes_bot — no new bot needed:\n"
              f"  1. TOKEN: @BotFather -> /mytoken -> pick @abed_hermes_bot.\n"
              f"     (Its live copy lives in the admin-owned Hermes install,\n"
              f"      /home/admin/.hermes, which this project cannot read and\n"
              f"      should not be given access to.)\n"
              f"  2. CHAT ID: your own Telegram numeric id — @userinfobot will\n"
              f"     tell you. Do NOT use /getUpdates: the Hermes gateway\n"
              f"     long-polls this bot and Telegram allows only one such\n"
              f"     consumer, so you would break Hermes to configure an alarm.\n"
              f"     Sending is unaffected — any number of senders may share a\n"
              f"     bot, which is why reusing this one is safe.\n\n"
              f"Then: .venv/bin/python -m ops.notify --whoami\n"
              f"      .venv/bin/python -m ops.notify --test\n\n"
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
