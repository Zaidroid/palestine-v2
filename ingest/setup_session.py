"""Telegram session setup for Palestine v2 — NON-INTERACTIVE, two steps.

Telethon's default flow calls input() for the login code. Claude Code's `!`
prefix runs commands without a TTY, so input() gets EOF immediately and the
process dies — taking the phone_code_hash with it. This splits the flow so each
step is a complete, non-interactive command:

  step 1 — ask Telegram to send a code (saves phone_code_hash to disk):
      ./.venv/bin/python -m ingest.setup_session --request-code

  step 2 — sign in with the code that arrived in your Telegram app:
      ./.venv/bin/python -m ingest.setup_session --code 12345
      ./.venv/bin/python -m ingest.setup_session --code 12345 --password 'your2fa'

  status:
      ./.venv/bin/python -m ingest.setup_session --status

The phone_code_hash is cached so re-running step 2 with a corrected code does
NOT trigger a second code request — repeated requests are what earn a FloodWait,
and this account is brand new and fragile.

WHY A SEPARATE ACCOUNT
v1 holds the only proven session; two Telethon clients sharing one session file
corrupt it. A different phone number gives v2 its own client and leaves v1
untouched. New api_id/api_hash on the SAME number would not — that is the same
account wearing a different hat.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSION_DIR = ROOT / "data" / "session"
SESSION = SESSION_DIR / "v2_ingest"
PENDING = SESSION_DIR / ".pending_login.json"
V1_PHONE = "+970595463664"


def _env() -> dict[str, str]:
    env: dict[str, str] = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.update(os.environ)
    return env


def _creds():
    e = _env()
    api_id = int(e.get("V2_TELEGRAM_API_ID", "0") or 0)
    api_hash = e.get("V2_TELEGRAM_API_HASH", "")
    phone = e.get("V2_TELEGRAM_PHONE", "").replace(" ", "")
    if not (api_id and api_hash and phone):
        print("Missing V2_TELEGRAM_API_ID / _API_HASH / _PHONE in .env")
        raise SystemExit(1)
    if phone == V1_PHONE:
        print("REFUSING: this is v1's phone number. A second session on that "
              "account risks the one v1 depends on.")
        raise SystemExit(1)
    return api_id, api_hash, phone


async def _client(api_id: int, api_hash: str):
    from telethon import TelegramClient
    from ingest.session_lock import acquire          # SessionBusy propagates: one client per session (F213)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    acquire(SESSION, who="setup_session")
    c = TelegramClient(str(SESSION), api_id, api_hash)
    await c.connect()
    return c


async def request_code() -> int:
    api_id, api_hash, phone = _creds()
    c = await _client(api_id, api_hash)
    if await c.is_user_authorized():
        me = await c.get_me()
        print(f"Already authorised as {me.first_name} (id={me.id}). Nothing to do.")
        await c.disconnect()
        return 0
    sent = await c.send_code_request(phone)
    PENDING.write_text(json.dumps({"phone": phone, "hash": sent.phone_code_hash}))
    try:
        PENDING.chmod(0o600)
    except OSError:
        pass
    await c.disconnect()
    print(f"Code sent to {phone} (check your Telegram app).")
    print("\nNow run:")
    print("  ./.venv/bin/python -m ingest.setup_session --code 12345")
    print("  (add --password 'xxx' if that account has 2FA)")
    return 0


async def sign_in(code: str, password: str | None) -> int:
    from telethon.errors import (PhoneCodeExpiredError, PhoneCodeInvalidError,
                                 SessionPasswordNeededError)
    api_id, api_hash, phone = _creds()
    if not PENDING.exists():
        print("No pending login. Run --request-code first.")
        return 1
    pending = json.loads(PENDING.read_text())

    c = await _client(api_id, api_hash)
    try:
        await c.sign_in(phone=pending["phone"], code=code.strip(),
                        phone_code_hash=pending["hash"])
    except SessionPasswordNeededError:
        if not password:
            print("This account has 2FA. Re-run with --password 'your-password'.")
            await c.disconnect()
            return 1
        await c.sign_in(password=password)
    except PhoneCodeInvalidError:
        print("Invalid code. Re-run --code with the correct digits "
              "(no new code request needed).")
        await c.disconnect()
        return 1
    except PhoneCodeExpiredError:
        print("Code expired. Run --request-code again.")
        PENDING.unlink(missing_ok=True)
        await c.disconnect()
        return 1

    me = await c.get_me()
    await c.disconnect()
    PENDING.unlink(missing_ok=True)
    try:
        Path(f"{SESSION}.session").chmod(0o600)
    except OSError:
        pass
    print(f"Authenticated as {me.first_name} (@{me.username or '—'}) id={me.id}")
    print(f"Session: {SESSION}.session")
    print("\nNext: ./.venv/bin/python -m ingest.discover_channels --all")
    return 0


async def status() -> int:
    api_id, api_hash, phone = _creds()
    if not Path(f"{SESSION}.session").exists():
        print(f"No session file. Start with --request-code (phone {phone}).")
        return 1
    c = await _client(api_id, api_hash)
    ok = await c.is_user_authorized()
    if ok:
        me = await c.get_me()
        print(f"Authorised as {me.first_name} (@{me.username or '—'}) id={me.id}")
    else:
        print("Session exists but is NOT authorised. Run --request-code.")
    await c.disconnect()
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request-code", action="store_true")
    ap.add_argument("--code")
    ap.add_argument("--password")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    if a.request_code:
        return asyncio.run(request_code())
    if a.code:
        return asyncio.run(sign_in(a.code, a.password))
    if a.status:
        return asyncio.run(status())
    ap.print_help()
    print("\nTypical flow:\n"
          "  --request-code            # Telegram sends a code to your app\n"
          "  --code 12345              # sign in with it\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
