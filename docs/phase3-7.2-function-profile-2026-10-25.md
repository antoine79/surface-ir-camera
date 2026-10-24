# Function profile of the patched ov7251 module during the test suite (7.2.12, 2026-10-25)

Kernel function profiler (`/sys/kernel/tracing/function_profile_enabled`, filter `:mod:ov7251`) switched on after insmod, then `pytest -q tests/` (4 failed, 59 passed, 7 skipped: rotation-90 x2 wait for patch 8, K4 bright room, cio2 compliance; K5 skipped bright room, K8/K9 disruptive). Only functions the compiler kept as calls appear: 23 traceable of 113 symbols, the rest are inlined. Line coverage needs the gcov kernel, see tools/coverage.sh.

Called (count, function):

```
35 ov7251_get_format
29 ov7251_get_frame_interval
422 ov7251_init_state
35 ov7251_pll_configure
33 ov7251_regulators_disable
375 ov7251_s_ctrl
426 ov7251_set_format
53 ov7251_set_frame_interval
33 ov7251_set_power_off
33 ov7251_set_power_on
71 ov7251_set_strobe_span
70 ov7251_s_stream
4231 ov7251_write_reg
184 ov7251_write_seq_regs
```

Not called during the suite (ran before the profiler was on, at insmod: probe, check_hwcfg, init_ctrls, read_reg, or not exercised: enum_mbus_code, enum_frame_size, enum_frame_ival, get_selection, remove):

```
ov7251_check_hwcfg
ov7251_enum_frame_ival
ov7251_enum_frame_size
ov7251_enum_mbus_code
ov7251_get_selection
ov7251_init_ctrls.constprop.0
ov7251_probe
ov7251_read_reg
ov7251_remove
```
