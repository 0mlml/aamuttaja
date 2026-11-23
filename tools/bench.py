"""Measure how many taps the game actually counts per second, and its real frame rate.

Usage: python -m tools.bench [seconds]
Run with the game on the Denssiklikkeri screen and the bot stopped. The bank and the owned
upgrades come from memory (inttibot.games.denssi.Clicker).
"""
import os
import re
import subprocess
import sys
import time

from inttibot.games.denssi import Game, state
from inttibot.games.denssi_data import income

from inttibot import device

ADB = device.ADB


def unity_layer():
    out = subprocess.run([*ADB, "shell", "dumpsys SurfaceFlinger --list"], capture_output=True, text=True).stdout
    m = re.search(r"(SurfaceView\[com\.OneGlitch\.INTTI[^\]]*\]\(BLAST\)#\d+)", out)
    return m.group(1) if m else None


def fps_start():
    subprocess.run([*ADB, "shell", "dumpsys SurfaceFlinger --timestats -enable -clear"], capture_output=True)


def fps(layer):
    """Average FPS of the game's surface since fps_start() (SurfaceFlinger timestats)."""
    out = subprocess.run([*ADB, "shell", "dumpsys SurfaceFlinger --timestats -dump"],
                         capture_output=True, text=True).stdout
    i = out.find(layer)
    m = re.search(r"averageFPS = ([\d.]+)", out[i:]) if i >= 0 else None
    return float(m.group(1)) if m else None


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 20
    g = Game()
    owned, _, _ = state(g.clk)
    _, dps, dpk = income(owned, 0)
    layer = unity_layer()
    print(f"DPS {dps}, DPK {dpk}, layer: {layer}")
    g.click_tin(2)  # warm up
    b0 = g.clk.bank(); t0 = time.time(); gt = g.gold_taps
    fps_start()
    sent = g.click_tin(secs)
    f = fps(layer) if layer else None
    t1 = time.time(); b1 = g.clk.bank()
    counted = (b1 - b0 - dps * (t1 - t0)) / dpk
    print(f"sent {sent / secs:5.1f}/s, counted {counted / secs:5.1f}/s, game {f or 0:.0f} fps, "
          f"gold taps {g.gold_taps - gt}", flush=True)


if __name__ == "__main__":
    main()
