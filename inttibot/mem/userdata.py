"""INTTI's save (UserData.data, a UserDataObject): every PlayerPrefs-style value the app keeps.

UserData.data has four SerializedDictionary<string, T> (a Dictionary underneath): ints, longs,
floats, strings. Keys are the games' counters and flags: coins and total_coins, each task's
counter (car_game_scoretotal, quiz_game_correctcount, ...), Ampumarata's skin copies
(shooter_game_skin_unlock_count_<weapon>_<skin>) and cases, the gift timers, records. The
dictionaries are read fresh on every call (the game rewrites them). See docs/memreader.md.
"""
import struct

from .il2cpp import Game

# Dictionary<TKey, TValue>: _entries (Entry[]: int hashCode, int next, TKey key, TValue value),
# _count; an entry with next < -1 is free.
ENTRIES_OFF, COUNT_OFF = 0x18, 0x20
KINDS = {"ints": "<i", "longs": "<q", "floats": "<f", "strings": "<Q"}


class UserData:
    def __init__(self, game=None):
        self.g = game or Game()
        self.klass = self.g.find_class("UserData")
        self._strings = {}

    def string(self, p):
        if not p:
            return None
        m = self.g.m
        n = m.i32(p + 0x10)
        return m.read(p + 0x14, 2 * n).decode("utf-16-le") if n is not None and 0 <= n < 4000 else None

    def _key(self, p):
        k = self._strings.get(p)        # keys are interned strings: cache by address
        if k is None:
            k = self._strings[p] = self.string(p)
        return k

    def read(self, kind="ints"):
        """{key: value} of one dictionary (ints, longs, floats or strings)."""
        g, m = self.g, self.g.m
        data = g.static(self.klass, "data")
        dic = g.field(data, kind)
        if not dic:
            return {}
        entries, count = m.u64(dic + ENTRIES_OFF), m.i32(dic + COUNT_OFF)
        n = m.u64(entries + 0x18) if entries else 0
        if not n or not 0 < count <= n <= 100000:
            return {}
        raw = m.read(entries + 0x20, 24 * count)
        out = {}
        for i in range(count):
            _, nxt, kp = struct.unpack_from("<iiQ", raw, 24 * i)
            if nxt < -1 or not kp:
                continue
            v = struct.unpack_from(KINDS[kind], raw, 24 * i + 16)[0]
            out[self._key(kp)] = self.string(v) if kind == "strings" else v
        return out

    def all(self):
        return {k: self.read(k) for k in KINDS}

    def int(self, key, default=0):
        return self.read("ints").get(key, default)

    def ints(self, *keys):
        d = self.read("ints")
        return {k: d.get(k, 0) for k in keys}

    def skin_copies(self, weapon, skin_id):
        return self.int(f"shooter_game_skin_unlock_count_{weapon}_{skin_id}")


# What the bots log at their start and end (the change is what a run earned).
COINS = ("coins", "total_coins")


def summary(before, after, keys):
    """'key a -> b (+d)' for the keys that changed."""
    parts = []
    for k in keys:
        a, b = before.get(k, 0), after.get(k, 0)
        if a != b:
            parts.append(f"{k} {a} -> {b} ({b - a:+d})")
    return ", ".join(parts) or "no change"


def main():
    import argparse
    ap = argparse.ArgumentParser(prog="inttibot userdata", description="Print INTTI's save (UserData) from memory.")
    ap.add_argument("grep", nargs="?", default="", help="only keys containing this")
    args = ap.parse_args()
    for kind, d in UserData().all().items():
        for k in sorted(d, key=str):
            if args.grep in (k or ""):
                print(f"{kind[:-1]:6s} {k} = {d[k]}")


if __name__ == "__main__":
    main()
