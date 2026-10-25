"""
Prediction core for an upcoming race. (Normally you never run this by hand:
auto_update.py does it automatically after qualifying.)

Manual override:  python src/predict_next.py --force
"""
import argparse
import json
import warnings
from pathlib import Path

import joblib
import pandas as pd

from backtest import predict
from features import DATA, build_features
from simulate import simulate

warnings.filterwarnings("ignore")


def predict_race(raw: pd.DataFrame, stub: pd.DataFrame, mdir: Path, sims=5000) -> pd.DataFrame:
    """raw = finished races, stub = the upcoming race (finish_pos NaN). Returns probabilities."""
    full = pd.concat([raw, stub], ignore_index=True)
    feats = build_features(full)
    g = feats[feats["race_idx"] == feats["race_idx"].max()].copy()
    reg, clf = joblib.load(mdir / "reg.joblib"), joblib.load(mdir / "clf.joblib")
    sig = json.loads((mdir / "sigma.json").read_text())
    g["pred_pos"], g["pred_dnf"] = predict(reg, clf, g)
    for k, v in simulate(g["pred_pos"].values, g["pred_dnf"].values, sig["a"], sig["b"], n=sims).items():
        g[k] = v
    return g[["season", "round", "event", "driver", "team", "grid", "pred_pos", "pred_dnf",
              "win_prob", "podium_prob", "top10_prob", "exp_pos"]].sort_values("exp_pos")


def stub_from_quali(season, rnd, event, country, quali_results: pd.DataFrame, rain: int) -> pd.DataFrame:
    """Qualifying classification (+ official starting grid when known) -> one model-input row per driver."""
    import quali_sources as Q
    d = Q.normalize(quali_results)
    grid, _source = Q.resolve_grid(d)  # official grid with penalties if available, else classification order
    secs = pd.concat([d[c].dt.total_seconds() for c in ("Q1", "Q2", "Q3")], axis=1)
    best = secs.min(axis=1)  # a driver with no lap time stays NaN -> quali_missing = 1 (not invented)
    pole = best.min()
    stub = pd.DataFrame({
        "season": season, "round": rnd, "event": event, "country": country,
        "driver": d["Abbreviation"].values, "team": d["TeamName"].values,
        "quali_pos": d["Position"].values, "quali_best_s": best.values,
    })
    stub["quali_gap_pct"] = (stub["quali_best_s"] - pole) / pole * 100
    stub["quali_missing"] = stub["quali_best_s"].isna().astype(int)
    stub["grid"] = grid.values.astype(float)
    stub["rain"] = rain
    stub["rain_share"] = 0.3 * rain
    return stub


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", default=True)
    ap.parse_args()
    import auto_update
    print(auto_update.update_if_needed(force=True))
