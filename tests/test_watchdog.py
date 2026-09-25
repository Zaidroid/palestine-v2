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
    # `"?` because most scripts write `"$(dirname "$0")/with-heartbeat.sh" name`
    # — without it the pattern silently skipped backup, restore-test,
    # classify-news, measure-accuracy, sync-checkpoints and mcp-audit.
    pattern = re.compile(r'with-heartbeat\.sh"?\s+(\S+)\s+(\d+)\s+(\d+)')
    found: dict[str, tuple[int, int]] = {}
    for sh in (ROOT / "ops").glob("*.sh"):
        for name, iv, gr in pattern.findall(sh.read_text()):
            found[name] = (int(iv), int(gr))

    assert found, "no wrapped jobs found — has with-heartbeat.sh been renamed?"
    for name in ("backup", "sync-checkpoints", "mcp-audit", "valhalla-ip"):
        assert name in found, f"{name}'s wrapper line was not read — the pattern drifted"
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


def test_recovery_is_delivered_silently(monkeypatch, tmp_path):
    """A channel that only reports failures cannot distinguish "it recovered"
    from "still broken, gone quiet" — and the second reading is the one that
    gets ignored. Silent so good news never wakes anybody.

    Exercised, not read: this used to grep resolve()'s source for `_notify`
    and `silent=True`, which a comment containing those words satisfies."""
    from ops import alert
    monkeypatch.setattr(alert, "ALERTS", tmp_path / "a.ndjson")
    sent = []
    monkeypatch.setattr(alert, "_notify",
                        lambda text, **kw: sent.append((text, kw)) or
                        {"ok": True, "reason": "", "channel": "ntfy", "id": "r1"})
    alert.raise_alert("watchdog:job:poller", "not_running")
    alert.resolve("watchdog:job:poller", "back within cadence")
    assert len(sent) == 2, "the recovery was not delivered"
    text, kw = sent[-1]
    assert "recovered" in text and "watchdog:job:poller" in text
    assert kw.get("silent") is True, "recovery notifications must not make a sound"


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


# ── F069: a crash is not a finding ────────────────────────────────────────────
# `if faults: return 1` and an uncaught exception both exited 1, and the unit
# (SuccessExitStatus=0 1) and the wrapper (OK_EXIT_CODES=1) both called 1 a
# success — so a watchdog that died before checking anything beat green.

def _board(monkeypatch, jobs=(), feeds=(), extra=()):
    """Run main() over fabricated check results; no DB, no network."""
    monkeypatch.setattr(watchdog, "job_checks", lambda: list(jobs))
    monkeypatch.setattr(watchdog, "measure_cadence", lambda: {})
    monkeypatch.setattr(watchdog, "feed_checks", lambda j, c=None: list(feeds))
    for name in ("capacity_check", "dependency_checks", "routing_check",
                 "minimax_check", "fuel_price_check"):
        monkeypatch.setattr(watchdog, name, lambda: [])
    monkeypatch.setattr(watchdog, "doorbell_check", lambda: list(extra), raising=False)


def _main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["ops.watchdog", *args])
    return watchdog.main()


def test_a_watchdog_that_crashes_does_not_exit_like_one_that_found_a_fault(monkeypatch):
    import psycopg

    def db_down():
        raise psycopg.OperationalError("connection refused")

    _board(monkeypatch)
    monkeypatch.setattr(watchdog, "job_checks", db_down)
    assert _main(monkeypatch, "--dry-run") == 1, "a crash must exit 1, and be caught to say so"

    _board(monkeypatch, jobs=[{"check": "job", "name": "poller", "status": "not_running",
                               "fault": True, "age_minutes": 99, "detail": "x"}])
    found = _main(monkeypatch, "--dry-run")
    assert found == watchdog.FAULTS_FOUND == 3, "a fault FOUND must not share the crash's code"

    _board(monkeypatch)
    assert _main(monkeypatch, "--dry-run") == 0


def test_a_status_body_that_is_not_an_object_is_a_finding_not_a_crash(monkeypatch):
    """`r.json().get("version")` raised AttributeError on a JSON array and took
    the whole run — every other check's alarms with it — down."""
    import httpx

    class R:
        status_code = 200

        def json(self):
            return ["not", "valhalla"]

    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    row = watchdog.routing_check()[0]
    assert row["status"] == "wrong-service" and row["fault"] is True


