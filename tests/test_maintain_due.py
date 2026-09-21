"""F-03 — the maintainer's catch-ups: when a week is owed, and how it is started.

    ./.venv/bin/python -m pytest tests/test_maintain_due.py -q

The weekly maintainer lost two consecutive Mondays (2026-09-14, 09-21) to the
Claude monthly spend limit, and nothing retried either one. The catch-ups that
now exist — the +6h retries and the Tuesday timer — are gated on one question,
"has a digest landed in the last 6 days?", and these pin down its answer in the
directions that would lose a week silently: a broken or missing ledger must
read as OWED, never as done.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops.maintain_due import is_owed, last_digest_ts            # noqa: E402

NOW = datetime(2026, 9, 22, 5, 15, tzinfo=timezone.utc)          # a Tuesday


def _ledger(tmp_path, *lines):
    p = tmp_path / "digests.ndjson"
    p.write_text("".join(line + "\n" for line in lines))
    return p


def _digest(ts: datetime) -> str:
    return json.dumps({"ts": ts.isoformat(), "ok": True, "highlights": []})


def test_a_digest_from_yesterday_means_the_week_is_done(tmp_path):
    p = _ledger(tmp_path, _digest(NOW - timedelta(days=1)))
    owed, _ = is_owed(p, NOW, max_age=timedelta(days=6))
    assert owed is False


def test_the_two_skipped_mondays_read_as_owed(tmp_path):
    """The real ledger on 2026-09-22: last digest 09-07, fifteen days old."""
    p = _ledger(tmp_path,
                _digest(datetime(2026, 8, 31, 5, 43, tzinfo=timezone.utc)),
                _digest(datetime(2026, 9, 7, 5, 40, 3, 859653, tzinfo=timezone.utc)))
    owed, why = is_owed(p, NOW, max_age=timedelta(days=6))
    assert owed is True
    assert "2026-09-07" in why


def test_the_last_line_decides_not_the_newest_looking_one(tmp_path):
    """Append order is the ledger's clock; an older line after a newer one
    means the newer one was written by hand or out of order — the last
    append is what the maintainer most recently did."""
    p = _ledger(tmp_path,
                _digest(NOW - timedelta(days=1)),
                _digest(NOW - timedelta(days=9)))
    assert last_digest_ts(p) == NOW - timedelta(days=9)


def test_a_missing_ledger_is_owed_not_done(tmp_path):
    owed, why = is_owed(tmp_path / "nope.ndjson", NOW, max_age=timedelta(days=6))
    assert owed is True
    assert "no readable digest" in why


def test_a_torn_last_line_falls_back_to_the_last_good_one(tmp_path):
    """A run killed mid-append leaves half a JSON object. The line before it
    is still the truth about when a digest last landed."""
    p = _ledger(tmp_path, _digest(NOW - timedelta(days=2)), '{"ts": "2026-09-2', "")
    owed, _ = is_owed(p, NOW, max_age=timedelta(days=6))
    assert owed is False


def test_a_ledger_with_nothing_parseable_is_owed(tmp_path):
    p = _ledger(tmp_path, "not json", '{"no_ts": 1}', '{"ts": "yesterday"}')
    owed, _ = is_owed(p, NOW, max_age=timedelta(days=6))
    assert owed is True


def test_a_naive_timestamp_is_read_as_utc(tmp_path):
    p = _ledger(tmp_path, json.dumps({"ts": "2026-09-21T05:40:00"}))
    assert last_digest_ts(p) == datetime(2026, 9, 21, 5, 40, tzinfo=timezone.utc)


# ── the wiring the check sits inside ─────────────────────────────────────────

def test_the_model_pin_is_still_the_default():
    """MAINTAIN_MODEL exists so the seat probe's failure path can be forced with
    a bogus name. Its default IS the pin (Zaid, 2026-08-04); an override that
    defaulted anywhere else would be the model switch the pin forbids."""
    sh = (ROOT / "ops" / "maintain.sh").read_text()
    assert re.search(r'^MODEL="\$\{MAINTAIN_MODEL:-claude-opus-5\}"$', sh, re.M)
    assert sh.count('--model "$MODEL"') == 2, "probe and session must ask for the same model"


def test_every_catch_up_starts_the_unit_and_never_the_script():
    """The overlap guard. systemd runs at most one instance of a unit, so a
    catch-up that starts palestine-v2-maintain.service while a session is
    running joins that session. One that ran maintain.sh itself would be a
    second agent in the same repo at the same time."""
    unit = (ROOT / "ops" / "systemd" / "palestine-v2-maintain-retry.service").read_text()
    starts = re.findall(r"^ExecStart=(.*)$", unit, re.M)
    assert starts == ["+/usr/bin/systemctl start --no-block palestine-v2-maintain.service"]
    assert not [l for l in re.findall(r"^Exec\w*=.*$", unit, re.M) if "maintain.sh" in l]
    assert re.search(r"^ExecCondition=.*-m ops\.maintain_due --max-age-days 6$", unit, re.M)

    sh = (ROOT / "ops" / "maintain.sh").read_text()
    retry = re.search(r"systemd-run\b.*?palestine-v2-maintain-retry\.service", sh, re.S)
    assert retry, "the +6h retry must go through the catch-up unit and its condition"
    assert "maintain.sh" not in retry.group(0)
