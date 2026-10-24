# ov7251.c backport

`ov7251.c` here is mainline v7.2, plus the one ov7251 change linux-surface carries for 7.2, plus the six Phase 3 patches from `../patches/` (media-committers branch `ov7251-ir`). Everything else is unchanged. It builds against the kernel-surface 7.2 headers. Patch 7 uses `V4L2_CID_FLASH_STROBE_OE`, which 6.18 does not have, so the file as a whole does not build against 6.18 (see `../build/README.md` for the 6.18 test module).

## How it was derived (2026-10-24)

1. Base: `https://raw.githubusercontent.com/torvalds/linux/v7.2/drivers/media/i2c/ov7251.c` (sha256 `cf0f867e17e66ac87aa124b955f20d2915fee51baacd4ba67309de96e6806e75`).
2. linux-surface patch: `https://raw.githubusercontent.com/linux-surface/linux-surface/master/patches/7.2/0013-cameras.patch` (sha256 `9875f5e095382092b3ae476505ff7f214172456d725fc9d77c168093c90d6eca` at download time; the file on master may change). Only the hunks touching `drivers/media/i2c/ov7251.c` were applied: commit 60082ed1beb9 "media: i2c: Clarify that gain is Analogue gain in OV7251" (Daniel Scally), which switches the gain control from `V4L2_CID_GAIN` to `V4L2_CID_ANALOGUE_GAIN`. This is the same change as patch 0002 of the series.
3. Phase 3 series: `../patches/0001`, `0003` to `0007` (0002 is step 2), applied with `git apply`. They were written against the media `next` branch (7.3.0-rc1) and apply to v7.2 without fuzz.

| Patch | Change |
|-------|--------|
| 0001 | link frequency index: use the driver's table index (319.2 MHz on the Surface Book 2 instead of 240 MHz) |
| 0002 | gain is `V4L2_CID_ANALOGUE_GAIN` (Daniel Scally, already in step 2) |
| 0003 | control events on the subdev node (`v4l2-compliance -u`) |
| 0004 | reset VBLANK on frame-interval and format changes (60/90 fps really stream at 60/90) |
| 0005 | `camera_orientation` and `camera_sensor_rotation` from firmware |
| 0006 | strobe registers moved out of the mode tables (no functional change) |
| 0007 | `V4L2_CID_FLASH_STROBE_OE` drives the STROBE pin, i.e. the 850 nm emitter; pulse = exposure, clamped to 52 lines .. 45% of the frame (VTS from the mode height + VBLANK) |

## Regenerate

```sh
W=$(mktemp -d) && mkdir -p $W/drivers/media/i2c && cd $W
curl -fsSL -o drivers/media/i2c/ov7251.c https://raw.githubusercontent.com/torvalds/linux/v7.2/drivers/media/i2c/ov7251.c
curl -fsSL -o 0013-cameras.patch https://raw.githubusercontent.com/linux-surface/linux-surface/master/patches/7.2/0013-cameras.patch
git apply --include='drivers/media/i2c/ov7251.c' 0013-cameras.patch
P=~/projects/surface-ir-camera/kernel/patches
for n in 0001 0003 0004 0005 0006 0007; do git apply $P/$n-*.patch; done
grep -c V4L2_CID_FLASH_STROBE_OE drivers/media/i2c/ov7251.c   # expect 2
```

Then copy `drivers/media/i2c/ov7251.c` here.

# ipu-bridge.c backport

`ipu-bridge.c` here is the ipu-bridge of the installed kernel-surface 7.2.12 plus patch 8 (`../patches/0008`). The installed kernel ships no source for it, so the base was rebuilt and checked against the strings of the stock module (it carries the IVSC-only ID list from stable and the Surface Pro 8 and 9 quirks from linux-surface).

1. Base: `https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/plain/drivers/media/pci/intel/ipu-bridge.c?h=v7.2.12` (sha256 `dfdca598bc76dfe3812abb7f6f8ab4332c361259f5f14e6e782052c2f7d8f600`). Mainline v7.2 differs from it by two stable fixes.
2. linux-surface: the two hunks of `0013-cameras.patch` (same URL and sha256 as above) touching `drivers/media/pci/intel/ipu-bridge.c`: the Surface Pro 9 sensor entries and the Surface Pro 8 and 9 upside-down quirks. Applied with `git apply --include`, no fuzz.
3. Patch 8, applied with `git apply` (it applies with an offset, no fuzz).

```sh
W=$(mktemp -d) && mkdir -p $W/drivers/media/pci/intel && cd $W
curl -fsSL -o drivers/media/pci/intel/ipu-bridge.c 'https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/plain/drivers/media/pci/intel/ipu-bridge.c?h=v7.2.12'
curl -fsSL -o 0013-cameras.patch https://raw.githubusercontent.com/linux-surface/linux-surface/master/patches/7.2/0013-cameras.patch
git apply --include='drivers/media/pci/intel/ipu-bridge.c' 0013-cameras.patch
git apply ~/projects/surface-ir-camera/kernel/patches/0008-*.patch
```

Then copy `drivers/media/pci/intel/ipu-bridge.c` here.
