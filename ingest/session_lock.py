"""Hard rule 4, enforced: ONE Telethon client per session file.

Two clients sharing one auth key can invalidate the account, and the account
is the scarcest asset in the project. Until now nothing enforced it: discovery,
`setup_session --status` and the poller's CLI modes all opened the live
session with no lock (audit 2026-09-25 F213). Every opener now takes an
exclusive flock on `<session>.lock` for the life of its process; a second
opener is told which pid holds it and exits non-zero.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSION = ROOT / "data" / "session" / "v2_ingest"

_HELD: dict[str, object] = {}          # path -> open file, kept for the process


class SessionBusy(RuntimeError):
    def __init__(self, holder: str, path: Path):
        super().__init__(f"the Telegram session is held by {holder} — one client per "
                         f"session file; stop it first ({path})")
        self.holder = holder


def acquire(session: Path | str = SESSION, *, who: str = "") -> Path:
    """Take the lock for this process (idempotent). Raises SessionBusy."""
    lock = Path(f"{session}.lock")
    key = str(lock)
    if key in _HELD:
        return lock
    lock.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.seek(0)
        holder = fh.read().strip() or "another process"
        fh.close()
        raise SessionBusy(holder, lock) from None
    fh.seek(0); fh.truncate()
    fh.write(f"pid {os.getpid()} {who}".strip() + "\n"); fh.flush()
    _HELD[key] = fh
    return lock


def release(session: Path | str = SESSION) -> None:
    key = str(Path(f"{session}.lock"))
    fh = _HELD.pop(key, None)
    if fh is not None:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()
