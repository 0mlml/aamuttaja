"""Read INTTI's memory (read-only) through /usr/local/bin/inttimem (native/memreader/inttimem.c:
a tiny root-owned helper with only CAP_SYS_PTRACE). See docs/memreader.md."""
import struct
import subprocess

import numpy as np

HELPER = "/usr/local/bin/inttimem"


class Mem:
    def __init__(self):
        import threading
        self.p = subprocess.Popen([HELPER], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.lock = threading.Lock()     # one request/reply at a time on the helper's pipe
        self.maps = self._maps()

    def _maps(self):
        with self.lock:
            return self._maps_locked()

    def _maps_locked(self):
        self.p.stdin.write(b"M\n")
        self.p.stdin.flush()
        out = []
        for line in iter(self.p.stdout.readline, b""):
            line = line.decode(errors="replace").rstrip("\n")
            if line == "END":
                break
            parts = line.split(None, 5)
            lo, hi = (int(x, 16) for x in parts[0].split("-"))
            out.append((lo, hi, parts[1], parts[5] if len(parts) > 5 else ""))
        return out

    def read(self, addr, n):
        with self.lock:
            self.p.stdin.write(f"R {addr:x} {n}\n".encode())
            self.p.stdin.flush()
            got = struct.unpack("<I", self.p.stdout.read(4))[0]
            return self.p.stdout.read(got) if got else b""

    def u64(self, addr):
        b = self.read(addr, 8)
        return struct.unpack("<Q", b)[0] if len(b) == 8 else None

    def i32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack("<i", b)[0] if len(b) == 4 else None

    def f32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack("<f", b)[0] if len(b) == 4 else None

    def cstr(self, addr, n=128):
        b = self.read(addr, n)
        return b.split(b"\0")[0].decode(errors="replace") if b else None

    def regions(self, writable=True, anon_only=False):
        for lo, hi, perm, path in self.maps:
            if writable and perm[1] != "w":
                continue
            if perm[0] != "r":
                continue
            if anon_only and path and not path.startswith("["):
                continue
            yield lo, hi, path

    def find_u64(self, value, writable=True, limit=1000, chunk=32 << 20):
        """Addresses (8-aligned) holding the 64-bit value."""
        hits = []
        for lo, hi, path in self.regions(writable):
            a = lo
            while a < hi:
                n = min(chunk, hi - a)
                b = self.read(a, n)
                if len(b) >= 8:
                    arr = np.frombuffer(b[: len(b) // 8 * 8], np.uint64)
                    for k in np.nonzero(arr == np.uint64(value))[0]:
                        hits.append(a + int(k) * 8)
                        if len(hits) >= limit:
                            return hits
                a += n
        return hits

    def metadata_base(self):
        for lo, hi, perm, path in self.maps:
            if path.endswith("global-metadata.dat"):
                return lo
        return None
