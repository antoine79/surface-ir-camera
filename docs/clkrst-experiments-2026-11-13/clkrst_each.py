"""Clear each named clock-gate bit of 0x3016-0x301c one at a time while the OV7251 streams at 30 fps on the v3 driver
(mode table: 0xf0 in all six registers). Emitter off. Per gate, one 4 s stream: poke the bit clear at 0.9 s, raise the
analogue gain 16 -> 128 at 1.5 s and back at 2.1 s (does the gain path still answer?), test pattern on 2.4-3.0 s (bars
still exact?), restore 0xf0 at 3.3 s. Frames before / cleared / gain / bars / restored are split by time (frame i is at
about T_FIRST + i/30 s). A stall shows as fewer frames than requested. Nothing persists: the next power-on resets the
sensor. Never writes 0x3d80 (OTP program command). Output: clkrst_each.json next to this file.

Run from the project root:  uv run --python 3.13 --with numpy --with pytest python3 docs/clkrst-experiments-2026-11-13/clkrst_each.py
"""
import json, re, subprocess, sys, tempfile, threading, time
from pathlib import Path
import numpy as np
PROJ = Path("/home/antoine/projects/surface-ir-camera")
sys.path[:0] = [str(PROJ / "tests"), str(PROJ / "tools")]
from conftest import (FRAME_BYTES, H, W, VIDEO, STROBE, ctrl, ip3y, read_reg, runtime_status, set_ctrl, set_fps,  # noqa: E402
                      setup_graph, subdev, wait_for)
OUT = Path(__file__).resolve().parent / "clkrst_each.json"
FPS, T_FIRST, NFRAMES, SKIP = 30, 0.45, 110, 5
TABLE = 0xf0  # what the 30 fps mode table writes to all six registers
GATES = [(0x3016, 7, "sclk_fc"), (0x3016, 5, "sclk_aec"), (0x3016, 4, "sclk_tc"),
         (0x3017, 7, "sclk_blc"), (0x3017, 6, "sclk_isp"), (0x3017, 4, "sclk_vfifo"),
         (0x3018, 6, "sclk_mipi"), (0x3018, 5, "sclk_ac"), (0x3018, 4, "sclk_otp"),
         (0x301a, 5, "pclk_vfifo"), (0x301a, 4, "pclk_mipi"),
         (0x301b, 7, "sclk_src"), (0x301b, 5, "sclk_asram_tst"), (0x301b, 4, "sclk_snr_sync"),
         (0x301c, 7, "sclk_bist"), (0x301c, 6, "sclk_srb"), (0x301c, 5, "sclk_grp")]

def poke(addr, val):
    assert addr != 0x3d80, "never touch the OTP program command"
    bus = re.fullmatch(r"ov7251 (\d+)-([0-9a-f]{4})", subdev()[0]).group(1)
    subprocess.run(["sudo", "-n", "i2ctransfer", "-f", "-y", bus, "w3@0x60", f"0x{addr >> 8:02x}", f"0x{addr & 0xff:02x}",
                    f"0x{val:02x}"], check=True, capture_output=True, text=True)
    return f"{read_reg(addr):02x}"

def kernel_lines(t0):
    out = subprocess.run(["journalctl", "-k", "--since", f"@{int(t0)}", "-o", "cat"], capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if re.search(r"cio2|csi|ov7251", l, re.I)]

def stream_bounded(path, timeout=9.0):
    cmd = ["v4l2-ctl", "-d", VIDEO, "--stream-mmap", f"--stream-count={NFRAMES}", f"--stream-skip={SKIP}", f"--stream-to={path}"]
    try:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout).stdout
    except subprocess.TimeoutExpired as e:
        return (e.stdout or b"").decode(errors="replace") + "\nTIMEOUT (killed)"

