"""K9: the driver survives 10 unload/load cycles (disruptive, uses sudo)."""
import os
import subprocess
import time

import pytest

from conftest import subdev, wait_for

pytestmark = pytest.mark.disruptive


def test_module_reload_x10():
    """Run with IRCAM_DISRUPTIVE=1 after `sudo -v`. Loads $IRCAM_KO (e.g. kernel/build/ov7251.ko) with insmod if set,
    else `modprobe ov7251`. Asserts the ov7251 entity re-appears each time and the kernel log since the start has no
    WARNING / BUG / leak.
    """
    since = time.strftime("%Y-%m-%d %H:%M:%S")
    load = ["sudo", "insmod", os.environ["IRCAM_KO"]] if os.environ.get("IRCAM_KO") else ["sudo", "modprobe", "ov7251"]
    for i in range(10):
        subprocess.run(["sudo", "modprobe", "-r", "ov7251"], check=True)
        subprocess.run(load, check=True)
        subdev.cache_clear()
        assert wait_for(lambda: subdev() is not None, 5), f"ov7251 entity missing after reload {i + 1}"
    log = subprocess.run(["journalctl", "-k", "--since", since, "-o", "cat"], capture_output=True, text=True).stdout
    bad = [l for l in log.splitlines() if any(w in l for w in ("WARNING", "BUG", "leak"))]
    assert not bad, f"kernel log after 10 reloads: {bad[:10]}"
