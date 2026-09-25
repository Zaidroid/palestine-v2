"""P3.1 — the properties that make a watchdog worth having.

    ./.venv/bin/python -m pytest tests/test_watchdog.py -q

The failure these defend against is not "the watchdog crashes". It is the
watchdog running happily and reporting health it did not establish, which is
indistinguishable from a healthy system right up until the moment it matters.
That is not hypothetical here: on 2026-08-01 the Telegram poller was dead for
eight hours while systemd, /health and the news classifier all reported normal
operation, and it was found by hand.

So most of these assert that specific things are NOT silently tolerated.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops import alert, watchdog                                     # noqa: E402
from ops.watchdog import (EXPECTED_JOBS, FEED_COLLECTOR,            # noqa: E402
                          LATE_MULTIPLE, MIN_ARRIVALS,
                          WEAK_THRESHOLD_SECONDS, feed_checks, job_checks)


# ── the registry must match what the jobs actually do ────────────────────────

def test_expected_jobs_match_the_cadence_each_script_reports():
    """EXPECTED_JOBS duplicates the numbers in the shell scripts on purpose.

    A timer whose interval changes without its watchdog entry changing would
    otherwise be judged against the old cadence forever — quietly, and in the
    safe-looking direction if the interval got shorter. The duplication only
    earns its keep if something checks it, so this is that something.
    """
    pattern = re.compile(r"with-heartbeat\.sh\s+(\S+)\s+(\d+)\s+(\d+)")
    found: dict[str, tuple[int, int]] = {}
    for sh in (ROOT / "ops").glob("*.sh"):
        for name, iv, gr in pattern.findall(sh.read_text()):
            found[name] = (int(iv), int(gr))

    assert found, "no wrapped jobs found — has with-heartbeat.sh been renamed?"
    for name, (iv, gr) in found.items():
        assert name in EXPECTED_JOBS, f"{name} is wrapped but not in EXPECTED_JOBS"
        assert EXPECTED_JOBS[name] == (iv, gr), (
            f"{name}: script says {(iv, gr)}, EXPECTED_JOBS says {EXPECTED_JOBS[name]}")


def test_every_job_that_reports_inline_is_also_registered():
    """Two jobs call ops.heartbeat directly rather than through the wrapper —
    the poller, which beats per cycle rather than per run, and ingest-external,
    which counts partial step failures. Both must still be in the registry, or
    the watchdog cannot notice them going missing."""
    for name in ("telegram-poller", "ingest-external"):
        assert name in EXPECTED_JOBS


def test_every_mapped_collector_is_a_registered_job():
    """A feed pointing at a collector that does not exist would silently fall
    through to 'its collector is not healthy' forever."""
    for kind, collector in FEED_COLLECTOR.items():
        assert collector in EXPECTED_JOBS, f"{kind} -> unknown collector {collector}"


# ── classification: the part that decides whether anyone is told ─────────────

def _checks(cadence, ages, jobs, monkeypatch):
    """Run feed_checks against fabricated cadence/current rows."""
    monkeypatch.setattr(watchdog, "_q", lambda sql: [
        {"state_kind": k, "latest": None, "age_seconds": v} for k, v in ages.items()
    ] if "max(observed_at)" in sql else [])
    return {c["name"]: c for c in feed_checks(jobs, cadence)}


def _cad(p99, arrivals=500, watchable=True):
    return {"arrivals": arrivals, "p50_seconds": 60.0, "p99_seconds": p99,
            "threshold_seconds": p99 * LATE_MULTIPLE if watchable else None,
            "watchable": watchable}


HEALTHY = [{"name": "sync-checkpoints", "status": "ok", "fault": False}]
BROKEN = [{"name": "sync-checkpoints", "status": "not_running", "fault": True}]


def test_a_feed_past_its_own_threshold_is_a_fault(monkeypatch):
    out = _checks({"checkpoint_status": _cad(600)},          # threshold 1800s
                  {"checkpoint_status": 5000}, HEALTHY, monkeypatch)
    assert out["checkpoint_status"]["status"] == "silent"
    assert out["checkpoint_status"]["fault"] is True


def test_a_feed_inside_its_threshold_is_not(monkeypatch):
    out = _checks({"checkpoint_status": _cad(600)},
                  {"checkpoint_status": 1000}, HEALTHY, monkeypatch)
    assert out["checkpoint_status"]["status"] == "ok"
    assert out["checkpoint_status"]["fault"] is False


def test_one_dead_collector_does_not_become_one_alarm_per_vertical(monkeypatch):
    """The single most important property here. A dead poller makes every feed
    downstream of it look silent at once; reporting each one would turn one
    fault into ten alarms, and an alerting channel that does that gets muted —
    after which the next real fault is delivered to nobody."""
    out = _checks({"checkpoint_status": _cad(600), "checkpoint_flow": _cad(600)},
                  {"checkpoint_status": 5000, "checkpoint_flow": 5000}, BROKEN, monkeypatch)
    for kind in ("checkpoint_status", "checkpoint_flow"):
        assert out[kind]["status"] == "collector_down"
        assert out[kind]["fault"] is False, "the collector's own alarm covers this"


def test_a_feed_nobody_watches_reports_itself_as_unwatched(monkeypatch):
    """An unwatchable feed whose collector is fine is covered, and says so.

    The age here sits INSIDE the silence ceiling on purpose. It used to be
    27.8h, which this test called healthy — and that expectation is exactly
    what let fuel sit dark for 23 hours reading `collector_only ... ok`.
    """
    out = _checks({"checkpoint_status": _cad(0, arrivals=MIN_ARRIVALS - 1, watchable=False)},
                  {"checkpoint_status": 3600}, HEALTHY, monkeypatch)
    assert out["checkpoint_status"]["status"] == "collector_only"
    assert out["checkpoint_status"]["fault"] is False


def test_a_hole_in_the_monitoring_is_itself_a_fault(monkeypatch):
    """No usable cadence AND no healthy collector means nothing whatsoever is
    watching this feed. That is reported as a fault, because a gap in coverage
    looks exactly like health and is the reason this file exists."""
    out = _checks({"checkpoint_status": _cad(0, arrivals=3, watchable=False)},
                  {"checkpoint_status": 99999}, BROKEN, monkeypatch)
    assert out["checkpoint_status"]["status"] == "uncovered"
    assert out["checkpoint_status"]["fault"] is True


def test_an_unmapped_feed_is_uncovered_not_quietly_skipped(monkeypatch):
    """A new state_kind added without a FEED_COLLECTOR entry must surface, or
    every future vertical arrives unmonitored by default."""
    out = _checks({"brand_new_kind": _cad(0, arrivals=2, watchable=False)},
                  {"brand_new_kind": 10}, HEALTHY, monkeypatch)
    assert out["brand_new_kind"]["status"] == "uncovered"
    assert out["brand_new_kind"]["fault"] is True


def test_a_threshold_too_wide_to_be_useful_is_labelled_as_such(monkeypatch):
    """checkpoint_settlers' measured p99 puts its deadline at 9.7 days. The
    check is honest and would still take a week and a half to fire; calling
    that plain 'ok' overstates what is known."""
    wide = WEAK_THRESHOLD_SECONDS  # p99 * 3 lands far past the ceiling
    out = _checks({"checkpoint_settlers": _cad(wide)},
                  {"checkpoint_settlers": 60}, HEALTHY, monkeypatch)
    assert out["checkpoint_settlers"]["status"] == "watched_loosely"
    assert out["checkpoint_settlers"]["fault"] is False


def test_a_feed_with_no_observations_at_all_is_a_fault(monkeypatch):
    out = _checks({"checkpoint_status": _cad(600)}, {}, HEALTHY, monkeypatch)
    assert out["checkpoint_status"]["status"] == "no_data"
    assert out["checkpoint_status"]["fault"] is True


# ── the baseline must not learn to accept a decline ──────────────────────────

def test_the_baseline_excludes_the_window_it_judges():
    """A threshold measured over a period that includes the period being tested
    drifts down with a degrading feed and never fires. The SQL must hold the
    judged window out of the baseline."""
    sql = watchdog.CADENCE_SQL
    assert f"interval '{watchdog.BASELINE_DAYS} days'" in sql
    assert f"<= now() - interval '{watchdog.JUDGE_HOURS} hours'" in sql
    assert watchdog.JUDGE_HOURS > 0


def test_arrivals_are_bucketed_so_a_batch_write_is_one_arrival():
    """Six hundred rows in one transaction are one arrival. Without the bucket
    every gap percentile collapses to zero and every feed looks perpetually
    overdue by a factor of hundreds."""
    assert "date_trunc('minute'" in watchdog.CADENCE_SQL


# ── P3.4: capacity, which nothing was watching at all ────────────────────────

def test_a_full_disk_is_a_fault(monkeypatch):
    """A full filesystem stops Postgres, the backups and every collector at the
    same moment. It was the largest unwatched failure in the system."""
    monkeypatch.setattr(watchdog.os, "statvfs",
                        lambda p: type("S", (), {"f_bavail": 1000,
                                                 "f_frsize": 4096})())
    out = watchdog.capacity_check()[0]
    assert out["status"] == "critical"
    assert out["fault"] is True


def test_a_low_disk_warns_without_alarming(monkeypatch):
    """Between the warning line and the floor there is nothing to DO yet;
    raising an alarm there spends the one thing an alert channel has."""
    gb = 1024 ** 3
    monkeypatch.setattr(watchdog.os, "statvfs",
                        lambda p: type("S", (), {"f_bavail": int(15 * gb / 4096),
                                                 "f_frsize": 4096})())
    out = watchdog.capacity_check()[0]
    assert out["status"] == "low"
    assert out["fault"] is False


def test_ample_disk_is_ok(monkeypatch):
    gb = 1024 ** 3
    monkeypatch.setattr(watchdog.os, "statvfs",
                        lambda p: type("S", (), {"f_bavail": int(250 * gb / 4096),
                                                 "f_frsize": 4096})())
    assert watchdog.capacity_check()[0]["status"] == "ok"


# ── P3.3: the upstream files v2 does not control ─────────────────────────────

def _dep(monkeypatch, spec):
    monkeypatch.setattr(watchdog, "DEPENDENCIES", spec)
    return {c["name"]: c for c in watchdog.dependency_checks()}


def test_a_sqlite_dependency_is_judged_by_its_wal_not_its_db_file(tmp_path,
                                                                  monkeypatch):
    """The trap that was live when this was written.

    SQLite in WAL mode leaves the .db file untouched between checkpoints. The
    real v1 database was 40 minutes stale while its -wal was 24 seconds old and
    v1 was writing normally — so judging the .db alone reports a healthy
    upstream as dead, and names the wrong stack to restart.
    """
    db = tmp_path / "checkpoints.db"
    db.write_text("x")
    wal = tmp_path / "checkpoints.db-wal"
    wal.write_text("x")
    import os
    os.utime(db, (0, 0))                      # .db last checkpointed in 1970
    out = _dep(monkeypatch, {"v1": (str(db), 3600, "why")})
    assert out["v1"]["status"] == "ok", "a fresh -wal means the writer is alive"
    assert out["v1"]["age_minutes"] < 1


def test_a_genuinely_stalled_dependency_is_a_fault(tmp_path, monkeypatch):
    import os
    db = tmp_path / "checkpoints.db"
    db.write_text("x")
    os.utime(db, (0, 0))
    out = _dep(monkeypatch, {"v1": (str(db), 3600, "v1 stopped")})
    assert out["v1"]["status"] == "stale"
    assert out["v1"]["fault"] is True


def test_a_missing_dependency_is_a_fault_not_an_exception(tmp_path, monkeypatch):
    out = _dep(monkeypatch, {"v1": (str(tmp_path / "nope.db"), 3600, "why")})
    assert out["v1"]["status"] == "missing"
    assert out["v1"]["fault"] is True


def test_a_rolling_spool_is_judged_by_its_newest_file(tmp_path, monkeypatch):
    """The tee spool rolls daily. Yesterday's file stops changing the moment
    today's is created, so judging any single file would report a stall every
    midnight."""
    import os
    (tmp_path / "2026-07-31.ndjson").write_text("old")
    os.utime(tmp_path / "2026-07-31.ndjson", (0, 0))
    (tmp_path / "2026-08-01.ndjson").write_text("new")
    out = _dep(monkeypatch, {"spool": (str(tmp_path), 3600, "why")})
    assert out["spool"]["status"] == "ok"


# ── alarms: conditions close, events do not ──────────────────────────────────

@pytest.fixture()
def alerts(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "alerts.ndjson"
        monkeypatch.setattr(alert, "ALERTS", p)
        yield p


def test_a_persistent_fault_raises_once_not_once_per_run(alerts, monkeypatch):
    """A fault lasting a week must not append an alarm every ten minutes. The
    guard is watchdog._already_open, so that is what is exercised here."""
    monkeypatch.setattr(watchdog, "open_alerts", alert.open_alerts)
    key = "watchdog:job:poller"
    assert watchdog._already_open(key) is False
    alert.raise_alert(key, "not_running")
    assert watchdog._already_open(key) is True
    assert len(alert.open_alerts()) == 1


def test_resolving_closes_the_alarm_without_deleting_the_history(alerts):
    alert.raise_alert("watchdog:job:poller", "not_running")
    alert.resolve("watchdog:job:poller", "back within cadence")
    assert alert.open_alerts() == []
    lines = [json.loads(x) for x in alerts.read_text().splitlines() if x.strip()]
    # Three lines now, and each one is a different thing: the alarm, the
    # delivery receipt that completes it, and the resolution. Nothing is
    # rewritten — the receipt is appended AFTER the alarm it belongs to.
    assert len(lines) == 3, "resolving must append, never rewrite"
    assert lines[0]["unit"] == "watchdog:job:poller"
    assert lines[1]["delivery_of"] == "watchdog:job:poller"
    assert lines[2]["resolves"] == "watchdog:job:poller"


def test_a_fault_that_comes_back_is_reported_again(alerts):
    """Resolution must not permanently silence a flapping fault — otherwise the
    second outage of the day is the one nobody hears about."""
    alert.raise_alert("watchdog:job:poller", "not_running")
    alert.resolve("watchdog:job:poller")
    assert alert.open_alerts() == []
    alert.raise_alert("watchdog:job:poller", "not_running again")
    assert len(alert.open_alerts()) == 1


def test_clearing_acknowledges_everything_open(alerts):
    alert.raise_alert("unit-a", "boom")
    alert.raise_alert("unit-b", "boom")
    with alerts.open("a") as fh:
        fh.write(json.dumps({"ts": "2999-01-01T00:00:00+00:00",
                             "clear_marker": True}) + "\n")
    assert alert.open_alerts() == []


# ── one torn line must not take the alarm channel down with it ───────────────
#
# The host lost power mid-append on 2026-08-08 and ext4's delayed allocation
# left line 195 as 3,275 NUL bytes. `open_alerts` json.loads()ed every line, so
# from that moment `ops.alert --list` raised, `ops.watchdog` printed a traceback
# where its alarm reconciliation should have been, and nothing said so. Nine
# days. An alerting channel whose reader can be killed by its own log is worse
# than none, because its silence reads as good news.

def test_a_torn_line_does_not_take_the_whole_log_down(alerts):
    alert.raise_alert("unit-a", "boom")
    with alerts.open("a") as fh:
        fh.write("\0" * 3275 + "\n")
    alert.raise_alert("unit-b", "boom")
    assert {r["unit"] for r in alert.open_alerts()} == {"unit-a", "unit-b"}


def test_damage_is_counted_rather_than_passed_over_in_silence(alerts):
    """Skipping quietly is the same bug one layer down: the alarms written into
    the torn region are gone, and only the count says so."""
    alert.raise_alert("unit-a", "boom")
    with alerts.open("a") as fh:
        fh.write("\0" * 12 + "\n{not json\n")
    assert alert.damaged_lines() == 2


def test_a_torn_line_cannot_hide_a_clear_marker(alerts):
    """Every read of the log has to reach the end of it. If a torn line stopped
    the scan early the newest alarms would vanish, which is the failure this
    test exists to make impossible to reintroduce."""
    alert.raise_alert("unit-a", "boom")
    with alerts.open("a") as fh:
        fh.write("\0" * 40 + "\n")
        fh.write(json.dumps({"ts": "2999-01-01T00:00:00+00:00",
                             "clear_marker": True}) + "\n")
    assert alert.open_alerts() == []


# ── the hole that let fuel sit dark for 23 hours ─────────────────────────────

def _cad_unwatchable(days=1, max_gap=None):
    return {"arrivals": 30, "p50_seconds": 60.0, "p99_seconds": None,
            "threshold_seconds": None, "watchable": False,
            "baseline_days": days, "max_gap_seconds": max_gap}


def test_an_unwatchable_feed_still_has_a_silence_ceiling(monkeypatch):
    """`collector_only` was supposed to mean "watched via its collector". It
    meant NOT WATCHED, because a collector that runs fine and finds nothing
    looks exactly like a healthy one. Fuel — the flagship vertical — read
    `collector_only ... ok` for 23 hours while its upstream had stopped
    publishing entirely."""
    out = _checks({"checkpoint_status": _cad_unwatchable()},
                  {"checkpoint_status": 30 * 3600}, HEALTHY, monkeypatch)
    assert out["checkpoint_status"]["status"] == "silent"
    assert out["checkpoint_status"]["fault"] is True
    assert "upstream has stopped" in out["checkpoint_status"]["detail"]


def test_an_unwatchable_feed_within_the_ceiling_is_still_fine(monkeypatch):
    """The ceiling must not turn every sporadic feed into a permanent alarm —
    road_closure is news-driven and 14 quiet hours is an ordinary night."""
    out = _checks({"checkpoint_status": _cad_unwatchable()},
                  {"checkpoint_status": 14 * 3600}, HEALTHY, monkeypatch)
    assert out["checkpoint_status"]["status"] == "collector_only"
    assert out["checkpoint_status"]["fault"] is False


def test_a_dead_collector_is_reported_as_a_hole_not_as_a_silent_feed(monkeypatch):
    """With no usable cadence AND no healthy collector, nothing watches this
    feed at all — `uncovered`. It must not be labelled `silent`, which would
    blame the upstream for our own collector being down and send whoever reads
    the alarm to the wrong system."""
    out = _checks({"checkpoint_status": _cad_unwatchable()},
                  {"checkpoint_status": 99 * 3600}, BROKEN, monkeypatch)
    assert out["checkpoint_status"]["status"] == "uncovered"
    assert "not healthy" in out["checkpoint_status"]["detail"]


def test_the_ceiling_says_whether_it_was_measured_or_chosen():
    """A chosen number reported as a measured one stops being questioned —
    this project already shipped a 0.70 "trust" and a 0.95 fuel confidence
    that both wore a measurement's clothing."""
    ceiling, basis = watchdog._silence_ceiling(_cad_unwatchable(days=1))
    assert ceiling == watchdog.SILENT_AFTER_SECONDS
    assert "too little history" in basis

    ceiling, basis = watchdog._silence_ceiling(
        {"silence_ceiling_seconds": 45.9 * 3600,
         "ceiling_basis": "measured p95(60d), n=139"})
    assert basis == "measured p95(60d), n=139"
    assert round(ceiling / 3600) == 46


