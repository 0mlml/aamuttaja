"""Ampumarata's Arsenaali: open every weapon case, scrap duplicate skins into new cases.

Start with the Arsenaali open (Ampumarata menu -> the orange Arsenaali button), then:
    python -m inttibot arsenaali open     # open every case (all types, until none are left)
    python -m inttibot arsenaali scrap    # scrap duplicate skins into cases (slot 1's type)
    python -m inttibot arsenaali all      # scrap, open, repeat until neither does anything

State from memory: the cases left (WeaponSkinSelector.skinCaseButtons' "x26" counts), the case
choice being up (scrapMode), the case-opening screen (caseOpeningUI: a CanvasGroup, its alpha),
the shown weapon and skin (selectedWeaponId, selectedSkinPreview). Scrapping is planned from the
save (UserData): a skin can be scrapped when its copies
(shooter_game_skin_unlock_count_<weapon>_<skin>) less skinMinOwnCount (1) reach its rarity's
threshold (WeaponSkinSelector.GetWeaponSkinRarityScrapThreshold: common 5, rare 2, epic 1;
default skins never), as TryWeaponScrap checks; the skins and rarities are skinDict's. Only those
skins are visited, by the shorter way round the carousel.

Screen (540x1200):
- Weapon tabs at y 303: RK 62 (105), P 80 (270), TKIV 2000 (433). Skins are paged with the
  arrows at (65, 700) / (472, 700).
- The case strip at y 980: the first slot at x 117 (the strip shifts left when a type runs
  out, so slot 1 holds a case while any are left).
- A case opens on its own screen: three fast swipes left spin it open; ~5 s later it's back in
  the Arsenaali showing the skin won. Palaa (127, 1163) leaves it unopened.
- "Romuta ylimääräiset kappaleet" (scrap extra copies) at (443, 845); tapping it brings up the
  case choice, which stays up while more can be scrapped from that skin; a case type is chosen
  in the strip.
"""
import argparse
import struct
import time

from .. import device, mem

TABS = {"rk62": 105, "pistooli80": 270, "tkiv2000": 433}   # weapon tabs' x (at y 303)
NEXT_SKIN, PREV_SKIN = (472, 700), (65, 700)
SCRAP = (443, 845)
CASE_SLOT = (117, 980)
BACK = (127, 1163)
SCRAP_THRESHOLD = {1: 5, 2: 2, 3: 1}       # rarity (common, rare, epic) -> spare copies a case takes


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class Selector:
    """WeaponSkinSelector, read from memory."""

    def __init__(self, game=None):
        self.g = game or mem.Game()
        self.k = self.g.find_class("WeaponSkinSelector")

    @property
    def ws(self):
        return self.g.static(self.k, "INSTANCE")

    def string(self, p):
        if not p:
            return None
        n = self.g.m.i32(p + 0x10)
        return self.g.m.read(p + 0x14, 2 * n).decode("utf-16-le") if n is not None and 0 <= n < 500 else None

    def text(self, name, obj=None):
        t = self.g.field(obj or self.ws, name)
        return self.string(self.g.m.u64(t + self.g.all_fields(self.g.obj_class(t))["m_text"][0])) or ""

    def cases(self):
        """{case name: count} of unopened cases."""
        out = {}
        for b in self.g.items(self.g.field(self.ws, "skinCaseButtons")):
            if b:
                digits = "".join(ch for ch in self.text("countText", b) if ch.isdigit())
                out[self.text("nameText", b)] = int(digits) if digits else 0
        return out

    def skins(self):
        """{weapon id: [(skin id, rarity)]} in the carousel's order (skinDict)."""
        g, m = self.g, self.g.m
        dic = g.field(self.ws, "skinDict")
        entries, count = m.u64(dic + 0x18), m.i32(dic + 0x20)
        out = {}
        for i in range(count):
            _, nxt, kp, vp = struct.unpack("<iiQQ", m.read(entries + 0x20 + 24 * i, 24))
            if nxt >= -1 and kp:
                out[self.string(kp)] = [(self.string(g.field(sk, "id")), m.i32(sk + 0x58)) for sk in g.items(vp)]
        return out

    def min_own(self):
        return self.g.m.i32(self.ws + self.g.class_fields(self.k)["skinMinOwnCount"][0])

    def shown(self):
        """(weapon id, skin id) on screen."""
        sk = self.g.field(self.ws, "selectedSkinPreview")
        return (self.string(self.g.field(self.ws, "selectedWeaponId")),
                self.string(self.g.field(sk, "id")) if sk else None)

    def scrap_ready(self):
        """The shown skin has enough spare copies: its copies ("4 kpl - ...") less the one kept,
        against the scrap button's threshold ("3/5": 3 spares, 5 make a case). The button's
        text isn't updated for a skin with a single copy, so the spares come from the copies."""
        copies = self.text("skinUnlockedCopiesCountText").split(" ")[0]
        try:
            spares = int(copies) - 1
            need = int(self.text("scrapButtonCountText").split("/")[1])
        except (ValueError, IndexError):
            return False
        return spares >= need > 0

    def choosing(self):
        return bool(self.g.m.read(self.ws + self.g.class_fields(self.k)["scrapMode"][0], 1)[0])

    def on_case(self):
        """The case-opening screen is up (caseOpeningUI's CanvasGroup alpha, native +0x2c)."""
        nat = self.g.native(self.g.field(self.ws, "caseOpeningUI"))
        return struct.unpack("<f", self.g.m.read(nat + 0x2C, 4))[0] > 0.5


