#!/usr/bin/env python3
"""throwaway spike: does the emitter's light carry a liveness signal?

For a stream of frames, pair each lit frame with the dark frame next to it,
and on the face box measure (1) how much of the face light comes from the
emitter, (2) how the emitter light falls off from the nose to the cheeks
(relief: a flat print lit from one point is lit evenly), (3) the glint of
the pupils (retro-reflection of the emitter next to the lens).
Usage: liveness_spike.py name file.grey [name file.grey ...]
"""
import sys
import numpy as np, dlib

H, W = 640, 480
det = dlib.get_frontal_face_detector()
sp = dlib.shape_predictor("/usr/share/howdy/dlib-data/shape_predictor_5_face_landmarks.dat")


def measure(frames):
    m = frames.mean(axis=(1, 2))
    lit_i = [i for i in range(len(frames) - 1) if m[i] > 2.5 * m[i + 1]]
    if not lit_i:
        return "no lit/dark pair: emitter signature absent"
    i = lit_i[0]
    lit, dark = frames[i].astype(int), frames[i + 1].astype(int)
    rgb = np.stack([frames[i]] * 3, -1)
    r = det(rgb, 1)
    if not r:
        return "no face in lit frame"
    r = r[0]; face = (slice(r.top(), r.bottom()), slice(r.left(), r.right()))
    emitter = (lit - dark)[face]
    share = emitter.mean() / max(lit[face].mean(), 1)
    pts = sp(rgb, r)
    nose = pts.part(4); nose_v = emitter[nose.y - r.top() - 10:nose.y - r.top() + 10, nose.x - r.left() - 10:nose.x - r.left() + 10].mean()
    w = emitter.shape[1] // 5; cheeks = (emitter[:, :w].mean() + emitter[:, -w:].mean()) / 2
    eyes = [((pts.part(0).x + pts.part(1).x) // 2, (pts.part(0).y + pts.part(1).y) // 2),
            ((pts.part(2).x + pts.part(3).x) // 2, (pts.part(2).y + pts.part(3).y) // 2)]
    glint = max(lit[y - 8:y + 8, x - 8:x + 8].max() for x, y in eyes) / max(np.median(lit[face]), 1)
    return f"emitter share {share:4.0%}  nose/cheek {nose_v / max(cheeks, 1):4.2f}  pupil glint {glint:4.2f}"


for name, path in zip(sys.argv[1::2], sys.argv[2::2]):
    print(f"{name:34s} {measure(np.fromfile(path, np.uint8).reshape(-1, H, W))}")
