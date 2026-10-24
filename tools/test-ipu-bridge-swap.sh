#!/bin/bash
# Test patch 8 (ipu-bridge: 90 degree rotation for the Surface Book 2 infrared
# sensor) on kernel-surface 7.2.12 with kernel/build/ipu-bridge.ko.
#
# Why this needs a reboot (no in-place module swap):
#   cio2_pci_probe() calls ipu_bridge_init(), which builds the software nodes
#   (including each sensor's "rotation" property) in a kzalloc'ed struct
#   ipu_bridge that is never freed: cio2_pci_remove() does not tear it down and
#   ipu-bridge has no exit hook. The comment in ipu_bridge_init() says this is
#   on purpose, so the nodes survive module unloads. On the next cio2 probe,
#   ipu_bridge_init() first calls ipu_bridge_check_fwnode_graph() on the cio2
#   device, finds the old nodes through its secondary fwnode and returns 0
#   without building anything. So unbinding the sensors, unloading ipu3-cio2
#   and ipu_bridge, insmod'ing the new ipu-bridge.ko and reloading ipu3-cio2
#   would bring the cameras back with the OLD rotation (0) and prove nothing.
#   The new module must be the one loaded at boot.
#
# Usage, as root, from the surface-ir-camera repo:
#   tools/test-ipu-bridge-swap.sh install   # put ipu-bridge.ko in updates/, depmod
#   reboot into 7.2.12-1.surface.fc43.x86_64
#   tools/test-ipu-bridge-swap.sh check     # swap in the patched ov7251, print controls
#   tools/test-ipu-bridge-swap.sh undo      # remove it from updates/, depmod, then reboot
#
# Expected from check: ov7251 camera_sensor_rotation 90, ov5693 and ov8865 180.
# The 7.2.12 ipu-bridge has no rotation debug print; the kernel log shows only
# "Found supported sensor" lines.
set -euo pipefail
set -x

KVER=7.2.12-1.surface.fc43.x86_64
REPO=$(cd "$(dirname "$0")/.." && pwd)
KO=$REPO/kernel/build/ipu-bridge.ko
OV7251_KO=$REPO/kernel/build/ov7251.ko
DEST=/lib/modules/$KVER/updates/ipu-bridge.ko
INITRD=/boot/initramfs-$KVER.img

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }

in_initrd() { lsinitrd "$INITRD" | grep -q 'ipu-bridge\.ko'; }

case "${1:-}" in
install)
	modinfo -F vermagic "$KO" | grep -q "^$KVER "
	install -D -m 0644 "$KO" "$DEST"
	depmod -a "$KVER"
	modinfo -k "$KVER" -n ipu_bridge   # must print $DEST
	# ipu-bridge is loaded from the initramfs if it is in there.
	if in_initrd; then dracut -f --kver "$KVER"; fi
	echo "Now reboot into $KVER and run: $0 check"
	;;
check)
	[ "$(uname -r)" = "$KVER" ]
	grep -q E /sys/module/ipu_bridge/taint || { echo "stock ipu_bridge loaded, run install first" >&2; exit 1; }
	RELAY=$(systemctl is-active mipi-camera-relay.service || true)
	echo "relay was: $RELAY"
	# Restart the relay on every exit path, including a failed step.
	trap '[ "$RELAY" = active ] && systemctl start mipi-camera-relay.service; systemctl is-active mipi-camera-relay.service || true' EXIT
	systemctl stop mipi-camera-relay.service
	# Stock 7.2.12 ov7251 has no rotation control (patch 5): swap in the
	# patched one the K9 way (unbind drops cio2's module reference first).
	if ! grep -q E /sys/module/ov7251/taint; then
		echo i2c-INT347E:00 > /sys/bus/i2c/drivers/ov7251/unbind
		modprobe -r ov7251
		insmod "$OV7251_KO"
	fi
	for drv in ov7251 ov5693 ov8865; do
		for i in $(seq 50); do
			sd=$(grep -l "^$drv " /sys/class/video4linux/v4l-subdev*/name || true)
			[ -n "$sd" ] && break
			sleep 0.1
		done
		[ -n "$sd" ] || { echo "$drv subdev missing" >&2; exit 1; }
		dev=/dev/$(basename "$(dirname "$sd")")
		echo "== $drv $dev"
		v4l2-ctl -d "$dev" -l | grep -E 'orientation|rotation' || echo "(no orientation/rotation controls)"
	done
	journalctl -k -b --no-pager | grep -i -E 'ipu|rotation|INT347E' || true
	;;
undo)
	# Restores the stock signed ipu-bridge (and, after the reboot, the stock
	# ov7251 too). Run on any kernel; takes effect at the next 7.2.12 boot.
	rm -f "$DEST"
	depmod -a "$KVER"
	modinfo -k "$KVER" -n ipu_bridge   # must print .../kernel/drivers/media/pci/intel/ipu-bridge.ko.xz
	if in_initrd; then dracut -f --kver "$KVER"; fi
	echo "Reboot to load the stock ipu-bridge."
	;;
*)
	echo "usage: $0 install|check|undo" >&2
	exit 2
	;;
esac
