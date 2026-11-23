"""Denssiklikkeri upgrade table (read from the game, v1.12.0, 2026-11-17).

price(n owned) = floor(base * GROWTH ** n). Bases for Antti/Jere/ES were
derived from prices seen at 2 owned (1116, 1606, 1770) and confirmed by one
Antti purchase (1116 -> 1217); the rest are the prices shown at 0 owned.
"""
import math

GROWTH = 1.09
NOLLAUS_PRICE = 10**16  # "Nollaus – Läpäise peli (+80 kolikkoa)"
BASE_DPK = 1            # denssiä per tap with nothing bought

# (name, kind, amount, base price)
UPGRADES = [
    ("Antti",   "DPS", 3,               940),
    ("Jere",    "DPS", 5,               1_352),
    ("ES",      "DPK", 1,               1_490),
    ("Arto",    "DPS", 15,              5_235),
    ("Megis",   "DPK", 8,               14_560),
    ("Veeti",   "DPS", 60,              23_460),
    ("Nokko",   "DPK", 35,              76_300),
    ("Onni",    "DPS", 300,             129_900),
    ("Otus",    "DPK", 160,             406_400),
    ("Juhani",  "DPS", 1_000,           475_000),
    ("Sonni",   "DPK", 550,             1_595_000),
    ("Mikko",   "DPS", 4_500,           2_326_500),
    ("Aatami",  "DPS", 18_000,          10_062_000),
    ("Lonkero", "DPK", 8_500,           27_710_000),
    ("Kalevi",  "DPS", 90_000,          54_090_000),
    ("Bisse",   "DPK", 57_000,          206_340_000),
    ("Jani",    "DPS", 400_000,         257_200_000),
    ("Kimmo",   "DPS", 1_500_000,       1_027_500_000),
    ("Salmari", "DPK", 750_000,         2_985_000_000),
    ("Pertti",  "DPS", 6_000_000,       4_362_000_000),
    ("Kalle",   "DPS", 30_000_000,      23_070_000_000),
    ("Gee",     "DPK", 12_000_000,      52_080_000_000),
    ("Risto",   "DPS", 150_000_000,     121_650_000_000),
    ("Kossu",   "DPK", 100_000_000,     470_000_000_000),
    ("Eero",    "DPS", 1_000_000_000,   853_000_000_000),
    ("Jekku",   "DPK", 600_000_000,     3_036_000_000_000),
    ("Heikki",  "DPS", 5_000_000_000,   4_475_000_000_000),
    ("Viski",   "DPK", 2_000_000_000,   10_840_000_000_000),
    ("Niilo",   "DPS", 25_000_000_000,  23_425_000_000_000),
    ("Erkki",   "DPS", 150_000_000_000, 146_850_000_000_000),
    ("Jallu",   "DPK", 50_000_000_000,  289_000_000_000_000),
]
INDEX = {name: i for i, (name, *_) in enumerate(UPGRADES)}


def price(i, owned):
    return math.floor(UPGRADES[i][3] * GROWTH ** owned)


def income(owned, taps_per_s):
    """Denssiä per second for an owned-count list."""
    dps = sum(n * amt for n, (_, kind, amt, _) in zip(owned, UPGRADES) if kind == "DPS")
    dpk = BASE_DPK + sum(n * amt for n, (_, kind, amt, _) in zip(owned, UPGRADES) if kind == "DPK")
    return dps + dpk * taps_per_s, dps, dpk


def gain(i, taps_per_s):
    _, kind, amt, _ = UPGRADES[i]
    return amt * (taps_per_s if kind == "DPK" else 1)


def best_buy(owned, bank, taps_per_s, prices=None):
    """Pick the upgrade that minimises (time until affordable + payback time).

    This is the usual idle-game greedy rule: it prefers efficient upgrades but
    won't save for ages for something marginally better. `prices` (current card
    prices) overrides the price model where the game's prices differ from it.
    """
    rate, _, _ = income(owned, taps_per_s)
    best, best_score = None, math.inf
    for i in range(len(UPGRADES)):
        p = prices[i] if prices else price(i, owned[i])
        wait = max(0.0, (p - bank) / rate)
        score = wait + p / gain(i, taps_per_s)
        if score < best_score:
            best, best_score = i, score
    return best
