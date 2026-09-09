"""Unit tests for the backup retention policy (pure logic)."""

import datetime as dt
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "prune_backups",
    Path(__file__).resolve().parents[2] / "scripts" / "prune_backups.py",
)
prune_backups = importlib.util.module_from_spec(spec)
sys.modules["prune_backups"] = prune_backups
spec.loader.exec_module(prune_backups)
keep = prune_backups.keep

TODAY = dt.date(2026, 9, 25)


def test_recent_dailies_kept():
    for age in range(0, 8):
        assert keep(TODAY - dt.timedelta(days=age), TODAY)


def test_old_daily_dropped():
    assert not keep(dt.date(2026, 9, 12), TODAY)  # age 13, day 12


def test_weekly_anchors_kept_five_weeks():
    assert keep(dt.date(2026, 9, 8), TODAY)   # age 17, day 8
    assert keep(dt.date(2026, 8, 22), TODAY)  # age 34, day 22
    assert not keep(dt.date(2026, 8, 15), TODAY)  # age 41


def test_monthly_firsts_kept_a_year():
    assert keep(dt.date(2026, 9, 1), TODAY)
    assert keep(dt.date(2025, 10, 1), TODAY)
    assert not keep(dt.date(2025, 9, 1), TODAY)  # age 389


def test_future_dumps_never_deleted():
    assert keep(TODAY + dt.timedelta(days=2), TODAY)


def test_prune_deletes_files(tmp_path):
    old = tmp_path / "pauk-2026-09-12.sql.gz"
    fresh = tmp_path / "pauk-2026-09-24.sql.gz"
    predeploy = tmp_path / "pauk-2026-09-24-predeploy.sql.gz"
    unrelated = tmp_path / "notes.txt"
    for f in (old, fresh, predeploy, unrelated):
        f.write_bytes(b"x")
    deleted = prune_backups.prune(tmp_path, TODAY, dry_run=False)
    assert [p.name for p in deleted] == ["pauk-2026-09-12.sql.gz"]
    assert fresh.exists() and predeploy.exists() and unrelated.exists()


def test_dry_run_keeps_files(tmp_path):
    old = tmp_path / "pauk-2026-01-12.sql.gz"
    old.write_bytes(b"x")
    prune_backups.prune(tmp_path, TODAY, dry_run=True)
    assert old.exists()
