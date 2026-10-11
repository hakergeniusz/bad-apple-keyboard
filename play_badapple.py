#!/usr/bin/env python3
"""Bad Apple player for the GK630K: streams precomputed frames at 30fps."""
import sys, time
sys.path.insert(0, '/tmp/ai-agent')
from gk630k import GK630K

FPS = 30.0
data = open('/home/hakergeniusz/projects/bad-apple-keyboard/data/badapple.kbd', 'rb').read()
nframes = len(data) // 384
print(f'{nframes} frames ({nframes/FPS:.1f}s)', flush=True)
start_at = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0  # lead-in seconds

kb = GK630K()
try:
    t0 = time.monotonic() + start_at
    for f in range(nframes):
        kb.send_frame(data[f*384:(f+1)*384])
        target = t0 + (f + 1) / FPS
        dt = target - time.monotonic()
        if dt > 0:
            time.sleep(dt)
        elif f % 300 == 0:
            print(f'frame {f} lag {-dt:.2f}s', flush=True)
    print('done, ending stream', flush=True)
    kb.end_frames()
finally:
    kb.close()
