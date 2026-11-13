"""0x3016 bit 4 (sclk_tc) isolated, after clkrst_matrix.py stalled every stream on the all-zero set: write 0x3016 alone,
the other five registers untouched, restore it 2 s later; frames counted before, during and after (lit/dark split at
the midpoint between the darkest and brightest frame). The stream is read through a pipe so a stall loses nothing."""
import json, re, subprocess, sys, tempfile, threading, time
from pathlib import Path
import numpy as np
PROJ = Path("/home/antoine/projects/surface-ir-camera")
sys.path[:0] = [str(PROJ / "tests"), str(PROJ / "tools")]
from conftest import FRAME_BYTES, H, VIDEO, W, STROBE, ctrl_info, ip3y, runtime_status, set_ctrl, set_fps, setup_graph, subdev, wait_for  # noqa: E402
OUT = Path(__file__).resolve().parent / "clkrst_tc.json"
BUS = re.fullmatch(r"ov7251 (\d+)-([0-9a-f]{4})", subdev()[0]).group(1)
DQ = re.compile(r"seq:\s*(\d+) bytesused:\s*(\d+) ts:\s*([\d.]+).*?\((.*?)\)")

def i2c(*args, retries=3):
    for _ in range(retries + 1):
        p = subprocess.run(["sudo", "-n", "i2ctransfer", "-f", "-y", BUS, *args], capture_output=True, text=True)
        if p.returncode == 0:
            return p.stdout.strip()
    raise RuntimeError(f"i2ctransfer {' '.join(args)}: {(p.stderr or p.stdout).strip()[-80:]}")

def poke(addr, val):
    assert addr != 0x3d80, "never touch the OTP program command"
    i2c("w3@0x60", f"0x{addr >> 8:02x}", f"0x{addr & 0xff:02x}", f"0x{val:02x}")

def read(addr):
    return int(i2c("w2@0x60", f"0x{addr >> 8:02x}", f"0x{addr & 0xff:02x}", "r1"), 16)

def stream(nframes, actions, timeout):
    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/f.raw"
        t0, m0 = time.time(), time.monotonic()
        p = subprocess.Popen(["v4l2-ctl", "-d", VIDEO, "--stream-mmap", f"--stream-count={nframes}", "--stream-skip=0", f"--stream-to={path}", "--verbose"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        err, log = [], {}
        th = threading.Thread(target=lambda: err.extend(p.stderr.readlines())); th.start()
        for t, fn, label in actions:
            while time.time() - t0 < t:
                time.sleep(0.01)
            try:
                log[label] = {"t": round(time.time() - t0, 3), "r": fn()}
            except Exception as e:  # noqa: BLE001
                log[label] = {"t": round(time.time() - t0, 3), "error": str(e)[:120]}
        try:
            p.wait(timeout=max(0.1, timeout - (time.time() - t0)))
        except subprocess.TimeoutExpired:
            p.kill(); log["killed_at"] = round(time.time() - t0, 3)
        th.join()
        raw = np.fromfile(path, np.uint8)
    dq = [{"seq": int(s), "bytes": int(b), "t": round(float(ts) - m0, 3), "flags": f} for s, b, ts, f in DQ.findall("".join(err))]
    off = 0
    for d in dq:
        if d["bytes"] == FRAME_BYTES and off + FRAME_BYTES <= raw.size:
            d["mean"] = float(ip3y.unpack(raw[off:off + FRAME_BYTES], W, H).mean())
        off += d["bytes"]
    k = subprocess.run(["journalctl", "-k", "--since", f"@{t0 - 1:.0f}", "-o", "short-unix"], capture_output=True, text=True).stdout
    kern = {}
    for line in k.splitlines():
        m = re.match(r"([\d.]+) \S+ kernel: (.*)", line)
        if m and float(m.group(1)) >= t0 and re.search(r"cio2|csi|ov7251", m.group(2), re.I):
            key = re.sub(r"\d+", "N", re.sub(r"ipu3-cio2 \S+: ", "", m.group(2)))[:60]
            kern[key] = kern.get(key, 0) + 1
    return dq, kern, log

def summary(dq, a, b):
    fr = [d for d in dq if a <= d["t"] < b and "mean" in d]
    if len(fr) < 2:
        return {"n": len(fr)}
    m = np.array([d["mean"] for d in fr]); mid = (m.min() + m.max()) / 2
    lit, dark = m[m > mid], m[m <= mid]
    return {"n": len(fr), "fps": round((len(fr) - 1) / (fr[-1]["t"] - fr[0]["t"]), 2), "lit": round(float(lit.mean()), 1) if len(lit) else None,
            "dark": round(float(dark.mean()), 1), "seq": [fr[0]["seq"], fr[-1]["seq"]]}

def run(fps, val, restore):
    acts = [(1.5, lambda: (poke(0x3016, val), f"{read(0x3016):02x}")[1], "set"), (3.5, lambda: (poke(0x3016, restore), f"{read(0x3016):02x}")[1], "restore")]
    dq, kern, log = stream(int(6 * fps), acts, timeout=12)
    seqs = [d["seq"] for d in dq]
    return {"log": log, "frames": len(dq), "before": summary(dq, 0.7, 1.5), "during": summary(dq, 1.6, 3.5), "after": summary(dq, 3.7, 9.0),
            "last_frame_t": dq[-1]["t"] if dq else None, "gaps": [(a, b) for a, b in zip(seqs, seqs[1:]) if b != a + 1][:5], "kern": kern,
            "errflags": sum(1 for d in dq if "error" in d["flags"]), "short": sum(1 for d in dq if d["bytes"] != FRAME_BYTES)}

results = {}
setup_graph()
assert ctrl_info(STROBE), "strobe control missing (v3 build?)"
try:
    set_ctrl("exposure", 504); set_ctrl("analogue_gain", 16); set_ctrl("test_pattern", 0); set_ctrl(STROBE, 1)
    for fps, val, restore, label in [(30, 0x00, 0xf0, "30fps_3016_00"), (30, 0xe0, 0xf0, "30fps_3016_e0"), (30, 0x10, 0xf0, "30fps_3016_10"), (60, 0x00, 0x10, "60fps_3016_00")]:
        set_fps(fps); assert wait_for(lambda: runtime_status() == "suspended", 5), "sensor did not suspend"; time.sleep(0.3)
        results[label] = run(fps, val, restore)
        print(label, json.dumps(results[label]), flush=True)
finally:
    set_ctrl(STROBE, 0); set_fps(30)
OUT.write_text(json.dumps(results, indent=1))
