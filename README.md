# surface-ir-camera

Linux support for the infrared camera of the Microsoft Surface Book 2 (13 inch, SKU Surface_Book_1832): an OmniVision OV7251 sensor with an 850 nm emitter, the pair Windows Hello uses. Out of the box the mainline kernel streams the sensor but never lights the emitter, so frames are black indoors.

The emitter is wired to the sensor's STROBE pin, not to any LED or GPIO the firmware describes, so lighting it is a sensor-driver change. This repository holds the kernel patches that add it, the tests that prove them on the hardware, and the user-space pieces that make the camera usable today.

## Status (October 2026)

- Kernel series of seven patches, ready to post to linux-media (`kernel/patches/`, cover letter included). All tested on the machine with the modules built out of tree against linux-surface 7.2.
- A bridge (`tools/ir-bridge.py`) that streams the camera with the emitter on and exposes upright 8-bit frames on a v4l2loopback device, so any webcam application sees it. Installed as a confined systemd service.
- Howdy face login works through the bridge. It recognises a face in about 3 s, but accepts a photo of it: a liveness check using both cameras is being designed.
- libcamera support is not started; the bridge is the stopgap until it exists.

## What the patches do

1. Fix the link frequency index, which made the sensor run at 240 MHz while the firmware asks for 319.2 MHz.
2. Make 60 and 90 fps actually change the frame rate.
3. Add control events, the one v4l2-compliance failure on the sensor.
4. Report orientation and rotation from firmware.
5. Move the strobe registers out of the mode tables, no functional change.
6. Add the `strobe_output_enable` control: lights the emitter on alternate frames while streaming, with a pulse that follows the exposure and stays within what the Windows driver uses on the same hardware. Off by default, off whenever the sensor is idle.
7. Make ipu-bridge report a 90 degree rotation for this model's infrared sensor, whose frames come out sideways.

`docs/windows-driver-notes.md` records what the Windows driver does with these registers, read with a decompiler: facts only, no code.

## Layout

- `kernel/patches/`: the series as `git format-patch` output. `kernel/build/`: out-of-tree build of the patched modules. `kernel/backport/`: the patched sources for the linux-surface 7.2 kernel.
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
