# feed.py: gathers everything the Touch Bar panels show, as the desktop user (gw2-touchbar-feed, a systemd
# user service). The bar itself runs as root and only draws: it reads $XDG_RUNTIME_DIR/gw2-touchbar/
# state.json (written once a second while GW2 runs) and sends taps back over feed.sock in the same folder
# ("combat.reset", "timer.toggle", "copy <text>"). Network and the session bus never run as root this way.
# Idle while GW2 isn't running: one look at /proc every 3 s.
import glob
import json
import os
import re
import socket
import subprocess
import threading
import time
from collections import deque
from datetime import date

from gw2tb import appwatch, config, mumble, online, sensors

RUN = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "gw2-touchbar")
STATE, SOCK = os.path.join(RUN, "state.json"), os.path.join(RUN, "feed.sock")
DATA = os.environ.get("GW2TB_DATA") or os.path.join(os.path.expanduser("~"), ".local", "share", "gw2-touchbar")
MANGO_DIRS = ("~/.local/share/letterbox/mangohud", "~/t2pm/gamelogs", "~/.local/share/MangoHud", "/tmp/MangoHud")
HIST = 300            # values kept per number (s): enough for a 5 min graph


def write_json(path, data):
    with open(path + ".part", "w") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(path + ".part", path)


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class MangoTail:
    """Follows the newest MangoHud log of GW2 and keeps the frame times of the last 60 s (from letterbox).
    MangoHud writes in blocks, so the numbers lag a few seconds behind; fine for averages."""

    def __init__(self, folder):
        self.folders = [os.path.expanduser(folder)] if folder else [os.path.expanduser(d) for d in MANGO_DIRS]
        self.path, self.pos, self.cols, self.buf = None, 0, None, b""
        self.frames = deque()          # (elapsed s, frametime ms)

    def update(self):
        logs = sorted((p for d in self.folders for p in glob.glob(f"{d}/Gw2-64_*.csv")), key=os.path.getmtime)
        if not logs or time.time() - os.path.getmtime(logs[-1]) > 30:
            self.frames.clear()
            return
        if logs[-1] != self.path:
            self.path, self.pos, self.cols, self.buf = logs[-1], 0, None, b""
            self.frames.clear()
        try:
            with open(self.path, "rb") as fh:
                size = os.fstat(fh.fileno()).st_size
                if self.pos == 0:
                    head = fh.read(4096).split(b"\n")
                    if len(head) > 2 and head[2].startswith(b"fps,"):
                        self.cols = head[2].decode().split(",")
                        self.pos = max(len(b"\n".join(head[:3])) + 1, size - 300_000)  # joining late: tail only
                fh.seek(self.pos)
                data = self.buf + fh.read()
                self.pos = fh.tell()
        except OSError:
            return
        if not self.cols:
            return
        lines = data.split(b"\n")
        self.buf = lines.pop()
        i_ft, i_el = self.cols.index("frametime"), self.cols.index("elapsed")
        for ln in lines:
            p = ln.split(b",")
            if len(p) != len(self.cols):
                continue
            try:
                self.frames.append((int(p[i_el]) / 1e9, float(p[i_ft])))
            except ValueError:
                continue
        while self.frames and self.frames[-1][0] - self.frames[0][0] > 60:
            self.frames.popleft()

    def stats(self):
        """-> (FPS of the newest second, 60 s average, 1 % low) or Nones."""
        if len(self.frames) < 30:
            return None, None, None
        last = self.frames[-1][0]
        fts = [ft for _, ft in self.frames if ft < 2000]
        recent = [ft for el, ft in self.frames if el > last - 1 and ft < 2000]
        now = len(recent) * 1000 / sum(recent) if recent else None
        worst = sorted(fts, reverse=True)[:max(1, len(fts) // 100)]
        return now, len(fts) * 1000 / sum(fts), 1000 / (sum(worst) / len(worst))


def game_ping():
    """Kernel's smoothed TCP round-trip time of GW2's most recently active connection (ss), ms or None."""
    try:
        out = subprocess.run(["ss", "-tinpH", "state", "established"], capture_output=True, text=True,
                             timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    best, best_last, game = None, 1e12, False
    for ln in out.splitlines():
        if not ln.startswith((" ", "\t")):
            game = '"Gw2-64.exe"' in ln and " 127." not in ln
            continue
        if game:
            m_rtt, m_last = re.search(r"\brtt:([\d.]+)", ln), re.search(r"\blastrcv:(\d+)", ln)
            last = int(m_last.group(1)) if m_last else 1e9
            if m_rtt and last < best_last:
                best, best_last = float(m_rtt.group(1)), last
            game = False
    return best


class Threads:
    """CPU use of GW2's busiest threads in % of one core, from /proc/<pid>/task (same user, no root)."""

    def __init__(self):
        self.last, self.at = {}, None
        self.hz = os.sysconf("SC_CLK_TCK")

    def sample(self, pid):
        now, cur = time.monotonic(), {}
        for t in glob.glob(f"/proc/{pid}/task/*"):
            try:
                raw = open(f"{t}/stat").read()
                comm = raw[raw.index("(") + 1:raw.rindex(")")]
                fields = raw[raw.rindex(")") + 2:].split()
                cur[t] = (comm, int(fields[11]) + int(fields[12]))
            except (OSError, ValueError, IndexError):
                continue
        out = []
        if self.at:
            dt = now - self.at
            for t, (comm, ticks) in cur.items():
                if t in self.last:
                    out.append(((ticks - self.last[t][1]) / self.hz / dt * 100, comm))
        self.last, self.at = cur, now
        return sorted(out, reverse=True)[:2]


def steam_libraries():
    libs = [os.path.expanduser(p) for p in ("~/.local/share/Steam", "~/.steam/steam")]
    for vdf in (f"{lib}/steamapps/libraryfolders.vdf" for lib in list(libs)):
        try:
            libs += re.findall(r'"path"\s*"([^"]+)"', open(vdf).read())
        except OSError:
            pass
    return list(dict.fromkeys(libs))


def bridge_path():
    """bridge.json of the letterbox Nexus addon (squad data), if GW2 has one."""
    for lib in steam_libraries():
        p = f"{lib}/steamapps/common/Guild Wars 2/addons/letterbox/bridge.json"
        if os.path.isdir(os.path.dirname(p)):
            return p
    return None


def localize(obj):
    """Every "icon_url" (and team logo) gets a local "icon" file next to it for the bar to draw."""
    if isinstance(obj, dict):
        out = {k: localize(v) for k, v in obj.items()}
        if obj.get("icon_url"):
            out["icon"] = online.icon(obj["icon_url"])
        if "teams" in obj:
            out["teams"] = [[a, s, online.icon(logo)] for a, s, logo in obj["teams"]]
        return out
    if isinstance(obj, list):
        return [localize(x) for x in obj]
    return obj


class Feed:
    def __init__(self):
        self.cfg = config.load()
        self.cfg_mtime = self._cfg_mtime()
        self.online = online.Online()
        self.reader = mumble.Reader()
        self.sensors = sensors.Sensors("")
        self.mango = MangoTail(self.cfg["settings"]["mangohud_dir"])
        self.threads = Threads()
        self.gpu_samples = deque(maxlen=20)
        self.hist = {}
        self.pings = deque(maxlen=60)
        self.net_last = None
        self.bridge = bridge_path()
        self.combat_since, self.combat_total = None, 0.0
        self.timer_start = None
        self.runs = self._load("timer-runs.json", [])
        self.play = self._load("playtime.json", {})
        self.session_start = None
        self.lock = threading.Lock()

    # ---- persistence in ~/.local/share/gw2-touchbar
    def _load(self, name, default):
        try:
            return json.load(open(os.path.join(DATA, name)))
        except (OSError, ValueError):
            return default

    def _save(self, name, data):
        os.makedirs(DATA, exist_ok=True)
        write_json(os.path.join(DATA, name), data)

    # ---- actions from the bar
    def action(self, line):
        cmd, _, arg = line.strip().partition(" ")
        with self.lock:
            if cmd == "combat.reset":
                self.combat_total = 0.0
                if self.combat_since:
                    self.combat_since = time.time()
            elif cmd == "timer.toggle":
                if self.timer_start is None:
                    self.timer_start = time.time()
                else:
                    self.runs = ([round(time.time() - self.timer_start, 1)] + self.runs)[:10]
                    self.timer_start = None
                    self._save("timer-runs.json", self.runs)
            elif cmd == "music.toggle":
                self.online.music_toggle()
            elif cmd == "copy" and arg:
                subprocess.Popen(["qdbus6", "org.kde.klipper", "/klipper",
                                  "org.kde.klipper.klipper.setClipboardContents", arg[:200]],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def serve_actions(self):
        try:
            os.unlink(SOCK)
        except FileNotFoundError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SOCK)
        os.chmod(SOCK, 0o600)
        srv.listen(4)
        while True:
            c, _ = srv.accept()
            try:
                c.settimeout(1)
                self.action(c.recv(512).decode(errors="replace"))
            except OSError:
                pass
            finally:
                c.close()

    # ---- one second of data
    def sample_gpu(self):
        try:
            self.gpu_samples.append(int(open(f"{self.sensors.gpu}/gpu_busy_percent").read()))
        except (OSError, ValueError, TypeError):
            pass

    def update(self, pid):
        game = self.reader.read()
        m = self._cfg_mtime()
        if m != self.cfg_mtime:                    # the settings app saved: new panels, key, watchlist
            self.cfg, self.cfg_mtime = config.load(), m
        used = {p["type"] for pg in self.cfg["pages"] for p in pg["panels"]}
        extra = localize(self.online.gather(self.cfg["settings"], used, game))
        self.mango.update()
        p = self.sensors.read()
        v, sub = {}, {}
        fmt = lambda x, s="{:.0f}": "-" if x is None else s.format(x)
        v["cpu"], sub["cpu"] = p.get("mhz_avg"), f"fastest {fmt(p.get('mhz_max'))}"
        v["ctemp"], sub["ctemp"] = p.get("core_max_c"), f"package {fmt(p.get('pkg_c'))} °C"
        v["pkg"], sub["pkg"] = p.get("pkg_w"), "RAPL package"
        v["gpu"], sub["gpu"] = p.get("gpu_w"), f"cap {fmt(p.get('gpu_cap_w'))} W"
        v["sclk"], sub["sclk"] = p.get("gpu_sclk"), f"mem {fmt(p.get('gpu_mclk'))} MHz"
        v["gtemp"], sub["gtemp"] = p.get("gpu_junc_c"), f"edge {fmt(p.get('gpu_edge_c'))} °C"
        gs = list(self.gpu_samples)
        self.gpu_samples.clear()
        v["busy"], sub["busy"] = (sum(gs) / len(gs) if gs else None), f"peak {max(gs) if gs else '-'} %"
        try:
            used = int(open(f"{self.sensors.gpu}/mem_info_vram_used").read()) / 2**30
            tot = int(open(f"{self.sensors.gpu}/mem_info_vram_total").read()) / 2**30
            v["vram"], sub["vram"] = used, f"of {tot:.0f} GiB"
        except (OSError, ValueError, TypeError):
            v["vram"] = None
        v["fan"], sub["fan"] = p.get("fan1"), f"{fmt(p.get('fan1'))} / {fmt(p.get('fan2'))} rpm"
        mi = {}
        try:
            for line in open("/proc/meminfo"):
                k, val = line.split(":", 1)
                mi[k] = int(val.split()[0]) / 1048576
            v["mem"] = mi["MemTotal"] - mi["MemAvailable"]
            sub["mem"] = f"of {mi['MemTotal']:.0f} GiB"
        except (OSError, KeyError, ValueError):
            v["mem"] = None
        rx = tx = 0
        try:
            for line in open("/proc/net/dev").readlines()[2:]:
                name, rest = line.split(":", 1)
                if name.strip() != "lo":
                    a = rest.split()
                    rx, tx = rx + int(a[0]), tx + int(a[8])
        except (OSError, ValueError):
            pass
        now = time.monotonic()
        if self.net_last:
            dt = now - self.net_last[0]
            v["net"], sub["net"] = (rx - self.net_last[1]) / dt / 1024, f"up {(tx - self.net_last[2]) / dt / 1024:.0f} KiB/s"
        self.net_last = (now, rx, tx)
        fnow, favg, flow = self.mango.stats()
        v["fps"], sub["fps"] = fnow, f"avg {fmt(favg)} · 1% low {fmt(flow)}"
        v["ping"] = game_ping()
        if v["ping"] is not None:
            self.pings.append(v["ping"])
        sub["ping"] = f"avg {sum(self.pings) / len(self.pings):.0f} ms" if self.pings else "-"
        th = self.threads.sample(pid)
        v["thread"] = th[0][0] if th else None
        sub["thread"] = f"{th[0][1]} · 2nd {th[1][0]:.0f} %" if len(th) > 1 else "-"
        for k, x in v.items():
            self.hist.setdefault(k, deque(maxlen=HIST)).append(None if x is None else round(x, 1))

        t = time.time()
        with self.lock:
            fighting = bool(game and game.get("in_combat"))
            if fighting and self.combat_since is None:
                self.combat_since = t
            elif not fighting and self.combat_since is not None:
                self.combat_total += t - self.combat_since
                self.combat_since = None
            if game:
                today = date.today().isoformat()
                self.play = {today: self.play.get(today, 0) + 1}
                if int(t) % 30 == 0:
                    self._save("playtime.json", self.play)
            state = {
                "t": t, "game": game, "v": v, "sub": sub,
                "hist": {k: list(h) for k, h in self.hist.items()},
                "bottleneck": self.bottleneck(v),
                "combat": {"since": self.combat_since, "total": self.combat_total},
                "timer": {"start": self.timer_start, "runs": self.runs[:5]},
                "play": {"today": self.play.get(date.today().isoformat(), 0),
                         "session": t - self.session_start if self.session_start else 0},
                "squad": self.read_bridge(),
                **extra,
            }
        write_json(STATE, state)

    @staticmethod
    def _cfg_mtime():
        try:
            return os.path.getmtime(config.path())
        except OSError:
            return None

    def bottleneck(self, v):
        busy, th = v.get("busy"), v.get("thread")
        if busy is not None and busy >= 95:
            return ["GPU-bound", f"GPU {busy:.0f} % busy"]
        if th is not None and th >= 85:
            return ["CPU-bound", f"main thread {th:.0f} % · {v.get('cpu') or 0:.0f} MHz"]
        return ["headroom", f"GPU {busy or 0:.0f} % · thread {th or 0:.0f} %"]

    def read_bridge(self):
        try:
            if self.bridge and time.time() - os.path.getmtime(self.bridge) < 5:
                return json.load(open(self.bridge))
        except (OSError, ValueError):
            pass
        return None

    def run(self):
        os.makedirs(RUN, mode=0o700, exist_ok=True)
        threading.Thread(target=self.serve_actions, daemon=True).start()
        app = None if self.reader.fake or os.environ.get("GW2TB_NO_APPWATCH") else appwatch.Watch(os.getuid())
        while True:
            pids = mumble.gw2_pids()
            gone = app is not None and app.gone()        # the settings app closed: the feed stops too
            if gone or (not pids and not self.reader.fake):
                if self.session_start:
                    self.session_start = None
                    self._save("playtime.json", self.play)
                    try:
                        os.unlink(STATE)
                    except FileNotFoundError:
                        pass
                if gone:
                    return
                time.sleep(3)
                continue
            self.session_start = self.session_start or time.time()
            start = time.monotonic()
            for _ in range(5):                     # GPU busy flickers: sample it 5x per second
                self.sample_gpu()
                time.sleep(0.2)
            self.update(pids[0] if pids else os.getpid())
            time.sleep(max(0.0, 1.0 - (time.monotonic() - start)))
