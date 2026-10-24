#!/usr/bin/env bash
# Phase 0 bench: does driving the OV7251 STROBE pad light the 850 nm emitter?
#
#   sudo tools/bench-strobe.sh [outdir]
#
# Aim the camera at a static scene and keep it identical for all captures.
# Changes made (runtime only, gone at reboot): enables the sensor -> ipu3-csi2 2 media link, sets the
# pad and video formats, sets exposure and gain on the sensor (the "before:" lines show the values to
# restore). The driver rewrites the mode table at every stream start, which should reset the strobe
# registers; the dark_after capture and the read-backs check that. Undo the link with:
#   media-ctl -d /dev/media0 -l '"ov7251 3-0060":0 -> "ipu3-csi2 2":0 [0]'
set -euo pipefail

MEDIA=/dev/media0
VIDEO=/dev/video2
CSI="ipu3-csi2 2"
W=640
H=480
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
out=${1:-/tmp/claude-1000/-home-antoine-projects-surface/3ccf287b-d9c6-4190-a42c-0b614d1d1d83/scratchpad/bench}
pid=

die() { echo "error: $*" >&2; exit 1; }
run() { echo "+ $*"; "$@"; }

echo "== preconditions"
[[ $EUID -eq 0 ]] || die "run as root: sudo $0"
for c in media-ctl v4l2-ctl i2ctransfer python3; do
  command -v "$c" >/dev/null || die "missing command: $c"
done
python3 -I -c 'import numpy' || die "root's python3 cannot import numpy"

