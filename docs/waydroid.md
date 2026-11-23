# Waydroid

The bots run INTTI in **Waydroid**: Android as an LXC container on the host kernel. The container shares the host's uids, which is what lets the memory reader see the game ([memreader.md](memreader.md)). INTTI's ARM code runs through ARM translation (libhoudini or libndk).

## Install (one-time, needs sudo)

The commands are in the README.

| Step | Detail |
|---|---|
| Package | `waydroid`; on Debian 13 it's in trixie-backports |
| Binder | If the kernel has no binderfs, the devices come from module params: `options binder_linux devices=binder,hwbinder,vndbinder` in `/etc/modprobe.d/binder.conf`, `binder_linux` in `/etc/modules-load.d/binder.conf`. Waydroid needs all three |
| Image | `sudo waydroid init`, plain (not `-s GAPPS`): INTTI installs from `apk/`. Its manifest uses Google Play Services only for AdMob and billing, so no Play Store is needed |
| ARM translation | `casualsnek/waydroid_script`: `install libhoudini` (Intel) or `libndk` (AMD), then restart the container. The APK is arm64-only; without translation it fails with `INSTALL_FAILED_NO_MATCHING_ABIS` |
| Firewall (ufw) | `ufw allow in on waydroid0 to any port 67 proto udp`, `… port 53`, `ufw route allow in on waydroid0`. Otherwise ufw blocks DHCP and the container gets no IP |
| INTTI | `adb -s 192.168.240.112:5555 install-multiple apk/base.apk apk/split_config.arm64_v8a.apk` (a split APK: base + arm64 libs) |

## Running
`scripts/launch-waydroid.sh` (re)starts the session and opens INTTI. It also sets `persist.waydroid.suspend false`: without it the container freezes when its window closes.

- **Headless by default.** On a desktop, Waydroid's frames are only taken while its window is on screen; hidden, minimized or with the screen locked, Android's buffers run out (`dequeueBuffer failed, error = -110`) and INTTI stalls. So the script runs Waydroid on its own **headless weston** (`weston --backend=headless --renderer=gl --shell=kiosk`, socket `wayland-waydroid`). The **kiosk shell** matters: the default desktop shell's panel shrinks a maximized window below 540×1200, Waydroid rejects that size and Android never finishes booting. `DESKTOP=1` uses a desktop window instead. The bots' recovery (`device.restart_waydroid()`) runs the same script.
- **Screen size.** `wm size 540x1200` + `wm density 210` set the size the bots' positions are for, whatever size the window has (e.g. with desktop scaling).
- **Ads** load without the Play Store. Private DNS `dns.adguard-dns.com` (`settings put global private_dns_mode hostname` + `private_dns_specifier`) blocks them. A banner already loaded stays until the app restarts.
- **First launch** of INTTI shows a black screen for a while (ARM translation warming up).

## Input: the app_process injector

There's no root for the bots (`adb root` isn't available, and root through `sudo waydroid shell` in a privileged container is close to host root), the input devices aren't writable by the shell user, and `adb shell input tap` starts a JVM per call (~1 s).

So `native/injector/Inject.java` (`inject.dex`, ~5 KB) runs **once** as the shell user via `app_process` and injects through `InputManager.injectInputEvent` (reflection, async mode), reading commands from stdin over one persistent `adb shell` (`touch.InjectTouch`). Coordinates are screen fractions; the display size comes from `wm size`. `InjectTouch` restarts the process (and resends) when the adb pipe breaks.

| Command | Meaning |
|---|---|
| `d x y` / `m x y` / `u` | finger 0 down / move / up |
| `a x y` / `r` | add a finger while others are down / lift the last one (Ampumarata fires with a second finger) |
| `D x1 y1 …` / `U` | several fingers at once / lift all |
| `t text` / `k code` | type text (`KeyCharacterMap`; characters without a key go as one multi-char KeyEvent) / key code (66 = Enter) |
| `p` | prints `ok`: sync point |

Unity accepts these events like real touches. Taps right after a screen change may be swallowed (Unity fade-ins), so the bots check the effect in memory and retry.
