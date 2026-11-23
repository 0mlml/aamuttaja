"""Fast taps through the Android emulator console (telnet, port 5554).

Why not the alternatives:
- `adb shell input tap` / uiautomator2 clicks: ~6 taps/s.
- Writing raw events to /dev/input/eventN: blocked by SELinux on the
  (non-rooted) Google Play image.
The console's `event send` injects through the emulator's virtual multitouch
device, exactly like a mouse click in the emulator window, over one persistent
socket.
"""
import os
import socket
import time

ABS_MAX = 32767
TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".emulator_console_auth_token")


class Touch:
    def __init__(self, port=5554, host="127.0.0.1"):
        self.sock = socket.create_connection((host, port), timeout=5)
        self._read_until(b"OK\r\n")  # banner
        with open(TOKEN_FILE) as f:
            token = f.read().strip()
        self.cmd(f"auth {token}")

    def _read_until(self, marker):
        buf = b""
        while not buf.endswith(marker) and b"KO:" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("emulator console closed")
            buf += chunk
        if b"KO:" in buf:
            raise RuntimeError(buf.decode(errors="replace").strip())
        return buf

    def cmd(self, line):
        self.sock.sendall(line.encode() + b"\n")
        return self._read_until(b"OK\r\n")

    @staticmethod
    def _xy(xf, yf):
        return round(xf * ABS_MAX), round(yf * ABS_MAX)

    def down(self, xf, yf):
        x, y = self._xy(xf, yf)
        self.cmd(
            "event send EV_ABS:ABS_MT_TRACKING_ID:0 "
            f"EV_ABS:ABS_MT_POSITION_X:{x} EV_ABS:ABS_MT_POSITION_Y:{y} "
            "EV_ABS:ABS_MT_PRESSURE:1024 EV_SYN:0:0"
        )

    def up(self):
        self.cmd("event send EV_ABS:ABS_MT_PRESSURE:0 EV_ABS:ABS_MT_TRACKING_ID:-1 EV_SYN:0:0")

    def tap(self, xf, yf, hold=0.0):
        """Tap at a fractional screen position (0..1, 0..1)."""
        self.down(xf, yf)
        if hold:
            time.sleep(hold)
        self.up()

    def burst(self, xf, yf, n, hold=0.0, gap=0.0):
        for _ in range(n):
            self.tap(xf, yf, hold)
            if gap:
                time.sleep(gap)

    def move(self, xf, yf):
        x, y = self._xy(xf, yf)
        self.cmd(f"event send EV_ABS:ABS_MT_POSITION_X:{x} EV_ABS:ABS_MT_POSITION_Y:{y} EV_SYN:0:0")

    def drag(self, x0, y0, x1, y1, steps=12, step_time=0.02, settle=0.3):
        """Drag without fling: move in steps, hold still before lifting."""
        self.down(x0, y0)
        time.sleep(step_time)
        for k in range(1, steps + 1):
            self.move(x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps)
            time.sleep(step_time)
        time.sleep(settle)
        self.up()

    def multi_down(self, points):
        """Press several fingers at once (one per MT slot, type-B protocol)."""
        ev = []
        for slot, (xf, yf) in enumerate(points):
            x, y = self._xy(xf, yf)
            ev += [f"EV_ABS:ABS_MT_SLOT:{slot}", f"EV_ABS:ABS_MT_TRACKING_ID:{slot}",
                   f"EV_ABS:ABS_MT_POSITION_X:{x}", f"EV_ABS:ABS_MT_POSITION_Y:{y}",
                   "EV_ABS:ABS_MT_PRESSURE:1024"]
        self.cmd("event send " + " ".join(ev + ["EV_SYN:0:0"]))

    def multi_up(self, count):
        ev = []
        for slot in range(count):
            ev += [f"EV_ABS:ABS_MT_SLOT:{slot}", "EV_ABS:ABS_MT_PRESSURE:0", "EV_ABS:ABS_MT_TRACKING_ID:-1"]
        self.cmd("event send " + " ".join(ev + ["EV_ABS:ABS_MT_SLOT:0", "EV_SYN:0:0"]))

    def multi_tap(self, points, hold=0.035):
        self.multi_down(points)
        time.sleep(hold)
        self.multi_up(len(points))

    def close(self):
        try:
            self.sock.sendall(b"quit\n")
        finally:
            self.sock.close()


class InjectTouch:
    """Same API as Touch, for devices without an emulator console (Waydroid, phones).

    Runs injector/inject.dex under app_process in one persistent `adb shell` and streams
    commands to it. The shell user may inject input (INJECT_EVENTS), so no root is needed.
    """
    REMOTE = "/data/local/tmp/inject.dex"

    def __init__(self):
        import subprocess
        from . import device
        self._subprocess = subprocess
        w, h = device.REF_W, device.REF_H
        out = device.adb("shell", "wm", "size").stdout.decode()
        for line in out.splitlines():  # an override size wins over the physical one
            if "size:" in line:
                w, h = map(int, line.split(":")[1].strip().split("x"))
        from .paths import INJECTOR_DEX as local
        device.adb("push", local, self.REMOTE)
        self._argv = [*device.ADB, "shell", f"CLASSPATH={self.REMOTE} exec app_process / Inject {w} {h}"]
        self._start()

    def _start(self):
        self.proc = self._subprocess.Popen(self._argv, stdin=self._subprocess.PIPE,
                                           stdout=self._subprocess.PIPE, bufsize=0)
        self.cmd("p")
        if self.proc.stdout.readline().strip() != b"ok":
            raise ConnectionError("injector didn't start")

    def cmd(self, line):
        try:
            self.proc.stdin.write(line.encode() + b"\n")
        except (BrokenPipeError, OSError):  # the adb shell dropped: start a new one, resend
            self.proc.kill()
            self._start()
            self.proc.stdin.write(line.encode() + b"\n")

    def sync(self):
        """Block until the injector has handled every command sent so far."""
        self.cmd("p")
        if self.proc.stdout.readline().strip() != b"ok":
            self.proc.kill()      # it died: start a new one (fingers it held are lifted)
            self._start()

    def down(self, xf, yf):
        self.cmd(f"d {xf:.5f} {yf:.5f}")

    def up(self):
        self.cmd("u")

    def move(self, xf, yf):
        self.cmd(f"m {xf:.5f} {yf:.5f}")

    def add_finger(self, xf, yf):
        """Press one more finger while others stay down."""
        self.cmd(f"a {xf:.5f} {yf:.5f}")

    def lift_finger(self):
        """Lift the most recently added finger."""
        self.cmd("r")

    tap = Touch.tap
    burst = Touch.burst
    drag = Touch.drag

    def multi_down(self, points):
        self.cmd("D " + " ".join(f"{x:.5f} {y:.5f}" for x, y in points))

    def multi_up(self, count):
        self.cmd("U")

    multi_tap = Touch.multi_tap

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()