def test_a_measured_ceiling_never_drops_below_the_default():
    """A feed that has only ever been busy would otherwise earn a ceiling of
    minutes and alarm on its first quiet evening."""
    ceiling, _ = watchdog._silence_ceiling(
        {"silence_ceiling_seconds": 60, "ceiling_basis": "measured"})
    assert ceiling >= watchdog.SILENT_AFTER_SECONDS


def test_silence_ceilings_are_measured_from_each_feeds_own_rhythm():
    """F-08, measured 2026-09-22: `checkpoint_settlers` (p95 45.9 h over 139
    arrivals) and `power` (p95 6.2 d over 59) were both being judged against a
    single day, which is why they alarmed on quiet weeks three Mondays running.
    """
    ceiling, basis = watchdog.measured_ceiling(45.9 * 3600, 139)
    assert round(ceiling / 3600) == 46
    assert "p95(60d)" in basis and "n=139" in basis

    ceiling, basis = watchdog.measured_ceiling(6.2 * 86400, 59)
    assert round(ceiling / 86400, 1) == 6.2

    # A regular feed cannot be made quieter than the floor — and the basis says
    # both things: the p95 was measured AND the floor is what is in force.
    ceiling, basis = watchdog.measured_ceiling(600, 9956)
    assert ceiling == watchdog.SILENT_AFTER_SECONDS and "floor 24h" in basis

    # ... and neither can an irregular one with too few gaps behind the p95.
    ceiling, basis = watchdog.measured_ceiling(9 * 86400, 5)
    assert ceiling == watchdog.SILENT_AFTER_SECONDS and "5 arrivals" in basis


