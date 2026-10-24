# ov7251.c backport

`ov7251.c` here is mainline v7.2 plus the one ov7251 change linux-surface carries for 7.2. Nothing else is changed.

How it was derived (2026-10-24):

1. Base: `https://raw.githubusercontent.com/torvalds/linux/v7.2/drivers/media/i2c/ov7251.c` (sha256 `cf0f867e17e66ac87aa124b955f20d2915fee51baacd4ba67309de96e6806e75`).
2. Patch: `https://raw.githubusercontent.com/linux-surface/linux-surface/master/patches/7.2/0013-cameras.patch` (sha256 `9875f5e095382092b3ae476505ff7f214172456d725fc9d77c168093c90d6eca` at download time; the file on master may change). Only the hunks touching `drivers/media/i2c/ov7251.c` were applied: commit 60082ed1beb9 "media: i2c: Clarify that gain is Analogue gain in OV7251" (Daniel Scally), which switches the gain control from `V4L2_CID_GAIN` to `V4L2_CID_ANALOGUE_GAIN`.

Regenerate:

```sh
W=$(mktemp -d) && mkdir -p $W/drivers/media/i2c && cd $W
curl -fsSL -o drivers/media/i2c/ov7251.c https://raw.githubusercontent.com/torvalds/linux/v7.2/drivers/media/i2c/ov7251.c
curl -fsSL -o 0013-cameras.patch https://raw.githubusercontent.com/linux-surface/linux-surface/master/patches/7.2/0013-cameras.patch
git apply --include='drivers/media/i2c/ov7251.c' 0013-cameras.patch
grep -c V4L2_CID_ANALOGUE_GAIN drivers/media/i2c/ov7251.c   # expect 2
```

Then copy `drivers/media/i2c/ov7251.c` here.
