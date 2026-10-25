"""K1: v4l2-compliance reports no failure on the sensor subdev, the media device and the capture node.

The first run on a kernel release saves the full output as tests/baseline/k1-<target>-<release>.log.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

from conftest import MEDIA, VIDEO, ctrl_info, parse_ctrls, run, sd, set_ctrl, set_fps, setup_graph

BASELINE = Path(__file__).parent / "baseline"
MEDIA_OOPS = "v4l2-compliance -m oopses ov5693_set_fmt (divide error), front camera; run only before a reboot"
TOTAL = re.compile(r"Total.*: (\d+), Succeeded: (\d+), Failed: (\d+), Warnings: (\d+)")


@pytest.mark.parametrize("target, args", [
    pytest.param("subdev", lambda: ["-u", sd()], marks=pytest.mark.needs_patch("3")),
    pytest.param("media", lambda: ["-m", MEDIA], marks=pytest.mark.disruptive(reason=MEDIA_OOPS)),
    ("video", lambda: ["-d", VIDEO, "-s", "30"]),
], ids=["subdev", "media", "video"])
def test_compliance(graph, target, args):
    before = parse_ctrls(run("v4l2-ctl", "-d", sd(), "-l"))
    try:
        p = subprocess.run(["v4l2-compliance", *args()], capture_output=True, text=True, timeout=300)
    finally:  # v4l2-compliance leaves controls (e.g. test_pattern), formats and the frame interval changed
        set_fps(30)
        setup_graph()  # resets exposure and gain, so restore the controls after it
        for name, c in before.items():
            if "read-only" not in c["flags"] and ctrl_info(name)["value"] != c["value"]:
                set_ctrl(name, c["value"])
    out = p.stdout + p.stderr
    log = BASELINE / f"k1-{target}-{os.uname().release}.log"
    if not log.exists():
        log.parent.mkdir(exist_ok=True)
        log.write_text(f"$ v4l2-compliance {' '.join(args())}\n# exit status {p.returncode}\n{out}")
    assert p.returncode >= 0, f"v4l2-compliance {target} crashed (signal {-p.returncode}) before finishing, see {log.name}"
    totals = TOTAL.findall(out)
    assert totals, f"v4l2-compliance {target} printed no final Total line (exit status {p.returncode}, a negative one is a crash)"
    failed = [l.strip() for l in out.splitlines() if "FAIL" in l or "fail:" in l]
    assert int(totals[-1][2]) == 0, f"v4l2-compliance {target}: {totals[-1]} (total, ok, failed, warn); failures: {failed}"
