# Ampumarata

Shooting range in INTTI. Path: Pelit → **Ampumarata**. Bot: `inttibot/games/ampumarata.py` (`python -m inttibot ampumarata`): every challenge is played from the game's memory ([memreader.md](memreader.md)). Positions in px at 540×1200.

## Challenges (23)

The challenge menu pages through them with arrows; the shooter's level (XP from playing) unlocks them.

| Type | # (weapon) | Unlocks at level |
|---|---|---|
| Paper target, N shots ("N laukausta tauluun") | 3 (RK 62, 10), 4 (P 80, 10), 5 (TKIV 2000, 8), 11 (RK 62, 20), 12 (P 80, 20), 13 (TKIV, 15) | 11–13: 12 |
| Melonintuhonta (watermelons) | 1 (RK 62), 6 (P 80), 16 (RK 62) | 6: 4, 16: 18 |
| Tölkinkaato (cans) | 2 (P 80), 7 (RK 62), 17 (P 80), 18 (TKIV) | 7: 4, 17/18: 18 |
| Omenantuhonta (apples) | 8, 23 (TKIV) | 8: 4, 23: 22 |
| Jaster-pellit (steel plates) | 9, 19 (RK 62), 10, 20 (P 80) | 8, 20 |
| Lännen nopein (bottles, quick draw) | 14, 21 (P 80), 15, 22 (RK 62) | 15, 22 |

Medal limits per challenge, e.g. P 80 10 shots: 65/80/90; RK 62: 60/75/85; TKIV 8 shots: 60/70/75; melons #2: 11/14/16 of 16.

## Controls
- **Holding a finger** brings the sights up; **dragging** moves the aim. Plain taps don't fire.
- **A second finger** on the "Laukaus" bar (270, 662) fires (the injector's add-finger command).
- **Reload:** the button at (241, 1011), tapped with a second finger while aiming. A challenge starts with an empty gun. Magazines: P 80 9–10 + 1, RK 62 10 + 1, TKIV 4 + 1.
- **Recoil** shifts the aim for good, and **a new press keeps the gun's last direction** (it doesn't re-centre).

## Finding things in memory
INTTI is Unity 6000.4.8f1, IL2CPP; [memreader.md](memreader.md) covers classes, fields and Unity transforms. `ShooterGame.INSTANCE` holds the challenge (`loadedScenario`), the weapon and the crosshair state.

**The view.** The unaimed camera is a centred pinhole with f = 2594.6 px (26° vertical), at `weaponCamera`'s pose (rms 0.9 px against cans). The aimed view is that view zoomed and shifted by the crosshair, `ShooterGame.crosshairEffectivePos`. The camera transforms themselves don't move.

