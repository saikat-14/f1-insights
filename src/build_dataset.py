"""
Day 1: build one row per driver per race (2018 onward).

Usage (run from the f1-predictor folder):
    python src/build_dataset.py --smoke          # quick test: 3 races of 2024
    python src/build_dataset.py                  # full build 2018 -> now (resumable)
    python src/build_dataset.py --start 2022 --end 2025

It caches each race as its own small parquet in data/raw/, so if it stops
or your internet drops, just run it again and it continues where it left off.
"""
import argparse
import datetime as dt
import warnings
from pathlib import Path

import fastf1
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
CACHE = ROOT / "f1_cache"
for p in (RAW, PROCESSED, CACHE):
    p.mkdir(parents=True, exist_ok=True)

fastf1.Cache.enable_cache(str(CACHE))
fastf1.set_log_level("WARNING")  # hide the noisy INFO lines


class StopForLimit(Exception):
    """Raised when FastF1's 500 calls/hour limit is hit."""


def _is_rate_limit(e: Exception) -> bool:
    return "calls/h" in str(e) or e.__class__.__name__ == "RateLimitExceededError"


def _load(year: int, rnd: int, code: str, weather: bool):
    """Load a session with only the light data we need (no telemetry/laps)."""
    try:
        s = fastf1.get_session(year, rnd, code)
        s.load(laps=False, telemetry=False, weather=weather, messages=False)
        return s
    except Exception as e:  # session missing, cancelled, API hiccup
        if _is_rate_limit(e):
            raise StopForLimit()
        print(f"    ! could not load {year} R{rnd} {code}: {e}")
        return None


def _td_seconds(series: pd.Series) -> pd.Series:
    return pd.to_timedelta(series, errors="coerce").dt.total_seconds()


def build_race(year: int, rnd: int, event_name: str, country: str):
    race = _load(year, rnd, "R", weather=True)
    if race is None or race.results is None or race.results.empty:
        return None

    res = race.results.copy()
    df = pd.DataFrame({
        "season": year,
        "round": rnd,
        "event": event_name,
        "country": country,
        "driver": res["Abbreviation"].values,
        "driver_number": res["DriverNumber"].values,
        "team": res["TeamName"].values,
        "grid": pd.to_numeric(res["GridPosition"], errors="coerce").values,
        "finish_pos": pd.to_numeric(res["Position"], errors="coerce").values,
        "status": res["Status"].values,
        "points": pd.to_numeric(res["Points"], errors="coerce").values,
    })
    # grid 0 means pit-lane start -> treat as last on grid
    n = len(df)
    df.loc[df["grid"] == 0, "grid"] = n
    # "Finished" or "+1 Lap" etc. = classified finish; anything else = DNF
    st = df["status"].fillna("")
    df["dnf"] = (~(st.eq("Finished") | st.str.startswith("+") | st.str.contains("Lap"))).astype(int)

    # --- weather (race-day averages) ---
    w = getattr(race, "weather_data", None)
    if w is not None and len(w):
        df["air_temp"] = w["AirTemp"].mean()
        df["track_temp"] = w["TrackTemp"].mean()
        df["humidity"] = w["Humidity"].mean()
        df["rain"] = int(w["Rainfall"].any())
        df["rain_share"] = float(w["Rainfall"].mean())
    else:
        for c in ("air_temp", "track_temp", "humidity", "rain", "rain_share"):
            df[c] = np.nan

    # --- qualifying ---
    q = _load(year, rnd, "Q", weather=False)
    if q is not None and q.results is not None and not q.results.empty:
        qr = q.results.copy()
        best = pd.concat([_td_seconds(qr[c]) for c in ("Q1", "Q2", "Q3")], axis=1).min(axis=1)
        qdf = pd.DataFrame({
            "driver": qr["Abbreviation"].values,
            "quali_pos": pd.to_numeric(qr["Position"], errors="coerce").values,
            "quali_best_s": best.values,
        })
        pole = qdf["quali_best_s"].min()
        qdf["quali_gap_pct"] = (qdf["quali_best_s"] - pole) / pole * 100
        df = df.merge(qdf, on="driver", how="left")
    else:
        print("    ! qualifying missing -> not saving, will retry next run")
        return None

    df["quali_missing"] = df["quali_best_s"].isna().astype(int)  # a signal, not something to impute away
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=2018)
    ap.add_argument("--end", type=int, default=dt.date.today().year)
    ap.add_argument("--smoke", action="store_true", help="only first 3 races of 2024")
    args = ap.parse_args()

    if args.smoke:
        args.start, args.end = 2024, 2024

    now = pd.Timestamp.now(tz="UTC").tz_localize(None)

    # delete cached races that were saved without qualifying data (old bug)
    for f in RAW.glob("*.parquet"):
        d = pd.read_parquet(f)
        if d["quali_best_s"].isna().all():
            f.unlink()
            print(f"  removed incomplete cache {f.name} (will re-download)")

    stopped = False
    try:
        for year in range(args.start, args.end + 1):
            print(f"\n=== {year} ===")
            try:
                sched = fastf1.get_event_schedule(year, include_testing=False)
            except Exception as e:
                if _is_rate_limit(e):
                    raise StopForLimit()
                print(f"  ! no schedule for {year}: {e}")
                continue
            if args.smoke:
                sched = sched.head(3)

            for _, ev in sched.iterrows():
                rnd = int(ev["RoundNumber"])
                date = pd.Timestamp(ev["EventDate"])
                if date.tzinfo is not None:
                    date = date.tz_convert("UTC").tz_localize(None)
                if date > now:
                    continue  # future race
                out = RAW / f"{year}_{rnd:02d}.parquet"
                if out.exists():
                    print(f"  R{rnd:02d} {ev['EventName']}: cached")
                    continue
                print(f"  R{rnd:02d} {ev['EventName']}: downloading...")
                df = build_race(year, rnd, ev["EventName"], ev["Country"])
                if df is not None:
                    df.to_parquet(out, index=False)
                    print(f"    saved {len(df)} rows")

    except StopForLimit:
        stopped = True
        print("\n*** FastF1 limit (500 calls/hour) reached. Progress is saved. ***")
        print("*** Wait about 60 minutes, then run the same command again.    ***")

    files = sorted(RAW.glob("*.parquet"))
    if not files:
        print("\nNo data saved. Check your internet connection and try again.")
        return
    full = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    full["rain"] = (full["rain_share"] > 0.10).astype(int)  # >10% of race samples wet
    full = full.sort_values(["season", "round", "finish_pos"]).reset_index(drop=True)
    full.to_parquet(PROCESSED / "results.parquet", index=False)

    print("\n=== " + ("PARTIAL (limit hit)" if stopped else "DONE") + " ===")
    print(f"Rows: {len(full)} | Races: {full.groupby(['season','round']).ngroups} "
          f"| Seasons: {sorted(full.season.unique())}")
    print(full.head(10).to_string())
    miss = full.isna().sum()
    print("\nMissing values per column:")
    print(miss[miss > 0].to_string() if (miss > 0).any() else "none")


if __name__ == "__main__":
    main()
