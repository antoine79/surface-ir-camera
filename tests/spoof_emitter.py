#!/usr/bin/env python3
"""Does Howdy need the emitter's light, or does any picture of the face do?

Feeds real sensor frames with the emitter's contribution kept, removed or
flattened. Usage: spoof_emitter.py ir-all.grey  (bridge --frames all capture)
"""
import sys
import numpy as np
from PIL import Image, ImageOps
from spoof_replay import trial, H, W

f = np.fromfile(sys.argv[1], np.uint8).reshape(-1, H, W)
m = f.mean(axis=(1, 2))
lit, dark = f[m > 2.5 * m.min()], f[m <= 2.5 * m.min()]
diff = np.clip(lit[:20].astype(int) - dark[:20].astype(int), 0, 255).astype(np.uint8)
gain = lambda x, g: np.clip(x.astype(int) * g, 0, 255).astype(np.uint8)
flat = np.array(ImageOps.equalize(Image.fromarray(lit[0])))

print(f"lit mean {lit.mean():.0f}, dark mean {dark.mean():.0f}, emitter-only mean {diff.mean():.0f}")
trial("lit frames (emitter + room light)", list(lit))
trial("dark frames (room light only)", list(dark))
trial("dark frames x4 (brighter room, no emitter)", [gain(x, 4) for x in dark])
trial("emitter light only (lit minus dark)", list(diff))
trial("lit frame, shading flattened", [flat])