def test_the_old_measured_branch_read_a_key_no_column_ever_held():
    """F-08's root cause, held down. `_silence_ceiling` read
    `cad["max_gap_seconds"]`, which `feed_cadence` has never had a column for —
    STORE_SQL and LOAD_SQL never carried it — so the measured branch could not
    fire and every unwatchable feed sat on the 24 h default. A stale key must
    still mean the default, not a silent claim to have measured something."""
    cad = {"baseline_days": 60, "max_gap_seconds": 8 * 86400}
    assert watchdog._silence_ceiling(cad)[0] == watchdog.SILENT_AFTER_SECONDS


# ── restart policy: the seventeen-hour outage ────────────────────────────────
# On 2026-08-02 at 14:10 the poller's transport failed five times. systemd tried
# three restarts, logged "Start request repeated too quickly", and STOPPED. The
# poller was dead for 1,051 minutes.
#
# Every detection mechanism worked. The unit exited non-zero rather than idling
# with a dead transport, OnFailure fired the alarm three times, and the watchdog
# reported `not_running` throughout. Detection was never what was missing —
# RECOVERY was, and a start limit is what took it away.
#
# These read the unit files in ops/systemd/, which are the source of truth
# copied to /etc. A unit that can permanently give up must fail here.

import configparser  # noqa: E402
from pathlib import Path  # noqa: E402

