"""Follow-ups to clkrst_lab.py (same conventions; results in clkrst_lab2.json next to this file).
  D1  I2C reliability during a stream: back-to-back reads of 0x300a for 3 s, failures counted, per configuration
      (30/60/90 fps, strobe on/off, clock registers poked to the other table's values)
  D2  OTP load at 60 fps, where the mode table clears sclk_otp: one 32-byte burst read, with retries
  D3  the four reset bits that disturbed the stream, instrumented: v4l2-ctl --verbose (sequence numbers, bytesused,
      flags), per-frame mean and hash, receiver errors from the kernel log with their time relative to the stream start
"""
import hashlib, json, re, subprocess, sys, tempfile, threading, time
from pathlib import Path
import numpy as np
PROJ = Path("/home/antoine/projects/surface-ir-camera")
sys.path[:0] = [str(PROJ / "tests"), str(PROJ / "tools")]
from conftest import FRAME_BYTES, H, VIDEO, W, STROBE, ctrl_info, ip3y, runtime_status, set_ctrl, set_fps, setup_graph, subdev, wait_for  # noqa: E402
OUT = Path(__file__).resolve().parent / "clkrst_lab2.json"
CLKRST = (0x3016, 0x3017, 0x3018, 0x3019, 0x301a, 0x301b, 0x301c)
BUS, DEV = re.fullmatch(r"ov7251 (\d+)-([0-9a-f]{4})", subdev()[0]).groups()

def i2c_try(*args):
    p = subprocess.run(["sudo", "-n", "i2ctransfer", "-f", "-y", BUS, *args], capture_output=True, text=True)
    return (p.returncode == 0, p.stdout.strip() if p.returncode == 0 else (p.stderr.strip() or p.stdout.strip())[-80:])

def i2c(*args, retries=0):
    for n in range(retries + 1):
        ok, out = i2c_try(*args)
        if ok:
            return out, n
    raise RuntimeError(f"i2ctransfer {' '.join(args)}: {out}")

def poke(addr, *vals, retries=0):
    assert addr != 0x3d80 and not (addr <= 0x3d80 < addr + len(vals)), "never touch the OTP program command"
    return i2c(f"w{2 + len(vals)}@0x60", f"0x{addr >> 8:02x}", f"0x{addr & 0xff:02x}", *(f"0x{v:02x}" for v in vals), retries=retries)[1]

def read(addr, n=1, retries=0):
    out, tries = i2c(f"w2@0x60", f"0x{addr >> 8:02x}", f"0x{addr & 0xff:02x}", f"r{n}", retries=retries)
    return [int(x, 16) for x in out.split()], tries

def regs(*addrs):
    return {f"0x{a:04x}": f"{read(a, retries=3)[0][0]:02x}" for a in addrs}

DQ = re.compile(r"seq:\s*(\d+) bytesused:\s*(\d+) ts:\s*([\d.]+).*?\((.*?)\)")

def vstream(nframes, actions, keep=None):
    """v4l2-ctl --verbose stream of nframes (no skip); actions = [(t, fn, label)]. Returns (frames, dqbuf list, log)."""
    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/f.raw"
        res, log = {}, {}
        t0, m0 = time.time(), time.monotonic()
        def run():
            p = subprocess.run(["v4l2-ctl", "-d", VIDEO, "--stream-mmap", f"--stream-count={nframes}", "--stream-skip=0", f"--stream-to={path}", "--verbose"],
                               capture_output=True, text=True, timeout=10 + nframes / 10)
            res["err"], res["out"] = p.stderr, p.stdout
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
        if keep:
            Path(keep).write_bytes(raw.tobytes())
    dq = [{"seq": int(s), "bytes": int(b), "t": round(float(ts) - m0, 3), "flags": f} for s, b, ts, f in DQ.findall(res.get("err", ""))]
    k = subprocess.run(["journalctl", "-k", "--since", f"@{t0 - 1:.0f}", "-o", "short-unix"], capture_output=True, text=True).stdout
    kern = []
    for line in k.splitlines():
        m = re.match(r"([\d.]+) \S+ kernel: (.*)", line)
        if m and float(m.group(1)) >= t0 and re.search(r"cio2|csi|ov7251", m.group(2), re.I):
            kern.append((round(float(m.group(1)) - t0, 3), re.sub(r"ipu3-cio2 \S+: ", "", m.group(2))))
    log["kern_n"] = len(kern)
    nfull = raw.size // FRAME_BYTES
    fr = np.stack([ip3y.unpack(raw[i * FRAME_BYTES:(i + 1) * FRAME_BYTES], W, H) for i in range(nfull)]).astype(np.float32) if nfull else np.zeros((0, H, W), np.float32)
    hashes = [hashlib.md5(raw[i * FRAME_BYTES:(i + 1) * FRAME_BYTES].tobytes()).hexdigest()[:8] for i in range(nfull)]
    log["file_frames"], log["file_tail_bytes"] = nfull, int(raw.size - nfull * FRAME_BYTES)
    return fr, hashes, dq, kern, log

