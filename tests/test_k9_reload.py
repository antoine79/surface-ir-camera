"""K9: the driver survives 10 unload/load cycles (disruptive, uses sudo).

`modprobe -r ov7251` alone fails with "Module ov7251 is in use": while the subdev is registered with the ipu3-cio2
v4l2_device, v4l2_device_register_subdev() holds a reference on the sensor module (try_module_get()). So each cycle
first unbinds the I2C device, which unregisters the subdev and drops that reference, then unloads and reloads the
module; the reload probes the device again and v4l2-async re-attaches it to cio2. The ov7251 entity comes back with a
new entity id each time (e.g. 39 -> 67); the other sensors' entities must not change.
"""
import os
import re
import subprocess
import time

import pytest

from conftest import MEDIA, run, runtime_status, subdev, wait_for

pytestmark = pytest.mark.disruptive

DEV = "i2c-INT347E:00"
UNBIND = "/sys/bus/i2c/drivers/ov7251/unbind"


def other_entities() -> set[str]:
    """'- entity N: name' lines of the media graph, minus the OV7251."""
    return {l for l in run("media-ctl", "-d", MEDIA, "-p").splitlines()
            if re.match(r"- entity \d+: ", l) and "ov7251" not in l}


def test_module_reload_x10():
    """Run with IRCAM_DISRUPTIVE=1 after `sudo -v`. Loads $IRCAM_KO (e.g. kernel/build/ov7251.ko) with insmod if set,
    else `modprobe ov7251`. Asserts the ov7251 entity re-appears each time, the other entities are unchanged, and the
    kernel log since the start has no WARNING / BUG / Oops / leak.
    """
    since = time.strftime("%Y-%m-%d %H:%M:%S")
    others = other_entities()
    load = ["sudo", "insmod", os.environ["IRCAM_KO"]] if os.environ.get("IRCAM_KO") else ["sudo", "modprobe", "ov7251"]
    for i in range(10):
        assert not subprocess.run(["pgrep", "v4l2-ctl"], capture_output=True).stdout, "a v4l2-ctl is running"
        assert wait_for(lambda: runtime_status() == "suspended", 3), f"sensor not suspended before reload {i + 1}"
        subprocess.run(["sudo", "tee", UNBIND], input=DEV, text=True, capture_output=True, check=True)
        subprocess.run(["sudo", "modprobe", "-r", "ov7251"], check=True)
        subprocess.run(load, check=True)
        subdev.cache_clear()
        assert wait_for(lambda: subdev() is not None, 5), f"ov7251 entity missing after reload {i + 1}"
        assert other_entities() == others, f"other media entities changed after reload {i + 1}"
    log = subprocess.run(["journalctl", "-k", "--since", since, "-o", "cat"], capture_output=True, text=True).stdout
    bad = [l for l in log.splitlines() if any(w in l for w in ("WARNING", "BUG", "Oops", "leak"))]
    assert not bad, f"kernel log after 10 reloads: {bad[:10]}"