_UNITS = Path(__file__).resolve().parent.parent / "ops" / "systemd"


def _long_running_units():
    """Units with a Restart= policy — the ones a start limit can strand."""
    out = []
    for f in sorted(_UNITS.glob("*.service")):
        if "@" in f.name:                      # templates are one-shot alarms
            continue
        cp = configparser.ConfigParser(strict=False)
        cp.optionxform = str
        cp.read(f)
        if cp.has_option("Service", "Restart") and \
           cp.get("Service", "Restart") in ("always", "on-failure"):
            out.append((f.name, cp))
    return out


def test_there_are_long_running_units_to_check():
    """Guard the guard: a glob that matches nothing passes everything."""
    assert _long_running_units(), "no restarting units found — did the path move?"


def test_no_restarting_unit_can_permanently_give_up():
    for name, cp in _long_running_units():
        assert cp.has_option("Unit", "StartLimitIntervalSec"), \
            (f"{name} inherits the manager default start limit (burst 5 in 10s). "
             f"State StartLimitIntervalSec explicitly — inheriting it is how the "
             f"poller died for 17 hours.")
        assert cp.get("Unit", "StartLimitIntervalSec") == "0", \
            (f"{name} has a start limit and will stop trying after a burst of "
             f"failures. A transient network fault must not be permanent.")


