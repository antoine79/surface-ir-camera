"""Do I2C reads fail around the stream stop or the runtime power-off? Short stream (65 frames) with continuous
reads of 0x300a from 0.3 s to 4.0 s; each read logged with its time and result; last-frame time, v4l2-ctl exit
time and runtime_status transitions logged too."""
import re, subprocess, sys, tempfile, threading, time
from pathlib import Path
PROJ = Path("/home/antoine/projects/surface-ir-camera")
sys.path[:0] = [str(PROJ / "tests"), str(PROJ / "tools")]
from conftest import VIDEO, STROBE, runtime_status, set_ctrl, set_fps, setup_graph, wait_for  # noqa: E402
setup_graph(); set_ctrl(STROBE, 1); set_ctrl("test_pattern", 0)
for fps in (60, 30, 60):
    set_fps(fps); assert wait_for(lambda: runtime_status() == "suspended", 5)
    with tempfile.TemporaryDirectory() as d:
        res = {}
        t0, m0 = time.time(), time.monotonic()
        def run():
            p = subprocess.run(["v4l2-ctl", "-d", VIDEO, "--stream-mmap", "--stream-count=60", "--stream-skip=5", f"--stream-to={d}/f.raw", "--verbose"], capture_output=True, text=True, timeout=30)
            res["exit"] = round(time.time() - t0, 3); res["err"] = p.stderr
        th = threading.Thread(target=run); th.start()
        reads, status, last = [], [], None
        while time.time() - t0 < 4.0:
            if time.time() - t0 >= 0.3:
                t = round(time.time() - t0, 3)
                p = subprocess.run(["sudo", "-n", "i2ctransfer", "-f", "-y", "3", "w2@0x60", "0x30", "0x0a", "r1"], capture_output=True, text=True)
                reads.append((t, p.stdout.strip() if p.returncode == 0 else "FAIL " + (p.stderr.strip() or p.stdout.strip())[-40:]))
            s = runtime_status()
            if s != last:
                status.append((round(time.time() - t0, 3), s)); last = s
            time.sleep(0.005)
        th.join()
    ts = [float(x) - m0 for x in re.findall(r"ts:\s*([\d.]+)", res["err"])]
    print(f"== {fps} fps: frames {len(ts)}, first frame {ts[0]:.3f} s, last frame {ts[-1]:.3f} s, v4l2-ctl exit {res['exit']} s; runtime_status: {status}")
    fails = [(t, r) for t, r in reads if r.startswith("FAIL")]
    print(f"   reads {len(reads)} from {reads[0][0]} to {reads[-1][0]} s, fails {len(fails)}: {fails[:3]} ... {fails[-2:]}")
    ok_after = [t for t, r in reads if not r.startswith("FAIL") and fails and t > fails[0][0]]
    print(f"   first fail {fails[0][0] if fails else None} s, last ok before first fail {max([t for t, r in reads if not r.startswith('FAIL') and (not fails or t < fails[0][0])], default=None)} s, ok reads after the first fail: {len(ok_after)} {ok_after[:3]}")
set_ctrl(STROBE, 0); set_fps(30)
