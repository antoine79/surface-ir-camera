"""Unit tests for tools/glow_compare.py on synthetic 120x160 frames."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import glow_compare as gc  # noqa: E402


def frame(lit, value=230):
    rng = np.random.default_rng(0)
    f = (10 + rng.integers(0, 3, (120, 160))).astype(np.uint8)
    if lit:
        yy, xx = np.ogrid[:120, :160]
        f[(yy - 60) ** 2 + (xx - 80) ** 2 <= 36] = value
    return f


def test_blob_mean():
    assert abs(gc.blob_mean(frame(True)) - 230) <= 5
    assert gc.blob_mean(frame(False)) is None


def test_alternating():
    r = gc.analyse([frame(i % 2 == 0) for i in range(64)], 30)
    assert abs(r["lit_fraction"] - 0.5) < 0.02
    assert abs(r["flicker_hz"] - 15) <= 1


def test_all_lit():
    r = gc.analyse([frame(True) for _ in range(64)], 30)
    assert r["lit_fraction"] == 1.0
    assert abs(r["median"] - 230) <= 5


def test_too_large():
    assert gc.blob_mean(np.full((120, 160), 250, np.uint8)) is None