def test_the_poller_backs_off_rather_than_hammering_telegram():
    """Removing the limit must not turn into a restart storm.

    agent2 is rate-limit fragile and that concern was the reason the limit
    existed. Backoff is what replaces it: a blip recovers in 30 seconds, a real
    outage settles to one attempt every 15 minutes — gentler than the poller's
    own 30-second cycle when it is perfectly healthy.
    """
    cp = dict(_long_running_units())["palestine-v2-poller.service"]
    assert int(cp.get("Service", "RestartSteps")) >= 3, "backoff must be gradual"
    assert int(cp.get("Service", "RestartMaxDelaySec")) >= 600, \
        "the ceiling must be patient enough not to hammer a fragile account"
    assert int(cp.get("Service", "RestartSec")) <= 60, \
        "the FIRST retry must be quick, or a blip costs minutes for no reason"


def test_an_unauthorised_session_still_stops_dead():
    """The one case where refusing to retry is correct, and it must survive.

    Reconnecting a de-authorised session repeatedly is the single pattern that
    genuinely endangers the account — unlike a network blip, retrying cannot fix
    it. Exit 2 means exactly that, and it is set in the watchdog.conf drop-in.
    """
    drop = Path("/etc/systemd/system/palestine-v2-poller.service.d/watchdog.conf")
    if not drop.exists():
        import pytest
        pytest.skip("drop-in not installed on this host")
    assert "RestartPreventExitStatus=2" in drop.read_text()


