"""Experiments on the OV7251 clock/reset registers 0x3016-0x301c, on the v3 driver at 30 fps (where the mode table
writes 0xf0 to all of them: every clock bit 1, every reset bit 0). Pokes are made over I2C while the sensor streams a
lit scene (emitter on, dark room, strobe pattern 0xaa: alternate frames lit/dark); frames are split into segments
before / during / after each poke. Nothing persists: the driver resets the sensor at the next power-on (1 s after
the stream ends), and the controls are set back at the end. Never writes 0x3d80 (OTP program command).

  A  clock-bit polarity on blocks idle while streaming: OTP read (sclk_otp), group frame counter and group write
     (sclk_grp), black-level re-regulation after a gain change (sclk_blc), strobe clock (sclk_stb per OV9281)
  B  block identity: each 'safe' reset bit set for 2 s mid-stream, scene pass then test-pattern pass
"""
import json, re, subprocess, sys, tempfile, threading, time
from pathlib import Path
import numpy as np
PROJ = Path("/home/antoine/projects/surface-ir-camera")
sys.path[:0] = [str(PROJ / "tests"), str(PROJ / "tools")]
from conftest import (FRAME_BYTES, H, W, STROBE, ctrl_info, ip3y, read_reg, runtime_status, set_ctrl, set_fps,  # noqa: E402
                      setup_graph, stream, subdev, wait_for)
OUT = Path(__file__).resolve().parent / "clkrst_lab.json"
FPS, T_FIRST = 30, 0.45          # frame i is at about T_FIRST + i/FPS after the stream command starts
CLKRST = (0x3016, 0x3017, 0x3018, 0x3019, 0x301a, 0x301b, 0x301c)

def i2c(*args):
    bus, dev = re.fullmatch(r"ov7251 (\d+)-([0-9a-f]{4})", subdev()[0]).groups()
    return subprocess.run(["sudo", "-n", "i2ctransfer", "-f", "-y", bus, *args], check=True, capture_output=True, text=True).stdout

def poke(addr, *vals):
    assert addr != 0x3d80 and not (addr <= 0x3d80 < addr + len(vals)), "never touch the OTP program command"
    i2c(f"w{2 + len(vals)}@0x60", f"0x{addr >> 8:02x}", f"0x{addr & 0xff:02x}", *(f"0x{v:02x}" for v in vals))
    return {f"0x{addr:04x}": [f"{v:02x}" for v in vals]}

def regs(*addrs):
    return {f"0x{a:04x}": f"{read_reg(a):02x}" for a in addrs}

def kernel_lines(t0):
    out = subprocess.run(["journalctl", "-k", "--since", f"@{int(t0)}", "-o", "cat"], capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if re.search(r"cio2|csi|ov7251", l, re.I)]

def run_stream(nframes, actions):
    """actions: list of (t_after_start, callable, label). Returns (frames, log)."""
    with tempfile.TemporaryDirectory() as d:
        path, log, t0 = f"{d}/f.raw", {}, time.time()
        th = threading.Thread(target=lambda: log.update(stream_out=stream(nframes, path, skip=5)))
        th.start()
        for t, fn, label in actions:
            while time.time() - t0 < t:
                time.sleep(0.02)
            try:
                log[label] = {"t": round(time.time() - t0, 2), "r": fn()}
            except Exception as e:  # noqa: BLE001
                log[label] = {"t": round(time.time() - t0, 2), "error": str(e)[:200]}
        th.join()
        raw = np.fromfile(path, np.uint8)
    log["kernel_lines"] = kernel_lines(t0)
    log["fps_reported"] = re.findall(r"([\d.]+) fps", log.pop("stream_out", ""))[-3:]
    fr = np.stack([ip3y.unpack(raw[i:i + FRAME_BYTES], W, H) for i in range(0, raw.size, FRAME_BYTES)]).astype(np.float32)
    return fr, log

def bars_ok(f):
    means = [f[:, x + 4:x + 76].mean() for x in range(0, 640, 80)]
    return bool(np.allclose(means, [1023 * k / 4 for k in (4, 3, 3, 2, 2, 1, 1, 0)], atol=12))

