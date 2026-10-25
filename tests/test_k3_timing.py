"""K3: the link frequency the firmware asks for, and real frame timing."""
import tempfile
import time

import pytest

from conftest import (H, INTEGRATION_MARGIN, MODE_VTS, VTS_REG, ctrl_info, get_fps, read_reg, reported_fps, set_ctrl, set_fps,
                      setup_graph, stream, streaming)

# PLL1 for a 19.2 MHz xclk (what ipu-bridge/INT3472 gives the sensor here; stock reads back 03 4b 01 0a 05, the 240 MHz
# entry) and a 319.2 MHz link: ov7251_pll1_cfg_19_2_mhz_319_2_mhz in drivers/media/i2c/ov7251.c
PLL1_319_2 = {"pre_div 0x30b4": 0x01, "mult 0x30b3": 0x85, "div 0x30b1": 0x04, "pix_div 0x30b0": 0x0a, "mipi_div 0x30b5": 0x05}


def restore_30fps_vblank():
    """Back to the 30 fps mode and its frame length: set_fps(30) alone keeps a VBLANK set by hand in the same mode."""
    set_fps(30)
    set_ctrl("vertical_blanking", ctrl_info("vertical_blanking")["default"])


@pytest.mark.needs_patch("1")
def test_link_frequency_matches_firmware(graph):
    c = ctrl_info("link_frequency")
    assert c["label"].split()[0] == "319200000", \
        f"link_frequency is {c['label']}; patch 1 must select the 319.2 MHz the ACPI SSDB/_DSD asks for"


@pytest.mark.needs_patch("1")
def test_pixel_rate_follows_link_frequency(graph):
    rate = ctrl_info("pixel_rate")["value"]
    assert rate == 63840000, f"pixel_rate is {rate}; at 319.2 MHz (x2 DDR / 10 bpp) it must be 63840000"


@pytest.mark.needs_patch("1")
def test_pll1_programmed_for_319_2_mhz(graph):
    with streaming():
        got = {name: read_reg(int(name.split()[1], 16)) for name in PLL1_319_2}
    assert got == PLL1_319_2, f"PLL1 registers {got}, expected the 19.2 MHz -> 319.2 MHz table {PLL1_319_2} (patch 1 index fix)"


def test_90_frames_at_30fps_take_3s(graph):
    set_fps(30)
    with tempfile.TemporaryDirectory() as d:
        t0 = time.monotonic()
        out = stream(90, f"{d}/f.raw")
        wall = time.monotonic() - t0
    fps = reported_fps(out)
    t = 90 / fps if fps else wall
    assert 2.6 <= t <= 3.6, f"90 frames took {t:.2f} s (v4l2-ctl fps {fps}, wall {wall:.2f} s), expected ~3 s at 30 fps"


@pytest.mark.needs_patch("2")
@pytest.mark.parametrize("fps", [60, 90])
def test_frame_interval_selects_fps(graph, fps):
    try:
        set_fps(fps)
        got = get_fps()
        with tempfile.TemporaryDirectory() as d:
            measured = reported_fps(stream(2 * fps, f"{d}/f.raw"))
    finally:
        set_fps(30)
    assert abs(got - fps) < 1, f"--set-subdev-fps fps={fps} read back {got}"
    assert measured and abs(measured - fps) / fps < 0.05, f"asked {fps} fps, v4l2-ctl measured {measured}"


def check_mode_controls(fps):
    vts = MODE_VTS[fps]
    vb, ex = ctrl_info("vertical_blanking"), ctrl_info("exposure")
    want = {"min": 1, "max": 0xffff - H, "default": vts - H, "value": vts - H}
    assert {k: vb[k] for k in want} == want, \
        f"vertical_blanking at {fps} fps {vb}, expected {want} (VTS {vts}): patch 2 resets VBLANK on a frame interval change"
    assert ex["max"] == vts - INTEGRATION_MARGIN, \
        f"exposure max {ex['max']} at {fps} fps, expected VTS {vts} - {INTEGRATION_MARGIN} = {vts - INTEGRATION_MARGIN}"


@pytest.mark.needs_patch("2")
@pytest.mark.parametrize("fps", [60, 90])
def test_vblank_and_exposure_range_follow_frame_interval(graph, fps):
    try:
        set_fps(fps)
        check_mode_controls(fps)
        set_fps(30)
        check_mode_controls(30)
    finally:
        restore_30fps_vblank()


@pytest.mark.parametrize("fps", [30, pytest.param(60, marks=pytest.mark.needs_patch("2")),
                                 pytest.param(90, marks=pytest.mark.needs_patch("2"))])
def test_vts_register_matches_mode(graph, fps):
    try:
        set_fps(fps)
        with streaming():
            vts = read_reg(VTS_REG, 2)
    finally:
        restore_30fps_vblank()
    assert vts == MODE_VTS[fps], f"0x380e/0x380f = {vts} streaming at {fps} fps, expected the mode's VTS {MODE_VTS[fps]} (patch 2)"


@pytest.mark.needs_patch("2")
def test_set_fmt_after_frame_interval_is_consistent(graph):
    """The other direction of patch 2: an active set_fmt after a 60 fps interval must not keep the 60 fps VBLANK
    (set_fmt picks the first 640x480 mode, 30 fps). VBLANK is also set by hand so the stock driver reaches the same state."""
    try:
        set_fps(60)
        set_ctrl("vertical_blanking", MODE_VTS[60] - H)
        setup_graph()
        fps = round(get_fps())
        vb = ctrl_info("vertical_blanking")["value"]
        with streaming():
            vts = read_reg(VTS_REG, 2)
    finally:
        restore_30fps_vblank()
    assert vb == MODE_VTS[fps] - H, \
        f"after set_fmt the interval reads {fps} fps but vertical_blanking is {vb}, expected {MODE_VTS[fps] - H} (patch 2)"
    assert vts == MODE_VTS[fps], f"after set_fmt streaming VTS {vts}, the {fps} fps mode needs {MODE_VTS[fps]} (patch 2)"
