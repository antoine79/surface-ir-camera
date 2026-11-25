#!/usr/bin/env python3
"""shortcut: raw V4L2 bridge, remove when the libcamera IPU3 mono path is merged.

Makes the OV7251 infrared camera look like an ordinary 8-bit grey webcam on the v4l2loopback device labelled
"Intel IR Camera" (/dev/video21, declared in /etc/modprobe.d/ir-camera-bridge.conf): sets up the IPU3 media graph,
turns the 850 nm emitter on, streams the packed 10-bit ip3y frames with v4l2-ctl, unpacks them, keeps the lit frame
of each lit/dark pair, rotates the picture upright and writes GREY frames to the loopback device. Emitter off and
children stopped on exit (Ctrl-C, SIGTERM, error).

Run by hand: tools/ir-bridge.py --frames lit|all|diff [--platform ipu3] [--rotate ccw|cw|180|none] [--no-emitter];
as a service: ir-camera-bridge.service.

Other camera interfaces (IPU4, IPU6, ...): everything platform-specific is in one Platform subclass below (find the
nodes, set up links and formats, unpack a frame). Copy the Template class, fill in its four parts, add it to PLATFORMS
and run with --platform <name>; the frame selection, rotation, loopback output and emitter handling are shared.
"""
import argparse
import signal
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ip3y  # noqa: E402

STROBE = "strobe_output_enable"
LABEL = "Intel IR Camera"


def run(*cmd, **kw) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw).stdout


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


def video_node(name: str) -> tuple[str, str]:
    """(/dev/mediaN, /dev/videoN) of the capture node with this name, resolved by name: numbering differs between
    kernels. The names are in /sys/class/video4linux/video*/name, or in `media-ctl -p`."""
    for f in Path("/sys/class/video4linux").glob("video*/name"):
        if f.read_text().strip() == name:
            media = next((f.parent / "device").resolve().glob("media*"))
            return f"/dev/{media.name}", f"/dev/{f.parent.name}"
    raise RuntimeError(f"no video node named {name!r}")


