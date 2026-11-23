"""INTTI bots.

    python -m inttibot <command> [options]     (python -m inttibot <command> -h for each)

Commands:
    tasks        daily tasks: list them, or play the minigames that complete them
    ampumarata   Ampumarata challenges
    arsenaali    Ampumarata's Arsenaali: open cases, scrap duplicate skins
    pakuralli    Pakuralli
    sotilas      Sotilasarvopeli
    denssi       Denssiklikkeri
    userdata     print INTTI's save (UserData) from memory [key filter]
    cloud        the cloud save's sync state; `cloud close` uploads the save, then closes INTTI
"""
import importlib
import sys
import time

COMMANDS = {"tasks": "inttibot.tasks", "ampumarata": "inttibot.games.ampumarata",
            "arsenaali": "inttibot.games.arsenaali", "pakuralli": "inttibot.games.pakuralli",
            "sotilas": "inttibot.games.sotilas", "denssi": "inttibot.games.denssi",
            "userdata": "inttibot.mem.userdata", "cloud": "inttibot.cloud"}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(0 if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help") else 2)
    cmd = sys.argv[1]
    sys.argv = [f"inttibot {cmd}", *sys.argv[2:]]
    if cmd in ("userdata", "cloud"):
        importlib.import_module(COMMANDS[cmd]).main()
        return
    before = save_snapshot()
    try:
        importlib.import_module(COMMANDS[cmd]).main()
    finally:
        log_save_changes(before)


def save_snapshot():
    """INTTI's save ints and the time, to log what a run changed; None if memory can't be read."""
    try:
        from .mem import UserData
        ud = UserData()
        return ud, time.time(), ud.read("ints")
    except Exception as e:                       # the game isn't running, the helper is missing
        print(f"(save not read: {e})", flush=True)
        return None


def log_save_changes(snap, limit=30):
    """Log the save's ints that changed during the run: coins (and per minute) first."""
    if snap is None:
        return
    ud, t0, before = snap
    try:
        after = ud.read("ints")
    except Exception as e:
        print(f"(save not read: {e})", flush=True)
        return
    minutes = (time.time() - t0) / 60
    earned = after.get("total_coins", 0) - before.get("total_coins", 0)
    stamp = time.strftime("%H:%M:%S")
    print(f"{stamp} coins {after.get('coins', 0)} ({earned:+d} in {minutes:.1f} min"
          + (f", {earned / minutes:.2f}/min)" if minutes >= 1 else ")"), flush=True)
    changed = [k for k in sorted(after, key=str) if after[k] != before.get(k, 0) and k not in ("coins", "total_coins")]
    for k in changed[:limit]:
        print(f"{stamp}   {k} {before.get(k, 0)} -> {after[k]} ({after[k] - before.get(k, 0):+d})", flush=True)
    if len(changed) > limit:
        print(f"{stamp}   ... and {len(changed) - limit} more", flush=True)


if __name__ == "__main__":
    main()
