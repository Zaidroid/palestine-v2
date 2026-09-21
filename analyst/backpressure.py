"""Whether the PC is available to think, and what to do when it is not.

The analyst's model organs run on the MainPC's llama-swap. That machine is also
the one Zaid plays on, and a game watcher stops the inference server when a game
starts. So the PC refusing a connection is the NORMAL state of a healthy system,
not an incident: `http://100.114.104.95:8480/running` answering nothing means
"someone is playing", and the correct response is to sleep and resume from the
watermark, never to alarm and never to hold up ingestion.

    available()  -> (True,  "1 model loaded: gpt-oss-20b")
                 -> (False, "connection refused — the PC is off or gaming")

WHY THE PROBE IS NOT A MODEL CALL
Asking the model a question to find out whether the model is there costs a load
of the model. `/running` is llama-swap's own list of what is resident; it
answers in milliseconds, it does not wake anything, and an empty list is still a
healthy answer — the port is up, nothing is loaded yet, and the first real call
will swap a model in.

WHY A REFUSED PORT IS NOT A FAULT AND AN UNREADABLE ONE IS NOT HEALTH
This returns two things, and the loop reports both. "Paused: the PC is gaming"
and "the probe itself is broken" must never collapse into one word — the first
is the system working as designed and the second is a blind spot.
"""
from __future__ import annotations

import os

# Tailnet address of the MainPC's llama-swap. Overridable so a test, or a move
# of the brain, does not need a code change.
LLAMA_SWAP_URL = os.environ.get("LLAMA_SWAP_URL", "http://100.114.104.95:8480")

# Short on purpose: this runs before every model batch, and a PC that takes
# three seconds to say hello is a PC that is busy rendering a game.
TIMEOUT_S = 3.0


def available(url: str | None = None, timeout: float = TIMEOUT_S) -> tuple[bool, str]:
    """(usable, a sentence saying why). Never raises."""
    base = (url or LLAMA_SWAP_URL).rstrip("/")
    try:
        import httpx
        r = httpx.get(f"{base}/running", timeout=timeout)
    except Exception as exc:                                    # noqa: BLE001
        return False, (f"{base} did not answer ({type(exc).__name__}) — the PC "
                       f"is off, gaming, or off the tailnet")
    if r.status_code != 200:
        return False, f"{base}/running answered {r.status_code}"
    try:
        loaded = [m.get("model") for m in (r.json().get("running") or [])]
    except ValueError:
        return False, f"{base}/running answered 200 but not JSON — something " \
                      f"else is listening on that port"
    if not loaded:
        return True, "llama-swap is up with no model resident; the first call swaps one in"
    return True, f"llama-swap is up: {', '.join(str(m) for m in loaded)}"
