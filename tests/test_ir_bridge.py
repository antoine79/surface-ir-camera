"""Pure-software tests for tools/ir-bridge.py: frame selection (lit/all/diff) and the 10-bit to 8-bit conversion."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

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
    out = bridge.to8(frame, turns=0)
    assert out.dtype == np.uint8 and out.shape == (480, 640) and out[1, 383] == 255 and out[0, 3] == 0  # pixel 1023 -> 255, pixel 3 -> 0
    rot = bridge.to8(frame)
    assert rot.shape == (640, 480) and rot[0, 0] == frame[0, -1] >> 2  # counter-clockwise: top-right corner goes top-left
    cw = bridge.to8(frame, bridge.ROTATIONS["cw"])
    assert cw.shape == (640, 480) and cw[0, 0] == frame[-1, 0] >> 2  # clockwise: bottom-left corner goes top-left


FRAME = np.random.default_rng(1).integers(0, 1024, (6, 8), dtype=np.uint16)


def test_unpack_y10_reads_low_10_bits_and_skips_line_padding():
    words = np.zeros((6, 10), "<u2")  # bytesperline 20: 2 padding pixels per line
    words[:, :8] = FRAME | 0xFC00  # junk in the top 6 bits must be masked
    out = bridge.unpack_y10(words.tobytes(), 8, 6, 20)
    assert out.shape == (6, 8) and np.array_equal(out, FRAME)


def test_unpack_y10p_round_trips_the_csi2_packing():
    g = FRAME.reshape(6, 2, 4)
    packed = np.zeros((6, 2, 5), np.uint8)
    packed[:, :, :4] = g >> 2
    packed[:, :, 4] = sum(((g[:, :, i] & 3) << (2 * i)) for i in range(4))
    raw = np.zeros((6, 12), np.uint8)  # bytesperline 12: 2 padding bytes per line
    raw[:, :10] = packed.reshape(6, 10)
    assert np.array_equal(bridge.unpack_y10p(raw.tobytes(), 8, 6, 12), FRAME)


def test_ipu3_platform_frame_size_and_unpack_match_ip3y():
    p = bridge.Ipu3()
    buf = bytes(range(256)) * (p.frame_bytes() // 256 + 1)
    assert p.frame_bytes() == 832 * 480
    assert np.array_equal(p.unpack(buf), bridge.ip3y.unpack(buf, 640, 480))


def test_template_is_not_registered_and_says_what_to_fill():
    assert "template" not in bridge.PLATFORMS
    with pytest.raises(NotImplementedError, match="media links"):
        bridge.Template().setup("m", "v", "s")
