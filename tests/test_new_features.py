import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import auto_update
import teams
import ui
from build_strategy_stats import aggregate_event


def test_team_colours_resolve_for_official_and_unknown_names():
    assert teams.team_key("Haas F1 Team") == "haas" and teams.team_key("RB F1 Team") == "racing_bulls"
    assert teams.team_key("Red Bull") == "red_bull" and teams.team_key("Alpine F1 Team") == "alpine"
    assert teams.team_style("Brand New Team")["name"] == "Brand New Team"
    assert teams.team_style("Ferrari")["ui"].startswith("#")


def test_podium_puts_top3_in_p2_p1_p3_order_and_rest_as_rows():
    n = 20
    d = pd.DataFrame({"driver": [f"D{i:02d}" for i in range(n)], "team": ["Ferrari"] * n, "grid": range(1, n + 1),
                      "exp_pos": np.arange(1, n + 1, dtype=float), "win_prob": np.r_[[.5, .3, .1], np.zeros(n - 3)],
                      "podium_prob": np.linspace(.9, 0, n), "top10_prob": np.linspace(1, 0, n), "pred_dnf": .04})
    h = ui.podium_html(d)
    assert h.index("D01") < h.index("D00") < h.index("D02")      # P2 | P1 | P3
    assert h.count('class="row"') == n - 3                       # everyone else horizontal


def test_aggregate_event_recovers_known_tyre_and_pit_numbers():
    rng = np.random.default_rng(3)
    rows = []
    for season in (2023, 2024, 2025):
        for drv in range(20):
            pit = int(rng.integers(20, 32))
            for lap in range(1, 58):
                stint = 1 if lap <= pit else 2
                age = lap if stint == 1 else lap - pit
                lt = 90 + 0.05 * age - 0.03 * lap + rng.normal(0, .1) + (15 if lap == pit else 0) + (11 if lap == pit + 1 else 0)
                rows.append(dict(season=season, round=5, event="X", driver=f"D{drv}", lap=lap, laptime_s=lt, stint=stint,
                                 compound="MEDIUM", tyre_life=age, pit_in=lap == pit, pit_out=lap == pit + 1,
                                 status="1", accurate=True))
    out = aggregate_event(pd.DataFrame(rows))
    assert abs(out["pit_loss"] - 26) < 1.0
    assert out["stops"]["1"] > 0.99
    assert abs(out["tyres"]["MEDIUM"]["deg"] - 0.05) < 0.01


def test_auto_update_waits_until_qualifying_is_done(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_update, "PROC", tmp_path)
    now = pd.Timestamp.now(tz="UTC")
    pd.DataFrame([
        dict(season=2026, round=1, event="X GP", country="X", location="Monza", session="Qualifying",
             start_utc=(now + pd.Timedelta(hours=20)).tz_localize(None)),
        dict(season=2026, round=1, event="X GP", country="X", location="Monza", session="Race",
             start_utc=(now + pd.Timedelta(days=1)).tz_localize(None)),
    ]).to_parquet(tmp_path / "schedule.parquet", index=False)
    assert "waiting for qualifying" in auto_update.update_if_needed(championship=False)


def test_auto_update_asks_for_models_if_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_update, "PROC", tmp_path)
    now = pd.Timestamp.now(tz="UTC")
    pd.DataFrame([
        dict(season=2026, round=1, event="X GP", country="X", location="Monza", session="Qualifying",
             start_utc=(now - pd.Timedelta(hours=5)).tz_localize(None)),
        dict(season=2026, round=1, event="X GP", country="X", location="Monza", session="Race",
             start_utc=(now + pd.Timedelta(hours=18)).tz_localize(None)),
    ]).to_parquet(tmp_path / "schedule.parquet", index=False)
    assert "models missing" in auto_update.update_if_needed(championship=False)
