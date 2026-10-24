"""Unit tests for the IPU3 packed 10-bit greyscale (V4L2_PIX_FMT_IPU3_Y10, 'ip3y') unpacker.

Layout (kernel Documentation/userspace-api/media/v4l/pixfmt-srggb10-ipu3.rst, shared by ip3y):
a 32-byte chunk holds 25 pixels of 10 bits as one 256-bit little-endian word, pixel i at
bits [10*i, 10*i+10); the top 6 bits are padding. The CIO2 writes 64-byte blocks (two chunks),
so a 640-pixel line is ceil(640/50) * 64 = 832 bytes.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import ip3y  # noqa: E402


def pack_chunk(pixels):
    """Reference packer: 25 ten-bit values -> 32 bytes, bit-exact per the kernel doc."""
    assert len(pixels) == 25
    word = 0
    for i, p in enumerate(pixels):
        assert 0 <= p < 1024
        word |= p << (10 * i)
    return word.to_bytes(32, "little")


def pack_line(pixels, bytesperline):
    out = bytearray()
    for start in range(0, len(pixels), 25):
        chunk = list(pixels[start:start + 25])
        chunk += [0] * (25 - len(chunk))
        out += pack_chunk(chunk)
    out += b"\0" * (bytesperline - len(out))
    return bytes(out)


def test_bytesperline_matches_cio2_formula():
    assert ip3y.bytesperline(640) == 832


def test_unpack_recovers_known_pixels_in_one_block():
    pixels = [0, 1, 2, 3, 1023, 512, 256, 128, 64, 32, 16, 8, 4, 1022, 341, 682, 0, 1023, 0, 1023, 100, 200, 300, 400, 500,
              999, 1, 1023, 0, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]
    assert len(pixels) == 50
    buf = pack_line(pixels, ip3y.bytesperline(50))
    out = ip3y.unpack(buf, width=50, height=1)
    assert out.dtype == np.uint16
    assert out.tolist() == [pixels]


def test_unpack_frame_shape_and_row_order():
    width, height = 640, 480
    bpl = ip3y.bytesperline(width)
    rows = [np.full(width, r % 1024, dtype=np.uint16) for r in range(height)]
    buf = b"".join(pack_line(row.tolist(), bpl) for row in rows)
    assert len(buf) == bpl * height == 399360
    out = ip3y.unpack(buf, width=width, height=height)
    assert out.shape == (height, width)
    assert out[0, 0] == 0 and out[479, 639] == 479 and out[300, 17] == 300


def test_unpack_rejects_short_buffer():
    with pytest.raises(ValueError):
        ip3y.unpack(b"\0" * 100, width=640, height=480)
