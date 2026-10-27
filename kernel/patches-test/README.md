# Test patches for the 319.2 MHz link (Surface Pro 7+ report)

Two throwaway patches for D. Manresa's report on patch 1 of the series ("media: i2c: ov7251: Fix link frequency index"): on a Surface Pro 7+ (IPU6), the 319.2 MHz link that patch 1 enables drops most frames, while the same link runs clean on a Surface Book 2 (IPU3). Not for merging as is.

- `0001-media-i2c-ov7251-Use-in-range-PLL1-dividers-for-the-.patch`: in the PLL1 table for a 19.2 MHz clock and the 319.2 MHz link, divide before multiplying (pre-divider 0x30B4 = 0x04 and divider 0x30B1 = 0x01, instead of 0x01 and 0x04). The link speed stays 638.4 Mbps; what changes is the PLL1 multiplier output (the VCO of figure 2-12 in the OV7251 datasheet): 638.4 MHz instead of 2553.6 MHz, inside the 300 to 800 MHz range of table 2-11. These are the values the Windows driver programs for Windows Hello on the Surface Book 2.
- `0002-media-i2c-ov7251-Use-the-Windows-MIPI-pixel-clock-pe.patch`: on top of the first, write 0x1f instead of 0x19 to register 0x4837 (PCLK_PERIOD) in the three mode tables, as the Windows driver does in that mode.

Apply with `git am`, in order, on a tree that already has patch 1 of the series. Test the first patch alone, then both.

Measured on a Surface Book 2 (kernel 7.2, IPU3): each build streamed 3 runs of 155/155 buffers at 30 fps with no dropped frame and no CSI-2 error line, the same as the unmodified driver, so this machine cannot tell the builds apart. Log: `docs/phase3-7.2-link-stress-2026-10-27.log` on `main`; script: `tools/link-stress.py` (IPU3 node names).
