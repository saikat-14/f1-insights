
"""
F1-InSights — Drivers' Championship Tracker

Data:
    Official championship standings, race results and schedule from Jolpica-F1.

Model:
    Monte Carlo simulation of the remaining races.
    Title probabilities are estimates, not official F1 statistics.

Updates:
    Recalculates the championship when new official standings become available.
    Uses cached data when the API is unavailable.

Run from the project root:

    python src/championship.py
    python src/championship.py --force
    python src/championship.py --season 2026
    python src/championship.py --season 2026 --force
"""

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests


# ============================================================
# Configuration
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
STANDINGS_DIR = PROC / "standings"

API = "https://api.jolpi.ca/ergast/f1"
USER_AGENT = "F1-InSights/1.0"

RACE_POINTS = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]
SPRINT_POINTS = [8, 7, 6, 5, 4, 3, 2, 1]

N_SIMS = 20_000
RESULT_DELAY = timedelta(hours=3)
SCHEDULE_CACHE_HOURS = 24
UPDATE_RETRY_MINUTES = 20

METHOD = (
    "Monte Carlo simulation of 20,000 possible remaining seasons. "
    "Driver pace is estimated from historical race results, with "
    "recent results weighted more heavily and early-season estimates "
    "shrunk toward the field average. Simulations include persistent "
    "driver and team form, race-to-race pace variation and estimated "
    "retirement risk. Grand Prix and sprint points are simulated "
    "separately. Championship probabilities are model estimates, "
    "not official Formula 1 statistics."
)


class ApiError(Exception):
    """Raised when official data cannot be retrieved or parsed."""


# ============================================================
# HTTP and JSON cache
# ============================================================

def _get(path, params=None, retries=3):
    """Fetch and validate a response from the Jolpica-F1 API."""
    last_error = "unknown API error"

    for attempt in range(retries):
        try:
            response = requests.get(
                f"{API}/{path.lstrip('/')}",
                params=params or {"limit": 100},
                timeout=20,
                headers={"User-Agent": USER_AGENT},
            )

            if response.status_code == 429:
                last_error = "rate limited (HTTP 429)"
                time.sleep(2 * (attempt + 1))
                continue

            response.raise_for_status()
            data = response.json()

            if not isinstance(data, dict):
                raise ApiError("invalid API response format")

            mrdata = data.get("MRData")

            if not isinstance(mrdata, dict):
                raise ApiError("API response is missing MRData")

            return mrdata

        except ApiError:
            raise

        except requests.RequestException as exc:
            last_error = (
                f"network error: {type(exc).__name__}"
            )
            time.sleep(1)

        except (ValueError, TypeError) as exc:
            last_error = f"invalid JSON response: {exc}"
            time.sleep(1)

    raise ApiError(last_error)


def _age_h(path):
    """Return the age of a file in hours."""
    try:
        return max(0.0, (time.time() - path.stat().st_mtime) / 3600)
    except OSError:
        return float("inf")


def _write_json(path, obj):
    """Atomically write JSON so interrupted writes do not corrupt the cache."""
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.with_name(path.name + ".tmp")

    try:
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(obj, file, indent=2, ensure_ascii=False)

        os.replace(temp_path, path)

    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _read_json(path, default=None):
    """Read JSON safely. Return default if the file is absent or invalid."""
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return default


# ============================================================
# Parsing helpers
# ============================================================

def _safe_int(value, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=0.0):
    try:
        result = float(value)
        return result if np.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _valid_position(value):
    """Return a positive finishing position, or None."""
    position = _safe_int(value, 0)
    return position if position > 0 else None


def _parse_utc(date_string, time_string="12:00:00Z"):
    """Parse an API date and time into a UTC-aware datetime."""
    raw = f"{date_string}T{time_string}"

    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(raw)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except ValueError as exc:
        raise ApiError(f"invalid race date/time: {raw}") from exc


