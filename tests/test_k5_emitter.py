"""K5: strobe_output_enable=1 set before streaming lights the emitter on every frame from the start."""
import pytest

from conftest import DARK_MAX, STROBE, bench_exposure, capture, ctrl_info, frame_means, need_dark, set_ctrl

pytestmark = pytest.mark.needs_patch("7")


MISSING = f"{STROBE} missing: patch 7 adds V4L2_CID_FLASH_STROBE_OE to light the emitter"


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


def test_emitter_lights_the_scene(lit, dark_mean):
    assert lit is not None, MISSING
    assert lit.mean() > 2.5 * dark_mean, \
        f"lit mean {lit.mean():.1f} vs dark {dark_mean:.1f}: with {STROBE}=1 the emitter must strobe (Phase 0: x5)"


def test_lit_from_first_frames(lit, dark_mean):
    assert lit is not None, MISSING
    assert (lit[:3] > 2.5 * dark_mean).all(), \
        f"first frames {lit[:3].round(1)} vs dark {dark_mean:.1f}: the stream-start mode table must not clear the strobe"


def test_dark_again_after_reset(lit):
    assert lit is not None, MISSING
    m = frame_means(capture(30)).mean()
    assert m < DARK_MAX, f"mean {m:.1f} after {STROBE}=0, expected < {DARK_MAX}: the emitter must switch off"
