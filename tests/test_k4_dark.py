"""K4: with the emitter off (no strobe control, or 0) a dark scene stays dark."""
from conftest import DARK_MAX


def test_default_is_dark(dark_mean):
    assert dark_mean < DARK_MAX, \
        f"mean {dark_mean:.1f} counts with the emitter off (exposure 1704, gain 128), expected < {DARK_MAX} (Phase 0: ~20)"
