# Acceptance tests

pytest + numpy, shelling out to `media-ctl`, `v4l2-ctl` and `v4l2-compliance`. Runs as the normal user (ACLs on `/dev/media0`, the OV7251 subdev and `/dev/video2`); sudo only for K9 and for the sensor register reads (`sudo -n i2ctransfer -f -y 3`, bus 3, address 0x60), so passwordless or cached sudo is needed for the register tests. Registers are read only inside `streaming()` (conftest), which runs a fixed-count stream in the background and reads 1 s in: a suspended sensor is powered off and reads back garbage. The OV7251 subdev is found by name under `/sys/class/video4linux`, hardware tests skip if it is absent. K4, K5 and the end-to-end test need a dark room: daylight carries near-infrared and swamps the emitter (a sunny morning gave 862 counts with the emitter off against ~20 at night), so K5 and E2E skip, naming the measured level, when the room is too bright.

## Run

```
pytest -q tests/                          # everything except disruptive tests
pytest -q tests/ -m "not needs_patch"     # only what the stock kernel must pass
IRCAM_DISRUPTIVE=1 pytest -q tests/test_k8_suspend.py tests/test_k9_reload.py   # at the machine, after sudo -v
IRCAM_DISRUPTIVE=1 pytest -q "tests/test_k1_compliance.py::test_compliance[media]"   # oopses ov5693, only before a reboot
```

Markers (registered in `pytest.ini`): `needs_patch("n")` = expected red until kernel patch n lands, numbered as in `kernel/patches/` (1 link frequency, 2 analogue gain, 3 control events, 4 frame interval, 5 fwnode controls, 6 strobe refactor, 7 strobe control, 8 ipu-bridge DMI quirk that reports the 90 degree sensor rotation the ACPI `_PLD` gets wrong, `all` for the end-to-end scenario); `disruptive` = suspends the machine, reloads modules or oopses the kernel, skipped unless `IRCAM_DISRUPTIVE=1`.

## Matrix

