# Reading INTTI's memory

Every bot reads INTTI's game state straight from its memory: read-only, nothing is injected into or written to the game. Code: `native/memreader/inttimem.c` (the privileged part) and `inttibot/mem/` (everything else: `reader` speaks to the helper, `il2cpp` finds classes, fields and transforms, `ui`, `shooter` and `tasks` read particular parts of the game).

## Access: the `inttimem` helper

The game runs as another uid inside Waydroid's container, and its app isn't debuggable: without privileges, `/proc/<pid>/maps` and `mem` are denied, and `run-as` fails. The container is a privileged LXC sharing the host's uids (`uid_map` is `0 0 4294967295`), so a host process with `CAP_SYS_PTRACE` can read the game directly. No Android-side root and no frida needed.

`native/memreader/inttimem.c` is a ~90-line reader that gets exactly that capability and nothing more:
- It finds the game itself (the process whose `cmdline` is `com.OneGlitch.INTTI`); no pid can be passed in, so it can't be pointed at anything else.
- It only reads: `process_vm_readv` and `/proc/<pid>/maps`.
- Installed root-owned and not writable by the user, so the bot can't change what runs with the capability:
  ```sh
  gcc -O2 -Wall -o native/memreader/inttimem native/memreader/inttimem.c
  sudo install -o root -g root -m 755 native/memreader/inttimem /usr/local/bin/inttimem
  sudo setcap cap_sys_ptrace+ep /usr/local/bin/inttimem
  /usr/sbin/getcap /usr/local/bin/inttimem    # cap_sys_ptrace=ep
  ```
  Reinstall after changing the source. Without the capability it still finds the pid but reads nothing (empty maps).

Protocol, one command per line on stdin (`inttibot.mem.Mem` speaks it):

| Command | Reply |
|---|---|
| `P` | the pid, as a line |
| `M` | the process's maps, then a line `END` |
| `R <hexaddr> <n>` | a 4-byte little-endian count, then that many bytes (0 if unreadable); n ≤ 64 MiB |

A read is ~0.1 ms; scanning all ~1.7 GB of writable memory for a pointer takes ~2 s.

## The game: Unity IL2CPP

INTTI (v1.12.0) is Unity 6000.4.8f1 with the IL2CPP backend. `libil2cpp.so` is arm64, run through libhoudini's translation; translated code shares the process's 64-bit address space, so heap objects and pointers read as they are. `global-metadata.dat` is plain (magic `0xFAB11BAF`, version 39), mapped from `/storage/emulated/0/Android/data/com.OneGlitch.INTTI/files/il2cpp/Metadata/`. Names can be listed offline from the APK's copy (`assets/bin/Data/Managed/Metadata/global-metadata.dat`).

### Finding a class
An `Il2CppClass`'s name pointer (+0x10) points into the mapped metadata. To find class `X`: find `\0X\0` in the metadata, scan writable memory for a pointer to it, and keep the hit whose struct's image (+0x0) names `Assembly-CSharp.dll` (other hits are other structs naming the same string). `Game.find_class(name)` does this (~2 s, cached per run).

### Il2CppClass (this build)

| Offset | Field |
|---|---|
| +0x00 | image (→ name: the assembly, e.g. `Assembly-CSharp.dll`) |
| +0x10 | name |
| +0x58 | parent class |
| +0x80 | fields: array of `FieldInfo` (0x20 each: name, type, parent class, int32 offset); it ends where `parent` stops being the class |
| +0xB8 | static fields (a singleton's `INSTANCE` is the first) |

Offsets of instance fields include the 0x10 object header. An object's first word is its class. `inttibot.mem.Game` gives fields by name (`field(obj, name, kind)`, `all_fields(klass)` including parents), `List<T>` items (`_items` at +0x10, `_size` at +0x18, array data from +0x20) and arrays (length at +0x18, data from +0x20).

### Static or instance, and a field's type
`FieldInfo.type` points at an `Il2CppType`; its 32-bit word at +8 holds `attrs` (low 16 bits; `0x10` = static) and the type kind (next 8 bits: `0x02` bool, `0x08` int32, `0x0c` float, `0x11` struct, `0x12` class, `0x15` generic instance, `0x1d` array). A static field's offset is into the class's static block (+0xB8), not the object: `UIManager.stackedScreens` looks like a list by its name but is an int32 count.

### Native Unity objects
A managed `UnityEngine.Object`'s +0x10 (`m_CachedPtr`) is its native object; null once destroyed.

| Native object | Offset | Field |
|---|---|---|
| Component | +0x20 | its GameObject |
| GameObject | +0x20 / +0x30 | components (16 bytes each: type, component) / count; the first is the Transform |
| GameObject | +0x46 | active (1/0) |
| GameObject | +0x50 | name (C string pointer) |
| Transform | +0x28 / +0x30 | TransformHierarchy / its index there |
| TransformHierarchy | +0x18 | local TRS, 48 bytes each: position xyz, pad, rotation xyzw, scale xyz, pad |
| TransformHierarchy | +0x20 | parent indices (int32, −1 at the root) |
| TransformHierarchy | +0x30 | the native Transforms, by index (so a subtree can be walked: children are the indices whose parent is i) |

World position and rotation are composed from the index up through the parents (`Game.world_pos`, `world_rot`). Hierarchy arrays are reallocated when objects come and go: don't cache their data addresses, resolve them on each read (it's cheap).

