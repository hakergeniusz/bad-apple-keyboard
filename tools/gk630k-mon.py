#!/usr/bin/env python3
"""Robust QEMU HMP monitor client: mon.py 'cmd1' 'cmd2' ..."""
import socket, sys, time

SOCK = "/var/tmp/ai-agent/gk630k/monitor.sock"

def run(cmds):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(10)
    s.connect(SOCK)
    out = b""
    def drain():
        nonlocal out
        try:
            while True:
                d = s.recv(65536)
                if not d:
                    break
                out += d
        except socket.timeout:
            pass
    drain()  # banner
    for c in cmds:
        s.sendall(c.encode() + b"\n")
        time.sleep(0.6)
        drain()
        print(f"--- {c}")
        # show tail of accumulated output
    s.close()
    text = out.decode(errors="replace")
    # crude de-echo: print last 1500 chars
    print(text[-1500:])

if __name__ == "__main__":
    run(sys.argv[1:] or ["info status"])
