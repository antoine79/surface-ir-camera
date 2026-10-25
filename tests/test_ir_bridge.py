"""Pure-software tests for tools/ir-bridge.py: frame selection (lit/all/diff) and the 10-bit to 8-bit conversion."""
import importlib.util
from pathlib import Path

import numpy as np

_spec = importlib.util.spec_from_file_location("ir_bridge", Path(__file__).resolve().parents[1] / "tools" / "ir-bridge.py")
bridge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bridge)

DARK = np.full((480, 640), 20, np.uint16)
LIT = np.full((480, 640), 120, np.uint16)
LIT[100:200, 300:400] = 1023  # a bright spot, saturated, so lit - dark clips at 1023 there


def test_lit_keeps_the_brighter_of_each_pair_whatever_the_order():
    out = list(bridge.select([DARK, LIT, LIT, DARK, DARK], "lit"))
    assert len(out) == 2 and all(np.array_equal(f, LIT) for f in out)  # the odd trailing frame has no partner


def test_all_passes_everything():
    assert len(list(bridge.select([DARK, LIT, DARK], "all"))) == 3


def test_diff_is_lit_minus_dark_clipped():
    (out,) = bridge.select([DARK, LIT], "diff")
    assert out.dtype == np.uint16 and out[0, 0] == 100 and out[150, 350] == 1003


def test_to8_shifts_and_rotates():
    frame = np.arange(480 * 640, dtype=np.uint16).reshape(480, 640) % 1024
    out = bridge.to8(frame, rotate=False)
    assert out.dtype == np.uint8 and out.shape == (480, 640) and out[1, 383] == 255 and out[0, 3] == 0  # pixel 1023 -> 255, pixel 3 -> 0
    rot = bridge.to8(frame)
    assert rot.shape == (640, 480) and rot[0, 0] == frame[0, -1] >> 2  # counter-clockwise: top-right corner goes top-left
