"""End to end: the IR camera works as a camera, the way the firmware describes it.

One scenario, in the order a camera stack goes through it. On the stock driver it fails at the first step that needs
a patch; with the whole series it passes and leaves two pictures in $IRCAM_E2E_OUT (default docs/e2e/):

1. the sensor reports the link frequency the firmware asks for (patch 1) and where it sits (patch 5), mounted rotated
   by 90 degrees (patch 8, ipu-bridge DMI quirk: the ACPI _PLD says 0);
2. a process can subscribe to control events, as libcamera does at start-up (patch 3);
3. the stack selects 60 fps (patch 4), sets exposure and analogue gain (patch 2) and switches the emitter on (patch 7);
4. 60 frames arrive in about one second, lit by the emitter, with a real image in them: aim the camera at the room
   before running, in the dark (daylight swamps the emitter), the lit frame is saved as the picture of the room;
5. afterwards the emitter is off and the sensor powered down (patch 7).

Run: pytest -v tests/test_e2e.py   (red on stock, green with kernel/build/ov7251.ko swapped in).
"""
import os
import subprocess
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

import ip3y
from conftest import (FRAME_BYTES, H, STROBE, W, ctrl, ctrl_info, get_fps, need_dark, reported_fps, runtime_status, sd,
                      set_ctrl, set_fps, stream, wait_for)

pytestmark = pytest.mark.needs_patch("all")

FIRMWARE_LINK_FREQ = 319_200_000  # what ipu-bridge hands every INT347E (drivers/media/pci/intel/ipu-bridge.c)
FPS = 60
EXPOSURE, GAIN = 504, 16  # the driver defaults; at gain 128 the emitter saturates a third of a desk scene
OUT = Path(os.environ.get("IRCAM_E2E_OUT", Path(__file__).resolve().parents[1] / "docs" / "e2e"))


def grab(frames: int) -> tuple[np.ndarray, float]:
    """(frames, 480, 640) uint16 and the frame rate v4l2-ctl measured while streaming."""
    with tempfile.TemporaryDirectory() as d:
        out = stream(frames, f"{d}/frames.raw")
        raw = np.fromfile(f"{d}/frames.raw", np.uint8)
    assert raw.size == frames * FRAME_BYTES, f"got {raw.size} bytes, expected {frames} frames"
    return np.stack([ip3y.unpack(raw[i:i + FRAME_BYTES], W, H) for i in range(0, raw.size, FRAME_BYTES)]), reported_fps(out)


def to_png(frame: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), (frame >> 2).astype(np.uint8))  # 10-bit to 8-bit, no stretching: brightness is the evidence


def test_firmware_description(graph):
    link = ctrl_info("link_frequency")
    assert link and link["label"].split()[0] == str(FIRMWARE_LINK_FREQ), \
        f"link_frequency is {link and link['label']}: the sensor must run at the {FIRMWARE_LINK_FREQ} Hz the firmware asks for (patch 1)"
    assert ctrl_info("camera_orientation") and ctrl("camera_orientation") == 0, \
        "camera_orientation must exist and read 0 (front), from the ACPI _PLD (patch 5)"
    assert ctrl_info("camera_sensor_rotation"), "camera_sensor_rotation must exist (patch 5)"


@pytest.mark.needs_patch("8")
def test_firmware_rotation(graph):
    assert ctrl_info("camera_sensor_rotation") and ctrl("camera_sensor_rotation") == 90, \
        "camera_sensor_rotation must read 90: the sensor is mounted rotated, the ACPI _PLD says 0 (patch 8, ipu-bridge DMI quirk)"


def test_control_events(graph):
    """libcamera subscribes to control events on every sensor it opens; the stock driver refuses (patch 3)."""
    waiter = subprocess.Popen(["v4l2-ctl", "-d", sd(), "--wait-for-event=ctrl=exposure"],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        time.sleep(0.5)
        set_ctrl("exposure", EXPOSURE + 100)
        set_ctrl("exposure", EXPOSURE)
        out, _ = waiter.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        waiter.kill()
        pytest.fail("no control event arrived within 5 s of changing exposure")
    assert waiter.returncode == 0 and "SUBSCRIBE_EVENT: failed" not in out, \
        f"subscribing to the exposure control event failed (patch 3):\n{out.strip()}"


def test_lit_60fps_capture(graph):
    """Steps 3 to 5: 60 fps, emitter on, one second of lit frames with an image in them, then everything off."""
    assert ctrl_info(STROBE), f"{STROBE} missing: without patch 7 the emitter cannot be switched on"
    try:
        set_fps(FPS)
        assert abs(get_fps() - FPS) < 0.02 * FPS, f"frame interval read back {get_fps()} fps, asked {FPS}"  # driver reports the exact rate
        set_ctrl("exposure", EXPOSURE)
        set_ctrl("analogue_gain", GAIN)  # patch 2: the control is ANALOGUE_GAIN, the one libcamera drives

        set_ctrl(STROBE, 0)
        dark, _ = grab(30)
        set_ctrl(STROBE, 1)
        lit, fps = grab(FPS)
        set_ctrl(STROBE, 0)
        mid = lit[FPS // 2]
        to_png(dark[len(dark) // 2], OUT / f"ir-{FPS}fps-emitter-off.png")  # written before the asserts: a failed run
        to_png(mid, OUT / f"ir-{FPS}fps-emitter-on.png")  # still shows what the camera saw

        need_dark(dark.mean())
        assert fps and fps >= 0.9 * FPS, f"streamed at {fps} fps, asked {FPS}: the frame interval must change the frame length (patch 4)"
        dark_mean, lit_mean = dark.mean(), lit.mean()
        assert lit_mean > 2.5 * dark_mean, \
            f"lit mean {lit_mean:.1f} vs dark {dark_mean:.1f}: the emitter must light the scene on every frame (patch 7)"
        per_frame = lit.reshape(FPS, -1).mean(axis=1)
        assert (per_frame > 2.5 * dark_mean).all(), f"some frames unlit: {per_frame.round(0)}"
        p10, p90 = np.percentile(mid, [10, 90])
        assert p90 - p10 > 40, f"lit frame has no texture (p10 {p10:.0f}, p90 {p90:.0f}): not a picture of a scene"
        assert (mid >= 1020).mean() < 0.25, f"{(mid >= 1020).mean():.0%} of the lit frame saturated: a white frame, not a picture"
    finally:
        if ctrl_info(STROBE):
            set_ctrl(STROBE, 0)
        set_fps(30)

    assert wait_for(lambda: runtime_status() == "suspended", 3), \
        f"sensor {runtime_status()} 3 s after the stream stopped: it must power down, taking the emitter with it"
    assert ctrl(STROBE) == 0
