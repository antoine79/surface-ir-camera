# Line coverage of the patched ov7251 driver

Measured 2026-10-25 on kernel 7.2.12-gcov (kernel-surface 7.2.12 rebuilt with CONFIG_GCOV_KERNEL, see `~/projects/surface/memory/project_gcov_kernel.md`) with `tools/coverage.sh`: the module from `kernel/backport/ov7251.c` built with gcov instrumentation, one probe plus the full suite (`pytest tests/`, disruptive tests excluded: 61 passed, 7 skipped, 2 failed for known reasons, the capture-driver compliance and a bright room). `ov7251.c.gcov` is gcov's annotated source: the first column is the execution count, `#####` marks a line that never ran, `-` a line with no code.

| | executable lines | executed | never |
|---|---|---|---|
| whole driver | 557 | 416 (74.7%) | 141 |
| lines added or changed by patches 1 to 7 | 43 | 38 | 5 |

The 5 patched lines never executed are error returns: the three `goto exit` after a failed control range update or control write in set_format and set_frame_interval (patch 4), and the "could not set strobe defaults" branch at stream start (patch 6). All four fire only when an I2C write or a control-framework call fails.

The 141 unexecuted lines of the whole driver, by kind:

- about 90 are error paths: I2C read and write failures, regulator and clock failures, probe failures (missing clock, wrong chip id, firmware without a matching link frequency), PLL configuration failure at stream start. Not reachable without fault injection.
- 39 are the format enumeration callbacks and crop selection (`enum_mbus_code`, `enum_frame_size`, `enum_frame_ival`, `get_selection`): stock code, untouched by the series, reachable from user space with `v4l2-ctl --list-subdev-mbus-codes`, `--list-subdev-framesizes`, `--list-subdev-frameintervals`, `--get-subdev-selection`. Candidate for one more test.
- the two lines that set the horizontal and vertical flip bits: the suite never sets the flip controls to 1.
- `remove` and the module exit: the instrumented module is unloaded after the counters are read, so its unload is never counted.
