"""Unpack IPU3 packed 10-bit greyscale (V4L2_PIX_FMT_IPU3_Y10, 'ip3y') frames.

A 32-byte chunk holds 25 pixels as one 256-bit little-endian word: pixel i is at bits [10*i, 10*i+10),
the top 6 bits are padding. The CIO2 writes 64-byte blocks (two chunks, 50 pixels), so every line is
padded to a multiple of 50 pixels.
"""
import numpy as np

_BIT = 10 * np.arange(25)
_LO = _BIT // 8  # byte holding the pixel's low bits; the next byte holds the rest (shift is at most 6)
_SHIFT = (_BIT % 8).astype(np.uint16)


def bytesperline(width: int) -> int:
    return -(-width // 50) * 64


def unpack(buf: bytes | bytearray | memoryview, width: int, height: int) -> np.ndarray:
    need = bytesperline(width) * height
    raw = np.frombuffer(buf, np.uint8)
    if raw.size < need:
        raise ValueError(f"buffer too short: {raw.size} bytes, {width}x{height} needs {need}")
    chunks = raw[:need].reshape(-1, 32).astype(np.uint16)
    pixels = ((chunks[:, _LO] | chunks[:, _LO + 1] << 8) >> _SHIFT) & 0x3FF
    return pixels.reshape(height, -1)[:, :width]
