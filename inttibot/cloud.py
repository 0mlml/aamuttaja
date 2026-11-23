"""INTTI's cloud save (BackendManager, https://www.intti-backend.com), and closing the app so it's kept.

    python -m inttibot cloud            # the sync state
    python -m inttibot cloud close      # upload the save (Home), wait for it, then force-stop INTTI

How the game syncs (v1.12.0, from the disassembly; see docs/cloudsave.md): the whole save
(UserData.data: guid, ints, longs, strings, floats; saved_at in longs, Unix ms) is uploaded when the
app loses focus (at most every 30 s) and after a download. A download happens at start and on
refocus after 5 min away; the cloud save replaces the local one entirely if its guid differs or
it's more than 60 s newer (saved_at), else the local one is uploaded over it. No merge: the last
writer wins, so a device that never loses focus (the bots' headless Waydroid) never uploads, and
a force-stop loses the upload. Close with `cloud close`.
"""
import argparse
import time

from . import device, mem


class Backend:
    def __init__(self, game=None):
        self.g = game or mem.Game()
        self.k = self.g.find_class("BackendManager")
        self.f = {n: v[0] for n, v in self.g.class_fields(self.k).items()}
        self.ud = mem.UserData(self.g)

    def _statics(self):
        return self.g.m.u64(self.k + 0xB8)

    def _inst(self):
        return self.g.static(self.k, "INSTANCE")

    def state(self):
        m, st, inst = self.g.m, self._statics(), self._inst()
        return {"synced": bool(m.read(st + self.f["dataSynced"], 1)[0]),
                "busy": bool(m.read(inst + self.f["accountProcessOn"], 1)[0]),
                "focus_lost_at": m.u64(inst + self.f["focusLostAt"]),
                "saved_at": self.ud.read("longs").get("saved_at", 0)}


def close(timeout=10.0, request_s=6.0):
    """Home (the game uploads on losing focus), give the request time, force-stop. The upload
    coroutine sets no flag to watch: its request times out after accountProcessTimeout (5 s)."""
    b = Backend()
    s0 = b.state()
    print(f"before: {s0}", flush=True)
    if not s0["synced"]:
        print("not synced with the cloud (not signed in, or the download didn't finish): "
              "nothing will upload", flush=True)
    device.adb("shell", "input", "keyevent", "KEYCODE_HOME", check=False, timeout=10)
    lost = device.wait_until(lambda: b.state()["focus_lost_at"] != s0["focus_lost_at"], timeout, 0.05)
    if lost:
        time.sleep(request_s)
    s = b.state()
    print(f"after: {s} ({'focus lost: uploading' if lost else 'focus not lost: no upload'})", flush=True)
    device.stop_app()
    print("INTTI closed", flush=True)
    return bool(lost)


def main():
    ap = argparse.ArgumentParser(prog="inttibot cloud", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", nargs="?", default="state", choices=["state", "close"])
    args = ap.parse_args()
    if args.what == "close":
        close()
    else:
        print(Backend().state())


if __name__ == "__main__":
    main()
