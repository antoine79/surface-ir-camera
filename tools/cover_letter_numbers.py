#!/usr/bin/env python3
"""Print every measured number the cover letter quotes, from the live sensor (audit item 4: the letter's figures must come
from a committed log). Run in a dark room with the patched module loaded: tools/cover_letter_numbers.py > docs/cover-letter-numbers-<date>.txt
Leaves the sensor at 30 fps, strobe off, exposure/gain at the driver defaults of the last mode change."""
import platform
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from conftest import (RUNTIME_STATUS, STROBE, capture, ctrl, frame_means, read_reg, reported_fps, run, runtime_status, sd,  # noqa: E402
                      set_ctrl, set_fps, setup_graph, stream, streaming, subdev, wait_for, STROBE_SPAN, DARK_MAX)


def say(k, v):
    print(f"{k}: {v}", flush=True)


def ctrls(dev):
    try:
        return run("v4l2-ctl", "-d", dev, "-L")
    except subprocess.CalledProcessError:
        return run("sudo", "-n", "v4l2-ctl", "-d", dev, "-L")


def placement(dev):
    text = ctrls(dev)
    ori = re.search(r"camera_orientation .*value=\d+ \((\w+)\)", text)
    rot = re.search(r"camera_sensor_rotation .*value=(\d+)", text)
    return (ori and ori.group(1), rot and rot.group(1))


setup_graph()
say("date", date.today().isoformat())
say("kernel", platform.release())
say("module", Path("/sys/module/ov7251/taint").read_text().strip() or "in-tree")
text = ctrls(sd())
idx = ctrl("link_frequency")
say("link_frequency index", idx)
say("link_frequency Hz", re.search(rf"^\s*{idx}: (\d+)", text, re.M).group(1))
say("pixel_rate Hz", ctrl("pixel_rate"))
for fps in (30, 60, 90):
    set_fps(fps)
    say(f"fps measured at {fps}", reported_fps(stream(90, "/dev/null")))
set_fps(30)
p = subprocess.run(["v4l2-compliance", "-u", sd()], capture_output=True, text=True, timeout=300)
set_fps(30)
say("v4l2-compliance -u sensor", re.findall(r"Total for .*", p.stdout)[-1])
say("ov7251 orientation, rotation", placement(sd()))
for f in sorted(Path("/sys/class/video4linux").glob("v4l-subdev*/name")):
    name = f.read_text().strip()
    if name.startswith(("ov5693", "ov8865")):
        say(f"{name} orientation, rotation", placement(f"/dev/{f.parent.name}"))
# strobe span follows exposure, clamped
set_ctrl(STROBE, 1)
for fps, exposure in ((30, 504), (30, 1704), (90, 552)):
    set_fps(fps)
    set_ctrl("exposure", exposure)
    with streaming(2):
        say(f"span at {fps} fps, exposure {exposure}", read_reg(STROBE_SPAN, 4))
set_fps(30)
# brightness, analogue gain 128
set_ctrl("analogue_gain", 128)
for strobe in (0, 1):
    set_ctrl(STROBE, strobe)
    for exposure in (504, 1704):
        set_ctrl("exposure", exposure)
        m = frame_means(capture(30)).mean()
        say(f"mean pixel value, strobe {strobe}, exposure {exposure}, gain 128", f"{m:.0f}")
        if strobe == 0 and exposure == 1704 and m >= DARK_MAX:
            say("WARNING", f"room too bright for the emitter figures ({m:.0f} >= {DARK_MAX})")
set_ctrl(STROBE, 0)
# emitter off and sensor suspended after the stream
set_ctrl(STROBE, 1)
t0 = time.monotonic()
stream(30, "/dev/null")
say("sensor suspended after stream end within s", f"{time.monotonic() - t0:.1f}" if wait_for(lambda: runtime_status() == "suspended", 5) else "NOT within 5")
set_ctrl(STROBE, 0)
say("reload cycles", "see docs/phase3-7.2-test-2026-10-25-k9-reload.log (K9, 10 cycles)")
