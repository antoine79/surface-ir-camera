"""K2: the sensor exposes the standard control set libcamera expects."""
import pytest

from conftest import STROBE, ctrl_info


def test_analogue_gain_not_gain(graph):
    assert ctrl_info("analogue_gain") is not None, "analogue_gain (V4L2_CID_ANALOGUE_GAIN) missing"
    assert ctrl_info("gain") is None, "gain must not exist: the sensor gain is V4L2_CID_ANALOGUE_GAIN"


@pytest.mark.needs_patch("5")
@pytest.mark.parametrize("name", ["camera_orientation", "camera_sensor_rotation"])
def test_fwnode_controls_are_front_and_0(graph, name):
    c = ctrl_info(name)
    assert c is not None, f"{name} missing: patch 5 registers the fwnode controls (v4l2_ctrl_new_fwnode_properties)"
    assert c["value"] == 0, f"{name} = {c['value']}, expected 0 (front-facing, not rotated)"


@pytest.mark.needs_patch("7")
def test_strobe_output_enable_is_bool_default_off(graph):
    c = ctrl_info(STROBE)
    assert c is not None, f"{STROBE} (V4L2_CID_FLASH_STROBE_OE) missing: patch 7 adds it to drive the IR emitter"
    assert (c["type"], c["default"]) == ("bool", 0), f"{STROBE} must be a bool defaulting to 0 (emitter off), got {c}"
