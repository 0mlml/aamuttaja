"""Pakuralli: steer the van between the rows of TNT crates. Played from the game's memory.

Start it with the Pakuralli start screen open (the big play button):
    python -m inttibot pakuralli            # play until stopped
    python -m inttibot pakuralli -n 3       # 3 runs

Everything comes from CarGame (inttibot.mem): the van (CarController: its position, sideways
velocity, alive), the crates (CarGameObstacle in activePoolables) and the lanes (5, laneMargin
6 apart: x = -12, -6, 0, 6, 12). Sideways physics (measured): holding a side accelerates the van
at horizontalAcc (67 units/s^2) up to horizontalMaxVel; letting go decelerates it at the same
rate to a stop, no drift. So the controller holds towards the target lane until the braking
distance v^2 / 2a covers what's left, then lets go. See docs/pakuralli.md.
"""
import argparse
import struct
import time

import numpy as np

from .. import device, mem

LEFT, RIGHT = (0.22, 0.80), (0.78, 0.80)   # where to hold to steer (screen fractions)
PLAY = (270, 755)
LAG = 0.08          # s from a touch to the game reacting (touch, then the next physics step)
PLAN_DELAY = 0.06   # s a plan takes (it's made for the van's state that much later)
COAST = 62.0        # deceleration when letting go (measured: 61-67 units/s^2)
# Collisions (from crash logs): the van touches a crate within ~4.1 sideways, and from ~2 ahead
# of its centre. Crates sit near the lane centres (x = -12 ... 12, 6 apart) but jitter sideways
# (posVariance 0.8), so the free space is planned from their actual positions.
BEHIND = 5.0        # a row still matters until it's this far behind the van's centre
AHEAD = 8.0         # plan to be in the gap by the time its row is this far ahead (contact: ~2)
NEAR = 30.0         # from this far ahead, aim at the middle of the row's gap
HIT = 4.3           # the van touches a crate closer than this sideways (centre to centre)
EDGE = 12.6         # the van's centre can't go further out than this (seen at -12.6)
MARGIN = 0.5        # a gap must leave the van at least this much room each side
DEEP = 1.2          # aim this far inside a gap (when it's wide enough)
DWELL = 0.04        # s each steering decision lasts at least (two physics steps: no chatter)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class Car:
    """CarGame's state, read from memory."""

    def __init__(self, game=None):
        self.g = game or mem.Game()
        g = self.g
        mm = g.static(g.find_class("MiniGameManager"), "INSTANCE")
        self.cg = g.field(mm, "carGame")
        self.f = g.all_fields(g.obj_class(self.cg))
        self.car = g.field(self.cg, "car")
        self.cf = g.all_fields(g.obj_class(self.car))
        self.tr = g.transform(self.car)
        self.acc = self.f32(self.car, self.cf, "horizontalAcc")
        self.lane_w = self.f32(self.cg, self.f, "laneMargin")
        self.lanes = g.field(self.cg, "laneCount", "i32")
        self.k_obstacle = g.find_class("CarGameObstacle")

    def f32(self, obj, fields, name):
        return struct.unpack("<f", self.g.m.read(obj + fields[name][0], 4))[0]

    def flag(self, obj, fields, name):
        return bool(self.g.m.read(obj + fields[name][0], 1)[0])

    def running(self):
        return self.flag(self.cg, self.f, "gameOn") and self.flag(self.car, self.cf, "alive")

    def score(self):
        return self.g.field(self.cg, "score", "i32")

    def state(self):
        """(x, z, sideways velocity)."""
        p = self.g.world_pos(self.tr)
        return p[0], p[2], self.f32(self.car, self.cf, "horizontalVel")

    def crates(self):
        """World (x, z) of every crate on the road."""
        g = self.g
        out = []
        for o in g.list_items(g.field(self.cg, "activePoolables")):
            if o and g.obj_class(o) == self.k_obstacle:
                p = g.world_pos(g.transform(o))
                out.append((p[0], p[2]))
        return out


class Steer:
    """Holds left, right or nothing; changes only when asked for a different state."""

    def __init__(self, touch):
        self.t = touch
        self.state = 0

    def set(self, d):
        if d == self.state:
            return
        if self.state:
            self.t.up()
        if d:
            self.t.down(*(RIGHT if d > 0 else LEFT))
        self.state = d


