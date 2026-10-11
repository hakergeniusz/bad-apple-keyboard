#!/usr/bin/env python3
"""Probe GK630K feature reports + input reports on both interfaces."""
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
        print(f"intf{i} detach: {e}", flush=True)
    usb.util.claim_interface(dev, i)

def xfer(bm, req, val, idx, data_or_len, tag):
    try:
        r = dev.ctrl_transfer(bm, req, val, idx, data_or_len, timeout=800)
        r = bytes(r) if not isinstance(r, int) else r
        print(f"{tag}: OK sent={r}" if bm == 0x21 else f"{tag}: OK len={len(r)} data={r[:64].hex(' ')}", flush=True)
    except usb.core.USBError as e:
        print(f"{tag}: ERR {e}", flush=True)

try:
    # GET_FEATURE (0xA1,0x01? no: GET_REPORT=0x01) type Feature=3: wValue=0x0300|id
    for idx in (0, 1):
        xfer(0xA1, 0x01, 0x0300, idx, 64, f"GET_FEATURE id0 intf{idx}")
    # GET_REPORT Input ids 0..9 on intf1
    for rid in range(0, 10):
        xfer(0xA1, 0x01, 0x0100 | rid, 1, 64, f"GET_INPUT id{rid} intf1")
    # SET_FEATURE id0 zeros/ones on both intfs
    for idx in (0, 1):
        xfer(0x21, 0x09, 0x0300, idx, bytes(64), f"SET_FEATURE id0 zeros intf{idx}")
    for idx in (0, 1):
        xfer(0xA1, 0x01, 0x0300, idx, 64, f"GET_FEATURE id0 after intf{idx}")
finally:
    for i in (0, 1):
        try: usb.util.release_interface(dev, i)
        except Exception: pass
    for i in detached:
        try: dev.attach_kernel_driver(i)
        except usb.core.USBError: pass
    print("released", flush=True)
