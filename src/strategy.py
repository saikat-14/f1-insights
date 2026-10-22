"""
Day 3: tyre-strategy simulator.

lap_time = base_pace + compound_offset + degradation*tyre_age + cliff_penalty + fuel_effect*laps_remaining
Pit stops cost `pit_loss` seconds (much less under a Safety Car). Monte Carlo over random Safety Cars.

NOTE: the compound numbers below are generic starting values, NOT yet fitted to real stint data.
Fitting them per circuit from FastF1 laps is the natural next upgrade.
"""
import heapq
from dataclasses import dataclass, field
from itertools import product

import numpy as np
import pandas as pd

COMPOUNDS = ("SOFT", "MEDIUM", "HARD")

DEFAULTS = {
    "SOFT":   {"offset": 0.00, "deg": 0.090, "life": 16, "cliff": 0.30},
    "MEDIUM": {"offset": 0.45, "deg": 0.055, "life": 26, "cliff": 0.25},
    "HARD":   {"offset": 0.85, "deg": 0.035, "life": 38, "cliff": 0.20},
}


@dataclass
class Race:
    laps: int = 57
    base_pace: float = 96.0
    pit_loss: float = 22.0
    fuel_effect: float = 0.03       # seconds per lap of fuel still on board
    sc_prob: float = 0.45           # chance of at least one Safety Car in the race
    sc_len: int = 4                 # laps under Safety Car
    sc_pit_discount: float = 0.45   # share of pit loss paid when stopping under SC
    tyres: dict = field(default_factory=lambda: {k: dict(v) for k, v in DEFAULTS.items()})


def stint_time(race: Race, compound: str, first_lap: int, length: int) -> float:
    t = race.tyres[compound]
    laps = np.arange(first_lap, first_lap + length)
    age = np.arange(1, length + 1)
    over = np.maximum(0, age - t["life"])
    lap_t = (race.base_pace + t["offset"] + t["deg"] * age + t["cliff"] * over
             + race.fuel_effect * (race.laps - laps))
    return float(lap_t.sum())


def pit_cost(race: Race, lap: int, sc_lap):
    if sc_lap is not None and sc_lap <= lap < sc_lap + race.sc_len:
        return race.pit_loss * race.sc_pit_discount
    return race.pit_loss


def adapt_for_sc(race: Race, pits, sc_lap, min_age=10, max_pull=12):
    """Teams pit under the Safety Car if the planned stop is near and tyres are old enough."""
    pits = list(pits)
    if sc_lap is None:
        return pits
    target = sc_lap + 1
    for k, p in enumerate(pits):
        if p < sc_lap:
            continue
        prev = pits[k - 1] if k else 0
        inside = sc_lap <= p < sc_lap + race.sc_len
        nxt_ok = k == len(pits) - 1 or pits[k + 1] - target >= 6
        if not inside and target - prev >= min_age and p - target <= max_pull and nxt_ok:
            pits[k] = target
        break
    return pits


def total_time(race: Race, comps, pits, sc_lap=None) -> float:
    pits = adapt_for_sc(race, pits, sc_lap)
    bounds = [0] + list(pits) + [race.laps]
    t = sum(stint_time(race, c, bounds[i] + 1, bounds[i + 1] - bounds[i]) for i, c in enumerate(comps))
    return t + sum(pit_cost(race, p, sc_lap) for p in pits)


def lap_times(race: Race, comps, pits) -> np.ndarray:
    """Lap-by-lap times (no Safety Car) for plotting; pit loss is added to the in-lap."""
    bounds = [0] + list(pits) + [race.laps]
    out = []
    for i, c in enumerate(comps):
        t = race.tyres[c]
        n = bounds[i + 1] - bounds[i]
        laps = np.arange(bounds[i] + 1, bounds[i + 1] + 1)
        age = np.arange(1, n + 1)
        out.append(race.base_pace + t["offset"] + t["deg"] * age + t["cliff"] * np.maximum(0, age - t["life"])
                   + race.fuel_effect * (race.laps - laps))
    arr = np.concatenate(out)
    for p in pits:
        arr[p - 1] += race.pit_loss
    return arr


def make_scenarios(race: Race, n=300, seed=1):
    rng = np.random.default_rng(seed)
    has = rng.random(n) < race.sc_prob
    laps = rng.integers(4, max(5, race.laps - 8), size=n)
    return [int(l) if h else None for h, l in zip(has, laps)]


def evaluate(race: Race, comps, pits, scenarios):
    times = np.array([total_time(race, comps, pits, sc) for sc in scenarios])
    return float(times.mean()), float(times.std())


def valid_compounds(seq) -> bool:
    return len(set(seq)) >= 2  # dry-race rule: use at least two different compounds


def optimise(race: Race, n_sims=300, top=10, step=2, min_stint=8, seed=1) -> pd.DataFrame:
    cands = []
    for stops in (1, 2):
        for seq in product(COMPOUNDS, repeat=stops + 1):
            if not valid_compounds(seq):
                continue
            rng1 = range(min_stint, race.laps - min_stint + 1, step)
            if stops == 1:
                pit_sets = [(p,) for p in rng1]
            else:
                pit_sets = [(p1, p2) for p1 in rng1
                            for p2 in range(p1 + min_stint, race.laps - min_stint + 1, step)]
            for pits in pit_sets:
                cands.append((total_time(race, seq, pits), seq, pits))

    shortlist = heapq.nsmallest(60, cands, key=lambda x: x[0])
    scen = make_scenarios(race, n_sims, seed)
    rows = []
    for nosc, seq, pits in shortlist:
        mean, std = evaluate(race, seq, pits, scen)
        rows.append({"Tyres": " > ".join(c[0] for c in seq), "Stops": len(pits),
                     "Pit laps": ", ".join(f"L{p}" for p in pits),
                     "No-SC time (s)": nosc, "Expected time (s)": mean, "Spread (s)": std,
                     "seq": seq, "pits": pits})
    df = pd.DataFrame(rows).sort_values("Expected time (s)").head(top).reset_index(drop=True)
    df["Behind best (s)"] = df["Expected time (s)"] - df["Expected time (s)"].iloc[0]
    return df


def fmt_time(seconds: float) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:06.3f}"