def bars_ok(f):
    means = [f[:, x + 4:x + 76].mean() for x in range(0, 640, 80)]
    return bool(np.allclose(means, [1023 * k / 4 for k in (4, 3, 3, 2, 2, 1, 1, 0)], atol=12))

def settle():
    assert wait_for(lambda: runtime_status() == "suspended", 5), "sensor did not suspend"
    time.sleep(0.3)

results = {}
if OUT.exists():
    results = json.loads(OUT.read_text())

def record(key, value):
    results[key] = value
    OUT.write_text(json.dumps(results, indent=1))
    print(key, json.dumps(value)[:1200], flush=True)

# ---------------------------------------------------------------- D1: I2C reliability
TABLE60 = [(0x3016, 0x10), (0x3017, 0x00), (0x3018, 0x00), (0x301a, 0x00), (0x301b, 0x00), (0x301c, 0x00)]
TABLE30 = [(a, 0xf0) for a, _ in TABLE60]
D1 = [("30fps_strobe", 30, 1, []), ("60fps_dark", 60, 0, []), ("60fps_strobe", 60, 1, []),
      ("60fps_strobe_301c_40_srb", 60, 1, [(0x301c, 0x40)]), ("60fps_strobe_301b_80_src", 60, 1, [(0x301b, 0x80)]),
      ("60fps_strobe_all_f0", 60, 1, TABLE30), ("90fps_strobe", 90, 1, []), ("30fps_strobe_60fps_clocks", 30, 1, TABLE60),
      ("30fps_dark", 30, 0, [])]

def exp_i2c(fps, strobe, pokes):
    set_fps(fps); set_ctrl(STROBE, strobe); settle()
    def burst():
        fails, n, t_end = [], 0, time.time() + 3.0
        while time.time() < t_end:
            ok, out = i2c_try("w2@0x60", "0x30", "0x0a", "r1")
            n += 1
            if not ok:
                fails.append((n, round(time.time() - t_burst, 3), out[-50:]))
        return {"reads": n, "fails": len(fails), "fail_list": fails[:12]}
    acts = [(1.0, lambda: [poke(a, v, retries=3) for a, v in pokes] and regs(*CLKRST), "pokes_and_regs")]
    t_burst = None
    def start_burst():
        nonlocal t_burst
        t_burst = time.time()
        return burst()
    acts.append((1.5, start_burst, "burst"))
    fr, hashes, dq, kern, log = vstream(int(5 * fps), acts)
    m = fr.reshape(len(fr), -1).mean(axis=1) if len(fr) else np.zeros(0)
    return {"log": log, "fps_frames": len(dq), "lit": round(float(m[m > np.median(m)].mean()), 1) if len(m) else None,
            "dark": round(float(m[m <= np.median(m)].mean()), 1) if len(m) else None, "kern": kern[:5]}

# ---------------------------------------------------------------- D2: OTP at 60 fps
def otp_load():
    r = {}
    r["clear_tries"] = poke(0x3d00, *([0] * 32), retries=5)
    r["cleared"], _ = read(0x3d00, 4, retries=5)
    r["load_tries"] = poke(0x3d81, 0x01, retries=5)
    time.sleep(0.03)
    try:
        data, r["burst_read_tries"] = read(0x3d00, 32, retries=5)
    except RuntimeError as e:
        r["burst_read_error"] = str(e)[-80:]
        data = []
        for i in range(32):
            data.append(read(0x3d00 + i, retries=5)[0][0])
    r["otp"], r["nonzero"] = "".join(f"{b:02x}" for b in data), sum(1 for b in data if b)
    return r

def exp_otp60(pokes):
    acts = [(1.0, lambda: [poke(a, v, retries=3) for a, v in pokes] and regs(0x3018), "pokes"), (2.0, otp_load, "otp"), (3.5, lambda: regs(0x3018), "regs")]
    fr, hashes, dq, kern, log = vstream(240, acts)
    return {"log": log, "frames": len(dq)}

