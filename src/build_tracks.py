"""
Build 2D circuit outlines (plus sector boundaries) from real FastF1 telemetry:
the fastest qualifying lap of the latest race at each circuit.

    python src/build_tracks.py                 # download circuits not saved yet
    python src/build_tracks.py --add-sectors   # re-download only circuits saved WITHOUT sector data

Resumable (one small JSON per circuit in data/tracks/). If the FastF1 limit (500 calls/h) hits, wait an hour
and run again. Output: data/processed/tracks.json
"""
import argparse
import json
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from build_dataset import StopForLimit, _is_rate_limit  # also enables the FastF1 cache

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT_DIR = ROOT / "data" / "tracks"


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def extract(season: int, rnd: int, event: str):
    import fastf1
    for code in ("Q", "R"):
        try:
            s = fastf1.get_session(season, rnd, code)
            s.load(laps=True, telemetry=True, weather=False, messages=False)
            tel = s.laps.pick_fastest().get_telemetry().dropna(subset=["X", "Y", "Z", "Speed"])
            break
        except Exception as e:
            if _is_rate_limit(e):
                raise StopForLimit()
            print(f"    ! {code} session failed: {e}")
            tel = None
    if tel is None or len(tel) < 50:
        return None

    n = len(tel)
    idx = np.arange(0, n, max(1, n // 350))
    sectors = None
    try:  # sector boundaries = where the lap clock crosses Sector1Time and Sector1Time+Sector2Time
        lap = s.laps.pick_fastest()
        t = tel["Time"].dt.total_seconds().to_numpy()
        s1, s2 = lap["Sector1Time"].total_seconds(), lap["Sector2Time"].total_seconds()
        if s1 > 0 and s2 > 0:
            j1, j2 = (int(np.searchsorted(idx, np.searchsorted(t, v))) for v in (s1, s1 + s2))
            if 0 < j1 < j2 < len(idx):
                sectors = [j1, j2]
    except Exception:
        sectors = None
    r1 = lambda a: [round(float(v), 1) for v in a]
    data = {"event": event, "season": season,
            "x": r1(tel["X"].to_numpy()[idx] / 10), "y": r1(tel["Y"].to_numpy()[idx] / 10),
            "z": r1(tel["Z"].to_numpy()[idx] / 10), "speed": r1(tel["Speed"].to_numpy()[idx]),
            "length_m": round(float(tel["Distance"].max()), 0),
            "top_speed": round(float(tel["Speed"].max()), 0), "corners": [], "sectors": sectors}
    try:
        ci = s.get_circuit_info()
        data["corners"] = [{"n": int(r.Number), "x": round(float(r.X) / 10, 1), "y": round(float(r.Y) / 10, 1)}
                           for r in ci.corners.itertuples()]
    except Exception:
        pass
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--add-sectors", action="store_true", help="re-download circuits that were saved without sector data")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    res = pd.read_parquet(PROC / "results.parquet")
    latest = (res.sort_values(["season", "round"]).groupby("event").tail(1)[["event", "season", "round"]]
              .sort_values(["season", "round"], ascending=False))
    try:
        for r in latest.itertuples():
            f = OUT_DIR / f"{slug(r.event)}.json"
            if f.exists():
                has_sectors = json.loads(f.read_text()).get("sectors")
                if not (args.add_sectors and not has_sectors):
                    print(f"  {r.event}: cached")
                    continue
            print(f"  {r.event} ({r.season}): downloading telemetry...")
            d = extract(int(r.season), int(r.round), r.event)
            if d:
                f.write_text(json.dumps(d))
                print(f"    saved {len(d['x'])} points, {len(d['corners'])} corners")
    except StopForLimit:
        print("\n*** FastF1 limit reached. Progress saved - wait ~60 min and run again. ***")

    allt = {}
    for f in OUT_DIR.glob("*.json"):
        d = json.loads(f.read_text())
        allt[d["event"]] = d
    (PROC / "tracks.json").write_text(json.dumps(allt))
    print(f"\nWrote {len(allt)} circuits -> data/processed/tracks.json")


if __name__ == "__main__":
    main()
