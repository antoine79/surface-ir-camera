"""Compare an IR emitter's glow across phone videos shot with locked exposure (Phase 3b).

A phone sensor renders the 850 nm emitter as a magenta dot whose centre saturates to white, so the
brightest region of a frame is useless (it is the screen) and the dot's peak is clipped. The metric is
the integrated brightness of the magenta pixels ("glow"): the unsaturated halo, whose area and
intensity grow with the emitter's output. Lit runs (>= 1 s) are reported separately so one video can
hold several takes.

    python3 tools/glow_compare.py VIDEO...   # per run: start-end, frames, median glow, p10, p90
"""
import sys
from pathlib import Path

import cv2
import numpy as np

MIN_AREA = 20  # magenta pixels: below this the dot is off (noise gives a handful)


def glow(bgr):
    """Integrated grey level of the magenta pixels (r >> g, b > g), or 0.0 when the dot is off."""
    b, g, r = (bgr[:, :, i].astype(np.int16) for i in range(3))
    mask = (r - g > 40) & (b - g > 20)
    if mask.sum() < MIN_AREA:
        return 0.0
    return float(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)[mask].sum())


def runs(series, fps, min_len=1.0, max_gap=0.5):
    """[(first, last)] frame indices of lit runs >= min_len s, bridging gaps < max_gap s."""
    out, start, last = [], None, None
    for i, v in enumerate(series):
        if v <= 0:
            continue
        if start is not None and i - last > max_gap * fps:
            out.append((start, last))
            start = None
        start = i if start is None else start
        last = i
    if start is not None:
        out.append((start, last))
    return [(a, b) for a, b in out if b - a + 1 >= min_len * fps]


def analyse(frames, fps):
    series = np.array([glow(f) for f in frames])
    out = []
    for a, b in runs(series, fps):
        lit = series[a:b + 1]
        lit = lit[lit > 0]
        p10, med, p90 = np.percentile(lit, [10, 50, 90])
        out.append({"start": a / fps, "end": (b + 1) / fps, "n": b - a + 1, "median": med, "p10": p10, "p90": p90})
    return out


def read_video(path):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    def gen():
        while True:
            ok, f = cap.read()
            if not ok:
                return cap.release()
            yield f
    return gen(), fps


def main(paths):
    print("video run start end frames median p10 p90")
    for p in paths:
        frames, fps = read_video(p)
        for i, r in enumerate(analyse(frames, fps), 1):
            print(Path(p).name, i, f"{r['start']:.1f}", f"{r['end']:.1f}", r["n"],
                  f"{r['median']:.0f}", f"{r['p10']:.0f}", f"{r['p90']:.0f}")


if __name__ == "__main__":
    main(sys.argv[1:])
