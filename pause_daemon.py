#!/usr/bin/env python3
"""Pause-key daemon: tap PAUSE on the GK630K -> first 56s of Bad Apple on the keys.
Run as a user service (see bad-apple-pause.service). Logs go to the journal."""
import fcntl, os, select, struct, sys, time

sys.path.insert(0, '/home/hakergeniusz/projects/bad-apple-keyboard')
from gk630k import GK630K

BASE = '/home/hakergeniusz/projects/bad-apple-keyboard'
FPS, SECS = 30.0, 56
NFRAMES = int(FPS * SECS)
KEY_PAUSE = 119
EV_KEY = 1
EVT = struct.Struct('qqHHI')

data = open(f'{BASE}/data/badapple.kbd', 'rb').read()
assert len(data) // 384 >= NFRAMES, 'frame file too short'
BACKUP = open(f'{BASE}/backup_custom.bin', 'rb').read()

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

def drain_pause(fds):
    """True if a PAUSE press arrived on any fd."""
    hit = False
    for fd in fds:
        try:
            chunk = os.read(fd, 24 * 32)
        except OSError:
            continue
        for off in range(0, len(chunk) - 23, 24):
            _, _, typ, code, val = EVT.unpack_from(chunk, off)
            if typ == EV_KEY and code == KEY_PAUSE and val == 1:
                hit = True
    return hit

def play56(kb, fds):
    """Returns True if finished, False if stopped via PAUSE."""
    t0 = time.monotonic()
    for f in range(NFRAMES):
        kb.send_frame(data[f * 384:(f + 1) * 384])
        dt = t0 + (f + 1) / FPS - time.monotonic()
        while dt > 0:
            r, _, _ = select.select(fds, [], [], min(dt, 0.05))
            if r and drain_pause(r):
                print('PAUSE pressed, stopping', flush=True)
                kb.write_custom_leds(BACKUP)
                kb.end_frames()
                return False
            dt = t0 + (f + 1) / FPS - time.monotonic()
    kb.write_custom_leds(BACKUP)
    kb.end_frames()
    return True

def main():
    nodes = kb_event_nodes()
    print(f'watching {[p for p, _ in nodes]} for PAUSE', flush=True)
    kb = GK630K()
    playing = False
    try:
        while True:
            r, _, _ = select.select([fd for _, fd in nodes], [], [], 30)
            if r and drain_pause(r) and not playing:
                print('PAUSE pressed, playing 56s (PAUSE again to stop)', flush=True)
                playing = True
                try:
                    done = play56(kb, [fd for _, fd in nodes])
                    print('finished' if done else 'stopped early', flush=True)
                except Exception as e:
                    print(f'play failed: {e}', flush=True)
                playing = False
    finally:
        kb.close()

if __name__ == '__main__':
    main()