class Bot:
    def __init__(self):
        self.t = device.make_touch()
        self.steer = Steer(self.t)
        self.car = Car()
        self.verbose = False

    def rows(self, z_car):
        """Rows ahead (and alongside), nearest first: [(z, crate xs)]."""
        rows = []
        for x, z in sorted(self.car.crates(), key=lambda c: c[1]):
            if z <= z_car - BEHIND:
                continue
            if rows and z - rows[-1][0] < 3:
                rows[-1][1].append(x)
            else:
                rows.append((z, [x]))
        return rows

    @staticmethod
    def gaps(xs):
        """A row's free intervals for the van's centre, given its crates' xs."""
        out, lo = [], -EDGE
        for c in sorted(xs) + [None]:
            hi = EDGE if c is None else c - HIT
            if hi - lo > 2 * MARGIN:
                out.append((lo, hi))
            if c is not None:
                lo = c + HIT
        return out

    def move_time(self, dx):
        """Seconds to move dx sideways and stop (accelerate half the way, brake the rest)."""
        return 2 * (abs(dx) / self.car.acc) ** 0.5

    def plan(self, x, z, vz):
        """The target x. Gaps through the next rows (up to 3): every combination the van can
        make in time, moving only while no row is alongside, least sideways travel. The target
        is inside the first gap (by MARGIN), as near as allowed to the next one."""
        rows = self.rows(z)[:3]
        if not rows:
            return x
        speed = max(vz, 1e-3)
        best = None

        def go(k, px, t_free, path, cost):
            nonlocal best
            if best is not None and cost >= best[0]:
                return
            if k == len(rows):
                best = (cost, list(path))
                return
            z_row, xs = rows[k]
            t_due = max(0.0, z_row - z - AHEAD) / speed           # be inside the gap by then
            for lo, hi in self.gaps(xs):
                tx = float(np.clip(px, lo + MARGIN, hi - MARGIN))   # this gap's nearest point
                if t_free + self.move_time(tx - px) > t_due + 0.02:
                    continue
                go(k + 1, tx, (z_row - z + BEHIND) / speed, path + [(lo, hi)], cost + abs(tx - px))

        go(0, x, 0.0, [], 0.0)
        if best is None:          # nothing reachable in time: the nearest gap of the first row
            g = self.gaps(rows[0][1]) or [(-EDGE, EDGE)]
            lo, hi = min(g, key=lambda g: abs(float(np.clip(x, g[0], g[1])) - x))
            return float(np.clip(x, lo + MARGIN, hi - MARGIN))
        (lo, hi), rest = best[1][0], best[1][1:]
        want = x if not rest else float(np.clip(x, rest[0][0] + MARGIN, rest[0][1] - MARGIN))
        if rows[0][0] - z < NEAR:
            # its row is close: the middle of the gap (the outer ones: well inside the wall)
            return float(np.clip((lo + hi) / 2, lo + MARGIN, hi - MARGIN)) if hi - lo < 2 * HIT \
                else float(np.clip(want, lo + DEEP, hi - DEEP))
        m = min(DEEP, (hi - lo) / 2)      # well inside the gap, towards the next
        return float(np.clip(want, lo + m, hi - m))

    def control(self, x, v, target_x):
        """Where the van stops if let go now (after the input lag), and steer so that's the
        target: push towards it, let go when the stop lands on it, push back if it overshoots."""
        a = self.car.acc
        vp = float(np.clip(v + a * self.steer.state * LAG, -55, 55))
        xp = x + (v + vp) / 2 * LAG
        if abs(target_x - xp) < 0.3 and abs(vp) < 4:
            return 0
        stop = xp + np.sign(vp) * vp * vp / (2 * COAST)
        e = target_x - stop
        if e * vp < 0 and abs(e) > 0.3:
            return -int(np.sign(vp))      # would overshoot: brake harder than coasting
        if abs(e) < 0.4:
            return 0                      # coasting lands on it
        return 1 if e > 0 else -1

    def start(self):
        end = time.time() + 10
        while time.time() < end:
            if self.car.running():
                return
            self.t.tap(PLAY[0] / device.REF_W, PLAY[1] / device.REF_H, 0.06)   # back after the crash animation
            t1 = time.time() + 0.8
            while time.time() < t1:
                if self.car.running():
                    return
                time.sleep(0.02)
        raise RuntimeError("the run didn't start (is the Pakuralli start screen open?)")

    def drive(self):
        """One run, steered by the DP planner (pakuralli_dp): a planner thread keeps a fresh
        policy table; this loop predicts the van's sideways state over the input lag and takes
        the table's action for it. Returns (seconds, score)."""
        import threading
        from . import pakuralli_dp as dp
        if not hasattr(self, "dp"):
            self.dp = dp.Planner(self.car.acc)
        P = self.dp
        t0 = time.time()
        shared = {"pol": None, "t": 0.0, "vz": 30.0, "cost": 0.0}
        stop = threading.Event()

        hist = []        # (time, z) samples: the forward speed is the slope over the last 0.6 s

        def planner():
            vz = 55.0
            while not stop.is_set():
                x, z, v = self.car.state()
                now = time.time()
                hist.append((now, z))
                while hist and hist[0][0] < now - 0.6:
                    hist.pop(0)
                if len(hist) >= 5 and hist[-1][0] - hist[0][0] > 0.2:
                    ts, zs = np.array(hist).T
                    vz = float(np.polyfit(ts - ts[0], zs, 1)[0])
                crates = [(cx, cz) for cx, cz in self.car.crates() if cz > z - dp.BEHIND - 2]
                # where the van will be when this plan starts to apply
                pol, V = P.plan(z + vz * PLAN_DELAY, vz, crates)
                shared.update(pol=pol, t=now + PLAN_DELAY, vz=vz, cost=float(V[P.index(x, v)]))
        th = threading.Thread(target=planner, daemon=True)
        th.start()
        score, trace = 0, []
        lag_f = int(round(LAG * dp.FPS))
        queue = [0] * lag_f          # decisions sent but not acted on yet, oldest first
        next_tick = time.time()
        try:
            while self.car.running():
                # one decision per game frame
                now = time.time()
                if now < next_tick:
                    time.sleep(next_tick - now)
                next_tick = max(next_tick + dp.DT, time.time() - dp.DT)
                score = max(score, self.car.score())
                pol = shared["pol"]
                if pol is None:
                    continue
                x, z, v = self.car.state()
                now = time.time()
                hist.append((now, z))
                # the state when this decision takes effect: through the decisions queued before it
                xp, vp = x, v
                for u in queue:
                    vp = vp + float(np.clip(u * 55.0 - vp, -P.dv, P.dv))
                    xp = float(np.clip(xp + vp * dp.DT, -dp.EDGE, dp.EDGE))
                k = int(round((now - shared["t"]) * dp.FPS)) + lag_f
                k = int(np.clip(k, 0, pol.shape[0] - 1))
                xi, vi = P.index(xp, vp)
                d = int(pol[k, xi, vi])
                self.steer.set(d)
                queue = queue[1:] + [d]
                if self.verbose:
                    trace.append((round(now - t0, 2), round(x, 1), round(v, 1), d, k, round(shared["vz"]),
                                  round(shared["cost"], 3)))
                    del trace[:-600]
        finally:
            stop.set()
            th.join(timeout=1)
            self.steer.set(0)
        if self.verbose and trace:
            tend, prev = trace[-1][0], None
            log("  crashed; the last 1.2 s (t, x, v, steer, plan frame, speed, plan cost):")
            for e in trace:
                if e[0] > tend - 1.2 and (prev is None or e[3] != prev[3] or e[0] - prev[0] > 0.1):
                    log("    ", e)
                    prev = e
            x, z, v = self.car.state()
            log("    crates near:", [(round(cx, 1), round(cz - z, 1)) for cx, cz in self.car.crates() if -8 < cz - z < 15])
        return time.time() - t0, score

    def run(self, n):
        k = 0
        while n == 0 or k < n:
            k += 1
            self.start()
            dur, score = self.drive()
            log(f"Run {k}: {score} points, {dur:.1f} s")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--runs", type=int, default=0, help="runs to play (0 = until stopped)")
    ap.add_argument("-v", "--verbose", action="store_true", help="log the state at each crash")
    args = ap.parse_args()
    bot = Bot()
    bot.verbose = args.verbose
    bot.run(args.runs)


if __name__ == "__main__":
    main()