## Aiming
`aim_world`, modelled on the game's own crosshair code (`ShooterGame.CrosshairPosUpdate`, disassembled):
- **The model, per frame (~16 ms):** `crosshairGoalInputPos` += the aim finger's move × 0.1296 per px (y flipped), clamped to a magnitude of 25 (`crosshairMaxInputMagnitude`); `crosshairInputPos` follows the goal (`Vector2.SmoothDamp`, 0.03 s); `crosshairEffectivePos` = `crosshairBasePos` + input + aim sway + recoil sway. Aim sway: `(PerlinNoise(t·0.32 + seed) − 0.5) × 1.7 × aimSwayFactor × Weapon.aimSwayFactor` per axis (TKIV 0.9): ±0.6 units, 0.5–0.9 units/s. A shot kicks the goal (a random jump, `crosshairJumpAtShotMagnitude` 3.5 × `Weapon.shotKickFactor`) and sets `shootSwayFactor` (a faster Perlin term that fades over `shootSwayRecoveryTime`, 0.6 s).
- **The shot:** `Physics.Raycast` from `targetCamera`, which sits on the line from the camera pivot (the unaimed camera's position) through `crosshairWorldObject`, so the unaimed-view projection is exact. It's taken in the frame that handles the fire touch, 63–68 ms after the command. A fire touch is dropped while `shotIntervalCounter` > 0 (`Weapon.shotInterval`: the TKIV's 1 s) or `aimCounter` < `minAimTimeToShoot` (0.2 s).
- **What the bot reads:** all of the above, in one read per poll (every ~3 ms). The sway is effective − base − input, sampled once per frame on the game's `aimCounter` clock; a quadratic through the last 0.15 s predicts it 60 ms ahead to ~0.01 units. Effective → projected px is a fitted scale per axis (~3.16 for the TKIV), from (effective, crosshair projection) pairs read within one frame.
- **Steering:** one finger move puts the goal where the target will be, less the sway predicted 0.1 s ahead; then nothing until the goal reaches the expected value (or stops short, at a clamp) and the input has settled. A target needing a goal past 25 is out of reach and skipped. The finger → goal gain isn't learned from the first goal change after a move: a split move lands over several frames.
- **Firing:** when base + goal + the sway predicted for the shot's frame is within the fire window (a third of the target's width), the recoil sway is gone and the game will take a shot. A shot counts once `statShotsFired` moves.
- **Recoil:** after a shot the recoil sway is fast noise: it's kept out of the sway history, the last clean value is held, and only coarse moves (undoing the kick, which really moves the goal) are made until it's gone.
- **Big moves** go in steps of 40 finger px, a frame apart: the game takes at most 130 normalized px (~70 finger px) of a finger's move per frame.
- **Re-pressing:** if a move changes nothing (the sights drop between waves) or would take the finger off the screen, the bot presses again. A press resets the goal (near 0, `crosshairStartPosVarianceMagnitude` 3), so it costs a re-aim.

## Targets
`Scenario.shootableTargets` (`ShootableCan`, `Shootable` for melons, apples and bottles) and `Scenario.jasters` (plates); neither means paper.
- **Paper:** the marked target is the `ShootingTarget` nearest the objective arrow (`ShooterGame.activeObjectiveArrows`). The target's transform is its stand's pivot; its child points (the score rings' marks) sit in the paper's plane at the bullseye's height, 0.738 above the pivot on the large target. The fire window is a third of the 10 ring (radius ~0.15).
- **Cans:** one hit destroys a can (`alive` false); the others count once they touch the ground (`hitGround`). A destroyed can's blast (`deathForceRadius` 0.5, force 90) throws its neighbours off, so the bot picks cans with ≥2 resting neighbours, lowest row first, and skips moving ones (positions read twice, 80 ms apart). The pivot is the can's base, so it aims 0.2 up its axis. A shot that destroys nothing was blocked (a can lying in front, a fragment): aim higher next time; after two such misses, shoot other cans first.
- **Melons and apples** must be destroyed, not knocked down: the highest first. A melon knocked off a box rolls away, out of reach.
- **Plates:** the transform is the hinge, and a plate swings up over `plateMoveTime`; aim at its centre once up (hinge + 1.5 world units straight up), and wait between waves in the middle of the plates. One shot starts the first wave. Between waves the game holds the timer until you reload (`allowReloadAboveZeroAmmo`), so the bot reloads at once; a hit plate counts as up while it falls, so it's skipped for 1 s.
- **Bottles (Lännen nopein):** the generic loop, ~1 s per bottle.

**Running a challenge.** `Scenario.state`: 0 the menu, 2 running, 3 the result. Ammo from `Weapon.currentMag`/`extraMags`.

## Results

| Challenge | Score (gold limit) |
|---|---|
| Paper #3, #4, #5 (10/10/8 shots) | 98/100 (85), 100/100 (90), 79/80 (75) |
| Paper #11, #12, #13 (20/20/15 shots) | 199/200 (175), 196/200 (180), 150/150 (140) |
| Tölkinkaato #1–#4 | 32/33 (32), 34/34, 35/35 (34), 26/26 (25) |
| Melonintuhonta #1–#3 | 14/14, 16/16, 18/18 |
| Omenantuhonta #1, #2 | 8/8, 10/10 |
| Jaster-pellit #1 (RK 62, P 80), #2 (RK 62, P 80) | 9/9, 9/9, 12/12, 12/12 |
| Lännen nopein #1–#4 | 9.17 s (14.0), 9.13 s (15.0), 10.59 s (15.0), 12.59 s (19.0) |

## Arsenaali: cases, odds, skins (from the game's code)

The bot: `python -m inttibot arsenaali open|scrap|all` (`inttibot/games/arsenaali.py`), all state from memory and the save.

**Skins** (`WeaponSkinSelector.skinDict`: weapon id → `WeaponSkin` list in the carousel's order; `WeaponSkin`: `id`, `weaponId`, `skinCase`, `rarity` 0 default, 1 common, 2 rare, 3 epic). 17 for the RK 62, 15 for the P 80, 7 for the TKIV 2000; each non-default skin belongs to one case type (`skin_case_1`, `skin_case_2`, `skin_case_alfa`, `skin_case_bravo`). Copies are in the save: `shooter_game_skin_unlock_count_<weapon>_<skin>`; cases owned `shooter_game_<case>_owned_count`.

**Opening** (`<CaseOpenCoroutine>` → `SkinCase.GenerateResult`):
1. **Rarity** (`RollForRarity`), one `Random.Range(0, 1)`: common if ≤ 0.922 − d, rare up to 0.07 + d × 0.07/0.078 more, else epic (0.008 + d × 0.008/0.078). d = min(0.02 × commons in a row, 0.922) (`GetCommonProbabilityDiminish`, `commonDiminishConstant` 0.02): each common in a row moves 2 points from common to rare (~1.79) and epic (~0.21). The counter is per case type, in the save as `shooter_game_case_commons_in_a_row_ <case>` (with the space); a common adds one, a rare or epic resets it. A rarity the case has no skins of is rolled again (up to 200 times).
2. **Skin:** uniform among the case's skins of that rarity, owned or not. Except an epic: with `newEpicUnlockForceProbability` 0.2 it's picked among the case's epics with no copies (if any). So duplicates are the rule.
3. **Coins** (`GenerateCoinAmount`), every case: 8% each 3, 4, 5; 3% 10; 3% 15; otherwise none. ~1.7 coins a case.

Base odds: common 92.2%, rare 7%, epic 0.8%. E.g. 4 commons in a row: 84.2 / 14.2 / 1.6%. The result can't be predicted: it's `UnityEngine.Random` (native state), not anything in the managed heap.

**Scrapping** (`TryWeaponScrap`): a skin's copies less `skinMinOwnCount` (1) against its rarity's threshold (`GetWeaponSkinRarityScrapThreshold`: common 5, rare 2, epic 1; default skins never) give one case of the type chosen in the strip; the threshold's copies go. The bot plans from the save and visits only the skins that qualify. It always chooses the strip's first case type; the better choice would be the type with the most commons in a row (the best rare/epic odds) and the most unowned rares and epics.

**Where cases come from:** challenge rewards (`shooter_game_cases_granted_total_from_challenges`), scrapping, level-ups, and Ampumarata's timed gift (`<CollectGiftCoroutine>` → `GrantRandomSkinCaseWithUnownedSkins`: a case type that still has unowned skins).

**Challenge rewards** (`ShooterGame.ReportScenarioFinishGeneric`, called with the medal the run's score earned):
- **The case roll:** a main challenge (`difficulty` ≠ 0) finished with a medal rolls `Random.Range(0, 1)` ≤ its chance / 100 for a case. No medal, no roll.
- **The chance** (`Scenario.GetExtraRewardChance`): the save's `shooter_game_scenario_extra_reward_chance_<id>`, or `extraRewardFirstChance` 60 if it's unset, clamped to `extraRewardBaseChance` 20 … `extraRewardMaxChance` 80. A won roll resets it to 20 (`ResetExtraRewardChance`).
- **Raising chances:** every `medalResultsForRewardChanceAdd` (3) medal runs, on any challenge (counter `shooter_game_medal_results_for_reward_chance_add`), `IncreaseScenarioExtraRewardChances` adds `extraRewardChanceAdd` 20 (up to 80) to the next 5 unlocked main challenges, round-robin from `shooter_game_scenario_reward_chance_increases_start_index`. Which challenges are next is predictable.
- **Level-ups:** each shooter level gained gives a case, and every 10th level another (`shooter_level_current_level`).
- **The bot** (`--auto`, and the tasks' case task) plays the unlocked challenge with the most chance per second: chance / (run time + getting there: 6 s to restart the same one, else 9 s + 0.6 s per menu arrow). Run times start from defaults (bottles 15 s, 10-shot paper 17 s, … plates 44 s) and are replaced by the session's own runs. `--chances` lists them. Runs go through `farm()`: it opens Ampumarata if needed, and when a run fires no shots it checks logcat for a crash loop (`device.crash_looping`), restarts the app, reopens Ampumarata and goes on; a lost reload tap is retried.
