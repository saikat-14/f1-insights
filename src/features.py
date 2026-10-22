"""
Day 2 / step 1: feature engineering.

Golden rule: every feature for a race may only use information known BEFORE
that race starts. Everything computed from past results is .shift()-ed so a
race never sees its own result. This function also works if you append a
"future" race row (finish_pos = NaN) - Day 3 uses that for the next race.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "results.parquet"

FEATURES = [
    "grid", "grid_pct", "quali_pos", "quali_gap_pct", "quali_missing", "quali_vs_team",
    "drv_form_pos5", "drv_form_gain5", "drv_form_pts5", "drv_dnf10", "drv_wet_gain",
    "team_form_pos3", "team_form_gap3", "team_form_pts3", "team_gap_rank",
    "circ_overtake", "circ_dnf",
    "rain", "rain_share", "track_temp", "n_drivers",
]

DNF_FEATURES = [
    "grid", "grid_pct", "quali_missing", "drv_dnf10", "circ_dnf",
    "rain", "team_form_pos3", "drv_form_pos5",
]


def _past_roll(s: pd.Series, window: int, min_periods: int) -> pd.Series:
    """Rolling mean of PREVIOUS races only."""
    return s.shift().rolling(window, min_periods=min_periods).mean()


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["season", "round", "grid"]).reset_index(drop=True).copy()
    df["race_idx"] = df.groupby(["season", "round"]).ngroup()
    df["n_drivers"] = df.groupby("race_idx")["driver"].transform("count")

    for c in ("rain", "rain_share"):
        df[c] = df[c].fillna(0)

    # --- grid / quali (known before the race) ---
    df["grid_pct"] = df["grid"] / df["n_drivers"]
    team_gap_now = df.groupby(["race_idx", "team"])["quali_gap_pct"].transform("mean")
    df["quali_vs_team"] = df["quali_gap_pct"] - team_gap_now  # beat / lost to teammate

    # --- driver form (past races only) ---
    df["pos_gain"] = (df["grid"] - df["finish_pos"]).where(df["dnf"] == 0)  # clean: ignore DNFs
    df["abs_gain"] = df["pos_gain"].abs()
    g = df.groupby("driver")
    df["drv_form_pos5"] = g["finish_pos"].transform(lambda s: _past_roll(s, 5, 2))
    df["drv_form_gain5"] = g["pos_gain"].transform(lambda s: _past_roll(s, 5, 2))
    df["drv_form_pts5"] = g["points"].transform(lambda s: _past_roll(s, 5, 2))
    df["drv_dnf10"] = g["dnf"].transform(lambda s: _past_roll(s, 10, 3))

    wet_gain = df["pos_gain"].where(df["rain"] == 1)
    df["drv_wet_gain"] = wet_gain.groupby(df["driver"]).transform(lambda s: s.shift().expanding().mean())

    # --- team form (both cars combined, last 3 races the team took part in) ---
    tr = (df.groupby(["team", "race_idx"], as_index=False)
            .agg(t_fin=("finish_pos", "mean"), t_gap=("quali_gap_pct", "mean"), t_pts=("points", "sum"))
            .sort_values(["team", "race_idx"]))
    for src, new in (("t_fin", "team_form_pos3"), ("t_gap", "team_form_gap3"), ("t_pts", "team_form_pts3")):
        tr[new] = tr.groupby("team")[src].transform(lambda s: _past_roll(s, 3, 1))
    df = df.merge(tr[["team", "race_idx", "team_form_pos3", "team_form_gap3", "team_form_pts3"]],
                  on=["team", "race_idx"], how="left")
    df["team_gap_rank"] = df.groupby("race_idx")["team_form_gap3"].rank(pct=True)

    # --- circuit history (earlier editions of the same Grand Prix) ---
    ev = (df.groupby(["event", "race_idx"], as_index=False)
            .agg(ev_abs=("abs_gain", "mean"), ev_dnf=("dnf", "mean"))
            .sort_values(["event", "race_idx"]))
    ev["circ_overtake"] = ev.groupby("event")["ev_abs"].transform(lambda s: s.shift().expanding().mean())
    ev["circ_dnf"] = ev.groupby("event")["ev_dnf"].transform(lambda s: s.shift().expanding().mean())
    df = df.merge(ev[["event", "race_idx", "circ_overtake", "circ_dnf"]], on=["event", "race_idx"], how="left")

    return df.sort_values(["race_idx", "grid"]).reset_index(drop=True)


if __name__ == "__main__":
    raw = pd.read_parquet(DATA)
    out = build_features(raw)
    out.to_parquet(DATA.parent / "features.parquet", index=False)
    print(out[["season", "round", "driver", "grid"] + FEATURES[5:12]].tail(12).to_string())
    print("\nFeature missing %:")
    print((out[FEATURES].isna().mean() * 100).round(1).to_string())