# ── F285: a collector going down is not the feed recovering ──────────────────

@pytest.fixture()
def quiet_alerts(alerts, monkeypatch):
    """The ledger fixture with delivery stubbed: no test pushes to a phone."""
    sent = []
    monkeypatch.setattr(alert, "_notify",
                        lambda text, **kw: sent.append((text, kw)) or
                        {"ok": True, "reason": "", "channel": "ntfy", "id": f"m{len(sent)}"})
    monkeypatch.setattr(watchdog, "open_alerts", alert.open_alerts)
    return sent


def test_a_stale_feed_keeps_its_alarm_when_its_collector_goes_down(quiet_alerts, monkeypatch):
    """checkpoint_status silent for 3 h (alarm open); then sync-checkpoints
    fails twice on a locked SQLite. The feed flips to `collector_down` — not a
    fault, because the collector's own alarm covers it — and that used to
    RESOLVE the feed alarm with 'check returned to within cadence' and a 🟢
    push while the feed was exactly as silent as before."""
    alert.raise_alert("watchdog:feed:checkpoint_status", "silent — 180m")
    _board(monkeypatch,
           jobs=[{"check": "job", "name": "sync-checkpoints", "status": "failing",
                  "fault": True, "age_minutes": 30, "detail": "exited 1"}],
           feeds=[{"check": "feed", "name": "checkpoint_status", "status": "collector_down",
                   "fault": False, "age_minutes": 200,
                   "detail": "stale, but sync-checkpoints is already reported"}])
    _main(monkeypatch)
    still_open = {r["unit"] for r in alert.open_alerts()}
    assert "watchdog:feed:checkpoint_status" in still_open, "a still-stale feed was 'recovered'"
    assert not any("recovered" in t for t, _ in quiet_alerts)

    # When the feed itself comes back, it does close.
    _board(monkeypatch, feeds=[{"check": "feed", "name": "checkpoint_status",
                                "status": "ok", "fault": False, "age_minutes": 1,
                                "detail": ""}])
    _main(monkeypatch)
    assert alert.open_alerts() == []


def test_a_key_open_twice_is_resolved_once(quiet_alerts, monkeypatch):
    for _ in range(2):
        with alert.ALERTS.open("a") as fh:
            fh.write(json.dumps({"ts": "2026-09-25T00:00:00+00:00",
                                 "unit": "watchdog:dep:valhalla", "detail": "x"}) + "\n")
    _board(monkeypatch)
    _main(monkeypatch)
    lines = [json.loads(x) for x in alert.ALERTS.read_text().splitlines()]
    assert sum(1 for x in lines if x.get("resolves")) == 1


# ── F286: an alarm nobody heard is re-sent, and a dead doorbell is a fault ────

def test_an_undelivered_alarm_is_re_sent_on_a_backoff(alerts, monkeypatch):
    from datetime import datetime, timedelta, timezone
    outcomes = [{"ok": False, "reason": "HTTP 403: forbidden", "channel": "ntfy"},
                {"ok": True, "reason": "", "channel": "ntfy", "id": "m2"}]
    monkeypatch.setattr(alert, "_notify", lambda text, **kw: outcomes.pop(0))
    rec = alert.raise_alert("watchdog:job:telegram-poller", "not_running — 31m")
    assert rec["delivered"] is False
    t0 = datetime.fromisoformat(rec["ts"])
    assert alert.redeliver_undelivered(t0 + timedelta(minutes=5)) == [], "backoff first"
    sent = alert.redeliver_undelivered(t0 + timedelta(minutes=31))
    assert len(sent) == 1 and sent[0]["delivered"] is True
    assert sent[0]["alarm_ts"] == rec["ts"]
    assert alert.redeliver_undelivered(t0 + timedelta(hours=5)) == [], \
        "once it has reached someone it is done"
    assert [r["unit"] for r in alert.open_alerts()] == ["watchdog:job:telegram-poller"]


def test_an_unconfigured_channel_is_not_retried_forever(alerts, monkeypatch):
    from datetime import datetime, timedelta
    monkeypatch.setattr(alert, "_notify", lambda text, **kw:
                        {"ok": False, "reason": "unconfigured (NTFY_URL/NTFY_TOPIC)"})
    rec = alert.raise_alert("unit-a", "boom")
    later = datetime.fromisoformat(rec["ts"]) + timedelta(hours=2)
    assert alert.redeliver_undelivered(later) == []


