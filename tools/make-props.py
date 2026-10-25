#!/usr/bin/env python3
"""Turn captured camera frames into life-size A4 face prints for the spoof tests.

Usage: make-props.py ir.grey colour.yuyv outdir
The face box found by dlib is scaled to FACE_CM tall (chin to brow) and
centred on an A4 page at 300 dpi, written as PNG and PDF.
"""
import sys
import numpy as np, dlib
from PIL import Image

FACE_CM, DPI = 18.0, 300
A4 = (int(8.27 * DPI), int(11.69 * DPI))
det = dlib.get_frontal_face_detector()


def page(img, name, out):
    rects = det(np.asarray(img.convert("L")), 1)
    assert rects, f"no face in {name}"
    r = max(rects, key=lambda r: r.height())
    s = FACE_CM / 2.54 * DPI / r.height()
    img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    cx, cy = round((r.left() + r.right()) / 2 * s), round((r.top() + r.bottom()) / 2 * s)
    sheet = Image.new(img.mode, A4, "white")
    sheet.paste(img, (A4[0] // 2 - cx, A4[1] // 2 - cy))
    sheet.save(f"{out}/{name}.png", dpi=(DPI, DPI))
    sheet.convert("RGB").save(f"{out}/{name}.pdf", resolution=DPI)
    print(f"{name}: face {r.width()}x{r.height()} px, scale x{s:.1f}")


ir, col, out = sys.argv[1:4]
frames = np.fromfile(ir, np.uint8).reshape(-1, 640, 480)
lit = frames[frames.mean(axis=(1, 2)).argmax()]
page(Image.fromarray(lit), "ir-face", out)

yuyv = np.fromfile(col, np.uint8).reshape(-1, 720, 1280, 2)[-1]
y = yuyv[..., 0].astype(float)
u = np.repeat(yuyv[:, 0::2, 1], 2, axis=1).astype(float) - 128
v = np.repeat(yuyv[:, 1::2, 1], 2, axis=1).astype(float) - 128
rgb = np.stack([y + 1.402 * v, y - 0.344 * u - 0.714 * v, y + 1.772 * u], -1)
page(Image.fromarray(rgb.clip(0, 255).astype(np.uint8)), "colour-face", out)
