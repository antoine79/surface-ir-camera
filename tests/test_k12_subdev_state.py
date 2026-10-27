"""K12: the active-state conversion (patch 3) kept the old behaviour. The format, the crop rectangle and the mode-derived
control ranges now live in the core sub-device state under the control handler's lock; each test reads one of them back
through user space the way the old driver-side copies answered. Every test passes on the stock 7.2 module too (that is
the proof); control events are K2's test_exposure_change_sends_event_with_value.
"""
import re
import subprocess

import pytest

from conftest import (H, INTEGRATION_MARGIN, MODE_VTS, W, ctrl, ctrl_info, get_fps, restore_30fps_vblank, run, sd, set_ctrl,
                      set_fps, streaming, subdev)

FMT = (W, H, "MEDIA_BUS_FMT_Y10_1X10")
CROP = (0, 0, W, H)
NATIVE, BOUNDS = (0, 0, 656, 496), (4, 4, 648, 488)  # OV7251_NATIVE_* and OV7251_ACTIVE_* in drivers/media/i2c/ov7251.c
LOG_BAD = re.compile(r"lockdep|WARNING|BUG|possible recursive locking")


def fmt(*args) -> tuple[int, int, str]:
    """(width, height, bus code name) printed by --get-subdev-fmt, --try-subdev-fmt or --set-subdev-fmt."""
    out = run("v4l2-ctl", "-d", sd(), *args)
    w, h = re.search(r"Width/Height\s*: (\d+)/(\d+)", out).groups()
    return int(w), int(h), re.search(r"Mediabus Code\s*: \S+ \((\w+)\)", out).group(1)


def selection(target: str) -> tuple[int, int, int, int]:
    out = run("v4l2-ctl", "-d", sd(), "--get-subdev-selection", f"pad=0,target={target}")
    return tuple(int(x) for x in re.search(r"Left (\d+), Top (\d+), Width (\d+), Height (\d+)", out).groups())


def mode_ranges() -> dict:
    ex, vb = ctrl_info("exposure"), ctrl_info("vertical_blanking")
    return {"exposure min": ex["min"], "exposure max": ex["max"], "vblank default": vb["default"]}


MODE30 = {"exposure min": 1, "exposure max": MODE_VTS[30] - INTEGRATION_MARGIN, "vblank default": MODE_VTS[30] - H}


def kernel_log() -> list[str]:
    return run("journalctl", "-k", "-b", "-o", "cat").splitlines()


def test_defaults_as_probe_left_them():
    """No graph fixture: the state init_state filled at probe (or the last test's restore) is read as is. The exposure
    default is not checked here: the VBLANK handler moves it to the current exposure (mainline behaviour, see K11)."""
    if subdev() is None:
        pytest.skip("no ov7251 subdev")
    assert fmt("--get-subdev-fmt", "pad=0") == FMT
    assert (selection("crop"), selection("crop_default")) == (CROP, CROP)
    assert (selection("native_size"), selection("crop_bounds")) == (NATIVE, BOUNDS)
    assert mode_ranges() == MODE30


def test_try_fmt_does_not_touch_active_state(graph):
    before = mode_ranges()
    assert fmt("--try-subdev-fmt", "pad=0,width=320,height=240") == FMT, "the driver has one size: a try must snap to it"
    assert fmt("--get-subdev-fmt", "pad=0") == FMT and selection("crop") == CROP, "a try format leaked into the active one"
    assert mode_ranges() == before, "a try format must not change the control ranges"


def test_active_set_fmt_snaps_to_mode_and_resets_ranges(graph):
    """320x240 ties on all three 640x480 modes and v4l2_find_nearest_size keeps the last one (90 fps); 640x480 matches
    the first (30 fps). Both are core rules the old driver-side copies followed too."""
    try:
        for size, fps in (("320x240", 90), ("640x480", 30)):
            w, h = size.split("x")
            run("v4l2-ctl", "-d", sd(), "--set-subdev-fmt", f"pad=0,width={w},height={h}")  # prints nothing: read back
            assert fmt("--get-subdev-fmt", "pad=0") == FMT and selection("crop") == CROP
            assert abs(get_fps() - fps) < 1, f"set_fmt {size} selected {get_fps()} fps, expected the {fps} fps mode"
            vts = MODE_VTS[fps]
            assert mode_ranges() == {"exposure min": 1, "exposure max": vts - INTEGRATION_MARGIN, "vblank default": vts - H}
            assert ctrl_info("exposure")["default"] == 504, "an active set_fmt sets the mode's exposure default"
    finally:
        restore_30fps_vblank()


# A per-file-handle try state cannot be observed: with one size and one bus code every try format is the same.


def test_frame_interval_updates_exposure_range(graph):
    """VBLANK following the interval is patch 2: K3 test_vblank_and_exposure_range_follow_frame_interval."""
    try:
        set_fps(90)
        assert abs(get_fps() - 90) < 1
        assert ctrl_info("exposure")["max"] == MODE_VTS[90] - INTEGRATION_MARGIN
        set_fps(30)
        assert abs(get_fps() - 30) < 1 and ctrl_info("exposure")["max"] == MODE30["exposure max"]
    finally:
        restore_30fps_vblank()


def test_controls_while_streaming_under_shared_lock(graph):
    """Exposure and VBLANK go through the control handler lock, which is now also the state lock the stream holds."""
    seen = len(kernel_log())
    try:
        with streaming(4):
            for exposure, vblank in ((1000, 1500), (100, 2000), (504, MODE30["vblank default"])):
                set_ctrl("exposure", exposure)
                set_ctrl("vertical_blanking", vblank)
                assert (ctrl("exposure"), ctrl("vertical_blanking")) == (exposure, vblank)
    finally:
        restore_30fps_vblank()
    bad = [l for l in kernel_log()[seen:] if LOG_BAD.search(l)]
    assert not bad, "kernel log during the stream:\n" + "\n".join(bad)


def test_set_fmt_and_interval_while_streaming_are_accepted(graph):
    """Neither the core nor the driver refuses them mid-stream (stock 7.2 behaviour, kept): same mode, so the stream
    goes on and the format reads back unchanged after it."""
    with streaming(3):
        p = subprocess.run(["v4l2-ctl", "-d", sd(), "--set-subdev-fmt", "pad=0,width=320,height=240"], capture_output=True, text=True)
        q = subprocess.run(["v4l2-ctl", "-d", sd(), "--set-subdev-fps", "pad=0,fps=30"], capture_output=True, text=True)
    assert p.returncode == 0, f"set_fmt while streaming: exit {p.returncode} {p.stderr.strip()}"
    assert q.returncode == 0, f"frame interval while streaming: exit {q.returncode} {q.stderr.strip()}"
    assert fmt("--get-subdev-fmt", "pad=0") == FMT and abs(get_fps() - 30) < 1
