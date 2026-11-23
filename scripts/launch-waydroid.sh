#!/usr/bin/env bash
# Start (or restart) Waydroid on its own headless Wayland compositor and open INTTI.
# Usage: ./launch-waydroid.sh            # headless (weston), for unattended runs
#        DESKTOP=1 ./launch-waydroid.sh  # in a window on the desktop instead
#
# Why headless: on the desktop, Waydroid's frames are only taken when its window is on
# screen. Hidden, minimized or with the screen locked, Android's buffers run out
# ("dequeueBuffer failed, error = -110", "Buffer failed to allocate"): screenshots fail,
# then rendering and INTTI stall. A headless weston always takes the frames. Its kiosk shell:
# the default desktop shell has a 32 px panel, and Waydroid insists on 540x1200 (protocol error).
set -euo pipefail
LOGS="$(cd "$(dirname "$0")/.." && pwd)/logs"; mkdir -p "$LOGS"

SOCKET=wayland-waydroid
SERIAL=192.168.240.112:5555
ADB="${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}/platform-tools/adb"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

if [ -z "${DESKTOP:-}" ]; then
  if [ ! -S "$XDG_RUNTIME_DIR/$SOCKET" ]; then
    echo "Starting headless weston on $SOCKET"
    setsid nohup weston --backend=headless --renderer=gl --shell=kiosk --socket="$SOCKET" \
      --width=540 --height=1200 > "$LOGS/weston.log" 2>&1 < /dev/null &
    for _ in $(seq 20); do [ -S "$XDG_RUNTIME_DIR/$SOCKET" ] && break; sleep 0.5; done
  fi
  export WAYLAND_DISPLAY="$SOCKET"
fi

"$ADB" disconnect "$SERIAL" > /dev/null 2>&1 || true
waydroid session stop > /dev/null 2>&1 || true
sleep 3
echo "Starting the Waydroid session on $WAYLAND_DISPLAY"
setsid nohup waydroid session start > "$LOGS/waydroid.log" 2>&1 < /dev/null &

printf "Waiting for Android"
until [ "$(timeout 5 "$ADB" -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; do
  "$ADB" connect "$SERIAL" > /dev/null 2>&1 || true
  printf "."; sleep 3
done
echo " booted."
waydroid prop set persist.waydroid.suspend false
setsid nohup waydroid show-full-ui > /dev/null 2>&1 < /dev/null &
sleep 5
timeout 15 "$ADB" -s "$SERIAL" shell am start -n com.OneGlitch.INTTI/com.unity3d.player.UnityPlayerActivity > /dev/null
echo "INTTI started."
