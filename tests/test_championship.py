import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import championship as C

CODES = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
TEAM = {"AAA": "Red Bull", "BBB": "Red Bull", "CCC": "Ferrari", "DDD": "Ferrari", "EEE": "Williams", "FFF": "Williams"}
# finishing order per round (first = winner). Round 4 is a sprint weekend. "!" = retired.
ORDERS = [["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"], ["AAA", "CCC", "BBB", "DDD", "EEE", "FFF"],
          ["BBB", "AAA", "CCC", "DDD", "EEE", "FFF"], ["AAA", "BBB", "DDD", "CCC", "EEE", "FFF"],
          ["AAA", "BBB", "CCC", "DDD", "FFF", "EEE"], ["BBB", "CCC", "DDD", "EEE", "FFF", "!AAA"],
          ["BBB", "CCC", "AAA", "DDD", "EEE", "FFF"], ["BBB", "AAA", "CCC", "DDD", "EEE", "FFF"]]
SPRINT_ROUND = 4


class Resp:
    def __init__(self, data, code=200):
        self._d, self.status_code = data, code

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeApi:
    """Serves Ergast-shaped JSON for a synthetic season, like Jolpica does."""
    def __init__(self, completed, season=2099, down=False):
        self.completed, self.season, self.down, self.now = completed, season, down, datetime.now(timezone.utc)

    def _points(self, upto):
        pts, wins = {c: 0.0 for c in CODES}, {c: 0 for c in CODES}
        for r in range(1, upto + 1):
            for i, x in enumerate(ORDERS[r - 1]):
                if x.startswith("!"):
                    continue
                pts[x] += C.RACE_POINTS[i] if i < 10 else 0
                wins[x] += i == 0
            if r == SPRINT_ROUND:
                for i, x in enumerate(ORDERS[r - 1][:8]):
                    pts[x.lstrip("!")] += C.SPRINT_POINTS[i]
        return pts, wins

    def standings(self, r):
        pts, wins = self._points(r)
        order = sorted(CODES, key=lambda c: (-pts[c], -wins[c]))
        ds = [{"position": str(i + 1), "points": str(pts[c]), "wins": str(wins[c]),
               "Driver": {"code": c, "givenName": c.title(), "familyName": "Driver", "url": f"http://en.wikipedia.org/wiki/{c}"},
               "Constructors": [{"name": TEAM[c]}]} for i, c in enumerate(order)]
        return {"MRData": {"StandingsTable": {"StandingsLists": [{"season": str(self.season), "round": str(r), "DriverStandings": ds}]}}}

    def get(self, url, params=None, timeout=None, headers=None):
        if self.down:
            import requests
            raise requests.ConnectionError("offline")
        if "wikipedia.org" in url:
            return Resp({"thumbnail": {"source": "https://upload.wikimedia.org/x.jpg"}})
        path = url.split("/ergast/f1/")[1]
        if re.fullmatch(rf"{self.season}\.json", path):
            races = []
            for r in range(1, 9):
                start = self.now + timedelta(days=14 * (r - self.completed) - 1)
                d = {"round": str(r), "raceName": f"GP {r}", "date": start.strftime("%Y-%m-%d"), "time": start.strftime("%H:%M:%SZ"),
                     "Circuit": {"circuitName": f"Circuit {r}", "Location": {"locality": "Town", "country": "Land"}}}
                if r == SPRINT_ROUND:
                    d["Sprint"] = {}
                races.append(d)
            return Resp({"MRData": {"RaceTable": {"Races": races}}})
        m = re.fullmatch(rf"{self.season}/(\d+)/driverStandings\.json", path)
        if m:
            r = int(m.group(1))
            return Resp({"MRData": self.standings(r)["MRData"] if r <= self.completed else {"StandingsTable": {"StandingsLists": []}}})
        if path == f"{self.season}/driverStandings.json":
            return Resp(self.standings(self.completed))
        m = re.fullmatch(rf"{self.season}/(\d+)/results\.json", path)
        if m:
            r = int(m.group(1))
            res = []
            for i, x in enumerate(ORDERS[r - 1]):
                code = x.lstrip("!")
                res.append({"position": str(i + 1), "status": "Engine" if x.startswith("!") else "Finished",
                            "Driver": {"code": code}, "Constructor": {"name": TEAM[code]}})
            return Resp({"MRData": {"RaceTable": {"Races": [{"Results": res}]}}})
        raise AssertionError("unexpected URL " + url)


def _patch(monkeypatch, api):
    monkeypatch.setattr(C.requests, "get", api.get)
    monkeypatch.setattr(C.time, "sleep", lambda s: None)