def _parse_standings(mrdata):
    """Convert an official API standings response into a stable structure."""
    table = mrdata.get("StandingsTable") or {}
    lists = table.get("StandingsLists") or []

    if not lists:
        return None

    standings = lists[0]
    drivers = []

    for index, item in enumerate(
        standings.get("DriverStandings") or [],
        start=1,
    ):
        driver = item.get("Driver") or {}
        constructors = item.get("Constructors") or []

        position = _safe_int(item.get("position"), 0)

        if position <= 0:
            position = _safe_int(item.get("positionText"), 0)

        if position <= 0:
            position = index

        driver_id = str(driver.get("driverId") or "?")
        code = str(
            driver.get("code") or driver_id[:3].upper()
        )

        name = (
            f"{driver.get('givenName', '')} "
            f"{driver.get('familyName', '')}"
        ).strip()

        team = (
            constructors[-1].get("name", "")
            if constructors
            else ""
        )

        drivers.append({
            "pos": position,
            "code": code,
            "name": name or code,
            "team": team,
            "points": _safe_float(item.get("points")),
            "wins": _safe_int(item.get("wins")),
            "url": driver.get("url"),
            "number": driver.get("permanentNumber"),
        })

    if not drivers:
        return None

    drivers.sort(key=lambda d: (d["pos"], -d["points"]))

    return {
        "round": _safe_int(standings.get("round")),
        "drivers": drivers,
    }


def _is_dnf(status, position=None):
    """
    Classify a race result as a retirement/non-finishing result.

    Classified finishers may have statuses such as:
        Finished
        +1 Lap
        +2 Laps
        Lapped

    Disqualifications and retirements are treated as non-finishes
    for the purpose of this simplified predictive model.
    """
    status = str(status or "").strip()

    if status == "Finished":
        return False

    if status.startswith("+"):
        return False

    if status.lower() == "lapped":
        return False

    return True


def _parse_results(mrdata):
    """Parse official Grand Prix results."""
    races = (mrdata.get("RaceTable") or {}).get("Races") or []

    if not races:
        return None

    results = []

    for result in races[0].get("Results") or []:
        driver = result.get("Driver") or {}
        constructor = result.get("Constructor") or {}

        driver_id = str(driver.get("driverId") or "?")
        code = str(
            driver.get("code") or driver_id[:3].upper()
        )

        status = str(result.get("status") or "")
        position = _valid_position(result.get("position"))

        results.append({
            "code": code,
            "pos": position,
            "dnf": _is_dnf(status, position),
            "status": status,
            "team": constructor.get("name", ""),
        })

    return results


# ============================================================
# Schedule
# ============================================================

def season_schedule(season, proc=None, force=False):
    """Load the season schedule, using a recent cache when possible."""
    proc = proc or PROC
    directory = proc / "standings"
    directory.mkdir(parents=True, exist_ok=True)

    cache_file = directory / f"schedule_{season}.json"

    if (
        cache_file.exists()
        and not force
        and _age_h(cache_file) < SCHEDULE_CACHE_HOURS
    ):
        cached = _read_json(cache_file)

        if isinstance(cached, list):
            return cached

    try:
        data = _get(
            f"{season}.json",
            {"limit": 100},
        )

    except ApiError:
        cached = _read_json(cache_file)

        if isinstance(cached, list):
            return cached

        raise

    races = (
        (data.get("RaceTable") or {}).get("Races") or []
    )

    schedule = []

    for race in races:
        try:
            round_number = int(race["round"])
            date_string = race["date"]
        except (KeyError, TypeError, ValueError):
            continue

        race_time = race.get("time", "12:00:00Z")
        start = _parse_utc(date_string, race_time)

        circuit = race.get("Circuit") or {}
        location = circuit.get("Location") or {}

        schedule.append({
            "round": round_number,
            "name": race.get("raceName", f"Round {round_number}"),
            "start_utc": start.isoformat().replace("+00:00", "Z"),
            "sprint": "Sprint" in race,
            "circuit": circuit.get("circuitName", ""),
            "locality": location.get("locality", ""),
            "country": location.get("country", ""),
        })

    schedule.sort(key=lambda race: race["round"])

    _write_json(cache_file, schedule)

    return schedule


