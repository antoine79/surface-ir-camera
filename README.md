# surface-ir-camera

Linux support for the infrared camera of the Microsoft Surface Book 2 (13 inch, SKU Surface_Book_1832): an OmniVision OV7251 sensor with an 850 nm emitter, the pair Windows Hello uses. Out of the box the mainline kernel streams the sensor but never lights the emitter, so frames are black indoors.

The emitter is wired to the sensor's STROBE pin, not to any LED or GPIO the firmware describes, so lighting it is a sensor-driver change. This repository holds the kernel patches that add it, the tests that prove them on the hardware, and the user-space pieces that make the camera usable today.

## Status (October 2026)

- Kernel series of nine patches. v2 was posted to linux-media on 28 Oct 2026 (`kernel/patches/v2-posted/`, cover letter included); v3 is in preparation in `kernel/patches/`, with the table merge from Dave Stevenson as patch 7 and no cover letter written yet. All tested on the machine with the modules built out of tree against linux-surface 7.2.
- A bridge (`tools/ir-bridge.py`) that streams the camera with the emitter on and exposes upright 8-bit frames on a v4l2loopback device, so any webcam application sees it. Installed as a confined systemd service.
- Howdy face login works through the bridge. It recognises a face in about 3 s, but accepts a photo of it: a liveness check using both cameras is being designed.
- libcamera support is not started; the bridge is the stopgap until it exists.

## What the patches do

1. Use in-range PLL1 dividers for the 319.2 MHz link: same link rate, VCO at 638.4 MHz instead of 2553.6 MHz (a Surface Pro 7+ dropped frames at the out-of-range setting).
2. Fix the link frequency index, which made the sensor run at 240 MHz while the firmware asks for 319.2 MHz.
3. Report the pixel array rate, 48 MHz, at both link frequencies.
4. Make 60 and 90 fps actually change the frame rate.
5. Use the sub-device active state for the format and crop; the core then delivers control events, the one v4l2-compliance failure on the sensor.
6. Report orientation and rotation from firmware.
7. Move the registers common to the three mode tables into the global init table written at power-on (Dave Stevenson), so they are written once per power-on instead of at every stream start.
8. Add the `strobe_output_enable` control: lights the emitter on alternate frames while streaming, with a pulse that follows the exposure and stays within what the Windows driver uses on the same hardware. Off by default, off whenever the sensor is idle.
9. Make ipu-bridge report a 90 degree rotation for the infrared sensor of this model and of the Surface Pro 7+, whose frames come out sideways.

`docs/windows-driver-notes.md` records what the Windows driver does with these registers, read with a decompiler: facts only, no code.

## Layout

- `kernel/patches/`: the v3 series as `git format-patch` output, the posted v1 and v2 under `v1-posted/` and `v2-posted/`. `kernel/build/`: out-of-tree build of the patched modules. `kernel/backport/`: the patched sources for the linux-surface 7.2 kernel.
- `tests/`: acceptance tests (pytest + numpy, shelling out to `media-ctl`, `v4l2-ctl`, `v4l2-compliance`). `tests/README.md` has the test matrix and how to run it, plus the bridge installation and undo steps.
- `tools/`: bench script that proved the emitter mechanism, the bridge, the phone glow comparison, cover letter number extraction, print props for spoof tests.
- `docs/`: test logs attached to the submission, measurements, Windows driver notes, line coverage of the driver under test.
- `libcamera/`: reserved, empty.

## Try it

Build and load the patched sensor module, then run the tests (details in `tests/README.md`):

```
make -s -C kernel/build KDIR=/path/to/kernel/source
sudo sh -c 'echo i2c-INT347E:00 > /sys/bus/i2c/drivers/ov7251/unbind; rmmod ov7251; insmod kernel/build/ov7251.ko'
pytest -q tests/
```

The emitter only shows in a dim room: daylight carries enough near-infrared to swamp it, and the tests say so when they skip.

## Licence

GPL-2.0, the kernel's licence, for everything here.
