"""Shared helpers for the OV7251 acceptance tests (also imported by later phases: `from conftest import ...`).

Hardware: OV7251 subdev -> "ipu3-csi2 2" -> /dev/video2 ("ipu3-cio2 2"), ip3y 640x480. Runs as the normal user
(ACLs on /dev/media0, the subdev and /dev/video2). Every stream is started by a v4l2-ctl child with a fixed
--stream-count, and killed on timeout, so no stream outlives a test.
"""
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import ip3y  # noqa: E402

CSI = "ipu3-csi2 2"


def _cio2_nodes() -> tuple[str, str]:
    """(/dev/mediaN of ipu3-cio2, /dev/videoN of "ipu3-cio2 2"): numbering differs between kernels (6.18: media0/video2,
    7.2: media1/video12), so resolve them from sysfs by name."""
    for f in Path("/sys/class/video4linux").glob("video*/name"):
        if f.read_text().strip() == CSI.replace("csi2", "cio2"):
            media = next((f.parent / "device").resolve().glob("media*"))
            return f"/dev/{media.name}", f"/dev/{f.parent.name}"
    raise RuntimeError("no 'ipu3-cio2 2' video node")


MEDIA, VIDEO = _cio2_nodes()
W, H = 640, 480
FRAME_BYTES = ip3y.bytesperline(W) * H
RUNTIME_STATUS = Path("/sys/bus/i2c/devices/i2c-INT347E:00/power/runtime_status")
# v4l2-ctl turns a control name into a variable name by lower-casing it and replacing each run of non-alphanumeric
# characters with one '_' (seen here: "Vertical Blanking" -> vertical_blanking, "Analogue Gain" -> analogue_gain), so the
# kernel names in v4l2-ctrls-defs.c give: "Camera Orientation" -> camera_orientation, "Camera Sensor Rotation" ->
# camera_sensor_rotation, "Strobe Output Enable" (V4L2_CID_FLASH_STROBE_OE) -> strobe_output_enable.
STROBE = "strobe_output_enable"
DARK_MAX = 40  # counts at exposure 1704, gain 128: Phase 0 dark ~20, emitter lit ~103
MODE_VTS = {30: 1724, 60: 860, 90: 572}  # frame length in lines of the three 640x480 modes (ov7251_mode_info_data)
INTEGRATION_MARGIN = 20  # OV7251_INTEGRATION_MARGIN: exposure max = VTS - 20
# Sensor registers (OV7251 datasheet, names as in drivers/media/i2c/ov7251.c), read with read_reg() while streaming
SC_REG5, STROBE_PATTERN, STROBE_SPAN, VTS_REG, EXPO_REG, GAIN_REG = 0x3005, 0x3b81, 0x3b8c, 0x380e, 0x3500, 0x350a


def run(*cmd, **kw) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw).stdout


@lru_cache(maxsize=None)
def subdev() -> tuple[str, str] | None:
    """(entity name, /dev/v4l-subdevN) of the OV7251, or None."""
    for f in sorted(Path("/sys/class/video4linux").glob("v4l-subdev*/name")):
        name = f.read_text().strip()
        if name.startswith("ov7251"):
            return name, f"/dev/{f.parent.name}"
    return None


def sd() -> str:
    return subdev()[1]


_CTRL = re.compile(r"^\s*(\w+) 0x([0-9a-f]+) \((\w+)\)\s*: (.*)$")


def parse_ctrls(text: str) -> dict[str, dict]:
    """Parse `v4l2-ctl -l` output into {name: {type, min, max, step, default, value, label, flags}}."""
    out = {}
    for line in text.splitlines():
        m = _CTRL.match(line)
        if not m:
            continue
        name, _id, typ, rest = m.groups()
        rest, _, flags = rest.partition("flags=")
        nums = {k: int(v) for k, v in re.findall(r"(\w+)=(-?\d+)", rest)}
        label = re.search(r"value=-?\d+ \(([^)]*)\)", rest)
        out[name] = {"type": typ, **{k: nums.get(k) for k in ("min", "max", "step", "default", "value")},
                     "label": label and label.group(1), "flags": [f.strip() for f in flags.split(",") if f.strip()]}
    return out


def ctrl_info(name: str) -> dict | None:
    return parse_ctrls(run("v4l2-ctl", "-d", sd(), "-l")).get(name)


def ctrl(name: str) -> int:
    """Current value (menu index for menu controls)."""
    return int(run("v4l2-ctl", "-d", sd(), f"--get-ctrl={name}").split(":", 1)[1].split()[0])


def set_ctrl(name: str, value: int) -> None:
    run("v4l2-ctl", "-d", sd(), f"--set-ctrl={name}={value}")


def get_fps() -> float:
    return float(re.search(r"Frames per second: ([\d.]+)", run("v4l2-ctl", "-d", sd(), "--get-subdev-fps", "pad=0")).group(1))