def test_the_doorbell_row_faults_when_the_last_deliveries_all_failed(alerts, monkeypatch):
    monkeypatch.setattr(alert, "_notify", lambda text, **kw:
                        {"ok": False, "reason": "HTTP 403: forbidden", "channel": "ntfy"})
    for i in range(alert.DOORBELL_RECEIPTS):
        alert.raise_alert(f"unit-{i}", "boom")
    row = watchdog.doorbell_check()[0]
    assert row["fault"] is True and "403" in row["detail"]

    monkeypatch.setattr(alert, "_notify", lambda text, **kw:
                        {"ok": True, "reason": "", "channel": "ntfy", "id": "ok1"})
    alert.raise_alert("unit-x", "boom")
    assert watchdog.doorbell_check()[0]["fault"] is False


def test_an_empty_ledger_is_unproven_not_broken(alerts):
    row = watchdog.doorbell_check()[0]
    assert row["fault"] is False and row["status"] == "unproven"


# ── F273: an OnFailure storm pushes once, not thirty times an hour ───────────

def _onfailure(monkeypatch, unit):
    monkeypatch.setattr(sys, "argv", ["ops.alert", unit, "exited 1"])
    return alert.main()


def test_a_unit_failing_every_two_minutes_pushes_once_an_hour(alerts, monkeypatch):
    sent = []
    monkeypatch.setattr(alert, "_notify", lambda text, **kw: sent.append(text) or
                        {"ok": True, "reason": "", "channel": "ntfy", "id": str(len(sent))})
    for _ in range(30):
        _onfailure(monkeypatch, "palestine-v2-checkpoints.service")
    assert len(sent) == 1, f"{len(sent)} pushes for one failing unit"
    alarms = [r for r in alert.open_alerts()
              if r["unit"] == "palestine-v2-checkpoints.service"]
    assert len(alarms) == 30, "every failure is still RECORDED"
    assert sum(1 for r in alarms if r.get("suppressed")) == 29

    # A different unit is a different alarm.
    _onfailure(monkeypatch, "palestine-v2-crowd.service")
    assert len(sent) == 2


def test_a_repeat_after_an_undelivered_push_is_pushed(alerts, monkeypatch):
    """Only a push that REACHED someone may quiet its repeats."""
    results = [{"ok": False, "reason": "URLError", "channel": "ntfy"},
               {"ok": True, "reason": "", "channel": "ntfy", "id": "2"}]
    monkeypatch.setattr(alert, "_notify", lambda text, **kw: results.pop(0))
    _onfailure(monkeypatch, "palestine-v2-news.service")
    _onfailure(monkeypatch, "palestine-v2-news.service")
    assert results == [], "the second failure must be pushed when the first was not heard"


def test_the_quiet_window_expires_into_a_reminder(alerts, monkeypatch):
    from datetime import datetime, timedelta, timezone
    sent = []
    monkeypatch.setattr(alert, "_notify", lambda text, **kw: sent.append(text) or
                        {"ok": True, "reason": "", "channel": "ntfy", "id": "x"})
    old = (datetime.now(timezone.utc)
           - timedelta(seconds=alert.REPEAT_QUIET_SECONDS + 60)).isoformat()
    with alerts.open("a") as fh:
        fh.write(json.dumps({"ts": old, "unit": "u.service", "detail": "x"}) + "\n")
        fh.write(json.dumps({"ts": old, "delivery_of": "u.service",
                             "delivered": True, "channel": "ntfy"}) + "\n")
    _onfailure(monkeypatch, "u.service")
    assert len(sent) == 1, "an hour on, a still-failing unit reminds once"


def test_the_watchdog_path_is_not_quieted(alerts, monkeypatch):
    """Dedup is for OnFailure EVENTS; the watchdog raises a key only when it is
    not already open, so a raise from it always pushes."""
    sent = []
    monkeypatch.setattr(alert, "_notify", lambda text, **kw: sent.append(text) or
                        {"ok": True, "reason": "", "channel": "ntfy", "id": "x"})
    alert.raise_alert("watchdog:job:x", "a")
    alert.raise_alert("watchdog:job:x", "b")
    assert len(sent) == 2