# ── the maintenance run's own exhaust ────────────────────────────────────────

def test_the_maintenance_runs_own_log_is_not_committable():
    """`ops/maintain-logs/` must be ignored, and by the DIRECTORY.

    The weekly run is an unattended agent session started with
    `--dangerously-skip-permissions`, and its log is the whole transcript:
    every command it ran and everything those commands printed. That file is
    the same class as `.env.bak-*` — operational exhaust nobody reviews in a
    diff, which the ignore rules were extended for once already after the
    timestamped `.env` backups turned out to be uncovered while `.env` itself
    was fine. The directory arrived on 2026-08-04 with the maintain feature
    and nothing added it, so the first run's log sat untracked in
    `git status`, one `git add -A` away from history that cannot be edited.

    Asserted against the path `ops/maintain.sh` actually writes, so renaming
    the log directory fails here rather than silently un-ignoring it.
    """
    logdir = re.search(r"^LOGDIR=(\S+)", (ROOT / "ops" / "maintain.sh").read_text(),
                       re.M).group(1)
    probe = f"{logdir}/2026-01-01T00-00-00Z.log"
    assert subprocess.run(["git", "check-ignore", "-q", probe],
                          cwd=ROOT).returncode == 0, \
        (f"{probe} is not git-ignored — an unattended agent's full session "
         f"transcript can be committed by `git add -A`")


# ── alarm DELIVERY ───────────────────────────────────────────────────────────
# The poller died for 17 hours with every detector working. The alarm reached a
# file and a journal, which nobody reads. These cover the properties that make
# a doorbell safe to attach to a monitor.

def test_notify_never_raises_however_broken_the_config(monkeypatch):
    """Monitoring that can break what it monitors is worse than none.

    `raise_alert` runs inside a systemd OnFailure handler. An exception there
    is a second outage on top of the one being reported. Both transports are
    broken at once here: the socket raises and the Telegram pair is missing.
    """
    from ops import notify

    def boom(*a, **k):
        raise OSError("network is gone")

    monkeypatch.setattr(notify.urllib.request, "urlopen", boom)
    monkeypatch.setattr(notify, "NTFY_TOKEN_FILE_DEFAULT", Path("/nonexistent"))
    monkeypatch.setattr(notify, "NTFY_HIGH_MARK", "!!")
    for token, chat in ((None, None), ("bad-token", "123"), ("", "")):
        monkeypatch.setattr(notify, "_env",
                            lambda n, t=token, c=chat: t if n == notify.TOKEN_VAR else c)
        r = notify.send("x")
        assert isinstance(r, dict) and "ok" in r and "reason" in r
        assert r["ok"] is False


