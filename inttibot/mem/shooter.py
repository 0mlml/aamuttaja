"""Ampumarata (ShooterGame): the scenario, its targets, the crosshair, the unaimed camera."""
import struct

import numpy as np

from .il2cpp import STATIC_OFF, Game, quat_rotate

UNAIMED_F = 2594.6         # px: the unaimed camera (weaponCamera's pose, ~26 deg vertical FOV), centred


class Range:
    """INTTI's ShooterGame: the scenario, its targets, the crosshair."""

    def __init__(self, game=None):
        self.g = game or Game()
        self.klass = self.g.find_class("ShooterGame")

    @property
    def inst(self):
        """The ShooterGame (via MiniGameManager: its own INSTANCE is null until it's opened)."""
        g = self.g
        return g.field(g.static(g.find_class("MiniGameManager"), "INSTANCE"), "shooterGame")

    def scenario(self):
        return self.g.field(self.inst, "loadedScenario")

    def eff(self):
        return np.array(struct.unpack("<ff", self.g.m.read(self.inst + self.g.all_fields(self.klass)["crosshairEffectivePos"][0], 8)))

    def inp(self):
        return np.array(struct.unpack("<ff", self.g.m.read(self.inst + self.g.all_fields(self.klass)["crosshairInputPos"][0], 8)))

    def camera(self):
        """(position, inverse rotation) of the unaimed camera."""
        tr = self.g.transform(self.g.field(self.inst, "weaponCamera"))
        q = self.g.world_rot(tr)
        return self.g.world_pos(tr), q * np.array([-1, -1, -1, 1.0])

    def project(self, P, cam=None):
        """World point -> unaimed-view screen point."""
        C, qi = cam or self.camera()
        v = quat_rotate(qi, np.asarray(P) - C)
        return np.array([270 + UNAIMED_F * v[0] / v[2], 600 - UNAIMED_F * v[1] / v[2]])

    def targets(self, lst="shootableTargets"):
        return self.g.list_items(self.g.field(self.scenario(), lst))
