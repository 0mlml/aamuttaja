"""INTTI's daily tasks (Pelit -> Tehtävät): play the minigames that complete them.

    python -m inttibot tasks           # list the tasks
    python -m inttibot tasks run       # do every task the bots can

The tasks, where the app is and which minigame is open are all read from memory (inttibot.mem);
the minigames are played by the bots in inttibot.games. See docs/tasks.md.
"""
import argparse
import math
import time

from . import device, mem

# Pelit screen buttons (540x1200)
GAME_BUTTONS = {"shooter_game": (270, 385), "car_game": (270, 488), "quiz_game": (270, 578),
                "clicker_game": (270, 665)}
MENU, MENU_PELIT = (42, 262), (113, 344)     # home: the side menu, its Pelit entry
CLOSE = (503, 157)                           # a minigame's close X
PALAA = (270, 1140)                          # a screen's back button
TASK_CARD_Y0, TASK_CARD_PITCH = 797, 83      # Pelit's Tehtävät panel: the card of slot i

# Ampumarata challenges (1-based, as the menu numbers them) per task, and what a run counts at
# the least: quick ones with many hits for that weapon. Cases: the bot picks the challenge with the
# best case chance each run (Bot.pick); ~0.5 a run counted.
SHOOTER_PICK = {"shooter_game_hit_shootables_rk62": (16, 18),       # Melonintuhonta #3: 18 hits
                "shooter_game_hit_shootables_pistooli80": (17, 15), # Tölkinkaato #3: ~16 hits
                "shooter_game_hit_shootables_tkiv2000": (23, 10),   # Omenantuhonta #2: 10 hits
                "shooter_game_earn_skin_cases": (None, 0.5)}        # auto: by case chance


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class App:
    """Moving around INTTI by its state in memory."""

    def __init__(self, game):
        self.ui = mem.UI(game)
        self.t = device.make_touch()

    def tap(self, xy, wait=1.0):
        self.t.tap(xy[0] / device.REF_W, xy[1] / device.REF_H, 0.06)
        time.sleep(wait)

    def wait(self, pred, timeout=8.0):
        end = time.time() + timeout
        while time.time() < end:
            if pred():
                return True
            time.sleep(0.2)
        return False

    def close_minigame(self):
        for _ in range(4):
            if self.ui.minigame() is None:
                return True
            self.tap(CLOSE, 0.5)
            self.wait(lambda: self.ui.minigame() is None, 3.0)
        return self.ui.minigame() is None

    def to_pelit(self):
        for _ in range(5):
            if self.ui.minigame():
                self.close_minigame()
            screen = self.ui.screen()
            if screen == "games":
                return True
            if screen is None:                  # home
                if not self.ui.menu_open():
                    self.tap(MENU, 1.0)
                self.tap(MENU_PELIT, 0.5)
                self.wait(lambda: self.ui.screen() == "games", 3.0)
            else:
                self.tap(PALAA, 1.0)
        return self.ui.screen() == "games"

    def open_game(self, game_id):
        if self.ui.minigame() == game_id:
            return True
        for _ in range(3):                      # a tap during a screen's transition is lost
            if not self.to_pelit():
                raise RuntimeError("can't get to Pelit")
            self.tap(GAME_BUTTONS[game_id], 0.5)
            if self.wait(lambda: self.ui.minigame() == game_id, 8.0):
                return True
        raise RuntimeError(f"can't open {game_id}")


