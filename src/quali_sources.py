"""
Qualifying results from several independent sources, normalised to one schema and validated before use.

Sources (tried in this order, configurable with F1_QUALI_SOURCES="fastf1,openf1,jolpica"):
  1. FastF1   - live-timing archive. Its failures are logged only at DEBUG, so the real exception is captured here.
  2. OpenF1   - /session_result (official classification, Q1/Q2/Q3) and /starting_grid (actual grid, penalties applied).
                OpenF1 documents that both become available a few minutes after the official results are published
                on formula1.com.
  3. Jolpica  - Ergast-compatible /{season}/{round}/qualifying. It uses ITS OWN round numbers, so the round is found
                by matching race dates, never by reusing FastF1's round.

Every provider either returns a DataFrame in SCHEMA or raises SourceFailure(status, detail). Nothing here is
specific to one race: the event to look for comes from the calendar.
"""
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import requests

UA = {"User-Agent": "F1-Insights/1.0"}
OPENF1 = "https://api.openf1.org/v1"
JOLPICA = "https://api.jolpi.ca/ergast/f1"
SCHEMA = ["Abbreviation", "TeamName", "Position", "Q1", "Q2", "Q3", "GridPosition", "Status"]
GRID_OFFICIAL = "official starting grid"
GRID_CLASSIFICATION = "qualifying classification (grid penalties not applied)"


class SourceFailure(Exception):
    """status: not_published | rate_limited | timeout | network | http_error | invalid | mismatch | error"""

    def __init__(self, status: str, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


@dataclass
class EventRef:
    """What we are looking for. Built from the calendar only; never hard-coded."""
    season: int
    round: int
    name: str
    location: str
    country: str
    quali_start: pd.Timestamp  # UTC
    race_start: pd.Timestamp  # UTC


@dataclass
class Attempt:
    source: str
    status: str
    detail: str

    def as_dict(self):
        return {"source": self.source, "status": self.status, "detail": self.detail}


@dataclass
class Outcome:
    df: "pd.DataFrame | None"
    source: "str | None"
    grid_source: "str | None"
    attempts: list = field(default_factory=list)

    @property
    def ok(self):
        return self.df is not None

    def summary(self) -> str:
        return "; ".join(f"{a.source}: {a.status} ({a.detail})" for a in self.attempts)


# =============================================================== HTTP with honest error classes
def http_json(url, params=None, timeout=(5, 15), retries=2, pause=0.6):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers=UA)
        except requests.Timeout:
            last = SourceFailure("timeout", f"no answer within {timeout[1]} s")
            time.sleep(pause * (i + 1))
            continue
        except requests.ConnectionError:
            raise SourceFailure("network", "cannot connect (offline, DNS or firewall)")
        code = r.status_code
        if code == 404:
            raise SourceFailure("not_published", "HTTP 404 (not published yet)")
        if code in (401, 403):
            raise SourceFailure("http_error", f"HTTP {code} (access restricted, e.g. a live session is in progress)")
        if code == 429:
            last = SourceFailure("rate_limited", "HTTP 429 (too many requests)")
            time.sleep(2 * (i + 1))
            continue
        if code >= 500:
            last = SourceFailure("http_error", f"HTTP {code} (server error)")
            time.sleep(pause * (i + 1))
            continue
        if code != 200:
            raise SourceFailure("http_error", f"HTTP {code}")
        try:
            return r.json()
        except ValueError:
            raise SourceFailure("invalid", "response was not valid JSON")
    raise last or SourceFailure("error", "request failed")


# =============================================================== small helpers
def _utc(x) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _norm_name(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower().replace("grand prix", "")).strip()


def same_event(a, b) -> bool:
    a, b = _norm_name(a), _norm_name(b)
    return bool(a and b and (a == b or a in b or b in a))


