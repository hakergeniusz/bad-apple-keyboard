#!/usr/bin/env python3
"""GK630K (Evision 3299:4E5A) vendor protocol over hidraw. Adapted from hivectl's
EVision V2 protocol: 64-byte packets [04, ck_lo, ck_hi, cmd, size, off_lo, off_hi, 00, data]."""
import os, select, time

VID, PID = 0x3299, 0x4E5A
REPORT_ID = 0x04
PACKET_SIZE = 64
HEADER_SIZE = 8
CHUNK_SIZE = 56

CMD_BEGIN_CONFIG = 0x01
CMD_END_CONFIG = 0x02
CMD_READ_CONFIG = 0x05
CMD_WRITE_CONFIG = 0x06
CMD_READ_KEYMAP = 0x07
CMD_READ_CUSTOM_LEDS = 0x0A
CMD_WRITE_CUSTOM_LEDS = 0x0B
CMD_SEND_FRAME = 0x12
CMD_END_FRAME = 0x13

NUM_SLOTS = 128
FRAME_SIZE = NUM_SLOTS * 3
OFFSET_ACTIVE_PROFILE = 0x00
PROFILE_OFFSETS = (0x01, 0x41, 0x81)
CONFIG_SIZE = 0xC0

def find_hidraw():
    import glob, re
    want = f"HID_ID=0003:{VID:08X}:{PID:08X}"
    cands = []
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            uevent = open(f"{node}/device/uevent").read()
        except OSError:
            continue
        if want in uevent:
            m = re.search(r"HID_PHYS=.*/input\d+$", uevent, re.M)
            phys = m.group(0) if m else ""
            cands.append((phys, "/dev/" + node.rsplit("/", 1)[-1]))
    # vendor interface = input1
    for phys, dev in cands:
        if "input1" in phys:
            return dev
    raise RuntimeError(f"vendor hidraw not found: {cands}")

class GK630K:
    def __init__(self, path=None):
        self.path = path or find_hidraw()
        self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        self._drain()

    def close(self):
        if self.fd is not None:
            os.close(self.fd); self.fd = None

    def __enter__(self): return self
    def __exit__(self, *e): self.close()

    def _drain(self):
        while select.select([self.fd], [], [], 0)[0]:
            try: os.read(self.fd, PACKET_SIZE)
            except BlockingIOError: break

    def query(self, cmd, offset=0, data=b"", size=None, timeout=0.5):
        self._drain()
        pkt = bytearray(PACKET_SIZE)
        pkt[0] = REPORT_ID
        pkt[3] = cmd
        pkt[4] = len(data) if size is None else size
        pkt[5] = offset & 0xFF
        pkt[6] = (offset >> 8) & 0xFF
        pkt[HEADER_SIZE:HEADER_SIZE + len(data)] = data
        ck = sum(pkt[3:]) & 0xFFFF
        pkt[1] = ck & 0xFF; pkt[2] = ck >> 8
        os.write(self.fd, pkt)
        deadline = time.monotonic() + timeout
        while True:
            rem = deadline - time.monotonic()
            if rem <= 0:
                raise TimeoutError(f"no reply to cmd 0x{cmd:02X}")
            if not select.select([self.fd], [], [], rem)[0]:
                continue
            resp = os.read(self.fd, PACKET_SIZE)
            if len(resp) == PACKET_SIZE and resp[0] == REPORT_ID and resp[3] == cmd \
                    and (resp[5] | (resp[6] << 8)) == (offset & 0xFFFF):
                return resp

    def _read(self, cmd, offset, length):
        out = bytearray()
        while len(out) < length:
            n = min(CHUNK_SIZE, length - len(out))
            out += self.query(cmd, offset + len(out), size=n)[HEADER_SIZE:HEADER_SIZE + n]
        return bytes(out)

    def _write(self, cmd, offset, data):
        self.query(CMD_BEGIN_CONFIG)
        try:
            for pos in range(0, len(data), CHUNK_SIZE):
                self.query(cmd, offset + pos, data[pos:pos + CHUNK_SIZE])
        finally:
            self.query(CMD_END_CONFIG)

    def read_config(self, offset=0, length=CONFIG_SIZE):
        return self._read(CMD_READ_CONFIG, offset, length)

    def write_config(self, offset, data):
        self._write(CMD_WRITE_CONFIG, offset, data)
        if self.read_config(offset, len(data)) != bytes(data):
            raise IOError("read-back mismatch")

    def read_keymap(self):
        return self._read(CMD_READ_KEYMAP, 0, FRAME_SIZE)

    def read_custom_leds(self):
        return self._read(CMD_READ_CUSTOM_LEDS, 0, FRAME_SIZE)

    def write_custom_leds(self, data):
        assert len(data) == FRAME_SIZE
        self._write(CMD_WRITE_CUSTOM_LEDS, 0, data)
        if self.read_custom_leds() != bytes(data):
            raise IOError("custom LED read-back mismatch")

    def send_frame(self, frame):
        assert len(frame) == FRAME_SIZE
        for pos in range(0, FRAME_SIZE, CHUNK_SIZE):
            self.query(CMD_SEND_FRAME, pos, frame[pos:pos + CHUNK_SIZE], timeout=0.15)

    def end_frames(self):
        self.query(CMD_END_FRAME)
