# ov7251.c backport

`ov7251.c` here is mainline v7.2, plus the one ov7251 change linux-surface carries for 7.2, plus the eight ov7251 patches of the v3 series in `../patches/` (media-committers branch `ov7251-ir-v3`, tip 3b1dea31ac41; `v3-0009` touches ipu-bridge only). Everything else is unchanged. It builds against the kernel-surface 7.2 headers. Patch 8 uses `V4L2_CID_FLASH_STROBE_OE`, which 6.18 does not have, so the file as a whole does not build against 6.18 (see `../build/README.md` for the 6.18 test module).

The check that matters: `diff <(git -C ~/projects/media-committers show ov7251-ir-v3:drivers/media/i2c/ov7251.c) ov7251.c` must show only the 7.2 adaptations, which are the gain control name (`V4L2_CID_ANALOGUE_GAIN` instead of mainline's `V4L2_CID_GAIN`, two lines) and the `v4l2_subdev_client_info *ci` argument that mainline 7.3 passes to set_fmt and get_selection (three lines). Checked 2026-10-30.

## How it was derived (2026-10-24; v2 since 2026-10-26, v3 since 2026-10-30)

1. Base: `https://raw.githubusercontent.com/torvalds/linux/v7.2/drivers/media/i2c/ov7251.c` (sha256 `cf0f867e17e66ac87aa124b955f20d2915fee51baacd4ba67309de96e6806e75`).
2. linux-surface patch: `https://raw.githubusercontent.com/linux-surface/linux-surface/master/patches/7.2/0013-cameras.patch` (sha256 `9875f5e095382092b3ae476505ff7f214172456d725fc9d77c168093c90d6eca` at download time; the file on master may change). Only the hunks touching `drivers/media/i2c/ov7251.c` were applied: commit 60082ed1beb9 "media: i2c: Clarify that gain is Analogue gain in OV7251" (Daniel Scally), which switches the gain control from `V4L2_CID_GAIN` to `V4L2_CID_ANALOGUE_GAIN`. Mainline, and so the series, still say `V4L2_CID_GAIN`; this rename is not a series patch.
3. The v3 series, `../patches/v3-0001` to `v3-0008`, written against the media `next` branch (7.3.0-rc1). Two hunks of patch 5 do not match the 7.2 base as they are: one carries the `ci` argument of 7.3's set_fmt in the `ov7251_set_format(subdev, NULL, sd_state, &fmt)` call, the other the mainline gain control name as context. Filtering those two strings out of the patch stream (Regenerate below) makes all eight apply, and the result is byte-identical to this file (replayed 2026-10-30 from the base as committed in e996431, so the two downloads above were not repeated).

| Patch | Change |
|-------|--------|
| v3 1 | in-range PLL1 dividers for the 19.2 MHz / 319.2 MHz table: pre-divider 4, divider 1 (same 638.4 Mbps link, VCO 638.4 MHz instead of 2553.6 MHz; fixes the dropped frames and CSI-2 errors D. Manresa measured on a Surface Pro 7+ once patch 2 selects this table) |
| v3 2 | link frequency index: use the driver's table index (319.2 MHz on the Surface Book 2 instead of 240 MHz) |
| v3 3 | `pixel_rate` reports the pixel array clock, 48 MHz, at both link frequencies |
| v3 4 | reset VBLANK on frame-interval and format changes (60/90 fps really stream at 60/90) |
| v3 5 | use the sub-device active state (format and crop live in the state, driver mutex dropped; the core then handles control events, so `v4l2-compliance -u` passes) |
| v3 6 | `camera_orientation` and `camera_sensor_rotation` from firmware |
| v3 7 | the registers common to the three mode tables, strobe defaults included (0x3005 = 0x00, 0x3b81 = 0xa5, 0x3b8c-0x3b8f = 0x1a), move into the global init table written at power-on; the mode tables keep only the clock control registers (Dave Stevenson) |
| v3 8 | `V4L2_CID_FLASH_STROBE_OE` drives the STROBE pin, i.e. the 850 nm emitter: the control handler writes 0x3005, 0x3b81 and the span at stream start; pulse = exposure, clamped to 52 lines .. 45% of the frame (VTS from the mode height + VBLANK) |
| v3 9 | ipu-bridge only, see below |

## Regenerate

```sh
W=$(mktemp -d) && mkdir -p $W/drivers/media/i2c && cd $W
curl -fsSL -o drivers/media/i2c/ov7251.c https://raw.githubusercontent.com/torvalds/linux/v7.2/drivers/media/i2c/ov7251.c
curl -fsSL -o 0013-cameras.patch https://raw.githubusercontent.com/linux-surface/linux-surface/master/patches/7.2/0013-cameras.patch
git apply --include='drivers/media/i2c/ov7251.c' 0013-cameras.patch
P=~/projects/surface-ir-camera/kernel/patches
for n in 0001 0002 0003 0004 0005 0006 0007 0008; do
  sed -e 's/ov7251_set_format(subdev, NULL, sd_state/ov7251_set_format(subdev, sd_state/' \
      -e 's/V4L2_CID_GAIN\b/V4L2_CID_ANALOGUE_GAIN/' $P/v3-$n-*.patch | git apply
done
grep -c V4L2_CID_FLASH_STROBE_OE drivers/media/i2c/ov7251.c   # expect 2
```

Then copy `drivers/media/i2c/ov7251.c` here.

# ipu-bridge.c backport

`ipu-bridge.c` here is the ipu-bridge of the installed kernel-surface 7.2.12 plus patch 9 of the v3 series (`../patches/v3-0009-*.patch`; its diff is the same as v2's patch 9). The installed kernel ships no source for it, so the base was rebuilt and checked against the strings of the stock module (it carries the IVSC-only ID list from stable and the Surface Pro 8 and 9 quirks from linux-surface).

1. Base: `https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/plain/drivers/media/pci/intel/ipu-bridge.c?h=v7.2.12` (sha256 `dfdca598bc76dfe3812abb7f6f8ab4332c361259f5f14e6e782052c2f7d8f600`). Mainline v7.2 differs from it by two stable fixes.
2. linux-surface: the two hunks of `0013-cameras.patch` (same URL and sha256 as above) touching `drivers/media/pci/intel/ipu-bridge.c`: the Surface Pro 9 sensor entries and the Surface Pro 8 and 9 upside-down quirks. Applied with `git apply --include`, no fuzz.
3. Patch 9, applied with `git apply` (it applies with an offset, no fuzz). Since 2026-10-28 the quirk table also carries the Surface Pro 7+ entry (DMI product SKU `Surface_Pro_7+_1960`), whose frames D. Manresa measured turned the same way.

```sh
W=$(mktemp -d) && mkdir -p $W/drivers/media/pci/intel && cd $W
curl -fsSL -o drivers/media/pci/intel/ipu-bridge.c 'https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/plain/drivers/media/pci/intel/ipu-bridge.c?h=v7.2.12'
curl -fsSL -o 0013-cameras.patch https://raw.githubusercontent.com/linux-surface/linux-surface/master/patches/7.2/0013-cameras.patch
git apply --include='drivers/media/pci/intel/ipu-bridge.c' 0013-cameras.patch
git apply ~/projects/surface-ir-camera/kernel/patches/v3-0009-*.patch
```

Then copy `drivers/media/pci/intel/ipu-bridge.c` here.
