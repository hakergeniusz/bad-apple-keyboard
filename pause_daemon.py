#!/usr/bin/env python3
"""GK630K 24/7 daemon: brightest-white idle + water ripples on keypress.
PAUSE starts/stops the 56s Bad Apple (ripples pause during playback).
Tune BRIGHTNESS / RIPPLE_COLOR below. Logs go to the journal."""
import fcntl, math, os, select, struct, sys, time

sys.path.insert(0, '/home/hakergeniusz/projects/bad-apple-keyboard')
from gk630k import GK630K
from gk630k_layout import MAP

BASE = '/home/hakergeniusz/projects/bad-apple-keyboard'
FPS, PAUSE_SECS = 30.0, 56
NFRAMES = int(FPS * PAUSE_SECS)
KEY_PAUSE, EV_KEY = 119, 1
EVT = struct.Struct('qqHHI')

BRIGHTNESS = 1.0          # white idle level, 0.0-1.0
RIPPLE_COLOR = (0x08, 0x2D, 0x8A)
RIPPLE_BRIGHTNESS = 0.8   # ripple intensity, 0.0-1.0
RIPPLE_SPEED = 7.0        # keys per second
RIPPLE_DECAY = 0.9        # seconds
RIPPLE_WIDTH = 1.1        # keys

data = open(f'{BASE}/data/badapple.kbd', 'rb').read()
BACKUP = open(f'{BASE}/backup_custom.bin', 'rb').read()

# keycode -> [positions]; '#' and '\\' share code 43 on ISO, ripple both
CODE_NAMES = {
    1: ['ESC'], 59: ['F1'], 60: ['F2'], 61: ['F3'], 62: ['F4'], 63: ['F5'],
    64: ['F6'], 65: ['F7'], 66: ['F8'], 67: ['F9'], 68: ['F10'], 87: ['F11'],
    88: ['F12'], 99: ['PRSC'], 70: ['SCRL'], 119: ['PAUS'],
    41: ['`'], 2: ['1'], 3: ['2'], 4: ['3'], 5: ['4'], 6: ['5'], 7: ['6'],
    8: ['7'], 9: ['8'], 10: ['9'], 11: ['0'], 12: ['-'], 13: ['='],
    14: ['BKSP'], 110: ['INS'], 102: ['HOME'],
    15: ['TAB'], 16: ['Q'], 17: ['W'], 18: ['E'], 19: ['R'], 20: ['T'],
    21: ['Y'], 22: ['U'], 23: ['I'], 24: ['O'], 25: ['P'], 26: ['['],
    27: [']'], 43: ['\\', '#'], 111: ['DEL'], 107: ['END'],
    58: ['CAPS'], 30: ['A'], 31: ['S'], 32: ['D'], 33: ['F'], 34: ['G'],
    35: ['H'], 36: ['J'], 37: ['K'], 38: ['L'], 39: [';'], 40: ["'"],
    28: ['ENTER'], 104: ['PGUP'], 109: ['PGDN'],
    42: ['LSH'], 86: ['<>'], 44: ['Z'], 45: ['X'], 46: ['C'], 47: ['V'],
    48: ['B'], 49: ['N'], 50: ['M'], 51: [','], 52: ['.'], 53: ['/'],
    54: ['RSH'], 103: ['UP'],
    29: ['LCTRL'], 125: ['WIN'], 56: ['ALT'], 57: ['SPACE'], 100: ['RALT'],
    139: ['MENU'], 97: ['RCTRL'], 105: ['LEFT'], 108: ['DOWN'], 106: ['RIGHT'],
}
NAME_POS = {name: (x, y) for (name, x, y) in MAP.values()}
CODE_POS = {c: [NAME_POS[n] for n in ns if n in NAME_POS]
            for c, ns in CODE_NAMES.items()}

