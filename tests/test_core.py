import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import strategy as S
from features import build_features


def _toy():
    rng = np.random.default_rng(0)
    rows = []
    for season in (2022, 2023):
        for rnd in range(1, 7):
            order = rng.permutation(6)
            for i in range(6):
                rows.append(dict(season=season, round=rnd, event=f"GP{rnd}", driver=f"D{i}", team=f"T{i//2}",
                                 grid=float(i + 1), finish_pos=float(order[i] + 1), points=float(max(0, 6 - order[i])),
                                 dnf=0, rain=0, rain_share=0.0, track_temp=30.0,
                                 quali_pos=float(i + 1), quali_gap_pct=float(i) * 0.3, quali_missing=0))
    return pd.DataFrame(rows)


def test_features_do_not_see_the_race_they_describe():
    df = _toy()
    base = build_features(df)
    changed = df.copy()
    last = (changed.season == 2023) & (changed["round"] == 6)
    changed.loc[last, "finish_pos"] = 1.0           # tamper with the final race result
    changed.loc[last, "points"] = 99.0
    new = build_features(changed)
    cols = [c for c in base.columns if c.startswith(("drv_", "team_form", "circ_"))]
    m = (base.season == 2023) & (base["round"] == 6)
    pd.testing.assert_frame_equal(base.loc[m, cols].reset_index(drop=True),
                                  new.loc[m, cols].reset_index(drop=True))


def test_safety_car_makes_a_stop_cheaper():
    r = S.Race()
    no_sc = S.total_time(r, ("MEDIUM", "HARD"), (24,), None)
    with_sc = S.total_time(r, ("MEDIUM", "HARD"), (24,), 22)
    assert with_sc < no_sc


def test_optimiser_obeys_two_compound_rule_and_beats_bad_plan():
    r = S.Race()
    best = S.optimise(r, n_sims=60, top=5)
    assert all(len(set(s)) >= 2 for s in best["seq"])
    silly = S.total_time(r, ("SOFT", "SOFT"), (28,), None)   # same compound twice is also slow here
    assert best["No-SC time (s)"].iloc[0] <= silly


def test_lap_times_length():
    r = S.Race()
    assert len(S.lap_times(r, ("MEDIUM", "HARD"), (24,))) == r.laps
