"""Does the chip's power mode decide whether the clock gates act? The init table runs the sensor in "low power mode"
(0x3c01 = 0x63; the reset value 0xab is "normal mode", datasheet table 7-10). At 30 fps on the v3 driver (every gate
set), in each mode: clear the 0x3017 gates (blc, isp, vfifo), write the recommended whole value, clear the timing
gate; watch the frames, the test pattern and the black level at gain 16 and 1023."""
import json, re, subprocess, sys, tempfile, threading, time
from pathlib import Path
import numpy as np
PROJ = Path("/home/antoine/projects/surface-ir-camera")
sys.path[:0] = [str(PROJ / "tests"), str(PROJ / "tools")]
from conftest import FRAME_BYTES, H, VIDEO, W, STROBE, ctrl_info, ip3y, runtime_status, set_ctrl, set_fps, setup_graph, subdev, wait_for  # noqa: E402
OUT = Path(__file__).resolve().parent / "clkrst_mode.json"
BUS = re.fullmatch(r"ov7251 (\d+)-([0-9a-f]{4})", subdev()[0]).group(1)
DQ = re.compile(r"seq:\s*(\d+) bytesused:\s*(\d+) ts:\s*([\d.]+).*?\((.*?)\)")
LADDER = np.array([1023 * k / 4 for k in (4, 3, 3, 2, 2, 1, 1, 0)])
RESTORE = [(0x3016, 0xf0), (0x3017, 0xf0), (0x3018, 0xf0), (0x301a, 0xf0), (0x301b, 0xf0), (0x301c, 0xf0)]
T60 = [(0x3016, 0x10), (0x3017, 0x00), (0x3018, 0x00), (0x301a, 0x00), (0x301b, 0x00), (0x301c, 0x00)]

def i2c(*args, retries=3):
    for _ in range(retries + 1):
        p = subprocess.run(["sudo", "-n", "i2ctransfer", "-f", "-y", BUS, *args], capture_output=True, text=True)
        if p.returncode == 0:
            return p.stdout.strip()
    raise RuntimeError(f"i2ctransfer {' '.join(args)}: {(p.stderr or p.stdout).strip()[-80:]}")

def poke(addr, val):
    assert addr != 0x3d80, "never touch the OTP program command"
    i2c("w3@0x60", f"0x{addr >> 8:02x}", f"0x{addr & 0xff:02x}", f"0x{val:02x}")
    return f"{addr:04x}={read(addr):02x}"

def read(addr):
    return int(i2c("w2@0x60", f"0x{addr >> 8:02x}", f"0x{addr & 0xff:02x}", "r1"), 16)

def bars(frame):
    m = np.array([frame[:, x + 4:x + 76].mean() for x in range(0, W, 80)])
    return bool(np.abs(m - LADDER).max() < 8)

