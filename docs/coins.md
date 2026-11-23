# Coins (kolikot)

INTTI's own currency (the counter top-right in the app). Worked out from the game's code (v1.12.0: `CoinManager` and the minigames, disassembled from libil2cpp via the MethodInfos found by name); the rates are from the code, not measured. To measure: the save's `total_coins` (coins earned in all) over a run; every `python -m inttibot` command logs its change and the rate per minute at the end. **Farming: Denssiklikkeri** (`python -m inttibot denssi --resets N`), ~6 coins/min.

## The interval coin (`CoinManager`)
One timer shared by all minigames; every in-game coin is worth 1.
- `coinTimeCounter` counts down only while a minigame is active (`gameActive`).
- When it's at 0, the next `CanGiveIntervalCoin()` a game makes says yes. With chance `min(0.17 × 1.5 × (n+1), 0.45)` (n = coins already given in this window: 0.255, then 0.45) the window stays open for another coin; otherwise the timer restarts at `random(7, 17) s × the open game's MiniGame.coinTimeFactor` and the next 2–3 checks (`coinChecksCounter`) are skipped. ≈ 1.46 coins per window.
- `coinTimeFactor`: Pakuralli 0.7, Sotilasarvopeli 1.2, Ampumarata 1.4, Denssiklikkeri 2.2 (avg 8.4 / 14.4 / 16.8 / 26.4 s).

Where each game asks:

| Game | Check | Coin |
|---|---|---|
| Pakuralli | each crate row spawned (`CarGame.Update`, ~1.1 s) | lies in the row's gap: must be driven over (`CoinHit`) |
| Sotilasarvopeli | each correct answer | given |
| Ampumarata | each hit (`ShootableHit`, after a string check not looked into) | given |
| Denssiklikkeri | every 2 s (`ClickableSpawnCheckCoroutine`), unless a golden tin is due | spawned gold, 6 s to tap it (`clickableLingerTime`); missed = lost |

## Other sources
- **Denssiklikkeri reward meter** (the yellow bar): each counted tap adds `rewardAddBaseValue` 0.004; at 1 it pays 1 coin and empties: 250 taps a coin. It only shrinks after `rewardShrinkInterval` (9999 s) without a tap.
- **Nollaus**: +80.
- **Tasks**: +14 each (`TaskManager.TryTurnInTask`); milestone rewards (`MilestoneReward.Unlock`).
- Ampumarata case duplicates (`SkinCase.GenerateCoinAmount`), trivia, gifts, promo codes, rewarded ads, `SlotMachine.Payout` (hidden game).

## Rates
| Game | Coins/min (code) | Notes |
|---|---|---|
| **Denssiklikkeri** | ~6 now, ~6.8 at most | meter: 3.6 at the 15 taps/s cap, ~3.0 at the bot's 12–13.5; interval gold ~3.2, fixed by the timer |
| Pakuralli | ~9 if every coin is taken | the planner doesn't go for coins; crashes and the start screen cost time |
| Sotilasarvopeli | ~5.5 | rounds don't end while the bot answers |
| Ampumarata | < 5 | time between runs |
| Tasks | ~0.2 | |

Pausing the tin to tap gold costs ~0.5–1 s (6–12 taps, 0.03–0.05 coins of meter) for 1 coin: always worth it.
