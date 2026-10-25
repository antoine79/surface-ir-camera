# What the Windows OV7251 driver does with the strobe

Read on 2026-10-25 from the driver installed on esteban's Windows partition (`nvme0n1p3`, mounted read-only): `Windows/System32/drivers/ov7251.sys`, Intel, DriverVer 05/12/2021, version 30.18305.6.5127, sha256 `3cc8b15dc2c3c1a3ea8520114f92e783ae1e07ad254bdb892a60e8989f3b89cf`, 155808 bytes. Tool: Ghidra 12.2 headless import, then the decompiled functions that use the constants 0x3b81, 0x3b8c, 0x3005, 52 and 776 were read, and the four register tables in the file's data were parsed (16-byte entries: flag, count 1, register, value). Facts only below: no code is copied. The driver files and the decompiler output are not committed (proprietary); they live in `~/opt/win-ov7251/` and `~/opt/win-ov7251-decompiled/`.

## 1. Pulse length

The exposure update function (one call per frame from the camera stack, address 0x1400064cc) writes, in this order:

- frame length `0x380e/0x380f` = max(minimum frame length, exposure + 20, requested frame length)
- exposure `0x3500..0x3502` = exposure lines << 4
- analogue gain `0x350a/0x350b`
- digital gain `0x3400..`
- strobe span `0x3b8c..0x3b8f` = clamp(exposure, 52, 776), as a 32-bit big-endian value

So on Windows the pulse equals the exposure, bounded to 52 to 776 lines, in every mode, re-written with every exposure change. There is no duty-cycle rule: in the 862-line 60 fps mode a 776-line pulse covers 90% of the frame. Our patch 6 uses the same clamp plus a 45% duty cap, which is stricter than Windows at 60 and 90 fps and identical at 30 fps.

## 2. Frame pattern

Four streaming modes, each a table of 139 register writes:

| table | window (0x3808..0x380b) | frame length 0x380e/f | 0x3b81 pattern | 0x3b96 | span default 0x3b8c..f | 0x3b8b |
|---|---|---|---|---|---|---|
| T0 (file offset 0x175fc) | 640 x 480 | 522 | 0xff every frame | 0x40 | 26 | 5 |
| T1 (0x17ebc) | 640 x 480 | 522 | 0xff | 0x40 | 26 | 5 |
| T2 (0x1877c) | 648 x 488 | 1724 (30 fps) | 0xaa alternate frames | 0xc0 | 776 | 0 |
| T3 (0x1903c) | 648 x 488 | 862 (60 fps) | 0xaa | 0xc0 | 776 | 0 |

T0 and T1, and T2 and T3, differ only in frame length (and the PLL/MIPI timing registers 0x30b1, 0x30b4, 0x30b5, 0x4837 differ between the pairs). The pattern is therefore chosen by the mode the camera stack selects, not computed. The live register dump taken on a Surface Book 2 during a Windows Hello sign-in (linux-surface issue 739: 0x3b81 = 0xaa, 0x3b96 = 0xc0, span 331) matches T2 exactly: Windows Hello on this hardware runs the 648 x 488, 30 fps, alternate-frame mode. The 0xff modes (reported from the Surface Pro 7+ driver disassembly in linux-surface PR 2252) are the two short-frame 640 x 480 modes.

The driver also exposes a property (id 0x27 in its get/set property handlers, addresses 0x140006154 and 0x1400067a0) that reads or writes 0x3b81 directly, so the camera stack above the sensor driver can change the pattern at run time. Nothing in the sensor driver itself calls it with a constant.

## 3. Other strobe registers, idle behaviour

- `0x3005` = 0x08 (STROBE pad output enable) in all four tables: on Windows the pad is enabled whenever the sensor streams.
- `0x3b80` 0, `0x3b82` 0x10, `0x3b84` 0x08, `0x3b86` 0x01, `0x3b88..0x3b8a` 0, `0x3b94` 0x05, `0x3b95` 0xf2 in all tables: the same values the Linux mode tables write.
- `0x3b96`: 0x40 in the every-frame modes, 0xc0 in the alternate-frame modes. The meaning of bit 7 is not known to us.
- `0x3b8b` (lowest byte of the strobe shift): 5 in the every-frame modes, 0 in the alternate-frame modes.
- The span is only written from the per-frame exposure path, and the pad enable only from the mode tables, so the emitter is never driven while the sensor is idle.
- A registry value `IRFlashLedIntensity` exists in the driver's strings; its use was not traced.

## Consequences for the series

- Patch 6's rule "span = exposure, clamped to 52..776" is the Windows rule. The 45% duty cap on top is ours, stricter than Windows at 60 and 90 fps.
- The cover letter's two Windows facts are both from this driver: 0xaa is the Windows Hello mode on the Book 2, 0xff is a different (short frame, 640 x 480) mode. Keeping 0xff as our default is a defensible choice (Windows uses it), but the mode Windows Hello actually uses on this unit is the alternate one.
- The 648 x 488 window and the 20-line exposure margin are differences from the Linux driver that do not affect the strobe.
