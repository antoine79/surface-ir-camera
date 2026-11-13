"""Value matrix for the clock/reset registers 0x3016-0x301c: candidate value sets x frame rates x how written.
Sets (the six registers the mode tables write; 0x3019 left alone):
  none     no write: the driver's own table values for that rate (control run)
  zero     all 0x00                     every gate off, every reset released
  t60      0x3016=0x10, others 0x00     the 60/90 fps table and what the Windows driver writes in all its modes
  gates    the documented gates on, debug and reset bits 0:
           0x3016=0xb0 0x3017=0xd0 0x3018=0x70 0x301a=0x30 0x301b=0xb0 0x301c=0xe0
  f0       all 0xf0                     the 30 fps table
  default  all 0xf0, 0x301c=0xf2        the datasheet reset values: what not writing them at all would leave
Variants: live = written during the stream; standby = 0x0100=0, the set, 0x0100=1 (the sensor restarts on the new
values: the nearest thing to the init table without a driver rebuild). For 'none' the standby variant restarts the
sensor without touching the registers, as a control for the restart itself.
Each run is one cold stream of 7 s (the sensor suspended before it, so the driver rewrites its tables), strobe on
alternate frames, scene, exposure 504, gain 16, test pattern off:
  1.5 s  write the set, read the seven registers back
  2.5 s  exposure 1                               -> black level at gain 16    (window 3.0-3.5 s)
  3.5 s  gain 1023                                -> black level at gain 1023  (window 4.0-4.5 s)
  4.5 s  exposure 504, gain 16, test pattern on   -> bars                      (window 5.0-5.5 s)
  5.5 s  test pattern off                         -> scene again               (window 5.9-6.8 s)
  6.8 s  read the seven registers again
Windows 0.7-1.5 s (before) and 1.8-2.5 s (after) give the frame rate and the lit/dark frame means around the write.
Cold-start mode (clkrst_matrix.py cold <label>): no write at all, so each run measures the loaded driver's own values
from power-on; used with driver variants whose init table carries one of the sets (cold/ builds, 30 Oct 2026).
"""
import hashlib, json, re, subprocess, sys, tempfile, threading, time
from pathlib import Path
import numpy as np
PROJ = Path("/home/antoine/projects/surface-ir-camera")
sys.path[:0] = [str(PROJ / "tests"), str(PROJ / "tools")]
from conftest import FRAME_BYTES, H, VIDEO, W, STROBE, ctrl_info, ip3y, runtime_status, set_ctrl, set_fps, setup_graph, subdev, wait_for  # noqa: E402
OUT = Path(__file__).resolve().parent / "clkrst_matrix.json"
CLKRST = (0x3016, 0x3017, 0x3018, 0x3019, 0x301a, 0x301b, 0x301c)
SIX = (0x3016, 0x3017, 0x3018, 0x301a, 0x301b, 0x301c)
BUS, DEV = re.fullmatch(r"ov7251 (\d+)-([0-9a-f]{4})", subdev()[0]).groups()
SETS = {
    "none": None,
    "zero": dict.fromkeys(SIX, 0x00),
    "t60": {0x3016: 0x10, 0x3017: 0, 0x3018: 0, 0x301a: 0, 0x301b: 0, 0x301c: 0},
    "gates": {0x3016: 0xb0, 0x3017: 0xd0, 0x3018: 0x70, 0x301a: 0x30, 0x301b: 0xb0, 0x301c: 0xe0},
    "f0": dict.fromkeys(SIX, 0xf0),
    "default": {**dict.fromkeys(SIX, 0xf0), 0x301c: 0xf2},
}

def i2c_try(*args):
    p = subprocess.run(["sudo", "-n", "i2ctransfer", "-f", "-y", BUS, *args], capture_output=True, text=True)
    return (p.returncode == 0, p.stdout.strip() if p.returncode == 0 else (p.stderr.strip() or p.stdout.strip())[-80:])

def i2c(*args, retries=0):
    for n in range(retries + 1):
        ok, out = i2c_try(*args)
        if ok:
            return out, n
    raise RuntimeError(f"i2ctransfer {' '.join(args)}: {out}")