# ============================================================
# Official standings and race results
# ============================================================

def fetch_standings(season, rnd, proc=None, force=False):
    """Fetch round-specific official driver standings."""
    directory = (proc or PROC) / "standings"
    directory.mkdir(parents=True, exist_ok=True)

    cache_file = directory / f"standings_{season}_{rnd:02d}.json"

    if cache_file.exists() and not force:
        cached = _read_json(cache_file)

        if isinstance(cached, dict) and cached.get("drivers"):
            return cached

    data = _get(
        f"{season}/{rnd}/driverStandings.json",
        {"limit": 100},
    )

    standings = _parse_standings(data)

    if standings:
        _write_json(cache_file, standings)

    return standings


def fetch_results(season, rnd, proc=None, force=False):
    """Fetch round-specific Grand Prix results."""
    directory = (proc or PROC) / "standings"
    directory.mkdir(parents=True, exist_ok=True)

    cache_file = directory / f"results_{season}_{rnd:02d}.json"

    if cache_file.exists() and not force:
        cached = _read_json(cache_file)

        if isinstance(cached, list):
            return cached

    data = _get(
        f"{season}/{rnd}/results.json",
        {"limit": 100},
    )

    results = _parse_results(data)

    if results is not None:
        _write_json(cache_file, results)

    return results


def latest_standings(season):
    """Get the latest official championship standings."""
    data = _get(
        f"{season}/driverStandings.json",
        {"limit": 100},
    )

    standings = _parse_standings(data)

    if not standings:
        return 0, None

    return standings["round"], standings


# ============================================================
# Statistical model
# ============================================================

def team_index(teams):
    """Convert team names into integer indices."""
    unique_teams = list(dict.fromkeys(teams))
    lookup = {
        team: index
        for index, team in enumerate(unique_teams)
    }

    indices = np.array(
        [lookup[team] for team in teams],
        dtype=int,
    )

    return indices, len(unique_teams)


def driver_strengths(codes, history, now_round, k=1.5, decay=0.9):
    """
    Estimate expected finishing position and retirement probability.

    Recent results receive more weight.
    Early-season estimates are shrunk toward the field average.
    """
    all_positions = [
        position
        for code in codes
        for _round, position, dnf in history.get(code, [])
        if position is not None and position > 0 and not dnf
    ]

    field_average = (
        float(np.mean(all_positions))
        if all_positions
        else 10.5
    )

    means = []
    retirement_probabilities = []

    for code in codes:
        records = history.get(code, [])

        valid_records = [
            (round_number, position, dnf)
            for round_number, position, dnf in records
            if position is not None and position > 0 and not dnf
        ]

        if valid_records:
            weights = np.array([
                decay ** max(0, now_round - round_number)
                for round_number, _position, _dnf in valid_records
            ])

            positions = np.array([
                position
                for _round_number, position, _dnf in valid_records
            ], dtype=float)

            expected_position = (
                np.dot(weights, positions) + k * field_average
            ) / (weights.sum() + k)

        else:
            expected_position = field_average

        means.append(float(expected_position))

        starts = len(records)
        retirements = sum(
            1 for _round_number, _position, dnf in records if dnf
        )

        # A small prior prevents extreme estimates from tiny samples.
        probability = (
            retirements + 5 * 0.10
        ) / (starts + 5)

        retirement_probabilities.append(
            float(np.clip(probability, 0.02, 0.35))
        )

    return (
        np.asarray(means, dtype=float),
        np.asarray(retirement_probabilities, dtype=float),
    )


