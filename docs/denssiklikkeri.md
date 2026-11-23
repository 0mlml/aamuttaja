# Denssiklikkeri

Clicker minigame in INTTI (v1.12.0). Path: home screen → side menu → **Pelit** → **denssiklikkeri**. Bot: `inttibot/games/denssi.py` (`python -m inttibot denssi`).

## Economy
- **DPS** = passive denssiä per second, **DPK** = denssiä per tap ("Denssiä Per Klikkaus").
- DPS = the sum over helpers of owned × amount, with no hidden multipliers. DPK = 1 + the sum over DPK items.
- **Price growth ×1.09 per purchase**: price = floor(base × 1.09^owned). Items gained for free (task rewards) don't raise the price, so a card's price can be lower than its count suggests; the bot reads the card's own price.
- **Tap cap:** each counted tap adds 1/15 to `clickAccumulator`, which drains 1.0/s, and a tap counts only while it's under 0.5: 15 taps/s sustained, a burst of ~7. Multitouch doesn't help (several fingers count as one click).
- **Golden tins** (boosters): `timeUntilBooster` counts down from 40 s at the start, then 160–250 s (`min/maxBoosterInterval`). Tapping one gives **5× all denssi income** for 14 s (`boostLength`).
- **Gold coins** spawn too; a coin is worth 1 kolikko. Tins and coins must be tapped within 6 s (`clickableLingerTime`).
- **Yellow bar:** the coin reward meter, +0.004 per counted tap, 1 coin when full (250 taps). See [coins.md](coins.md).
- **No offline progress**: the game has to stay open.
- **Nollaus** (the last card): price 10¹⁶. "Läpäise peli (+80 kolikkoa)": it finishes the game for +80 coins and starts over; it gives no permanent bonus.

## Upgrades (31 + Nollaus)
Base price = price at 0 owned. The table is in `inttibot/games/denssi_data.py`.

| # | Name | Effect | Base price |
|---|---|---|---|
| 1 | Antti | +3 DPS | 940 |
| 2 | Jere | +5 DPS | 1 352 |
| 3 | ES | +1 DPK | 1 490 |
| 4 | Arto | +15 DPS | 5 235 |
| 5 | Megis | +8 DPK | 14 560 |
| 6 | Veeti | +60 DPS | 23 460 |
| 7 | Nokko | +35 DPK | 76 300 |
| 8 | Onni | +300 DPS | 129 900 |
| 9 | Otus | +160 DPK | 406 400 |
| 10 | Juhani | +1 000 DPS | 475 000 |
| 11 | Sonni | +550 DPK | 1 595 000 |
| 12 | Mikko | +4 500 DPS | 2 326 500 |
| 13 | Aatami | +18 000 DPS | 10 062 000 |
| 14 | Lonkero | +8 500 DPK | 27 710 000 |
| 15 | Kalevi | +90 000 DPS | 54 090 000 |
| 16 | Bisse | +57 000 DPK | 206 340 000 |
| 17 | Jani | +400 000 DPS | 257 200 000 |
| 18 | Kimmo | +1 500 000 DPS | 1 027 500 000 |
| 19 | Salmari | +750 000 DPK | 2 985 000 000 |
| 20 | Pertti | +6 000 000 DPS | 4 362 000 000 |
| 21 | Kalle | +30 000 000 DPS | 23 070 000 000 |
| 22 | Gee | +12 000 000 DPK | 52 080 000 000 |
| 23 | Risto | +150 000 000 DPS | 121 650 000 000 |
| 24 | Kossu | +100 000 000 DPK | 470 000 000 000 |
| 25 | Eero | +1 000 000 000 DPS | 853 000 000 000 |
| 26 | Jekku | +600 000 000 DPK | 3 036 000 000 000 |
| 27 | Heikki | +5 000 000 000 DPS | 4 475 000 000 000 |
| 28 | Viski | +2 000 000 000 DPK | 10 840 000 000 000 |
| 29 | Niilo | +25 000 000 000 DPS | 23 425 000 000 000 |
| 30 | Erkki | +150 000 000 000 DPS | 146 850 000 000 000 |
| 31 | Jallu | +50 000 000 000 DPK | 289 000 000 000 000 |
| — | **Nollaus** | finish the game, +80 kolikkoa | 10 000 000 000 000 000 |

## Strategy (`tools/denssi_sim.py`)
- At tap rate *r*, a DPK item is worth *r* × its amount per second, so DPK items are strong.
- Greedy rule: **time until affordable + payback time (cost ÷ gain), lowest wins** → Nollaus after ~3.9 h at 12 taps/s, ~3.2 h at 15 taps/s. Buying the best gain per price instead takes 5.7–7.1 h: the time spent saving up matters.
- Near the end, stop buying when an upgrade wouldn't pay for itself before Nollaus, and save up.

## The bot
`ClickerGame` (via `MiniGameManager.clickerGame`, see [memreader.md](memreader.md)):
- **Bank**: `densCount`, a C# `decimal` (16 bytes: flags with the scale in bits 16–23 and the sign in bit 31, then the 96-bit integer). `maxValue` is 10²⁷.
- **Cards**: `itemUIBoxes`, a `Dictionary<item, ClickerGameItemUIBox>`. Item: `itemName`, `itemId`, `power`. Box: `ownedCountText` ("X12"), `priceText` ("1 325"), `powerText`. These are the game's own strings, so counts and prices are exact, including Nollaus's count of resets. The bot keeps no state of its own.
- **Positions**: the cards and the gold are on the main canvas: screen x = 269.4 + 133.1 × world x, y = 734.5 − 133.1 × world y (at 540×1200). A card is brought on screen by one drag of the right length, tapped at y 1050, and the purchase is confirmed by the card's count going up.
- **Gold**: `activeClickables`, GameObjects (golden tins, coins) mapped like the cards. Each has a `ClickerGameClickable` (`type` 0 coin, 1 golden tin; `clicked`; `clickable`), found by a scan for the class (pooled, so cached). A collected one stays listed until its 6 s are up, so `clicked` is the only sign a tap took.
- **Tapping**: 35 ms down / 35 ms up, under the 15/s cap. A gold tap gets 0.15 s of quiet on each side and a 0.08 s hold (at a low frame rate, touches 35 ms apart fall in one frame), and is retried until `clicked`.
- **Deciding**: `choose()` with `denssi_data.best_buy`'s payback rule; Nollaus once no upgrade would pay for itself first.
- **Frozen game**: the bank unchanged for 20 s while tapping → restart INTTI and go back.