class Runner:
    def __init__(self):
        self.g = mem.Game()
        self.T = mem.Tasks(self.g)
        self.app = App(self.g)

    def task(self, slot):
        return next((t for t in self.T.read() if t.slot == slot), None)

    def until_done(self, slot, step, limit=60):
        for _ in range(limit):
            t = self.task(slot)
            if t is None or t.done:
                return True
            log(f"  {t}")
            step()
        return False

    def car(self, slot, t):
        from .games import pakuralli
        self.app.open_game("car_game")
        time.sleep(2.0)
        bot = pakuralli.Bot()
        try:
            return self.until_done(slot, lambda: bot.run(3))
        finally:
            bot.steer.set(0)

    def quiz(self, slot, t):
        from .games import sotilas
        self.app.open_game("quiz_game")
        time.sleep(2.0)
        bot = sotilas.Bot("koulutus")
        # The bot doesn't miss, so a round only ends when it stops answering (the timer then
        # ends it and the correct count is saved): stop at what the task still needs.
        left = lambda: max(1, self.task(slot).target - self.task(slot).progress + 2)
        return self.until_done(slot, lambda: bot.run(1, until=left()))

    def shooter(self, slot, t):
        """Ampumarata's task progress doesn't move while it's open (its quick view is set when it
        opens), so: play the runs the rest needs, then check in Pelit; again if short."""
        from .games import ampumarata
        number, per_run = SHOOTER_PICK[t.id]
        for _ in range(4):
            self.app.to_pelit()
            time.sleep(1.5)                     # the Tehtävät panel updates the progress
            t = self.task(slot)
            if t is None or t.done:
                return True
            runs = math.ceil((t.target - t.progress) / per_run)
            log(f"  {t}: {runs} runs")
            self.app.open_game("shooter_game")
            time.sleep(2.0)
            if number is not None:
                self.select_scenario(number)
            ampumarata.farm(runs, auto=number is None, number=number)
            self.app.close_minigame()
        return False

    def select_scenario(self, number):
        """Page the Ampumarata menu to challenge `number` (1-based), by its index in memory."""
        R = mem.Range(self.g)
        g = self.g
        lst = g.field(R.inst, "allScenarios")
        allsc = g.list_items(lst) or g.array_items(lst)
        n = len(allsc)
        for _ in range(3):
            cur = allsc.index(g.field(R.inst, "selectedScenario")) + 1
            d = (number - cur) % n
            if d == 0:
                return
            right = d <= n // 2
            for _ in range(d if right else n - d):
                self.app.tap((495, 504) if right else (45, 504), 0.6)
            time.sleep(0.8)

    def clicker(self, slot, t):
        from .games import denssi
        self.app.open_game("clicker_game")
        time.sleep(2.0)
        game = denssi.Game()
        return self.until_done(slot, lambda: game.click_tin(60))

    def run_task(self, t):
        fn = {"car_game": self.car, "quiz_game": self.quiz, "clicker_game": self.clicker}.get(t.game)
        if t.game == "shooter_game" and t.id in SHOOTER_PICK:
            fn = self.shooter
        if fn is None:
            log(f"  no runner for {t.id}")
            return False
        try:
            ok = fn(t.slot, t)
        except RuntimeError as e:
            log(f"  {t.id}: {e}")
            ok = False
        self.app.close_minigame()
        return ok

    def collect(self):
        """Tap each finished task's card: its coins and milestone point; the slot empties
        (in memory the instance goes)."""
        self.app.to_pelit()
        for t in self.T.read():
            if not t.done:
                continue
            for _ in range(3):                  # a tap during the panel's animation is lost
                self.app.tap((270, TASK_CARD_Y0 + TASK_CARD_PITCH * t.slot), 0.5)
                ok = self.app.wait(lambda: all(o.slot != t.slot for o in self.T.read()), 3.0)
                if ok:
                    break
            log(f"  collected {t.id}" if ok else f"  {t.id}: collecting didn't take")

    def run(self):
        for t in self.T.read():
            if t.done or t.turned_in:
                continue
            log(f"Task {t}")
            self.run_task(t)
        self.collect()
        for t in self.T.read():
            log(f"  left: {t}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="inttibot tasks", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", nargs="?", default="list", choices=["list", "run", "collect"])
    args = ap.parse_args(argv)
    if args.what == "list":
        T = mem.Tasks()
        for t in T.read():
            print(t, "| game", t.game)
        left = T.next_grant()
        print(f"new tasks in {int(left // 3600)} h {int(left % 3600 // 60)} min")
        ud = mem.UserData(T.g)
        nxt = ud.read("strings").get("gm_next_gift_date_time")
        print(f"coins {ud.int('coins')} (earned in all {ud.int('total_coins')}); next gift {nxt}")
    elif args.what == "collect":
        Runner().collect()
    else:
        Runner().run()


if __name__ == "__main__":
    main()
