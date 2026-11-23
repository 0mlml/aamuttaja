# Daily tasks (Tehtävät)

INTTI hands out tasks for its minigames: Pelit → **Tehtävät**, below the game list. Each task pays coins (+14) and milestone points: a bar of 12 at the bottom unlocks a weapon skin. New tasks come every few hours ("uudet tehtävät" timer); the red ✕ drops a task. Runner: `python -m inttibot tasks run` (`inttibot/tasks.py`); listing: `python -m inttibot tasks`.

## In memory

All read with `inttibot.mem` ([memreader.md](memreader.md)):

`TaskManager.INSTANCE`:
- `taskInstances`: `TaskInstance[]`, up to `SLOT_COUNT` slots (null = empty)
- `taskDatas`: `Dictionary<?, List<TaskData>>`, the task types per game
- `milestoneThresholds` ([8, 12]), `startMilestoneLevel`
- static `taskBaseCompletionMinutesRequirement` = 5

`TaskInstance`: `myTaskData`, `taskScale` (enum `TaskScale`), `startProgress`, `completionThreshold`, `lastDisplayedProgress`, `turnedIn`.

`TaskData`: `id`, `prefKey` (the PlayerPrefs counter it watches), `gameId`, `avgProgressInMinute`, `completionRequirementFactor`.

- **Progress** = `lastDisplayedProgress − startProgress`, in the counter's own units. `lastDisplayedProgress` only moves when the game shows the task in full: the Tehtävät panel, Pakuralli's results. Inside Denssiklikkeri and Sotilasarvopeli it stays put while the corner quick view counts up.
- **The quick view** (the task chip on a minigame's right edge): `TaskQuickViews.INSTANCE.items`, `TaskQuickItem`s with `myInstance` (the `TaskInstance`) and `currentDisplayProgress` (progress, animated). `Tasks.read()` takes the larger of the two. Ampumarata's quick view is set when the game opens and doesn't move between runs: its progress is only seen back in Pelit.
- **Target** = `TaskInstance.GetEffectiveCompletionThreshold() − startProgress` = `round((completionThreshold / 10 − startProgress) × factor)`, rounded half to even. `completionThreshold` is set at grant (`CalculateCompletionThreshold`) to `10 × (startProgress + avgProgressInMinute × completionRequirementFactor × 5)`. `taskScale` is an enum, `TaskScale { Small, Big1 }`, and `TaskManager.GetTaskCompletionThresholdFactor` maps it to the factor: Small (0) → 0.75, Big1 (1) → 1.0, 2 → 1.5. So Big1 is `avgProgressInMinute × 5` (e.g. 40 × 5 = 200 points) and Small is ¾ of that (2500 clicks → 1875). Read from the disassembled methods (libil2cpp, via the MethodInfo found by name).

## The task types (v1.12.0)

| id | Counter (`prefKey`) | Target (Big1; Small is ¾) | How the runner does it |
|---|---|---|---|
| `car_game_total_score` | `car_game_scoretotal` | 200 | Pakuralli runs |
| `quiz_game_total_score` | `quiz_game_correctcount` | 50 | Sotilasarvopeli, Koulutus: the bot never misses, so a round only ends when it stops answering (`until` = what's left; the timer then ends it and the count is saved) |
| `shooter_game_hit_shootables_rk62` | `shooter_game_shootables_hit_weapon_rk62` | 75 | Melonintuhonta #3 (18 hits a run) |
| `shooter_game_hit_shootables_pistooli80` | `..._pistooli80` | 75 | Tölkinkaato #3 |
| `shooter_game_hit_shootables_tkiv2000` | `..._tkiv2000` | 60 | Omenantuhonta #2 (10 hits) |
| `shooter_game_earn_skin_cases` | `shooter_game_cases_granted_total_from_challenges` | 8 | `ampumarata.farm(auto)`: each run the challenge with the best case chance per second (docs/ampumarata.md); level-up cases count too |
| `clicker_game_clicks` | `clicker_game_total_clicks_dec` | 2500 | Denssiklikkeri tapping |
| `clicker_game_golden_disks` | `clicker_game_boosters_used` | 3 | Denssiklikkeri tapping; golden tins (boosters) spawn every 160–250 s: ~10 min |

Two slots can hold the same task; they count the same counter. These 8 are all of `TaskManager.taskDatas` (a dictionary of `List<TaskData>` per minigame).

**Ampumarata** tasks: the runner plays the runs the rest needs (`SHOOTER_PICK`: the challenge and what one run counts at the least), then goes to Pelit to read the progress, and plays more if it's short. Inside Ampumarata the progress doesn't update between runs.

## When new tasks come
`TaskGranter.INSTANCE.timeUntilNextGrant` (a `TimeSpan`: 100 ns ticks) counts down to the next batch; `grantIntervalDefault` is 4 h. Collected slots stay empty ("Tyhjä") until then. `python -m inttibot tasks` prints it.

## Collecting
A finished task shows a check mark; **tapping its card** pays the coins and a milestone point, and empties the slot ("Tyhjä", with a timer until a new task; a video ad would fill it at once: the bot doesn't). In memory the slot's instance goes. Cards: slot i at y = 797 + 83 i. `python -m inttibot tasks collect`; `tasks run` collects at the end.

## Getting around
The runner moves by the app's state in memory ([memreader.md](memreader.md#where-the-app-is-inttibotmemui)): which minigame is open, which screen is up. Taps: the side menu (42, 262) → Pelit (113, 344); in Pelit the games at (270, 385) Ampumarata, (270, 488) Pakuralli, (270, 578) Sotilasarvopeli, (270, 665) Denssiklikkeri; a minigame's ✕ at (503, 157). Ampumarata's challenge is paged to by `ShooterGame.selectedScenario`'s index in `allScenarios` (the carousel wraps).
