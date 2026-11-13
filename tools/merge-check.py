"""Behaviour checks for the table merge (v3 patch 7), run on the v2 module then the v3 module and diffed.

Usage: python3 tools/merge-check.py <label>   -> prints a summary and writes <label>.json next to this file.
"Warm" steps pin the sensor powered (power/control = on) so stream restarts and mode switches happen on a sensor in
software standby, without the power cycle that rewrites the init table; "cold" steps wait for the runtime suspend.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PROJ = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJ / "tests"), str(PROJ / "tools")]
from conftest import (RUNTIME_STATUS, capture, ctrl_info, frame_means, read_reg, reported_fps,  # noqa: E402
                      restore_30fps_vblank, runtime_status, set_ctrl, set_fps, setup_graph, stream, streaming)

STROBE = "strobe_output_enable"
PM = RUNTIME_STATUS.parent
REGS = {"clk": (0x3016, 6), "0x3019": (0x3019, 1), "0x301c": (0x301c, 1), "vts": (0x380e, 2), "hts": (0x380c, 2), "0x3820": (0x3820, 1),
        "0x3821": (0x3821, 1), "0x3005": (0x3005, 1), "0x3b81": (0x3b81, 1), "span": (0x3b8c, 4), "pll1": (0x30b0, 6),
        "0x3106": (0x3106, 1), "0x3023": (0x3023, 1), "0x0100": (0x0100, 1)}
out = {}


def pm_control(value: str) -> None:
    subprocess.run(["sudo", "-n", "tee", str(PM / "control")], input=value, text=True, check=True, capture_output=True)


def suspended_ms() -> int:
    return int((PM / "runtime_suspended_time").read_text())


def regs() -> dict:
    return {k: f"{read_reg(a, n):0{2 * n}x}" for k, (a, n) in REGS.items()}


def bars_ok(frames: np.ndarray) -> bool:
    means = [frames[0][:, x + 4:x + 76].mean() for x in range(0, 640, 80)]
    return bool((frames == frames[0]).all() and np.allclose(means, [1023 * k / 4 for k in (4, 3, 3, 2, 2, 1, 1, 0)]))


def bench() -> None:
    set_ctrl("exposure", 1704)
    set_ctrl("analogue_gain", 128)


def ctrls(*names) -> dict:
    return {n: ctrl_info(n)["value"] for n in names if ctrl_info(n)}


setup_graph()
try:
    restore_30fps_vblank()
    if ctrl_info(STROBE):
        set_ctrl(STROBE, 0)
    set_ctrl("vertical_flip", 0)
    set_ctrl("horizontal_flip", 0)
    set_ctrl("test_pattern", 0)
    out["module"] = sys.argv[1]
    out["ctrls"] = ctrls("exposure", "analogue_gain", "vertical_blanking", "vertical_flip", STROBE)

    # 1. Registers while streaming, cold start (sensor powered off before each: init table rewritten) at 30/60/90 fps
    cold = {}
    for fps in (30, 60, 90):
        set_fps(fps)
        time.sleep(2.5)
        assert runtime_status() == "suspended"
        with streaming(6):
            cold[fps] = regs()
    out["cold"] = cold
    restore_30fps_vblank()

    # 2. Black level and 0x3820, vflip 0 and 1, exposure 1: scene-independent (daylight at 1 line of exposure is ~0)
    bl = {}
    for vflip in (0, 1):
        set_ctrl("vertical_flip", vflip)
        for gain in (16, 1023):
            set_ctrl("exposure", 1)
            set_ctrl("analogue_gain", gain)
            time.sleep(2.5)
            f = capture(10).astype(float)
            with streaming(2):
                r3820 = f"{read_reg(0x3820):02x}"
            bl[f"vflip{vflip}_gain{gain}"] = {"mean": round(float(f.mean()), 2), "top8": round(float(f[:, :8].mean()), 2),
                                              "bottom8": round(float(f[:, -8:].mean()), 2), "0x3820": r3820,
                                              "p99": float(np.percentile(f, 99))}
        set_ctrl("test_pattern", 1)
        time.sleep(2.5)
        bl[f"vflip{vflip}_bars"] = bars_ok(capture(3))
        set_ctrl("test_pattern", 0)
    set_ctrl("vertical_flip", 0)
    out["black"] = bl

    # 3. Scene mean at the K4 bench settings (daylight-dependent, for the record only)
    bench()
    time.sleep(2.5)
    out["bench_mean"] = round(float(frame_means(capture(30)).mean()), 1)

    # 4. Warm restart: sensor pinned on, so the second stream starts on a sensor in software standby
    time.sleep(2.5)
    pm_control("on")
    time.sleep(0.5)
    w = {"status_pinned": runtime_status()}
    set_ctrl("test_pattern", 1)
    s0 = suspended_ms()
    a = capture(10, skip=0)
    b = capture(10, skip=0)
    w.update(bars_first=bars_ok(a), bars_second=bars_ok(b), second_first_frame_ok=bars_ok(b[:1]))
    set_ctrl("test_pattern", 0)
    bench()
    a = frame_means(capture(10, skip=0))
    b = frame_means(capture(10, skip=0))
    w["scene_means"] = [round(float(a.mean()), 1), round(float(b.mean()), 1)]
    w["second_first_frames"] = [round(float(x), 1) for x in b[:3]]
    with streaming(6):
        w["regs_after_restart"] = regs()
    w["suspended_during"] = suspended_ms() != s0
    out["warm_restart"] = w

    # 5. Warm mode switch: 30 -> 90 -> 60 -> 30 fps on the pinned sensor, test pattern on, fps measured
    set_ctrl("test_pattern", 1)
    sw = []
    s0 = suspended_ms()
    stream(10, "/dev/null", skip=0)
    for fps in (90, 60, 30):
        set_fps(fps)
        o = stream(3 * fps, "/dev/null", skip=0)
        with streaming(6):
            r = regs()
        f = capture(3, skip=0)
        sw.append({"fps": fps, "measured": reported_fps(o), "clk": r["clk"], "vts": r["vts"], "pll1": r["pll1"],
                   "bars": bars_ok(f)})
    out["warm_switch"] = {"suspended_during": suspended_ms() != s0, "steps": sw}
    set_ctrl("test_pattern", 0)
    restore_30fps_vblank()

    # 6. Strobe on: registers while streaming, warm (pinned) then cold
    if ctrl_info(STROBE):
        bench()
        set_ctrl(STROBE, 1)
        s0 = suspended_ms()
        stream(10, "/dev/null", skip=0)
        with streaming(6):
            warm_on = regs()
        warm_susp = suspended_ms() != s0
        pm_control("auto")
        time.sleep(2.5)
        assert runtime_status() == "suspended"
        with streaming(6):
            cold_on = regs()
        out["strobe_on"] = {"warm": warm_on, "warm_suspended": warm_susp, "cold": cold_on}
        set_ctrl(STROBE, 0)
    else:
        pm_control("auto")

    time.sleep(2.5)
    out["idle_status"] = runtime_status()
    out["final_ctrls"] = ctrls("exposure", "analogue_gain", "vertical_blanking", STROBE)
finally:
    pm_control("auto")
    set_ctrl("test_pattern", 0)
    set_ctrl("vertical_flip", 0)
    if ctrl_info(STROBE):
        set_ctrl(STROBE, 0)
    restore_30fps_vblank()
    bench()
(HERE / f"{sys.argv[1]}.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