cleanup() {
  # never leave the sensor streaming: the emitter could stay lit
  if [[ -n $pid ]]; then kill "$pid" 2>/dev/null || true; fi
  # hand our files back to the invoking user, root-owned files in a scratch dir are a nuisance
  chown "${SUDO_UID:-0}:${SUDO_GID:-0}" "$out"/*.raw "$out/summary.tsv" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

ent=
for f in /sys/class/video4linux/v4l-subdev*/name; do
  if [[ -r $f ]] && read -r name < "$f" && [[ $name == ov7251* ]]; then
    ent=$name
    sd=/dev/$(basename "$(dirname "$f")")
    break
  fi
done
[[ -n $ent ]] || die "no ov7251 subdev found under /sys/class/video4linux"
re='^ov7251 ([0-9]+)-([0-9a-f]{4})$'
[[ $ent =~ $re ]] || die "cannot parse an I2C bus and address from the entity name '$ent'"
bus=${BASH_REMATCH[1]}
printf -v addr '0x%x' "$((16#${BASH_REMATCH[2]}))"
[[ -e /dev/i2c-$bus ]] || die "/dev/i2c-$bus is missing: run 'modprobe i2c-dev'"
echo "ov7251 entity '$ent', subdev $sd, i2c bus $bus, address $addr"

[[ -d $out ]] || install -d -o "${SUDO_UID:-0}" -g "${SUDO_GID:-0}" "$out"
: > "$out/summary.tsv"
echo "output dir $out"

# stats <label> <first analysed frame>: print the summary line, append a row to summary.tsv
stats() {
  python3 -I - "$here" "$out" "$W" "$H" "$1" "$2" <<'PY'
import sys

import numpy as np

here, out, w, h, label, first = sys.argv[1:]
w, h, first = int(w), int(h), int(first)
sys.path.insert(0, here)
import ip3y

raw = np.fromfile(f"{out}/{label}.raw", np.uint8)
size = ip3y.bytesperline(w) * h
if raw.size == 0 or raw.size % size:
    sys.exit(f"{label}.raw: {raw.size} bytes is not a whole number of {size}-byte frames")
means = np.array([ip3y.unpack(raw[i:i + size], w, h).mean() for i in range(0, raw.size, size)])
m = means[first:]
p5, p95 = np.percentile(m, [5, 95])
print(f"{label} frames={m.size} mean={m.mean():.2f} p5={p5:.2f} p95={p95:.2f}")
if first:  # whole stream, to see when the registers were written
    blocks = np.array_split(means, max(1, means.size // 10))
    print("  all frames, mean per 10:", " ".join(f"{b.mean():.1f}" for b in blocks))
with open(f"{out}/summary.tsv", "a") as f:
    print(label, m.mean(), p5, p95, m[0::2].mean(), m[1::2].mean(), sep="\t", file=f)
PY
}

# capture <label> <frames> <first analysed frame> [0x3b81 value]
# With a 0x3b81 value, the strobe registers are written 1 s after the stream starts.
capture() {
  local label=$1 frames=$2 first=$3 pattern=${4:-}
  local cmd=(v4l2-ctl -d "$VIDEO" --stream-mmap --stream-count="$frames" --stream-skip=5 --stream-to="$out/$label.raw")
  echo "== $label: $frames frames, analysing from frame $first"
  echo "+ ${cmd[*]} &"
  "${cmd[@]}" &
  pid=$!
  if [[ -n $pattern ]]; then
    # the driver rewrites the mode table at every stream start (0x3005 -> 0x00, 0x3b81 -> 0xa5): write only once streaming
    sleep 1.0
    run i2ctransfer -f -y "$bus" "w3@$addr" 0x30 0x05 0x08       # STROBE pad output enable
    run i2ctransfer -f -y "$bus" "w3@$addr" 0x3b 0x81 "$pattern" # 0xaa: alternate frames (Windows' pattern), 0xff: every frame
    echo "read back, expect 0x08 then $pattern:"
    run i2ctransfer -f -y "$bus" "w2@$addr" 0x30 0x05 r1
    run i2ctransfer -f -y "$bus" "w2@$addr" 0x3b 0x81 r1
  fi
  wait "$pid"
  pid=
  stats "$label" "$first"
}

echo "== media graph"
run media-ctl -d "$MEDIA" -l "\"$ent\":0 -> \"$CSI\":0 [1]"
run media-ctl -d "$MEDIA" -V "\"$ent\":0 [fmt:Y10_1X10/${W}x${H}]"
run media-ctl -d "$MEDIA" -V "\"$CSI\":0 [fmt:Y10_1X10/${W}x${H}]"
run v4l2-ctl -d "$VIDEO" --set-fmt-video="width=$W,height=$H,pixelformat=ip3y"

echo "== sensor controls"
ctrls() { v4l2-ctl -d "$sd" -l | awk '$1 == "exposure" || $1 == "analogue_gain"'; }
echo "before:"
ctrls
emax=$(v4l2-ctl -d "$sd" -l | awk '$1 == "exposure" { for (i = 1; i <= NF; i++) if ($i ~ /^max=/) print substr($i, 5) }')
[[ $emax =~ ^[0-9]+$ ]] || die "cannot read the exposure max from 'v4l2-ctl -d $sd -l'"
run v4l2-ctl -d "$sd" --set-ctrl="exposure=$emax,analogue_gain=128"
echo "after:"
ctrls

# 120 frames for the strobe runs: the first 60 cover the registers being written, only the last 60 are analysed.
capture dark 60 0
capture strobe_aa 120 60 0xaa
capture strobe_ff 120 60 0xff
capture dark_after 60 0 # control: fresh stream, strobe registers reset by the driver

echo "== sensor power state"
sleep 2
status=$(< /sys/bus/i2c/devices/i2c-INT347E:00/power/runtime_status)
echo "runtime_status: $status (expected: suspended = sensor powered down, emitter cannot be lit)"
[[ $status == suspended ]] || echo "WARNING: sensor not suspended 2 s after the last stream, look for a leftover v4l2-ctl"

echo "== summary (means are 10-bit counts; even/odd = mean of even-/odd-indexed frames in the analysed window)"
awk -F'\t' '
  function ratio(a, b) { return m[b] ? sprintf("%.3f", m[a] / m[b]) : "n/a" }
  { label[NR] = $1; m[$1] = $2; p5[$1] = $3; p95[$1] = $4; ev[$1] = $5; od[$1] = $6 }
  END {
    printf "%-11s %8s %8s %8s %8s %8s\n", "label", "mean", "p5", "p95", "even", "odd"
    for (i = 1; i <= NR; i++) {
      l = label[i]
      printf "%-11s %8.2f %8.2f %8.2f %8.2f %8.2f\n", l, m[l], p5[l], p95[l], ev[l], od[l]
    }
    print "strobe_ff / dark  =", ratio("strobe_ff", "dark")
    print "strobe_aa / dark  =", ratio("strobe_aa", "dark")
    print "dark_after / dark =", ratio("dark_after", "dark")
  }' "$out/summary.tsv"
