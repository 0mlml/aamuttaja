"""Sotilasarvopeli, the quiz: every answer read from the game's memory.

Start it with the quiz's own menu open (Pelaa / Opettele / Poistu):
    python -m inttibot sotilas koulutus          # rounds until stopped (maa, meri, koulutus, aakkoset)
    python -m inttibot sotilas maa -n 1          # one round
    python -m inttibot sotilas meri --until 80   # stop answering at 80 (the timer ends the round)

A round runs in QuizGame's coroutine (<GameCoroutine>d__105, or <GameCoroutineABC>d__106 for
Aakkoset), whose locals hold the question: the choices and the index of the correct one, or
the NATO word to type. The bot finds that coroutine object in memory at the start of a round,
taps the correct button (or types the word and checks the input field's value), and waits for
QuizGame.score to count it. See docs/sotilasarvopeli.md.
"""
import argparse
import time

from .. import device, mem

CATEGORIES = {"maa": 84, "meri": 208, "koulutus": 332, "aakkoset": 456}   # x of the mode tile
MODE_INDEX = {"maa": 0, "meri": 1, "koulutus": 2, "aakkoset": 3}           # QuizGame.selectedGameMode
TILE_Y = 437
PELAA = (270, 698)
# The answer buttons (QuizChoiceButton: its index into the choices, its world position): screen
# y = BUTTON_Y0 - BUTTON_SCALE * world y (two buttons at world -0.8 / -1.4 sit at y 841 / 922)
BUTTON_Y0, BUTTON_SCALE = 733.5, 135.0
ANSWER_BOX = (270, 566)              # Aakkoset: the text field
KEYBOARD_OK = (483, 700)             # the OK beside the keyboard's input bar (closes it)
KEYCODE_ENTER = 66
KEYCODE_DEL = 67


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class Quiz:
    """QuizGame and its running round, read from memory."""

    def __init__(self, game=None):
        self.g = game or mem.Game()
        g = self.g
        self.q = g.field(g.static(g.find_class("MiniGameManager"), "INSTANCE"), "quizGame")
        self.f = g.all_fields(g.obj_class(self.q))
        self.k_round = g.find_class("<GameCoroutine>d__105")
        self.k_abc = g.find_class("<GameCoroutineABC>d__106")
        self.co, self.co_kind = None, None
        self._near = None

    def string(self, p):
        if not p:
            return None
        n = self.g.m.i32(p + 0x10)
        return self.g.m.read(p + 0x14, 2 * n).decode("utf-16-le") if n is not None and 0 <= n < 500 else None

    def i32(self, name):
        return self.g.m.i32(self.q + self.f[name][0])

    def flag(self, name):
        return bool(self.g.m.read(self.q + self.f[name][0], 1)[0])

    def mode(self):
        return self.i32("selectedGameMode")

    def score(self):
        return self.i32("score")

    def _on(self):
        if self.co is not None and (self.g.m.i32(self.co + 0x10) or -1) >= 0:
            return True
        return self.flag("roundActive")

    def active(self):
        """A round is on: its coroutine hasn't finished (state -1) or roundActive is set.
        Over only when neither holds on three reads 0.2 s apart (roundActive drops between
        questions; a read can catch the coroutine mid-step)."""
        for i in range(3):
            if self._on():
                return True
            if i < 2:
                time.sleep(0.2)
        return False

    def clickable(self):
        return self.flag("clickable")

    def input_value(self):
        return self.string(self.g.m.u64(self.q + self.f["abcInputFieldValue"][0])) or ""

    def find_round(self):
        """The running round's coroutine object: an instance of the round class whose <>4__this
        is the quiz and whose state is live (>= 0). Searched near the last one first."""
        m = self.g.m
        for k, kind in ((self.k_abc, "abc"), (self.k_round, "buttons")):
            for h in self._scan(k):
                if m.u64(h + 0x20) == self.q and 0 <= (m.i32(h + 0x10) or -1) < 1000:
                    self.co, self.co_kind = h, kind
                    self._near = h
                    return True
        return False

    def _scan(self, value):
        m = self.g.m
        if self._near:   # objects of a kind tend to come back near where the last one was
            lo = self._near - (32 << 20)
            for r_lo, r_hi, perm, path in m.maps:
                if perm[1] == "w" and r_lo < self._near + (32 << 20) and r_hi > lo:
                    a, b = max(r_lo, lo), min(r_hi, self._near + (32 << 20))
                    import numpy as np
                    buf = m.read(a, b - a)
                    arr = np.frombuffer(buf[: len(buf) // 8 * 8], np.uint64)
                    hits = [a + int(i) * 8 for i in np.nonzero(arr == np.uint64(value))[0]]
                    if hits:
                        yield from hits
        yield from m.find_u64(value, limit=200)

    def question_id(self):
        """Changes with each question: the correct choice's object (the word, for Aakkoset)
        and the round's state-machine step."""
        m = self.g.m
        k = self.k_abc if self.co_kind == "abc" else self.k_round
        f = self.g.class_fields(k)
        key = "<correctChoice>5__3" if self.co_kind == "abc" else "<correctChoice>5__7"
        return m.u64(self.co + f[key][0]), m.i32(self.co + 0x10)

    def button_y(self, index):
        """Screen y of the answer button for choice `index`."""
        g = self.g
        for b in g.items(g.field(self.q, "choiceButtons")):
            if b and g.field(b, "index", "i32") == index:
                return BUTTON_Y0 - BUTTON_SCALE * g.world_pos(g.transform(b))[1]
        return None

    def question(self):
        """('buttons', correct index, number of choices) or ('abc', the word, None)."""
        m = self.g.m
        # (read here: IL2CPP fills a class's fields in when it's first used)
        if self.co_kind == "abc":
            fa = self.g.class_fields(self.k_abc)
            return "abc", self.string(m.u64(self.co + fa["<correctChoice>5__3"][0])), None
        fr = self.g.class_fields(self.k_round)
        choices = m.u64(self.co + fr["<choices>5__5"][0])
        n = self.g.items(choices)
        return "buttons", m.i32(self.co + fr["<correctChoiceIndex>5__6"][0]), len(n)


class Bot:
    def __init__(self, cat):
        self.cat = cat
        self.t = device.make_touch()
        self.quiz = Quiz()
        self.verbose = False

    def tap(self, xy, wait=0.0):
        self.t.tap(xy[0] / device.REF_W, xy[1] / device.REF_H, 0.06)
        if wait:
            time.sleep(wait)

    def wait(self, pred, timeout, interval=0.02):
        end = time.time() + timeout
        while time.time() < end:
            if pred():
                return True
            time.sleep(interval)
        return False

    def close_keyboard(self):
        """A keyboard left up (after Aakkoset) covers Pelaa."""
        for _ in range(3):
            if not device.keyboard_shown():
                return
            self.tap(KEYBOARD_OK, 0.8)

    def start_round(self):
        q = self.quiz
        q.co = None
        self.close_keyboard()
        if q.mode() != MODE_INDEX[self.cat]:
            self.tap((CATEGORIES[self.cat], TILE_Y), 1.0)
        self.tap(PELAA)
        if not self.wait(q.active, 6):
            raise RuntimeError("the round didn't start (is the quiz's menu open?)")
        if not self.wait(q.find_round, 4, 0.1):
            raise RuntimeError("can't find the round's coroutine in memory")

    def answer_buttons(self, idx, n):
        y = self.quiz.button_y(idx)
        if y is None:
            log(f"  no button for choice {idx}")
            return
        if self.verbose:
            log(f"    tap y {y:.0f}")
        self.tap((270, y))

    def answer_abc(self, word):
        q = self.quiz
        for attempt in range(3):
            self.tap(ANSWER_BOX, 0.3)
            for _ in range(len(q.input_value()) + 2):     # clear what's there
                self.t.cmd(f"k {KEYCODE_DEL}")
            self.t.cmd(f"t {word}")
            if self.wait(lambda: q.input_value().strip().lower() == word.lower(), 1.0):
                self.t.cmd(f"k {KEYCODE_ENTER}")
                return True
        log(f"  couldn't type {word} (field: {q.input_value()!r})")
        return False

    def play_round(self, until=None):
        q = self.quiz
        self.start_round()
        answered, best = None, 0
        while q.active():
            best = max(best, q.score())
            if until is not None and q.score() >= until:
                self.wait(lambda: not q.active(), 60, 0.2)   # stop answering: the timer ends it
                break
            # a new question that takes input
            if not self.wait(lambda: not q.active() or (q.clickable() and q.question_id()[0] != answered), 10):
                log(f"  no new question in 10 s (score {q.score()})")
                break
            if not q.active():
                break
            qid = q.question_id()[0]
            score = q.score()
            kind, ans, n = q.question()
            if self.verbose:
                log(f"  {kind} {ans} of {n}")
            if kind == "abc":
                self.answer_abc(ans)
            else:
                self.answer_buttons(ans, n)
            answered = qid
            self.wait(lambda: q.score() != score or not q.active(), 6)
            best = max(best, q.score())
        log(f"Round ({self.cat}): {best} points")
        if self.cat == "aakkoset":
            time.sleep(1.0)
            self.close_keyboard()
        time.sleep(2.0)       # the result, then the menu again
        return best

    def run(self, rounds, until=None):
        k, best = 0, 0
        while rounds == 0 or k < rounds:
            k += 1
            best = max(best, self.play_round(until))
        return best


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("category", choices=CATEGORIES)
    ap.add_argument("-n", "--rounds", type=int, default=0, help="rounds to play (0 = until stopped)")
    ap.add_argument("--until", type=int, help="stop answering at this score (the timer ends the round)")
    ap.add_argument("-v", "--verbose", action="store_true", help="log every question")
    args = ap.parse_args()
    bot = Bot(args.category)
    bot.verbose = args.verbose
    bot.run(args.rounds, args.until)


if __name__ == "__main__":
    main()
