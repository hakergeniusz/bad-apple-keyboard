#!/usr/bin/env python3
"""Flowing plasma for the GK630K. Ctrl+C to stop (restores saved lighting)."""
import math, sys, time
import numpy as np

sys.path.insert(0, '/home/hakergeniusz/projects/bad-apple-keyboard')
from gk630k import GK630K
from gk630k_layout import slot_pos

FPS = 30

KEYS = [(s, slot_pos(s)) for s in range(128)]
KEYS = [(s, p) for s, p in KEYS if p]
XS = np.array([p[0] / 16.0 for _, p in KEYS])
YS = np.array([p[1] / 6.0 for _, p in KEYS])
KSLOT = [s for s, _ in KEYS]

def hsv(h):
    h = h % 1.0
    i = int(h * 6)
    f = h * 6 - i
    q = 1 - f
    i %= 6
    if i == 0: return (1, f, 0)
    if i == 1: return (q, 1, 0)
    if i == 2: return (0, 1, f)
    if i == 3: return (0, q, 1)
    if i == 4: return (f, 0, 1)
    return (1, 0, q)

def main(secs=float('inf')):
    kb = GK630K()
    frame = bytearray(384)
    t0, n = time.monotonic(), 0
    try:
        while time.monotonic() - t0 < secs:
            t = time.monotonic() - t0
            v = (np.sin(XS * 6.0 + t * 1.7) + np.sin(YS * 8.0 - t * 1.3) +
                 np.sin((XS + YS) * 5.0 + t * 0.9) + np.sin(np.sqrt(XS**2 + YS**2) * 9.0 - t * 2.1)) / 4
            v = (v + 1) / 2
            hue = (v + t * 0.05) % 1.0
            sat = 0.75 + 0.25 * np.sin(t * 0.8 + XS * 3.0)
            val = 0.55 + 0.45 * v
            for i, s in enumerate(KSLOT):
                r, g, b = hsv(hue[i])
                frame[s*3]   = int(255 * min(1, r * sat[i]) * val[i])
                frame[s*3+1] = int(255 * min(1, g * sat[i]) * val[i])
                frame[s*3+2] = int(255 * min(1, b * sat[i]) * val[i])
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
        print(f'\n{n} plasma frames, lighting restored')

if __name__ == '__main__':
    main(float(sys.argv[1]) if len(sys.argv) > 1 else float('inf'))
