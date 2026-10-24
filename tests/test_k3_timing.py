"""K3: the link frequency the firmware asks for, and real frame timing."""
import tempfile
import time

import pytest

from conftest import ctrl_info, get_fps, reported_fps, set_fps, stream


@pytest.mark.needs_patch("1")
def test_link_frequency_matches_firmware(graph):
    c = ctrl_info("link_frequency")
    assert c["label"].split()[0] == "319200000", \
        f"link_frequency is {c['label']}; patch 1 must select the 319.2 MHz the ACPI SSDB/_DSD asks for"


@pytest.mark.needs_patch("1")
def test_pixel_rate_follows_link_frequency(graph):
    rate = ctrl_info("pixel_rate")["value"]
    assert rate == 63840000, f"pixel_rate is {rate}; at 319.2 MHz (x2 DDR / 10 bpp) it must be 63840000"


def test_90_frames_at_30fps_take_3s(graph):
    set_fps(30)
    with tempfile.TemporaryDirectory() as d:
        t0 = time.monotonic()
        out = stream(90, f"{d}/f.raw")
        wall = time.monotonic() - t0
    fps = reported_fps(out)
    t = 90 / fps if fps else wall
    assert 2.6 <= t <= 3.6, f"90 frames took {t:.2f} s (v4l2-ctl fps {fps}, wall {wall:.2f} s), expected ~3 s at 30 fps"


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