# ── F510: an alarm is allowed to make a sound ────────────────────────────────

def test_every_alarm_is_pushed_at_high_priority(alerts, monkeypatch):
    """The high path keyed on `!!`, the watchdog's CONSOLE mark, which never
    appears in an alarm's text — so every real alarm went out at `default`."""
    from ops import notify

    class Resp:
        status = 200

        def read(self):
            return b'{"id":"p1"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append({k.lower(): v for k, v in req.header_items()}.get("priority"))
        return Resp()

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(notify, "_env", lambda n: None)
    monkeypatch.setattr(notify, "NTFY_TOKEN_FILE_DEFAULT", Path("/nonexistent"))
    alert.raise_alert("watchdog:job:telegram-poller", "not_running — 31m since last beat")
    assert seen == ["high"]
    alert.resolve("watchdog:job:telegram-poller", "back")
    assert seen[-1] == "min", "a recovery stays silent"


# ── the heartbeat detail: say why, and judge what the registry expects ───────

def _job_row(**kw):
    row = {"name": "classify-news", "status": "ok", "ok_age_minutes": 1,
           "attempt_age_minutes": 1, "expected_interval_seconds": 300,
           "consecutive_failures": 0, "last_error": None}
    row.update(kw)
    return row


def test_a_job_killed_mid_run_says_so_instead_of_nothing(monkeypatch):
    """F287: the wrapper stamps the attempt first; an attempt with no outcome
    is a run that never came back. `failing — ` with an empty reason sent the
    responder nowhere."""
    monkeypatch.setattr(watchdog, "_q", lambda sql: [
        _job_row(status="failing", ok_age_minutes=40, attempt_age_minutes=3)])
    row = next(r for r in job_checks() if r["name"] == "classify-news")
    assert row["fault"] is True
    assert "no outcome" in row["detail"] and "3m ago" in row["detail"]


def test_an_expected_job_with_no_cadence_is_a_fault_not_unmonitored(monkeypatch):
    """F508: `ops.heartbeat maintain --fail ...` without --interval on a fresh
    row inserted NULL, the view said `unmonitored`, and that was never a fault
    — a maintainer capped every Monday would read green forever."""
    monkeypatch.setattr(watchdog, "_q", lambda sql: [
        _job_row(name="maintain", status="unmonitored", expected_interval_seconds=None,
                 last_error="seat probe, model claude-opus-5: spend-limit (rc 1)")])
    row = next(r for r in job_checks() if r["name"] == "maintain")
    assert row["fault"] is True
    assert "no cadence" in row["detail"] and "spend-limit" in row["detail"]


def test_an_unregistered_unmonitored_row_is_still_not_judged(monkeypatch):
    monkeypatch.setattr(watchdog, "_q", lambda sql: [
        _job_row(name="some-hand-run", status="unmonitored", expected_interval_seconds=None)])
    row = next(r for r in job_checks() if r["name"] == "some-hand-run")
    assert row["fault"] is False


# ── against the database: the SQL itself, in a rolled-back transaction ──────

@pytest.fixture()
def db():
    """A transaction that is always rolled back. Never commits."""
    import psycopg
    from resolve.db import dsn
    conn = psycopg.connect(dsn())
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _fixture_kind(db, kind):
    with db.cursor() as cur:
        cur.execute("""INSERT INTO state_kind_config (state_kind, half_life_seconds)
                       VALUES (%s, 3600) ON CONFLICT (state_kind) DO NOTHING""", (kind,))
        cur.execute("""INSERT INTO place (kind, name_en, geom)
                       VALUES ('checkpoint', 'T_watchdog',
                               ST_SetSRID(ST_MakePoint(35.2, 32.2), 4326))
                       RETURNING place_id""")
        place = cur.fetchone()[0]
        cur.execute("""INSERT INTO source (key, name, kind, license_spdx, commercial_use,
                                           attribution_text, authority_rank)
                       VALUES ('t_watchdog_src', 't', 'telegram', 'NONE', false, 't', 5)
                       RETURNING source_id""")
        return place, cur.fetchone()[0]


