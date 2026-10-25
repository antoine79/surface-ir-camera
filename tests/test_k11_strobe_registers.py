"""K11: what the driver writes to the strobe registers, read back over I2C while streaming.

Patch 5 moves the strobe block out of the three mode tables without changing a value, so with the strobe off every
register reads back what the stock tables wrote, on both modules. Patch 6 then drives SC_REG5 bit 3, the frame
pattern and the 32-bit frame span from STROBE_OE: span = clamp(exposure, 52, min(ceil(VTS * 45 / 100), 776)) lines.
"""
import pytest

from conftest import (EXPO_REG, H, INTEGRATION_MARGIN, MODE_VTS, SC_REG5, STROBE, STROBE_PATTERN, STROBE_SPAN, VTS_REG, ctrl,
                      ctrl_info, read_reg, runtime_status, set_ctrl, set_fps, streaming, wait_for)

# 0x3005 and 0x3b80..0x3b96 as the stock mode tables (all three identical) write them, from the patch 5 diff
STOCK_STROBE_REGS = {0x3005: 0x00, 0x3b80: 0x00, 0x3b81: 0xa5, 0x3b82: 0x10, 0x3b83: 0x00, 0x3b84: 0x08, 0x3b85: 0x00,
                     0x3b86: 0x01, 0x3b87: 0x00, 0x3b88: 0x00, 0x3b89: 0x00, 0x3b8a: 0x00, 0x3b8b: 0x05, 0x3b8c: 0x00,
                     0x3b8d: 0x00, 0x3b8e: 0x00, 0x3b8f: 0x1a, 0x3b94: 0x05, 0x3b95: 0xf2, 0x3b96: 0x40}
OFF = (0x00, 0xa5, 0x1a)  # SC_REG5, frame pattern, span with the strobe off
SPAN_MIN, SPAN_MAX, DUTY = 52, 776, 45
MISSING = f"{STROBE} missing: patch 6 adds V4L2_CID_FLASH_STROBE_OE"


