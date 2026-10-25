"""
Qualifying data layer: FastF1 failure + fallbacks, validation, timeouts, round mapping, penalties, and a full prediction run.
All HTTP is faked with payloads shaped like the documented OpenF1 / Jolpica-F1 responses.
"""
import json
import logging
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import quali_sources as Q

CODES = [chr(65 + i) * 3 for i in range(20)]                    # AAA, BBB, ... TTT (stable 3-letter ids)
TEAMS = [f"Team {i}" for i in range(10)]
NOW = pd.Timestamp.now(tz="UTC")
EV = Q.EventRef(2026, 18, "United States Grand Prix", "Austin", "United States",
                NOW - pd.Timedelta(hours=6), NOW + pd.Timedelta(hours=18))


# ----------------------------------------------------------------------------- fakes
class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.content = data, status, b"x"

    def json(self):
        if self._d is None:
            raise ValueError("no json")
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class Web:
    """First matching route wins; unknown URLs return 404 (that is what OpenF1 does before results are published)."""
    def __init__(self):
        self.routes, self.calls = [], []

    def add(self, needle, data=None, status=200, exc=None):
        self.routes.append((needle, data, status, exc))

    def get(self, url, params=None, **kw):
        full = url + ("?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items())) if params else "")
        self.calls.append(full)
        for needle, data, status, exc in self.routes:
            if needle in full:
                if exc:
                    raise exc
                return Resp(data, status)
        return Resp(None, 404)


def q_times(pos):
    return (92.0 + pos * 0.05, 91.0 + pos * 0.05 if pos <= 15 else None, 90.0 + pos * 0.05 if pos <= 10 else None)


def fmt(t):
    return "" if t is None else f"{int(t // 60)}:{t % 60:06.3f}"


def openf1_routes(web, grid=None, session_key=1001, results=True, with_race_grid=True):
    web.add("/sessions?session_name=Qualifying&year=2026", [{
        "session_key": session_key, "meeting_key": 77, "date_start": EV.quali_start.isoformat(), "location": "Austin",
        "country_name": "United States", "is_cancelled": False, "circuit_short_name": "Austin"}])
    if results:
        web.add(f"/session_result?session_key={session_key}", [
            {"driver_number": 100 + i, "position": i + 1, "duration": list(q_times(i + 1)), "dnf": False, "dns": False, "dsq": False}
            for i in range(20)])
    web.add(f"/drivers?session_key={session_key}", [
        {"driver_number": 100 + i, "name_acronym": CODES[i], "team_name": TEAMS[i // 2]} for i in range(20)])
    web.add("/sessions?meeting_key=77&session_name=Race", [{"session_key": 1002}])
    if grid and with_race_grid:
        web.add("/starting_grid?session_key=1002", [{"driver_number": 100 + CODES.index(c), "position": p} for c, p in grid.items()])


def jolpica_routes(web, our_round=18, their_round=19):
    web.add("/ergast/f1/2026.json", {"MRData": {"RaceTable": {"Races": [
        {"round": str(their_round - 1), "raceName": "Singapore Grand Prix", "date": "2026-10-11", "time": "12:00:00Z"},
        {"round": str(their_round), "raceName": "United States Grand Prix", "date": f"{EV.race_start:%Y-%m-%d}", "time": f"{EV.race_start:%H:%M:%S}Z"}]}}})
    web.add(f"/ergast/f1/2026/{their_round}/qualifying.json", {"MRData": {"RaceTable": {"Races": [{"QualifyingResults": [
        {"position": str(i + 1), "Driver": {"code": CODES[i]}, "Constructor": {"name": TEAMS[i // 2]},
         "Q1": fmt(q_times(i + 1)[0]), "Q2": fmt(q_times(i + 1)[1]), "Q3": fmt(q_times(i + 1)[2])} for i in range(20)]}]}}})


class SessionNotAvailableError(Exception):
    pass


class RateLimitExceededError(Exception):
    pass


class FakeSession:
    def __init__(self, name="United States Grand Prix", rnd=18, results=None, hidden=None):
        self.event, self._results, self._hidden = {"RoundNumber": rnd, "EventName": name}, results, hidden

    def load(self, **k):
        if self._hidden is not None:  # what FastF1 really does: WARNING on the console, the exception only at DEBUG
            log = logging.getLogger("fastf1.core")
            log.warning("Failed to load session info data!")
            log.debug("Traceback for failure in session info data", exc_info=self._hidden)
        self.results = self._results


def install_fastf1(session):
    m = types.ModuleType("fastf1")
    m.Cache = types.SimpleNamespace(enable_cache=lambda *a, **k: None)
    m.set_log_level = lambda *a, **k: None
    m.get_session = lambda *a, **k: session
    saved = sys.modules.get("fastf1")
    sys.modules["fastf1"] = m
    return saved


def restore_fastf1(saved):
    if saved is None:
        sys.modules.pop("fastf1", None)
    else:
        sys.modules["fastf1"] = saved


def with_web(monkeypatch, web):
    monkeypatch.setattr(requests, "get", web.get)
    monkeypatch.setattr(Q.time, "sleep", lambda s: None)


# ----------------------------------------------------------------------------- 1. FastF1 failure: real reason, fallback
def test_fastf1_failure_exposes_the_hidden_exception_and_classifies_it():
    saved = install_fastf1(FakeSession(hidden=SessionNotAvailableError("No data for this session! try again in a few minutes")))
    try:
        try:
            Q.fetch_fastf1(EV)
            assert False, "must fail"
        except Q.SourceFailure as f:
            assert f.status == "not_published" and "SessionNotAvailableError" in f.detail
        restore_fastf1(install_fastf1(FakeSession(hidden=RateLimitExceededError("any API: 500 calls/h"))))
        install_fastf1(FakeSession(hidden=RateLimitExceededError("any API: 500 calls/h")))
        try:
            Q.fetch_fastf1(EV)
            assert False, "must fail"
        except Q.SourceFailure as f:
            assert f.status == "rate_limited" and "RateLimitExceededError" in f.detail
    finally:
        restore_fastf1(saved)


def test_fastf1_returning_the_wrong_event_is_rejected():
    saved = install_fastf1(FakeSession(name="Singapore Grand Prix", rnd=18))     # round number maps to another race
    try:
        try:
            Q.fetch_fastf1(EV)
            assert False
        except Q.SourceFailure as f:
            assert f.status == "mismatch" and "Singapore" in f.detail
    finally:
        restore_fastf1(saved)


def test_fastf1_fails_openf1_succeeds_and_grid_penalties_are_respected(tmp_path, monkeypatch):
    web, saved = Web(), install_fastf1(FakeSession(hidden=SessionNotAvailableError("No data for this session!")))
    penalised = {c: i + 1 for i, c in enumerate(CODES)}
    penalised.update({"CCC": 8, "DDD": 3, "EEE": 4, "FFF": 5, "GGG": 6, "HHH": 7, "BBB": 2})  # CCC (P3 in quali) drops five places
    openf1_routes(web, grid=penalised)
    with_web(monkeypatch, web)
    try:
        out = Q.get_qualifying(EV, set(CODES), proc=tmp_path)
    finally:
        restore_fastf1(saved)
    assert out.ok and out.source == "openf1"
    assert [a.source for a in out.attempts][:2] == ["fastf1", "openf1"] and out.attempts[0].status == "not_published"
    grid, gsrc = Q.resolve_grid(out.df)
    assert gsrc == Q.GRID_OFFICIAL
    g = dict(zip(out.df["Abbreviation"], grid))
    assert g["CCC"] == 8 and g["DDD"] == 3 and sorted(grid) == list(range(1, 21))     # penalty applied, grid is a clean 1..20
    assert out.df.loc[out.df["Abbreviation"] == "CCC", "Position"].iloc[0] == 3        # classification itself is untouched


def test_without_a_published_starting_grid_the_classification_is_used_and_labelled(tmp_path, monkeypatch):
    web = Web()
    openf1_routes(web, grid=None)
    with_web(monkeypatch, web)
    out = Q.get_qualifying(EV, set(CODES), order=["openf1"])
    assert out.ok and out.grid_source == Q.GRID_CLASSIFICATION


# ----------------------------------------------------------------------------- 2. normalisation: missing times, DSQ
def test_missing_lap_times_and_disqualification_are_handled_not_invented(monkeypatch):
    web = Web()
    openf1_routes(web)
    rows = [{"driver_number": 100 + i, "position": i + 1, "duration": list(q_times(i + 1)), "dnf": False, "dns": False, "dsq": False}
            for i in range(19)]
    rows.append({"driver_number": 119, "position": 20, "duration": [None, None, None], "dnf": False, "dns": False, "dsq": True})
    web.routes.insert(0, ("/session_result?session_key=1001", rows, 200, None))
    with_web(monkeypatch, web)
    out = Q.get_qualifying(EV, set(CODES), order=["openf1"])
    assert out.ok
    ttt = out.df[out.df["Abbreviation"] == "TTT"].iloc[0]
    assert ttt[["Q1", "Q2", "Q3"]].isna().all() and ttt["Status"] == "DSQ"
    import predict_next
    stub = predict_next.stub_from_quali(2026, 18, "United States Grand Prix", "United States", out.df, 0)
    last = stub[stub["driver"] == "TTT"].iloc[0]
    assert last["quali_missing"] == 1 and np.isnan(last["quali_best_s"]) and last["grid"] == 20
    assert stub["grid"].is_unique and sorted(stub["grid"]) == list(range(1, 21))


# ----------------------------------------------------------------------------- 3. Jolpica uses its own round numbers
def test_jolpica_round_is_matched_by_date_not_by_the_fastf1_round(monkeypatch):
    web = Web()
    jolpica_routes(web, our_round=18, their_round=19)          # calendars differ by one
    with_web(monkeypatch, web)
    out = Q.get_qualifying(EV, set(CODES), order=["jolpica"])
    assert out.ok and out.source == "jolpica"
    urls = " ".join(web.calls)
    assert "/2026/19/qualifying.json" in urls and "/2026/18/qualifying.json" not in urls


def test_jolpica_with_no_matching_race_reports_a_calendar_mismatch(monkeypatch):
    web = Web()
    web.add("/ergast/f1/2026.json", {"MRData": {"RaceTable": {"Races": [
        {"round": "1", "raceName": "Australian Grand Prix", "date": "2026-03-08", "time": "04:00:00Z"}]}}})
    with_web(monkeypatch, web)
    out = Q.get_qualifying(EV, set(CODES), order=["jolpica"])
    assert not out.ok and out.attempts[0].status == "mismatch"


# ----------------------------------------------------------------------------- 4. invalid fallback data is rejected
def _bad_session_result(kind):
    rows = [{"driver_number": 100 + i, "position": i + 1, "duration": list(q_times(i + 1)), "dnf": False, "dns": False, "dsq": False}
            for i in range(20)]
    if kind == "short":
        rows = rows[:5]
    elif kind == "unsorted":
        rows[0]["duration"][2], rows[1]["duration"][2] = rows[1]["duration"][2], rows[0]["duration"][2]   # P1 slower than P2 in Q3
    elif kind == "implausible":
        rows[3]["duration"][2] = 9.0
    elif kind == "duplicate_position":
        rows[5]["position"] = 5
    return rows


def test_invalid_data_is_rejected_and_the_next_source_is_used(monkeypatch):
    for kind in ("short", "unsorted", "implausible", "duplicate_position"):
        web = Web()
        openf1_routes(web)
        web.routes.insert(0, ("/session_result?session_key=1001", _bad_session_result(kind), 200, None))
        jolpica_routes(web)
        with_web(monkeypatch, web)
        out = Q.get_qualifying(EV, set(CODES), order=["openf1", "jolpica"])
        assert out.attempts[0].source == "openf1" and out.attempts[0].status == "invalid", kind
        assert out.ok and out.source == "jolpica", kind


def test_data_for_the_wrong_drivers_is_rejected():
    d = Q.normalize(pd.DataFrame({"Abbreviation": CODES, "TeamName": "T", "Position": range(1, 21),
                                  "Q1": [pd.Timedelta(seconds=q_times(i + 1)[0]) for i in range(20)]}))
    assert any("wrong event" in p for p in Q.validate(d, known_codes={"XXX", "YYY", "ZZZ"}))
    assert Q.validate(d, known_codes=set(CODES)) == [] or all("Q" not in p for p in Q.validate(d, known_codes=set(CODES)))


# ----------------------------------------------------------------------------- 5. timeouts and total failure
def test_timeouts_are_classified_and_the_next_source_is_tried(monkeypatch):
    web = Web()
    web.add("api.openf1.org", exc=requests.Timeout("slow"))
    jolpica_routes(web)
    with_web(monkeypatch, web)
    out = Q.get_qualifying(EV, set(CODES), order=["openf1", "jolpica"])
    assert out.attempts[0].status == "timeout" and out.ok and out.source == "jolpica"


def test_when_every_source_fails_the_outcome_explains_each_one(monkeypatch):
    web = Web()
    web.add("openf1", exc=requests.Timeout("slow"))
    web.add("jolpi.ca", exc=requests.ConnectionError("down"))
    saved = install_fastf1(FakeSession(hidden=SessionNotAvailableError("No data for this session!")))
    with_web(monkeypatch, web)
    try:
        out = Q.get_qualifying(EV, set(CODES))
    finally:
        restore_fastf1(saved)
    assert not out.ok and out.df is None
    assert [(a.source, a.status) for a in out.attempts] == [("fastf1", "not_published"), ("openf1", "timeout"), ("jolpica", "network")]
    assert "not happened" not in out.summary().lower()


# ----------------------------------------------------------------------------- 6. full pipeline with the real model code
def _synthetic_raw():
    rng = np.random.default_rng(4)
    rows = []
    team_of = {c: TEAMS[i // 2] for i, c in enumerate(CODES)}
    for season, n_rounds in ((2025, 12), (2026, 6)):
        for rnd in range(1, n_rounds + 1):
            pace = {c: -(len(CODES) - i) * 0.05 + rng.normal(0, .5) for i, c in enumerate(CODES)}
            order = sorted(CODES, key=lambda c: pace[c])
            dnf = {c: rng.random() < .1 for c in CODES}
            fin = {c: i + 1 for i, c in enumerate(sorted(CODES, key=lambda c: pace[c] + rng.normal(0, 1) + (50 if dnf[c] else 0)))}
            for c in CODES:
                gp = order.index(c) + 1
                rows.append(dict(season=season, round=rnd, event=f"GP{rnd}", country="X", driver=c, driver_number="1", team=team_of[c],
                                 grid=float(gp), finish_pos=float(fin[c]), status="Retired" if dnf[c] else "Finished",
                                 points=float(max(0, 11 - fin[c])), dnf=int(dnf[c]), air_temp=25., track_temp=35., humidity=50., rain=0,
                                 rain_share=0., quali_pos=float(gp), quali_best_s=90 + gp * .05, quali_gap_pct=gp * .05 / 90 * 100, quali_missing=0))
    return pd.DataFrame(rows)


def test_prediction_is_generated_published_refreshed_and_preserved_on_failure(tmp_path, monkeypatch):
    import auto_update as A
    import weather
    from backtest import save_final_models
    from features import build_features

    raw = _synthetic_raw()
    raw.to_parquet(tmp_path / "results.parquet", index=False)
    save_final_models(build_features(raw), tmp_path / "models")
    (tmp_path / "models" / "sigma.json").write_text(json.dumps({"a": 1.85, "b": 0.10}))
    pd.DataFrame([dict(season=2026, round=7, event="United States Grand Prix", country="United States", location="Austin", session="Qualifying",
                       start_utc=EV.quali_start.tz_localize(None)),
                  dict(season=2026, round=7, event="United States Grand Prix", country="United States", location="Austin", session="Race",
                       start_utc=EV.race_start.tz_localize(None))]).to_parquet(tmp_path / "schedule.parquet", index=False)
    monkeypatch.setattr(A, "PROC", tmp_path)
    monkeypatch.setattr(weather, "event_forecast", lambda *a, **k: None)
    ev7 = Q.EventRef(2026, 7, EV.name, EV.location, EV.country, EV.quali_start, EV.race_start)
    monkeypatch.setattr(Q, "EventRef", lambda *a, **k: ev7)
    saved_bd = sys.modules.get("build_dataset")
    sys.modules["build_dataset"] = types.SimpleNamespace(main=lambda argv: None)
    saved_ff = install_fastf1(FakeSession(name=EV.name, rnd=7, hidden=SessionNotAvailableError("No data for this session!")))
    out_file, meta_file = tmp_path / "next_race.parquet", tmp_path / "next_race_meta.json"
    try:
        # (a) FastF1 down, OpenF1 has the classification but NOT the starting grid yet -> prediction from the classification
        web = Web()
        openf1_routes(web, grid=None)
        with_web(monkeypatch, web)
        msg = A._update(False)
        assert msg.startswith("prediction updated") and "openf1" in msg, msg
        pred = pd.read_parquet(out_file)
        meta = json.loads(meta_file.read_text())
        assert len(pred) == 20 and abs(pred["win_prob"].sum() - 1) < 1e-6 and set(pred["driver"]) == set(CODES)
        assert meta["round"] == 7 and meta["quali_source"] == "openf1" and meta["grid_source"] == Q.GRID_CLASSIFICATION
        assert pred.set_index("driver").loc["CCC", "grid"] == 3

        # (b) the official starting grid is published later, with a penalty -> stale prediction is replaced
        penalised = {c: i + 1 for i, c in enumerate(CODES)}
        penalised.update({"CCC": 8, "DDD": 3, "EEE": 4, "FFF": 5, "GGG": 6, "HHH": 7})
        web2 = Web()
        openf1_routes(web2, grid=penalised)
        with_web(monkeypatch, web2)
        msg = A._update(False)
        assert msg.startswith("prediction updated"), msg
        pred2, meta2 = pd.read_parquet(out_file), json.loads(meta_file.read_text())
        assert pred2.set_index("driver").loc["CCC", "grid"] == 8 and meta2["grid_source"] == Q.GRID_OFFICIAL
        assert meta2["grid_hash"] != meta["grid_hash"] and meta2["generated_at"] > meta["generated_at"]

        # (c) nothing changed -> no needless rebuild
        assert "up to date" in A._update(False)

        # (d) every source now fails -> the good prediction is preserved, and the message is an honest error
        before = out_file.read_bytes()
        meta_file.write_text(json.dumps({**meta2, "grid_source": Q.GRID_CLASSIFICATION}))   # force a re-check
        web3 = Web()
        web3.add("openf1", exc=requests.Timeout("slow"))
        web3.add("jolpi.ca", exc=requests.ConnectionError("down"))
        with_web(monkeypatch, web3)
        msg = A._update(False)
        assert "no source has returned valid results" in msg and "existing prediction" in msg and "not happened" not in msg
        assert out_file.read_bytes() == before
        assert A._EXTRA["state"] == "error" and len(A._EXTRA["attempts"]) == 3
    finally:
        restore_fastf1(saved_ff)
        if saved_bd is None:
            sys.modules.pop("build_dataset", None)
        else:
            sys.modules["build_dataset"] = saved_bd
