# appwatch: is the settings app open? The bar and the feed only run while it is. The app starts and stops
# both services itself, this is the safety net for an app that crashed or got killed.
import os
import time

NAME = b"gw2-touchbar-settings"


def app_open(uid):
    """True if a process of this user runs gw2-touchbar-settings (as argv[0] or as python3's script)."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            if os.stat(f"/proc/{pid}").st_uid != uid:
                continue
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = f.read().split(b"\0")[:2]
        except OSError:
            continue
        if any(os.path.basename(a) == NAME for a in argv):
            return True
    return False


class Watch:
    """gone() turns True once the app has been missing for `grace` seconds."""

    def __init__(self, uid, grace=6.0):
        self.uid, self.grace, self.seen = uid, grace, time.monotonic()

    def gone(self):
        if app_open(self.uid):
            self.seen = time.monotonic()
            return False
        return time.monotonic() - self.seen > self.grace
