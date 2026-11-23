"""Ampumarata, the shooting range: every challenge, played from the game's memory.

Select a challenge in the Ampumarata menu (or leave its result screen open), then:
    python -m inttibot ampumarata           # play it once
    python -m inttibot ampumarata -n 5      # 5 times
    python -m inttibot ampumarata -v        # log every shot
    python -m inttibot ampumarata --auto -n 10   # each run: the challenge with the best case chance
    python -m inttibot ampumarata --chances      # list every challenge's case chance

Everything comes from ShooterGame (inttibot.mem.Range): the scenario (state: 0 menu, 2 running,
3 result; score; targets), the weapon (magazine), and crosshairWorldObject, which sits where
the sights point, and the crosshair's own state (goal, input, effective aim, the sway, the shot
lockout). Aiming moves the finger once to put the goal where the target will be (less the sway
predicted for then), waits for the game to take the move, and fires when the aim predicted for the
frame that takes the shot (~0.065 s later) is inside the fire window (see aim_world).

Targets:
- paper ("N laukausta tauluun"): the ShootingTarget under the objective arrow; its centre is the
  target's child point in the paper's plane (0.738 above the pivot on the large target)
- cans, melons, apples, bottles (shootableTargets): one at a time; cans by their blast (a
  destroyed can throws its neighbours off), the rest top down; moving ones skipped
- steel plates (jasters): each plate as it rises, aimed where it will be once up; between waves
  the game wants a reload
Case chance (--auto): a run with a medal rolls for a reward case with the challenge's own chance
(20-80%, 60 before its first roll), which drops to 20 when it pays; every 3 medal runs raise the next
5 challenges' chances by 20. Auto picks the challenge with the most chance per second of play.
See docs/ampumarata.md.
"""
import argparse
import struct
import time

import numpy as np

from .. import device, mem

AIM_FINGER = (270, 900)
FIRE = (270, 662)          # the "Laukaus" bar: a second finger fires
RELOAD = (241, 1011)
START = (270, 504)         # challenge menu: the target preview
RESTART = (450, 766)       # result screen: play again
FIRE_LAG = 0.065           # s from the fire command to the frame that takes the shot (measured 63-68 ms)
STEER_AHEAD = 0.1          # s: steering aims where the sway will be by then
K_GOAL = np.array([0.1296, -0.1296])   # crosshairGoalInputPos per finger px (measured; y flipped)
GOAL_MAX = 25.0            # ShooterGame.crosshairMaxInputMagnitude: the goal's clamp
MOVE_STEP = 40             # finger px per step of a big move (one frame takes ~70 at most)
RECOIL_DONE = 0.05         # shootSwayFactor below this: the recoil sway is gone
PLATE_UP = 1.5             # world units from a plate's hinge to its centre, once up
CAN_HALF = 0.2             # world units from a can's pivot (its base) to its centre, along its up axis
TARGET_W = {"ShootableCan": 0.28}   # world width for the fire window (default 0.28)
RING10 = 0.15              # the paper's 10 ring radius (world units, large target; measured by score)

RUNNING, RESULT = 2, 3     # Scenario.state


class GameFrozen(RuntimeError):
    """INTTI stopped running (a crash loop): restart it (farm does)."""
BACK = (60, 766)           # result screen: back to the challenge menu
PREV_SC, NEXT_SC = (45, 504), (495, 504)   # challenge menu arrows

# Reward case chance (Scenario.GetExtraRewardChance): the save's int CHANCE_KEY + id, or
# extraRewardFirstChance when unset, clamped to [extraRewardBaseChance, extraRewardMaxChance].
CHANCE_KEY = "shooter_game_scenario_extra_reward_chance_"
CASES_KEY = "shooter_game_cases_granted_total_from_challenges"
LEVEL_KEY = "shooter_level_current_level"
# Seconds a run takes, running to result (measured 2026-11-21); refined by the runs this session.
RUN_S = {"target_10_shots": 17, "target_8_shots": 20, "target_20_shots": 31, "target_15_shots": 29,
         "can_shooting": 27, "fruit_shooting": 25, "endless_plates": 44, "bottle_shooting": 15}
