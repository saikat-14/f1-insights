"""
Build real per-circuit strategy statistics from race lap data (tyre stints, pit stops, Safety Cars).

    python src/build_strategy_stats.py              # 2023 -> now
    python src/build_strategy_stats.py --start 2024 # fewer races = faster

Resumable. Output: data/processed/strategy_stats.json  (used by the Strategy page)
"""
import argparse
import json
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
LAPS_DIR = ROOT / "data" / "raw_laps"
FUEL = 0.03  # seconds per lap of fuel burn (standard assumption)
LETTER = {"SOFT": "S", "MEDIUM": "M", "HARD": "H", "INTERMEDIATE": "I", "WET": "W"}


def _quantiles(vals):
    if len(vals) < 3:
        return None
    q = np.percentile(vals, [25, 50, 75])
    return {"p25": float(q[0]), "p50": float(q[1]), "p75": float(q[2])}


def aggregate_event(L: pd.DataFrame) -> dict:
    """L = per-lap rows for several editions of ONE circuit. Pure function (unit-tested)."""
    L = L.copy()
    L["stint"] = L["stint"].fillna(1)
    keys = ["season", "round"]
    race_laps = L.groupby(keys)["lap"].max().rename("race_laps").reset_index()
    n_races = len(race_laps)
    laps_total = int(race_laps["race_laps"].median())

    dr = (L.groupby(keys + ["driver"]).agg(max_lap=("lap", "max"), stints=("stint", "max")).reset_index()
          .merge(race_laps, on=keys))
    fin = dr[dr["max_lap"] >= 0.9 * dr["race_laps"]]
    n_dr = max(1, len(fin))
    stops = (fin["stints"] - 1).clip(lower=0)
    stop_dist = {"0": float((stops == 0).mean()), "1": float((stops == 1).mean()),
                 "2": float((stops == 2).mean()), "3+": float((stops >= 3).mean())}

    # pit windows
    pits = L[L["pit_in"]].merge(fin[keys + ["driver"]], on=keys + ["driver"])
    pit_prob = np.zeros(laps_total)
    for lap, c in pits["lap"].value_counts().items():
        if 1 <= lap <= laps_total:
            pit_prob[int(lap) - 1] = c / n_dr
    pits = pits.sort_values(keys + ["driver", "lap"])
    pits["nth"] = pits.groupby(keys + ["driver"]).cumcount() + 1
    first_stop = _quantiles(pits.loc[pits["nth"] == 1, "lap"].tolist())
    second_stop = _quantiles(pits.loc[pits["nth"] == 2, "lap"].tolist())

    # safety cars
    st = L.groupby(keys)["status"].apply(lambda s: "".join(s.astype(str)))
    sc_prob = float(st.str.contains("4").mean())
    vsc_prob = float(st.str.contains("6|7", regex=True).mean())

    # compound sequences
    seqs = Counter()
    for _, g in L.merge(fin[keys + ["driver"]], on=keys + ["driver"]).groupby(keys + ["driver"]):
        s = g.sort_values("stint").groupby("stint")["compound"].agg(lambda x: x.mode().iloc[0] if len(x.mode()) else "?")
        seqs["-".join(LETTER.get(str(c).upper(), "?") for c in s)] += 1
    strategies = [{"seq": k, "pct": v / n_dr} for k, v in seqs.most_common(6)]

    # clean laps
    clean = L[(L["status"].astype(str) == "1") & ~L["pit_in"] & ~L["pit_out"] & L["accurate"] & L["laptime_s"].notna()]
    clean_med = clean.groupby(keys)["laptime_s"].median().rename("clean_med").reset_index()

    # pit loss: in-lap + out-lap - 2 * green-flag median lap
    a = L[L["pit_in"] & L["laptime_s"].notna()][keys + ["driver", "lap", "laptime_s", "status"]]
    b = L[L["pit_out"] & L["laptime_s"].notna()][keys + ["driver", "lap", "laptime_s", "status"]].copy()
    b["lap"] = b["lap"] - 1
    m = a.merge(b, on=keys + ["driver", "lap"], suffixes=("_in", "_out")).merge(clean_med, on=keys)
    m = m[(m["status_in"].astype(str) == "1") & (m["status_out"].astype(str) == "1")]
    m["loss"] = m["laptime_s_in"] + m["laptime_s_out"] - 2 * m["clean_med"]
    m = m[(m["loss"] > 8) & (m["loss"] < 45)]
    pit_loss = float(m["loss"].median()) if len(m) >= 5 else 22.0

    # tyre wear + compound pace offsets (fuel-corrected)
    rows = []
    c2 = clean.merge(race_laps, on=keys).dropna(subset=["tyre_life"])
    for (s, r, d, stn), g in c2.groupby(keys + ["driver", "stint"]):
        if len(g) < 8 or g["tyre_life"].nunique() < 6:
            continue
        slope, icpt = np.polyfit(g["tyre_life"].to_numpy(float), g["laptime_s"].to_numpy(), 1)
        lap_at_1 = float((g["lap"] - g["tyre_life"]).mean() + 1)
        p1 = icpt + slope - FUEL * (float(g["race_laps"].iloc[0]) - lap_at_1)
        rows.append((s, r, d, str(g["compound"].mode().iloc[0]).upper(), slope + FUEL, p1))
    tyres = {}
    if rows:
        t = pd.DataFrame(rows, columns=["season", "round", "driver", "compound", "deg", "p1"])
        t["dev"] = t["p1"] - t.groupby(keys + ["driver"])["p1"].transform("mean")
        t["n"] = t.groupby(keys + ["driver"])["p1"].transform("count")
        off = {}
        for comp, g in t.groupby("compound"):
            if comp not in ("SOFT", "MEDIUM", "HARD") or len(g) < 5:
                continue
            tyres[comp] = {"deg": float(np.clip(g["deg"].median(), 0.005, 0.25))}
            multi = g[g["n"] >= 2]
            off[comp] = float(multi["dev"].median()) if len(multi) >= 5 else None
        known = {k: v for k, v in off.items() if v is not None}
        if known:
            base = min(known.values())
            for k, v in known.items():
                tyres[k]["offset"] = float(np.clip(v - base, 0.0, 2.5))

    drv_med = clean.groupby(keys + ["driver"])["laptime_s"].median()
    base_pace = float(np.percentile(drv_med, 25) - 1.5) if len(drv_med) else None

    return {"n_races": int(n_races), "laps": laps_total, "base_pace": base_pace, "pit_loss": round(pit_loss, 1),
            "sc_prob": round(sc_prob, 3), "vsc_prob": round(vsc_prob, 3),
            "stops": {k: round(v, 3) for k, v in stop_dist.items()},
            "pit_lap_prob": [round(float(v), 4) for v in pit_prob],
            "first_stop": first_stop, "second_stop": second_stop,
            "strategies": [{"seq": s["seq"], "pct": round(s["pct"], 3)} for s in strategies], "tyres": tyres}


