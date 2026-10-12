# AGENTS.md — bad-apple-keyboard

## Hardware
SPC Gear GK630K = Evision `3299:4E5A`. All RGB traffic goes through **HID
interface 1** (`input1` hidraw node). Never send vendor reports to interface 0.

## Safety
- `backup_config.bin` / `backup_custom.bin` are the owner's saved lighting.
  Never overwrite them. Restore them (`write_config` + `write_custom_leds`)
  after any experiment that changes stored state. RAM-only frame streaming
  (`0x12`/`0x13`) needs no restore.
- **One hidraw writer at a time.** `pause_daemon.py` streams constantly when
  its service runs; a second writer (mpv VO, one-off scripts) interleaves
  chunks and steals replies, which looks like firmware timeouts. Stop
  `bad-apple-pause.service` before any other streaming, restart after.
- Do not pass the keyboard to a VM while the daemon runs — detach/attach
  around it.
- Do not re-run blind fuzz probes (`tools/probe*.py`); an output-report sweep
  once wedged firmware key state. Prefer targeted commands from `gk630k.py`.

## Protocol (see README.md for the full table)
- 64B packets, report ID `0x04`, checksum = sum of bytes 3..63 mod 0xFFFF.
- Replies echo cmd + offset — always verify, never fire-and-forget.
- `SEND_FRAME (0x12)` chunks are 56B, **except the last: send only
  `FRAME_SIZE - pos` (48B)**. The firmware silently drops an overshooting
  chunk and the stream stalls with no reply.
- Slot = column * 8 + row, 128 slots × RGB. Rows 6–7 are phantoms (no LED);
  `gk630k_layout.slot_pos()` returns None for them — skip those.

## Commands
Run from the repo root with `uv run --no-project [--with numpy] python`.
Scripts hardcode absolute paths under `BASE` — keep them consistent if moved.
- Daemon: `systemctl --user [start|stop|restart|status] bad-apple-pause.service`
  (unit file: `bad-apple-pause.service`, installed to `~/.config/systemd/user/`).
- Frame pipeline: `tools/make_frames.py` reads `data/frames.rgb`, writes
  `data/badapple.kbd`. Do not commit new large captures (`data/*.bin`,
  `*.asm` are gitignored for a reason).
- mpv VO: sources live in `mpv-vo/`; build/register steps are in README.md
  ("mpv VO build"). After editing the driver, copy it back to `mpv-vo/`.

## Completion
Report the changed files and checks run. End every session with the owner's
lighting restored and the working tree committed + pushed.
(Note: the idle daemon is currently disabled — it fought the mpv VO over
the hidraw node. Re-enable only if VO use is paused.)
