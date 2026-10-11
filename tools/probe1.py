#!/usr/bin/env python3
"""Probe the GK630K RGB interface (intf1) with SET_REPORT Output ID0 payloads.
Watches EP 0x82 interrupt-IN and GET_REPORT for replies."""
import sys, time
import usb.core, usb.util

VID, PID = 0x3299, 0x4E5A

def open_kb():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        raise SystemExit("keyboard not found")
    dev._detached = False
    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass
    cfg = dev.get_active_configuration()
    intf1 = cfg[(1, 0)]
    if dev.is_kernel_driver_active(1):
        dev.detach_kernel_driver(1)
        dev._detached = True
    usb.util.claim_interface(dev, 1)
    ep_in = None
    for ep in intf1:
        if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN:
            ep_in = ep
    print(f"opened, EP_IN=0x{ep_in.bEndpointAddress:02x} maxpkt={ep_in.wMaxPacketSize}", flush=True)
    return dev, ep_in

def drain(dev, ep, timeout=150):
    """Read all pending interrupt-IN packets."""
    out = []
    while True:
        try:
            d = dev.read(ep.bEndpointAddress, ep.wMaxPacketSize, timeout=timeout)
            out.append(bytes(d))
        except usb.core.USBTimeoutError:
            break
        except usb.core.USBError as e:
            out.append(("ERR", str(e)))
            break
    return out

def set_report(dev, payload, wValue=0x0200, wIndex=0x0001):
    # bmRequestType 0x21 = Host->Device, Class, Interface
    return dev.ctrl_transfer(0x21, 0x09, wValue, wIndex, payload, timeout=1000)

def get_report_input(dev, rep_id=4, length=64, wIndex=0x0001):
    try:
        return bytes(dev.ctrl_transfer(0xA1, 0x01, 0x0100 | rep_id, wIndex, length, timeout=500))
    except usb.core.USBError as e:
        return ("ERR", str(e))

def main():
    dev, ep = open_kb()
    try:
        drain(dev, ep)  # flush stale
        # 1. reproduce app probe
        print("== probe [00] ==", flush=True)
        n = set_report(dev, bytes([0x00]))
        print("sent:", n, flush=True)
        time.sleep(0.3)
        for p in drain(dev, ep):
            print("IN reply:", p.hex(' ') if isinstance(p, bytes) else p, flush=True)
        print("GET_REPORT input id4:", get_report_input(dev), flush=True)
        # 2. sweep single bytes
        if len(sys.argv) > 1 and sys.argv[1] == "sweep":
            for b in range(256):
                try:
                    set_report(dev, bytes([b]))
                except usb.core.USBError as e:
                    print(f"[{b:02x}] send ERR {e}", flush=True)
                    continue
                time.sleep(0.02)
                pkts = drain(dev, ep, timeout=60)
                if pkts:
                    print(f"[{b:02x}] REPLY:", [p.hex(' ') if isinstance(p, bytes) else p for p in pkts], flush=True)
            print("sweep done", flush=True)
    finally:
        usb.util.release_interface(dev, 1)
        if dev._detached:
            try:
                dev.attach_kernel_driver(1)
            except usb.core.USBError:
                pass
        print("released", flush=True)

main()
