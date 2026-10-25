"""K8: suspend/resume in the middle of a stream (disruptive, needs a human to wake the machine)."""
import subprocess
import tempfile

import pytest

from conftest import STROBE, VIDEO, ctrl_info, set_ctrl

pytestmark = pytest.mark.disruptive


def test_suspend_mid_stream(graph):
    """Manual procedure (IRCAM_DISRUPTIVE=1, at the machine):
    1. this test starts a 300-frame capture (10 s at 30 fps) and runs `systemctl suspend` 3 s in;
    2. wake the machine with the power button;
    3. the capture must either complete or v4l2-ctl must exit with a clean error (no hang, no kernel splat),
       and the sensor controls must be unchanged.
    """
    names = ["exposure", "analogue_gain", "vertical_blanking"]
    if ctrl_info(STROBE):  # patch 6: the emitter is on across the suspend and the control must survive it
        set_ctrl(STROBE, 1)
        names.append(STROBE)
    before = {n: ctrl_info(n)["value"] for n in names}
    with tempfile.TemporaryDirectory() as d:
        p = subprocess.Popen(["v4l2-ctl", "-d", VIDEO, "--stream-mmap", "--stream-count=300", f"--stream-to={d}/f.raw"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            subprocess.run(["sleep", "3"])
            subprocess.run(["systemctl", "suspend"], check=True)
            out, _ = p.communicate(timeout=600)  # time for the human to wake the machine
        finally:
            p.kill()
            after = {n: ctrl_info(n)["value"] for n in names}
            if ctrl_info(STROBE):
                set_ctrl(STROBE, 0)
    assert p.returncode >= 0, f"v4l2-ctl died from signal {-p.returncode} across suspend:\n{out[-2000:]}"
    assert after == before, f"sensor controls changed across suspend/resume: {before} -> {after}"