def title_probabilities(
    drivers,
    hist,
    remaining,
    now_round,
    sigma=(1.85, 0.10),
    n=N_SIMS,
    seed=0,
):
    """
    Simulate the remaining season and estimate each driver's
    championship-winning probability.

    drivers:
        List containing code, team, points and wins.

    hist:
        {code: [(round, finishing_position, dnf), ...]}

    remaining:
        [{"sprint": True}, {"sprint": False}, ...]

    Returns:
        {driver_code: probability}

    Probabilities sum to 1 when at least one driver exists.
    """
    if not drivers:
        return {}

    n = max(1, int(n))

    codes = [driver["code"] for driver in drivers]
    driver_count = len(codes)

    points_now = np.array(
        [driver["points"] for driver in drivers],
        dtype=float,
    )

    wins_now = np.array(
        [driver["wins"] for driver in drivers],
        dtype=int,
    )

    if not remaining:
        leader = int(
            np.lexsort((-wins_now, -points_now))[0]
        )

        return {
            code: float(index == leader)
            for index, code in enumerate(codes)
        }

    rng = np.random.default_rng(seed)

    mean, retirement_probability = driver_strengths(
        codes,
        hist,
        now_round,
    )

    sigma_a, sigma_b = sigma

    pace_noise = np.clip(
        sigma_a + sigma_b * mean,
        0.8,
        6.0,
    )

    team_indices, team_count = team_index([
        driver.get("team") or driver["code"]
        for driver in drivers
    ])

    # Score arrays are indexed by finishing position.
    max_positions = max(driver_count, len(RACE_POINTS))

    race_points = np.zeros(max_positions, dtype=float)
    race_points[:len(RACE_POINTS)] = RACE_POINTS

    sprint_points = np.zeros(max_positions, dtype=float)
    sprint_points[:len(SPRINT_POINTS)] = SPRINT_POINTS

    totals = np.tile(points_now, (n, 1))
    wins = np.tile(wins_now, (n, 1))

    rows = np.arange(n)[:, None]

    # Unknown season-long changes: driver form and team performance.
    persistent_form = (
        0.9 * rng.normal(size=(n, driver_count))
        + 1.0 * rng.normal(size=(n, team_count))[:, team_indices]
    )

    for race in remaining:
        sessions = (
            ("sprint", "race")
            if race.get("sprint", False)
            else ("race",)
        )

        for session in sessions:
            is_sprint = session == "sprint"

            scores = (
                mean[None, :]
                + persistent_form
                + pace_noise[None, :]
                * rng.normal(size=(n, driver_count))
                + 1.0
                * rng.normal(size=(n, team_count))[:, team_indices]
            )

            retirement_rate = retirement_probability.copy()

            if is_sprint:
                retirement_rate *= 0.5

            retired = (
                rng.random((n, driver_count))
                < retirement_rate[None, :]
            )

            # Retired drivers finish behind classified finishers
            # in this simplified ordering model.
            scores = scores + 1000.0 * retired

            order = np.argsort(scores, axis=1)

            rank = np.empty_like(order)
            rank[rows, order] = np.arange(driver_count)[None, :]

            scoring = sprint_points if is_sprint else race_points

            awarded_points = scoring[rank]
            totals += np.where(retired, 0.0, awarded_points)

            if not is_sprint:
                wins += (
                    (rank == 0) & ~retired
                ).astype(int)

    # First tie-breaker: points. Second: number of wins.
    # Exact remaining ties are split randomly because the model
    # does not simulate every official countback tie-breaker.
    tied_noise = rng.random((n, driver_count)) * 1e-8

    final_key = totals + 1e-3 * wins + tied_noise

    champions = np.argmax(final_key, axis=1)

    counts = np.bincount(
        champions,
        minlength=driver_count,
    )

    probabilities = counts / n

    return {
        code: float(probability)
        for code, probability in zip(codes, probabilities)
    }


# ============================================================
# Build round history
# ============================================================

def _state(rounds, rnd):
    """Return standings and driver result history through a round."""
    standings = rounds[rnd]["standings"]
    history = {}

    for round_number in range(1, rnd + 1):
        round_data = rounds.get(round_number) or {}

        for result in round_data.get("results") or []:
            history.setdefault(result["code"], []).append((
                round_number,
                result.get("pos"),
                result.get("dnf", False),
            ))

    return standings, history


