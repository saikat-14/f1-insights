"""Guards for the requested product changes (liveries removed, 2D circuits, About wording, auto-updating championship)."""
import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import championship as C
import ui
from test_championship import FakeApi, _patch

CODE_FILES = [*ROOT.glob("src/*.py"), *ROOT.glob("app/*.py")]


def _text(files):
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


def test_liveries_are_gone():
    assert not (ROOT / "src" / "livery.py").exists()
    assert "livery" not in _text(CODE_FILES).lower() and "liveries" not in _text(CODE_FILES).lower()


def test_about_and_ui_text_has_no_hobby_wording():
    blob = (_text(CODE_FILES) + (ROOT / "README.md").read_text(encoding="utf-8")).lower()
    for bad in ("hobby", "side project", "fan project", "for fun", "just for fun", "amateur", "experiment"):
        assert bad not in blob, bad
    assert "analytics platform" in (ROOT / "app" / "app.py").read_text(encoding="utf-8")


def _demo_track(sectors=True):
    n = 300
    t = [i * 2 * math.pi / n for i in range(n)]
    x = [2600 * math.cos(a) + 500 * math.cos(3 * a) for a in t]
    y = [1500 * math.sin(a) + 400 * math.sin(2 * a) for a in t]
    return {"x": x, "y": y, "speed": [200 + 80 * math.sin(3 * a) for a in t], "length_m": 5000, "top_speed": 320,
            "corners": [{"n": k + 1, "x": x[i], "y": y[i]} for k, i in enumerate(range(10, n, 30))],
            "sectors": [100, 200] if sectors else None}


def test_circuit_map_is_flat_2d_with_turns_start_finish_and_sectors():
    h = ui.track2d_html(_demo_track(), "Demo GP", "Round 1")
    low = h.lower()
    for banned in ("three.js", "webgl", "orbitcontrols", "perspective", "camera"):
        assert banned not in low
    svg = re.search(r"<svg.*?</svg>", h, flags=re.S).group(0)
    ET.fromstring(svg)                                              # valid, well-formed SVG
    assert svg.count('class="mk"') >= 10 + 1                        # 10 turn markers + start/finish
    assert "START/FINISH" in svg and "S2" in svg and "S3" in svg  # start line + sector markers
    assert "S2" not in ui.track2d_html(_demo_track(sectors=False), "Demo GP")  # no sector data -> no invented sectors


def test_brand_is_prominent_and_logo_assets_are_valid():
    for f in ("logo.svg", "logo_mark.svg"):
        ET.parse(ROOT / "app" / "assets" / f)
    assert "F1 <b>INSIGHTS</b>" in ui.brand_banner() and "F1 <b>INSIGHTS</b>" in ui.brand("Any page")
    assert ui.brand("Any page").count("data:image/svg+xml;base64") == 1


def test_probability_labels_never_overstate_certainty():
    assert ui.fmt_prob(0.9991) == ">99%" and ui.fmt_prob(0.0002) == "<0.1%"
    assert ui.fmt_prob(0.9991, clinched=True) == "Champion"


def test_championship_refreshes_itself_only_when_a_new_race_is_due(tmp_path, monkeypatch):
    api = FakeApi(completed=5, season=datetime.now(timezone.utc).year)   # the real code defaults to the current season
    _patch(monkeypatch, api)
    assert C.update_if_due(proc=tmp_path, now=api.now)["updated"]                      # first run builds everything
    f = tmp_path / "championship.json"
    old = time.time() - 3600
    os.utime(f, (old, old))
    assert C.update_if_due(proc=tmp_path, now=api.now)["updated"] is False             # nothing new -> no network refresh
    api.completed = 6                                                                  # a Grand Prix finishes...
    later = api.now + timedelta(days=15)
    out = C.update_if_due(proc=tmp_path, now=later)                                    # ...the updater notices by itself
    assert out["updated"] and C.load_payload(tmp_path)["as_of_round"] == 6