def poke(addr, *vals, retries=3):
    assert addr != 0x3d80 and not (addr <= 0x3d80 < addr + len(vals)), "never touch the OTP program command"
    return i2c(f"w{2 + len(vals)}@0x60", f"0x{addr >> 8:02x}", f"0x{addr & 0xff:02x}", *(f"0x{v:02x}" for v in vals), retries=retries)[1]

def read(addr, n=1, retries=3):
    out, tries = i2c("w2@0x60", f"0x{addr >> 8:02x}", f"0x{addr & 0xff:02x}", f"r{n}", retries=retries)
    return [int(x, 16) for x in out.split()], tries

def regs(*addrs):
    return {f"0x{a:04x}": f"{read(a)[0][0]:02x}" for a in addrs}

DQ = re.compile(r"seq:\s*(\d+) bytesused:\s*(\d+) ts:\s*([\d.]+).*?\((.*?)\)")
BARS = [1023 * k / 4 for k in (4, 3, 3, 2, 2, 1, 1, 0)]

def bars_ok(f):
    return bool(np.allclose([f[:, x + 4:x + 76].mean() for x in range(0, 640, 80)], BARS, atol=12))

def vstream(nframes, actions):
    """v4l2-ctl --verbose stream; actions = [(t, fn, label)] at t seconds after the start. Per-frame stats in dq."""
    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/f.raw"
        res, log = {}, {}
        t0, m0 = time.time(), time.monotonic()
        def run():
            p = subprocess.run(["v4l2-ctl", "-d", VIDEO, "--stream-mmap", f"--stream-count={nframes}", "--stream-skip=0", f"--stream-to={path}", "--verbose"],
                               capture_output=True, text=True, timeout=15 + nframes / 10)
            res["err"] = p.stderr
        th = threading.Thread(target=run); th.start()
        for t, fn, label in actions:
            while time.time() - t0 < t:
                time.sleep(0.01)
            try:
                log[label] = {"t": round(time.time() - t0, 3), "r": fn()}
            except Exception as e:  # noqa: BLE001
                log[label] = {"t": round(time.time() - t0, 3), "error": str(e)[:160]}
        th.join()
        raw = np.fromfile(path, np.uint8)
    dq = [{"seq": int(s), "bytes": int(b), "t": round(float(ts) - m0, 3), "flags": f} for s, b, ts, f in DQ.findall(res.get("err", ""))]
    off, prev = 0, None  # the file holds bytesused bytes per dequeued buffer
    for d in dq:
        if d["bytes"] == FRAME_BYTES and off + FRAME_BYTES <= raw.size:
            fb = raw[off:off + FRAME_BYTES]
            f = ip3y.unpack(fb, W, H).astype(np.float32)
            h = hashlib.md5(fb.tobytes()).hexdigest()[:8]
            d.update(mean=float(f.mean()), bars=bars_ok(f), dup=(h == prev))
            prev = h
        off += d["bytes"]
    k = subprocess.run(["journalctl", "-k", "--since", f"@{t0 - 1:.0f}", "-o", "short-unix"], capture_output=True, text=True).stdout
    kern = {}
    for line in k.splitlines():
        m = re.match(r"([\d.]+) \S+ kernel: (.*)", line)
        if m and float(m.group(1)) >= t0 and re.search(r"cio2|csi|ov7251", m.group(2), re.I):
            key = re.sub(r"\d+", "N", re.sub(r"ipu3-cio2 \S+: ", "", m.group(2)))[:60]
            kern[key] = kern.get(key, 0) + 1
    return dq, kern, log

def window(dq, a, b):
    return [d for d in dq if a <= d["t"] < b and "mean" in d]

def fps_of(fr):
    return round((len(fr) - 1) / (fr[-1]["t"] - fr[0]["t"]), 2) if len(fr) > 2 else None

def litdark(fr):
    m = np.array([d["mean"] for d in fr])
    if not len(m):
        return [None, None]
    hi, lo = m[m > np.median(m)], m[m <= np.median(m)]
    return [round(float(hi.mean()), 1) if len(hi) else None, round(float(lo.mean()), 1)]

