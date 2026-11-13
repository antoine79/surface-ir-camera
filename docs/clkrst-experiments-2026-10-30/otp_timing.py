"""OTP with sclk_otp (0x3018 bit 4) clear: does the load merely take longer, and do buffer reads/writes work at all?"""
import sys, time
from pathlib import Path
sys.path[:0] = [str(Path("/home/antoine/projects/surface-ir-camera/tests")), str(Path("/home/antoine/projects/surface-ir-camera/tools"))]
sys.argv = ["x"]
exec(Path(__file__).with_name("otp_sweep.py").read_text().split("setup_graph();")[0])  # reuse i2c/poke/read/during_stream
from conftest import STROBE, set_ctrl, set_fps, setup_graph
setup_graph(); set_ctrl(STROBE, 0); set_ctrl("test_pattern", 0); set_fps(30)
def sig(d): return "data" if d[1:3] == [0x72, 0x51] else ("zeros" if not any(d) else "other:" + "".join(f"{b:02x}" for b in d[:8]))

def timed_load(val):
    poke(0x3018, val); time.sleep(0.3)
    poke(0x3d00, *([0] * 32)); poke(0x3d81, 0x01); t0 = time.time(); out = []
    for wait in (0.005, 0.03, 0.1, 0.3, 1.0, 2.0):
        while time.time() - t0 < wait: time.sleep(0.002)
        out.append((wait, sig(read(0x3d00, 32))))
    return out

def rw_test(val):
    poke(0x3018, 0x10); time.sleep(0.1); poke(0x3d00, *([0] * 32)); poke(0x3d81, 0x01); time.sleep(0.05)
    a = sig(read(0x3d00, 32))                       # loaded with the clock bit set
    poke(0x3018, val); time.sleep(0.2)
    b = sig(read(0x3d00, 32))                       # same buffer read with the bit clear
    poke(0x3d00, *([0x5a] * 32)); c = read(0x3d00, 4)  # write/read the buffer with the bit clear
    poke(0x3d00, *([0] * 32)); d = read(0x3d00, 4)
    return {"loaded_bit4": a, "read_after_clearing_bit4": b, "write_5a_readback": [f"{x:02x}" for x in c], "write_00_readback": [f"{x:02x}" for x in d]}

for val in (0x00, 0xe0, 0x00, 0xe0, 0x10):
    print(f"30fps 0x3018={val:02x} load timing:", during_stream(30, lambda: timed_load(val)), flush=True)
print("30fps buffer rw with 0x3018=00:", during_stream(30, lambda: rw_test(0x00)), flush=True)
print("30fps buffer rw with 0x3018=e0:", during_stream(30, lambda: rw_test(0xe0)), flush=True)
set_fps(60)
for val in (0x00, 0xe0):
    print(f"60fps 0x3018={val:02x} load timing:", during_stream(60, lambda: timed_load(val)), flush=True)
set_fps(30)