def _secs(v):
    """seconds (float) -> Timedelta; None/NaN/0/negative -> NaT."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return pd.NaT
    return pd.to_timedelta(v, unit="s") if v > 0 and v == v else pd.NaT


def parse_lap_time(s):
    """'1:22.345' -> 82.345; '' / None / garbage -> None."""
    m = re.match(r"^\s*(?:(\d+):)?(\d+)\.(\d+)\s*$", s or "")
    if not m:
        return None
    mins, secs, frac = m.groups()
    return int(mins or 0) * 60 + int(secs) + float("0." + frac)


# =============================================================== provider 1: FastF1
class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def classify_text(text: str):
    t = text.lower()
    if "sessionnotavailable" in t or "no data for this session" in t:
        return "not_published"
    if "ratelimit" in t or "calls/h" in t or "rate limit" in t:
        return "rate_limited"
    if "timeout" in t or "timed out" in t:
        return "timeout"
    if "connection" in t or "name resolution" in t or "max retries" in t:
        return "network"
    return "error"


def _captured_reason(records):
    """The exception FastF1 swallows is logged at DEBUG with exc_info; pull it out."""
    seen = []
    for r in records:
        if r.exc_info and r.exc_info[1] is not None:
            s = f"{type(r.exc_info[1]).__name__}: {r.exc_info[1]}"
            if s not in seen:
                seen.append(s)
    return seen


def invalidate_fastf1_session_cache(cache_dir, season, event_name):
    """Remove FastF1's parsed-data pickles for this event's qualifying so a half-loaded copy cannot be reused."""
    removed = 0
    try:
        slug = re.sub(r"\s+", "_", str(event_name).strip())
        for f in Path(cache_dir).glob(f"{season}/*{slug}*/*Qualifying*/*.ff1pkl"):
            f.unlink()
            removed += 1
    except Exception:
        pass
    return removed


def fetch_fastf1(ev: EventRef, cache_dir=None) -> pd.DataFrame:
    try:
        import fastf1
    except ImportError:
        raise SourceFailure("error", "the fastf1 package is not installed")
    cap, lg = _Capture(), logging.getLogger("fastf1")
    old_level = lg.level
    lg.addHandler(cap)
    lg.setLevel(logging.DEBUG)
    try:
        if cache_dir:
            fastf1.Cache.enable_cache(str(cache_dir))
        fastf1.set_log_level("WARNING")
        lg.setLevel(logging.DEBUG)
        ses = fastf1.get_session(ev.season, ev.round, "Q")  # identifier "Q" = the Grand Prix qualifying (not Sprint Qualifying)
        info = ses.event
        if int(info["RoundNumber"]) != ev.round or not same_event(info["EventName"], ev.name):
            raise SourceFailure("mismatch", f"FastF1 round {ev.round} is '{info['EventName']}', expected '{ev.name}'")
        ses.load(laps=False, telemetry=False, weather=False, messages=False)
        res = getattr(ses, "results", None)
    except SourceFailure:
        raise
    except Exception as e:
        raise SourceFailure(classify_text(f"{type(e).__name__}: {e}"), f"{type(e).__name__}: {e}")
    finally:
        lg.removeHandler(cap)
        lg.setLevel(old_level)
    reasons = _captured_reason(cap.records)
    if res is None or len(res) == 0:
        raise SourceFailure(classify_text(" ".join(reasons)) if reasons else "not_published",
                            ("; ".join(reasons[:2]) or "session loaded but contains no classification"))
    q = res[["Q1", "Q2", "Q3"]] if all(c in res for c in ("Q1", "Q2", "Q3")) else None
    if q is None or q.isna().all().all():
        if cache_dir:
            invalidate_fastf1_session_cache(cache_dir, ev.season, ev.name)
        raise SourceFailure("not_published", "drivers loaded but no Q1/Q2/Q3 times yet (stale cache cleared)")
    return pd.DataFrame({
        "Abbreviation": res["Abbreviation"].values, "TeamName": res["TeamName"].values,
        "Position": pd.to_numeric(res["Position"], errors="coerce").values,
        "Q1": res["Q1"].values, "Q2": res["Q2"].values, "Q3": res["Q3"].values,
        "GridPosition": float("nan"), "Status": ""})


# =============================================================== provider 2: OpenF1
def _match_openf1_session(sessions, ev: EventRef):
    live = [s for s in sessions if not s.get("is_cancelled") and s.get("date_start")]
    best = min(live, key=lambda s: abs((_utc(s["date_start"]) - ev.quali_start).total_seconds()), default=None)
    if best is not None and abs((_utc(best["date_start"]) - ev.quali_start).total_seconds()) <= 12 * 3600:
        return best
    for s in live:  # same weekend by place and date window, if the clock times differ
        near = abs((_utc(s["date_start"]) - ev.quali_start).total_seconds()) <= 3 * 86400
        if near and (same_event(s.get("location"), ev.location) or same_event(s.get("country_name"), ev.country)):
            return s
    raise SourceFailure("not_published", f"OpenF1 has no Qualifying session near {ev.quali_start:%Y-%m-%d %H:%M} UTC "
                                         "(its session list refreshes daily at midnight UTC)")


def _openf1_driver_map(key):
    rows = http_json(f"{OPENF1}/drivers", {"session_key": key})
    return {int(r["driver_number"]): (str(r.get("name_acronym") or "").upper(), r.get("team_name") or "") for r in rows}


def _openf1_grid(sess, dmap):
    """Official starting grid (penalties applied). Tries the qualifying session key, then the race's."""
    keys = [sess["session_key"]]
    try:
        race = http_json(f"{OPENF1}/sessions", {"meeting_key": sess["meeting_key"], "session_name": "Race"})
        keys += [r["session_key"] for r in race if r.get("session_key") not in keys]
    except SourceFailure:
        pass
    for k in keys:
        time.sleep(0.4)
        try:
            rows = http_json(f"{OPENF1}/starting_grid", {"session_key": k})
        except SourceFailure as e:
            if e.status == "not_published":
                continue
            raise
        grid = {}
        for r in rows or []:
            code = dmap.get(int(r["driver_number"]), ("", ""))[0]
            if code and r.get("position") is not None:
                grid[code] = int(r["position"])
        if grid:
            return grid
    return {}


