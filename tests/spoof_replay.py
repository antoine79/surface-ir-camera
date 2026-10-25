#!/usr/bin/env python3
"""Replay recorded frames into the virtual IR camera and ask Howdy to recognise.

Digital stand-in for the physical spoof tests: a perfect photo, a hand-held
photo, a video replay and a colour-camera photo, each presented to Howdy on
/dev/video21 while the real bridge is stopped. Run as the user; calls sudo
for Howdy's compare script. Usage: spoof_replay.py ir.grey colour.yuyv
"""
import subprocess, sys, time, threading
import numpy as np

DEV, H, W, FPS = "/dev/video21", 640, 480, 15
COMPARE = ["sudo", "-n", "timeout", "15", "python3",
           "/usr/lib/python3.14/site-packages/howdy/compare.py", "antoine"]
CODES = {0: "ACCEPTED", 11: "rejected (no match before timeout)",
         13: "rejected (all frames too dark)", 124: "rejected (killed at 15 s)"}


def feed(frames, stop):
    sink = open(DEV, "wb", buffering=0)
    subprocess.run(["v4l2-ctl", "-d", DEV, f"--set-fmt-video-out=width={W},height={H},pixelformat=GREY"], check=True)
    i = 0
    while not stop.is_set():
        sink.write(frames[i % len(frames)].tobytes()); i += 1
        time.sleep(1 / FPS)
    sink.close()


def trial(name, frames):
    stop = threading.Event()
    t = threading.Thread(target=feed, args=(frames, stop)); t.start()
    time.sleep(0.5)
    t0 = time.time()
    rc = subprocess.run(COMPARE, capture_output=True).returncode
    stop.set(); t.join()
    print(f"{name:34s} {CODES.get(rc, f'exit {rc}'):40s} {time.time() - t0:4.1f} s", flush=True)


if __name__ == "__main__":
  ir = np.fromfile(sys.argv[1], np.uint8).reshape(-1, H, W)
  still = ir[ir.mean(axis=(1, 2)).argmax()]
  rng = np.random.default_rng(0)
  jitter = [np.roll(still, (int(dy), int(dx)), (0, 1)) for dy, dx in rng.integers(-6, 7, (30, 2))]
  yuyv = np.fromfile(sys.argv[2], np.uint8).reshape(-1, 720, 1280, 2)[-1, ..., 0]
  colour = np.array(__import__("PIL.Image").Image.fromarray(yuyv).resize((W, H)))

  trial("control: dark frames", [np.zeros((H, W), np.uint8)])
  trial("control: grey, no face", [np.full((H, W), 100, np.uint8)])
  trial("video replay (20 lit frames)", list(ir))
  trial("perfect photo (1 frame repeated)", [still])
  trial("hand-held photo (jitter 6 px)", jitter)
  trial("colour-camera photo, as grey", [colour])
