#!/bin/bash
# Verify that killing mpv does NOT wedge the keyboard in frame-streaming
# mode (which would make it emit phantom key events forever).
#
#   tools/verify_sigterm.sh [SIGNAL]
#
# The protocol check (keyboard still answers queries, streaming still works)
# needs no root.  The phantom-key check reads /dev/input/eventN and needs
# root, so it is skipped unless the event node is readable.
cd ~/Projects/bad-apple-keyboard || exit 1
SIG=${1:-TERM}
MPVBIN=./mpv-bin
VID=/tmp/kb-sigterm.mp4
EVENTS=$(for e in /sys/class/input/event*/device/uevent; do
            n=$(basename "$(dirname "$(dirname "$e")")")
            if rg -q 'PRODUCT=3/3299/4e5a' "$e" 2>/dev/null; then echo /dev/input/$n; fi
        done | tr '\n' ' ')

if [ ! -f "$VID" ]; then
    ffmpeg -y -f lavfi -i testsrc2=size=320x240:rate=30 -t 30 \
           -pix_fmt yuv420p -c:v libx264 -preset ultrafast -an "$VID" >/dev/null 2>&1
fi

echo "=== keyboard event nodes: ${EVENTS:-none found} ==="

echo
echo "=== start mpv, stream for 4s, then SIG$SIG ==="
"$MPVBIN" --vo=rgb-keyboard --no-config --ao=null --loop "$VID" >/tmp/mpvterm.log 2>&1 &
MPVPID=$!
sleep 4
kill -$SIG $MPVPID
sleep 2
if ps -p $MPVPID >/dev/null 2>&1; then
    echo "FAIL: mpv still running after SIG$SIG"
    kill -9 $MPVPID 2>/dev/null
    wait $MPVPID 2>/dev/null
else
    wait $MPVPID 2>/dev/null
    echo "OK: mpv exited on SIG$SIG (status $?)"
fi

echo
echo "=== keyboard still answers protocol queries? ==="
uv run --no-project python - <<'PY'
import sys
sys.path.insert(0, ".")
import gk630k
with gk630k.GK630K() as kb:
    cfg = kb.read_config()
    leds = kb.read_custom_leds()
print(f"OK: config {len(cfg)} bytes, custom LEDs {len(leds)} bytes")
PY

echo
echo "=== phantom key events? ==="
READABLE=""
for e in $EVENTS; do [ -r "$e" ] && READABLE="$READABLE $e"; done
if [ -n "$READABLE" ]; then
    python3 - $READABLE <<'PY'
import struct, sys, select, collections
counts = collections.Counter()
for path in sys.argv[1:]:
    fd = open(path, "rb", buffering=0)
    end = 5
    while end > 0:
        r, _, _ = select.select([fd], [], [], 1)
        if not r:
            end -= 1
            continue
        data = fd.read(24)
        if len(data) < 24:
            end -= 1
            continue
        _, _, code, value = struct.unpack("hiHi", data)
        if code == 0:  # EV_SYN
            continue
        counts[(path, code, value)] += 1
    fd.close()
if counts:
    print("key events seen (5s):", dict(counts))
else:
    print("OK: no key events")
PY
else
    echo "SKIPPED: event nodes are not readable without root"
fi