def _arrive(cur, place, source, kind, ages_minutes, modality="assertion"):
    cur.executemany(
        """INSERT INTO state_observation (place_id, state_kind, value, observed_at,
                                          source_id, modality)
           VALUES (%s, %s, 'open', now() - make_interval(mins => %s), %s, %s)""",
        [(place, kind, m, source, modality) for m in ages_minutes])


def test_quarantined_rows_do_not_keep_a_served_feed_fresh(db):
    """F284: palhub writes checkpoint_flow every five minutes as `quarantined`;
    the served stream is v1's assertions. With v1 dark for ten hours, the feed
    must read ten hours old — not five minutes."""
    from psycopg.rows import dict_row
    kind = "_t_watchdog_flow"
    with db.cursor(row_factory=dict_row) as cur:
        place, src = _fixture_kind(db, kind)
        _arrive(cur, place, src, kind, [600, 700, 800])                  # v1, dark 10 h
        _arrive(cur, place, src, kind, [5, 10, 15], modality="quarantined")  # palhub
        cur.execute(watchdog.CURRENT_SQL)
        row = next(r for r in cur.fetchall() if r["state_kind"] == kind)
        assert round(float(row["age_seconds"]) / 60) == 600

        cur.execute(watchdog.CEILING_SQL)
        ceil = next(r for r in cur.fetchall() if r["state_kind"] == kind)
        assert int(ceil["arrivals"]) == 2, "quarantined arrivals counted in the ceiling"


def test_a_kind_with_only_quarantined_rows_is_not_a_fresh_feed(db):
    from psycopg.rows import dict_row
    kind = "_t_watchdog_quarantine_only"
    with db.cursor(row_factory=dict_row) as cur:
        place, src = _fixture_kind(db, kind)
        _arrive(cur, place, src, kind, [1, 2], modality="quarantined")
        cur.execute(watchdog.CURRENT_SQL)
        assert kind not in {r["state_kind"] for r in cur.fetchall()}


def test_the_baseline_holds_out_the_window_it_judges_measured(db):
    """F588: behaviour, not an f-string. Hourly arrivals for four days, then a
    burst every minute inside the last JUDGE_HOURS — the kind of change the
    judged window is for. Held out, the baseline still reads one hour; had the
    burst leaked in, the median gap would collapse to a minute."""
    from psycopg.rows import dict_row
    kind = "_t_watchdog_cadence"
    judge = watchdog.JUDGE_HOURS * 60
    baseline = [judge + 60 * h for h in range(1, 97)]              # hourly, 4 days
    burst = list(range(1, judge - 1))                              # every minute
    with db.cursor(row_factory=dict_row) as cur:
        place, src = _fixture_kind(db, kind)
        _arrive(cur, place, src, kind, baseline + burst)
        _arrive(cur, place, src, kind, [judge + 30], modality="quarantined")
        cur.execute(watchdog.CADENCE_SQL)
        row = next(r for r in cur.fetchall() if r["state_kind"] == kind)
        assert int(row["arrivals"]) == len(baseline) - 1
        assert float(row["p50"]) == 3600.0


def test_a_stamped_attempt_turns_a_killed_job_into_failing(db):
    """F287 at the view: last_ok and last_attempt both stale read `not_running`
    ("the scheduler stopped"); the attempt the wrapper now stamps before the
    run makes the same killed job read `failing`, which is what it is."""
    from ops.heartbeat import UPSERT_ATTEMPT
    with db.cursor() as cur:
        cur.execute("""INSERT INTO ops_heartbeat (name, last_ok, last_attempt,
                                                  expected_interval_seconds, grace_seconds)
                       VALUES ('_t_killed', now() - interval '2 hours',
                               now() - interval '2 hours', 300, 900)""")
        cur.execute("SELECT status FROM ops_heartbeat_status WHERE name = '_t_killed'")
        assert cur.fetchone()[0] == "not_running"
        cur.execute(UPSERT_ATTEMPT, ("_t_killed", 300, 900))
        cur.execute("""SELECT status, last_ok < now() - interval '1 hour',
                              consecutive_failures
                         FROM ops_heartbeat_status WHERE name = '_t_killed'""")
        status, still_stale, failures = cur.fetchone()
        assert status == "failing"
        assert still_stale and failures == 0, "an attempt is neither a success nor a failure"
