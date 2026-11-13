"""OTP load with 0x3018 bit 4 clear: other five clock registers at the 30 fps values (0xf0) or the 60 fps values, at both rates."""
import sys, time
from pathlib import Path
sys.path[:0] = [str(Path("/home/antoine/projects/surface-ir-camera/tests")), str(Path("/home/antoine/projects/surface-ir-camera/tools"))]
sys.argv = ["x"]
exec(Path(__file__).with_name("otp_sweep.py").read_text().split("setup_graph();")[0])
from conftest import STROBE, set_ctrl, set_fps, setup_graph
setup_graph(); set_ctrl(STROBE, 0); set_ctrl("test_pattern", 0)
OTHERS = (0x3016, 0x3017, 0x301a, 0x301b, 0x301c)
V60 = {0x3016: 0x10, 0x3017: 0x00, 0x301a: 0x00, 0x301b: 0x00, 0x301c: 0x00}
def attempt(others, val3018):
    for a in OTHERS: poke(a, others[a] if isinstance(others, dict) else others)
    poke(0x3018, val3018); time.sleep(0.3)
    return otp()
for fps in (30, 60):
    set_fps(fps)
    for label, others in (("others=f0", 0xf0), ("others=60fps", V60)):
        for v in (0x00, 0x00, 0x00, 0x10):
            r = during_stream(fps, lambda: attempt(others, v))
            print(f"{fps} fps {label} 0x3018={v:02x}: {r}", flush=True)
set_fps(30)
