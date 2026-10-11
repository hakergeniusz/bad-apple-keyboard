#!/usr/bin/env python3
"""usbmon binary capture + parse. Auto-syncs on repeating (bus,dev,ep) pattern.
Usage: cap.py <usbmonN> <seconds> <outfile>   (raw binary dump)
       cap.py parse <binfile>                 (decode + print summary)"""
import struct, sys, collections

HDRS = {48: "<QBBBBHbbqiiII8s", 56: "<QBBBBHbbqiiII8sii"}

def sync_events(buf):
    """Try header sizes; return (hdrlen, events). Event = dict."""
    best = None
    for hlen, fmt in HDRS.items():
        sz = struct.calcsize(fmt)
        assert sz == hlen, (fmt, sz)
        evs = []
        off = 0
        ok = True
        while off + hlen <= len(buf):
            try:
                (uid, typ, xt, ep, dev, bus, fs, fd, ts, tu,
                 status, length, lcap, setup) = struct.unpack_from(fmt, buf, off)[:14] if hlen == 48 else \
                    struct.unpack_from(fmt, buf, off)[:14]
            except struct.error:
                ok = False; break
            t = bytes([typ])
            if t not in b"SCE" or bus > 64 or dev > 127 or xt > 3:
                ok = False; break
            pad = lcap if t == b'S' else 0  # payload only on submit side? (both sides carry for ctrl)
            # usbmon: data follows on both S (out) and C (in); use lcap always
            pad = lcap
            if off + hlen + pad > len(buf):
                break  # truncated tail: stop cleanly
            evs.append(dict(id=uid, type=chr(typ), xfer=xt, ep=ep, dev=dev,
                            bus=bus, fs=chr(fs), fd=chr(fd), length=length,
                            lcap=lcap, setup=setup, data=buf[off+hlen:off+hlen+pad]))
            off += hlen + pad
        if ok and len(evs) > 3:
            # score: repeating S/C pairs with sane timestamps
            if best is None or len(evs) > len(best[1]):
                best = (hlen, evs)
    return best

XT = {0: "ISO", 1: "INT", 2: "CTRL", 3: "BULK"}

def show(evs, dev=None):
    for e in evs:
        if dev is not None and e["dev"] != dev:
            continue
        d = e["data"][:72].hex(" ")
        print(f"{e['type']} {XT[e['xfer']]:4s} bus={e['bus']} dev={e['dev']:3d} "
              f"ep=0x{e['ep']:02x} len={e['length']:4d} cap={e['lcap']:3d} "
              f"setup={e['setup'].hex(' ')} data={d}")

if __name__ == "__main__":
    if sys.argv[1] == "parse":
        buf = open(sys.argv[2], "rb").read()
        dev = int(sys.argv[3]) if len(sys.argv) > 3 else None
        print(f"file: {len(buf)} bytes")
        r = sync_events(buf)
        if not r:
            print("NO SYNC"); sys.exit(1)
        hlen, evs = r
        print(f"synced: header={hlen} events={len(evs)}")
        show(evs, dev)
    else:
        import time
        mon, secs, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
        fd = open(f"/dev/usbmon{mon}", "rb")
        t0 = time.time()
        chunks = []
        while time.time() - t0 < secs:
            import select
            r, _, _ = select.select([fd], [], [], 0.5)
            if r:
                chunks.append(fd.read1(1 << 16) if hasattr(fd, "read1") else fd.read(1 << 16))
        open(out, "wb").write(b"".join(chunks))
        print(f"captured {sum(map(len,chunks))} bytes -> {out}")
