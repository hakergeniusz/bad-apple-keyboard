#!/usr/bin/env python3
"""Doom-style fire for the GK630K. Ctrl+C to stop (restores saved lighting)."""
import math, random, sys, time
import numpy as np

sys.path.insert(0, '/home/hakergeniusz/projects/bad-apple-keyboard')
from gk630k import GK630K
from gk630k_layout import slot_pos

W, H, MAXH = 34, 14, 36
FPS = 30

def palette():
    stops = [(0, 0, 0, 0), (8, 120, 10, 0), (16, 230, 60, 0),
             (24, 255, 160, 20), (30, 255, 230, 120), (36, 255, 255, 240)]
    pal = np.zeros((MAXH + 1, 3), np.uint8)
    for (h0, r0, g0, b0), (h1, r1, g1, b1) in zip(stops, stops[1:]):
        for h in range(h0, h1 + 1):
            t = (h - h0) / max(1, h1 - h0)
            pal[h] = (r0 + (r1 - r0) * t, g0 + (g1 - g0) * t, b0 + (b1 - b0) * t)
    return pal

PAL = palette()
KEYS = [(s, slot_pos(s)) for s in range(128)]
KEYS = [(s, (min(W - 1, int(p[0] * 2)), min(H - 1, int(p[1] * 2)))) for s, p in KEYS if p]
KX = np.array([k[1][0] for k in KEYS])
KY = np.array([k[1][1] for k in KEYS])
KSLOT = [k[0] for k in KEYS]

def main(secs=float('inf')):
    kb = GK630K()
    heat = np.zeros((H, W), np.int16)
    frame = bytearray(384)
    t0, n = time.monotonic(), 0
    try:
        while time.monotonic() - t0 < secs:
            t = time.monotonic() - t0
            # fuel bed with flicker + flare-ups + travelling wind
            wind = math.sin(t * 0.7) * 2 + math.sin(t * 2.3) * 1
            for x in range(W):
                base = MAXH - random.randint(0, 6)
                if random.random() < 0.06:
                    base = MAXH
                heat[H - 1, x] = base
                heat[H - 2, x] = max(heat[H - 2, x], base - random.randint(2, 8))
            # propagate upward
            for y in range(H - 2, -1, -1):
                shift = int(wind * (H - 1 - y) / H) + random.randint(-1, 1)
                src = heat[y + 1]
                xs = np.clip(np.arange(W) + shift, 0, W - 1)
                decay = np.random.randint(0, 3, W)
                heat[y] = np.clip(src[xs] - decay - (1 if y < H // 2 else 0), 0, MAXH)
            cols = PAL[np.clip(heat[KY, KX], 0, MAXH)]
            for i, s in enumerate(KSLOT):
                frame[s * 3:s * 3 + 3] = bytes(cols[i])
            kb.send_frame(bytes(frame))
            n += 1
            dt = t0 + (n + 1) / FPS - time.monotonic()
            if dt > 0:
                time.sleep(dt)
    except KeyboardInterrupt:
        pass
    finally:
        kb.write_custom_leds(open('/home/hakergeniusz/projects/bad-apple-keyboard/backup_custom.bin', 'rb').read())
        kb.end_frames()
        kb.close()
        print(f'\n{n} fire frames, lighting restored')

if __name__ == '__main__':
    main(float(sys.argv[1]) if len(sys.argv) > 1 else float('inf'))
