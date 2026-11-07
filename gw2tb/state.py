# state.py: the bar's view of what gw2-touchbar-feed gathered (state.json in the user's runtime dir) and
# the way back for taps (feed.sock). The settings app's preview hands in a fixed state instead.
import json
import os
import pwd
import socket
import time

override = None        # a dict to draw instead of the feed's state (settings preview)


def run_dir():
    if os.environ.get("GW2TB_RUN"):
        return os.environ["GW2TB_RUN"]
    name = os.environ.get("GW2TB_USER")
    try:
        uid = pwd.getpwnam(name).pw_uid if name else os.getuid()
    except KeyError:
        uid = os.getuid()
    return f"/run/user/{uid}/gw2-touchbar"


class Source:
    """Rereads state.json when it changes; anything older than 5 s counts as no data."""

    def __init__(self):
        self.path = os.path.join(run_dir(), "state.json")
        self.mtime, self.data = None, {}

    def get(self):
        if override is not None:
            return override
        try:
            m = os.path.getmtime(self.path)
        except OSError:
            self.data = {}
            return self.data
        if m != self.mtime:
            self.mtime = m
            try:
                with open(self.path) as f:
                    self.data = json.load(f)
            except (OSError, ValueError):
                pass
        return self.data if time.time() - m < 5 else {}


def send(cmd):
    """One line to the feed ("timer.toggle", "copy <text>"); False when it isn't running."""
    if override is not None:
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect(os.path.join(run_dir(), "feed.sock"))
        s.sendall(cmd.encode()[:512])
        s.close()
        return True
    except OSError:
        return False
