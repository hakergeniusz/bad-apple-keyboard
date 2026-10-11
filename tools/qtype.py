#!/usr/bin/env python3
"""Type text into the QEMU guest via one persistent monitor connection.
Usage: qtype.py 'text to type\nwith ret'  (\\n = Enter, \\t = Tab, \\e = Esc)
"""
import socket, sys, time

SOCK = "/var/tmp/ai-agent/gk630k/monitor.sock"

SHIFTED = {
    '!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7',
    '*': '8', '(': '9', ')': '0', '_': 'minus', '+': 'equal', '{': 'bracket_left',
    '}': 'bracket_right', '|': 'backslash', ':': 'semicolon', '"': 'apostrophe',
    '<': 'comma', '>': 'dot', '?': 'slash', '~': 'grave',
}
PLAIN = {
    ' ': 'spc', '.': 'dot', ',': 'comma', '/': 'slash', '\\': 'backslash',
    '-': 'minus', '=': 'equal', ';': 'semicolon', "'": 'apostrophe',
    '[': 'bracket_left', ']': 'bracket_right', '`': 'grave',
    '\n': 'ret', '\t': 'tab', '\x1b': 'esc',
}

def key_for(ch):
    if ch in PLAIN:
        return [PLAIN[ch]]
    if ch in SHIFTED:
        return ['shift-' + SHIFTED[ch]]
    if 'a' <= ch <= 'z' or '0' <= ch <= '9':
        return [ch]
    if 'A' <= ch <= 'Z':
        return ['shift-' + ch.lower()]
    raise ValueError(f"no mapping for {ch!r}")

def main():
    text = sys.argv[1].encode().decode('unicode_escape') if len(sys.argv) > 1 else ''
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(SOCK)
    try:
        s.recv(65536)  # banner
    except socket.timeout:
        pass
    for ch in text:
        s.sendall(b'sendkey ' + '-'.join(key_for(ch)).encode() + b'\n')
        # 'shift-semicolon' style = combo press in sequence
        time.sleep(0.09)
    s.settimeout(0.2)
    try:
        while s.recv(65536):
            pass
    except socket.timeout:
        pass
    s.close()
    print(f"typed {len(text)} chars")

if __name__ == '__main__':
    main()
