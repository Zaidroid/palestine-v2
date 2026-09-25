"""Operability: the shell steps, the wrapper and the unit files, run for real.

    python3 -m pytest tests/test_ops_hardening.py -q

The rule every test here defends is the one HANDOFF §4 states and this repo
has broken several ways at once: SILENCE IS FAILURE. A step that cannot fail,
a crash that exits like a finding, a unit with no OnFailure, a wrapper that
never hears the exit code it was told to accept — each one reads, from
outside, exactly like a healthy system.

The scripts are exercised in a sandbox: a copy of the script under a temporary
"repo" whose .venv/bin/python is a stub that records its arguments, with
`docker`, `sudo` and `curl` stubbed on PATH where a script needs them. Nothing
here touches a database, a unit, or the network.
"""
from __future__ import annotations

import configparser
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

UNITS = ROOT / "ops" / "systemd"

STUB_PYTHON = """#!/bin/sh
# Records every call; fails the module named in STUB_FAIL, exits STUB_RC for
# the module named in STUB_RC_MODULE.
root="$(cd "$(dirname "$0")/../.." && pwd)"
printf '%s\\n' "$*" >> "$root/calls.log"
for m in ${STUB_FAIL:-}; do [ "$2" = "$m" ] && exit 1; done
[ -n "${STUB_RC_MODULE:-}" ] && [ "$2" = "$STUB_RC_MODULE" ] && exit "${STUB_RC:-0}"
exit 0
"""


def _exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _sandbox(tmp_path: Path, *scripts: str, source: Path = ROOT) -> Path:
    repo = tmp_path / "repo"
    for name in ("with-heartbeat.sh", *scripts):
        _exe(repo / "ops" / name, (source / "ops" / name).read_text())
    _exe(repo / ".venv" / "bin" / "python", STUB_PYTHON)
    return repo


def _calls(repo: Path) -> list[str]:
    log = repo / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def _beats(repo: Path, name: str) -> list[str]:
    return [c for c in _calls(repo) if c.startswith(f"-m ops.heartbeat {name} ")]


def _run(cmd, env=None, **kw) -> subprocess.CompletedProcess:
    full = {**os.environ, **(env or {})}
    full.pop("OK_EXIT_CODES", None)
    for k, v in (env or {}).items():
        full[k] = v
    return subprocess.run(cmd, capture_output=True, text=True, env=full,
                          timeout=60, **kw)


# ── F287: the wrapper records the attempt, and a kill, not only a return ─────

def test_the_wrapper_stamps_the_attempt_before_the_job_runs(tmp_path):
    """`last_attempt` written only after the job returns is never written for a
    job systemd kills — and then the view calls it `not_running`."""
    repo = _sandbox(tmp_path)
    marker = tmp_path / "ran"
    r = _run([str(repo / "ops" / "with-heartbeat.sh"), "j", "60", "90", "--",
              "sh", "-c", f"cat '{repo}/calls.log' > '{marker}'"])
    assert r.returncode == 0
    seen_while_running = marker.read_text()
    assert "--attempt" in seen_while_running, \
        "the attempt must be on record BEFORE the job starts"
    assert _beats(repo, "j")[-1] == "-m ops.heartbeat j --interval 60 --grace 90"