def run(name, fps, variant):
    vals = SETS[name] or {}
    def write():
        if variant == "standby":
            poke(0x0100, 0x00)
        for a, v in vals.items():
            poke(a, v)
        if variant == "standby":
            poke(0x0100, 0x01)
        return regs(*CLKRST)
    def pattern():
        set_ctrl("exposure", 504); set_ctrl("analogue_gain", 16); set_ctrl("test_pattern", 1)
    acts = [(1.5, write, "write"), (2.5, lambda: set_ctrl("exposure", 1), "exp1"), (3.5, lambda: set_ctrl("analogue_gain", 1023), "gain1023"),
            (4.5, pattern, "pattern"), (5.5, lambda: set_ctrl("test_pattern", 0), "scene"), (6.8, lambda: regs(*CLKRST), "regs_end")]
    dq, kern, log = vstream(int(7 * fps), acts)
    before, after, end = window(dq, 0.7, 1.5), window(dq, 1.8, 2.5), window(dq, 5.9, 6.8)
    b16, b1023, bars = window(dq, 3.0, 3.5), window(dq, 4.0, 4.5), window(dq, 5.0, 5.5)
    seqs = [d["seq"] for d in dq]
    want = {f"0x{a:04x}": f"{v:02x}" for a, v in vals.items()}
    got = log["write"].get("r", {})
    return {"frames": len(dq), "fps_before": fps_of(before), "fps_after": fps_of(after), "fps_end": fps_of(end),
            "litdark_before": litdark(before), "litdark_after": litdark(after), "litdark_end": litdark(end),
            "black16": litdark(b16)[1], "black1023": litdark(b1023)[1], "bars": f"{sum(d['bars'] for d in bars)}/{len(bars)}",
            "gaps": sum(1 for a, b in zip(seqs, seqs[1:]) if b != a + 1), "short": sum(1 for d in dq if d["bytes"] != FRAME_BYTES),
            "errflags": sum(1 for d in dq if "error" in d["flags"]), "dups": sum(1 for d in dq if d.get("dup")),
            "readback_ok": all(got.get(k) == v for k, v in want.items()) if vals else None, "kern": kern, "log": log}

results = json.loads(OUT.read_text()) if OUT.exists() else {}

def record(key, value):
    results[key] = value
    OUT.write_text(json.dumps(results, indent=1))
    print(key, json.dumps({k: v for k, v in value.items() if k != "log"})[:700], flush=True)

def settle():
    assert wait_for(lambda: runtime_status() == "suspended", 5), "sensor did not suspend"
    time.sleep(0.3)

variants = sys.argv[1:] or ["live", "standby"]
setup_graph()
assert ctrl_info(STROBE), "strobe control missing (v3 build?)"
try:
    set_ctrl("exposure", 504); set_ctrl("analogue_gain", 16); set_ctrl("test_pattern", 0); set_ctrl("vertical_flip", 0); set_ctrl(STROBE, 1)
    if variants[0] == "cold":  # python3 clkrst_matrix.py cold <label>: the loaded driver's own values, cold, at the three rates
        for fps in (30, 60, 90):
            set_fps(fps); settle()
            record(f"cold_{variants[1]}_{fps}", run("none", fps, "live"))
        variants = []
    for variant in variants:
        for fps in (30, 60, 90):
            set_fps(fps)
            for name in SETS:
                key = f"{variant}_{fps}_{name}"
                if key in results:
                    continue
                settle()
                record(key, run(name, fps, variant))
finally:
    set_ctrl(STROBE, 0); set_ctrl("test_pattern", 0); set_ctrl("exposure", 504); set_ctrl("analogue_gain", 16); set_fps(30)
print(f"\n{'run':20} {'fps':>6} {'lit/dark after':>15} {'blk16':>6} {'blk1023':>7} {'bars':>6} {'gap':>3} {'err':>3} {'dup':>3} {'rb':>5} kern")
for key, r in results.items():
    ld = r["litdark_after"]
    print(f"{key:20} {str(r['fps_after']):>6} {str(ld[0]):>7}/{str(ld[1]):<7} {str(r['black16']):>6} {str(r['black1023']):>7} {r['bars']:>6} "
          f"{r['gaps']:>3} {r['errflags'] + r['short']:>3} {r['dups']:>3} {str(r['readback_ok']):>5} {sum(r['kern'].values())} {r['log']['write'].get('error', '')[:40]}")
print("done:", OUT)