def fetch_openf1(ev: EventRef) -> pd.DataFrame:
    sessions = http_json(f"{OPENF1}/sessions", {"year": ev.season, "session_name": "Qualifying"})
    sess = _match_openf1_session(sessions, ev)
    key = sess["session_key"]
    time.sleep(0.4)
    result = http_json(f"{OPENF1}/session_result", {"session_key": key})
    if not result:
        raise SourceFailure("not_published", "OpenF1 has the session but no classification yet (official results pending)")
    time.sleep(0.4)
    dmap = _openf1_driver_map(key)
    rows = []
    for r in result:
        code, team = dmap.get(int(r["driver_number"]), ("", ""))
        dur = r.get("duration")
        q = list(dur) if isinstance(dur, (list, tuple)) else [dur, None, None]
        q = (q + [None, None, None])[:3]
        status = "DSQ" if r.get("dsq") else "DNS" if r.get("dns") else "DNF" if r.get("dnf") else ""
        rows.append({"Abbreviation": code, "TeamName": team, "Position": r.get("position"),
                     "Q1": _secs(q[0]), "Q2": _secs(q[1]), "Q3": _secs(q[2]), "GridPosition": float("nan"), "Status": status})
    df = pd.DataFrame(rows)
    try:
        grid = _openf1_grid(sess, dmap)
        df["GridPosition"] = df["Abbreviation"].map(grid).astype(float)
    except SourceFailure:
        pass  # the classification is still valid; the grid just stays "penalties not applied"
    return df


def enrich_with_starting_grid(df: pd.DataFrame, ev: EventRef) -> pd.DataFrame:
    """For results from other sources: attach OpenF1's official starting grid so penalties are respected."""
    try:
        sess = _match_openf1_session(http_json(f"{OPENF1}/sessions", {"year": ev.season, "session_name": "Qualifying"}), ev)
        grid = _openf1_grid(sess, _openf1_driver_map(sess["session_key"]))
    except Exception:
        return df
    d = df.copy()
    mapped = d["Abbreviation"].map(grid).astype(float)
    if mapped.notna().sum() >= 0.9 * len(d):
        d["GridPosition"] = mapped
    return d


# =============================================================== provider 3: Jolpica (own round numbers!)
def _jolpica_round(ev: EventRef):
    md = http_json(f"{JOLPICA}/{ev.season}.json", {"limit": 100})["MRData"]
    races = (md.get("RaceTable") or {}).get("Races") or []
    cand = []
    for r in races:
        t = r.get("time", "12:00:00Z")
        start = _utc(f"{r['date']}T{t if t.endswith('Z') else t + 'Z'}")
        cand.append((abs((start - ev.race_start).total_seconds()), r))
    cand.sort(key=lambda x: x[0])
    if cand and cand[0][0] <= 36 * 3600:
        return int(cand[0][1]["round"]), cand[0][1].get("raceName", "")
    named = [r for _d, r in cand if same_event(r.get("raceName"), ev.name)]
    if named:
        return int(named[0]["round"]), named[0].get("raceName", "")
    cal = ", ".join(f"R{r['round']} {r.get('raceName', '')} {r['date']}" for _d, r in cand[:3])
    raise SourceFailure("mismatch", f"no Jolpica race within 36 h of {ev.race_start:%Y-%m-%d} (nearest: {cal or 'none'})")