def test_alert_is_recorded_even_when_delivery_fails(monkeypatch, tmp_path):
    """The sink is written FIRST and unconditionally.

    A dead network, an expired token or a Telegram outage must not cost the
    record — delivery is best-effort ON TOP of the log, never instead of it.
    """
    from ops import alert
    monkeypatch.setattr(alert, "ALERTS", tmp_path / "a.ndjson")
    monkeypatch.setattr(alert, "_notify",
                        lambda *a, **k: {"ok": False, "reason": "boom"})
    rec = alert.raise_alert("some-unit", "a reason")
    assert rec["unit"] == "some-unit"
    assert rec["delivered"] is False
    written = (tmp_path / "a.ndjson").read_text()
    assert "some-unit" in written, "the alarm was lost when delivery failed"


def test_recovery_is_delivered_silently():
    """A channel that only reports failures cannot distinguish "it recovered"
    from "still broken, gone quiet" — and the second reading is the one that
    gets ignored. Silent so good news never wakes anybody."""
    import inspect

    from ops import alert
    src = inspect.getsource(alert.resolve)
    assert "_notify" in src, "recoveries are not delivered"
    assert "silent=True" in src, "recovery notifications must not make a sound"


def test_unconfigured_is_a_normal_state_not_a_crash(monkeypatch):
    """Reachable only with the ntfy transport deliberately switched off.

    ntfy is configured by default (that is the point of 2026-09-22), so the
    honest way to reach this state — and the only one — is `NTFY_URL=off`
    together with no Telegram pair.
    """
    from ops import notify
    monkeypatch.setattr(notify, "_env",
                        lambda n: "off" if n == notify.NTFY_URL_VAR else None)
    assert notify.ntfy_configured() is False
    assert notify.configured() is False
    r = notify.send("x")
    assert r["ok"] is False and "unconfigured" in r["reason"]


def test_ntfy_is_the_doorbell_that_is_configured_by_default(monkeypatch):
    """The 2026-09-22 finding: every detector worked and no phone rang.

    `fawwaz-alerts` on the house ntfy is the channel Zaid already carries. What
    `send` returns is ntfy's own message id — not a 200, not a bool — because a
    receipt is the only thing that can be checked after the fact.
    """
    from ops import notify

    class Resp:
        status = 200

        def read(self):
            return b'{"id":"abc123","event":"message","topic":"fawwaz-alerts"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        seen["body"] = req.data.decode()
        return Resp()

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(notify, "_env",
                        lambda n: "a-token" if n == notify.NTFY_TOKEN_VAR else None)
    r = notify.send("!! checkpoint feed silent")
    assert r["ok"] is True and r["channel"] == "ntfy" and r["id"] == "abc123"
    assert seen["url"] == f"{notify.NTFY_URL_DEFAULT}/{notify.NTFY_TOPIC_DEFAULT}"
    assert seen["headers"]["authorization"] == "Bearer a-token"
    assert seen["headers"]["priority"] == "high", "a !! fault must be allowed to make a sound"
    assert notify.configured() is True


def test_a_recovery_push_is_silent_and_a_plain_push_is_not_high(monkeypatch):
    """Good news must never wake anybody, and only a fault gets high priority."""
    from ops import notify

    class Resp:
        status = 200

        def read(self):
            return b'{"id":"s1"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["priority"] = {k.lower(): v for k, v in req.header_items()}.get("priority")
        return Resp()

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(notify, "_env", lambda n: None)
    monkeypatch.setattr(notify, "NTFY_TOKEN_FILE_DEFAULT", Path("/nonexistent"))
    assert notify.send("a plain alarm")["ok"] is True
    assert seen["priority"] == "default"
    assert notify.send("🟢 recovered: x", silent=True)["ok"] is True
    assert seen["priority"] == "min"