# ============================================================
# Build dashboard payload
# ============================================================

def build_payload(
    season,
    sched,
    rounds,
    latest,
    sigma=(1.85, 0.10),
    prev_history=None,
    n=N_SIMS,
    now=None,
    images=None,
    source="Jolpica-F1 API",
    data_status="official",
):
    """
    Convert official data and simulation output into the JSON
    structure consumed by the F1-InSights dashboard.
    """
    now = now or datetime.now(timezone.utc)

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    now = now.astimezone(timezone.utc)

    schedule_by_round = {
        race["round"]: race for race in sched
    }

    total_rounds = len(sched)

    cached_history = {
        item["round"]: item
        for item in (prev_history or [])
    }

    history = []

    for rnd in range(1, latest + 1):
        if rnd not in rounds:
            continue

        # Preserve prior estimates for old rounds to avoid
        # recomputing the entire season after every race.
        if rnd in cached_history and rnd != latest:
            history.append(cached_history[rnd])
            continue

        standings, result_history = _state(rounds, rnd)

        remaining = [
            {
                "sprint": schedule_by_round.get(
                    future_round, {}
                ).get("sprint", False)
            }
            for future_round in range(rnd + 1, total_rounds + 1)
        ]

        probabilities = title_probabilities(
            standings["drivers"],
            result_history,
            remaining,
            rnd,
            sigma=sigma,
            n=n,
            seed=season * 100 + rnd,
        )

        history.append({
            "round": rnd,
            "event": schedule_by_round.get(
                rnd, {}
            ).get("name", f"Round {rnd}"),
            "probs": probabilities,
            "points": {
                driver["code"]: driver["points"]
                for driver in standings["drivers"]
            },
        })

    if latest not in rounds:
        raise ValueError(
            f"Official standings for round {latest} are missing."
        )

    current_drivers = sorted(
        rounds[latest]["standings"]["drivers"],
        key=lambda driver: (
            -driver["points"],
            -driver["wins"],
            driver["pos"],
        ),
    )

    _, current_history = _state(rounds, latest)

    current_probabilities = (
        history[-1]["probs"] if history else {}
    )

    previous_probabilities = (
        history[-2]["probs"] if len(history) >= 2 else {}
    )

    remaining_rounds = list(
        range(latest + 1, total_rounds + 1)
    )

    remaining_sprints = sum(
        1
        for rnd in remaining_rounds
        if schedule_by_round.get(rnd, {}).get("sprint", False)
    )

    max_remaining_points = (
        25 * len(remaining_rounds)
        + 8 * remaining_sprints
    )

    leader_points = (
        current_drivers[0]["points"]
        if current_drivers
        else 0.0
    )

    podium_counts = {}

    for rnd in range(1, latest + 1):
        for result in (
            rounds.get(rnd, {}).get("results") or []
        ):
            position = result.get("pos")

            if position is not None and 1 <= position <= 3:
                code = result["code"]
                podium_counts[code] = (
                    podium_counts.get(code, 0) + 1
                )

    cumulative_points = {
        rnd: {
            driver["code"]: driver["points"]
            for driver in round_data["standings"]["drivers"]
        }
        for rnd, round_data in rounds.items()
        if round_data.get("standings")
    }

    rows = []

    for index, driver in enumerate(current_drivers):
        code = driver["code"]

        recent_form = [
            {
                "round": rnd,
                "pos": position,
                "dnf": retired,
            }
            for rnd, position, retired in sorted(
                current_history.get(code, [])
            )[-5:]
        ]

        current_probability = current_probabilities.get(
            code, 0.0
        )

        previous_probability = previous_probabilities.get(code)

        probability_change = (
            current_probability - previous_probability
            if previous_probability is not None
            else None
        )

        previous_round = max(0, latest - 3)

        points_latest = cumulative_points.get(
            latest, {}
        ).get(code, 0.0)

        points_previous = cumulative_points.get(
            previous_round, {}
        ).get(code, 0.0)

        points_last_three = points_latest - points_previous

        gap_ahead = (
            current_drivers[index - 1]["points"]
            - driver["points"]
            if index > 0
            else 0.0
        )

        rows.append({
            **{
                key: driver.get(key)
                for key in (
                    "code",
                    "name",
                    "team",
                    "points",
                    "wins",
                    "number",
                )
            },
            "pos": index + 1,
            "podiums": podium_counts.get(code, 0),
            "gap_leader": leader_points - driver["points"],
            "gap_ahead": gap_ahead,
            "max_possible": (
                driver["points"] + max_remaining_points
            ),
            "eliminated": (
                driver["points"] + max_remaining_points
                < leader_points
            ),
            "prob": current_probability,
            "prev_prob": previous_probability,
            "prob_change": probability_change,
            "trend": (
                "flat"
                if probability_change is None
                or abs(probability_change) < 0.005
                else (
                    "up"
                    if probability_change > 0
                    else "down"
                )
            ),
            "form": recent_form,
            "points_last3": points_last_three,
            "image": (images or {}).get(code),
        })

    pending_race = None

    due_races = []

    for race in sched:
        if race["round"] <= latest:
            continue

        start = datetime.fromisoformat(
            race["start_utc"].replace("Z", "+00:00")
        )

        if start + RESULT_DELAY < now:
            due_races.append(race)

    if due_races:
        first_due = min(
            due_races,
            key=lambda race: race["round"],
        )

        pending_race = {
            "round": first_due["round"],
            "name": first_due["name"],
        }

    clinched = False

    if len(current_drivers) > 1:
        leader = current_drivers[0]
        runner_up = current_drivers[1]

        clinched = (
            leader["points"]
            > runner_up["points"] + max_remaining_points
        )

    return {
        "clinched": clinched,
        "season": season,
        "as_of_round": latest,
        "as_of_event": schedule_by_round.get(
            latest, {}
        ).get("name", f"Round {latest}"),
        "total_rounds": total_rounds,
        "remaining_rounds": len(remaining_rounds),
        "remaining_sprints": remaining_sprints,
        "max_points_remaining": max_remaining_points,
        "generated_at": now.isoformat(),
        "source": source,
        "data_status": data_status,
        "pending_race": pending_race,
        "n_sims": n,
        "method": METHOD,
        "standings": rows,
        "history": history,
    }