def parse_jolpica_qualifying(md) -> pd.DataFrame:
    races = (md.get("RaceTable") or {}).get("Races") or []
    rows = (races[0].get("QualifyingResults") if races else None) or []
    out = []
    for r in rows:
        drv, cons = r.get("Driver") or {}, r.get("Constructor") or {}
        t = [parse_lap_time(r.get(q)) for q in ("Q1", "Q2", "Q3")]
        out.append({"Abbreviation": drv.get("code") or str(drv.get("driverId", "?"))[:3].upper(), "TeamName": cons.get("name", ""),
                    "Position": int(r["position"]) if str(r.get("position", "")).isdigit() else None,
                    **{q: (pd.to_timedelta(v, unit="s") if v else pd.NaT) for q, v in zip(("Q1", "Q2", "Q3"), t)},
                    "GridPosition": float("nan"), "Status": ""})
    return pd.DataFrame(out)


def fetch_jolpica(ev: EventRef) -> pd.DataFrame:
    rnd, _name = _jolpica_round(ev)
    md = http_json(f"{JOLPICA}/{ev.season}/{rnd}/qualifying.json", {"limit": 100})["MRData"]
    df = parse_jolpica_qualifying(md)
    if df.empty:
        raise SourceFailure("not_published", f"Jolpica round {rnd} has no qualifying results yet")
    return df