def segment(fr, t_from, t_to, pattern=False):
    i0, i1 = int((t_from - T_FIRST) * FPS), int((t_to - T_FIRST) * FPS)
    s = fr[max(i0, 0):min(i1, len(fr))]
    if not len(s):
        return {"frames": 0}
    m = s.reshape(len(s), -1).mean(axis=1)
    if pattern:
        return {"frames": len(s), "mean": round(float(m.mean()), 1), "bars_ok": int(sum(bars_ok(f) for f in s)), "mean_min_max": [round(float(m.min()), 1), round(float(m.max()), 1)]}
    hi, lo = m[m > np.median(m)], m[m <= np.median(m)]
    return {"frames": len(s), "lit": round(float(hi.mean()), 1) if len(hi) else None, "dark": round(float(lo.mean()), 1),
            "spread": round(float(hi.mean() - lo.mean()), 1) if len(hi) else 0.0}

def settle():
    """Let the sensor power off (autosuspend 1 s): every register is back to the driver's values at the next start."""
    assert wait_for(lambda: runtime_status() == "suspended", 5), "sensor did not suspend"
    time.sleep(0.3)

results = {}

def record(key, value):
    results[key] = value
    OUT.write_text(json.dumps(results, indent=1))
    print(key, json.dumps(value, indent=None)[:1500])

# ---------------------------------------------------------------- A: clock-bit polarity on idle blocks
POKES = {"clk0": (0x3018, 0xe0), "bit4": (0x3018, 0x10), "grp0": (0x301c, 0xd0), "bit5": (0x301c, 0x20)}

def exp_otp(state):
    acts = []
    if state in POKES:
        acts.append((1.0, lambda: (poke(*POKES[state]), regs(POKES[state][0])), f"poke_{state}"))
    def otp_read():
        poke(0x3d00, *([0] * 32))
        cleared = read_reg(0x3d00, 4)
        poke(0x3d81, 0x01)
        time.sleep(0.03)
        data = [read_reg(0x3d00 + i) for i in range(32)]
        return {"buffer_after_clear_first4": f"{cleared:08x}", "otp": "".join(f"{b:02x}" for b in data), "nonzero": sum(1 for b in data if b)}
    acts += [(2.0, otp_read, "otp_read"), (4.0, lambda: regs(0x3018), "regs")]
    fr, log = run_stream(160, acts)
    return {"log": log, "pre": segment(fr, 0.5, 1.5), "post": segment(fr, 4.2, 5.2)}

def exp_group(state):
    acts = []
    if state in POKES:
        acts.append((1.0, lambda: (poke(*POKES[state]), regs(POKES[state][0])), f"poke_{state}"))
    acts += [(1.5, lambda: regs(0x320d, 0x320e, 0x320f), "grp_regs_t1"),
             (2.5, lambda: regs(0x320d, 0x320e, 0x320f), "grp_regs_t2"),
             (3.0, lambda: (poke(0x3208, 0x00), poke(0x3500, 0x00, 0x03, 0x20), poke(0x3208, 0x10), poke(0x3208, 0xa0), regs(0x3500, 0x3501, 0x3502)), "group_write_exposure_50"),
             (4.5, lambda: (poke(0x3500, 0x00, 0x1f, 0x80), regs(0x3500, 0x3501, 0x3502, 0x320d, 0x320e)), "direct_restore_504")]
    fr, log = run_stream(200, acts)
    return {"log": log, "pre": segment(fr, 0.5, 1.5), "after_group_launch": segment(fr, 3.6, 4.4), "after_restore": segment(fr, 5.1, 6.1)}

def exp_blc(state):
    acts = []
    if state == "clk0":
        acts.append((1.0, lambda: (poke(0x3017, 0x70), regs(0x3017)), "poke_sclk_blc_0"))
    acts += [(2.5, lambda: (poke(0x350a, 0x00, 0x40), regs(0x350a, 0x350b)), "gain_64"),
             (4.5, lambda: (poke(0x350a, 0x00, 0x10), regs(0x350a, 0x350b)), "gain_16")]
    fr, log = run_stream(200, acts)
    return {"log": log, "pre": segment(fr, 0.5, 1.5), "gain64": segment(fr, 3.1, 4.1), "back16": segment(fr, 5.1, 6.1)}

def exp_strobe_clock():
    acts = [(2.0, lambda: (poke(0x3016, 0xb0), regs(0x3016)), "poke_sclk_stb_0"), (4.0, lambda: (poke(0x3016, 0xf0), regs(0x3016)), "restore")]
    fr, log = run_stream(200, acts)
    return {"log": log, "pre": segment(fr, 0.5, 1.5), "during": segment(fr, 2.6, 3.6), "post": segment(fr, 4.6, 5.6)}

