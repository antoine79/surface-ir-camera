#!/usr/bin/env python3
"""Measure how well the OV7251 -> CSI-2 -> CIO2 link holds during a capture, so one measurement can be repeated for
several driver builds and on other machines (D. Manresa saw dropped frames and CSI-2 error lines on a Surface Pro 7+
with patch 1 of the series).

Per run: stream --skip + --frames buffers through `v4l2-ctl --verbose`, count the dequeued buffers and the gaps in
their sequence numbers, the kernel-log lines about the link since the run started, and the mean of the last frame
(a decoded picture proves the data is valid). Once per invocation, while a stream runs, read back the PLL and MIPI
registers, link_frequency, pixel_rate and the module taint. One JSON object per run is appended to --out. Exit 1 if
a run timed out or returned fewer buffers than requested (requested = frames + skip: v4l2-ctl dequeues the skipped
buffers too, it only leaves them out of the file).

Usage: tools/link-stress.py --label V1 [--frames 150] [--runs 3] [--fps 30] [--skip 5] [--out link-stress.jsonl]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import conftest as c  # noqa: E402  (puts tools/ on sys.path too)
import ip3y  # noqa: E402

REGS = (0x30b4, 0x30b3, 0x30b1, 0x30b0, 0x30b5, 0x4837, 0x3098, 0x3099, 0x309a, 0x309b, 0x309d)
LINK_WORDS = re.compile(r"cio2|csi2|csi-2|dphy|sync error|packet discarded|frame sync|mipi|ov7251", re.I)
DQBUF = re.compile(r"^cap dqbuf: \d+ seq:\s*(\d+) ", re.M)
FPS = re.compile(r"fps: ([\d.]+)")


def parse_stream(out: str) -> tuple[int, int, float | None]:
    """(received, dropped, last fps) from `v4l2-ctl --verbose` output: one 'cap dqbuf: N seq: S ... fps: F' line
    per dequeued buffer."""
    seqs = [int(s) for s in DQBUF.findall(out)]
    fps = FPS.findall(out)
    return len(seqs), seqs[-1] - seqs[0] + 1 - len(seqs) if seqs else 0, float(fps[-1]) if fps else None


def readback() -> dict:
    with c.streaming():
        regs = {f"0x{a:04x}": f"0x{c.read_reg(a):02x}" for a in REGS}
        ctrls = c.run("v4l2-ctl", "-d", c.sd(), "--get-ctrl", "link_frequency,pixel_rate")
    return {"kernel": os.uname().release, "taint": Path("/sys/module/ov7251/taint").read_text().strip(),
            "regs": regs, "ctrls": dict(l.strip().split(": ", 1) for l in ctrls.splitlines() if ": " in l)}


def run_once(frames: int, skip: int, path: str) -> dict:
    Path(path).unlink(missing_ok=True)
    start = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")  # the form `journalctl --since` takes
    cmd = ["v4l2-ctl", "-d", c.VIDEO, "--stream-mmap", f"--stream-count={frames}", f"--stream-skip={skip}",
           "--verbose", f"--stream-to={path}"]
    try:  # as conftest.stream: the timeout assumes >= 10 fps, the child is killed on timeout
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             timeout=10 + (frames + skip) / 10).stdout
        timed_out = False
    except subprocess.TimeoutExpired as e:
        out, timed_out = (e.output or b"").decode(errors="replace"), True  # bytes even with text=True
    end = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    received, dropped, fps = parse_stream(out)
    log = [l for l in c.run("journalctl", "-k", "-q", "-o", "cat", "--since", start).splitlines()
           if LINK_WORDS.search(l) and "audit" not in l]
    raw = Path(path).read_bytes() if Path(path).exists() else b""
    mean = round(float(ip3y.unpack(raw[-c.FRAME_BYTES:], c.W, c.H).mean()), 1) if len(raw) >= c.FRAME_BYTES else None
    return {"start": start, "end": end, "requested": frames + skip, "received": received, "dropped": dropped,
            "fps": fps, "error_lines": len(log), "errors": sorted(set(log)), "mean": mean,
            "complete": not timed_out and received >= frames + skip}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True, help="driver build under test, e.g. V1")
    ap.add_argument("--frames", type=int, default=150)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--skip", type=int, default=5)
    ap.add_argument("--out", default="link-stress.jsonl", help="one JSON object per run is appended here")
    a = ap.parse_args()
    if c.subdev() is None or c.VIDEO is None:
        sys.exit("no ov7251 subdev or no 'ipu3-cio2 2' video node under /sys/class/video4linux")
    c.setup_graph()
    c.set_fps(a.fps)
    rb = readback()
    print(f"readback: {a.label} on {rb['kernel']}, taint {rb['taint'] or '-'}\n  "
          + " ".join(f"{k}={v}" for k, v in rb["regs"].items()) + "\n  "
          + "  ".join(f"{k}: {v}" for k, v in rb["ctrls"].items()))
    print("\n| label | run | requested | received | dropped | fps | error lines | mean |\n|---|---|---|---|---|---|---|---|")
    runs = []
    with tempfile.TemporaryDirectory() as d:
        for i in range(1, a.runs + 1):
            r = {"label": a.label, "run": i, "fps_set": a.fps, **run_once(a.frames, a.skip, f"{d}/frames.raw"), "readback": rb}
            runs.append(r)
            with open(a.out, "a") as f:
                f.write(json.dumps(r) + "\n")
            print(f"| {a.label} | {i} | {r['requested']} | {r['received']}{'' if r['complete'] else ' (incomplete)'} | "
                  f"{r['dropped']} | {r['fps']} | {r['error_lines']} | {r['mean']} |", flush=True)
    errors = sorted({e for r in runs for e in r["errors"]})
    if errors:
        print("\nkernel log lines:\n" + "\n".join(f"  {e}" for e in errors))
    return 0 if all(r["complete"] for r in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
