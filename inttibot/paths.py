"""Where things are in the repository."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INJECTOR_DEX = os.path.join(ROOT, "native", "injector", "inject.dex")
LAUNCH_WAYDROID = os.path.join(ROOT, "scripts", "launch-waydroid.sh")
DEBUG = os.path.join(ROOT, "debug")      # debug frames and dumps (git-ignored)
STATE = os.path.join(ROOT, "state")      # bots' saved state (git-ignored)


def debug_path(*parts):
    p = os.path.join(DEBUG, *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p
