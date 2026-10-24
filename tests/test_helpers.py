"""Offline tests for the conftest helpers: parse a saved `v4l2-ctl -l` listing (stock 6.18 ov7251)."""
from pathlib import Path

from conftest import frame_means, parse_ctrls

SAMPLE = (Path(__file__).parent / "fixtures" / "ov7251-6.18-ctrls.txt").read_text()


def test_parse_int_control():
    c = parse_ctrls(SAMPLE)["exposure"]
    assert (c["type"], c["min"], c["max"], c["step"], c["default"], c["value"]) == ("int", 1, 1704, 1, 1704, 1704)
    assert c["flags"] == ["has-min-max"]


def test_parse_bool_has_no_range():
    c = parse_ctrls(SAMPLE)["vertical_flip"]
    assert (c["type"], c["min"], c["max"], c["default"], c["value"]) == ("bool", None, None, 0, 0)


def test_parse_menu_and_intmenu_keep_the_label():
    ctrls = parse_ctrls(SAMPLE)
    assert (ctrls["test_pattern"]["value"], ctrls["test_pattern"]["label"]) == (0, "Disabled")
    lf = ctrls["link_frequency"]
    assert (lf["type"], lf["value"], lf["label"]) == ("intmenu", 0, "240000000 0xe4e1c00")
    assert lf["flags"] == ["read-only", "has-min-max"]


def test_parse_int64_and_absent_control():
    ctrls = parse_ctrls(SAMPLE)
    assert ctrls["pixel_rate"]["value"] == 48000000
    assert "gain" not in ctrls and "camera_orientation" not in ctrls


def test_frame_means():
    import numpy as np

    arr = np.stack([np.full((2, 3), v, np.uint16) for v in (1, 5)])
    assert frame_means(arr).tolist() == [1.0, 5.0]
