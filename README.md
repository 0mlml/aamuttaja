# aamuttaja

Bots for the minigames in the INTTI app (`com.OneGlitch.INTTI`, v1.12.0), running on Waydroid. Everything runs through one command, `python -m inttibot <command>`:

| Command | What it does |
|---|---|
| `tasks` | The daily tasks (Pelit → Tehtävät): lists them, or plays the minigames that complete them (`tasks run`) |
| `ampumarata` | Ampumarata: gold on all 23 challenges, every one played from memory (targets, the crosshair, the score) |
| `arsenaali` | Ampumarata's Arsenaali: opens every weapon case and scraps duplicate skins into new cases |
| `pakuralli` | Pakuralli: steers the van between the TNT rows, planned from the van's physics and the crates in memory |
| `sotilas` | Sotilasarvopeli, the quiz: reads each question's correct answer from memory; types the NATO word in Aakkoset |
| `denssi` | Denssiklikkeri: taps the tin and the gold, buys upgrades in the optimal order, and finishes with Nollaus |
| `userdata` | Prints INTTI's save from memory (coins, every counter, skins, cases); `userdata coin` filters the keys. Every command logs what it changed in the save |
| `cloud` | The cloud save's sync state; **`cloud close` closes INTTI so the save is uploaded** (Home, then force-stop) |

Every bot reads the game's state from INTTI's memory (read-only, see [`docs/memreader.md`](docs/memreader.md)); nothing reads the screen. Taps, swipes and typing go through a small injector (`native/injector`).

## Docs

- [`docs/waydroid.md`](docs/waydroid.md): Waydroid setup, the touch injector, running headless
- [`docs/memreader.md`](docs/memreader.md): reading the game's memory: the `inttimem` helper, IL2CPP classes and Unity transforms, the save
- [`docs/denssiklikkeri.md`](docs/denssiklikkeri.md): Denssiklikkeri's economy, upgrade table and buying strategy
- [`docs/ampumarata.md`](docs/ampumarata.md): the challenges, the game's aiming model, targets, Arsenaali cases and odds
- [`docs/pakuralli.md`](docs/pakuralli.md): the van's physics and the dynamic-programming planner
- [`docs/sotilasarvopeli.md`](docs/sotilasarvopeli.md): the quiz and where its answers live in memory
- [`docs/tasks.md`](docs/tasks.md): the daily tasks: where they live in memory, how they're counted, how each is done
- [`docs/cloudsave.md`](docs/cloudsave.md): how the cloud save syncs and how to close INTTI without losing progress
- [`docs/coins.md`](docs/coins.md): where INTTI's coins come from and each game's rate

## Setup

Linux with Waydroid; INTTI's ARM code runs through Waydroid's ARM translation. One-time, with sudo:
```sh
sudo apt install waydroid                 # Debian 13: from trixie-backports
echo 'options binder_linux devices=binder,hwbinder,vndbinder' | sudo tee /etc/modprobe.d/binder.conf
echo binder_linux | sudo tee /etc/modules-load.d/binder.conf
sudo modprobe binder_linux devices=binder,hwbinder,vndbinder
sudo waydroid init                        # plain image: INTTI is installed from apk/, no Play Store needed
sudo systemctl enable --now waydroid-container
# INTTI is ARM-only: add ARM translation (libhoudini on Intel, libndk on AMD)
git clone https://github.com/casualsnek/waydroid_script ~/waydroid_script
cd ~/waydroid_script && python3 -m venv venv && venv/bin/pip install -r requirements.txt
sudo venv/bin/python3 main.py install libhoudini && sudo systemctl restart waydroid-container
# only with ufw: let the container get an address and reach the internet
sudo ufw allow in on waydroid0 to any port 67 proto udp
sudo ufw allow in on waydroid0 to any port 53
sudo ufw route allow in on waydroid0
```

The memory reader, `/usr/local/bin/inttimem`, is a tiny read-only helper for INTTI's process only, installed root-owned with just `CAP_SYS_PTRACE` ([`docs/memreader.md`](docs/memreader.md)):
```sh
gcc -O2 -Wall -o native/memreader/inttimem native/memreader/inttimem.c
sudo install -o root -g root -m 755 native/memreader/inttimem /usr/local/bin/inttimem
sudo setcap cap_sys_ptrace+ep /usr/local/bin/inttimem
```