def contenders(payload, max_n=8):
    """
    Return mathematically eligible drivers with at least a 0.1%
    estimated title chance, always including the current leader.
    """
    standings = payload.get("standings", [])

    eligible = [
        driver
        for driver in standings
        if not driver.get("eliminated", False)
        and (
            driver.get("pos") == 1
            or driver.get("prob", 0.0) >= 0.001
        )
    ]

    eligible.sort(
        key=lambda driver: (
            -driver.get("prob", 0.0),
            driver.get("pos", 999),
        )
    )

    return eligible[:max(1, max_n)]


# ============================================================
# Driver images
# ============================================================

def driver_images(rows, proc=None, limit=12):
    """
    Retrieve driver thumbnails from Wikipedia.

    Failures are cached as None so the dashboard can display initials.
    Delete data/processed/driver_images.json to retry failed lookups.
    """
    proc = proc or PROC
    proc.mkdir(parents=True, exist_ok=True)

    cache_file = proc / "driver_images.json"
    cache = _read_json(cache_file, {})

    if not isinstance(cache, dict):
        cache = {}

    changed = False

    for driver in rows[:limit]:
        code = driver.get("code")
        url = driver.get("url")

        if not code or code in cache or not url:
            continue

        title = url.rstrip("/").split("/")[-1]

        try:
            response = requests.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}",
                timeout=10,
                headers={"User-Agent": USER_AGENT},
            )

            response.raise_for_status()
            data = response.json()

            cache[code] = (
                (data.get("thumbnail") or {}).get("source")
            )

        except (
            requests.RequestException,
            ValueError,
            TypeError,
        ):
            cache[code] = None

        changed = True

    if changed:
        _write_json(cache_file, cache)

    return cache


