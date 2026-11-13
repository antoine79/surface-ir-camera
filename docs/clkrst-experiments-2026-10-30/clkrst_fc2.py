"""0x3016 bit 7 (sclk_fc): the frame control block (datasheet 7.13, 0x4240-0x4244) owns a read-only frame counter,
0x4244. Read it 1 s apart with the gate set, with the gate cleared (0x3016 = 0x70), with the gate set again, and with
the block held in reset (0x3016 = 0xf8, bit 3): a block whose clock is stopped cannot count. 30 fps, strobe off."""
import json, re, subprocess, sys, threading, time
from pathlib import Path
PROJ = Path("/home/antoine/projects/surface-ir-camera")
sys.path[:0] = [str(PROJ / "tests"), str(PROJ / "tools")]
from conftest import FRAME_BYTES, VIDEO, STROBE, ctrl_info, runtime_status, set_ctrl, set_fps, setup_graph, subdev, wait_for  # noqa: E402
OUT = Path(__file__).resolve().parent / "clkrst_fc2.json"
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
    return read(addr)

def read(addr):
    return int(i2c("w2@0x60", f"0x{addr >> 8:02x}", f"0x{addr & 0xff:02x}", "r1"), 16)

def stream(nframes, actions, timeout):
    t0, m0 = time.time(), time.monotonic()
    p = subprocess.Popen(["v4l2-ctl", "-d", VIDEO, "--stream-mmap", f"--stream-count={nframes}", "--stream-skip=0", "--stream-to=/dev/null", "--verbose"],
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
    dq = [{"seq": int(s), "t": round(float(ts) - m0, 3), "short": int(b) != FRAME_BYTES, "err": "error" in f} for s, b, ts, f in DQ.findall("".join(err))]
    return dq, log

def frames_between(dq, a, b):
    return sum(1 for d in dq if a <= d["t"] < b)

# does any frame-control configuration make the counter run? frame on/off numbers, mask disable, eof select
acts = [(1.0, lambda: read(0x4244), "default:a"), (1.5, lambda: read(0x4244), "default:b"),
        (2.0, lambda: poke(0x4241, 0x0f), "write 0x4241=0x0f (frame on number 15)"),
        (2.5, lambda: read(0x4244), "on15:a"), (3.5, lambda: read(0x4244), "on15:b"),
        (4.0, lambda: poke(0x4242, 0x01), "write 0x4242=0x01 (frame off number 1)"),
        (4.5, lambda: read(0x4244), "on15off1:a"), (5.5, lambda: read(0x4244), "on15off1:b"),
        (6.0, lambda: poke(0x4240, 0x02), "write 0x4240=0x02 (fcnt_mask_dis)"),
        (6.5, lambda: read(0x4244), "maskdis:a"), (7.5, lambda: read(0x4244), "maskdis:b"),
        (8.0, lambda: poke(0x4240, 0x06), "write 0x4240=0x06 (+fcnt_eof_sel)"),
        (8.5, lambda: read(0x4244), "eofsel:a"), (9.5, lambda: read(0x4244), "eofsel:b"),
        (10.0, lambda: (poke(0x4240, 0x00), poke(0x4241, 0x00), poke(0x4242, 0x00)), "restore 0x4240-0x4242 = 0"),
        (10.5, lambda: read(0x4244), "restored:a"), (11.5, lambda: read(0x4244), "restored:b")]
STATES = ("default", "on15", "on15off1", "maskdis", "eofsel", "restored")
setup_graph()
assert ctrl_info(STROBE), "strobe control missing (v3 build?)"
set_ctrl("exposure", 504); set_ctrl("analogue_gain", 16); set_ctrl("test_pattern", 0); set_ctrl(STROBE, 0)
set_fps(30); assert wait_for(lambda: runtime_status() == "suspended", 5), "sensor did not suspend"; time.sleep(0.3)
dq, log = stream(390, acts, timeout=16)
res = {"log": log, "frames": len(dq), "short": sum(d["short"] for d in dq), "err": sum(d["err"] for d in dq),
       "gaps": [(a["seq"], b["seq"]) for a, b in zip(dq, dq[1:]) if b["seq"] != a["seq"] + 1][:5]}
reads = {e["step"]: e for e in log if ":" in e["step"]}
for state in STATES:
    a, b = reads[f"{state}:a"], reads[f"{state}:b"]
    res[state] = {"counter": [a.get("r"), b.get("r")], "delta_mod256": (b["r"] - a["r"]) % 256 if "r" in a and "r" in b else None,
                  "frames_received": frames_between(dq, a["t"], b["t"])}
print(json.dumps(res, indent=1), flush=True)
OUT.write_text(json.dumps(res, indent=1))
