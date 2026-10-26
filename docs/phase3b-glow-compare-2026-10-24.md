# Phase 3b: emitter glow, Linux (patched ov7251) vs Windows Hello, 2026-10-24

Same unit (Surface Book 2 1832), same phone, same locked settings for both videos: ISO 50, shutter 1/30 s, white balance 4000 K, 1080p at 29.9 fps, dark room, phone on a stand facing the bezel. Kernel 7.2.12-1.surface with the patch-7 module (a6a22e7645) for the Linux take, Windows 11 lock screen with three Windows Hello face attempts for the Windows take ("Making sure it's you" then "Couldn't recognize you", the phone was not in front of the face). Originals (not committed): `20261024_212133.mp4` (Linux, 79 s) and `20261024_212411.mp4` (Windows, 77 s). Crops of the emitter region are in `docs/phase3b/`.

Metric (`tools/glow_compare.py`): the phone renders the 850 nm dot as a magenta blob with a white, clipped core (peak 255 in both videos), so the brightest region of the frame (the screen) and the peak are useless. The glow is the integrated grey level of the magenta pixels (r - g > 40, b - g > 20), i.e. the unsaturated halo; its area and intensity grow with the emitter output, sub-linearly because of the clipped core. The brightest-region method first written for this tool locked onto the screen in both videos and was replaced.

| take | strobe span | frames | median glow | p10 | p90 | ratio to Windows |
|---|---|---|---|---|---|---|
| Linux, exposure 504 lines (driver default), gain 16, 30 fps | 504 lines | 450 | 120 628 | 118 023 | 125 356 | 1.12 |
| Linux, exposure 1704 lines (maximum), gain 16, 30 fps | 776 lines (45 % clamp) | 451 | 127 151 | 124 697 | 130 109 | 1.18 |
| Windows Hello sign-in, steady 13 s | unknown | 394 | 107 436 | 98 753 | 110 501 | 1 |

(Values from the cropped clips; the uncropped videos give 120 020 / 126 298 / 104 038, the same ratios within 3 %.)

Decision rule from the plan: ratio within 0.5–1.5 keeps the defaults. Result: 1.12 at the default exposure, 1.18 at the maximum, so the 52-line floor and 45 % duty cap stay. The ratio barely moves between a 504- and a 776-line pulse (+5 %) because the core is clipped at these phone settings; the halo metric compresses large differences, so the true ratio to Windows may be somewhat above the measured one but a factor of 2 would have shown as a much larger halo (the stock-driver 26-line pulse gave no visible dot at all in the earlier takes).

What the phone cannot tell: whether Windows alternates lit and dark frames (the register dump on an identical unit says it does). With a 1/30 s shutter every phone frame integrates one full sensor period, so an alternating 30 fps strobe looks continuous; even- and odd-frame glow were equal in both videos. Peak output per lit frame is therefore the figure compared here; the film was taken with every frame lit (pattern 0xff); the series switched to alternate frames (0xaa) on 2026-10-25, so the average emission now matches Windows' within the same ratio.

Camera geometry was not identical: the laptop was rebooted between the takes and the Windows clip shows the dot drift off the crop in its last 7 s (the tail is excluded by the 1 s run detection; the p10 of the uncropped Windows run, 42 775, is that tail). Dot size was comparable (37x55 px Linux, 39x51 px Windows) so distance was similar.
