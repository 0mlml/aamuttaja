"""Denssiklikkeri: tap the tin, collect gold, buy upgrades in the best order, up to Nollaus.
Played from the game's memory.

Start it with INTTI open (it opens Denssiklikkeri itself):
    python -m inttibot denssi                 # play to one Nollaus
    python -m inttibot denssi --resets 4      # four Nollaus purchases, starting over after each
    python -m inttibot denssi --no-nollaus    # stop when Nollaus becomes affordable
    python -m inttibot denssi --dry-run       # tap, log what it would buy

From ClickerGame (inttibot.mem): the bank (densCount, a C# decimal), every card's owned count
and price (its own text fields: "X12", "1 325"), the cards' and the gold objects' positions
(UI canvas: screen x = 269.4 + 133.1 * world x, y = 734.5 - 133.1 * world y). The buying
order is denssi_data's (best gain per price, Nollaus when that's sooner). No screenshots, no
saved state: the game is the state. See docs/denssiklikkeri.md.
"""
import argparse
import struct
import threading
import time

from .. import device, mem
from .denssi_data import NOLLAUS_PRICE, UPGRADES, best_buy, gain, income

REF_W, REF_H = 540, 1200
TIN = (270, 570)
CARD_TAP_Y = 1050
ROW_Y = 1050
DRAG_SLOP = 22          # px of a drag that Unity swallows before scrolling
UI_X0, UI_Y0, UI_SCALE = 269.4, 734.5, 133.1   # main canvas: world -> screen px
NOLLAUS = len(UPGRADES)  # card index of Nollaus (after the 31 upgrades)
TAP_HOLD = 0.035
TAP_GAP = 0.035
GOLD_HOLD, GOLD_QUIET, GOLD_TRIES = 0.08, 0.15, 3   # a gold tap: held longer, quiet around it
TAPS_PER_S = 12.0       # taps the game counts at the pacing above (it runs at ~7-21 fps here)
FREEZE_AFTER = 20.0     # s of an unchanged bank (while tapping) before the game counts as frozen


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def fmt(n):
    for div, s in ((1e15, "Q"), (1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k")):
        if n >= div:
            return f"{n / div:.2f}{s}"
    return f"{n:.0f}"


def decimal(b):
    """A C# System.Decimal (16 bytes: flags, hi, lo) as a float."""
    flags, hi, lo = struct.unpack("<IIQ", b)
    v = ((hi << 64) | lo) / 10 ** ((flags >> 16) & 0xFF)
    return -v if flags >> 31 else v


def number(text):
    """A card's number: '1 325' (spaces, also no-break ones) or 'X12'."""
    digits = "".join(ch for ch in (text or "") if ch.isdigit())
    return int(digits) if digits else None


class Clicker:
    """ClickerGame's state, read from memory."""

    def __init__(self, game=None):
        self.g = game or mem.Game()
        g = self.g
        self.c = g.field(g.static(g.find_class("MiniGameManager"), "INSTANCE"), "clickerGame")
        self.f = g.all_fields(g.obj_class(self.c))
        self.names = [u[0] for u in UPGRADES] + ["Nollaus"]

    def string(self, p):
        if not p:
            return None
        n = self.g.m.i32(p + 0x10)
        return self.g.m.read(p + 0x14, 2 * n).decode("utf-16-le") if n is not None and 0 <= n < 500 else None

    def text(self, tmp):
        return self.string(self.g.m.u64(tmp + self.g.all_fields(self.g.obj_class(tmp))["m_text"][0]))

    def bank(self):
        return decimal(self.g.m.read(self.c + self.f["densCount"][0], 16))

    def cards(self):
        """{card index: (owned, price, screen x)} by the upgrades' names (Nollaus last)."""
        g, m = self.g, self.g.m
        d = g.field(self.c, "itemUIBoxes")
        ent, cnt = m.u64(d + 0x18), m.i32(d + 0x20)
        out = {}
        for i in range(cnt):
            e = ent + 0x20 + i * 24
            item, box = m.u64(e + 8), m.u64(e + 16)
            if not item or not box:
                continue
            name = self.string(g.field(item, "itemName"))
            if name not in self.names:
                continue
            x = UI_X0 + UI_SCALE * g.world_pos(g.transform(box))[0]
            out[self.names.index(name)] = (number(self.text(g.field(box, "ownedCountText"))) or 0,
                                           number(self.text(g.field(box, "priceText"))), x)
        return out

    def gold(self):
        """Gold to tap (activeClickables: golden tins and coins): [(object, screen x, y)].
        They're drawn on the main canvas layer (same mapping as the cards; checked against
        screenshots). A collected one stays listed until its lifetime runs out (pooled)."""
        g = self.g
        out = []
        for o in g.items(g.field(self.c, "activeClickables")):
            if not o:
                continue
            p = g.world_pos(g.transform(o))
            x, y = UI_X0 + UI_SCALE * p[0], UI_Y0 - UI_SCALE * p[1]
            if 20 < x < REF_W - 20 and 300 < y < 920:     # the play area (not the counters, cards)
                out.append((o, x, y))
        return out

    def clickable(self, obj):
        """The ClickerGameClickable on a gold GameObject: (type, clicked, clickable), type 0 a
        coin and 1 a golden tin (a booster: what the golden_disks task counts). None if not found.
        The components are found by a scan for the class (~2 s); they're pooled, so the scan is
        cached and redone only when a new object turns up."""
        g, m = self.g, self.g.m
        if not hasattr(self, "_ck"):
            self._ck = g.find_class("ClickerGameClickable")
            f = g.class_fields(self._ck)
            self._ck_off = (f["type"][0], f["clicked"][0], f["clickable"][0])
            self._comps = {}
        go = g.native(obj)
        if go not in self._comps:
            for h in m.find_u64(self._ck, limit=1000):
                nat = m.u64(h + 0x10)
                if nat:
                    self._comps[m.u64(nat + 0x20)] = h
        h = self._comps.get(go)
        if not h:
            return None
        t, c, k = self._ck_off
        b = m.read(h + c, 2)
        return m.i32(h + t), bool(b[0]), bool(m.read(h + k, 1)[0])


class Game:
    def __init__(self):
        self.t = device.make_touch()
        self.app = None
        self.clk = Clicker()
        self.gold_taps = 0
        self.boosters = 0      # golden tins collected
        self.tapped = {}       # gold objects tapped (pooled: the same object comes back later)

    def tap(self, x, y):
        self.t.tap(x / REF_W, y / REF_H, TAP_HOLD)

    def click_tin(self, seconds):
        """Tap the tin for `seconds`; gold (golden tins first, then coins) is tapped when it shows."""
        end = time.time() + seconds
        n = 0
        while time.time() < end:
            if n % 3 == 0 and self.tap_gold():
                n += 1
                continue
            self.tap(*TIN)
            time.sleep(TAP_GAP)
            n += 1
        return n

    def tap_gold(self):
        """Tap one uncollected gold object, if any, until the game marks it clicked.

        A gold tap squeezed between tin taps (35 ms apart) is lost: at the game's 7-21 fps the
        touches land in one frame. So the gold tap gets a quiet gap on each side, and its
        `clicked` flag (ClickerGameClickable) tells whether it took."""
        best = None
        for o, x, y in self.clk.gold():
            st = self.clk.clickable(o)
            if st is not None and (st[1] or not st[2]):
                continue
            if st is None and time.time() - self.tapped.get(o, 0) < 10:   # unknown: tap once
                continue
            kind = st[0] if st else 0
            if best is None or kind > best[0]:
                best = (kind, o, x, y)
        if best is None:
            return False
        kind, o, x, y = best
        for _ in range(GOLD_TRIES):
            time.sleep(GOLD_QUIET)
            self.t.tap(x / REF_W, y / REF_H, GOLD_HOLD)
            t0 = time.time()
            while time.time() - t0 < GOLD_QUIET * 3:
                st = self.clk.clickable(o)
                if st is None or st[1]:
                    break
                time.sleep(0.03)
            st = self.clk.clickable(o)
            if st is None or st[1]:
                break
        if st is None:
            self.tapped[o] = time.time()
        self.gold_taps += 1
        if st is not None and st[1]:
            if kind == 1:
                self.boosters += 1
                log(f"golden tin collected ({self.boosters})")
        elif st is not None:
            log(f"{'golden tin' if kind == 1 else 'coin'} at ({x:.0f}, {y:.0f}) didn't take")
        return True

    def show_card(self, i, tries=10):
        """Scroll the card row until card i is well on screen; returns its screen x."""
        for _ in range(tries):
            x = self.clk.cards()[i][2]
            if 110 <= x <= 430:
                return x
            dx = x - 270                   # > 0: the content must move left
            length = min(abs(dx) + DRAG_SLOP, 440)
            x0 = 490 if dx > 0 else 50
            x1 = x0 - length if dx > 0 else x0 + length
            self.t.drag(x0 / REF_W, ROW_Y / REF_H, x1 / REF_W, ROW_Y / REF_H)
            end = time.time() + 2          # let it come to rest
            prev = None
            while time.time() < end:
                cur = round(self.clk.cards()[i][2])
                if cur == prev:
                    break
                prev = cur
                time.sleep(0.15)
        return None

    def ensure_open(self):
        """Back in Denssiklikkeri (from wherever INTTI is), by the app's state in memory."""
        from ..tasks import App
        if self.app is None:
            self.app = App(self.clk.g)
        if self.app.ui.minigame() == "clicker_game":
            return True
        return self.app.open_game("clicker_game")


def state(clk):
    cards = clk.cards()
    owned = [cards[i][0] for i in range(NOLLAUS)]
    prices = [cards[i][1] for i in range(NOLLAUS)]
    return owned, prices, cards[NOLLAUS][0]


def choose(owned, prices, bank):
    """Next thing to buy: an upgrade index, NOLLAUS, or None (just save up)."""
    rate, _, _ = income(owned, TAPS_PER_S)
    t_nollaus = max(0.0, (NOLLAUS_PRICE - bank) / rate)
    i = best_buy(owned, bank, TAPS_PER_S, prices)
    p = prices[i]
    wait = max(0.0, (p - bank) / rate)
    t_after = wait + max(0.0, (NOLLAUS_PRICE - (bank + rate * wait - p)) / (rate + gain(i, TAPS_PER_S)))
    if t_after < t_nollaus:
        return i
    return NOLLAUS if bank >= NOLLAUS_PRICE else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="tap and log decisions, but never buy")
    ap.add_argument("--no-nollaus", action="store_true", help="stop instead of buying Nollaus")
    ap.add_argument("--resets", type=int, default=1, help="Nollaus purchases to make before stopping (default 1)")
    args = ap.parse_args()

    g = Game()
    clk = g.clk
    ud = mem.UserData(clk.g)
    coins0, t0 = ud.int("total_coins"), time.time()
    if not g.ensure_open():
        raise SystemExit("can't open Denssiklikkeri")
    resets = 0
    last_report = 0
    stuck_bank, stuck_since = None, time.time()
    while True:
        if device_lost(g):
            continue
        bank = clk.bank()
        owned, prices, nollaus_count = state(clk)
        if bank != stuck_bank:
            stuck_bank, stuck_since = bank, time.time()
        elif time.time() - stuck_since > FREEZE_AFTER:
            log(f"bank stuck at {fmt(bank)} for {time.time() - stuck_since:.0f} s: the game looks frozen; reopening")
            device.stop_app()
            device.launch_app(wait=20)
            g.ensure_open()
            stuck_bank = None
            continue

        target = choose(owned, prices, bank)
        rate, dps, dpk = income(owned, TAPS_PER_S)
        if time.time() - last_report > 60:
            log(f"bank {fmt(bank)}  DPS {fmt(dps)}  DPK {fmt(dpk)}  ~{fmt(rate)}/s  gold taps {g.gold_taps}"
                f"  next: {'Nollaus' if target == NOLLAUS else (UPGRADES[target][0] if target is not None else 'save')}"
                f"  coins {coins_report(ud, coins0, t0)}")
            last_report = time.time()

        if target is None:
            g.click_tin(min(30.0, max(2.0, (NOLLAUS_PRICE - bank) / rate)))
            continue
        p = NOLLAUS_PRICE if target == NOLLAUS else prices[target]
        if bank < p:
            g.click_tin(min(20.0, max(1.0, (p - bank) / rate)))
            continue
        name = "Nollaus" if target == NOLLAUS else UPGRADES[target][0]
        if args.dry_run:
            log(f"[dry-run] would buy {name} for {fmt(p)}")
            g.click_tin(5.0)
            continue
        if target == NOLLAUS and args.no_nollaus:
            log("Nollaus is affordable: stopping (--no-nollaus)")
            return

        x = g.show_card(target)
        if x is None:
            log(f"couldn't bring {name} on screen; retrying")
            continue
        before = clk.cards()[target][0]
        g.tap(x, CARD_TAP_Y)
        end = time.time() + 2
        while time.time() < end and clk.cards()[target][0] == before:
            time.sleep(0.1)
        after = clk.cards()[target][0]
        if after == before:
            log(f"buying {name} didn't register (x{before}); will retry")
            continue
        if target == NOLLAUS:
            resets += 1
            log(f"BOUGHT NOLLAUS (#{after}, +80 kolikkoa): reset {resets}/{args.resets}")
            if resets >= args.resets:
                return
            time.sleep(3)
            continue
        log(f"bought {name} #{after} for ~{fmt(p)}, next {fmt(clk.cards()[target][1] or 0)}")


def coins_report(ud, coins0, t0):
    """'+n (r/min)': coins earned since the start (total_coins in the save)."""
    try:
        n = ud.int("total_coins") - coins0
    except Exception:
        return "?"
    minutes = max((time.time() - t0) / 60, 1e-9)
    return f"+{n} ({n / minutes:.2f}/min)"


def device_lost(g):
    """Not in Denssiklikkeri any more (a popup closed it, INTTI restarted): go back."""
    try:
        if g.clk.g.m.read(g.clk.c, 8):
            from ..mem import UI
            if UI(g.clk.g).minigame() == "clicker_game":
                return False
    except Exception:
        pass
    log("not in Denssiklikkeri: going back")
    if not g.ensure_open():
        time.sleep(5)
    return True


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("stopped")
