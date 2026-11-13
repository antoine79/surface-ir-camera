"""Which bits of 0x3018 (and 0x301c for the group block) matter: sweep the register value at 30 fps (other clock
registers at the 30 fps table's 0xf0), OTP load / group write at 2 s into a 4 s stream."""
import json, re, subprocess, sys, tempfile, threading, time
from pathlib import Path
PROJ = Path("/home/antoine/projects/surface-ir-camera")
sys.path[:0] = [str(PROJ / "tests"), str(PROJ / "tools")]
from conftest import VIDEO, STROBE, runtime_status, set_ctrl, set_fps, setup_graph, wait_for  # noqa: E402

def i2c(*args):
    p = subprocess.run(["sudo", "-n", "i2ctransfer", "-f", "-y", "3", *args], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-80:]
    return p.stdout.strip()

def poke(addr, *vals):
    assert addr != 0x3d80 and not (addr <= 0x3d80 < addr + len(vals))
    i2c(f"w{2 + len(vals)}@0x60", f"0x{addr >> 8:02x}", f"0x{addr & 0xff:02x}", *(f"0x{v:02x}" for v in vals))

def read(addr, n=1):
    return [int(x, 16) for x in i2c("w2@0x60", f"0x{addr >> 8:02x}", f"0x{addr & 0xff:02x}", f"r{n}").split()]

def otp():
    poke(0x3d00, *([0] * 32)); assert read(0x3d00, 4) == [0, 0, 0, 0]
    poke(0x3d81, 0x01); time.sleep(0.03)
    d = read(0x3d00, 32)
    return "data" if d[1:3] == [0x72, 0x51] and sum(1 for b in d if b) == 23 else ("zeros" if not any(d) else "other:" + "".join(f"{b:02x}" for b in d))

def group():
    poke(0x3208, 0x00); poke(0x3500, 0x00, 0x03, 0x20); poke(0x3208, 0x10); poke(0x3208, 0xa0); time.sleep(0.15)
    r = read(0x3501, 2); poke(0x3500, 0x00, 0x1f, 0x80)
    return "applied" if r == [0x03, 0x20] else ("lost" if r == [0x1f, 0x80] else f"other:{r}")

def during_stream(fps, fn):
    assert wait_for(lambda: runtime_status() == "suspended", 5)
    with tempfile.TemporaryDirectory() as d:
        th = threading.Thread(target=lambda: subprocess.run(["v4l2-ctl", "-d", VIDEO, "--stream-mmap", f"--stream-count={4 * fps}", f"--stream-to={d}/f.raw"], capture_output=True, timeout=30))
        th.start(); time.sleep(1.0)
        try:
            r = fn()
        finally:
            th.join()
    return r

setup_graph(); set_ctrl(STROBE, 0); set_ctrl("test_pattern", 0); set_fps(30)
out = {}
for val in (0xf0, 0x00, 0x10, 0xe0, 0x80, 0x40, 0x20, 0xc0, 0xa0, 0x60, 0xd0, 0xb0, 0x70, 0xe0, 0x00):
    out[f"30fps 0x3018={val:02x}"] = during_stream(30, lambda: (poke(0x3018, val), time.sleep(0.5), otp(), f"{read(0x3018)[0]:02x}")[2:])
    print(list(out.items())[-1], flush=True)
for val in (0x00, 0x20, 0xd0, 0xf0):
    out[f"30fps 0x301c={val:02x} group"] = during_stream(30, lambda: (poke(0x301c, val), time.sleep(0.5), group(), f"{read(0x301c)[0]:02x}")[2:])
    print(list(out.items())[-1], flush=True)
set_fps(60)
for val in (0x00, 0xe0, 0xf0):
    out[f"60fps 0x3018={val:02x}"] = during_stream(60, lambda: (poke(0x3018, val), time.sleep(0.5), otp(), f"{read(0x3018)[0]:02x}")[2:])
    print(list(out.items())[-1], flush=True)
set_fps(30)
Path(__file__).with_suffix(".json").write_text(json.dumps(out, indent=1))
