#!/usr/bin/env python3
"""Count GK630K frame commands (cmd 0x12) on the vendor hidraw node."""
import os, sys, time, select

PATH = sys.argv[1] if len(sys.argv) > 1 else "/dev/hidraw1"
DUR = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0

fd = os.open(PATH, os.O_RDONLY | os.O_NONBLOCK)
end = time.monotonic() + DUR
chunks = 0
try:
    while time.monotonic() < end:
        r, _, _ = select.select([fd], [], [], 0.1)
        if not r:
            continue
        data = os.read(fd, 4096)
        if not data:
            continue
        for i in range(0, len(data) - 63, 64):
            pkt = data[i:i + 64]
            if len(pkt) == 64 and pkt[0] == 0x04 and pkt[3] == 0x12:
                chunks += 1
finally:
    os.close(fd)

print(f"0x12 chunks={chunks} frames={chunks/7:.1f} fps={chunks/7/DUR:.1f}")
