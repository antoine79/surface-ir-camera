#!/usr/bin/env python3
"""Print this Surface's model and the rotation its firmware gives the infrared camera.

Read-only. Run it with:  sudo python3 ir-rotation-report.py
It needs iasl (package acpica-tools on Fedora and Debian/Ubuntu, acpica on Arch).

What it does, and nothing else:
1. reads the model name and SKU from /sys/class/dmi/id/;
2. copies the firmware's ACPI tables (DSDT and SSDT*) from /sys/firmware/acpi/tables/ into a
   temporary folder, decompiles them there with iasl, and deletes the folder at the end;
3. finds the infrared sensor (OV7251, ACPI ID INT347E) and prints byte 84 of its SSDB record,
   the "degree" field Linux reads the camera's rotation from (0 = normal, 1 = upside down).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SENSOR = "INT347E"
DEGREE = 84            # offset of the degree byte in the SSDB record (struct ipu_sensor_ssdb)
MCLK = slice(86, 90)   # sensor clock in Hz, little endian: a check that the offset is right


def dmi(field: str) -> str:
    return Path("/sys/class/dmi/id", field).read_text().strip()


def strip_comments(asl: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", asl, flags=re.S)


def device_blocks(asl: str):
    """Yield the text of every ACPI Device (...) { ... } block that names the sensor as its _HID."""
    for hid in re.finditer(r'Name \(_HID, "%s"\)' % SENSOR, asl):
        start = asl.rfind("Device (", 0, hid.start())
        depth, i = 0, asl.index("{", start)
        for j in range(i, len(asl)):
            depth += {"{": 1, "}": -1}.get(asl[j], 0)
            if depth == 0:
                yield asl[start:j + 1]
                break


def ssdb_bytes(device: str):
    """The SSDB record if the firmware gives it as a constant buffer, else None."""
    m = re.search(r"(?:Method|Name) \(SSDB.*?Buffer \(0x[0-9A-Fa-f]+\)\s*\{(.*?)\}", device, re.S)
    return bytes(int(b, 16) for b in re.findall(r"0x[0-9A-Fa-f]{2}", m.group(1))) if m else None


def main() -> None:
    print(f"Model: {dmi('product_name')}")
    print(f"SKU:   {dmi('product_sku')}")
    with tempfile.TemporaryDirectory() as tmp:
        for table in [Path("/sys/firmware/acpi/tables/DSDT"), *Path("/sys/firmware/acpi/tables").glob("SSDT*")]:
            Path(tmp, table.name + ".dat").write_bytes(table.read_bytes())
        subprocess.run("iasl -d *.dat", shell=True, cwd=tmp, capture_output=True)
        found = False
        for dsl in sorted(Path(tmp).glob("*.dsl")):
            for device in device_blocks(strip_comments(dsl.read_text(errors="replace"))):
                found = True
                name = device.split(")", 1)[0] + ")"
                data = ssdb_bytes(device)
                if data is None or len(data) <= MCLK.stop:
                    print(f"{name} in {dsl.stem}: SSDB is not a constant buffer here, please post this text:")
                    print(device)
                    continue
                degree, mclk = data[DEGREE], int.from_bytes(data[MCLK], "little")
                meaning = {0: "0 degrees", 1: "180 degrees"}.get(degree, "unknown")
                print(f"{name} in {dsl.stem}: firmware rotation byte {degree} ({meaning}), sensor clock {mclk} Hz")
        if not found:
            print(f"No {SENSOR} device in the ACPI tables: this Surface has no OV7251 infrared camera described.")


if __name__ == "__main__":
    if os.geteuid() != 0:
        sys.exit("Please run it with sudo: the ACPI tables are readable by root only.")
    if not shutil.which("iasl"):
        sys.exit("Please install iasl first (package acpica-tools, or acpica on Arch).")
    main()