Python, and the one-time Android settings (INTTI's APK, a split APK, goes in `apk/`):
```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
scripts/launch-waydroid.sh                           # starts Waydroid and opens INTTI
ADB=~/Android/Sdk/platform-tools/adb; S=192.168.240.112:5555
$ADB connect $S                                      # accept the debugging prompt once (DESKTOP=1 shows the window)
$ADB -s $S shell wm size 540x1200; $ADB -s $S shell wm density 210   # the screen size the bots' positions are for
$ADB -s $S shell settings put global private_dns_mode hostname       # ad blocking
$ADB -s $S shell settings put global private_dns_specifier dns.adguard-dns.com
$ADB -s $S install-multiple apk/base.apk apk/split_config.arm64_v8a.apk
```
Then sign in to INTTI and set it up once by hand.

`scripts/launch-waydroid.sh` runs Waydroid on a headless weston (`sudo apt install weston`), which unattended runs need; `DESKTOP=1 scripts/launch-waydroid.sh` uses a desktop window instead ([`docs/waydroid.md`](docs/waydroid.md)).

The injector, `native/injector/inject.dex`, is prebuilt. Rebuild it after editing `native/injector/*.java` (javac and d8 from the Android SDK):
```sh
cd native/injector && B=$(mktemp -d) && javac --release 11 \
  -cp ~/Android/Sdk/platforms/android-36/android.jar -d $B Inject.java Capture.java && \
  ~/Android/Sdk/build-tools/36.0.0/d8 --min-api 30 --output $B $B/*.class && cp $B/classes.dex inject.dex
```

## Running

Each bot opens its game itself, or starts where it's told below. Logs and debug output go to `logs/` and `debug/`.

```sh
.venv/bin/python -m inttibot tasks                 # list: [slot] task: progress/target
.venv/bin/python -m inttibot tasks run             # play until every task is done
.venv/bin/python -u -m inttibot denssi             # --resets N, --no-nollaus, --dry-run
.venv/bin/python -u -m inttibot ampumarata         # -n N, -v, --auto, --chances
.venv/bin/python -m inttibot arsenaali all         # with the Arsenaali open: open cases, scrap duplicates
.venv/bin/python -u -m inttibot pakuralli          # from the Pakuralli start screen; -n N, -v
.venv/bin/python -u -m inttibot sotilas koulutus   # from the quiz menu; or maa, meri, aakkoset; -n N, --until N
.venv/bin/python -m inttibot cloud close           # before playing on another device
```

- **Denssiklikkeri**: `--resets N` buys Nollaus N times, starting over after each (default 1); `--no-nollaus` stops when it becomes affordable; `--dry-run` taps and logs decisions without buying. A full run to Nollaus takes about 3¾ h (`python -m tools.denssi_sim 13` simulates one). There's no offline progress, so the game must stay open. If the game freezes (bank unchanged for 20 s), the bot restarts INTTI and goes back.
- **Ampumarata**: plays the selected challenge (or the one whose result screen is open). `--auto` picks, run by run, the challenge with the best reward case chance per second; `--chances` lists them.
- **Sotilasarvopeli**: `--until N` stops answering at N and lets the timer end the round, which saves the score.

The bots default to Waydroid's address; `ANDROID_SERIAL` selects another device.

## Layout

| Path | What |
|---|---|
| `inttibot/__main__.py` | The command line: `python -m inttibot <command>` |
| `inttibot/device.py`, `inttibot/touch.py` | Android access: which device (`ANDROID_SERIAL`, default Waydroid), touch through the injector, app control and recovery |
| `inttibot/mem/` | Reading INTTI's memory: `reader` (the helper's protocol), `il2cpp` (classes, fields, lists, Unity transforms), `ui` (screens, the open minigame), `shooter` (Ampumarata), `tasks` (the daily tasks), `userdata` (the save) |
| `inttibot/tasks.py` | The daily task runner |
| `inttibot/cloud.py` | The cloud save's state and `cloud close` |
| `inttibot/games/` | One module per minigame: `ampumarata`, `arsenaali`, `pakuralli` (+ `pakuralli_dp`, the planner), `sotilas`, `denssi` (+ `denssi_data`: upgrades, income and the buying rule) |
| `native/injector/` | `Inject.java` (touch and keys), built into `inject.dex` and run with `app_process` |
| `native/memreader/` | `inttimem.c`, the memory reader helper |
| `scripts/` | `launch-waydroid.sh` (Waydroid on a headless weston, opens INTTI); `launch-emulator.sh` (the Android emulator: touch works through its console, but the memory reader needs Waydroid) |
| `tools/` | `denssi_sim.py` (simulates a Denssiklikkeri run), `bench.py` (counted taps/s and the game's FPS) |
| `docs/` | Notes per game, Waydroid, the memory reader, the tasks, the save |