# ---------------------------------------------------------------- B: reset bits
SAFE_RESETS = [(0x3016, 3, "rst_fc"), (0x3016, 2, "debug bit (OV9281: rst_stb, strobe)"), (0x3016, 1, "rst_aec"),
               (0x3017, 3, "rst_blc"), (0x3017, 2, "rst_isp"), (0x3017, 1, "debug bit (OV9281: rst_psv_ctrl)"),
               (0x3018, 3, "debug bit (OV9281: rst_dvp)"), (0x3018, 0, "rst_otp"),
               (0x301b, 1, "rst_asram_tst"), (0x301b, 0, "rst_snr_sync"), (0x301c, 3, "rst_bist"), (0x301c, 1, "rst_grp")]
PROBE = (0x3500, 0x3501, 0x3502, 0x350a, 0x350b, 0x5e00, 0x4009, 0x3005, 0x3b81, 0x0100)

def exp_reset(reg, bit, pattern):
    acts = [(1.8, lambda: regs(*PROBE), "probe_before"),
            (2.0, lambda: (poke(reg, 0xf0 | (1 << bit)), regs(reg)), "set"),
            (3.5, lambda: regs(*PROBE), "probe_during"),
            (4.0, lambda: (poke(reg, 0xf0), regs(reg)), "clear"),
            (4.3, lambda: regs(*PROBE), "probe_after")]
    fr, log = run_stream(200, acts)
    return {"log": log, "frames": len(fr), "pre": segment(fr, 0.5, 1.5, pattern), "during": segment(fr, 2.6, 3.6, pattern), "post": segment(fr, 4.8, 5.8, pattern)}

# ---------------------------------------------------------------- main
which = sys.argv[1:] or ["A", "B"]
if OUT.exists():
    results = json.loads(OUT.read_text())
setup_graph()
assert ctrl_info(STROBE), "strobe control missing (v3 build?)"
try:
    set_fps(FPS); set_ctrl("exposure", 504); set_ctrl("analogue_gain", 16); set_ctrl("test_pattern", 0); set_ctrl("vertical_flip", 0); set_ctrl(STROBE, 1)
    settle()
    if "A" in which:
        fr, log = run_stream(60, [(1.0, lambda: regs(*CLKRST), "clkrst_at_30fps")])
        record("A0_state", {"log": log, "scene": segment(fr, 0.5, 1.5)}); settle()
        for state in ("clk1", "clk0"):
            record(f"A1_otp_{state}", exp_otp(state)); settle()
        for state in ("clk1", "grp0"):
            record(f"A2_group_{state}", exp_group(state)); settle()
        for state in ("clk1", "clk0"):
            record(f"A3_blc_{state}", exp_blc(state)); settle()
        record("A4_strobe_clock", exp_strobe_clock()); settle()
    if "B" in which:
        for pattern in (False, True):
            set_ctrl("test_pattern", int(pattern)); set_ctrl(STROBE, int(not pattern))
            for reg, bit, name in SAFE_RESETS:
                record(f"B_{'pattern' if pattern else 'scene'}_0x{reg:04x}_bit{bit}_{name.split()[0]}", {"name": name, **exp_reset(reg, bit, pattern)}); settle()
    if "C" in which:  # 60 fps: the mode table writes 0x3018 = 0x00 and 0x301c = 0x00 (sclk_otp and sclk_grp clear)
        set_ctrl("test_pattern", 0); set_ctrl(STROBE, 1); set_fps(60); FPS = 60; settle()
        fr, log = run_stream(60, [(1.0, lambda: regs(*CLKRST), "clkrst_at_60fps")])
        record("C0_state", {"log": log, "scene": segment(fr, 0.5, 1.5)}); settle()
        for state in ("table", "bit4"):
            record(f"C1_otp_60fps_{state}", exp_otp(state)); settle()
        for state in ("table", "bit5"):
            record(f"C2_group_60fps_{state}", exp_group(state)); settle()
        set_fps(30); FPS = 30
finally:
    set_ctrl(STROBE, 0); set_ctrl("test_pattern", 0); set_ctrl("exposure", 504); set_ctrl("analogue_gain", 16)
print("done:", OUT)
