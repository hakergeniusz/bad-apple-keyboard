#!/usr/bin/env python3
"""Sweep 1-byte commands on Output ID0 + Feature ID0, read back Input id4 / Feature / EP82."""
import sys, time
import usb.core, usb.util

VID, PID = 0x3299, 0x4E5A
dev = usb.core.find(idVendor=VID, idProduct=PID)
assert dev, "keyboard not found"
try:
    dev.set_configuration()
except usb.core.USBError:
    pass
detached = []
for i in (0, 1):
    try:
        if dev.is_kernel_driver_active(i):
            dev.detach_kernel_driver(i); detached.append(i)
    except usb.core.USBError as e:
        print(f"intf{i}: {e}", flush=True)
    usb.util.claim_interface(dev, i)

cfg = dev.get_active_configuration()
ep82 = None
for ep in cfg[(1, 0)]:
    if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN:
        ep82 = ep

def rd_ep(timeout=40):
    out = []
    while True:
        try:
            out.append(bytes(dev.read(ep82.bEndpointAddress, 64, timeout=timeout)))
        except usb.core.USBError:
            break
    return out

def get_in(rid, idx=1):
    try:
        return bytes(dev.ctrl_transfer(0xA1, 0x01, 0x0100 | rid, idx, 64, timeout=300))
    except usb.core.USBError as e:
        return f"ERR {e}"

def get_feat(idx=0):
    try:
        return bytes(dev.ctrl_transfer(0xA1, 0x01, 0x0300, idx, 64, timeout=300))
    except usb.core.USBError as e:
        return f"ERR {e}"

def nz(b):
    return isinstance(b, bytes) and len(b) > 0 and any(b)

try:
    rd_ep()
    mode = sys.argv[1] if len(sys.argv) > 1 else "out"
    for cmd in range(256):
        if mode == "out":
            try:
                dev.ctrl_transfer(0x21, 0x09, 0x0200, 1, bytes([cmd]), timeout=300)
            except usb.core.USBError as e:
                print(f"[{cmd:02x}] send ERR {e}", flush=True); continue
            time.sleep(0.015)
            pkts = rd_ep()
            g = get_in(4)
            if pkts or nz(g):
                print(f"[{cmd:02x}] EP82={[p.hex(' ') for p in pkts]} GET_IN4={g.hex(' ') if isinstance(g,bytes) else g}", flush=True)
        else:  # feature on intf0
            try:
                dev.ctrl_transfer(0x21, 0x09, 0x0300, 0, bytes([cmd]), timeout=300)
            except usb.core.USBError as e:
                print(f"[{cmd:02x}] send ERR {e}", flush=True); continue
            time.sleep(0.015)
            g = get_feat(0)
            if nz(g):
                print(f"[{cmd:02x}] GET_FEAT={g.hex(' ')}", flush=True)
    print("done", flush=True)
finally:
    for i in (0, 1):
        try: usb.util.release_interface(dev, i)
        except Exception: pass
    for i in detached:
        try: dev.attach_kernel_driver(i)
        except usb.core.USBError: pass