# ---------------------------------------------------------------- D3: instrumented resets at 30 fps
D3 = [(0x3016, 3, "rst_fc"), (0x3017, 3, "rst_blc"), (0x3017, 2, "rst_isp"), (0x301b, 0, "rst_snr_sync")]

def exp_reset(reg, bit, pattern, keep=None, val=None):
    val = 0xf0 | (1 << bit) if val is None else val
    acts = [(2.0, lambda: poke(reg, val, retries=3), "set"), (4.0, lambda: poke(reg, 0xf0, retries=3), "clear"), (4.5, lambda: regs(reg), "regs")]
    fr, hashes, dq, kern, log = vstream(200, acts, keep)
    means = fr.reshape(len(fr), -1).mean(axis=1) if len(fr) else np.zeros(0)
    # map file frames to dqbuf entries: v4l2-ctl writes bytesused bytes per dequeued buffer
    frames, off = [], 0
    for i, d in enumerate(dq):
        entry = dict(d)
        if d["bytes"] == FRAME_BYTES and off % FRAME_BYTES == 0 and off // FRAME_BYTES < len(fr):
            j = off // FRAME_BYTES
            entry.update(mean=round(float(means[j]), 1), hash=hashes[j], dup=bool(j and hashes[j] == hashes[j - 1]))
            if pattern:
                entry["bars"] = bars_ok(fr[j])
        off += d["bytes"]
        frames.append(entry)
    seqs = [d["seq"] for d in dq]
    gaps = [(a, b) for a, b in zip(seqs, seqs[1:]) if b != a + 1]
    kinds = {}
    for t, msg in kern:
        kinds.setdefault(re.sub(r"\d+", "N", msg)[:60], []).append(t)
    kern_summary = {k: {"n": len(v), "first": v[0], "last": v[-1]} for k, v in kinds.items()}
    return {"log": log, "dq": len(dq), "seq_gaps": gaps[:20], "short_buffers": [(d["seq"], d["bytes"], d["t"]) for d in dq if d["bytes"] != FRAME_BYTES][:20],
            "error_flags": [(d["seq"], d["t"], d["flags"]) for d in dq if "error" in d["flags"]][:20], "kern": kern_summary,
            "frames": frames}

which = sys.argv[1:] or ["D1", "D2", "D3"]
setup_graph()
assert ctrl_info(STROBE), "strobe control missing (v3 build?)"
try:
    set_ctrl("exposure", 504); set_ctrl("analogue_gain", 16); set_ctrl("test_pattern", 0); set_ctrl("vertical_flip", 0)
    if "D1" in which:
        for label, fps, strobe, pokes in D1:
            record(f"D1_{label}", exp_i2c(fps, strobe, pokes))
        set_fps(30); set_ctrl(STROBE, 1)
    if "D2" in which:
        set_fps(60); set_ctrl(STROBE, 1); settle()
        for label, pokes in (("table", []), ("bit4", [(0x3018, 0x10)]), ("all_f0", TABLE30)):
            record(f"D2_otp_60fps_{label}", exp_otp60(pokes)); settle()
        set_fps(30)
    if "D3" in which:
        set_fps(30)
        for pattern in (False, True):
            set_ctrl("test_pattern", int(pattern)); set_ctrl(STROBE, int(not pattern)); settle()
            for reg, bit, name in D3:
                keep = str(OUT.parent / f"d3_{name}_{'pattern' if pattern else 'scene'}.raw") if name in ("rst_blc", "rst_fc") else None
                record(f"D3_{'pattern' if pattern else 'scene'}_{name}", exp_reset(reg, bit, pattern, keep)); settle()
    if "E" in which:  # receiver-path resets and the two unknown values of 0x3019, scene only
        set_fps(30); set_ctrl("test_pattern", 0); set_ctrl(STROBE, 1); settle()
        for reg, bit, name, val in [(0x3016, 0, "rst_tc", None), (0x3017, 0, "rst_vfifo", None), (0x3018, 2, "rst_mipi", None),
                                    (0x3018, 1, "rst_ac", None), (0x301a, 2, "rst_mipi_sc", None), (0x301b, 3, "rst_src", None),
                                    (0x3019, 0, "0x3019_00", 0x00), (0x3019, 0, "0x3019_ff", 0xff)]:
            record(f"E_scene_{name}", exp_reset(reg, bit, False, None, val)); settle()
finally:
    set_ctrl(STROBE, 0); set_ctrl("test_pattern", 0); set_ctrl("exposure", 504); set_ctrl("analogue_gain", 16); set_fps(30)
print("done:", OUT)