def extract_laps(season: int, rnd: int, event: str):
    import fastf1
    from build_dataset import StopForLimit, _is_rate_limit
    try:
        s = fastf1.get_session(season, rnd, "R")
        s.load(laps=True, telemetry=False, weather=False, messages=False)
        l = s.laps
    except Exception as e:
        if _is_rate_limit(e):
            raise StopForLimit()
        print(f"    ! {season} R{rnd}: {e}")
        return None
    return pd.DataFrame({
        "season": season, "round": rnd, "event": event, "driver": l["Driver"].values, "lap": l["LapNumber"].values,
        "laptime_s": l["LapTime"].dt.total_seconds().values, "stint": l["Stint"].values,
        "compound": l["Compound"].values, "tyre_life": l["TyreLife"].values,
        "pit_in": l["PitInTime"].notna().values, "pit_out": l["PitOutTime"].notna().values,
        "status": l["TrackStatus"].astype(str).values, "accurate": l["IsAccurate"].fillna(False).astype(bool).values})


def main():
    from build_dataset import StopForLimit
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=2023)
    a = ap.parse_args()
    LAPS_DIR.mkdir(parents=True, exist_ok=True)
    res = pd.read_parquet(PROC / "results.parquet")
    races = (res[res["season"] >= a.start][["season", "round", "event"]].drop_duplicates()
             .sort_values(["season", "round"], ascending=False))
    try:
        for r in races.itertuples():
            f = LAPS_DIR / f"{r.season}_{r.round:02d}.parquet"
            if f.exists():
                continue
            print(f"  {r.season} R{r.round} {r.event}: downloading laps...")
            d = extract_laps(int(r.season), int(r.round), r.event)
            if d is not None:
                d.to_parquet(f, index=False)
    except StopForLimit:
        print("\n*** FastF1 limit reached. Progress saved - wait ~60 min and run again. ***")

    files = sorted(LAPS_DIR.glob("*.parquet"))
    if not files:
        print("No lap data yet.")
        return
    allL = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    out = {}
    for ev, g in allL.groupby("event"):
        try:
            out[ev] = aggregate_event(g)
        except Exception as e:
            print(f"  ! could not aggregate {ev}: {e}")
    (PROC / "strategy_stats.json").write_text(json.dumps(out))
    print(f"\nStrategy stats for {len(out)} circuits from {len(files)} races -> data/processed/strategy_stats.json")


if __name__ == "__main__":
    main()