# =============================================================== normalise + validate
def normalize(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    for c in SCHEMA:  # a source may omit columns (e.g. no Q2/Q3 for an early knock-out): fill with correctly typed "unknown"
        if c not in d:
            d[c] = (pd.Series(pd.NaT, index=d.index, dtype="timedelta64[ns]") if c in ("Q1", "Q2", "Q3")
                    else float("nan") if c in ("GridPosition", "Position") else "")
    d["Abbreviation"] = d["Abbreviation"].astype(str).str.upper().str.strip()
    d["TeamName"] = d["TeamName"].fillna("").astype(str)
    for q in ("Q1", "Q2", "Q3"):
        d[q] = pd.to_timedelta(d[q], errors="coerce")
    d["Position"] = pd.to_numeric(d["Position"], errors="coerce")
    d["GridPosition"] = pd.to_numeric(d["GridPosition"], errors="coerce")
    d["Status"] = d["Status"].fillna("").astype(str)
    return d[SCHEMA].sort_values("Position", na_position="last").reset_index(drop=True)


def validate(d: pd.DataFrame, known_codes=None, min_drivers=10) -> list:
    """Return a list of problems; empty means the classification is safe to use as model input."""
    p = []
    if len(d) < min_drivers:
        return [f"only {len(d)} drivers (expected a full grid)"]
    if d["Abbreviation"].duplicated().any():
        p.append("duplicate driver codes: " + ", ".join(sorted(d.loc[d["Abbreviation"].duplicated(), "Abbreviation"])))
    bad = d.loc[~d["Abbreviation"].str.fullmatch(r"[A-Z]{3}"), "Abbreviation"].tolist()
    if bad:
        p.append(f"invalid driver codes {bad[:3]}")
    pos = d["Position"].dropna()
    if pos.empty or pos.min() != 1 or pos.duplicated().any():
        p.append("positions are missing, duplicated, or there is no pole sitter")
    times = pd.concat([d[q].dt.total_seconds() for q in ("Q1", "Q2", "Q3")], axis=1)
    if ((times < 30) | (times > 200)).any().any():
        p.append("implausible lap times (outside 30-200 s)")
    if times.notna().any(axis=1).mean() < 0.5:
        p.append("fewer than half the drivers have a lap time")
    pole = d[d["Position"] == 1]
    if len(pole) and times.loc[pole.index[0]].isna().all():
        p.append("the pole sitter has no lap time")
    # within each knock-out phase, a better position must never have a slower time
    groups = {"Q3": d["Q3"].notna(),
              "Q2": d["Q3"].isna() & d["Q2"].notna(),
              "Q1": d["Q3"].isna() & d["Q2"].isna() & d["Q1"].notna()}
    for q, mask in groups.items():
        g = d[mask].sort_values("Position")
        if len(g) > 1 and not g[q].is_monotonic_increasing:
            p.append(f"{q} times are not in classification order (mixed-up or wrong data)")
    if known_codes:
        overlap = len(set(d["Abbreviation"]) & set(known_codes)) / len(d)
        if overlap < 0.7:
            p.append(f"only {overlap:.0%} of drivers match this season's known drivers (wrong event?)")
    return p


def resolve_grid(d: pd.DataFrame):
    """Official starting grid when available and consistent (penalties applied), otherwise the classification order.
    Always returns unique integer grid slots 1..N for every driver, with missing-time drivers at the back."""
    g = pd.to_numeric(d["GridPosition"], errors="coerce")
    have = g.notna()
    if have.mean() >= 0.9 and not g[have].duplicated().any():
        key = g.fillna(1000) + d["Position"].fillna(99) / 1000  # pit-lane starters (no grid slot) go last
        return key.rank(method="first").astype(int), GRID_OFFICIAL
    return d["Position"].fillna(1000).rank(method="first").astype(int), GRID_CLASSIFICATION


def align_team_names(df: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    """Use each driver's most recent team name from our own results, so team-form features line up
    (feeds name teams differently, e.g. 'Red Bull' vs 'Red Bull Racing')."""
    last = raw.sort_values(["season", "round"]).drop_duplicates("driver", keep="last").set_index("driver")["team"].to_dict()
    d = df.copy()
    d["TeamName"] = [last.get(c) or t for c, t in zip(d["Abbreviation"], d["TeamName"])]
    return d


def grid_hash(codes, grid) -> str:
    return hashlib.sha1(json.dumps(sorted((str(c), int(g)) for c, g in zip(codes, grid))).encode()).hexdigest()[:12]


# =============================================================== orchestration
PROVIDERS = {"fastf1": fetch_fastf1, "openf1": fetch_openf1, "jolpica": fetch_jolpica}


def source_order():
    env = os.environ.get("F1_QUALI_SOURCES", "fastf1,openf1,jolpica")
    return [s.strip() for s in env.split(",") if s.strip() in PROVIDERS] or list(PROVIDERS)


def _health_path(proc):
    return Path(proc) / "source_health.json" if proc else None


def _backed_off(proc, name, minutes=20):
    p = _health_path(proc)
    try:
        h = json.loads(p.read_text()).get(name) if p and p.exists() else None
        if h and h["status"] in ("not_published", "rate_limited") and \
                (pd.Timestamp.now(tz="UTC") - _utc(h["at"])).total_seconds() < minutes * 60:
            return h
    except Exception:
        pass
    return None


def _note_health(proc, name, status):
    p = _health_path(proc)
    if not p:
        return
    try:
        h = json.loads(p.read_text()) if p.exists() else {}
        h[name] = {"status": status, "at": pd.Timestamp.now(tz="UTC").isoformat()}
        p.write_text(json.dumps(h))
    except Exception:
        pass


def get_qualifying(ev: EventRef, known_codes=None, proc=None, cache_dir=None, order=None) -> Outcome:
    """Try each source in turn; return the first one that passes validation. Never raises."""
    attempts = []
    for name in (order or source_order()):
        if name == "fastf1":  # FastF1 is rate limited (500 calls/h): do not hammer it right after it said "not yet"
            h = _backed_off(proc, name)
            if h:
                attempts.append(Attempt(name, "skipped", f"backing off after '{h['status']}' at {_utc(h['at']):%H:%M} UTC"))
                continue
        try:
            raw = fetch_fastf1(ev, cache_dir) if name == "fastf1" else PROVIDERS[name](ev)
            d = normalize(raw)
            problems = validate(d, known_codes)
            if problems:
                attempts.append(Attempt(name, "invalid", "; ".join(problems)))
                continue
            if name != "openf1" and resolve_grid(d)[1] == GRID_CLASSIFICATION:  # try to respect grid penalties
                d = enrich_with_starting_grid(d, ev)
            _g, gsrc = resolve_grid(d)
            attempts.append(Attempt(name, "ok", f"{len(d)} drivers; grid: {gsrc}"))
            return Outcome(d, name, gsrc, attempts)
        except SourceFailure as f:
            attempts.append(Attempt(name, f.status, f.detail))
            if name == "fastf1":
                _note_health(proc, name, f.status)
        except Exception as e:  # a provider bug must never take the app down
            attempts.append(Attempt(name, "error", f"{type(e).__name__}: {e}"))
    return Outcome(None, None, None, attempts)
