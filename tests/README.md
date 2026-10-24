# Acceptance tests

pytest + numpy, shelling out to `media-ctl`, `v4l2-ctl` and `v4l2-compliance`. Runs as the normal user (ACLs on `/dev/media0`, the OV7251 subdev and `/dev/video2`); no sudo except K9. The OV7251 subdev is found by name under `/sys/class/video4linux`, hardware tests skip if it is absent.

## Run

```
pytest -q tests/                          # everything except disruptive tests
pytest -q tests/ -m "not needs_patch"     # only what the stock kernel must pass
IRCAM_DISRUPTIVE=1 pytest -q tests/test_k8_suspend.py tests/test_k9_reload.py   # at the machine, after sudo -v
IRCAM_DISRUPTIVE=1 pytest -q "tests/test_k1_compliance.py::test_compliance[media]"   # oopses ov5693, only before a reboot
```

Markers (registered in `pytest.ini`): `needs_patch("n")` = expected red until kernel patch n lands, numbered as in `kernel/patches/` (1 link frequency, 2 analogue gain, 3 control events, 4 frame interval, 5 fwnode controls, 6 strobe refactor, 7 strobe control); `disruptive` = suspends the machine, reloads modules or oopses the kernel, skipped unless `IRCAM_DISRUPTIVE=1`.

## Matrix

| ID | File | Asserts | Stock 6.18 | Green after |
|----|------|---------|------------|-------------|
| helpers | `test_helpers.py` | `v4l2-ctl -l` parser on `fixtures/ov7251-6.18-ctrls.txt` | green | |
| ip3y | `test_ip3y.py` | unpacker against a reference packer | green | |
| K1 | `test_k1_compliance.py` | `v4l2-compliance -u <subdev>`, `-m /dev/media0`, `-d /dev/video2 -s 30`: Failed == 0; first run per kernel saves `baseline/k1-<target>-<release>.log` | red (see baseline logs) | subdev: patch 3; video: not an ov7251 issue (7 buffer failures in ipu3-cio2); media: disruptive, skipped by default: `v4l2-compliance -m` oopses the kernel in `ov5693_set_fmt` (divide error, front camera) and dies with SIGSEGV, so run it only before a reboot |
| K2 | `test_k2_controls.py` | `analogue_gain` present, `gain` absent | green | |
| K2 | | `camera_orientation` = 0 (front), `camera_sensor_rotation` = 0 | red | patch 5 |
| K2 | | `strobe_output_enable` is bool, default 0 | red | patch 7 |
| K3 | `test_k3_timing.py` | `link_frequency` = 319200000, `pixel_rate` = 63840000 | red | patch 1 |
| K3 | | 90 frames at 30 fps take 2.6-3.6 s | green | |
| K3 | | `--set-subdev-fps` 60 / 90 reads back and the stream really runs at that rate | red (reads back, streams at 30) | patch 4 (not marked `needs_patch`) |
| K4 | `test_k4_dark.py` | emitter off, exposure 1704, gain 128: 30-frame mean < 40 | green | |
| K5 | `test_k5_emitter.py` | `strobe_output_enable=1` before stream: mean > 2.5 x K4 dark, first 3 frames lit, dark again after reset to 0 | red | patch 7 |
| K7 | `test_k7_safety.py` | sensor `runtime_status` = suspended within 2 s of a stream ending | green | |
| K7 | | strobe set to 1 while idle reads back 1 and the sensor stays suspended | red | patch 7 |
| K8 | `test_k8_suspend.py` | suspend mid-stream: capture completes or exits cleanly, controls unchanged (manual wake) | skipped | |
| K9 | `test_k9_reload.py` | 10 x unbind/unload/load: ov7251 entity re-appears (new entity id), other entities unchanged, no WARNING/BUG/Oops/leak in `journalctl -k` | skipped | |
| K10 | `test_k10_test_pattern.py` | test pattern decodes to the exact 8 colour bars on a Bayer mosaic (only 0/1023, rows period 2, bar means 1023 x k/4) | green | |

K9 unbinds `i2c-INT347E:00` from the ov7251 driver first (`modprobe -r` alone fails: the ipu3-cio2 v4l2_device holds a reference on the sensor module), then runs `sudo modprobe -r ov7251` and loads `$IRCAM_KO` with `sudo insmod` if set (e.g. `kernel/build/ov7251.ko`), else `sudo modprobe ov7251`.

## Safety

Every stream is a `v4l2-ctl --stream-count=N` child with a timeout, so no test leaves a stream (and, on a patched driver, a lit emitter) running. Tests that turn the strobe on reset it to 0 in a `finally`. K7 checks the sensor powers down after streaming. Tests change only runtime state: the sensor -> CSI-2 link stays enabled, exposure/gain stay at the bench values (1704/128). Note that the driver resets exposure and gain to 504/16 on every format or frame-interval change.

## Phase 3b: glow-compare

`tools/glow_compare.py` compares the brightness of the IR emitter (a small bright blob) across phone videos filmed with locked exposure, e.g. our driver against Windows Hello. Per video it reports the median blob brightness (Gaussian blur, threshold max(200, 0.9 x frame max), connected component around the brightest pixel, mean of the raw pixels), the fraction of frames where the blob is present, and the dominant flicker frequency (Windows strobes on alternate frames, so 15 Hz at 30 fps; ours every frame). Run `python3 tools/glow_compare.py linux.mp4 windows1.mp4` to get `name n lit% median p10 p90 flicker_hz` per video plus `ratio <name>/<first> = x.xx` of medians. Unit tests: `pytest -q tests/test_glow_compare.py`.
