#!/bin/bash
# Line coverage of the patched ov7251 driver: needs a kernel built with CONFIG_GCOV_KERNEL (memory/project_gcov_kernel.md).
# Builds the module with gcov instrumentation, swaps it in, runs the test suite, reads the counters back from debugfs and
# writes gcov's annotated source (##### marks a line never executed) to docs/coverage/. Undo: nothing persists, the stock
# module is restored at the end.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
build=$root/kernel/build
KDIR=${KDIR:-/lib/modules/$(uname -r)/build}
out=${1:-$root/docs/coverage}
gcov_fs=/sys/kernel/debug/gcov

sudo -n test -d $gcov_fs || { echo "no $gcov_fs: boot the gcov kernel (uname -r: $(uname -r))"; exit 1; }
make -C "$build" KDIR="$KDIR" GCOV=1 clean all >/dev/null
echo i2c-INT347E:00 | sudo -n tee /sys/bus/i2c/drivers/ov7251/unbind >/dev/null
sudo -n modprobe -r ov7251
sudo -n insmod "$build/ov7251.ko"
sleep 2
sudo -n sh -c "echo 1 > $gcov_fs/reset"   # drop the counts of probe, so the report shows what the tests exercise... see below
# ...except that probe only runs at insmod: reload once more so probe is counted too, then run the suite.
echo i2c-INT347E:00 | sudo -n tee /sys/bus/i2c/drivers/ov7251/unbind >/dev/null
echo i2c-INT347E:00 | sudo -n tee /sys/bus/i2c/drivers/ov7251/bind >/dev/null
sleep 2
set +e
(cd "$root" && python3 -m pytest -q tests/ "${PYTEST_ARGS:-}" 2>&1 | tail -3)
set -e

tmp=$(mktemp -d)
sudo -n cat "$gcov_fs$build/ov7251.gcda" > "$tmp/ov7251.gcda"
cp "$build/ov7251.gcno" "$tmp/"
mkdir -p "$out"
(cd "$tmp" && gcov -o . "$build/ov7251.c" | grep -A1 "ov7251.c'" ) | tee "$out/summary.txt"
mv "$tmp"/ov7251.c.gcov "$out/ov7251.c.gcov"
rm -rf "$tmp"
echo "never executed lines: $(grep -c '#####' "$out/ov7251.c.gcov")  (see $out/ov7251.c.gcov)"

echo i2c-INT347E:00 | sudo -n tee /sys/bus/i2c/drivers/ov7251/unbind >/dev/null
sudo -n rmmod ov7251
sudo -n modprobe ov7251
echo "stock module restored, taint: [$(cat /sys/module/ov7251/taint)]"
