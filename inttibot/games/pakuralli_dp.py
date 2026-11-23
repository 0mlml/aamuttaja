"""Pakuralli's planner: dynamic programming over the van's sideways state.

The game's sideways physics is exactly discrete (measured from memory): each frame (60/s)
horizontalVel moves towards input x 55 by at most horizontalAcc x dt = 67/60 = 1.117 (letting
go is input 0: the same rate down to a stop), so it is always an integer multiple of 1.117
(49 steps to full speed), and x moves by vel x dt: a multiple of q = 1.117/60. A state grid of
(x / q, vel / 1.117) is exact, and moves on it are integer index steps.

Over the next HORIZON frames each crate blocks |x - crate x| < HIT while its row is alongside
(from AHEAD ahead of the van's centre to BEHIND behind it, by the forward speed); nearer than
SOFT costs (clearance). Backward induction (compiled with numba) gives, for every state, the
least cost to the end of the horizon; the action now is the best from the current state.
"""
import numba
import numpy as np

FPS = 60.0
DT = 1.0 / FPS
VMAX_I = 49            # full speed: 55 / 1.117
HIT = 4.15             # contact sideways (centre to centre)
SOFT = 5.6             # clearance below this costs
AHEAD, BEHIND = 2.5, 5.0
EDGE = 12.6
HORIZON = 150          # frames (2.5 s)
INF = 1e9


@numba.njit(cache=True, parallel=True, nogil=True)
def _backward(hard, cost, nx, nv, vmax_i, terminal, keep):
    """Backward induction over (T, nx) costs. Returns the policy (best action, -1/0/1) for the
    first `keep` frames, as int8 (keep, nx, nv), and the value at t = 0."""
    T = hard.shape[0]
    V = terminal.copy()
    W = np.empty_like(V)
    pol = np.zeros((keep, nx, nv), np.int8)
    for t in range(T - 1, -1, -1):
        for xi in numba.prange(nx):
            for vi in range(nv):
                v = vi - vmax_i
                best = INF
                bu = 0
                for u in (0, -1, 1):
                    d = u * vmax_i - v
                    if d > 1:
                        d = 1
                    elif d < -1:
                        d = -1
                    v2 = v + d
                    x2 = xi + v2
                    if x2 < 0:
                        x2 = 0
                        v2 = 0          # the road's edge stops the van
                    elif x2 >= nx:
                        x2 = nx - 1
                        v2 = 0
                    if hard[t, x2]:
                        continue
                    c = V[x2, v2 + vmax_i] + cost[t, x2] + (0.0002 if u != 0 else 0.0)
                    if c < best:
                        best = c
                        bu = u
                W[xi, vi] = best
                if t < keep:
                    pol[t, xi, vi] = bu
        V, W = W, V
    return pol, V


class Planner:
    def __init__(self, acc=67.0):
        self.dv = acc * DT                 # 1.117: one frame's change of velocity
        self.q = self.dv * DT              # position quantum: x moves by v_i * q per frame
        self.nv = 2 * VMAX_I + 1
        self.xmax_i = int(EDGE / self.q)
        self.nx = 2 * self.xmax_i + 1
        self.xs = (np.arange(self.nx) - self.xmax_i) * self.q
        vi = np.arange(self.nv) - VMAX_I
        self.terminal = (0.002 * self.xs[:, None] ** 2 + 0.0005 * (vi[None, :] * self.dv) ** 2)
        self.V = None

    def costs(self, z, vz, crates, T=HORIZON):
        cost = np.zeros((T, self.nx))
        hard = np.zeros((T, self.nx), np.bool_)
        for cx, cz in crates:
            t0 = (cz - z - AHEAD) / vz * FPS
            t1 = (cz - z + BEHIND) / vz * FPS
            a, b = max(0, int(np.floor(t0)) - 1), min(T, int(np.ceil(t1)) + 1)
            if a >= b:
                continue
            d = np.abs(self.xs - cx)
            hard[a:b] |= d < HIT
            cost[a:b] += np.clip(SOFT - d, 0, None) ** 2
        return hard, cost

    def plan(self, z, vz, crates, keep=30):
        """Plan from now: the policy table for the next `keep` frames (best action for every
        sideways state) and the value table at t = 0. Crates [(x, z)], the van at forward
        position z with forward speed vz."""
        hard, cost = self.costs(z, vz, crates)
        pol, V = _backward(hard, cost, self.nx, self.nv, VMAX_I, self.terminal, keep)
        return pol, V

    def index(self, x, v):
        return (int(np.clip(round(x / self.q) + self.xmax_i, 0, self.nx - 1)),
                int(np.clip(round(v / self.dv), -VMAX_I, VMAX_I)) + VMAX_I)
