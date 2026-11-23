"""Device access shared by the bots: which Android to talk to, screenshots, touch.

Two targets are supported:
- Waydroid (default): `ANDROID_SERIAL` defaults to Waydroid's adb address. Touch goes through
  native/injector/inject.dex (a persistent app_process program; no root needed).
- The Android emulator: set `ANDROID_SERIAL=emulator-5554`. Touch goes through the emulator
  console (touch.Touch).
"""
import os
import shutil
import subprocess
import time

import numpy as np
from PIL import Image

from .paths import INJECTOR_DEX, LAUNCH_WAYDROID
WAYDROID_SERIAL = "192.168.240.112:5555"
SERIAL = os.environ.get("ANDROID_SERIAL", WAYDROID_SERIAL)
REF_W, REF_H = 540, 1200   # every template and coordinate in this repo is for this screen size


def adb_path():
    for sdk in (os.environ.get("ANDROID_SDK_ROOT"), os.environ.get("ANDROID_HOME"),
                os.path.expanduser("~/Android/Sdk"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk")):
        if sdk:
            for exe in ("adb", "adb.exe"):
                p = os.path.join(sdk, "platform-tools", exe)
                if os.path.exists(p):
                    return p
    return shutil.which("adb") or "adb"


ADB = [adb_path(), "-s", SERIAL]


def is_emulator():
    return SERIAL.startswith("emulator-")


def adb(*args, check=True, **kw):
    if ":" in SERIAL:  # network device (Waydroid): make sure adb is connected
        subprocess.run([ADB[0], "connect", SERIAL], capture_output=True, timeout=10)
    return subprocess.run([*ADB, *args], check=check, capture_output=True, **kw)


class FrameStream:
    """Frames from injector's Capture (a persistent app_process program mirroring the display
    into an ImageReader, like scrcpy): the latest frame in ~3.5 ms instead of ~100 ms per
    `screencap`. The game renders a new frame every ~25 ms; a frame is ~14 ms old on arrival."""
    REMOTE = "/data/local/tmp/inject.dex"

    def __init__(self):
        self.p = None
        self.ts = 0          # device timestamp (ns) of the last frame
        self.pushed = False

    def start(self):
        if not self.pushed:
            adb("push", INJECTOR_DEX, self.REMOTE)
            self.pushed = True
        self.p = subprocess.Popen([*ADB, "shell", "-T", "app_process", f"-Djava.class.path={self.REMOTE}", "/",
                                   "Capture", str(REF_W), str(REF_H), "0", "0", str(REF_W), str(REF_H)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        end = time.time() + 5   # the first frames come once the virtual display is up
        while True:
            a = self._read()
            if a.any() or time.time() > end:
                return

    def _read(self):
        self.p.stdin.write(b"f")
        self.p.stdin.flush()
        hdr = self.p.stdout.read(16)
        n = REF_W * REF_H * 4
        buf = self.p.stdout.read(n)
        if len(hdr) < 16 or len(buf) < n:
            raise BrokenPipeError("capture stream ended")
        self.ts = int.from_bytes(hdr[:8], "big", signed=True)
        return np.frombuffer(buf, np.uint8).reshape(REF_H, REF_W, 4)[:, :, :3]

    def frame(self):
        for attempt in range(2):
            try:
                if self.p is None or self.p.poll() is not None:
                    self.start()
                return self._read()
            except (BrokenPipeError, OSError):
                self.close()
        raise RuntimeError("capture stream keeps failing")

    def close(self):
        if self.p is not None:
            try:
                self.p.kill()
            except OSError:
                pass
            self.p = None


_stream = None


def screenshot_array():
    """Current screen as an HxWx3 uint8 array: from the capture stream on Waydroid (falls back
    to screencap if it fails), else raw screencap."""
    global _stream
    if not is_emulator() and os.environ.get("AAMUTTAJA_SCREENCAP") != "1":
        if _stream is None:
            _stream = FrameStream()
        try:
            return _stream.frame()
        except RuntimeError:
            pass
    return screencap_array()


def screencap_array():
    """Current screen via `adb exec-out screencap` (raw: much faster than PNG), ~100 ms."""
    for attempt in range(10):  # adb sometimes drops out for seconds (empty output): reconnect, retry
        raw = subprocess.run([*ADB, "exec-out", "screencap"], capture_output=True, timeout=10).stdout
        if len(raw) > 16:
            break
        if ":" in SERIAL:
            subprocess.run([ADB[0], "connect", SERIAL], capture_output=True, timeout=10)
        time.sleep(1.0)
    for header in (16, 12):  # Android 12+: w, h, format, colorspace; older: w, h, format
        w, h = int.from_bytes(raw[0:4], "little"), int.from_bytes(raw[4:8], "little")
        if len(raw) - header == w * h * 4:
            return np.frombuffer(raw, np.uint8, offset=header).reshape(h, w, 4)[:, :, :3]
    raise RuntimeError(f"unexpected screencap size {len(raw)}")


def screenshot():
    return Image.fromarray(screenshot_array())


def make_touch():
    if is_emulator():
        from .touch import Touch
        return Touch(port=int(SERIAL.split("-")[1]))
    from .touch import InjectTouch
    return InjectTouch()


def wait_until(pred, timeout, interval=0.3):
    end = time.time() + timeout
    while time.time() < end:
        r = pred()
        if r:
            return r
        time.sleep(interval)
    return None


PACKAGE = "com.OneGlitch.INTTI"
ACTIVITY = PACKAGE + "/com.unity3d.player.UnityPlayerActivity"
ANR_WAIT = (141, 651)   # "Wait" in Android's "INTTI isn't responding" dialog


def focused_window():
    out = adb("shell", "dumpsys", "window", check=False, timeout=10).stdout.decode(errors="replace")
    for line in out.splitlines():
        if "mCurrentFocus" in line:
            return line.strip()
    return ""


def anr_shown():
    """Android's "isn't responding" dialog is up (Unity under Waydroid sometimes misses focus
    events when the keyboard opens or closes)."""
    return "Not Responding" in focused_window()


def keyboard_shown():
    """Android's soft keyboard is up (from the input method service, not the screen)."""
    out = adb("shell", "dumpsys", "input_method", check=False, timeout=10).stdout.decode(errors="replace")
    return "mInputShown=true" in out


def crash_looping(within=10.0):
    """INTTI is stuck in a crash loop: a native crash report (tag CRASH) in logcat within the last
    `within` s. Seen 2026-11-22: a null dereference in a Java -> C# callback (AndroidJavaProxy.Invoke
    -> MonoBehaviour.InvokeDelayed) every ~200 ms; Unity's handler catches it, so the app neither
    dies nor runs: the game freezes and every tap is lost."""
    out = adb("logcat", "-d", "-v", "epoch", "-s", "CRASH:E", "-t", "5", check=False,
              timeout=10).stdout.decode(errors="replace")
    for line in reversed(out.splitlines()):
        try:
            return time.time() - float(line.split()[0]) < within
        except (ValueError, IndexError):
            continue
    return False


def app_running():
    return adb("shell", "pidof", PACKAGE, check=False, timeout=10).returncode == 0


def launch_app(wait=30):
    adb("shell", "am", "start", "-n", ACTIVITY, check=False, timeout=15)
    time.sleep(wait)


def stop_app():
    adb("shell", "am", "force-stop", PACKAGE, check=False, timeout=15)


def restart_waydroid():
    """Waydroid degrades when its frames aren't taken (screenshots fail with 'Buffer failed to
    allocate', then adb hangs): restart the session with launch-waydroid.sh, which also runs it
    on a headless compositor and starts INTTI. No sudo needed; settings persist."""
    if not SERIAL.startswith("192.168.240."):
        return False
    r = subprocess.run([LAUNCH_WAYDROID], capture_output=True, timeout=300)
    return r.returncode == 0