# ============================================================
# Dashboard payload storage
# ============================================================

def load_payload(proc=None):
    """Load the most recently saved championship payload."""
    path = (proc or PROC) / "championship.json"
    payload = _read_json(path)

    if not isinstance(payload, dict):
        return None

    if not isinstance(payload.get("standings"), list):
        return None

    return payload


def _sigma(proc):
    """Load model noise parameters, falling back to defaults."""
    path = proc / "models" / "sigma.json"
    data = _read_json(path, {})

    try:
        a = float(data["a"])
        b = float(data["b"])

        if not np.isfinite(a) or not np.isfinite(b):
            raise ValueError("non-finite model parameters")

        return a, b

    except (KeyError, TypeError, ValueError):
        return 1.85, 0.10


# ============================================================
# Main update operation
# ============================================================

def update_championship(
    season=None,
    force=False,
    proc=None,
    now=None,
):
    """
    Fetch official data, recompute title probabilities and save.

    Returns:
        {
            "ok": bool,
            "updated": bool,
            "message": str
        }

    If the API fails, the last saved payload is preserved.
    """
    proc = proc or PROC
    proc.mkdir(parents=True, exist_ok=True)

    now = now or datetime.now(timezone.utc)

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    now = now.astimezone(timezone.utc)

    season = int(season or now.year)

    previous_payload = load_payload(proc)

    try:
        schedule = season_schedule(
            season,
            proc=proc,
            force=force,
        )

        latest_round, latest_standings_data = latest_standings(
            season
        )

        if not latest_standings_data:
            return {
                "ok": True,
                "updated": False,
                "message": (
                    f"The {season} season has no official "
                    "driver standings available yet."
                ),
            }

        # A pending race must be checked again even if the API's
        # official standings round has not advanced.
        if (
            previous_payload
            and not force
            and previous_payload.get("season") == season
            and previous_payload.get("as_of_round") == latest_round
            and previous_payload.get("data_status") == "official"
            and not previous_payload.get("pending_race")
        ):
            return {
                "ok": True,
                "updated": False,
                "message": (
                    f"Already up to date after round {latest_round}."
                ),
            }

        directory = proc / "standings"
        directory.mkdir(parents=True, exist_ok=True)

        # Always refresh the latest official standings.
        _write_json(
            directory
            / f"standings_{season}_{latest_round:02d}.json",
            latest_standings_data,
        )

        rounds = {}
        missing_rounds = []

        for rnd in range(1, latest_round + 1):
            try:
                standings = fetch_standings(
                    season,
                    rnd,
                    proc=proc,
                    force=force,
                )

                results = fetch_results(
                    season,
                    rnd,
                    proc=proc,
                    force=force,
                )

                if standings:
                    rounds[rnd] = {
                        "standings": standings,
                        "results": results or [],
                    }
                else:
                    missing_rounds.append(rnd)

                # Avoid sending requests too rapidly.
                time.sleep(0.25)

            except ApiError:
                missing_rounds.append(rnd)

                # Continue using cached rounds where possible.
                cached_standings = _read_json(
                    directory
                    / f"standings_{season}_{rnd:02d}.json"
                )

                cached_results = _read_json(
                    directory
                    / f"results_{season}_{rnd:02d}.json",
                    [],
                )

                if (
                    isinstance(cached_standings, dict)
                    and cached_standings.get("drivers")
                ):
                    rounds[rnd] = {
                        "standings": cached_standings,
                        "results": (
                            cached_results
                            if isinstance(cached_results, list)
                            else []
                        ),
                    }

                # Stop making API requests after an error.
                break

        # Official current standings take precedence over historical
        # cached data when the latest round could not be fetched.
        if latest_round not in rounds:
            rounds[latest_round] = {
                "standings": latest_standings_data,
                "results": [],
            }

        sigma = _sigma(proc)

        images = driver_images(
            latest_standings_data["drivers"],
            proc=proc,
        )

        previous_history = None

        if (
            previous_payload
            and previous_payload.get("season") == season
            and not force
        ):
            previous_history = previous_payload.get("history", [])

        payload = build_payload(
            season=season,
            sched=schedule,
            rounds=rounds,
            latest=latest_round,
            sigma=sigma,
            prev_history=previous_history,
            n=N_SIMS,
            now=now,
            images=images,
        )

        if missing_rounds:
            payload["incomplete_rounds"] = sorted(
                set(missing_rounds)
            )
            payload["historical_data_complete"] = False
        else:
            payload["historical_data_complete"] = True

        output_path = proc / "championship.json"
        _write_json(output_path, payload)

        message = (
            f"Championship updated after round {latest_round} "
            f"({payload['as_of_event']})."
        )

        if missing_rounds:
            message += (
                f" Warning: historical data is incomplete for "
                f"{len(set(missing_rounds))} round(s); "
                "some model estimates may be less reliable."
            )

        if payload.get("pending_race"):
            pending = payload["pending_race"]

            message += (
                f" Round {pending['round']} ({pending['name']}) "
                "is past its scheduled start, but official standings "
                "have not advanced to that round."
            )

        return {
            "ok": True,
            "updated": True,
            "message": message,
        }

    except (ApiError, OSError, ValueError, KeyError) as exc:
        message = f"Championship update failed: {exc}."

        if previous_payload:
            message += " The last saved championship payload was preserved."
        else:
            message += " No previous championship payload is available."

        return {
            "ok": False,
            "updated": False,
            "message": message,
        }