def set_fps(fps: float) -> None:
    run("v4l2-ctl", "-d", sd(), "--set-subdev-fps", f"pad=0,fps={fps}")


def stream(frames: int, path: str, *, skip: int = 5) -> str:
    """Stream skip+frames frames, write the last `frames` to path, return v4l2-ctl's output ('... 30.00 fps' lines)."""
    return subprocess.run(["v4l2-ctl", "-d", VIDEO, "--stream-mmap", f"--stream-count={frames}", f"--stream-skip={skip}",
                           f"--stream-to={path}"], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          timeout=10 + (frames + skip) / 10).stdout  # >= 10 fps; on timeout the child is killed


def reported_fps(output: str) -> float | None:
    fps = re.findall(r"([\d.]+) fps", output)
    return float(fps[-1]) if fps else None


def capture(frames: int, *, skip: int = 5, fps: float | None = None) -> np.ndarray:
    """(frames, 480, 640) uint16 frames from /dev/video2; restores 30 fps if fps is given."""
    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/frames.raw"
        try:
            if fps:
                set_fps(fps)
            stream(frames, path, skip=skip)
        finally:
            if fps:
                set_fps(30)
        raw = np.fromfile(path, np.uint8)
    assert raw.size == frames * FRAME_BYTES, f"got {raw.size} bytes, expected {frames} frames of {FRAME_BYTES}"
    return np.stack([ip3y.unpack(raw[i:i + FRAME_BYTES], W, H) for i in range(0, raw.size, FRAME_BYTES)])


def frame_means(arr: np.ndarray) -> np.ndarray:
    return arr.reshape(arr.shape[0], -1).mean(axis=1)


def read_reg(addr: int, n: int = 1) -> int:
    """n consecutive sensor registers from addr, big-endian, over I2C (bus 3, 0x60; sudo, -f because the driver owns
    the address). Only meaningful inside streaming(): a suspended sensor is powered off and reads fail or return garbage."""
    val = 0
    for a in range(addr, addr + n):
        out = run("sudo", "-n", "i2ctransfer", "-f", "-y", "3", "w2@0x60", f"0x{a >> 8:02x}", f"0x{a & 0xff:02x}", "r1")
        val = val << 8 | int(out, 16)
    return val


@contextmanager
def streaming(seconds: float = 3):
    """Stream about `seconds` at the current frame rate in a background stream() (fixed frame count, so it always
    ends), enter the block 1 s in, while the sensor is powered and streaming, and wait for the stream to end after it."""
    with ThreadPoolExecutor(1) as ex:
        done = ex.submit(stream, int(seconds * get_fps()), "/dev/null")
        time.sleep(1)
        try:
            assert runtime_status() == "active", f"sensor {runtime_status()} 1 s into a stream"
            yield
        finally:
            done.result()


def runtime_status() -> str:
    return RUNTIME_STATUS.read_text().strip()


def setup_graph() -> str:
    """Enable sensor -> CSI-2 link and set Y10 640x480 on both pads and ip3y on /dev/video2 (idempotent)."""
    ent = subdev()[0]
    run("media-ctl", "-d", MEDIA, "-l", f'"{ent}":0 -> "{CSI}":0 [1]')
    run("media-ctl", "-d", MEDIA, "-V", f'"{ent}":0 [fmt:Y10_1X10/{W}x{H}]')
    run("media-ctl", "-d", MEDIA, "-V", f'"{CSI}":0 [fmt:Y10_1X10/{W}x{H}]')
    run("v4l2-ctl", "-d", VIDEO, f"--set-fmt-video=width={W},height={H},pixelformat=ip3y")
    return ent


@pytest.fixture(scope="session")
def graph():
    if subdev() is None:
        pytest.skip("no ov7251 subdev under /sys/class/video4linux")
    return setup_graph()


def bench_exposure() -> None:
    """Phase 0 bench settings. Needed before each measurement: the driver resets exposure and gain to the mode defaults
    (504, 16) on every active set_fmt and frame-interval change."""
    set_ctrl("exposure", 1704)
    set_ctrl("analogue_gain", 128)


@pytest.fixture(scope="session")
def dark_mean(graph):
    """Mean of 30 frames, emitter off (strobe control absent or 0), exposure 1704, gain 128: the K4 reference."""
    if ctrl_info(STROBE):
        set_ctrl(STROBE, 0)
    bench_exposure()
    return float(frame_means(capture(30)).mean())


def pytest_collection_modifyitems(config, items):
    if os.environ.get("IRCAM_DISRUPTIVE") == "1":
        return
    for item in items:
        m = item.get_closest_marker("disruptive")
        if m:
            why = m.kwargs.get("reason", "suspend / module reload")
            item.add_marker(pytest.mark.skip(reason=f"disruptive ({why}): set IRCAM_DISRUPTIVE=1"))


def wait_for(pred, timeout: float, step: float = 0.1) -> bool:
    end = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > end:
            return False
        time.sleep(step)
    return True
