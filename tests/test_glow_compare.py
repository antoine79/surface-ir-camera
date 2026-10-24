"""Unit tests for tools/glow_compare.py on synthetic 120x160 BGR frames."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import glow_compare as gc  # noqa: E402


def frame(lit, radius=6):
    """Dark scene with a bright white screen; when lit, a magenta dot with a saturated white core."""
    f = np.full((120, 160, 3), 10, np.uint8)
    f[90:, :] = 255  # the laptop screen: brightest region, must be ignored
    if lit:
        yy, xx = np.ogrid[:120, :160]
        d = (yy - 40) ** 2 + (xx - 80) ** 2
        f[d <= radius ** 2] = (200, 60, 230)  # BGR magenta halo
        f[d <= 4] = 255
    return f


def test_glow_ignores_screen_and_sees_dot():
    assert gc.glow(frame(False)) == 0.0
    assert gc.glow(frame(True)) > 0
    assert gc.glow(frame(True, radius=9)) > gc.glow(frame(True, radius=6))


def test_runs_split_takes():
    series = [0.0] * 30 + [1.0] * 60 + [0.0] * 5 + [1.0] * 60 + [0.0] * 90 + [1.0] * 10 + [0.0] * 30
    assert gc.runs(series, 30) == [(30, 154)]  # a 5-frame gap is bridged, a 10-frame run is noise
    series = [0.0] * 30 + [1.0] * 60 + [0.0] * 60 + [1.0] * 60
    assert gc.runs(series, 30) == [(30, 89), (150, 209)]


def test_analyse_reports_each_take():
    frames = [frame(False)] * 30 + [frame(True)] * 60 + [frame(False)] * 60 + [frame(True, radius=9)] * 60
    r = gc.analyse(frames, 30)
    assert [(x["start"], x["end"], x["n"]) for x in r] == [(1.0, 3.0, 60), (5.0, 7.0, 60)]
    assert r[1]["median"] > r[0]["median"]
