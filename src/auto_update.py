"""
Auto-update. Two independent jobs, both automatic:

  1. Championship: after every Grand Prix, once the official standings are published, re-fetches standings and
     results and recomputes the title probabilities (see championship.py). Never claims an update that did not happen.
  2. Race prediction: waits for qualifying to finish, then pulls new results, re-trains if needed, reads the
     weather forecast and writes next_race.parquet.

    python src/auto_update.py --once         # one check (used by GitHub Actions)
    python src/auto_update.py --loop 15      # keep checking every 15 minutes (a watcher)
    python src/auto_update.py --force        # predict right now (needs finished qualifying)

The Streamlit app also runs this in a background thread, so just keep the app open.
"""
import argparse
import json
import os
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
QUALI_WAIT = timedelta(minutes=75)  # qualifying is ~1h; data needs a little time to appear


def log(msg: str):
    line = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z  {msg}"
    print(line)
    try:
        with open(PROC / "update_log.txt", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _age_h(p: Path) -> float:
    return (time.time() - p.stat().st_mtime) / 3600


def _acquire() -> bool:
    lock = PROC / "update.lock"
    for _ in range(2):
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            if _age_h(lock) > 0.5:  # stale lock
                lock.unlink(missing_ok=True)
            else:
                return False
    return False


def _release():
    (PROC / "update.lock").unlink(missing_ok=True)


def read_meta() -> dict:
    p = PROC / "next_race_meta.json"
    return json.loads(p.read_text()) if p.exists() else {}


_EXTRA = {}  # details for the status file, filled in by _update


def write_status(message: str, **extra):
    """What the app shows while it waits: the real reason, per source, never a vague spinner."""
    state = extra.pop("state", None) or ("ok" if message.startswith("prediction") else "waiting" if message.startswith("waiting") else "info")
    try:
        (PROC / "update_status.json").write_text(json.dumps(
            {"checked_at": datetime.now(timezone.utc).isoformat(), "message": message, "state": state, **extra}, default=str))
    except Exception:
        pass


def _update_championship(force: bool) -> str:
    """Official standings + title probabilities. Isolated so a data-source problem never blocks race predictions."""
    try:
        import championship
        r = championship.update_if_due(proc=PROC, force=force)
        if r["updated"] or not r["ok"]:
            log("championship: " + r["message"])
        return r["message"]
    except Exception as e:
        log(f"championship ERROR {type(e).__name__}: {e}")
        return f"error: {e}"


def update_if_needed(force: bool = False, championship: bool = True) -> str:
    PROC.mkdir(parents=True, exist_ok=True)
    if not _acquire():
        return "another update is already running"
    try:
        champ = _update_championship(force) if championship else None
        _EXTRA.clear()
        pred = _update(force)
        write_status(pred, **_EXTRA)
        return pred if champ is None else f"{pred} | championship: {champ}"
    except Exception as e:
        log("ERROR " + "".join(traceback.format_exception_only(type(e), e)).strip())
        return f"error: {e}"
    finally:
        _release()


def _update(force: bool) -> str:
    sched_path = PROC / "schedule.parquet"
    if force or not sched_path.exists() or _age_h(sched_path) > 168:
        import fetch_schedule
        fetch_schedule.main()
    if not sched_path.exists():
        return "no schedule available yet"

    sched = pd.read_parquet(sched_path)
    sched["start"] = pd.to_datetime(sched["start_utc"], utc=True)
    now = pd.Timestamp.now(tz="UTC")
    races = sched[(sched["session"] == "Race") & (sched["start"] > now)].sort_values("start")
    if races.empty:
        return "no upcoming race in the calendar"
    nxt = races.iloc[0]
    season, rnd = int(nxt["season"]), int(nxt["round"])
    wk = sched[(sched["season"] == season) & (sched["round"] == rnd)]
    q = wk[wk["session"] == "Qualifying"]
    if q.empty:
        return "calendar has no Qualifying session for the next race"
    ready = q["start"].iloc[0] + QUALI_WAIT
    if now < ready and not force:
        return f"waiting for qualifying to finish (prediction auto-starts ~{ready:%a %d %b %H:%M} UTC)"

    out = PROC / "next_race.parquet"
    meta = read_meta()
    same_race = out.exists() and meta.get("season") == season and meta.get("round") == rnd
    import quali_sources as QS
    if not force and same_race and _age_h(out) < 3 and meta.get("grid_source") == QS.GRID_OFFICIAL:
        return "prediction is up to date"

    mdir = PROC / "models"
    if not (mdir / "reg.joblib").exists():
        return "models missing - run python src/backtest.py once first"

    # 1) pull any newly finished races
    import build_dataset
    build_dataset.main(["--start", str(season)])
    results_path = PROC / "results.parquet"

    # 2) retrain if the results are newer than the models
    from features import build_features
    raw = pd.read_parquet(results_path)
    if results_path.stat().st_mtime > (mdir / "reg.joblib").stat().st_mtime:
        from backtest import save_final_models
        save_final_models(build_features(raw), mdir)
        log("models retrained on new results")

    # 3) qualifying classification: independent sources, each validated (see quali_sources.py)
    q_start = q["start"].iloc[0]
    ev = QS.EventRef(season, rnd, nxt["event"], nxt["location"], nxt["country"], q_start, nxt["start"])
    known = set(raw.loc[raw["season"] >= season - 1, "driver"])
    outcome = QS.get_qualifying(ev, known, proc=PROC, cache_dir=ROOT / "f1_cache")
    attempts = [a.as_dict() for a in outcome.attempts]
    if not outcome.ok:
        kept = " The existing prediction for this race is kept." if same_race else ""
        msg = (f"qualifying finished ({q_start:%a %d %b %H:%M} UTC) but no source has returned valid results yet. "
               f"{outcome.summary()}.{kept} Retrying automatically every 15 minutes")
        _EXTRA.update(state="error", attempts=attempts, event=nxt["event"], qualifying_start=q_start.isoformat())
        log(msg)
        return msg
    res = QS.align_team_names(outcome.df, raw)
    grid, grid_source = QS.resolve_grid(res)
    ghash = QS.grid_hash(res["Abbreviation"], grid)

    # 4) weather forecast -> rain switch
    import weather
    wx = weather.event_forecast(nxt["location"], nxt["start"], nxt["country"])
    rain = int(bool(wx and wx.get("rain_prob") is not None and wx["rain_prob"] >= 50))

    # 5) skip the work only if nothing that feeds the model has changed (grid, rain) and the file is fresh
    if not force and same_race and meta.get("grid_hash") == ghash and meta.get("rain_assumed") == rain and _age_h(out) < 3:
        _EXTRA.update(state="ok", attempts=attempts)
        return f"prediction is up to date (grid unchanged; source: {outcome.source})"

    # 6) predict + publish (atomic write: the app never reads a half-written file, and a failure keeps the old one)
    from predict_next import predict_race, stub_from_quali
    stub = stub_from_quali(season, rnd, nxt["event"], nxt["country"], res, rain)
    pred = predict_race(raw, stub, mdir)
    tmp = out.with_name("next_race.tmp.parquet")
    pred.to_parquet(tmp, index=False)
    os.replace(tmp, out)
    (PROC / "next_race_meta.json").write_text(json.dumps({
        "season": season, "round": rnd, "event": nxt["event"], "country": nxt["country"],
        "generated_at": datetime.now(timezone.utc).isoformat(), "rain_assumed": rain, "weather": wx,
        "quali_source": outcome.source, "grid_source": grid_source, "grid_hash": ghash, "quali_attempts": attempts}, default=str))
    msg = (f"prediction updated for {season} R{rnd} {nxt['event']} (qualifying from {outcome.source}; grid: {grid_source}; "
           f"rain assumed: {bool(rain)})")
    _EXTRA.update(state="ok", attempts=attempts)
    log(msg)
    return msg


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", type=int, default=0, help="minutes between checks")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.loop:
        while True:
            print(update_if_needed(force=a.force))
            time.sleep(a.loop * 60)
    else:
        print(update_if_needed(force=a.force))
