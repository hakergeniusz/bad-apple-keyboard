#!/bin/bash
# Measure the effective keyboard frame rate for various mpv options.
#
#   tools/bench_fps.sh [video]
#
# The monitor only *reads* the vendor hidraw node, so it does not steal
# replies from mpv (each hidraw fd has its own report buffer).
cd ~/Projects/bad-apple-keyboard || exit 1
MPVBIN=./mpv-bin
VID="${1:-/tmp/kb-bench.mp4}"

if [ ! -f "$VID" ]; then
    echo "== generating test video $VID"
    ffmpeg -y -f lavfi -i testsrc2=size=320x240:rate=30 -t 20 \
           -pix_fmt yuv420p -c:v libx264 -preset ultrafast -an "$VID" >/dev/null 2>&1
fi

run() {
    local label="$1"; shift
    python3 tools/count_frames.py /dev/hidraw1 6 > /tmp/kbcount.log 2>&1 &
    local mon=$!
    sleep 1
    "$MPVBIN" --vo=rgb-keyboard --no-config --ao=null --loop "$@" "$VID" >/dev/null 2>&1 &
    local p=$!
    wait $mon
    kill $p 2>/dev/null; wait $p 2>/dev/null
    printf "%-42s %s\n" "$label" "$(cat /tmp/kbcount.log)"
}

echo "video: $VID"
run "default"
run "max-fps=60"            --vo-rgb-keyboard-max-fps=60
run "max-fps=60 + desync"    --vo-rgb-keyboard-max-fps=60 --video-sync=desync
run "max-fps=60 + vdrop"     --vo-rgb-keyboard-max-fps=60 --video-sync=display-vdrop
run "max-fps=120"            --vo-rgb-keyboard-max-fps=120
