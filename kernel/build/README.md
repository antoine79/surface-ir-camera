# Out-of-tree ov7251.ko

`ov7251.c` in this folder is a symlink to `../backport/ov7251.c`. Nothing is installed under `/lib/modules`.

## Build

```sh
make -C kernel/build KDIR=/lib/modules/7.2.12-1.surface.fc43.x86_64/build        # -> kernel/build/ov7251.ko
make -C kernel/build KDIR=... W=1                                                # extra warnings
make -C kernel/build check                                                       # checkpatch --strict from ~/projects/media-committers
make -C kernel/build KDIR=... clean
```

`KDIR` defaults to the running kernel's headers. Check the result with `modinfo kernel/build/ov7251.ko | grep -E 'vermagic|depends'`: vermagic must match `uname -r` of the kernel you load it on.

`C=1` (sparse) and `CHECK="smatch -p=kernel"` work against the 6.18 headers, but against 7.2 the kernel's checker gate silently disables them: Fedora 43's sparse 0.6.4 and smatch 1.73 do not understand `__typeof_unqual__`, which 7.x headers use. A sparse/smatch built from git is needed for 7.x.

## Load for a test session (booted into 7.2.12)

```sh
sudo modprobe -r ov7251 && sudo insmod ./kernel/build/ov7251.ko
```

ipu3-cio2, ipu-bridge and the other sensor drivers stay loaded. `modprobe -r` fails if something holds the sensor (a running camera app, libcamera, an open `/dev/v4l-subdev*`); close it first. `insmod` does not load dependencies, but videodev, v4l2-async, mc and v4l2-fwnode are already loaded by the distro camera stack. The module is unsigned: with Secure Boot disabled and `CONFIG_MODULE_SIG_FORCE` unset it loads and taints the kernel (`E`), which is harmless for tests.

## Undo

```sh
sudo rmmod ov7251 && sudo modprobe ov7251
```

This restores the distro module. A reboot does the same.