RESTART_S = 6.0            # result screen -> the same challenge running again
SWITCH_S, ARROW_S = 9.0, 0.6   # to another challenge: back to the menu, then per arrow tap


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class Bot:
    def __init__(self):
        self.t = device.make_touch()
        self.R = mem.Range()
        self.g = self.R.g
        self.fx, self.fy = AIM_FINGER
        self._gain_px = None      # projected px per effective unit (fitted)
        self._sway, self._pairs, self._last_eff = [], [], None
        self._coff = None
        self.verbose = False
        self._cw = None
        self.ud = mem.UserData(self.g)
        self._run_s = {}          # scenario id -> seconds a run took (this session)

    # --- state ------------------------------------------------------------------------------
    @property
    def sh(self):
        return self.R.inst

    def scenario(self):
        return self.g.field(self.sh, "loadedScenario")

    def state(self):
        sc = self.scenario()
        return self.g.field(sc, "state", "i32") if sc else 0

    def weapon(self):
        return self.g.field(self.sh, "currentWeapon")

    def mag(self):
        return self.g.field(self.weapon(), "currentMag", "i32")

    def flag(self, obj, name):
        return bool(self.g.m.read(obj + self.g.all_fields(self.g.obj_class(obj))[name][0], 1)[0])

    # --- input ------------------------------------------------------------------------------
    def finger(self, x, y):
        self.fx, self.fy = x, y
        self.t.move(x / device.REF_W, y / device.REF_H)

    def hold(self, settle=0.6):
        """Press the aim finger. The gun keeps the direction it had."""
        self.fx, self.fy = AIM_FINGER
        self.t.down(self.fx / device.REF_W, self.fy / device.REF_H)
        time.sleep(settle)

    def release(self):
        self.t.up()
        self.t.sync()

    def tap(self, xy, wait):
        self.t.tap(xy[0] / device.REF_W, xy[1] / device.REF_H, 0.06)
        time.sleep(wait)

    def fire(self, ex, ey):
        self.t.add_finger(FIRE[0] / device.REF_W, FIRE[1] / device.REF_H)
        time.sleep(0.03)
        self.t.lift_finger()
        if self.verbose:
            log(f"    fire (predicted error {ex:+.2f},{ey:+.2f} px)")

    def reload(self, timeout=4.0):
        """Reload (lifting the aim), wait for Weapon.currentMag to fill, press again. False
        when there's nothing to reload with."""
        g = self.g
        w = self.weapon()
        if g.field(w, "extraMags", "i32") <= 0 and self.mag() <= 0:
            return False
        self.release()
        time.sleep(0.1)
        full = g.field(w, "magSize", "i32")
        for _ in range(3):                      # a tap during the start animation is lost
            self.tap(RELOAD, 0.1)
            end = time.time() + timeout
            while time.time() < end and self.mag() < full and self.state() == RUNNING:
                time.sleep(0.05)
            if self.mag() > 0 or self.state() != RUNNING or g.field(w, "extraMags", "i32") <= 0:
                break
            log("  reload didn't take: again")
        self.hold(0.3)
        return self.mag() > 0

    def ammo(self):
        """Rounds in the gun, reloading when empty (or when the game asks between waves).
        False: none left."""
        g = self.g
        want = self.flag(self.sh, "allowReloadAboveZeroAmmo")
        m = self.mag()
        if m <= 0 or (want and m < g.field(self.weapon(), "magSize", "i32")):
            return self.reload()
        return True

    # --- aiming -----------------------------------------------------------------------------
    def cstate(self):
        """The crosshair state, in one read: base, input, its SmoothDamp velocity, goal, effective
        (2-vectors), aimCounter, minAimTimeToShoot, shotIntervalCounter, allowShooting,
        shootSwayFactor, statShotsFired."""
        g, m = self.g, self.g.m
        if self._coff is None:
            f = g.all_fields(g.obj_class(self.sh))
            names = ("crosshairBasePos", "crosshairInputPos", "crosshairInputPosVel", "crosshairGoalInputPos",
                     "crosshairEffectivePos", "aimCounter", "minAimTimeToShoot", "shotIntervalCounter",
                     "allowShooting", "shootSwayFactor", "statShotsFired")
            offs = {n: f[n][0] for n in names}
            lo = min(offs.values())
            self._coff = (lo, max(offs.values()) + 8 - lo, {n: o - lo for n, o in offs.items()})
        lo, n, o = self._coff
        raw = m.read(self.sh + lo, n)
        v = lambda k: np.array(struct.unpack_from("<ff", raw, o[k]))
        f = lambda k: struct.unpack_from("<f", raw, o[k])[0]
        return {"base": v("crosshairBasePos"), "inp": v("crosshairInputPos"), "vel": v("crosshairInputPosVel"),
                "goal": v("crosshairGoalInputPos"), "eff": v("crosshairEffectivePos"), "aim_t": f("aimCounter"),
                "min_aim": f("minAimTimeToShoot"), "interval": f("shotIntervalCounter"),
                "allow": raw[o["allowShooting"]], "shoot_sway": f("shootSwayFactor"),
                "shots": struct.unpack_from("<i", raw, o["statShotsFired"])[0], "t": time.time()}

    def observe(self, cam):
        """One poll: the crosshair state and, if no game frame passed during the reads, the
        crosshair's projection with it (an exact (effective, px) pair). Feeds the sway history
        (one sample per frame, on the game's aimCounter clock) and the effective -> px gain."""
        g = self.g
        s1 = self.cstate()
        u = self.R.project(g.world_pos(self._cw), cam)
        s2 = self.cstate()
        s2["u"] = u if np.array_equal(s1["eff"], s2["eff"]) else None
        h = self._sway
        if h and s2["aim_t"] < h[-1][0]:
            h.clear()                       # aiming restarted (a press): a new clock
        if not np.array_equal(s2["eff"], self._last_eff):
            self._last_eff = s2["eff"]
            if s2["shoot_sway"] < RECOIL_DONE:  # the recoil sway is fast noise: keep it out of the history
                h.append((s2["aim_t"], s2["t"], s2["eff"] - s2["base"] - s2["inp"]))
                del h[:-40]
            if s2["u"] is not None:
                self._pairs.append((s2["eff"], u))
                del self._pairs[:-200]
        return s2

    def sway_at(self, s, ahead):
        """The sway (effective - base - input) `ahead` s from the state's poll: a quadratic
        through the last 0.15 s of frames (predicts 60 ms to ~0.01 effective units)."""
        h = self._sway
        if not h:
            return np.zeros(2)
        t_now = h[-1][0] + (s["t"] - h[-1][1])
        pts = [(t, w) for t, _, w in h if t > h[-1][0] - 0.15]
        if len(pts) < 4 or t_now - h[-1][0] > 0.05 or pts[-1][0] - pts[0][0] < 0.04:
            return h[-1][2]     # no recent frames (the recoil): the last clean value
        T = np.array([t for t, _ in pts]) - t_now
        W = np.array([w for _, w in pts])
        return np.array([np.polyval(np.polyfit(T, W[:, a], 2), ahead) for a in (0, 1)])

    def px_gain(self):
        """Projected px per effective unit, per axis (a scaled mirror: x keeps its sign, y
        flips), fitted on the exact pairs; None until the sway or a move has spread them."""
        if len(self._pairs) < 6:
            return self._gain_px
        E = np.array([e for e, _ in self._pairs])
        U = np.array([u for _, u in self._pairs])
        out = []
        for a in (0, 1):
            if np.ptp(E[:, a]) < 0.02:
                return self._gain_px
            out.append(np.polyfit(E[:, a], U[:, a], 1)[0])
        self._gain_px = np.array(out)
        return self._gain_px

    def aim_world(self, target, tol=2.2, timeout=2.5, fire=True):
        """Aim at a world point (or an unaimed-view px point) and fire when the shot will land
        within `tol` px of it. Returns True when the shot was taken (statShotsFired moved), or
        with fire=False when the aim is there.

        The game's crosshair (ShooterGame.CrosshairPosUpdate): goal += the finger's move x
        K_GOAL per px (y flipped); input follows goal (SmoothDamp, 0.03 s); effective = base +
        input + sway (Perlin, slow). The shot goes through the effective aim of the frame that
        takes it, ~FIRE_LAG after the command. So: one finger move puts goal where the target
        will be minus the sway predicted for the shot, then nothing until the game has taken
        the move and input has settled; fire when base + goal + the sway at the shot frame is
        within `tol` and the game will take a shot (shotIntervalCounter, aimCounter, the recoil
        sway gone). Steer again only when that drifts past tol / 2."""
        R = self.R
        if self._cw is None:
            self._cw = self.g.transform(self.g.field(self.sh, "crosshairWorldObject"))
        cam = R.camera()
        tu = R.project(target, cam) if len(target) == 3 else np.asarray(target, float)
        start = time.time()
        pending = None          # (time sent, goal expected, time goal last changed, goal last seen)
        settle_until = 0.0
        trace = []              # the moves, logged if the aim times out
        s = self.observe(cam)
        while time.time() - start < timeout:
            time.sleep(0.003)
            s = self.observe(cam)
            gain = self.px_gain()
            if s["u"] is None or gain is None:
                continue
            if self.flag(self.sh, "allowReloadAboveZeroAmmo"):
                return False            # a wave is over: the game drops the sights and wants a reload
            if pending is not None:
                t0, want, t_chg, g_last = pending
                now = time.time()
                if not np.array_equal(s["goal"], g_last):
                    pending = (t0, want, now, s["goal"])
                    if np.abs(s["goal"] - want).max() < 0.02:
                        pending, settle_until = None, now + 0.03     # taken in full
                elif t_chg is not None and now - t_chg > 0.05:
                    trace.append(f"{now - start:.2f}s stopped short: goal {np.round(s['goal'], 2)}, wanted {np.round(want, 2)}")
                    pending, settle_until = None, now   # stopped short (a clamp): steer again from where it is
                elif t_chg is None and now - t0 > 0.15:
                    trace.append(f"{now - start:.2f}s the move changed nothing: press again")
                    pending = None      # the move changed nothing: the sights are down; press again
                    self.release()
                    self.hold(0.4)
                if pending is not None:
                    continue
            if time.time() < settle_until or np.abs(s["goal"] - s["inp"]).max() > 0.02:
                continue
            e_target = s["eff"] + (tu - s["u"]) / gain      # the effective aim that hits the target
            err = lambda ahead: gain * (s["base"] + s["goal"] + self.sway_at(s, ahead) - e_target)
            e_fire = err(FIRE_LAG)
            recoil = s["shoot_sway"] >= RECOIL_DONE
            if np.abs(e_fire).max() <= tol and not recoil:
                if not fire:
                    return True
                if s["allow"] and s["interval"] <= 0 and s["aim_t"] >= s["min_aim"]:
                    shots = s["shots"]
                    self.fire(e_fire[0], e_fire[1])
                    end = time.time() + 0.3
                    while time.time() < end:
                        if self.cstate()["shots"] != shots:
                            return True
                        time.sleep(0.005)
                    if self.verbose:
                        log("    the shot wasn't taken")
                    continue
            e_steer = err(STEER_AHEAD)
            if np.abs(e_steer).max() <= tol / 2 and np.abs(e_fire).max() <= tol:
                continue                # on target: wait for the gun
            if recoil and np.abs(e_steer).max() <= 4 * tol:
                continue                # the recoil sway fades by itself: only coarse moves meanwhile
            want = s["goal"] - e_steer / gain
            r = np.hypot(*want)
            if r > GOAL_MAX:
                if self.verbose:
                    log(f"  out of reach (goal {np.round(want, 2)}, the game clamps at {GOAL_MAX})")
                return False
            dfx, dfy = (want - s["goal"]) / K_GOAL
            if not (40 < self.fx + dfx < 500 and 560 < self.fy + dfy < 1160):
                trace.append(f"{time.time() - start:.2f}s the finger would leave the screen: press again")
                self.release()          # the finger would leave the screen: press again (the gun keeps its aim)
                self.hold(0.4)
                continue
            pending = (time.time(), want, None, s["goal"])
            trace.append(f"{time.time() - start:.2f}s move {dfx:+.1f},{dfy:+.1f} px: error {np.round(e_steer, 1)}"
                         f"{' (recoil)' if recoil else ''}, goal {np.round(s['goal'], 2)} -> {np.round(want, 2)}")
            n = int(max(1, np.ceil(max(abs(dfx), abs(dfy)) / MOVE_STEP)))
            x0, y0 = self.fx, self.fy
            for j in range(1, n + 1):   # the game takes at most ~70 px of finger per frame
                self.finger(x0 + dfx * j / n, y0 + dfy * j / n)
                if j < n:
                    time.sleep(0.017)
        if self.verbose and fire:
            log(f"  aim timed out (error {np.round(tu - s['u'], 2) if s.get('u') is not None else '?'} px)")
            for line in trace[-8:]:
                log(f"      {line}")
        return False

    def up_axis(self, obj):
        return mem.quat_rotate(self.g.world_rot(self.g.transform(obj)), np.array([0.0, 1.0, 0.0]))

    def window(self, point, width):
        """Fire window (unaimed px): a third of `width` (world units) at the point's distance."""
        dist = np.linalg.norm(np.asarray(point) - self.R.camera()[0])
        return float(np.clip(0.35 * width * mem.UNAIMED_F / dist, 0.25, 3.0))

    # --- paper targets ----------------------------------------------------------------------
    def paper_target(self):
        """The ShootingTarget under the objective arrow, and its centre (world)."""
        g, m = self.g, self.g.m
        arrows = [a for a in g.items(g.field(self.sh, "activeObjectiveArrows")) if a]
        k = g.find_class("ShootingTarget")
        targets, P = [], []
        for h in m.find_u64(k, limit=100):       # (stale copies of the class pointer don't resolve)
            p = g.world_pos(g.transform(h)) if g.native(h) else None
            if p is not None:
                targets.append(h)
                P.append(p)
        if not arrows or not targets:
            return None, None
        ap = g.world_pos(g.transform(arrows[0]))
        i = int(np.argmin([np.hypot(p[0] - ap[0], p[2] - ap[2]) for p in P]))
        return targets[i], self.paper_centre(targets[i])

    def paper_centre(self, target):
        """The target's centre: of its child points (the score rings' marks, in the paper's
        plane at the bullseye's height), the one nearest its plane."""
        g, m = self.g, self.g.m
        tr = g.transform(target)
        H, idx = m.u64(tr + 0x28), m.i32(tr + 0x30)
        parents, trs = m.u64(H + 0x20), m.u64(H + 0x18)
        n = m.i32(H + 0x10)
        pidx = np.frombuffer(m.read(parents, 4 * n), np.int32)
        base = g.world_pos(tr)
        best = None
        for c in np.nonzero(pidx == idx)[0]:
            p, i = None, int(c)
            while i >= 0:
                t = struct.unpack("<12f", m.read(trs + i * 48, 48))
                pos, q, s = np.array(t[0:3]), np.array(t[4:8]), np.array(t[8:11])
                p = pos if p is None else pos + mem.quat_rotate(q, s * p)
                i = m.i32(parents + i * 4)
            d = p - base
            if d[1] > 0.05 and (best is None or abs(d[2]) < abs(best[2])):
                best = d
        return base + (best if best is not None else np.array([0.0, 0.738, 0.0]))

    def play_paper(self):
        shots = 0
        target, centre = self.paper_target()
        if target is None:
            log("  no marked paper target found")
            return 0
        tol = self.window(centre, 2 * RING10)
        if self.verbose:
            log(f"  target at {np.round(centre, 2)}, window {tol:.2f} px")
        while self.state() == RUNNING:
            if not self.ammo():
                break
            if self.aim_world(centre, tol=tol, timeout=4.0):
                shots += 1
                time.sleep(0.25)
        return shots

    # --- objects: cans, melons, apples, bottles -----------------------------------------------
    def centre(self, c, tclass):
        up = CAN_HALF if tclass == "ShootableCan" else 0.0
        return self.g.world_pos(self.g.transform(c)) + up * self.up_axis(c)

    def settle(self, objs, alive_off, hit_off, most=0.8):
        """Wait until what a shot threw has landed (positions of the ones left stop changing)."""
        g = self.g
        time.sleep(0.3)
        end, prev = time.time() + most, None
        while time.time() < end:
            P = np.array([g.world_pos(g.transform(c)) for c in objs
                          if g.m.read(c + alive_off, 1)[0] and not (hit_off and g.m.read(c + hit_off, 1)[0])])
            if prev is not None and len(P) == len(prev) and (not len(P) or np.abs(P - prev).max() < 0.004):
                return
            prev = P
            time.sleep(0.1)

    def play_objects(self):
        R, g, m = self.R, self.g, self.g.m
        objs = R.targets()
        tclass = g.class_name(g.obj_class(objs[0]))
        f = g.all_fields(g.obj_class(objs[0]))
        alive_off = f["alive"][0]
        hit_off = f["hitGround"][0] if "hitGround" in f else None
        radius = struct.unpack("<f", m.read(objs[0] + f["deathForceRadius"][0], 4))[0] + 0.05
        log(f"  {len(objs)} {tclass} targets")
        shots, missed = 0, {}
        while self.state() == RUNNING:
            if not self.ammo():
                break
            left = [c for c in objs if m.read(c + alive_off, 1)[0] and not (hit_off and m.read(c + hit_off, 1)[0])]
            if not left:
                time.sleep(0.2)
                continue
            W0 = np.array([g.world_pos(g.transform(c)) for c in left])
            time.sleep(0.08)
            W = np.array([g.world_pos(g.transform(c)) for c in left])
            moving = np.linalg.norm(W - W0, axis=1) / 0.08 > 0.15   # still falling or rolling
            if moving.all():
                continue
            cam = R.camera()
            if self._cw is None:
                self._cw = g.transform(g.field(self.sh, "crosshairWorldObject"))
            au = R.project(g.world_pos(self._cw), cam)
            U = [R.project(self.centre(c, tclass), cam) for c in left]
            near = lambda i: -np.hypot(*(U[i] - au))
            if tclass == "ShootableCan":
                # a destroyed can throws the cans within its deathForceRadius off; tried on every
                # can as the opening shot: a pyramid's base throws the most. Cans with company,
                # the lowest row first, then the most neighbours, then the nearest
                D = np.linalg.norm(W[:, None, :] - W[None, :, :], axis=2)
                nb = ((D < radius) & ~moving[None, :]).sum(1) - 1
                nb[moving] = -99
                k = max(range(len(left)), key=lambda i: (missed.get(left[i], 0) < 2, nb[i] >= 2,
                                                         -round(W[i, 1] / 0.2), nb[i], near(i)))
            else:
                # destroyed, not dropped: the highest first (one knocked off a box rolls away,
                # maybe out of reach), then the nearest
                k = max(range(len(left)), key=lambda i: (missed.get(left[i], 0) < 2, not moving[i],
                                                         round(W[i, 1] / 0.3), near(i)))
            c = left[k]
            # a shot that took nothing was blocked (a can lying in front, a fragment): higher next
            up = (0.0, 0.13, -0.08)[min(missed.get(c, 0), 2)]
            point = self.centre(c, tclass) + up * self.up_axis(c)
            tol = self.window(point, TARGET_W.get(tclass, 0.28))
            before = sum(1 for o in objs if m.read(o + alive_off, 1)[0])
            if self.aim_world(point, tol=tol):
                shots += 1
                self.settle(objs, alive_off, hit_off)
                if sum(1 for o in objs if m.read(o + alive_off, 1)[0]) == before:
                    missed[c] = missed.get(c, 0) + 1
                if self.verbose:
                    log(f"    {len(left)} left; {'hit' if m.read(c + alive_off, 1)[0] == 0 else 'blocked'}")
        done = sum(1 for c in objs if not m.read(c + alive_off, 1)[0] or (hit_off and m.read(c + hit_off, 1)[0]))
        log(f"  {done}/{len(objs)} down")
        return shots

    # --- steel plates -----------------------------------------------------------------------
    def play_plates(self):
        """Plates rise a few at a time, wave after wave (Jaster.plateUp): shoot each one up,
        aimed where it will be once up. One shot starts the first wave; between waves wait in
        the middle of them (and reload: the game wants it)."""
        R, g, m = self.R, self.g, self.g.m
        J = R.targets("jasters")
        f = g.all_fields(g.obj_class(J[0]))
        up_off, plate_off = f["plateUp"][0], f["plate"][0]
        plates = {j: g.transform(m.u64(j + plate_off)) for j in J}
        where = lambda j: g.world_pos(plates[j]) + np.array([0.0, PLATE_UP, 0.0])
        log(f"  {len(J)} plates")
        shots, started, parked, idle = 0, False, False, time.time()
        shot_at = {}
        while self.state() == RUNNING:
            if not self.ammo():
                break
            up = [j for j in J if m.read(j + up_off, 1)[0]]
            if not up:
                if not started and time.time() - idle > 1.0:
                    self.fire(0, 0)
                    shots += 1
                    started = True
                elif started and not parked:
                    cam = R.camera()
                    self.aim_world(np.mean([R.project(where(j), cam) for j in J], axis=0), timeout=1.0, fire=False)
                    parked = True
                time.sleep(0.05)
                continue
            parked = False
            cam = R.camera()
            if self._cw is None:
                self._cw = g.transform(g.field(self.sh, "crosshairWorldObject"))
            au = R.project(g.world_pos(self._cw), cam)
            fresh = [j for j in up if time.time() - shot_at.get(j, 0) > 1.0]   # a hit plate is up while it falls
            if not fresh:
                time.sleep(0.05)
                continue
            j = min(fresh, key=lambda j: np.hypot(*(R.project(where(j), cam) - au)))
            if self.aim_world(where(j), timeout=2.0):
                shots += 1
                shot_at[j] = time.time()
            idle = time.time()
        return shots

    def prime(self, seconds=0.4):
        """New scenario: forget the last one's crosshair history, then watch the sway (it moves
        the aim on its own) long enough to fit the effective -> px gain."""
        self._sway, self._pairs, self._last_eff, self._gain_px = [], [], None, None
        self._cw = self.g.transform(self.g.field(self.sh, "crosshairWorldObject"))
        cam = self.R.camera()
        end = time.time() + seconds
        while time.time() < end or (self.px_gain() is None and time.time() < end + 1.0):
            self.observe(cam)
            time.sleep(0.003)
        if self.verbose:
            log(f"  px per effective unit {np.round(self.px_gain(), 3) if self.px_gain() is not None else '?'}")

    # --- a challenge ------------------------------------------------------------------------
    def play(self):
        """One challenge, from its menu or result screen to the next result."""
        end = time.time() + 15
        while self.state() not in (0, RESULT, RUNNING) and time.time() < end:
            time.sleep(0.3)
        if self.state() == RESULT:
            # the medal animation covers the button; a level-up and a reward case take longer
            time.sleep(3.0)
            for _ in range(6):
                self.tap(RESTART, 0.5)
                if self.wait_state(RUNNING, 3.0):
                    break
        elif self.state() != RUNNING:
            self.tap(START, 0.5)
        self.wait_state(RUNNING, 10.0)
        if self.state() != RUNNING:
            raise RuntimeError("the challenge didn't start (is the Ampumarata menu open?)")
        sc = self.scenario()
        t0 = time.time()
        time.sleep(1.0)
        self.hold(0.6)
        self.prime()
        try:
            if self.R.targets("jasters"):
                kind, shots = "plates", self.play_plates()
            elif self.R.targets():
                kind, shots = "objects", self.play_objects()
            else:
                kind, shots = "paper", self.play_paper()
        finally:
            self.release()
        end = time.time() + 60                    # the timer ends a run the bot stopped in
        while self.state() == RUNNING and time.time() < end:
            time.sleep(0.3)
        self._took = time.time() - t0             # running -> result
        if shots == 0 and (device.crash_looping() or not device.app_running()):
            raise GameFrozen("INTTI is crash-looping (logcat CRASH)")
        log(f"Challenge ({kind}) done: {shots} shots, score {self.g.field(sc, 'score', 'i32')}")
        return shots

    # --- choosing a challenge by its case chance ----------------------------------------------
    def all_scenarios(self):
        lst = self.g.field(self.sh, "allScenarios")
        return self.g.list_items(lst) or self.g.array_items(lst)

    def chances(self):
        """Every main challenge: [{n (1-based, as the menu numbers them), id, chance %, unlocked}]."""
        g, ud = self.g, self.ud
        k = g.find_class("Scenario")
        lo, first, _, hi = struct.unpack("<4i", g.m.read(g.m.u64(k + 0xB8), 16))
        ints = ud.read("ints")
        level = ints.get(LEVEL_KEY, 0)
        main = set(g.list_items(g.field(self.sh, "mainScenarios")))
        out = []
        for i, sc in enumerate(self.all_scenarios()):
            if sc not in main:
                continue
            sid = ud.string(g.field(sc, "id"))
            c = min(max(ints.get(CHANCE_KEY + sid, first), lo), hi)
            out.append({"n": i + 1, "id": sid, "chance": c,
                        "unlocked": level >= g.field(sc, "levelRequirement", "i32")})
        return out

    def run_s(self, sid):
        if sid in self._run_s:
            return self._run_s[sid]
        return next((v for k, v in RUN_S.items() if sid.startswith(k)), 30)

    def current(self):
        sel = self.g.field(self.sh, "selectedScenario")
        sc = self.all_scenarios()
        return sc.index(sel) + 1 if sel in sc else None

    def pick(self):
        """The challenge with the most case chance per second (its run, plus getting to it)."""
        cur, n = self.current(), len(self.all_scenarios())

        def cost(c):
            if c["n"] == cur:
                return self.run_s(c["id"]) + RESTART_S
            d = (c["n"] - (cur or 1)) % n
            return self.run_s(c["id"]) + SWITCH_S + ARROW_S * min(d, n - d)
        best = max((c for c in self.chances() if c["unlocked"]), key=lambda c: c["chance"] / cost(c))
        return best, cost(best)

    def to_menu(self):
        """From the result screen back to the challenge menu (state 0); a run still going is let
        run out first."""
        if self.state() == RUNNING:
            self.wait_state(RESULT, 60.0)
        if self.state() == RESULT:
            time.sleep(3.0)                     # the medal animation covers the buttons
            for _ in range(6):
                self.tap(BACK, 0.8)
                if self.wait_state(0, 2.0):
                    break
        return self.state() == 0

    def select(self, number):
        """Page the challenge menu to challenge `number` (1-based) by the shorter way round."""
        n = len(self.all_scenarios())
        for _ in range(3):
            cur = self.current()
            if cur is None:
                return False
            d = (number - cur) % n
            if d == 0:
                return True
            right = d <= n // 2
            for _ in range(d if right else n - d):
                self.tap(NEXT_SC if right else PREV_SC, 0.6)
            time.sleep(0.8)
        return self.current() == number

    def play_best(self):
        """Go to the challenge with the best case chance and play it; log the roll's outcome."""
        best, cost = self.pick()
        log(f"Case chance: #{best['n']} {best['id']} {best['chance']}% "
            f"(~{cost:.0f} s with getting to it: {0.6 * best['chance'] / cost:.2f} cases/min)")
        if best["n"] != self.current() or self.state() not in (RESULT, 0):
            if not self.to_menu() or not self.select(best["n"]):
                raise RuntimeError(f"couldn't select challenge #{best['n']}")
        before = self.ud.ints(CASES_KEY, LEVEL_KEY)
        self.play()
        took = self._took
        old = self._run_s.get(best["id"])
        self._run_s[best["id"]] = took if old is None else 0.5 * (old + took)
        after = self.ud.ints(CASES_KEY, LEVEL_KEY)
        got = after[CASES_KEY] - before[CASES_KEY]
        # a level-up grants a case per level, and another at every 10th (ReportScenarioFinishGeneric)
        levels = range(before[LEVEL_KEY] + 1, after[LEVEL_KEY] + 1)
        lvl_cases = len(levels) + sum(1 for lv in levels if lv % 10 == 0)
        roll = got - lvl_cases
        log(f"  {took:.0f} s; case roll {'won' if roll > 0 else 'lost'}"
            + (f"; level {after[LEVEL_KEY]}: +{lvl_cases} cases" if lvl_cases else ""))
        return got

    def wait_state(self, state, timeout):
        end = time.time() + timeout
        while self.state() != state and time.time() < end:
            time.sleep(0.1)
        return self.state() == state

    def run(self, rounds, auto=False):
        cases = 0
        for _ in range(rounds):
            if auto:
                cases += self.play_best()
            else:
                self.play()
        if auto:
            log(f"{rounds} runs: {cases} cases")
        return cases


