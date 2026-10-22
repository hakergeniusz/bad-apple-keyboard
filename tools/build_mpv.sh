#!/bin/bash
# Build mpv v0.41.0 with the rgb-keyboard video output and install the
# resulting binary as ./mpv-bin.
#
# Sources of truth (all in this repo):
#   mpv-vo/vo_rgb_keyboard.c                       - the video output driver
#   mpv-vo/vo_rgb_keyboard_map.h                   - per-key sampling rects
#   mpv-vo/0001-vo-rgb-keyboard-integration.patch  - mpv build integration
#
# The mpv checkout lives outside the repo (it is big).  Override the
# location with MPV_SRC=... if you want it somewhere else.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${MPV_SRC:-$HOME/.cache/ai-agent/mpv-src}"
OUT="$REPO/mpv-bin"
PATCH="$REPO/mpv-vo/0001-vo-rgb-keyboard-integration.patch"
MPV_TAG="v0.41.0"

mkdir -p "$HOME/.cache/ai-agent"
export PATH="$HOME/.local/bin:$PATH"

if [ ! -d "$SRC/.git" ]; then
    echo "== cloning mpv $MPV_TAG"
    git clone --depth 1 --branch "$MPV_TAG" https://github.com/mpv-player/mpv.git "$SRC"
fi

cd "$SRC"

# 1. start from pristine upstream sources
git checkout -- meson.build video/out/vo.c
git clean -f -- video/out/vo_rgb_keyboard.c video/out/vo_rgb_keyboard_map.h

# 2. install the driver sources and hook them into mpv's build
cp "$REPO/mpv-vo/vo_rgb_keyboard.c" "$REPO/mpv-vo/vo_rgb_keyboard_map.h" video/out/
git apply --check "$PATCH"
git apply "$PATCH"
echo "== driver installed, integration patched"

# 3. configure + build
if [ ! -f build/build.ninja ]; then
    meson setup build --prefix="$HOME/.local" -Dbuildtype=release
fi
ninja -C build

# 4. install the binary into the repo
install -m 0755 build/mpv "$OUT"
echo "== wrote $OUT"

# 5. verify
if ! "$OUT" --vo=help | grep -q 'rgb-keyboard'; then
    echo "FAIL: rgb-keyboard video output is missing from $OUT"
    exit 1
fi
"$OUT" --version | head -1
echo "== OK: $OUT supports --vo=rgb-keyboard"