def stream(nframes, actions, timeout):
    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/f.raw"
        t0, m0 = time.time(), time.monotonic()
        p = subprocess.Popen(["v4l2-ctl", "-d", VIDEO, "--stream-mmap", f"--stream-count={nframes}", "--stream-skip=0", f"--stream-to={path}", "--verbose"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        err, log = [], []
        th = threading.Thread(target=lambda: err.extend(p.stderr.readlines())); th.start()
        for t, fn, label in actions:
            while time.time() - t0 < t:
                time.sleep(0.005)
            try:
                log.append({"t": round(time.time() - t0, 3), "step": label, "r": fn()})
            except Exception as e:  # noqa: BLE001
                log.append({"t": round(time.time() - t0, 3), "step": label, "error": str(e)[:120]})
        try:
            p.wait(timeout=max(0.1, timeout - (time.time() - t0)))
        except subprocess.TimeoutExpired:
            p.kill(); log.append({"t": round(time.time() - t0, 3), "step": "killed"})
        th.join()
        raw = np.fromfile(path, np.uint8)
    dq = [{"seq": int(s), "bytes": int(b), "t": round(float(ts) - m0, 3), "flags": f} for s, b, ts, f in DQ.findall("".join(err))]
    off = 0
    for d in dq:
        if d["bytes"] == FRAME_BYTES and off + FRAME_BYTES <= raw.size:
            fr = ip3y.unpack(raw[off:off + FRAME_BYTES], W, H)
            d["mean"] = float(fr.mean()); d["bars"] = bars(fr)
        off += d["bytes"]
    k = subprocess.run(["journalctl", "-k", "--since", f"@{t0 - 1:.0f}", "-o", "short-unix"], capture_output=True, text=True).stdout
    kern = {}
    for line in k.splitlines():
        m = re.match(r"([\d.]+) \S+ kernel: (.*)", line)
        if m and float(m.group(1)) >= t0 and re.search(r"cio2|csi|ov7251", m.group(2), re.I):
            key = re.sub(r"\d+", "N", re.sub(r"ipu3-cio2 \S+: ", "", m.group(2)))[:60]
            kern[key] = kern.get(key, 0) + 1
    return dq, kern, log

def win(dq, a, b):
    fr = [d for d in dq if a <= d["t"] < b]
    full = [d for d in fr if "mean" in d]
    if not fr:
        return {"n": 0}
    out = {"n": len(fr), "short": sum(1 for d in fr if d["bytes"] != FRAME_BYTES), "err": sum(1 for d in fr if "error" in d["flags"])}
    if len(fr) > 1:
        out["fps"] = round((len(fr) - 1) / (fr[-1]["t"] - fr[0]["t"]), 1)
    if full:
        out["mean"] = round(float(np.mean([d["mean"] for d in full])), 1); out["bars"] = f"{sum(d['bars'] for d in full)}/{len(full)}"
    return out

def run(mode, gates):
    acts = [(0.5, lambda: poke(0x3c01, mode), "mode"),
            (1.5, lambda: [poke(a, v) for a, v in gates], "gates"),
            (2.5, lambda: set_ctrl("test_pattern", 1), "pattern on"),
            (3.5, lambda: set_ctrl("test_pattern", 0), "pattern off"),
            (4.0, lambda: set_ctrl("exposure", 1), "exposure 1"),
            (5.0, lambda: set_ctrl("analogue_gain", 1023), "gain 1023"),
            (6.0, lambda: (set_ctrl("exposure", 504), set_ctrl("analogue_gain", 16)), "restore ctrls"),
            (6.5, lambda: [poke(a, v) for a, v in RESTORE] + [poke(0x3c01, 0x63)], "restore regs")]
    dq, kern, log = stream(210, acts, timeout=11)
    seqs = [d["seq"] for d in dq]
    return {"log": log, "frames": len(dq), "before": win(dq, 0.7, 1.5), "gated": win(dq, 1.7, 2.5), "bars": win(dq, 2.6, 3.5), "after_bars": win(dq, 3.6, 4.0),
            "black16": win(dq, 4.3, 5.0), "black1023": win(dq, 5.3, 6.0), "end": win(dq, 6.6, 7.0), "kern": kern,
            "gaps": [(a, b) for a, b in zip(seqs, seqs[1:]) if b != a + 1][:5], "last_frame_t": dq[-1]["t"] if dq else None}

RUNS = [("lp_control", 0x63, []), ("lp_3017_00", 0x63, [(0x3017, 0x00)]), ("lp_3016_e0", 0x63, [(0x3016, 0xe0)]),
        ("normal_control", 0xab, []), ("normal_3017_00", 0xab, [(0x3017, 0x00)]), ("normal_t60", 0xab, T60), ("normal_3016_e0", 0xab, [(0x3016, 0xe0)])]
results = {}
setup_graph()
assert ctrl_info(STROBE), "strobe control missing (v3 build?)"
try:
    set_ctrl("exposure", 504); set_ctrl("analogue_gain", 16); set_ctrl("test_pattern", 0); set_ctrl(STROBE, 0); set_fps(30)
    for label, mode, gates in RUNS:
        assert wait_for(lambda: runtime_status() == "suspended", 8), "sensor did not suspend"; time.sleep(0.3)
        results[label] = run(mode, gates)
        r = results[label]
        print(label, "frames", r["frames"], "gaps", r["gaps"], "kern", r["kern"], flush=True)
        for w in ("before", "gated", "bars", "after_bars", "black16", "black1023", "end"):
            print(f"   {w:10s} {r[w]}", flush=True)
        print("   log:", [(e["step"], e.get("r", e.get("error"))) for e in r["log"] if e["step"] in ("mode", "gates", "restore regs")], flush=True)
finally:
    set_ctrl("exposure", 504); set_ctrl("analogue_gain", 16); set_ctrl("test_pattern", 0); set_ctrl(STROBE, 0); set_fps(30)
OUT.write_text(json.dumps(results, indent=1))
