# Howdy face login with the infrared camera

This page sets up Howdy, the Linux face login, on the infrared camera of the Surface Book 2 13 inch. It is written for that model, on Fedora 45 with the linux-surface kernel 7.3.4; "Tested so far" at the end says which steps have been run. The commands are Fedora's; other distributions have the same pieces under similar package names.

The bridge script (`tools/ir-bridge.py`) is written for the Intel IPU3 camera interface of the Book 2. The Surface Pro 7+ and Book 3 have newer camera interfaces. Everything in the bridge that depends on the camera interface sits in one small class, and the `Template` class in `tools/ir-bridge.py` lists what to fill in for another one (`--platform`, `--rotate` and `--no-emitter` select the rest). The kernel patches themselves are not specific to the Book 2.

## Read this first

- **This is not as secure as Windows Hello.** Howdy accepts recorded infrared frames of your face, and other programs can feed it some: treat it as a convenience on the lock screen, never as a lock on anything that grants root. [How it compares with Windows Hello](#how-it-compares-with-windows-hello) explains why. Your password keeps working.
- **The emitter is lit while the bridge runs.** For a login the bridge starts when your face is asked for and stops, which turns the emitter off, as soon as Howdy has finished, and after 15 seconds at the latest. For enrolment you run it by hand until you stop it.
- Every step below has its undo.

## How it compares with Windows Hello

Howdy only asks "does this picture look like the enrolled person?". Windows Hello also checks where the picture came from and protects what it compares against.

- **No liveness check.** Windows Hello accepts only an infrared camera, its camera driver tells it which frames the emitter lit, and it has an enhanced anti-spoofing mode; without that mode, a printed infrared photo fooled it ([SySS, 2017](https://www.syss.de/fileadmin/dokumente/Publikationen/2018/Biometricks_-_Bypassing_an_Enterprise-Grade_Biometric_Face_Authentication_System_-_PHDays_8.pdf)). Howdy has no such check. On the test machine it accepted a still frame of the face, the same still moved slightly from frame to frame, and a recorded video, each written into the virtual camera (`tests/spoof_replay.py`). It rejected frames that were too dark, a flat grey picture and a frame from the colour camera. Removing the emitter's light from the frames changed the match score only a little (`tests/spoof_emitter.py`), so the infrared light by itself gives Howdy no protection. A printed photo has not been tried.
- **No trusted camera.** Since 2021 Windows takes face sign-in only from cameras it trusts, after CyberArk unlocked it with a fake USB camera replaying infrared frames ([CVE-2021-34466](https://www.cyberark.com/resources/threat-research-blog/bypassing-windows-hello-without-masks-or-plastic-surgery)). Here the frames reach Howdy through a virtual camera that programs running as you can write to, as the replays above did. Do not add Howdy to sudo, su or anything else that grants root.
- **Unprotected face data.** With Enhanced Sign-in Security ([Microsoft](https://learn.microsoft.com/windows-hardware/design/device-experiences/windows-hello-enhanced-sign-in-security)), Windows stores and matches the face template in memory isolated from the rest of the system. That needs newer hardware, very likely not the Surface Book 2 (not checked). Howdy stores the face model in `/etc/howdy/models/<user>.dat`, readable by every account on the machine as installed, and compares in an ordinary Python process.
- **No measured error rate.** Microsoft sets false-acceptance limits for Windows Hello face hardware ([requirements](https://learn.microsoft.com/windows-hardware/design/device-experiences/windows-hello-biometric-requirements)). No false-acceptance rate has been measured for Howdy on this camera.

What would close the gap:

1. A liveness check using the lit and dark frames together: the emitter's reflection in the pupils and how its light falls off across a real face, or agreement with the colour camera. `tests/liveness_spike.py` is a first experiment; it rejects the replays above, but a printed photo lit by the emitter would likely pass.
2. A camera path no other program can write to: Howdy reading the sensor itself, through libcamera once it supports this sensor, instead of a virtual camera.
3. Face models that other accounts cannot read. Lock screens run Howdy as you, so give the file to its owner rather than to root: `sudo chown $USER:root /etc/howdy/models/$USER.dat && sudo chmod 600 /etc/howdy/models/$USER.dat` after each enrolment (tested on the Xfce lock screen setup: Howdy still recognises you, another account is refused).
4. A measured false-acceptance rate.

## 1. The patched sensor module

Mainline Linux cannot switch the emitter on yet; the patches in `kernel/patches/` add that, and `kernel/backport/ov7251.c` is the sensor driver with them applied. Build it against your running kernel (needs the matching `kernel-surface-devel`):

```sh
git clone https://github.com/antoine79/surface-ir-camera && cd surface-ir-camera
mkdir -p ~/ov7251-build && cp kernel/backport/ov7251.c ~/ov7251-build/
echo 'obj-m := ov7251.o' > ~/ov7251-build/Kbuild
make -C /lib/modules/$(uname -r)/build M=$HOME/ov7251-build modules
sudo install -D -m644 ~/ov7251-build/ov7251.ko /lib/modules/$(uname -r)/updates/ov7251.ko
sudo depmod -a
```

Reboot, then `modinfo -n ov7251` must print the `updates/` path. The module is built for one kernel only. To have every new kernel get it automatically, install the kernel-install hook and the source it builds from:

```sh
sudo install -D -m644 kernel/backport/ov7251.c /usr/local/src/ov7251-ir/ov7251.c
sudo install -m755 tools/96-ov7251-ir.install /etc/kernel/install.d/96-ov7251-ir.install
```

It never fails a kernel install; if the headers are missing it skips, and the stock driver loads (face login then falls back to the password). Undo: `sudo rm -r /etc/kernel/install.d/96-ov7251-ir.install /usr/local/src/ov7251-ir`. Undo: `sudo rm /lib/modules/$(uname -r)/updates/ov7251.ko && sudo depmod -a`, then reboot.

## 2. The virtual camera

The bridge exposes a webcam device through v4l2loopback (from RPM Fusion on Fedora):

```sh
sudo dnf install akmod-v4l2loopback v4l-utils python3-numpy
echo 'options v4l2loopback devices=1 video_nr=21 exclusive_caps=1 card_label="Intel IR Camera" max_buffers=2' |
	sudo tee /etc/modprobe.d/ir-camera-bridge.conf
```

If you already use v4l2loopback for something else, such as a relay for the colour camera, merge both into one `options` line: the kernel keeps only the last value of each option. `tests/README.md` (Phase 4) shows the two-device line used on the test machine. Undo: `sudo rm /etc/modprobe.d/ir-camera-bridge.conf`.

## 3. The bridge, started on demand

```sh
sudo install -D -m644 tools/ir-bridge.py /usr/local/lib/ir-camera-bridge/ir-bridge.py
sudo install -m644 tools/ip3y.py /usr/local/lib/ir-camera-bridge/ip3y.py
sudo install -m755 tools/ir-camera-on-demand /usr/local/lib/ir-camera-bridge/ir-camera-on-demand
sudo install -m644 tools/ir-camera-bridge.service /etc/systemd/system/ir-camera-bridge.service
sudo install -m644 tools/ir-camera-bridge.rules /etc/polkit-1/rules.d/50-ir-camera-bridge.rules
sudo systemctl daemon-reload
```

- `ir-camera-on-demand` starts the service and returns once the bridge is writing to the virtual camera, under 0.7 seconds on the test machine. It fails after 8 seconds if the bridge never gets there.
- It then stops the service once Howdy has opened and closed the camera, or after 8 seconds if Howdy never opens it. The service itself runs without root and without network, and stops after 15 seconds whatever happens.
- The polkit rule lets the person at the console start and stop it, which a lock screen needs because it checks your face as you, not as root.

Check: `sudo /usr/local/lib/ir-camera-bridge/ir-camera-on-demand && v4l2-ctl -d /dev/video21 --stream-mmap --stream-count=10 --stream-to=/dev/null` captures ten frames, and `systemctl status ir-camera-bridge` shows the service stopped 15 seconds later ("failed" with result "timeout" is the expected end).

Undo: `sudo rm -r /usr/local/lib/ir-camera-bridge /etc/systemd/system/ir-camera-bridge.service /etc/polkit-1/rules.d/50-ir-camera-bridge.rules && sudo systemctl daemon-reload`.

## 4. Howdy

Howdy 3 for Fedora 45 is in the COPR `starfish/howdy-beta`:

```sh
sudo dnf copr enable starfish/howdy-beta
sudo dnf install howdy
sudo howdy config
```

Set these values in the file that opens (the bridge turns the picture upright, so it is 480 wide and 640 high):

```ini
device_path = /dev/video21
frame_width = 480
frame_height = 640
dark_threshold = 60
certainty = 3.5
timeout = 4
```

Enrol your face with the bridge running by hand in a second terminal (as your own user: a local login session has access to the camera devices), since enrolment can outlast the service's 15 seconds: `python3 tools/ir-bridge.py --frames lit`, then `sudo howdy add`, then Ctrl-C in the bridge terminal (the emitter goes off). Enrol in the light you will log in with. If Howdy stops recognising you, add a second model the same way rather than replacing the first: on the test machine a model enrolled at night stopped matching in daylight, where the emitter's reflection covered the lenses of the glasses, and a second model enrolled in daylight fixed it.

Check, looking at the camera: `sudo /usr/local/lib/ir-camera-bridge/ir-camera-on-demand && sudo python3 /usr/lib/python3.*/site-packages/howdy/compare.py $USER; echo $?` prints 0 when it recognises you, 11 when it saw no matching face before the timeout.

Undo: `sudo dnf remove howdy && sudo dnf copr remove starfish/howdy-beta`.

## 5. Login and lock screen

Add two lines at the top of the `auth` section of the screen you want face login on: `/etc/pam.d/xfce4-screensaver` for the Xfce lock screen, `/etc/pam.d/gdm-password` for the GNOME login and lock screen. Not sudo or su: see [How it compares with Windows Hello](#how-it-compares-with-windows-hello).

```
auth  optional    pam_exec.so quiet /usr/local/lib/ir-camera-bridge/ir-camera-on-demand
auth  sufficient  pam_howdy.so
```

The first line starts the bridge, the second tries your face. If Howdy does not recognise you within its timeout, the normal password prompt follows. Keep a root terminal open while you edit a PAM file and test it from another one. Undo: delete the two lines.

## Tested so far

On the Surface Book 2 13 inch with linux-surface 7.3.4, 25 Nov 2026: steps 1, 3, 4 and 5 with the Xfce lock screen; the kernel hook run by hand for the installed kernel (not yet through a real kernel update). The unlock prompt started the bridge, Howdy approved the face 2.6 seconds later, and the bridge stopped 0.2 seconds after the approval, which turned the emitter off; when Howdy did not recognise the face, the password prompt followed. Not tested: the single-device v4l2loopback line of step 2 (the test machine uses the two-device line), the GNOME PAM file, and any login screen.
