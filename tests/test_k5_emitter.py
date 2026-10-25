"""K5: strobe_output_enable=1 set before streaming lights the emitter on alternate frames from the start (pattern 0xaa, the
Windows Hello pattern on this hardware: one lit frame, one dark)."""
import pytest

from conftest import DARK_MAX, STROBE, bench_exposure, capture, ctrl_info, frame_means, need_dark, set_ctrl

pytestmark = pytest.mark.needs_patch("6")


MISSING = f"{STROBE} missing: patch 6 adds V4L2_CID_FLASH_STROBE_OE to light the emitter"


@pytest.fixture(scope="module")
def lit(dark_mean):
    """Frame means of 30 frames with the strobe enabled before stream start, or None if the control is absent."""
    if ctrl_info(STROBE) is None:
        return None
    need_dark(dark_mean)
    bench_exposure()
    set_ctrl(STROBE, 1)
    try:
        return frame_means(capture(30))
    finally:
        set_ctrl(STROBE, 0)


def test_emitter_lights_alternate_frames(lit, dark_mean):
    assert lit is not None, MISSING
    is_lit = lit > 2.5 * dark_mean
    assert is_lit.any(), f"frame means {lit.round(1)} vs dark {dark_mean:.1f}: with {STROBE}=1 the emitter must strobe (Phase 0: x5)"
    assert is_lit[::2].all() != is_lit[1::2].all() and not (is_lit[::2].any() and is_lit[1::2].any()), \
        f"lit frames must alternate with dark ones (pattern 0xaa), got {is_lit.astype(int)}"


def test_lit_from_first_frames(lit, dark_mean):
    assert lit is not None, MISSING
    assert (lit[:2] > 2.5 * dark_mean).sum() == 1, \
        f"first frames {lit[:2].round(1)} vs dark {dark_mean:.1f}: one of the first two frames must be lit (the stream-start mode table must not clear the strobe)"


def test_dark_again_after_reset(lit):
    assert lit is not None, MISSING
    m = frame_means(capture(30)).mean()
    assert m < DARK_MAX, f"mean {m:.1f} after {STROBE}=0, expected < {DARK_MAX}: the emitter must switch off"
