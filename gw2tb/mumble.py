# mumble.py: reads GW2's MumbleLink (the official overlay interface) straight from the game process.
# Under Proton it is a Wine file mapping inside Gw2-64.exe: /proc/<pid>/maps finds the mapping,
# /proc/<pid>/mem reads it. Wine allows that to its own user even with ptrace_scope 1, root always can. Map and specialization names come from
# the public GW2 API once per id and are cached in /var/lib/gw2-touchbar/names.json.
# GW2TB_FAKE=<json file> replaces the game with a fixed state (headless tests).
import json, math, os, struct, threading, time, urllib.request

NAME = "Guild Wars 2".encode("utf-16-le")
CACHE = os.environ.get("GW2TB_CACHE", "/var/lib/gw2-touchbar/names.json")
PROFESSIONS = {1: "Guardian", 2: "Warrior", 3: "Engineer", 4: "Ranger", 5: "Thief", 6: "Elementalist",
               7: "Mesmer", 8: "Necromancer", 9: "Revenant"}
MAP_TYPES = {0: "redirect", 1: "character create", 2: "pvp", 3: "gvg", 4: "instance", 5: "open world",
             6: "tournament", 7: "tutorial", 8: "user tournament", 9: "wvw", 10: "wvw", 11: "wvw",
             12: "wvw", 13: "wvw lobby", 14: "obsidian sanctum", 15: "edge of the mists", 16: "public mini",
             18: "wvw lobby"}
MOUNTS = {0: "", 1: "jackal", 2: "griffon", 3: "springer", 4: "skimmer", 5: "raptor", 6: "roller beetle",
          7: "warclaw", 8: "skyscale", 9: "skiff", 10: "siege turtle"}


def gw2_pids():
    """The game process itself (comm "Gw2-64.exe"); wrappers like steam.exe/reaper only mention it."""
    out = []
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            with open(f"/proc/{p}/comm") as f:
                if f.read().strip().lower() == "gw2-64.exe":
                    out.append(int(p))
        except OSError:
            continue
    return out


def find_link(pid):
    """(open mem file, address) of the LinkedMem struct: a small Wine mapping with 'Guild Wars 2' at
    offset 44 (name field), or (None, None)."""
    try:
        maps = open(f"/proc/{pid}/maps").read().splitlines()
        mem = open(f"/proc/{pid}/mem", "rb", buffering=0)
    except OSError:
        return None, None
    for line in maps:
        rng, perms = line.split()[:2]
        a, b = (int(x, 16) for x in rng.split("-"))
        if "r" not in perms or "wine-mapping" not in line or not (4096 <= b - a <= 65536):
            continue
        try:
            mem.seek(a + 44)
            if mem.read(len(NAME)) == NAME:
                return mem, a
        except OSError:
            continue
    mem.close()
    return None, None


def parse(buf):
    tick = struct.unpack_from("<I", buf, 4)[0]
    ctx = 1108
    map_id, map_type = struct.unpack_from("<II", buf, ctx + 28)
    ui_state = struct.unpack_from("<I", buf, ctx + 48)[0]
    mount = buf[ctx + 84]
    ident = {}
    try:                                    # identity JSON: character, profession, spec, map id, commander
        ident = json.loads(buf[592:1104].decode("utf-16-le").split("\0")[0] or "{}")
        map_id = ident.get("map_id", map_id)
    except ValueError:
        pass
    fx, _fy, fz = struct.unpack_from("<3f", buf, 568)       # camera front vector
    heading = round(math.degrees(math.atan2(fx, fz)) % 360) if (fx or fz) else None
    return dict(tick=tick, map_id=map_id, map_type=MAP_TYPES.get(map_type, str(map_type)),
                in_combat=bool(ui_state & 0x40), map_open=bool(ui_state & 0x1), focus=bool(ui_state & 0x8),
                mount=MOUNTS.get(mount, ""), char_name=ident.get("name", ""),
                profession=PROFESSIONS.get(ident.get("profession"), ""), spec_id=ident.get("spec", 0),
                commander=bool(ident.get("commander")), heading=heading, team_color_id=ident.get("team_color_id"))


def compass(deg):
    if deg is None:
        return ""
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((deg + 22.5) % 360 // 45)]


class Names:
    """Map and specialization names from the GW2 API, fetched in the background, never while drawing."""

    def __init__(self, path=CACHE):
        self.path, self.pending = path, set()
        try:
            self.cache = json.load(open(path))
        except (OSError, ValueError):
            self.cache = {}

    def get(self, kind, ident):
        if not ident:
            return ""
        key = str(ident) if kind == "maps" else f"spec:{ident}"
        if key in self.cache:
            return self.cache[key]
        if key not in self.pending:
            self.pending.add(key)
            threading.Thread(target=self._fetch, args=(kind, ident, key), daemon=True).start()
        return ""

    def _fetch(self, kind, ident, key):
        try:
            with urllib.request.urlopen(f"https://api.guildwars2.com/v2/{kind}/{ident}", timeout=5) as r:
                self.cache[key] = json.load(r).get("name", "")
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path + ".part", "w") as f:
                json.dump(self.cache, f)
            os.replace(self.path + ".part", self.path)
        except Exception:
            time.sleep(30)                  # offline: try again later, not on every poll
        finally:
            self.pending.discard(key)


class Reader:
    """Latest GW2 state as a dict, or None while GW2 isn't in a map (not running, loading, character
    select: the tick stops moving)."""

    def __init__(self):
        self.mem = self.addr = None
        self.last_tick, self.tick_at = None, 0.0
        self.names = Names()
        self.fake = os.environ.get("GW2TB_FAKE")

    def read(self):
        if self.fake:
            try:
                return json.load(open(self.fake))
            except (OSError, ValueError):
                return None
        if self.mem is None:
            for pid in gw2_pids():
                self.mem, self.addr = find_link(pid)
                if self.mem:
                    break
            if self.mem is None:
                return None
        try:
            self.mem.seek(self.addr)
            buf = self.mem.read(1364)
        except OSError:
            self.mem.close()
            self.mem = None
            return None
        if len(buf) < 1364:
            return None
        s = parse(buf)
        now = time.monotonic()
        if s["tick"] != self.last_tick:
            self.last_tick, self.tick_at = s["tick"], now
        if now - self.tick_at > 3 or not s["char_name"]:
            return None
        s["map_name"] = self.names.get("maps", s["map_id"])
        s["spec"] = self.names.get("specializations", s["spec_id"])
        return s
