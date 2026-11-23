"""IL2CPP objects by name (classes, fields, statics, lists) and Unity native transforms.

INTTI is Unity IL2CPP. Classes are found at runtime by name: an Il2CppClass points its `name`
into the mapped global-metadata.dat, so the class is wherever a pointer to that string sits
(at the struct's name offset); its fields (FieldInfo: name, type, parent, offset) come from
the class's field array; instances start with a pointer to their class. See docs/memreader.md.
"""
import struct

import numpy as np

from .reader import Mem


FIELDS_OFF = 0x80        # Il2CppClass.fields (FieldInfo*), Unity 6000.4 / metadata v39
STATIC_OFF = 0xB8        # Il2CppClass.static_fields
PARENT_OFF = 0x58        # Il2CppClass.parent (checked at runtime in class_fields)


class Game:
    """Named access to IL2CPP objects."""

    def __init__(self, mem=None):
        self.m = mem or Mem()
        self._fields = {}

    def find_class(self, name, assembly="Assembly-CSharp.dll"):
        """An Il2CppClass by name: the struct whose name pointer (+0x10) points at that name in
        the mapped metadata and whose image names `assembly` (~2 s: scans writable memory)."""
        if name in getattr(self, "_classes", {}):
            return self._classes[name]
        m = self.m
        md = m.metadata_base()
        if getattr(self, "_mdblob", None) is None:
            self._mdblob = m.read(md, 16 << 20)
        off = self._mdblob.find(b"\0" + name.encode() + b"\0")
        while off >= 0:
            for h in m.find_u64(md + off + 1, limit=50):
                k = h - 0x10
                img = m.u64(k)
                if img and m.cstr(m.u64(img) or 0, 60) == assembly:
                    self._classes = getattr(self, "_classes", {})
                    self._classes[name] = k
                    return k
            off = self._mdblob.find(b"\0" + name.encode() + b"\0", off + 1)
        raise RuntimeError(f"class {name} not found")

    def static(self, klass, name):
        """A static field's value (u64)."""
        off = self.class_fields(klass)[name][0]
        return self.m.u64(self.m.u64(klass + STATIC_OFF) + off)

    def class_name(self, klass):
        return self.m.cstr(self.m.u64(klass + 0x10), 80)

    def obj_class(self, obj):
        return self.m.u64(obj) if obj else None

    def class_fields(self, klass):
        """{name: offset} of a class's own fields (FieldInfo: name, type, parent, offset)."""
        if klass in self._fields:
            return self._fields[klass]
        out = {}
        p = self.m.u64(klass + FIELDS_OFF)
        i = 0
        while p and i < 2000:
            fi = self.m.read(p + i * 0x20, 0x20)
            if len(fi) < 0x20:
                break
            name, typ, parent, off = struct.unpack("<QQQi", fi[:0x1C])
            if parent != klass:
                break
            out[self.m.cstr(name, 80)] = (off, typ)
            i += 1
        if out:       # a class not used yet has no field array: don't cache that
            self._fields[klass] = out
        return out

    def all_fields(self, klass):
        """Fields of the class and its parents (parents found as a pointer to a class whose
        fields' parent is itself)."""
        out = {}
        k, depth = klass, 0
        while k and depth < 8:
            for n, v in self.class_fields(k).items():
                out.setdefault(n, v)
            k = self.parent(k)
            depth += 1
        return out

    def parent(self, klass):
        p = self.m.u64(klass + PARENT_OFF)
        return p if p and p > 0x10000 and self.m.u64(p + 0x10) else None

    def field(self, obj, name, kind="u64"):
        k = self.obj_class(obj)
        off = self.all_fields(k)[name][0]
        return {"u64": self.m.u64, "i32": self.m.i32, "f32": self.m.f32}[kind](obj + off)

    def list_items(self, lst):
        """Items of a System.Collections.Generic.List<T> of references."""
        if not lst:
            return []
        items, size = self.m.u64(lst + 0x10), self.m.i32(lst + 0x18)
        if not items or not size or size < 0 or size > 100000:
            return []
        b = self.m.read(items + 0x20, 8 * size)
        return list(struct.unpack(f"<{size}Q", b))

    def items(self, obj):
        """Items of a List<T> or a T[] of references."""
        if not obj:
            return []
        name = self.class_name(self.obj_class(obj)) or ""
        return self.list_items(obj) if name.startswith("List") else self.array_items(obj)

    def array_items(self, arr):
        """Items of a managed array of references (T[])."""
        if not arr:
            return []
        n = self.m.u64(arr + 0x18)
        if not n or n > 100000:
            return []
        b = self.m.read(arr + 0x20, 8 * n)
        return list(struct.unpack(f"<{n}Q", b))

    # --- native Unity objects (Unity 6000.4, found by inspection) -----------------------------
    # managed object +0x10 -> native object (m_CachedPtr). Native component +0x20 -> GameObject.
    # Native GameObject +0x20 -> components (16 bytes each: type, component), +0x30 count; the
    # first is the Transform. Native Transform +0x20 -> GameObject, +0x28 -> TransformHierarchy,
    # +0x30 index. TransformHierarchy +0x18 -> local TRS (48 bytes each: position xyz _,
    # rotation xyzw, scale xyz _), +0x20 -> parent indices (int32, -1 at the root).

    def native(self, obj):
        return self.m.u64(obj + 0x10) if obj else None

    def go_transform(self, native_go):
        """Native Transform of a native GameObject (its first component)."""
        data = self.m.u64(native_go + 0x20)
        return self.m.u64(data + 8) if data else None

    def transform(self, obj):
        """Native Transform of a managed Component or GameObject."""
        nat = self.native(obj)
        if not nat:
            return None
        if self.class_name(self.obj_class(obj)) == "GameObject":
            return self.go_transform(nat)
        return self.transform_of(nat)

    def transform_of(self, native_component):
        """Native Transform of a native component (or itself if it is one: its +0x20 is a
        GameObject whose first component is itself)."""
        go = self.m.u64(native_component + 0x20)
        if go:
            data = self.m.u64(go + 0x20)
            if data:
                tr = self.m.u64(data + 8)
                if tr:
                    return tr
        return native_component

    def world_pos(self, transform):
        """World position of a native Transform."""
        if not transform:
            return None
        H, idx = self.m.u64(transform + 0x28), self.m.i32(transform + 0x30)
        if not H or idx is None or idx < 0:
            return None
        trs, parents = self.m.u64(H + 0x18), self.m.u64(H + 0x20)
        if not trs or not parents:
            return None
        p = None
        i, depth = idx, 0
        while i >= 0 and depth < 64:
            t = struct.unpack("<12f", self.m.read(trs + i * 48, 48))
            pos, q, s = np.array(t[0:3]), np.array(t[4:8]), np.array(t[8:11])
            p = pos if p is None else pos + quat_rotate(q, s * p)
            i = self.m.i32(parents + i * 4)
            depth += 1
        return p

    def world_rot(self, transform):
        """World rotation (quaternion xyzw) of a native Transform."""
        H, idx = self.m.u64(transform + 0x28), self.m.i32(transform + 0x30)
        trs, parents = self.m.u64(H + 0x18), self.m.u64(H + 0x20)
        qs, i, depth = [], idx, 0
        while i >= 0 and depth < 64:
            t = struct.unpack("<12f", self.m.read(trs + i * 48, 48))
            qs.append(np.array(t[4:8]))
            i = self.m.i32(parents + i * 4)
            depth += 1
        q = np.array([0.0, 0.0, 0.0, 1.0])
        for qq in reversed(qs):
            q = quat_mul(q, qq)
        return q

    def forward(self, transform):
        return quat_rotate(self.world_rot(transform), np.array([0.0, 0.0, 1.0]))


def quat_mul(a, b):
    x1, y1, z1, w1 = a
    x2, y2, z2, w2 = b
    return np.array([w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2, w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                     w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2, w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2])


def quat_rotate(q, v):
    x, y, z, w = q
    u = np.array([x, y, z])
    return 2 * np.dot(u, v) * u + (w * w - np.dot(u, u)) * v + 2 * w * np.cross(u, v)