def test_a_job_killed_by_sigterm_is_recorded_as_killed(tmp_path):
    """systemd's TimeoutStartSec SIGTERMs the whole cgroup — wrapper and job
    together. The wrapper used to die with it and write nothing."""
    repo = _sandbox(tmp_path)
    env = {**os.environ}
    env.pop("OK_EXIT_CODES", None)
    p = subprocess.Popen([str(repo / "ops" / "with-heartbeat.sh"), "j", "60", "90",
                          "--", "sleep", "30"], start_new_session=True, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.time() + 10
    while time.time() < deadline and not any("--attempt" in c for c in _calls(repo)):
        time.sleep(0.05)
    time.sleep(0.3)                       # let `sleep` start
    os.killpg(p.pid, signal.SIGTERM)      # the whole group, as systemd does
    rc = p.wait(20)
    assert rc == 143
    beats = _beats(repo, "j")
    assert any("--attempt" in b for b in beats)
    assert "--fail killed by SIGTERM" in beats[-1], beats


# ── F067: OK_EXIT_CODES has to reach the WRAPPER ─────────────────────────────

def test_ok_exit_codes_passed_through_env_never_reach_the_wrapper(tmp_path):
    """The mechanism of F067, pinned: `-- env OK_EXIT_CODES=1 cmd` gives the
    variable to the child; the wrapper that reads it never sees it."""
    repo = _sandbox(tmp_path)
    wrap = str(repo / "ops" / "with-heartbeat.sh")
    _run([wrap, "a", "60", "90", "--", "env", "OK_EXIT_CODES=1", "sh", "-c", "exit 1"])
    assert "--fail exited 1" in _beats(repo, "a")[-1]
    _run([wrap, "b", "60", "90", "--", "sh", "-c", "exit 1"], env={"OK_EXIT_CODES": "1"})
    assert _beats(repo, "b")[-1] == "-m ops.heartbeat b --interval 60 --grace 90"


def _unit_for_script(script: str) -> configparser.ConfigParser | None:
    for f in sorted(UNITS.glob("*.service")):
        cp = _unit(f)
        if cp.has_option("Service", "ExecStart") and \
           cp.get("Service", "ExecStart").endswith(f"/ops/{script}"):
            return cp
    return None


def _unit(f: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    cp.read(f)
    for drop in sorted((f.parent / (f.name + ".d")).glob("*.conf")):
        cp.read(drop)
    return cp


def test_every_ok_exit_code_is_exported_and_systemd_agrees():
    """Three places must agree on "this exit code means it worked": the
    script's EXPORTED OK_EXIT_CODES (what the heartbeat hears), and what
    systemd hears — the unit's SuccessExitStatus, or the script mapping the
    code to 0 itself. mcp-audit had the first in the wrong process and the
    second missing, so every night with a finding was a failed job twice."""
    checked = 0
    for sh in sorted((ROOT / "ops").glob("*.sh")):
        text = sh.read_text()
        live = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        if "OK_EXIT_CODES" not in live or sh.name == "with-heartbeat.sh":
            continue
        checked += 1
        assert not re.search(r"\benv\s+(\S+\s+)*OK_EXIT_CODES=", live), \
            f"{sh.name} passes OK_EXIT_CODES to the child through env — the wrapper never sees it"
        m = re.search(r"^export OK_EXIT_CODES=\"?([0-9 ]+)\"?$", live, re.M)
        assert m, f"{sh.name} must `export OK_EXIT_CODES=...` before the wrapper runs"
        unit = _unit_for_script(sh.name)
        assert unit is not None, f"no unit runs {sh.name}"
        success = unit.get("Service", "SuccessExitStatus", fallback="0").split()
        for code in m.group(1).split():
            mapped = re.search(rf"^\s*(\S+\|)?{code}(\|\S+)?\)\s*exit 0", live, re.M)
            assert code in success or mapped, \
                (f"{sh.name}: exit {code} is success to the heartbeat but a FAILURE "
                 f"to systemd — OnFailure pushes a second alarm for a working run")
    assert checked >= 2, "the watchdog and mcp-audit both use OK_EXIT_CODES"


# ── F069: a crash and a found fault are different exits, all the way out ─────

@pytest.mark.parametrize("py_rc, unit_rc, beat_ok", [
    (0, 0, True),      # all green
    (3, 0, True),      # ran, found faults — raised by the watchdog itself
    (1, 70, False),    # crashed: an uncaught exception
])
def test_the_watchdog_script_keeps_a_crash_apart_from_a_finding(tmp_path, py_rc,
                                                               unit_rc, beat_ok):
    repo = _sandbox(tmp_path, "watchdog.sh")
    r = _run([str(repo / "ops" / "watchdog.sh")],
             env={"STUB_RC_MODULE": "ops.watchdog", "STUB_RC": str(py_rc)})
    assert r.returncode == unit_rc, r.stderr
    last = _beats(repo, "watchdog")[-1]
    assert ("--fail" not in last) is beat_ok, last
    # 70 is a failure under the unit file installed TODAY (SuccessExitStatus=0 1)
    # as well as under the one in ops/systemd.
    assert (unit_rc in (0, 1)) is beat_ok


# ── F068 / F279: the Valhalla IP sync ────────────────────────────────────────

def _valhalla(tmp_path, source: Path = ROOT):
    repo = _sandbox(tmp_path, "sync-valhalla-ip.sh", source=source)
    stubs = tmp_path / "bin"
    _exe(stubs / "docker", '#!/bin/sh\n[ -n "$FAKE_IP" ] || exit 1\necho "$FAKE_IP"\n')
    _exe(stubs / "sudo", f'#!/bin/sh\necho "$*" >> "{tmp_path}/sudo.log"\n'
                         'exit "${FAKE_SUDO_RC:-0}"\n')
    _exe(stubs / "curl", "#!/bin/sh\nexit 0\n")
    (tmp_path / "home").mkdir(exist_ok=True)
    env = {"PATH": f"{stubs}:{os.environ['PATH']}", "HOME": str(tmp_path / "home"),
           "XDG_STATE_HOME": str(tmp_path / "home" / ".state")}
    envfile = repo / ".env"
    envfile.write_text("PGPASSWORD=secret\nVALHALLA_URL=http://172.22.0.4:8002\n"
                       "OTHER=kept\n")
    envfile.chmod(0o600)

    def run(ip="172.22.0.5", sudo_rc=0):
        return _run([str(repo / "ops" / "sync-valhalla-ip.sh")],
                    env={**env, "FAKE_IP": ip, "FAKE_SUDO_RC": str(sudo_rc)})

    def restarts():
        log = tmp_path / "sudo.log"
        return log.read_text().count("restart palestine-v2-api") if log.exists() else 0

    return repo, envfile, run, restarts


def test_a_moved_ip_is_written_atomically_and_the_api_restarted(tmp_path):
    repo, envfile, run, restarts = _valhalla(tmp_path)
    inode = envfile.stat().st_ino
    r = run()
    assert r.returncode == 0, r.stderr
    assert envfile.read_text() == ("PGPASSWORD=secret\nVALHALLA_URL=http://172.22.0.5:8002\n"
                                   "OTHER=kept\n")
    assert stat.S_IMODE(envfile.stat().st_mode) == 0o600
    assert envfile.stat().st_ino != inode, \
        ".env must be renamed into place, never truncated and rewritten"
    assert restarts() == 1
    assert not list(repo.glob(".env.valhalla-*")), "the temp copy must not be left behind"
    beats = _beats(repo, "valhalla-ip")
    assert beats and beats[-1] == "-m ops.heartbeat valhalla-ip --interval 900 --grace 1800"


def test_a_failed_restart_keeps_failing_until_the_api_has_restarted(tmp_path):
    """The silent state F068 describes: .env already says the new IP, the API
    process still holds the old one, and the next tick used to see a match and
    exit 0 forever while routing answered 'unavailable'."""
    repo, envfile, run, restarts = _valhalla(tmp_path)
    assert run(sudo_rc=1).returncode == 1
    assert "172.22.0.5" in envfile.read_text()
    assert "--fail" in _beats(repo, "valhalla-ip")[-1]
    r = run(sudo_rc=1)
    assert r.returncode == 1, "a restart still owed must keep failing, not read as in sync"
    assert "RESTART FAILED" in r.stderr
    assert run(sudo_rc=0).returncode == 0
    n = restarts()
    assert run(sudo_rc=0).returncode == 0
    assert restarts() == n, "once restarted, nothing is owed"


def test_a_missing_line_is_added_once_not_restarted_forever(tmp_path):
    repo, envfile, run, restarts = _valhalla(tmp_path)
    envfile.write_text("PGPASSWORD=secret\nOTHER=kept")          # no trailing newline
    assert run().returncode == 0
    assert envfile.read_text() == ("PGPASSWORD=secret\nOTHER=kept\n"
                                   "VALHALLA_URL=http://172.22.0.5:8002\n")
    assert run().returncode == 0
    assert restarts() == 1, "the API must not be restarted on every tick"


def test_a_missing_container_fails_loudly(tmp_path):
    repo, envfile, run, restarts = _valhalla(tmp_path)
    r = run(ip="")
    assert r.returncode == 1 and "not running" in r.stderr
    assert "--fail" in _beats(repo, "valhalla-ip")[-1]
    assert restarts() == 0


# ── F511: the unit files ─────────────────────────────────────────────────────

def _services():
    return [f for f in sorted(UNITS.glob("*.service")) if "@" not in f.name]


def test_every_unit_that_can_fail_alarms_when_it_does():
    """palestine-v2-valhalla-ip.service had no OnFailure anywhere — the only
    one — and HANDOFF said 'on all twelve units'. Checked per unit, in the
    file or its drop-ins, so the claim cannot drift from the files again."""
    assert _services()
    for f in _services():
        cp = _unit(f)
        assert cp.get("Unit", "OnFailure", fallback="").startswith("palestine-v2-alert@"), \
            f"{f.name} can fail without anyone being told"


def test_every_timer_runs_a_job_the_watchdog_expects():
    """A timer whose job writes no heartbeat — or writes one under a name the
    watchdog does not hold — is unwatched from its first tick. valhalla-ip was
    both, for seven weeks."""
    from ops.watchdog import EXPECTED_JOBS
    # Starts another unit (palestine-v2-maintain.service), which is watched.
    starts_another_unit = {"palestine-v2-maintain-retry.service"}
    beat = re.compile(r'with-heartbeat\.sh"?\s+([a-z0-9-]+)\s+\d+\s+\d+'
                      r'|ops\.heartbeat\s+([a-z0-9-]+)')
    timers = sorted(UNITS.glob("*.timer"))
    assert timers
    for t in timers:
        tcp = _unit(t)
        svc = tcp.get("Timer", "Unit", fallback=t.name.replace(".timer", ".service"))
        if svc in starts_another_unit:
            continue
        exec_start = _unit(UNITS / svc).get("Service", "ExecStart")
        text = exec_start
        script = re.search(r"/ops/([\w.-]+\.sh)$", exec_start)
        if script:
            text += "\n" + (ROOT / "ops" / script.group(1)).read_text()
        names = {a or b for a, b in beat.findall(text)}
        assert names, f"{t.name} -> {svc} writes no heartbeat at all"
        assert names & set(EXPECTED_JOBS), \
            f"{t.name}: heartbeat {names} is not in the watchdog's EXPECTED_JOBS"
