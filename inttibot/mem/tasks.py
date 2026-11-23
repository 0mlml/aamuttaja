"""INTTI's daily tasks (TaskManager): slots of TaskInstance, each pointing at a TaskData.

Progress is the watched counter's value now (lastDisplayedProgress, updated as the games report
it) minus its value when the task was granted (startProgress). lastDisplayedProgress only moves
when the game shows the task in full (the Tehtävät panel, Pakuralli's results); inside a
minigame the quick view in its corner (TaskQuickViews: TaskQuickItem.currentDisplayProgress)
is current, so that's read too. The target is what TaskInstance.GetEffectiveCompletionThreshold
works out: completionThreshold (set at grant to 10 x (startProgress + avgProgressInMinute x
completionRequirementFactor x taskBaseCompletionMinutesRequirement)) back to a progress count,
scaled by TaskManager.GetTaskCompletionThresholdFactor(taskScale). See docs/tasks.md.
"""
import struct

from .il2cpp import STATIC_OFF, Game

# TaskManager.GetTaskCompletionThresholdFactor: TaskScale (an enum: Small, Big1, ...) -> factor
SCALE_FACTOR = {0: 0.75, 1: 1.0, 2: 1.5}


class Task:
    def __init__(self, slot, id, game, start, last, target, turned_in, shown=None):
        self.slot, self.id, self.game = slot, id, game
        self.start, self.last, self.target, self.turned_in = start, last, target, turned_in
        self.shown = shown     # the open minigame's quick view of it (progress), if it has one

    @property
    def progress(self):
        return max(self.last - self.start, self.shown or 0)

    @property
    def done(self):
        return self.progress >= self.target

    def __repr__(self):
        return f"[{self.slot}] {self.id}: {self.progress}/{self.target}" + (" (turned in)" if self.turned_in else "")


class Tasks:
    def __init__(self, game=None):
        self.g = game or Game()
        self.klass = self.g.find_class("TaskManager")
        st = self.g.m.u64(self.klass + STATIC_OFF)
        off = self.g.class_fields(self.klass)["taskBaseCompletionMinutesRequirement"][0]
        self.base_minutes = self.g.m.i32(st + off)

    def string(self, p):
        if not p:
            return None
        n = self.g.m.i32(p + 0x10)
        return self.g.m.read(p + 0x14, 2 * n).decode("utf-16-le") if 0 <= n < 500 else None

    def read(self):
        m, g = self.g.m, self.g
        inst = g.static(self.klass, "INSTANCE")
        shown = self.quick_view()
        out = []
        for slot, t in enumerate(g.array_items(g.field(inst, "taskInstances"))):
            if not t:
                continue
            ti = g.all_fields(g.obj_class(t))
            td = g.field(t, "myTaskData")
            df = g.all_fields(g.obj_class(td))
            start = m.i32(t + ti["startProgress"][0])
            threshold = m.i32(t + ti["completionThreshold"][0]) / 10
            factor = SCALE_FACTOR.get(m.i32(t + ti["taskScale"][0]), 1.0)
            target = max(1, round((threshold - start) * factor))   # round half to even, as the game
            out.append(Task(slot, self.string(m.u64(td + df["id"][0])), self.string(m.u64(td + df["gameId"][0])),
                            start, m.i32(t + ti["lastDisplayedProgress"][0]),
                            target, bool(m.read(t + ti["turnedIn"][0], 1)[0]), shown.get(t)))
        return out

    def quick_view(self):
        """{TaskInstance: progress shown} from the open minigame's task quick view."""
        g, m = self.g, self.g.m
        try:
            k = g.find_class("TaskQuickViews")
            qv = g.static(k, "INSTANCE")
            out = {}
            for it in g.items(g.field(qv, "items")) if qv else []:
                if not it or not g.native(it):
                    continue
                f = g.all_fields(g.obj_class(it))
                ti = m.u64(it + f["myInstance"][0])
                if ti:
                    out[ti] = m.i32(it + f["currentDisplayProgress"][0])
            return out
        except (RuntimeError, KeyError):
            return {}

    def next_grant(self):
        """Seconds until new tasks (TaskGranter.timeUntilNextGrant: a TimeSpan, 100 ns ticks)."""
        k = self.g.find_class("TaskGranter")
        gi = self.g.static(k, "INSTANCE")
        ticks = struct.unpack("<q", self.g.m.read(gi + self.g.class_fields(k)["timeUntilNextGrant"][0], 8))[0]
        return ticks / 1e7