def test_alert_ledger_keeps_the_channel_and_the_message_id(monkeypatch, tmp_path):
    """`delivered: true` with no channel is a claim nobody can check."""
    from ops import alert
    monkeypatch.setattr(alert, "ALERTS", tmp_path / "a.ndjson")
    monkeypatch.setattr(alert, "_notify",
                        lambda *a, **k: {"ok": True, "reason": "",
                                         "channel": "ntfy", "id": "abc123"})
    rec = alert.raise_alert("some-unit", "a reason")
    assert rec["delivered"] is True
    assert rec["channel"] == "ntfy"
    assert rec["message_id"] == "abc123"
    written = (tmp_path / "a.ndjson").read_text()
    assert '"channel": "ntfy"' in written and "abc123" in written, \
        "the receipt is not in the ledger"


def test_a_delivery_receipt_is_not_a_second_alarm(monkeypatch, tmp_path):
    """The receipt line completes a record; open_alerts() must not read it as
    another open alarm, or every alarm would double the moment it was sent."""
    from ops import alert
    monkeypatch.setattr(alert, "ALERTS", tmp_path / "a.ndjson")
    monkeypatch.setattr(alert, "_notify",
                        lambda *a, **k: {"ok": True, "reason": "",
                                         "channel": "ntfy", "id": "x1"})
    alert.raise_alert("some-unit", "a reason")
    assert [r["unit"] for r in alert.open_alerts()] == ["some-unit"]
    assert alert.damaged_lines() == 0


# ── 070: a retired vertical is not an outage ─────────────────────────────────

def test_a_retired_feed_is_not_judged_even_when_silent(monkeypatch):
    """Zaid retired fuel availability on 2026-09-23. Its collectors were stopped
    on purpose, so its silence is the intended state; judging it would page a
    human every night about a vertical nobody wants — and an alarm that is
    always expected trains people to skim the one that is not."""
    from ops.watchdog import RETIRED_FEEDS
    assert "fuel_diesel" in RETIRED_FEEDS
    out = _checks({"fuel_diesel": _cad(600), "checkpoint_status": _cad(600)},
                  {"fuel_diesel": 99 * 3600, "checkpoint_status": 99 * 3600},
                  HEALTHY, monkeypatch)
    assert "fuel_diesel" not in out
    # ...and retiring one feed does not quietly silence its neighbours.
    assert out["checkpoint_status"]["fault"] is True


def test_the_retired_list_matches_the_migration_that_retired_them():
    """RETIRED_FEEDS is a copy of state_kind_config.retired_at (070), kept in
    code so the check needs no query. A copy that drifts is a lie, so pin it."""
    import re
    from pathlib import Path
    from ops.watchdog import RETIRED_FEEDS, EXPECTED_JOBS
    sql = (Path(__file__).resolve().parents[1]
           / "db/migrations/070_retire_fuel_availability.sql").read_text(encoding="utf-8")
    kinds = re.search(r"WHERE state_kind IN \(([^)]*)\)", sql).group(1)
    assert set(re.findall(r"'([a-z_]+)'", kinds)) == set(RETIRED_FEEDS)
    jobs = re.search(r"WHERE name IN \(([^)]*)\)", sql).group(1)
    for job in re.findall(r"'([a-z0-9-]+)'", jobs):
        assert job not in EXPECTED_JOBS, f"{job} is retired in 070 but still expected by the watchdog"


# ── fuel prices: judged by the monthly list, not by feed cadence ──────────────

def _price_row(**kw):
    row = {"confirmed": 8, "conflicting": 0, "products": 8, "newest": "2026-09-07", "day": 10}
    row.update(kw)
    return [row]


def test_a_month_with_no_confirmed_list_is_a_fault_after_the_grace_days(monkeypatch):
    import ops.watchdog as w
    monkeypatch.setattr(w, "_q", lambda sql: _price_row(confirmed=0, day=w.FUEL_PRICE_GRACE_DAYS))
    r = w.fuel_price_check()[0]
    assert r["status"] == "no_list" and r["fault"] is True


def test_the_first_days_of_a_month_are_awaiting_not_a_fault(monkeypatch):
    import ops.watchdog as w
    monkeypatch.setattr(w, "_q", lambda sql: _price_row(confirmed=0, day=2))
    r = w.fuel_price_check()[0]
    assert r["status"] == "awaiting" and r["fault"] is False


def test_outlets_disagreeing_on_a_price_is_a_fault(monkeypatch):
    import ops.watchdog as w
    monkeypatch.setattr(w, "_q", lambda sql: _price_row(conflicting=1))
    assert w.fuel_price_check()[0]["fault"] is True


def test_a_broken_price_query_cannot_take_the_watchdog_down(monkeypatch):
    import ops.watchdog as w
    def boom(sql):
        raise RuntimeError("relation does not exist")
    monkeypatch.setattr(w, "_q", boom)
    r = w.fuel_price_check()[0]
    assert r["status"] == "unreadable" and r["fault"] is True
