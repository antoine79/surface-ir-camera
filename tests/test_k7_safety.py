"""K7: the emitter cannot stay lit: the sensor powers down when no stream runs."""
import time

import pytest

from conftest import STROBE, capture, ctrl, ctrl_info, runtime_status, set_ctrl, wait_for


def test_suspended_after_capture(graph):
    capture(5)
    assert wait_for(lambda: runtime_status() == "suspended", 2), \
        f"sensor runtime_status '{runtime_status()}' 2 s after the stream stopped, expected suspended (powered off)"


@pytest.mark.needs_patch("6")
def test_strobe_set_while_idle_keeps_sensor_off(graph):
    assert ctrl_info(STROBE) is not None, f"{STROBE} missing: patch 6 adds V4L2_CID_FLASH_STROBE_OE"
    try:
        set_ctrl(STROBE, 1)
        assert ctrl(STROBE) == 1, f"{STROBE} did not read back 1 while idle"
        seen = set()
        for _ in range(10):
            seen.add(runtime_status())
            time.sleep(0.1)
        assert seen == {"suspended"}, f"runtime_status {seen} with {STROBE}=1 and no stream: setting it must not power on"
    finally:
        set_ctrl(STROBE, 0)
