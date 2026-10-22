"""Save the race calendar (all sessions, UTC) so the app can show IST times."""
import datetime as dt
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed" / "schedule.parquet"


def main():
    import fastf1
    fastf1.Cache.enable_cache(str(ROOT / "f1_cache"))
    fastf1.set_log_level("WARNING")
    rows = []
    for year in (dt.date.today().year, dt.date.today().year + 1):
        try:
            sched = fastf1.get_event_schedule(year, include_testing=False)
        except Exception as e:
            print(f"! no schedule for {year}: {e}")
            continue
        for _, ev in sched.iterrows():
            for i in range(1, 6):
                name, t = ev.get(f"Session{i}"), ev.get(f"Session{i}DateUtc")
                if name is None or pd.isna(name) or name == "" or t is None or pd.isna(t):
                    continue
                rows.append({"season": year, "round": int(ev["RoundNumber"]), "event": ev["EventName"],
                             "country": ev["Country"], "location": ev["Location"],
                             "session": name, "start_utc": pd.Timestamp(t)})
    if rows:
        df = pd.DataFrame(rows)
        df.to_parquet(OUT, index=False)
        print(f"Saved {len(df)} sessions across {df.groupby(['season','round']).ngroups} events -> {OUT}")
    else:
        print("Nothing saved. Check internet / FastF1 rate limit and retry in an hour.")


if __name__ == "__main__":
    main()
