#!/bin/bash
# Cold-start check of the OV7251 clock/reset register values (30 Oct 2026, see memory/project_surfacebook2_ir_camera.md).
# Loads an ov7251.ko whose init table carries one value set (or none) in place of the mode tables, so the sensor starts
# from power-on with it; the stream checks are clkrst_matrix.py cold <label>.
#
#   coldstart-clkrst.sh swap <ov7251.ko>   unbind the sensor, unload the loaded ov7251, load this one, re-apply the ACL
#   coldstart-clkrst.sh restore            back to the v3 test build (~/projects/surface-ir-camera/kernel/build/ov7251.ko)
#   coldstart-clkrst.sh stock              back to the stock module under /lib/modules (modprobe): no strobe control
#
# Undo at any time: coldstart-clkrst.sh restore (a reboot gives the stock module instead). Nothing is installed or written outside /sys.
# The unbind is needed because ipu3-cio2 holds a reference on the sensor module while its subdev is registered.
set -euo pipefail
DEV=i2c-INT347E:00
acl() { sleep 1; sudo setfacl -m u:"$USER":rw /dev/"$(basename /sys/bus/i2c/devices/$DEV/video4linux/v4l-subdev*)"; }
state() { echo "ov7251: $(/usr/bin/grep -c '^ov7251 ' /proc/modules) loaded, bound: $(ls /sys/bus/i2c/drivers/ov7251/ | /usr/bin/grep -c "$DEV"), subdev: $(basename /sys/bus/i2c/devices/$DEV/video4linux/v4l-subdev* 2>/dev/null)"; }
case "${1:-}" in
swap)
	modinfo -F vermagic "$2" | /usr/bin/grep -q "^$(uname -r) " || { echo "vermagic mismatch" >&2; exit 1; }
	echo $DEV | sudo tee /sys/bus/i2c/drivers/ov7251/unbind >/dev/null
	sudo modprobe -r ov7251
	sudo insmod "$2"
	acl; state ;;
restore)
	exec "$0" swap /home/antoine/projects/surface-ir-camera/kernel/build/ov7251.ko ;;
stock)
	echo $DEV | sudo tee /sys/bus/i2c/drivers/ov7251/unbind >/dev/null || true
	sudo rmmod ov7251 || true
	sudo modprobe ov7251
	acl; state ;;
*)
	echo "usage: $0 swap <ov7251.ko> | restore | stock" >&2; exit 1 ;;
esac