def unpack_y10(buf, width: int, height: int, bytesperline: int) -> np.ndarray:
    """V4L2 'Y10 ': one pixel per little-endian 16-bit word, low 10 bits used. bytesperline from v4l2-ctl --get-fmt-video."""
    return np.frombuffer(buf, "<u2", count=bytesperline // 2 * height).reshape(height, -1)[:, :width] & 0x3FF


def unpack_y10p(buf, width: int, height: int, bytesperline: int) -> np.ndarray:
    """V4L2 'Y10P' (MIPI CSI-2 packed): 4 pixels in 5 bytes, bytes 0-3 hold the high 8 bits, byte 4 the 4 x 2 low bits."""
    raw = np.frombuffer(buf, np.uint8, count=bytesperline * height).reshape(height, bytesperline)
    g = raw[:, : width // 4 * 5].reshape(height, -1, 5).astype(np.uint16)
    return ((g[:, :, :4] << 2) | ((g[:, :, 4:5] >> (2 * np.arange(4))) & 3)).reshape(height, -1)[:, :width]


class Platform:
    """What the bridge needs from a camera interface: one subclass per platform, listed in PLATFORMS."""
    width, height = 640, 480  # what the sensor delivers, before rotation

    def nodes(self) -> tuple[str, str]:
        """(/dev/mediaN, capture /dev/videoN)."""
        raise NotImplementedError

    def setup(self, media: str, video: str, sensor: str) -> None:
        """Enable the links from the sensor (media entity name `sensor`) to the capture node and set the formats.
        Must be idempotent: it runs at every start."""
        raise NotImplementedError

    def frame_bytes(self) -> int:
        """Size of one frame as the capture node delivers it (v4l2-ctl --get-fmt-video: bytesperline x height)."""
        raise NotImplementedError

    def unpack(self, buf) -> np.ndarray:
        """One frame -> (height, width) uint16 array of 10-bit values (0..1023)."""
        raise NotImplementedError


class Ipu3(Platform):
    """Surface Book 2 (tested), and other Kaby Lake Surfaces with the IPU3 (not tested): OV7251 on CSI-2 receiver 2."""
    CSI = "ipu3-csi2 2"

    def nodes(self):
        return video_node(self.CSI.replace("csi2", "cio2"))

    def setup(self, media, video, sensor):
        w, h = self.width, self.height
        run("media-ctl", "-d", media, "-l", f'"{sensor}":0 -> "{self.CSI}":0 [1]')
        run("media-ctl", "-d", media, "-V", f'"{sensor}":0 [fmt:Y10_1X10/{w}x{h}]')
        run("media-ctl", "-d", media, "-V", f'"{self.CSI}":0 [fmt:Y10_1X10/{w}x{h}]')
        run("v4l2-ctl", "-d", video, f"--set-fmt-video=width={w},height={h},pixelformat=ip3y")

    def frame_bytes(self):
        return ip3y.bytesperline(self.width) * self.height

    def unpack(self, buf):
        return ip3y.unpack(buf, self.width, self.height)


class Template(Platform):
    """Copy this class for a new camera interface (rename it, add it to PLATFORMS). To fill it in, with the sensor
    powered (streaming once with v4l2-ctl is enough):
    - `media-ctl -p`: entity names and pads from the sensor to the capture node, for nodes() and setup();
    - `v4l2-ctl -d /dev/videoN --list-formats-ext` and `--get-fmt-video`: the pixel format and bytesperline;
    - a 10-bit format is usually 'Y10 ' (unpack_y10) or 'Y10P' (unpack_y10p); 8-bit 'GREY' needs `<< 2`;
    - if the sensor mode is not 640x480 (the Book 3 Windows driver uses 648x488), set width and height.
    Check with `tools/ir-bridge.py --platform <name> --no-emitter --frames all` and a webcam viewer on the loopback."""
    CAPTURE = "<capture node name>"
    BYTESPERLINE = 0

    def nodes(self):
        return video_node(self.CAPTURE)

    def setup(self, media, video, sensor):
        raise NotImplementedError("set the media links and formats: see the class docstring")

    def frame_bytes(self):
        return self.BYTESPERLINE * self.height

    def unpack(self, buf):
        return unpack_y10(buf, self.width, self.height, self.BYTESPERLINE)


PLATFORMS = {"ipu3": Ipu3}


def read_frames(stdout, platform: Platform):
    """10-bit (H, W) frames from a v4l2-ctl --stream-to=- pipe, until it closes."""
    n = platform.frame_bytes()
    while len(buf := stdout.read(n)) == n:
        yield platform.unpack(buf)


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


ROTATIONS = {"ccw": 1, "180": 2, "cw": 3, "none": 0}  # quarter turns counter-clockwise


def to8(frame: np.ndarray, turns: int = 1) -> np.ndarray:
    """10-bit -> 8-bit, turned `turns` quarter turns counter-clockwise to undo the sensor mounting (the Surface Book 2
    needs one: 640x480 -> 480x640)."""
    return np.rot90((frame >> 2).astype(np.uint8), turns)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frames", choices=("lit", "all", "diff"), default="lit")
    ap.add_argument("--platform", choices=sorted(PLATFORMS), default="ipu3")
    ap.add_argument("--rotate", choices=ROTATIONS, default="ccw", help="turn applied to the picture (Book 2: ccw)")
    ap.add_argument("--no-rotate", dest="rotate", action="store_const", const="none", help="same as --rotate none")
    ap.add_argument("--no-emitter", action="store_true", help="leave the emitter off (then use --frames all)")
    args = ap.parse_args()
    platform = PLATFORMS[args.platform]()
    turns = ROTATIONS[args.rotate]
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # so the finally below runs on systemctl stop

    media, video = platform.nodes()
    ent, sd = subdev()
    out = loopback()
    platform.setup(media, video, ent)
    oh, ow = (platform.width, platform.height) if turns % 2 else (platform.height, platform.width)
    sink = open(out, "wb", buffering=0)  # opened before S_FMT: v4l2loopback forgets the format when its last user closes
    run("v4l2-ctl", "-d", out, f"--set-fmt-video-out=width={ow},height={oh},pixelformat=GREY")
    cap = None
    try:
        if not args.no_emitter:
            try:
                run("v4l2-ctl", "-d", sd, f"--set-ctrl={STROBE}=1")
            except subprocess.CalledProcessError as e:
                print(f"ir-bridge: cannot enable the emitter ({e.stderr.strip()}), streaming dark frames", file=sys.stderr)
        cap = subprocess.Popen(["v4l2-ctl", "-d", video, "--stream-mmap", "--stream-to=-"], stdout=subprocess.PIPE)
        for frame in select(read_frames(cap.stdout, platform), args.frames):
            sink.write(to8(frame, turns).tobytes())
        raise RuntimeError("v4l2-ctl stream ended")
    finally:
        if cap:
            cap.terminate()
            cap.wait()
        subprocess.run(["v4l2-ctl", "-d", sd, f"--set-ctrl={STROBE}=0"], capture_output=True)
        sink.close()


if __name__ == "__main__":
    main()
