"""Compare an IR emitter's blob brightness and flicker across locked-exposure videos."""
import sys
from pathlib import Path

import cv2
import numpy as np


def blob_mean(gray):
    """Mean of the unblurred pixels of the bright blob around the frame maximum, or None."""
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    mask = (blur >= max(200, 0.9 * blur.max())).astype(np.uint8)
    if not mask.any():
        return None
    _, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    k = lab[np.unravel_index(blur.argmax(), blur.shape)]
    if k == 0 or not 4 <= stats[k, cv2.CC_STAT_AREA] <= 0.05 * gray.size:
        return None
    return float(gray[lab == k].mean())


def analyse(frames, fps):
    series = [blob_mean(f) for f in frames]
    n = len(series)
    lit = np.array([v for v in series if v is not None])
    q = np.percentile(lit, [10, 50, 90]) if len(lit) else [None] * 3
    hz = None
    if n >= 16:
        x = np.array([v or 0.0 for v in series])
        spec = np.abs(np.fft.rfft(x - x.mean()))
        spec[0] = 0
        hz = float(np.fft.rfftfreq(n, 1 / fps)[spec.argmax()])
    return {"n": n, "lit_fraction": len(lit) / n if n else 0.0, "median": q[1],
            "p10": q[0], "p90": q[2], "flicker_hz": hz, "series": series}


def read_video(path):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    def gen():
        while True:
            ok, f = cap.read()
            if not ok:
                return cap.release()
            yield cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
    return gen(), fps


def _f(v, spec=".1f"):
    return "-" if v is None else format(v, spec)


def main(paths):
    first = None
    for p in paths:
        frames, fps = read_video(p)
        r = analyse(frames, fps)
        print(Path(p).name, r["n"], _f(100 * r["lit_fraction"]), _f(r["median"]),
              _f(r["p10"]), _f(r["p90"]), _f(r["flicker_hz"], ".2f"))
        if first is None:
            first = (Path(p).name, r["median"])
        elif r["median"] and first[1]:
            print(f"ratio {Path(p).name}/{first[0]} = {r['median'] / first[1]:.2f}")


if __name__ == "__main__":
    main(sys.argv[1:])
