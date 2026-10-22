"""
Day 2 / step 2: Monte Carlo race simulation.
Turns "predicted position" + "DNF chance" into win / podium / top-10 probabilities.
"""
import numpy as np

_MAD_TO_STD = 1.2533  # mean absolute deviation -> standard deviation for a normal


def fit_sigma(pred_pos: np.ndarray, abs_resid: np.ndarray):
    """Uncertainty grows for midfield drivers. Fit |error| ~ a + b * predicted_position."""
    b, a = np.polyfit(pred_pos, abs_resid, 1)
    return float(a * _MAD_TO_STD), float(b * _MAD_TO_STD)


def sigma_for(pred_pos, a: float, b: float):
    return np.clip(a + b * np.asarray(pred_pos), 0.8, 6.0)


def simulate(pred_pos, p_dnf, a, b, n=5000, seed=0):
    """Returns dict of per-driver arrays: win, podium, top10, exp_pos."""
    rng = np.random.default_rng(seed)
    pred_pos = np.asarray(pred_pos, dtype=float)
    p_dnf = np.asarray(p_dnf, dtype=float)
    k = len(pred_pos)

    score = pred_pos[None, :] + rng.normal(size=(n, k)) * sigma_for(pred_pos, a, b)[None, :]
    dnf = rng.random((n, k)) < p_dnf[None, :]
    score = np.where(dnf, 1000 + rng.random((n, k)), score)  # retirements end up at the back

    ranks = score.argsort(axis=1).argsort(axis=1) + 1
    return {
        "win_prob": (ranks == 1).mean(0),
        "podium_prob": (ranks <= 3).mean(0),
        "top10_prob": (ranks <= 10).mean(0),
        "exp_pos": ranks.mean(0),
    }