def kb_event_nodes():
    nodes = []
    for n in sorted(os.listdir('/dev/input')):
        if not n.startswith('event'):
            continue
        p = f'/dev/input/{n}'
        try:
            fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        buf = bytearray(256)
        try:
            fcntl.ioctl(fd, (2 << 30) | (ord('E') << 8) | 0x06 | (256 << 16), buf, True)
        except OSError:
            os.close(fd)
            continue
        if b'GK630' in bytes(buf):
            nodes.append((p, fd))
        else:
            os.close(fd)
    return nodes

def read_events(fds):
    """Yield (code, value) for key events; drains all ready fds."""
    out = []
    for fd in fds:
        try:
            chunk = os.read(fd, 24 * 64)
        except OSError:
            continue
        for off in range(0, len(chunk) - 23, 24):
            _, _, typ, code, val = EVT.unpack_from(chunk, off)
            if typ == EV_KEY:
                out.append((code, val))
    return out

def render_idle(ripples, now):
    import numpy as np
    w = int(255 * BRIGHTNESS)
    base = np.full((128, 3), w, np.uint8)
    if not ripples:
        return bytes(base.flatten())
    ripples[:] = [(x, y, t0) for x, y, t0 in ripples if now - t0 < 2.5 * RIPPLE_DECAY]
    k = np.zeros(128)
    for x, y, t0 in ripples:
        age = now - t0
        r = age * RIPPLE_SPEED
        amp = math.exp(-age / RIPPLE_DECAY) * RIPPLE_BRIGHTNESS
        for s, p in enumerate(slot_xy):
            if p is None:
                continue
            d = math.hypot(p[0] - x, p[1] - y)
            k[s] += amp * math.exp(-((d - r) ** 2) / (2 * RIPPLE_WIDTH ** 2))
    k = np.clip(k, 0, 1)
    rc = np.array(RIPPLE_COLOR, float)
    out = base.astype(float) * (1 - k[:, None]) + rc[None, :] * k[:, None]
    return bytes(np.clip(out, 0, 255).astype(np.uint8).flatten())

slot_xy = [None] * 128
for (col, row), (name, x, y) in MAP.items():
    slot_xy[col * 8 + row] = (x, y)

def main():
    import numpy as np  # noqa: F401  (used in render_idle globals)
    nodes = kb_event_nodes()
    fds = [fd for _, fd in nodes]
    print(f'watching {[p for p, _ in nodes]}: white idle + ripples, PAUSE=bad apple', flush=True)
    kb = GK630K()
    ripples, mode, fidx, t0, last_trig = [], 'idle', 0, 0.0, {}
    try:
        while True:
            now = time.monotonic()
            if mode == 'idle':
                nxt = now + 1 / FPS
                r, _, _ = select.select(fds, [], [], max(0, nxt - now))
                if r:
                    for code, val in read_events(r):
                        if val != 1:
                            continue
                        if code == KEY_PAUSE:
                            print('PAUSE: playing 56s', flush=True)
                            mode, fidx, t0, ripples = 'play', 0, time.monotonic(), []
                            break
                        pass  # plain white idle: ignore all keys except PAUSE
                if mode == 'idle':
                    kb.send_frame(render_idle(ripples, time.monotonic()))
            else:
                nxt = t0 + (fidx + 1) / FPS
                dt = nxt - time.monotonic()
                stop = False
                while dt > 0:
                    r, _, _ = select.select(fds, [], [], min(dt, 0.05))
                    if r and any(c == KEY_PAUSE and v == 1 for c, v in read_events(r)):
                        stop = True
                        break
                    dt = nxt - time.monotonic()
                if stop or fidx >= NFRAMES:
                    print('stopped, back to idle' if stop else 'finished, back to idle', flush=True)
                    kb.write_custom_leds(BACKUP)
                    kb.end_frames()
                    mode = 'idle'
                else:
                    kb.send_frame(data[fidx * 384:(fidx + 1) * 384])
                    fidx += 1
    finally:
        kb.write_custom_leds(BACKUP)
        kb.end_frames()
        kb.close()

if __name__ == '__main__':
    main()
