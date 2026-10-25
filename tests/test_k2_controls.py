"""K2: the sensor exposes the standard control set libcamera expects."""
import re
import subprocess
import time

import pytest

from conftest import GAIN_REG, STROBE, ctrl, ctrl_info, read_reg, sd, set_ctrl, streaming


def test_analogue_gain_not_gain(graph):
    assert ctrl_info("analogue_gain") is not None, "analogue_gain (V4L2_CID_ANALOGUE_GAIN) missing"
    assert ctrl_info("gain") is None, "gain must not exist: the sensor gain is V4L2_CID_ANALOGUE_GAIN"


def test_analogue_gain_written_to_sensor(graph):
    try:
        set_ctrl("analogue_gain", 200)
        with streaming():
            got = read_reg(GAIN_REG, 2)
    finally:
        set_ctrl("analogue_gain", 16)
    assert got == 200, f"0x350a/0x350b = {got} with analogue_gain 200: the ANALOGUE_GAIN handler must write the gain (patch 2)"


FWNODE = "patch 4 registers the fwnode controls (v4l2_ctrl_new_fwnode_properties)"


@pytest.mark.needs_patch("4")
def test_camera_orientation_is_front(graph):
    c = ctrl_info("camera_orientation")
    assert c is not None, f"camera_orientation missing: {FWNODE}"
    assert (c["value"], c["label"]) == (0, "Front"), f"camera_orientation {c}, expected 0 (Front) from the ACPI _PLD"


@pytest.mark.needs_patch("4")
def test_camera_sensor_rotation_present(graph):
    assert ctrl_info("camera_sensor_rotation") is not None, f"camera_sensor_rotation missing: {FWNODE}"


@pytest.mark.needs_patch("7")
def test_camera_sensor_rotation_is_90(graph):
    c = ctrl_info("camera_sensor_rotation")
    assert c is not None and c["value"] == 90, \
        f"camera_sensor_rotation {c and c['value']}, expected 90: the sensor is mounted rotated, the ACPI _PLD says 0 (patch 7, ipu-bridge DMI quirk)"


@pytest.mark.needs_patch("4")
@pytest.mark.parametrize("name, value", [("camera_orientation", 1), ("camera_sensor_rotation", 90)])
def test_fwnode_controls_are_read_only(graph, name, value):
    c = ctrl_info(name)
    assert c is not None, f"{name} missing: {FWNODE}"
    assert "read-only" in c["flags"], f"{name} flags {c['flags']}, expected read-only"
    p = subprocess.run(["v4l2-ctl", "-d", sd(), f"--set-ctrl={name}={value}"], capture_output=True, text=True)
    assert p.returncode != 0 and "Permission denied" in p.stderr + p.stdout, \
        f"setting {name}={value} must fail with EACCES (Permission denied), got exit {p.returncode}: {p.stderr.strip()}"
    assert ctrl(name) == c["value"], f"{name} changed to {ctrl(name)} after a refused write"


@pytest.mark.needs_patch("2")
def test_exposure_change_sends_event_with_value(graph):
    old = ctrl("exposure")
    new = 432 if old != 432 else 433
    waiter = subprocess.Popen(["v4l2-ctl", "-d", sd(), "--wait-for-event=ctrl=exposure"],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        time.sleep(0.5)
        set_ctrl("exposure", new)
        out, _ = waiter.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        waiter.kill()
        pytest.fail("no control event within 5 s of changing exposure (patch 2)")
    finally:
        set_ctrl("exposure", old)
    got = re.search(r"value: (-?\d+)", out)
    assert waiter.returncode == 0 and got, f"no exposure control event (patch 2 adds subscribe_event):\n{out.strip()}"
    assert int(got.group(1)) == new, f"event carries exposure {got.group(1)}, set {new}:\n{out.strip()}"


@pytest.mark.needs_patch("6")
def test_strobe_output_enable_is_bool_default_off(graph):
    c = ctrl_info(STROBE)
    assert c is not None, f"{STROBE} (V4L2_CID_FLASH_STROBE_OE) missing: patch 6 adds it to drive the IR emitter"
    assert (c["type"], c["default"], c["value"]) == ("bool", 0, 0), f"{STROBE} must be a bool defaulting to 0 (emitter off), got {c}"
    assert not {"read-only", "write-only", "volatile", "inactive", "disabled"} & set(c["flags"]), \
        f"{STROBE} flags {c['flags']}: it must be a plain writable control"
