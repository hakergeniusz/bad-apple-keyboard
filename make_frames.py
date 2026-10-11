#!/usr/bin/env python3
"""Precompute per-key RGB frames from frames.rgb (128x64 rgb24 @30fps)."""
import sys
sys.path.insert(0, '/tmp/ai-agent')
import numpy as np
from gk630k_layout import slot_pos

W, H = 128, 64
XMAX, YMAX = 16.5, 6.2  # keyboard spans this in key units

raw = np.fromfile('/var/tmp/ai-agent/gk630k/frames.rgb', dtype=np.uint8)
nframes = len(raw) // (W * H * 3)
print('frames:', nframes, flush=True)
raw = raw.reshape(nframes, H, W, 3)

slots = []
for slot in range(128):
    p = slot_pos(slot)
    if p is None:
        slots.append(None)
        continue
    x, y = p
    x0 = int(max(0, (x - 0.38) / XMAX * W)); x1 = int(min(W, (x + 0.38) / XMAX * W))
    y0 = int(max(0, (y - 0.38) / YMAX * H)); y1 = int(min(H, (y + 0.38) / YMAX * H))
    slots.append((y0, y1, x0, x1))
print('mapped slots:', sum(1 for s in slots if s), flush=True)

out = bytearray()
for f in range(nframes):
    fr = raw[f].astype(np.uint16)
    frame = bytearray(128 * 3)
    for slot, r in enumerate(slots):
        if r is None:
            continue
        y0, y1, x0, x1 = r
        v = int(fr[y0:y1, x0:x1].mean())
        frame[slot*3:(slot+1)*3] = (v, v, v)
    out += frame
    if f % 1000 == 0:
        print(f, flush=True)
open('/var/tmp/ai-agent/gk630k/badapple.kbd', 'wb').write(out)
print('wrote', len(out), flush=True)