def run_gate(reg, bit, name):
    actions = [(0.9, lambda: poke(reg, TABLE & ~(1 << bit)), "poke_clear"),
               (1.5, lambda: set_ctrl("analogue_gain", 128), "gain128"),
               (2.1, lambda: set_ctrl("analogue_gain", 16), "gain16"),
               (2.4, lambda: set_ctrl("test_pattern", 1), "bars_on"),
               (3.0, lambda: set_ctrl("test_pattern", 0), "bars_off"),
               (3.3, lambda: poke(reg, TABLE), "poke_restore")]
    with tempfile.TemporaryDirectory() as d:
        path, log, t0 = f"{d}/f.raw", {}, time.time()
        th = threading.Thread(target=lambda: log.update(stream_out=stream_bounded(path)))
        th.start()
        for t, fn, label in actions:
            while time.time() - t0 < t:
                time.sleep(0.02)
            try:
                log[label] = fn()
            except Exception as e:  # noqa: BLE001
                log[label] = f"error: {str(e)[:120]}"
        th.join()
        raw = np.fromfile(path, np.uint8) if Path(path).exists() else np.zeros(0, np.uint8)
    out = log.pop("stream_out", "")
    n = raw.size // FRAME_BYTES
    fr = np.stack([ip3y.unpack(raw[i * FRAME_BYTES:(i + 1) * FRAME_BYTES], W, H) for i in range(n)]).astype(np.float32) if n else None
    def seg(a, b):
        i, j = int((a - T_FIRST) * FPS), int((b - T_FIRST) * FPS)
        return fr[max(i, 0):min(j, n)] if fr is not None and min(j, n) > max(i, 0) else None
    def mean(a, b):
        s = seg(a, b)
        return round(float(s.mean()), 1) if s is not None else None
    def bars(a, b):
        s = seg(a, b)
        if s is None:
            return None
        ok = 0
        for f in s:
            m = [f[:, x + 4:x + 76].mean() for x in range(0, 640, 80)]
            ok += bool(np.allclose(m, [1023 * k / 4 for k in (4, 3, 3, 2, 2, 1, 1, 0)], atol=12))
        return f"{ok}/{len(s)}"
    r = {"gate": name, "reg": f"0x{reg:04x}", "bit": bit, "frames": n, "requested": NFRAMES,
         "fps_reported": re.findall(r"([\d.]+) fps", out)[-2:], "timeout": "TIMEOUT" in out,
         "mean_before": mean(0.5, 0.85), "mean_cleared": mean(1.0, 1.45), "mean_gain128": mean(1.7, 2.05),
         "bars_cleared": bars(2.6, 2.95), "mean_restored": mean(3.5, 4.0),
         "readback_cleared": log.get("poke_clear"), "readback_restored": log.get("poke_restore"),
         "ctrl_errors": {k: v for k, v in log.items() if isinstance(v, str) and v.startswith("error")},
         "kernel": kernel_lines(t0)}
    return r

def main():
    assert runtime_status() == "suspended", "sensor busy: stop the bridge or other users first"
    setup_graph()
    results, t_start = [], time.time()
    for reg, bit, name in GATES:
        if not wait_for(lambda: runtime_status() == "suspended", 6):
            results.append({"gate": name, "error": "sensor did not suspend before the run"}); continue
        # a short stream powers the sensor so the controls can be set from a known state
        set_fps(30); set_ctrl(STROBE, 0); set_ctrl("analogue_gain", 16); set_ctrl("exposure", 504); set_ctrl("test_pattern", 0)
        r = run_gate(reg, bit, name)
        results.append(r)
        print(f"{name:15s} {r['reg']} b{r['bit']}  n={r['frames']:3d}{'*' if r['timeout'] else ' '} fps={r['fps_reported'][-1:] or '-'}"
              f"  mean before/cleared/gain128/restored={r['mean_before']}/{r['mean_cleared']}/{r['mean_gain128']}/{r['mean_restored']}"
              f"  bars={r['bars_cleared']}  rb={r['readback_cleared']}->{r['readback_restored']}  kern={len(r['kernel'])}"
              f"  {r['ctrl_errors'] or ''}", flush=True)
    set_ctrl("test_pattern", 0); set_ctrl("analogue_gain", 16); set_ctrl("exposure", 504); set_ctrl(STROBE, 0)
    OUT.write_text(json.dumps({"date": time.strftime("%Y-%m-%d %H:%M %Z"), "kernel": Path("/proc/version").read_text().split()[2],
                               "duration_s": round(time.time() - t_start), "results": results}, indent=1))
    print("saved", OUT)

if __name__ == "__main__":
    main()
