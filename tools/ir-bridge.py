#!/usr/bin/env python3
"""shortcut: raw V4L2 bridge, remove when the libcamera IPU3 mono path is merged.

Makes the OV7251 infrared camera look like an ordinary 8-bit grey webcam on the v4l2loopback device labelled
"Intel IR Camera" (/dev/video21, declared in /etc/modprobe.d/ir-camera-bridge.conf): sets up the IPU3 media graph,
turns the 850 nm emitter on, streams the packed 10-bit ip3y frames with v4l2-ctl, unpacks them, keeps the lit frame
of each lit/dark pair, rotates the picture upright and writes GREY frames to the loopback device. Emitter off and
children stopped on exit (Ctrl-C, SIGTERM, error).

Run by hand: tools/ir-bridge.py --frames lit|all|diff [--no-rotate]; as a service: ir-camera-bridge.service.
"""
import argparse
import signal
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ip3y  # noqa: E402

# cio2_nodes, subdev and setup_graph are copied from tests/conftest.py: importing conftest would pull in pytest.
CSI = "ipu3-csi2 2"
W, H = 640, 480
FRAME_BYTES = ip3y.bytesperline(W) * H
STROBE = "strobe_output_enable"
LABEL = "Intel IR Camera"


def run(*cmd, **kw) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw).stdout


def cio2_nodes() -> tuple[str, str]:
    """(/dev/mediaN of ipu3-cio2, /dev/videoN of "ipu3-cio2 2"), resolved by name: numbering differs between kernels."""
    for f in Path("/sys/class/video4linux").glob("video*/name"):
        if f.read_text().strip() == CSI.replace("csi2", "cio2"):
            media = next((f.parent / "device").resolve().glob("media*"))
            return f"/dev/{media.name}", f"/dev/{f.parent.name}"
    raise RuntimeError("no 'ipu3-cio2 2' video node")


def subdev() -> tuple[str, str]:
    """(entity name, /dev/v4l-subdevN) of the OV7251."""
    for f in sorted(Path("/sys/class/video4linux").glob("v4l-subdev*/name")):
        name = f.read_text().strip()
        if name.startswith("ov7251"):
            return name, f"/dev/{f.parent.name}"
    raise RuntimeError("no ov7251 subdev")


def loopback() -> str:
    for f in Path("/sys/devices/virtual/video4linux").glob("video*/name"):
        if f.read_text().strip() == LABEL:
            return f"/dev/{f.parent.name}"
    raise RuntimeError(f"no v4l2loopback device labelled {LABEL!r}: modprobe v4l2loopback")


def setup_graph(media: str, video: str, ent: str) -> None:
    """Enable sensor -> CSI-2 link and set Y10 640x480 on both pads and ip3y on the capture node (idempotent)."""
    run("media-ctl", "-d", media, "-l", f'"{ent}":0 -> "{CSI}":0 [1]')
    run("media-ctl", "-d", media, "-V", f'"{ent}":0 [fmt:Y10_1X10/{W}x{H}]')
    run("media-ctl", "-d", media, "-V", f'"{CSI}":0 [fmt:Y10_1X10/{W}x{H}]')
    run("v4l2-ctl", "-d", video, f"--set-fmt-video=width={W},height={H},pixelformat=ip3y")


def read_frames(stdout):
    """10-bit (H, W) frames from a v4l2-ctl --stream-to=- pipe, until it closes."""
    while len(buf := stdout.read(FRAME_BYTES)) == FRAME_BYTES:
        yield ip3y.unpack(buf, W, H)


def select(frames, mode: str):
    """lit: the brighter of each consecutive pair (the emitter lights alternate frames); diff: brighter minus darker,
    clipped (ambient light removed); all: every frame."""
    if mode == "all":
        yield from frames
        return
    it = iter(frames)
    for a, b in zip(it, it):
        lit, dark = (a, b) if a.mean() >= b.mean() else (b, a)
        yield lit if mode == "lit" else np.clip(lit.astype(np.int32) - dark, 0, 1023).astype(np.uint16)


def to8(frame: np.ndarray, rotate: bool = True) -> np.ndarray:
    """10-bit -> 8-bit; rotated 90 degrees counter-clockwise to undo the sensor mounting (640x480 -> 480x640)."""
    out = (frame >> 2).astype(np.uint8)
    return np.rot90(out) if rotate else out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frames", choices=("lit", "all", "diff"), default="lit")
    ap.add_argument("--no-rotate", action="store_true")
    args = ap.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # so the finally below runs on systemctl stop

    media, video = cio2_nodes()
    ent, sd = subdev()
    out = loopback()
    setup_graph(media, video, ent)
    oh, ow = (H, W) if args.no_rotate else (W, H)
    sink = open(out, "wb", buffering=0)  # opened before S_FMT: v4l2loopback forgets the format when its last user closes
    run("v4l2-ctl", "-d", out, f"--set-fmt-video-out=width={ow},height={oh},pixelformat=GREY")
    cap = None
    try:
        try:
            run("v4l2-ctl", "-d", sd, f"--set-ctrl={STROBE}=1")
        except subprocess.CalledProcessError as e:
            print(f"ir-bridge: cannot enable the emitter ({e.stderr.strip()}), streaming dark frames", file=sys.stderr)
        cap = subprocess.Popen(["v4l2-ctl", "-d", video, "--stream-mmap", "--stream-to=-"], stdout=subprocess.PIPE)
        for frame in select(read_frames(cap.stdout), args.frames):
            sink.write(to8(frame, not args.no_rotate).tobytes())
        raise RuntimeError("v4l2-ctl stream ended")
    finally:
        if cap:
            cap.terminate()
            cap.wait()
        subprocess.run(["v4l2-ctl", "-d", sd, f"--set-ctrl={STROBE}=0"], capture_output=True)
        sink.close()


if __name__ == "__main__":
    main()