def test_standings_gaps_and_leader_match_the_official_source(tmp_path, monkeypatch):
    api = FakeApi(completed=5)
    _patch(monkeypatch, api)
    out = C.update_championship(season=2099, proc=tmp_path, now=api.now)
    assert out["updated"] and out["ok"]
    p = C.load_payload(tmp_path)
    pts, wins = api._points(5)
    rows = {r["code"]: r for r in p["standings"]}
    assert p["standings"][0]["code"] == max(pts, key=pts.get)             # leader = most official points
    for c in CODES:
        assert rows[c]["points"] == pts[c]
        assert rows[c]["gap_leader"] == pts[p["standings"][0]["code"]] - pts[c]
        assert rows[c]["wins"] == wins[c]
    assert p["remaining_rounds"] == 3 and p["remaining_sprints"] == 0      # sprint round (4) already run
    assert p["max_points_remaining"] == 75
    assert len(p["history"]) == 5                                         # a probability snapshot after every race
    assert rows["AAA"]["image"].startswith("https://upload.wikimedia.org")


def test_probabilities_sum_to_one_and_eliminated_drivers_get_zero(tmp_path, monkeypatch):
    api = FakeApi(completed=5)
    _patch(monkeypatch, api)
    C.update_championship(season=2099, proc=tmp_path, now=api.now)
    p = C.load_payload(tmp_path)
    assert abs(sum(r["prob"] for r in p["standings"]) - 1.0) < 1e-9
    for snap in p["history"]:
        assert abs(sum(snap["probs"].values()) - 1.0) < 1e-9
    for r in p["standings"]:
        if r["eliminated"]:
            assert r["prob"] == 0.0
    assert any(r["eliminated"] for r in p["standings"])                    # FFF is mathematically out
    assert p["standings"][0]["prob"] > 0.5                                 # clear leader is the favourite


def test_a_new_race_updates_leader_gaps_probabilities_and_trend(tmp_path, monkeypatch):
    api = FakeApi(completed=5)
    _patch(monkeypatch, api)
    C.update_championship(season=2099, proc=tmp_path, now=api.now)
    before = {r["code"]: r for r in C.load_payload(tmp_path)["standings"]}
    api.completed = 6                                                      # round 6 happens: BBB wins, AAA retires
    out = C.update_championship(season=2099, proc=tmp_path, now=api.now)
    assert out["updated"]
    after_p = C.load_payload(tmp_path)
    after = {r["code"]: r for r in after_p["standings"]}
    assert after_p["as_of_round"] == 6 and len(after_p["history"]) == 6
    assert after["BBB"]["points"] == api._points(6)[0]["BBB"]
    assert after["BBB"]["prob"] > before["BBB"]["prob"]                    # winner's chances rise
    assert after["AAA"]["prob"] < before["AAA"]["prob"]                    # retirement hurts the leader
    assert after["BBB"]["trend"] == "up" and after["AAA"]["trend"] == "down"
    assert abs(after["BBB"]["prob_change"] - (after["BBB"]["prob"] - before["BBB"]["prob"])) < 0.02


def test_no_fake_update_when_source_is_down_or_race_not_published(tmp_path, monkeypatch):
    api = FakeApi(completed=5)
    _patch(monkeypatch, api)
    C.update_championship(season=2099, proc=tmp_path, now=api.now)
    saved = (tmp_path / "championship.json").read_text()
    api.down = True
    out = C.update_championship(season=2099, proc=tmp_path, now=api.now, force=True)
    assert out["ok"] is False and out["updated"] is False and "last saved" in out["message"]
    assert (tmp_path / "championship.json").read_text() == saved           # nothing overwritten, nothing invented
    # a race has been run (date passed) but the API still shows round 5 -> flagged as pending, not silently "updated"
    api.down = False
    later = api.now + timedelta(days=15)                                   # round 6's date is now in the past
    out = C.update_championship(season=2099, proc=tmp_path, now=later, force=True)
    p = C.load_payload(tmp_path)
    assert p["as_of_round"] == 5 and p["pending_race"]["round"] == 6
    assert "not published yet" in out["message"]


def test_simulation_behaves_sensibly():
    drv = lambda a, b: [{"code": "X", "team": "t1", "points": a, "wins": 0}, {"code": "Y", "team": "t2", "points": b, "wins": 0}]
    hist = {"X": [(r, 5, False) for r in range(1, 6)], "Y": [(r, 5, False) for r in range(1, 6)]}
    rem = lambda k: [{"sprint": False}] * k
    even = C.title_probabilities(drv(100, 100), hist, rem(6), 5, n=20000, seed=1)
    assert abs(even["X"] - 0.5) < 0.04 and abs(sum(even.values()) - 1) < 1e-9
    lead10 = C.title_probabilities(drv(110, 100), hist, rem(6), 5, n=20000, seed=1)["X"]
    lead60 = C.title_probabilities(drv(160, 100), hist, rem(6), 5, n=20000, seed=1)["X"]
    assert 0.5 < lead10 < lead60                                           # bigger gap -> bigger chance
    short = C.title_probabilities(drv(160, 100), hist, rem(2), 5, n=20000, seed=1)["X"]
    assert short > lead60                                                  # fewer races left -> leader safer
    over = C.title_probabilities(drv(300, 100), hist, [], 5)
    assert over["X"] == 1.0                                                # season finished
