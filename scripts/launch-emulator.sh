#!/usr/bin/env bash
# Launch the Android emulator without Android Studio and wait until it has booted.
# Usage: [HEADLESS=1] ./launch-emulator.sh [AVD_NAME] [extra emulator args...]
# Works on Linux and on Windows (Git Bash).
set -euo pipefail

if [ -n "${LOCALAPPDATA:-}" ]; then
  DEFAULT_SDK="$LOCALAPPDATA/Android/Sdk"; EXE=.exe
else
  DEFAULT_SDK="$HOME/Android/Sdk"; EXE=
fi
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$DEFAULT_SDK}}"
SDK="${SDK//\\//}"
EMULATOR="$SDK/emulator/emulator$EXE"
# Always address the emulator, never a phone that happens to be plugged in over USB.
SERIAL="${ANDROID_SERIAL:-emulator-5554}"
ADB=("$SDK/platform-tools/adb$EXE" -s "$SERIAL")
AVD="${1:-Pixel_8_API_36}"
shift || true
# INTTI (Unity) hangs on a black screen with guest Vulkan; host GLES works.
[ $# -eq 0 ] && set -- -gpu host -feature -Vulkan
# On Linux (Mesa) restoring the quick-boot snapshot segfaults in the GPU driver
# (xcb_dri3_pixmap_from_buffer failed), so always cold boot and never save one.
[ -z "$EXE" ] && set -- "$@" -no-snapshot
# HEADLESS=1: no emulator window (the bots only need the console).
[ -n "${HEADLESS:-}" ] && set -- "$@" -no-window

if [ -z "$EXE" ] && [ ! -w /dev/kvm ]; then
  echo "No write access to /dev/kvm: the emulator would be very slow. Add yourself to the 'kvm' group." >&2
  exit 1
fi

LOGS="$(cd "$(dirname "$0")/.." && pwd)/logs"; mkdir -p "$LOGS"
LOG="$LOGS/emulator.log"
PID=
if "${ADB[@]}" devices | grep -q "^$SERIAL[[:space:]]"; then
  echo "$SERIAL is already running."
else
  echo "Starting AVD '$AVD'..."
  # Detached (own session on Linux) so it survives closing this terminal; output goes to a log file.
  DETACH=(nohup); command -v setsid >/dev/null && DETACH=(setsid nohup)
  "${DETACH[@]}" "$EMULATOR" -avd "$AVD" -port "${SERIAL#emulator-}" "$@" > "$LOG" 2>&1 &
  PID=$!
fi

printf "Waiting for boot"
until [ "$("${ADB[@]}" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do
  if [ -n "$PID" ] && ! kill -0 "$PID" 2>/dev/null; then
    echo " emulator exited. Last lines of $LOG:" >&2; tail -n 20 "$LOG" >&2; exit 1
  fi
  printf "."; sleep 2
done
echo " booted."
"${ADB[@]}" devices
