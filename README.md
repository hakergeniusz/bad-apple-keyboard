# bad-apple-keyboard

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Play video on an **SPC Gear GK630K** keyboard's per-key RGB — including a
custom **`--vo=rgb-keyboard` video output for mpv**. No Windows software needed.

Reverse engineered from scratch: the board is an **Evision 3299:4E5A** device
speaking the Evision vendor HID protocol (same family as Kreo Hive 98 —
thanks to [hivectl](https://github.com/omsingh02/hivectl) for documenting it).

## Protocol (Evision, USB 3299:4E5A, HID interface 1)

- 64-byte packets, report ID `0x04`:
  `[04, cksum_lo, cksum_hi, cmd, size, off_lo, off_hi, 00, data...]`,
  checksum = sum of bytes 3..63 mod 0xFFFF.
- Commands: `01` begin-config, `02` end-config, `05` read-config,
  `06` write-config, `07` read-keymap, `0A` read-custom-LEDs,
  `0B` write-custom-LEDs, `12` send-frame (streaming, RAM only),
  `13` end-frames. Replies echo cmd + offset.
- Matrix: slot = column * 8 + row, 128 slots × 3 bytes RGB.
- Config: byte 0 = active profile; profiles at 0x01/0x41/0x81
  (mode, brightness, speed, direction, rainbow, R, G, B).
  Modes include `0x01` wave … `0x14` custom.
- Transport is control SET_REPORT (output) + interrupt IN (replies) —
  works over plain hidraw, no driver.

## Files

- `gk630k.py` — protocol library (read/write profiles, keymap, custom LEDs,
  live frame streaming with read-back verification).
- `gk630k_layout.py` — matrix slot → physical key positions (ISO TKL).
- `play_badapple.py` — streams `data/badapple.kbd` at 30 fps.
- `tools/make_frames.py` — renders `frames.rgb` (128×64 rgb24 @30fps)
  into per-key `badapple.kbd` frames.
- `mpv-vo/vo_rgb_keyboard.c` — mpv video output: `mpv --vo=rgb-keyboard file`
  (`+vo_rgb_keyboard_map.h`, generated sampling rects).
- `mpv-vo/0001-vo-rgb-keyboard-integration.patch` — hooks the driver into
  mpv's build (meson.build + video/out/vo.c).
- `tools/build_mpv.sh` — builds mpv with the driver and writes `./mpv-bin`.
- `mpv-bin` — prebuilt mpv v0.41.0 with `--vo=rgb-keyboard`.
- `tools/` — RE notes: usbmon capture parser, descriptors, probes.
- `71-gk630k.rules` — udev rule so hidraw is user-writable.

## udev

```
sudo cp 71-gk630k.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw
```

## mpv VO build

`mpv-bin` is a prebuilt mpv v0.41.0 with the `rgb-keyboard` video output.
Rebuild it from this repo (patches a clean mpv checkout):

```sh
./tools/build_mpv.sh          # -> ./mpv-bin
```

Needs `meson`, `ninja`, a C compiler and mpv's build deps (ffmpeg,
libplacebo, …).  The mpv checkout lives in `~/.cache/ai-agent/mpv-src`
(override with `MPV_SRC=...`); the script clones mpv v0.41.0 if missing,
resets the tree, copies `mpv-vo/vo_rgb_keyboard.{c,map.h}` into
`video/out/`, applies the integration patch and rebuilds.

Usage:

```sh
./mpv-bin --vo=rgb-keyboard bad_apple.mkv                    # audio + keys
./mpv-bin --vo=rgb-keyboard --vo-rgb-keyboard-max-fps=60 bad_apple.mkv
./mpv-bin --vo=rgb-keyboard --vo-rgb-keyboard-brightness=0.6 bad_apple.mkv
./mpv-bin --vo=rgb-keyboard --vo-rgb-keyboard-device=/dev/hidraw1 bad_apple.mkv
```

Note: mpv removed `--vo=driver=opt=value` sub-options in 0.23, so driver
options are passed as separate global options named `--vo-<driver>-<option>`.
`--vo=rgb-keyboard=max-fps=60` is an *error*, not a shortcut.

The driver streams frames to RAM only (command `0x12`), so the stored
lighting profile is never touched.  On SIGINT/SIGTERM it sends the
end-of-frame command (`0x13`) from a signal handler, so the keyboard never
stays stuck in frame-streaming mode.

Throughput is limited by the USB round trips, not by mpv: every frame is 7
request/reply packets (56 B each, the last one 48 B), which caps the board
at ~25 fps (`--vo-rgb-keyboard-max-fps=60`); the default 30 fps cap yields
~15 fps.  Measure with `tools/bench_fps.sh`.

## Bad Apple

```sh
ffmpeg -i bad_apple.mkv -vf fps=30,scale=128:64 -pix_fmt rgb24 -f rawvideo frames.rgb
python3 tools/make_frames.py   # -> data/badapple.kbd
python3 play_badapple.py       # 30 fps stream, then returns to stored profile
```
