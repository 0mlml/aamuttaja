"""Simulate a Denssiklikkeri run to Nollaus to compare buying strategies.

Usage: python denssi_sim.py [taps_per_s]
"""
import sys

from inttibot.games.denssi_data import NOLLAUS_PRICE, UPGRADES, best_buy, gain, income, price


def simulate(taps_per_s, owned=None, bank=0.0, strategy="payback", verbose=False):
    owned = list(owned or [0] * len(UPGRADES))
    t = 0.0
    while True:
        rate, _, _ = income(owned, taps_per_s)
        # Is it faster to save for Nollaus directly than to buy anything else?
        t_nollaus = max(0.0, (NOLLAUS_PRICE - bank) / rate)
        if strategy == "payback":
            i = best_buy(owned, bank, taps_per_s)
        else:  # "ratio": best gain/price, ignoring wait time
            i = max(range(len(UPGRADES)), key=lambda k: gain(k, taps_per_s) / price(k, owned[k]))
        p = price(i, owned[i])
        wait = max(0.0, (p - bank) / rate)
        # Buying i only helps if it pays for itself before we'd reach Nollaus anyway.
        new_rate = rate + gain(i, taps_per_s)
        t_after = wait + max(0.0, (NOLLAUS_PRICE - (bank + rate * wait - p)) / new_rate)
        if t_after >= t_nollaus:
            return t + t_nollaus, owned
        t += wait
        bank += rate * wait - p
        owned[i] += 1
        if verbose:
            print(f"{t/3600:7.2f} h  buy {UPGRADES[i][0]:8s} #{owned[i]:<3d} for {p:.3g}  -> {new_rate:.3g}/s")


if __name__ == "__main__":
    tps = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
    for strat in ("payback", "ratio"):
        total, owned = simulate(tps, strategy=strat)
        print(f"{strat:8s}: Nollaus after {total/3600:.1f} h of play at {tps} taps/s")
    total, owned = simulate(tps)
    print("Final owned:", {UPGRADES[i][0]: n for i, n in enumerate(owned) if n})