def span_for(exposure: int, vts: int) -> int:
    return min(max(exposure, SPAN_MIN), -(-vts * DUTY // 100), SPAN_MAX)


def strobe_state() -> tuple[int, int, int]:
    return read_reg(SC_REG5), read_reg(STROBE_PATTERN), read_reg(STROBE_SPAN, 4)


def strobe_off_if_present():
    if ctrl_info(STROBE):
        set_ctrl(STROBE, 0)


@pytest.fixture
def clean():
    """Leave the strobe off, 30 fps and the 30 fps frame length whatever the test did."""
    yield
    strobe_off_if_present()
    set_fps(30)
    set_ctrl("vertical_blanking", ctrl_info("vertical_blanking")["default"])


@pytest.mark.parametrize("fps", [30, 60, 90])
def test_strobe_block_unchanged_with_strobe_off(graph, clean, fps):
    strobe_off_if_present()
    set_fps(fps)
    with streaming():
        got = {a: read_reg(a) for a in STOCK_STROBE_REGS}
    diff = {f"0x{a:04x}": (f"0x{got[a]:02x}", f"0x{v:02x}") for a, v in STOCK_STROBE_REGS.items() if got[a] != v}
    assert not diff, f"strobe block at {fps} fps, strobe off, differs from the stock mode tables (read, expected): {diff} (patch 5)"


@pytest.mark.needs_patch("6")
@pytest.mark.parametrize("fps, exposure", [(fps, e) for fps, mid in ((30, 504), (60, 300), (90, 200))
                                           for e in (10, mid, "max")])
def test_strobe_on_at_stream_start(graph, clean, fps, exposure):
    assert ctrl_info(STROBE), MISSING
    set_fps(fps)  # resets exposure to 504, so set it after
    exposure = ctrl_info("exposure")["max"] if exposure == "max" else exposure
    set_ctrl("exposure", exposure)
    set_ctrl(STROBE, 1)
    with streaming():
        reg5, pattern, span = strobe_state()
    want = span_for(exposure, MODE_VTS[fps])
    assert (reg5, pattern) == (0x08, 0xff), f"0x3005 = 0x{reg5:02x}, 0x3b81 = 0x{pattern:02x}, expected 0x08 (pad on) and 0xff"
    assert span == want, f"span {span} at {fps} fps, exposure {exposure}: expected clamp({exposure}, {SPAN_MIN}, 45% of {MODE_VTS[fps]}) = {want}"


@pytest.mark.needs_patch("6")
def test_span_follows_exposure_while_streaming(graph, clean):
    assert ctrl_info(STROBE), MISSING
    set_ctrl("exposure", 504)
    set_ctrl(STROBE, 1)
    seen = []
    with streaming(6):
        for exposure in (504, 1000, 100, 10):
            set_ctrl("exposure", exposure)
            seen.append((exposure, read_reg(EXPO_REG, 3) >> 4, read_reg(STROBE_SPAN, 4)))
    want = [(e, e, span_for(e, MODE_VTS[30])) for e, _, _ in seen]
    assert seen == want, f"(exposure, exposure register, span) {seen}, expected {want}: the span must follow exposure"


def test_span_untouched_by_exposure_with_strobe_off(graph, clean):
    strobe_off_if_present()
    with streaming():
        set_ctrl("exposure", 1000)
        expo, span = read_reg(EXPO_REG, 3) >> 4, read_reg(STROBE_SPAN, 4)
    assert (expo, span) == (1000, 0x1a), f"exposure register {expo}, span {span}: with the strobe off span stays 0x1a"


@pytest.mark.needs_patch("6")
def test_span_follows_vblank_while_streaming(graph, clean):
    assert ctrl_info(STROBE), MISSING
    set_ctrl("exposure", MODE_VTS[30] - INTEGRATION_MARGIN)
    set_ctrl(STROBE, 1)
    seen = []
    with streaming(5):
        for vts in (MODE_VTS[30], 1100, 3000, MODE_VTS[30]):
            set_ctrl("vertical_blanking", vts - H)
            seen.append((vts, read_reg(VTS_REG, 2), ctrl("exposure"), read_reg(STROBE_SPAN, 4)))
    # 1100 lines clamp exposure to 1080 (VTS - margin), which then stays: span 776, 495, 776 (3000 x 45% = 1350 capped), 776
    want = [(v, v, e, span_for(e, v)) for v, _, e, _ in seen]
    assert [s[2] for s in seen] == [1704, 1080, 1080, 1080], f"exposure did not follow the frame length: {seen}"
    assert seen == want, f"(VTS, 0x380e/f, exposure, span) {seen}, expected {want}: the span must follow VBLANK"


def test_vblank_change_with_strobe_off_keeps_default_span(graph, clean):
    strobe_off_if_present()
    with streaming():
        set_ctrl("vertical_blanking", 1100 - H)
        vts, span = read_reg(VTS_REG, 2), read_reg(STROBE_SPAN, 4)
    assert (vts, span) == (1100, 0x1a), f"VTS {vts}, span {span}: expected 1100 and the default 0x1a with the strobe off"


@pytest.mark.needs_patch("6")
def test_strobe_toggled_while_streaming(graph, clean):
    assert ctrl_info(STROBE), MISSING
    set_ctrl("exposure", 504)
    set_ctrl(STROBE, 0)
    seen = []
    with streaming(5):
        seen.append(strobe_state())
        set_ctrl(STROBE, 1)
        seen.append(strobe_state())
        set_ctrl(STROBE, 0)
        seen.append(strobe_state())
    want = [OFF, (0x08, 0xff, 504), OFF]
    assert seen == want, f"(0x3005, 0x3b81, span) off/on/off while streaming: {seen}, expected {want}"


@pytest.mark.needs_patch("6")
def test_strobe_survives_runtime_suspend(graph, clean):
    """Set while idle, the control is applied at each stream start by __v4l2_ctrl_handler_setup(), also after the
    sensor was powered off in between."""
    assert ctrl_info(STROBE), MISSING
    set_ctrl("exposure", 504)
    set_ctrl(STROBE, 1)
    with streaming(2):
        first = strobe_state()
    assert wait_for(lambda: runtime_status() == "suspended", 3), f"sensor {runtime_status()} 3 s after the stream"
    with streaming(2):
        second = strobe_state()
    assert first == second == (0x08, 0xff, 504), f"strobe registers first stream {first}, after suspend {second}"