def open_range():
    """Open Ampumarata (from wherever the app is) if it isn't open."""
    from ..tasks import App
    g = mem.Game()
    if mem.UI(g).minigame() != "shooter_game":
        App(g).open_game("shooter_game")
        time.sleep(2.0)


def recover():
    """Restart INTTI and open Ampumarata again."""
    log("  restarting INTTI")
    device.stop_app()
    time.sleep(2)
    device.launch_app(wait=30)
    open_range()


def farm(rounds, auto=True, number=None, verbose=False, tries=3):
    """Bot.run that outlives INTTI freezing: on a failure, restart the app if it's stuck (then a
    fresh Bot: the addresses change), select `number` again if given, and go on with the runs left."""
    done = cases = fails = 0
    while done < rounds:
        try:
            open_range()
            bot = Bot()
            bot.verbose = verbose
            if number is not None and bot.state() != RUNNING:
                bot.to_menu()
                bot.select(number)
            while done < rounds:
                if auto:
                    cases += bot.play_best()
                else:
                    bot.play()
                done += 1
                fails = 0
        except Exception as e:              # the game's memory changes under a restart
            fails += 1
            log(f"  run {done + 1} failed: {type(e).__name__}: {e}")
            if fails > tries:
                raise
            # a frozen app, or the same failure twice: restart it; else just try again
            if isinstance(e, GameFrozen) or fails > 1 or device.crash_looping() or not device.app_running():
                recover()
    if auto:
        log(f"{rounds} runs: {cases} cases")
    return cases


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--rounds", type=int, default=1, help="times to play the challenge")
    ap.add_argument("-v", "--verbose", action="store_true", help="log every shot")
    ap.add_argument("--auto", action="store_true", help="each run: the challenge with the best case chance")
    ap.add_argument("--chances", action="store_true", help="list the challenges' case chances and exit")
    args = ap.parse_args()
    bot = Bot()
    bot.verbose = args.verbose
    if args.chances:
        best, _ = bot.pick()
        for c in bot.chances():
            mark = "*" if c is best or c["n"] == best["n"] else " "
            lock = "" if c["unlocked"] else " (locked)"
            print(f"{mark} #{c['n']:2d} {c['id']:30s} {c['chance']:3d}%  ~{bot.run_s(c['id'])} s{lock}")
        return
    farm(args.rounds, auto=args.auto, verbose=args.verbose)


if __name__ == "__main__":
    main()