class Arsenal:
    def __init__(self):
        self.t = device.make_touch()
        self.s = Selector()
        self.ud = mem.UserData(self.s.g)

    def wait(self, pred, timeout):
        end = time.time() + timeout
        while time.time() < end:
            if pred():
                return True
            time.sleep(0.1)
        return pred()

    def tap(self, xy, wait):
        self.t.tap(xy[0] / device.REF_W, xy[1] / device.REF_H, 0.06)
        time.sleep(wait)

    def spin_open(self):
        for _ in range(3):
            self.t.down(480 / device.REF_W, 600 / device.REF_H)
            for x in range(480, 60, -60):
                self.t.move(x / device.REF_W, 600 / device.REF_H)
                time.sleep(0.008)
            self.t.up()
            self.t.sync()
            time.sleep(0.15)

    def open_all(self):
        opened = 0
        while sum(self.s.cases().values()) > 0:
            # after scrapping the case screen takes longer to come up; it may already be up
            for _ in range(2):
                if self.s.on_case():
                    break
                self.tap(CASE_SLOT, 0.3)
                self.wait(self.s.on_case, 3.0)
            if not self.s.on_case():
                log("  the case screen didn't open")
                break
            self.spin_open()
            end = time.time() + 12
            while time.time() < end and self.s.on_case():
                time.sleep(0.4)
                if time.time() > end - 8 and self.s.on_case():
                    self.spin_open()      # didn't take: spin again
            time.sleep(0.8)
            opened += 1
            if opened % 10 == 0:
                log(f"opened {opened}")
        log(f"opened {opened} cases")
        return opened

    def spares(self, weapon, skin, rarity, ints=None):
        """Cases this skin can be scrapped into now (0 if none)."""
        need = SCRAP_THRESHOLD.get(rarity)
        if not need:
            return 0
        ints = ints if ints is not None else self.ud.read("ints")
        copies = ints.get(f"shooter_game_skin_unlock_count_{weapon}_{skin}", 0)
        return max(0, copies - self.s.min_own()) // need

    def plan(self):
        """[(weapon, index, skin id, rarity, cases)] that can be scrapped, from the save."""
        ints = self.ud.read("ints")
        return [(w, i, sk, r, n) for w, skins in self.s.skins().items()
                for i, (sk, r) in enumerate(skins) if (n := self.spares(w, sk, r, ints))]

    def go_to(self, weapon, skin):
        """Bring the skin on screen: its weapon's tab, then the arrows the shorter way round."""
        skins = [sk for sk, _ in self.s.skins()[weapon]]
        tab = TABS[weapon]
        for _ in range(3):
            if self.s.shown()[0] == weapon:
                break
            self.tap((tab, 303), 0.3)
            self.wait(lambda: self.s.shown()[0] == weapon, 1.5)
        for _ in range(2 * len(skins)):
            w, cur = self.s.shown()
            if w != weapon:
                return False
            if cur == skin:
                return True
            d = (skins.index(skin) - skins.index(cur)) % len(skins) if cur in skins else 1
            self.tap(NEXT_SKIN if d <= len(skins) - d else PREV_SKIN, 0.15)
            self.wait(lambda: self.s.shown()[1] != cur, 1.0)
        return self.s.shown() == (weapon, skin)

    def scrap_all(self):
        total = 0
        todo = self.plan()
        if not todo:
            log("nothing to scrap")
            return 0
        log("to scrap: " + ", ".join(f"{sk} x{n}" for _, _, sk, _, n in todo))
        for weapon, _, skin, rarity, _ in todo:
            if not self.go_to(weapon, skin):
                log(f"  couldn't bring {skin} on screen")
                continue
            for _ in range(10):
                key = f"shooter_game_skin_unlock_count_{weapon}_{skin}"
                copies = self.ud.int(key)
                if not self.spares(weapon, skin, rarity):
                    break
                if not self.s.choosing():
                    self.tap(SCRAP, 0.2)
                    if not self.wait(self.s.choosing, 2.0):
                        log(f"  {skin}: the case choice didn't come up")
                        break
                self.tap(CASE_SLOT, 0.2)
                if not self.wait(lambda: self.ud.int(key) < copies, 3.0):
                    log(f"  {skin}: scrapping didn't take")
                    break
                total += 1
            if self.s.on_case():          # a stray tap opened a case screen: leave it
                self.tap(BACK, 1.5)
        log(f"scrapped into {total} cases")
        return total

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["open", "scrap", "all"])
    args = ap.parse_args()
    a = Arsenal()
    log("cases:", a.s.cases())
    if args.what == "open":
        a.open_all()
    elif args.what == "scrap":
        a.scrap_all()
    else:
        while a.scrap_all() + a.open_all():
            pass


if __name__ == "__main__":
    main()
