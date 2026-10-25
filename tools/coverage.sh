#!/bin/bash
# Line coverage of the patched ov7251 driver: needs a kernel built with CONFIG_GCOV_KERNEL (memory/project_gcov_kernel.md).
# Builds the module with gcov instrumentation, swaps it in, runs the test suite, reads the counters back from debugfs and
# writes gcov's annotated source (##### marks a line never executed) to docs/coverage/. Undo: nothing persists, the stock
# module is restored at the end.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd -P)   # physical path: gcc records it, and debugfs mirrors it
build=$root/kernel/build
KDIR=${KDIR:-/home/antoine/build/kernel-gcov/kernel-ark}
out=${1:-$root/docs/coverage}
gcov_fs=/sys/kernel/debug/gcov
unset IRCAM_DISRUPTIVE   # K9 would unload the module and throw the counters away

sudo -n true || { echo "sudo -n must work"; exit 1; }
sudo -n test -d $gcov_fs || { echo "no $gcov_fs: boot the gcov kernel (uname -r: $(uname -r))"; exit 1; }
make -C "$build" KDIR="$KDIR" GCOV=1 clean all >/dev/null
restore() {
    echo i2c-INT347E:00 | sudo -n tee /sys/bus/i2c/drivers/ov7251/unbind >/dev/null 2>&1 || true
    sudo -n rmmod ov7251 2>/dev/null || true
    sudo -n modprobe ov7251
    echo "stock module restored, taint: [$(cat /sys/module/ov7251/taint)]"
}
trap restore EXIT
echo i2c-INT347E:00 | sudo -n tee /sys/bus/i2c/drivers/ov7251/unbind >/dev/null
sudo -n modprobe -r ov7251
sudo -n insmod "$build/ov7251.ko"
sleep 2
# probe ran before the counters could be reset, so rebind once: the report then counts one probe plus the suite
sudo -n sh -c "echo 1 > $gcov_fs/reset"
echo i2c-INT347E:00 | sudo -n tee /sys/bus/i2c/drivers/ov7251/unbind >/dev/null
echo i2c-INT347E:00 | sudo -n tee /sys/bus/i2c/drivers/ov7251/bind >/dev/null
sleep 2
set +e
# shellcheck disable=SC2086
(cd "$root" && python3 -m pytest -q tests/ ${PYTEST_ARGS:-} 2>&1 | tail -3)
set -e

tmp=$(mktemp -d)
sudo -n cat "$gcov_fs$build/ov7251.gcda" > "$tmp/ov7251.gcda"
cp "$build/ov7251.gcno" "$tmp/"
mkdir -p "$out"
(cd "$tmp" && gcov -o . "$build/ov7251.c" | grep -A1 "ov7251.c'" ) | tee "$out/summary.txt"
mv "$tmp"/ov7251.c.gcov "$out/ov7251.c.gcov"
rm -rf "$tmp"
echo "never executed lines: $(grep -c '#####' "$out/ov7251.c.gcov")  (see $out/ov7251.c.gcov)"