### Coroutines: a method's locals
A running C# coroutine is an object of a compiler-made class named `<Method>d__N`, its fields the method's locals (`<name>5__K`), `<>1__state` (−1 when done), `<>4__this`. The live one is found by scanning memory for its class pointer (`Mem.find_u64`) and checking `<>4__this`. Unity's `Coroutine` handle stored in a field is only a wrapper. The quiz's question and correct answer live in one of these ([sotilasarvopeli.md](sotilasarvopeli.md)).

## Notes and pitfalls
- A class that hasn't been used yet has no field array: `class_fields` doesn't cache an empty result; read fields when they're needed.
- A singleton's `INSTANCE` may be null until its screen opens; `MiniGameManager` holds every minigame (`carGame`, `quizGame`, `shooterGame`, `clickerGame`, ...) all along.
- Boehm GC doesn't move objects, but frees and reuses memory: re-resolve from `INSTANCE` per scenario and check an object's class pointer before trusting it.
- Reads aren't atomic against the game thread: a value can be torn mid-update. Read twice, or reject NaNs and jumps, where it matters.
- Some state lives in coroutine objects (e.g. a countdown in `<ScenarioRun>d__72`), not in the main class.
- Offsets are for this build. Field offsets are resolved by name at runtime, so a game update mostly needs the class-struct offsets above re-checked.

## Ampumarata's state (examples)
`ShooterGame` (`INSTANCE`): `loadedScenario`, `currentWeapon` (`Weapon`: `currentMag`, `magSize`), `crosshairInputPos`/`crosshairEffectivePos` (Vector2), `crosshairWorldObject` (where the sights point), `weaponCamera` (the unaimed camera's pose), `allowReloadAboveZeroAmmo`, statistics (`cansDropped`, `jastersHit`, ...). `Scenario`: `state` (2 running), `timer`, `currentRound`/`maxRound`, `score`, `shootableTargets` (`ShootableCan`/`Shootable`: `alive`, `hitGround`, `deathForceRadius`), `jasters` (`Jaster`: `plateUp`, `plate`). How the bot uses them: [ampumarata.md](ampumarata.md).

## Where the app is (`inttibot.mem.UI`)
- `MiniGameManager.INSTANCE.currentMiniGame`: the open minigame (null on INTTI's own screens); its `gameId` string is `car_game` (Pakuralli), `quiz_game` (Sotilasarvopeli), `shooter_game` (Ampumarata), `clicker_game` (Denssiklikkeri); `slotsGame` and `ballGame` exist too. `MiniGame.gameActive`/`gameOn` say whether a round is running.
- `UIManager.INSTANCE.currentActiveScreen` is one of its screen RectTransforms: `gamesScreen` (Pelit), `dateScreen`, `propSelectScreen`, `statsScreen`, `cateringListScreen`, `calendarScreen`, `socialScreen`; null on the home screen. `mainMenuEnabled`: the side menu is open.
- The daily tasks: [tasks.md](tasks.md).

## The save (`inttibot.mem.UserData`)
`UserData.data` (static, a `UserDataObject`) holds the app's whole save: `ints`, `longs`, `floats`, `strings`, each a `SerializedDictionary<string, T>` (a `Dictionary` underneath: `_entries` at +0x18, `_count` at +0x20; an entry is `int hashCode, int next, key, value`, 24 bytes; `next < -1` is free). The games read and write it through `UserData.GetInt`/`SetInt`, so it is current. `python -m inttibot userdata [filter]` prints it. In v1.12.0 (~490 ints, ~150 strings):
- **Coins:** `coins` (the balance), `total_coins` (earned in all: the difference over a run is what it earned).
- **Every task counter** (`car_game_scoretotal`, `quiz_game_correctcount`, `clicker_game_total_clicks_dec` (a string), `clicker_game_boosters_used`, `shooter_game_shootables_hit_weapon_*`, `shooter_game_cases_granted_total_from_challenges`), and `task_manager_*`/`tm_*` (milestones, tasks completed per game and scale).
- **Ampumarata:** skin copies `shooter_game_skin_unlock_count_<weapon>_<skin>`, cases owned/granted/opened per type, `shooter_game_case_commons_in_a_row_ <case>` (feeds the next case's odds), scraps done, level and XP, medal records, per-scenario records, shots and hits per weapon.
- **Denssiklikkeri:** `clicker_game_count_dec` (the bank), `clicker_game_dps`, `clicker_game_click_power` (strings), item counts, `clicker_game_reward_progress`, `clicker_game_time_until_booster` (floats), `clicker_game_game_resets`.
- **Timed gifts:** `gm_next_gift_date_time` (the app's gift, `GiftManager`, pays coins), `shooter_game_next_gift_date_time`; `gm_gifts_collected`.
- Records and play time per game (`car_game_best`, `quiz_game_best_<mode>`, `*_play_time_seconds`), unlocked props and skins, settings.

Every `python -m inttibot <command>` logs the save's ints that changed during the run at its end, coins (and per minute) first; Denssiklikkeri's minute report includes the coins earned so far.

## Hidden minigames
`MiniGameManager` also holds `slotsGame` (`SlotsGame`: a slot machine, `SlotMachine` with bets, payouts and win rows) and `ballGame` (`BallGame`: pinball-like levels with flippers, bouncers, enemies, a gun and maps; `BallGamePlayHandler`). The Pelit screen (`MiniGamesScreen/TopItemsParent/ButtonsParent`) has buttons for both, `SlotsGameButton` (with a `LockOverlay`) and `BallGameButton`, but their GameObjects are inactive in v1.12.0, so they can't be opened from the app. There's also an inactive `UnlockAllDebug` button. The bots only read memory, so they leave them alone.
