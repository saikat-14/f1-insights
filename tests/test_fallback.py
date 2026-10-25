"""Updater behaviours that do not depend on a particular data source."""
import json
import sys
import types
from datetime import timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_race_day_is_not_treated_as_race_over():
    saved = sys.modules.get("fastf1")
    if saved is None:
        m = types.ModuleType("fastf1")
        m.Cache = types.SimpleNamespace(enable_cache=lambda *a, **k: None)
        m.set_log_level = lambda *a, **k: None
        sys.modules["fastf1"] = m
    try:
        import build_dataset as B
        now = pd.Timestamp.now(tz="UTC").tz_localize(None)
        today = now.normalize()
        assert B.race_is_over({"Session5DateUtc": now + timedelta(hours=8), "EventDate": today}, now) is False   # the old bug
        assert B.race_is_over({"Session5DateUtc": now - timedelta(hours=1), "EventDate": today}, now) is False   # within 3 h
        assert B.race_is_over({"Session5DateUtc": now - timedelta(hours=5), "EventDate": today}, now) is True
        assert B.race_is_over({"EventDate": today}, now) is False
        assert B.race_is_over({"EventDate": today - timedelta(days=3)}, now) is True
    finally:
        if saved is None:
            sys.modules.pop("fastf1", None)
            sys.modules.pop("build_dataset", None)


def test_updater_always_leaves_a_human_readable_status(tmp_path, monkeypatch):
    import auto_update as A
    monkeypatch.setattr(A, "PROC", tmp_path)
    now = pd.Timestamp.now(tz="UTC")
    pd.DataFrame([dict(season=2026, round=1, event="X GP", country="X", location="Monza", session="Qualifying",
                       start_utc=(now + pd.Timedelta(hours=20)).tz_localize(None)),
                  dict(season=2026, round=1, event="X GP", country="X", location="Monza", session="Race",
                       start_utc=(now + pd.Timedelta(days=1)).tz_localize(None))]).to_parquet(tmp_path / "schedule.parquet", index=False)
    A.update_if_needed(championship=False)
    st = json.loads((tmp_path / "update_status.json").read_text())
    assert "waiting for qualifying" in st["message"] and st["state"] == "waiting" and st["checked_at"]
