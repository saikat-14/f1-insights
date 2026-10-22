"""
Day 2 / step 3: train, walk-forward backtest, honest scoring vs the grid baseline.

    python src/backtest.py                      # test on 2024, 2025, 2026
    python src/backtest.py --test-from 2025     # faster

Walk-forward = for every test race, train ONLY on races before it. No peeking.
"""
import argparse
import json
import warnings
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

from features import DATA, DNF_FEATURES, FEATURES, build_features
from simulate import fit_sigma, simulate

warnings.filterwarnings("ignore")


def make_reg():
    return lgb.LGBMRegressor(n_estimators=250, learning_rate=0.03, num_leaves=15, min_child_samples=40,
                             subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=2.0,
                             random_state=42, verbose=-1)


def make_clf():
    return lgb.LGBMClassifier(n_estimators=150, learning_rate=0.03, num_leaves=7, min_child_samples=60,
                              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0,
                              random_state=42, verbose=-1)


def fit_models(train: pd.DataFrame):
    """Position model learns the SHIFT from grid, using drivers who finished.
    DNF model learns retirement risk. Predicted position = grid + shift."""
    fin = train[train["dnf"] == 0]
    reg = make_reg().fit(fin[FEATURES], fin["finish_pos"] - fin["grid"])
    clf = make_clf().fit(train[DNF_FEATURES], train["dnf"])
    return reg, clf


def predict(reg, clf, g: pd.DataFrame):
    pred_pos = np.clip(g["grid"].values + reg.predict(g[FEATURES]), 1, g["n_drivers"].values)
    p_dnf = np.clip(clf.predict_proba(g[DNF_FEATURES])[:, 1], 0.01, 0.6)
    return pred_pos, p_dnf


def save_final_models(df: pd.DataFrame, mdir: Path):
    """Train on ALL finished races and save. Also used by auto_update after new races arrive."""
    final_train = df[df["finish_pos"].notna() & (df["season"] >= 2019)]
    reg, clf = fit_models(final_train)
    mdir.mkdir(parents=True, exist_ok=True)
    joblib.dump(reg, mdir / "reg.joblib")
    joblib.dump(clf, mdir / "clf.joblib")
    return reg


def evaluate(bt: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (s, r), g in bt.groupby(["season", "round"]):
        won = g["finish_pos"] == 1
        top3_actual = set(g.loc[g["finish_pos"] <= 3, "driver"])
        top3_model = set(g.nlargest(3, "podium_prob")["driver"])
        top3_grid = set(g.loc[g["grid"] <= 3, "driver"])
        rows.append({
            "season": s, "round": r,
            "mae_model": (g["finish_pos"] - g["pred_pos"]).abs().mean(),
            "mae_grid": (g["finish_pos"] - g["grid"]).abs().mean(),
            "rho_model": g["pred_pos"].corr(g["finish_pos"], method="spearman"),
            "rho_grid": g["grid"].corr(g["finish_pos"], method="spearman"),
            "win_hit_model": float(g.loc[g["win_prob"].idxmax(), "finish_pos"] == 1),
            "win_hit_grid": float(g.loc[g["grid"].idxmin(), "finish_pos"] == 1),
            "podium_model": len(top3_actual & top3_model) / 3,
            "podium_grid": len(top3_actual & top3_grid) / 3,
            "p_actual_winner": g.loc[won, "win_prob"].max() if won.any() else np.nan,
            "brier_win": ((g["win_prob"] - won.astype(float)) ** 2).mean(),
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--test-from", type=int, default=2024)
    ap.add_argument("--sims", type=int, default=4000)
    args = ap.parse_args()

    out_dir = Path(args.data).parent
    raw = pd.read_parquet(args.data)
    df = build_features(raw)
    df.to_parquet(out_dir / "features.parquet", index=False)
    print(f"Features built: {len(df)} rows, {df['race_idx'].nunique()} races")

    # ---------- walk-forward ----------
    test_ids = sorted(df.loc[(df["season"] >= args.test_from) & df["finish_pos"].notna(), "race_idx"].unique())
    rows = []
    for i, rid in enumerate(test_ids, 1):
        train = df[(df["race_idx"] < rid) & df["finish_pos"].notna() & (df["season"] >= 2019)]
        test = df[df["race_idx"] == rid].copy()
        if len(train) < 500:
            continue
        reg, clf = fit_models(train)
        test["pred_pos"], test["pred_dnf"] = predict(reg, clf, test)
        rows.append(test)
        if i % 10 == 0 or i == len(test_ids):
            print(f"  walk-forward {i}/{len(test_ids)} races")
    bt = pd.concat(rows, ignore_index=True)

    # ---------- uncertainty + Monte Carlo ----------
    ok = bt["dnf"] == 0
    a, b = fit_sigma(bt.loc[ok, "pred_pos"].values, (bt.loc[ok, "finish_pos"] - bt.loc[ok, "pred_pos"]).abs().values)
    print(f"Noise model: sigma = {a:.2f} + {b:.2f} * predicted_position")

    parts = []
    for _, g in bt.groupby("race_idx"):
        g = g.copy()
        sim = simulate(g["pred_pos"].values, g["pred_dnf"].values, a, b, n=args.sims)
        for k, v in sim.items():
            g[k] = v
        parts.append(g)
    bt = pd.concat(parts, ignore_index=True)

    keep = ["season", "round", "event", "driver", "team", "grid", "finish_pos", "dnf",
            "pred_pos", "pred_dnf", "win_prob", "podium_prob", "top10_prob", "exp_pos"]
    bt[keep].to_parquet(out_dir / "backtest.parquet", index=False)

    # ---------- scoreboard ----------
    ev = evaluate(bt)
    cols = ["mae_model", "mae_grid", "rho_model", "rho_grid", "win_hit_model", "win_hit_grid",
            "podium_model", "podium_grid", "p_actual_winner", "brier_win"]
    print("\n================ SCOREBOARD (lower MAE better, higher rest better) ================")
    print(ev.groupby("season")[cols].mean().round(3).to_string())
    print("\nOVERALL")
    overall = ev[cols].mean().round(3)
    print(overall.to_string())
    print(f"\nRaces tested: {len(ev)}")
    verdict = "BEATS" if overall["mae_model"] < overall["mae_grid"] else "does NOT beat"
    print(f"Model {verdict} the grid baseline on position error "
          f"({overall['mae_model']} vs {overall['mae_grid']}).")
    ev.to_csv(out_dir / "backtest_scores.csv", index=False)

    # ---------- final models on ALL data (used by the app) ----------
    mdir = out_dir / "models"
    reg = save_final_models(df, mdir)
    (mdir / "sigma.json").write_text(json.dumps({"a": a, "b": b}))
    imp = pd.Series(reg.booster_.feature_importance("gain"), index=FEATURES).sort_values(ascending=False)
    imp = (imp / imp.sum() * 100).round(1)
    imp.to_csv(out_dir / "feature_importance.csv", header=["gain_pct"])
    print("\nTop features (position model, % of gain):")
    print(imp.head(10).to_string())
    print(f"\nSaved models + backtest to {out_dir}")


if __name__ == "__main__":
    main()
