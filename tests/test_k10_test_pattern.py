"""K10: the ip3y unpacker decodes the sensor's test pattern exactly.

On this monochrome OV7251 "Vertical Pattern Bars" is the colour-bar pattern laid on a 2x2 Bayer mosaic: 8 bars of
80 px (white, yellow, cyan, green, magenta, red, blue, black), each pixel 0 or 1023, so the bar means are
1023 * (4, 3, 3, 2, 2, 1, 1, 0) / 4 and rows repeat with period 2.
"""
import numpy as np
import pytest

from conftest import capture, set_ctrl


@pytest.fixture(scope="module")
def frames(graph):
    set_ctrl("test_pattern", 1)
    try:
        return capture(3)
    finally:
        set_ctrl("test_pattern", 0)


def test_frames_identical(frames):
    assert (frames == frames[0]).all(), "test-pattern frames differ: the unpacker or the stream is unstable"


def test_only_full_scale_values(frames):
    assert set(np.unique(frames).tolist()) == {0, 1023}, f"values {np.unique(frames)[:10]}: expected only 0 and 1023"


def test_rows_repeat_every_two(frames):
    f = frames[0]
    assert (f[0::2] == f[0]).all() and (f[1::2] == f[1]).all(), "rows must alternate between two patterns (Bayer)"


def test_eight_vertical_bars(frames):
    means = [frames[0][:, x + 4:x + 76].mean() for x in range(0, 640, 80)]  # skip the bar edges
    expect = [1023 * k / 4 for k in (4, 3, 3, 2, 2, 1, 1, 0)]
    assert np.allclose(means, expect), f"bar means {np.round(means, 2)}, expected {expect}"