# ============================================================
# Automatic update check
# ============================================================

def update_if_due(proc=None, now=None, force=False):
    """
    Lightweight check for use by the application's background updater.

    The API is queried for a full update only when:
      - no saved payload exists;
      - force=True;
      - a scheduled race should have published results; or
      - a new calendar year requires a season refresh.
    """
    proc = proc or PROC
    now = now or datetime.now(timezone.utc)

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    now = now.astimezone(timezone.utc)

    previous_payload = load_payload(proc)

    if force or previous_payload is None:
        return update_championship(
            proc=proc,
            now=now,
            force=force,
        )

    payload_file = proc / "championship.json"

    try:
        previous_season = int(previous_payload["season"])

        schedule = season_schedule(
            previous_season,
            proc=proc,
        )

    except (
        ApiError,
        KeyError,
        TypeError,
        ValueError,
    ):
        return {
            "ok": False,
            "updated": False,
            "message": (
                "Official schedule unavailable. "
                "Showing the last saved championship data."
            ),
        }

    latest_round = int(
        previous_payload.get("as_of_round", 0)
    )

    due_rounds = [
        race
        for race in schedule
        if race["round"] > latest_round
        and datetime.fromisoformat(
            race["start_utc"].replace("Z", "+00:00")
        ) + RESULT_DELAY < now
    ]

    age_minutes = _age_h(payload_file) * 60

    if due_rounds and age_minutes >= UPDATE_RETRY_MINUTES:
        return update_championship(
            season=previous_season,
            proc=proc,
            now=now,
        )

    if now.year > previous_season and _age_h(payload_file) > 24:
        return update_championship(
            season=now.year,
            proc=proc,
            now=now,
        )

    return {
        "ok": True,
        "updated": False,
        "message": "No new race is due for processing.",
    }


# ============================================================
# Command-line interface
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Update the F1-InSights drivers' championship."
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Refresh the schedule and historical cached API data.",
    )

    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="Season year, for example 2026.",
    )

    args = parser.parse_args()

    result = update_championship(
        season=args.season,
        force=args.force,
    )

    print(result["message"])

    if not result["ok"]:
        raise SystemExit(1)
