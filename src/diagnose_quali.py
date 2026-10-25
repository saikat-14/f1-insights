"""
Shows, with evidence, why qualifying results are (not) available for a race. Read-only: it changes nothing.

    python src/diagnose_quali.py                 # the next race on the calendar
    python src/diagnose_quali.py --round 18      # a specific round of this season (FastF1 numbering)
    python src/diagnose_quali.py --clear-cache   # also delete FastF1's cached files for that qualifying session

Checks, in order: calendar and session identifier -> FastF1 (event match, API path, raw HTTP probe, the exception
FastF1 hides at DEBUG level, cache contents) -> OpenF1 -> Jolpica (including its own round number) -> the exact
result the app would use.
"""
import argparse
import time
from pathlib import Path

import pandas as pd
import requests

import quali_sources as Q

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
CACHE = ROOT / "f1_cache"


def head(t):
    print(f"\n{'=' * 8} {t} {'=' * (60 - len(t))}")


def probe(url):
    try:
        r = requests.get(url, timeout=(5, 15), headers=Q.UA)
        return f"HTTP {r.status_code} ({len(r.content)} bytes)"
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def pick_event(args):
    sched = pd.read_parquet(PROC / "schedule.parquet")
    sched["start"] = pd.to_datetime(sched["start_utc"], utc=True)
    now = pd.Timestamp.now(tz="UTC")
    if args.round:
        season = args.season or int(sched["season"].max())
        wk = sched[(sched["season"] == season) & (sched["round"] == args.round)]
    else:
        races = sched[(sched["session"] == "Race") & (sched["start"] > now)].sort_values("start")
        nxt = races.iloc[0]
        wk = sched[(sched["season"] == nxt["season"]) & (sched["round"] == nxt["round"])]
    wk = wk.sort_values("start")
    q, r = wk[wk["session"] == "Qualifying"].iloc[0], wk[wk["session"] == "Race"].iloc[0]
    ev = Q.EventRef(int(q["season"]), int(q["round"]), q["event"], q["location"], q["country"], q["start"], r["start"])
    return ev, wk, now


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--round", type=int)
    ap.add_argument("--clear-cache", action="store_true")
    args = ap.parse_args()
    ev, wk, now = pick_event(args)

    head("1. Calendar (our schedule.parquet)")
    print(f"event: {ev.season} round {ev.round} '{ev.name}' ({ev.location}, {ev.country})")
    for _, s in wk.iterrows():
        print(f"  {s['session']:<18} {s['start']:%a %Y-%m-%d %H:%M} UTC")
    ended = ev.quali_start + pd.Timedelta(minutes=75)
    print(f"now: {now:%Y-%m-%d %H:%M} UTC | qualifying scheduled end ~{ended:%H:%M} UTC | has it happened? {'YES' if now > ended else 'not yet'}")

    head("2. FastF1")
    try:
        import fastf1
        print("fastf1 version:", fastf1.__version__)
        fastf1.Cache.enable_cache(str(CACHE))
        sched = fastf1.get_event_schedule(ev.season, include_testing=False)
        row = sched[sched["RoundNumber"] == ev.round].iloc[0]
        print(f"FastF1 round {ev.round} = '{row['EventName']}' | EventDate {row['EventDate']:%Y-%m-%d} | "
              f"F1ApiSupport={row.get('F1ApiSupport', 'n/a')} | event match: {'OK' if Q.same_event(row['EventName'], ev.name) else 'MISMATCH'}")
        ses = fastf1.get_session(ev.season, ev.round, "Q")
        print(f"session identifier 'Q' -> '{ses.name}' on {ses.date}")
        path = getattr(ses, "api_path", None)
        print("api_path:", path)
        if path:
            for base in ("https://livetiming.formula1.com", "https://livetiming-mirror.fastf1.dev"):
                print(f"  probe {base}{path}SessionInfo.json -> {probe(base + path + 'SessionInfo.json')}")
        cdir = CACHE / str(ev.season)
        files = sorted(cdir.glob(f"*{ev.name.replace(' ', '_')}*/*Qualifying*/*")) if cdir.exists() else []
        print(f"cache files for this qualifying: {len(files)}")
        for f in files[:8]:
            print(f"  {f.name}  age {(time.time() - f.stat().st_mtime) / 3600:.1f} h")
        if args.clear_cache:
            print("cleared:", Q.invalidate_fastf1_session_cache(CACHE, ev.season, ev.name), "files")
        try:
            df = Q.fetch_fastf1(ev, CACHE)
            print(f"RESULT: OK, {len(df)} rows")
        except Q.SourceFailure as f:
            print(f"RESULT: {f.status.upper()} -> {f.detail}")
        print("(requests-cache / rate limit: FastF1 allows 500 uncached calls per hour; cached calls do not count)")
    except Exception as e:
        print(f"FastF1 section failed: {type(e).__name__}: {e}")

    head("3. OpenF1 (official classification + starting grid)")
    try:
        sessions = Q.http_json(f"{Q.OPENF1}/sessions", {"year": ev.season, "session_name": "Qualifying"})
        near = sorted(sessions, key=lambda s: abs((Q._utc(s["date_start"]) - ev.quali_start).total_seconds()))[:2]
        for s in near:
            print(f"  candidate key {s['session_key']}: {s.get('location')} {s['date_start']} cancelled={s.get('is_cancelled')}")
        sess = Q._match_openf1_session(sessions, ev)
        print(f"matched session_key {sess['session_key']} ({sess.get('circuit_short_name')})")
        for ep in ("session_result", "starting_grid"):
            try:
                rows = Q.http_json(f"{Q.OPENF1}/{ep}", {"session_key": sess["session_key"]})
                print(f"  {ep}: HTTP 200, {len(rows)} rows")
            except Q.SourceFailure as f:
                print(f"  {ep}: {f.status} -> {f.detail}")
    except Q.SourceFailure as f:
        print(f"OpenF1: {f.status} -> {f.detail}")

    head("4. Jolpica-F1 (own round numbering)")
    try:
        rnd, name = Q._jolpica_round(ev)
        print(f"our round {ev.round} ('{ev.name}') maps to Jolpica round {rnd} ('{name}') "
              f"{'- SAME number' if rnd == ev.round else '- DIFFERENT number: passing FastF1 round would have asked for the wrong race'}")
        md = Q.http_json(f"{Q.JOLPICA}/{ev.season}/{rnd}/qualifying.json", {"limit": 100})["MRData"]
        n = len(Q.parse_jolpica_qualifying(md))
        print(f"  qualifying endpoint: {n} rows")
    except Q.SourceFailure as f:
        print(f"Jolpica: {f.status} -> {f.detail}")

    head("5. What the app will use")
    raw = pd.read_parquet(PROC / "results.parquet")
    known = set(raw.loc[raw["season"] >= ev.season - 1, "driver"])
    out = Q.get_qualifying(ev, known, proc=None, cache_dir=CACHE)
    for a in out.attempts:
        print(f"  {a.source:<8} {a.status:<14} {a.detail}")
    if out.ok:
        grid, gsrc = Q.resolve_grid(out.df)
        d = out.df.assign(Grid=grid.values)
        print(f"\nUSING: {out.source} | grid: {gsrc} | hash {Q.grid_hash(d['Abbreviation'], d['Grid'])}")
        print(d[["Grid", "Position", "Abbreviation", "TeamName", "Q1", "Q2", "Q3", "Status"]].sort_values("Grid").to_string(index=False))
        print("\nNext: python src/auto_update.py --force   (generates and publishes the prediction)")
    else:
        print("\nNo source returned valid results. The app keeps any existing prediction and retries every 15 minutes.")


if __name__ == "__main__":
    main()