| ID | File | Asserts | Stock 6.18 / 7.2 | Green after |
|----|------|---------|------------|-------------|
| helpers | `test_helpers.py` | `v4l2-ctl -l` parser on `fixtures/ov7251-6.18-ctrls.txt` | green | |
| ip3y | `test_ip3y.py` | unpacker against a reference packer | green | |
| K1 | `test_k1_compliance.py` | `v4l2-compliance -u <subdev>`, `-m /dev/media0`, `-d /dev/video2 -s 30`: Failed == 0; first run per kernel saves `baseline/k1-<target>-<release>.log` | red (see baseline logs) | subdev: patch 3; video: not an ov7251 issue (7 buffer failures in ipu3-cio2); media: disruptive, skipped by default: `v4l2-compliance -m` oopses the kernel in `ov5693_set_fmt` (divide error, front camera) and dies with SIGSEGV, so run it only before a reboot |
| K2 | `test_k2_controls.py` | `analogue_gain` present, `gain` absent | green | |
| K2 | | `analogue_gain` 200 reads back from 0x350a/0x350b while streaming | green | |
| K2 | | `camera_orientation` = 0 (Front), `camera_sensor_rotation` present, both read-only: `--set-ctrl` fails with Permission denied (EACCES) and the value stays | red | patch 5 |
| K2 | | `camera_sensor_rotation` = 90 (the sensor is mounted rotated) | red | patch 8 |
| K2 | | an exposure change delivers a control event carrying the new value (`--wait-for-event=ctrl=exposure`) | red | patch 3 |
| K2 | | `strobe_output_enable` is bool, default and value 0, not read-only, volatile or inactive | red | patch 7 |
| K3 | `test_k3_timing.py` | `link_frequency` = 319200000, `pixel_rate` = 63840000 | red | patch 1 |
| K3 | | PLL1 registers 0x30b0-0x30b5 read back while streaming = the 19.2 MHz xclk, 319.2 MHz table (01 85 04 0a 05; stock programs the 240 MHz one, 03 4b 01 0a 05) | red | patch 1 |
| K3 | | 90 frames at 30 fps take 2.6-3.6 s | green | |
| K3 | | `--set-subdev-fps` 60 / 90 reads back and the stream really runs at that rate | red (reads back, streams at 30) | patch 4 |
| K3 | | after 60 / 90 fps, `vertical_blanking` range 1-65055, default and value 380 / 92, `exposure` max = VTS - 20 (840 / 552); back at 30 fps 1244 and 1704 | red | patch 4 |
| K3 | | 0x380e/0x380f read back while streaming = the mode's VTS (1724, 860, 572) | 30: green, 60/90: red | patch 4 |
| K3 | | an active set_fmt after a 60 fps interval (VBLANK 380) gives a consistent mode: the interval read back, VBLANK and streaming VTS all agree (30 fps, 1244, 1724) | red | patch 4 |
| K4 | `test_k4_dark.py` | emitter off, exposure 1704, gain 128: 30-frame mean < 40 | green | |
| K5 | `test_k5_emitter.py` | `strobe_output_enable=1` before stream: mean > 2.5 x K4 dark, first 3 frames lit, dark again after reset to 0 | red | patch 7 |
| K7 | `test_k7_safety.py` | sensor `runtime_status` = suspended within 2 s of a stream ending | green | |
| K7 | | strobe set to 1 while idle reads back 1 and the sensor stays suspended | red | patch 7 |
| K8 | `test_k8_suspend.py` | suspend mid-stream: capture completes or exits cleanly, controls unchanged (manual wake) | skipped | |
| K9 | `test_k9_reload.py` | 10 x unbind/unload/load: ov7251 entity re-appears (new entity id), other entities unchanged, no WARNING/BUG/Oops/leak in `journalctl -k` | skipped | |
| K11 | `test_k11_strobe_registers.py` | strobe off, at 30, 60 and 90 fps: 0x3005 and 0x3b80-0x3b96 read back while streaming equal the stock mode-table values (0x3005 = 00, 0x3b81 = a5, span 0x3b8c-0x3b8f = 0x1a, ...) | green (on both modules: the patch 6 no-change proof) | |
| K11 | | strobe off: an exposure or VBLANK change while streaming writes exposure or VTS and leaves the span at 0x1a | green | |
| K11 | | strobe on before stream start, 3 exposures per mode: 0x3005 = 08, 0x3b81 = ff, span = clamp(exposure, 52, ceil(VTS x 45 / 100)): 10 -> 52, middle value unchanged, max -> 776 / 387 / 258 at 30 / 60 / 90 fps | red | patch 7 |
| K11 | | strobe on, while streaming: span follows exposure (504, 1000, 100, 10 -> 504, 776, 100, 52) and VBLANK (VTS 1100 clamps exposure to 1080, span 495, back to 776); toggling off/on/off rewrites 0x3005, 0x3b81 and the span; set while idle, still applied after a runtime suspend and a second stream | red | patch 7 |
| K10 | `test_k10_test_pattern.py` | test pattern decodes to the exact 8 colour bars on a Bayer mosaic (only 0/1023, rows period 2, bar means 1023 x k/4) | green | |
| E2E | `test_e2e.py` | One scenario in stack order: firmware link frequency and placement (1, 5), rotation 90 (8, separate test), control events (3), 60 fps (4), analogue gain (2), emitter on (7), 60 lit frames in 1 s with a real picture, emitter off and sensor suspended after. Aim the camera at the room before running: it writes the picture to `docs/e2e/ir-60fps-emitter-{on,off}.png` (or `$IRCAM_E2E_OUT`) | red (4 failures, each naming its patch) | all, rotation patch 8; green log `docs/phase3-7.2-test-2026-10-24-e2e.log`, red `docs/phase3-7.2-stock-red-2026-10-24.log` |

K9 unbinds `i2c-INT347E:00` from the ov7251 driver first (`modprobe -r` alone fails: the ipu3-cio2 v4l2_device holds a reference on the sensor module), then runs `sudo modprobe -r ov7251` and loads `$IRCAM_KO` with `sudo insmod` if set (e.g. `kernel/build/ov7251.ko`), else `sudo modprobe ov7251`.

Full-suite logs of this matrix on 7.2.12: stock `docs/phase3-7.2-stock-red-2026-10-24b.log` (40 failed, 27 passed), patched patches 1-7 `docs/phase3-7.2-test-2026-10-24b.log` (3 failed: the two patch 8 rotation tests and K1 video).

## Safety

Every stream is a `v4l2-ctl --stream-count=N` child with a timeout, so no test leaves a stream (and, on a patched driver, a lit emitter) running. Tests that turn the strobe on reset it to 0 in a `finally`. K7 checks the sensor powers down after streaming. Tests change only runtime state: the sensor -> CSI-2 link stays enabled, exposure/gain stay at the bench values (1704/128). Note that the driver resets exposure and gain to 504/16 on every format or frame-interval change.

## Phase 3b: glow-compare

`tools/glow_compare.py` compares the brightness of the IR emitter (a small bright blob) across phone videos filmed with locked exposure, e.g. our driver against Windows Hello. Per video it reports the median blob brightness (Gaussian blur, threshold max(200, 0.9 x frame max), connected component around the brightest pixel, mean of the raw pixels), the fraction of frames where the blob is present, and the dominant flicker frequency (Windows strobes on alternate frames, so 15 Hz at 30 fps; ours every frame). Run `python3 tools/glow_compare.py linux.mp4 windows1.mp4` to get `name n lit% median p10 p90 flicker_hz` per video plus `ratio <name>/<first> = x.xx` of medians. Unit tests: `pytest -q tests/test_glow_compare.py`.
