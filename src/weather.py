"""Weather: Open-Meteo forecast (free, no key) for upcoming races, recorded data for past races."""
import json
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
GEO_CACHE = ROOT / "data" / "processed" / "geo_cache.json"

# approximate circuit coordinates (lat, lon), keyed by normalised FastF1 'Location'
COORDS = {
    "sakhir": (26.0325, 50.5106), "jeddah": (21.6319, 39.1044), "melbourne": (-37.8497, 144.9680),
    "suzuka": (34.8431, 136.5410), "shanghai": (31.3389, 121.2197), "miami": (25.9581, -80.2389),
    "imola": (44.3439, 11.7167), "monaco": (43.7347, 7.4206), "monte carlo": (43.7347, 7.4206),
    "montreal": (45.5000, -73.5228), "barcelona": (41.5700, 2.2611), "spielberg": (47.2197, 14.7647),
    "silverstone": (52.0786, -1.0169), "spa": (50.4372, 5.9714), "budapest": (47.5789, 19.2486),
    "zandvoort": (52.3888, 4.5409), "monza": (45.6156, 9.2811), "baku": (40.3725, 49.8533),
    "marina bay": (1.2914, 103.8640), "singapore": (1.2914, 103.8640), "austin": (30.1328, -97.6411),
    "mexico city": (19.4042, -99.0907), "sao paulo": (-23.7036, -46.6997), "las vegas": (36.1147, -115.1728),
    "lusail": (25.4900, 51.4542), "yas": (24.4672, 54.6031), "abu dhabi": (24.4672, 54.6031),
    "madrid": (40.4655, -3.6165), "istanbul": (40.9517, 29.4050), "portimao": (37.2270, -8.6267),
    "mugello": (43.9975, 11.3719), "sochi": (43.4057, 39.9578), "le castellet": (43.2506, 5.7919),
    "hockenheim": (49.3278, 8.5656), "nurburg": (50.3356, 6.9475), "doha": (25.4900, 51.4542),
}


def _norm(s) -> str:
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()


def coords_for(location, country=None):
    key = _norm(location)
    for k, v in COORDS.items():
        if k in key or (len(key) >= 4 and key in k):
            return v
    try:  # fallback: free geocoding
        cache = json.loads(GEO_CACHE.read_text()) if GEO_CACHE.exists() else {}
        ck = f"{key}|{country}"
        if ck not in cache:
            r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                             params={"name": location, "count": 1}, timeout=10).json()
            res = (r.get("results") or [None])[0]
            cache[ck] = [res["latitude"], res["longitude"]] if res else None
            GEO_CACHE.write_text(json.dumps(cache))
        return tuple(cache[ck]) if cache[ck] else None
    except Exception:
        return None


def forecast(lat, lon, when):
    """Hourly forecast nearest to `when` (UTC). Open-Meteo covers ~16 days ahead; else returns None."""
    when = pd.Timestamp(when)
    when = when.tz_localize("UTC") if when.tzinfo is None else when.tz_convert("UTC")
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=15, params={
            "latitude": lat, "longitude": lon, "timezone": "UTC", "forecast_days": 16, "wind_speed_unit": "kmh",
            "hourly": "temperature_2m,precipitation_probability,precipitation,wind_speed_10m,relative_humidity_2m,cloud_cover"})
        r.raise_for_status()
        h = r.json()["hourly"]
    except Exception:
        return None
    times = pd.to_datetime(h["time"], utc=True)
    diff = np.abs((times - when).total_seconds())
    i = int(diff.argmin())
    if diff[i] > 2 * 3600:
        return None  # race is beyond the forecast window
    g = lambda k: (h[k][i] if h.get(k) and h[k][i] is not None else None)
    return {"temp_c": g("temperature_2m"), "track_c": None, "rain_prob": g("precipitation_probability"),
            "precip_mm": g("precipitation"), "wind_kph": g("wind_speed_10m"), "humidity": g("relative_humidity_2m"),
            "cloud": g("cloud_cover"), "wet": None, "source": "Open-Meteo forecast"}


def event_forecast(location, when, country=None):
    c = coords_for(location, country)
    return forecast(c[0], c[1], when) if c else None


def recorded(results: pd.DataFrame, season: int, rnd: int):
    """Weather measured during a past race (from our results table)."""
    g = results[(results["season"] == season) & (results["round"] == rnd)]
    if g.empty:
        return None
    r = g.iloc[0]
    f = lambda k: None if pd.isna(r.get(k)) else float(r.get(k))
    share = f("rain_share")
    return {"temp_c": f("air_temp"), "track_c": f("track_temp"), "rain_prob": None, "precip_mm": None,
            "wind_kph": None, "humidity": f("humidity"), "cloud": None,
            "wet": bool(share is not None and share > 0.10), "wet_share": share, "source": "Recorded during race"}
