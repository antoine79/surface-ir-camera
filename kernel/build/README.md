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

## 6.18 test module (patches 1, 3-6)

Patch 7 needs `V4L2_CID_FLASH_STROBE_OE`, which the 6.18 control framework does not know, so `../backport/ov7251.c` does not build against 6.18. To test the rest of the series on the running 6.18.8 kernel, build a module from the pristine backport base (v7.2 + the gain patch, i.e. `ov7251.c` as of commit e996431) plus patches 0001 and 0003-0006. The v7.2 driver builds against the 6.18 headers unchanged.

```sh
T=$(mktemp -d) && cd ~/projects/surface-ir-camera
git show e996431:kernel/backport/ov7251.c > $T/ov7251.c
cp kernel/build/Makefile $T/
for n in 0001 0003 0004 0005 0006; do (cd $T && git apply -p4 ~/projects/surface-ir-camera/kernel/patches/$n-*.patch); done
make -C $T KDIR=/lib/modules/6.18.8-1.surface.fc43.x86_64/build W=1
modinfo $T/ov7251.ko | grep vermagic     # 6.18.8-1.surface.fc43.x86_64
```

(`-p4` strips `a/drivers/media/i2c/` so the patches apply to the flat `ov7251.c`.)

## Load for a test session

```sh
sudo modprobe -r ov7251 && sudo insmod ./kernel/build/ov7251.ko
```

Caveat (found 2026-10-24 on 6.18.8): `modprobe -r ov7251` fails with "Module ov7251 is in use" while ipu3-cio2 is bound. `v4l2_device_register_subdev()` takes a reference on the sensor module (`try_module_get()`, `drivers/media/v4l2-core/v4l2-device.c`) for as long as the subdev is registered with cio2's v4l2_device, so the module has refcount 1 and no holders even with nothing open. Unloading needs the I2C device unbound first (`echo i2c-INT347E:00 | sudo tee /sys/bus/i2c/drivers/ov7251/unbind`), which removes the ov7251 entity from `/dev/media0` until the new module binds again, or ipu3-cio2 reloaded, which also takes down the ov5693 front camera.

ipu3-cio2, ipu-bridge and the other sensor drivers stay loaded. `modprobe -r` fails if something holds the sensor (a running camera app, libcamera, an open `/dev/v4l-subdev*`); close it first. `insmod` does not load dependencies, but videodev, v4l2-async, mc and v4l2-fwnode are already loaded by the distro camera stack. The module is unsigned: with Secure Boot disabled and `CONFIG_MODULE_SIG_FORCE` unset it loads and taints the kernel (`E`), which is harmless for tests.

## Undo

```sh
sudo rmmod ov7251 && sudo modprobe ov7251
```

This restores the distro module. A reboot does the same.
