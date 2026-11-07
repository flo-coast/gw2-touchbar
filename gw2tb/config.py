# config.py: the user's Touch Bar setup in ~/.config/gw2-touchbar/config.toml, shared by the bar (root
# service, reads it) and gw2-touchbar-settings (writes it). Pages of panels; each panel has a type from
# CATALOG plus its own width, colour, font size and style. The service picks up saved changes by itself.
import os
import pwd
import re
import tomllib

# type: title, group (for the settings app), default width (0 = takes the room that's left), and for
# number panels the state key, unit, graph maximum and number format.
CATALOG = {
    # performance
    "fps":        {"title": "FPS", "group": "Performance", "width": 190, "num": "fps", "unit": "", "max": 90},
    "ping":       {"title": "Ping", "group": "Performance", "width": 170, "num": "ping", "unit": "ms", "max": 200},
    "cpu":        {"title": "CPU clock", "group": "Performance", "width": 190, "num": "cpu", "unit": "MHz", "max": 5000},
    "ctemp":      {"title": "CPU temp", "group": "Performance", "width": 160, "num": "ctemp", "unit": "°C", "max": 105},
    "pkg":        {"title": "CPU power", "group": "Performance", "width": 160, "num": "pkg", "unit": "W", "max": 60},
    "thread":     {"title": "GW2 main thread", "group": "Performance", "width": 200, "num": "thread", "unit": "%", "max": 110},
    "gpu":        {"title": "GPU power", "group": "Performance", "width": 160, "num": "gpu", "unit": "W", "max": 60},
    "sclk":       {"title": "GPU clock", "group": "Performance", "width": 190, "num": "sclk", "unit": "MHz", "max": 1600},
    "busy":       {"title": "GPU busy", "group": "Performance", "width": 160, "num": "busy", "unit": "%", "max": 100},
    "gtemp":      {"title": "GPU temp", "group": "Performance", "width": 160, "num": "gtemp", "unit": "°C", "max": 105},
    "vram":       {"title": "VRAM", "group": "Performance", "width": 160, "num": "vram", "unit": "GiB", "max": 8, "fmt": "{:.1f}"},
    "fan":        {"title": "Fans", "group": "Performance", "width": 180, "num": "fan", "unit": "rpm", "max": 6500},
    "mem":        {"title": "Memory", "group": "Performance", "width": 170, "num": "mem", "unit": "GiB", "max": 32, "fmt": "{:.1f}"},
    "net":        {"title": "Network", "group": "Performance", "width": 190, "num": "net", "unit": "KiB/s", "max": 2000},
    "bottleneck": {"title": "Bottleneck", "group": "Performance", "width": 260},
    "sensors":    {"title": "GPU temp + CPU clock", "group": "Performance", "width": 210},
    # game
    "char":       {"title": "Character + map", "group": "Game", "width": 440},
    "combat":     {"title": "Combat timer", "group": "Game", "width": 220},
    "boss":       {"title": "Next world boss", "group": "Game", "width": 0},
    "timeline":   {"title": "Event timeline", "group": "Game", "width": 0},
    "timer":      {"title": "Run timer", "group": "Game", "width": 200},
    "playtime":   {"title": "Playtime", "group": "Game", "width": 200},
    "squad":      {"title": "Squad", "group": "Game", "width": 300},
    # account (GW2 API key)
    "wvw":        {"title": "WvW matchup", "group": "Account", "width": 520},
    "tp":         {"title": "Trading Post watchlist", "group": "Account", "width": 0},
    "earnings":   {"title": "Session earnings", "group": "Account", "width": 300},
    "vault":      {"title": "Wizard's Vault", "group": "Account", "width": 300},
    "gems":       {"title": "Gem exchange", "group": "Account", "width": 260},
    # everyday
    "music":      {"title": "Now playing", "group": "Everyday", "width": 420},
    "notify":     {"title": "Latest notification", "group": "Everyday", "width": 0},
    "battery":    {"title": "Batteries", "group": "Everyday", "width": 260},
    "weather":    {"title": "Weather", "group": "Everyday", "width": 300},
    "scores":     {"title": "Scores", "group": "Everyday", "width": 0},
    # bar
    "keys":       {"title": "Keys (game keys group)", "group": "Bar", "width": 130},
    "clock":      {"title": "Clock", "group": "Bar", "width": 100},
    "spacer":     {"title": "Empty space", "group": "Bar", "width": 0},
}
STYLES = ("number", "graph", "both")            # number panels only
FONT_SIZES = (14, 30)                           # px of a panel's main line
BAR_WIDTH = 2008

DEFAULT_KEYS = [
    {"label": "Map", "keys": ["M"]}, {"label": "Hero", "keys": ["H"]}, {"label": "Bags", "keys": ["I"]},
    {"label": "WvW", "keys": ["B"]}, {"label": "TP", "keys": ["O"]},
    {"label": "Mark", "keys": ["LeftMeta", "LeftShift", "M"]},
]

DEFAULT = {
    "settings": {"brightness": 2, "touch_flip": False, "page_dots": True, "swipe": True, "graph_seconds": 60,
                 "mangohud_dir": "",
                 "start_on_open": False,          # the settings app switches the bar on when it opens
                 # account and everyday panels
                 "api_key": "", "tp_watch": [], "weather_city": "", "sports_league": "basketball/nba",
                 "sports_team": "", "notify_filter": "discord", "notify_popup": True},
    "keys": DEFAULT_KEYS,
    "pages": [
        {"name": "Game", "panels": [{"type": "char"}, {"type": "combat"}, {"type": "boss"},
                                    {"type": "keys"}, {"type": "sensors"}, {"type": "clock"}]},
        {"name": "Performance", "panels": [{"type": "fps", "style": "both"}, {"type": "ping", "style": "both"},
                                           {"type": "thread"}, {"type": "busy", "style": "both"},
                                           {"type": "gtemp"}, {"type": "cpu"}, {"type": "bottleneck"},
                                           {"type": "clock"}]},
        {"name": "Events", "panels": [{"type": "timeline"}, {"type": "timer"}, {"type": "playtime"},
                                      {"type": "clock"}]},
        {"name": "Account", "panels": [{"type": "wvw"}, {"type": "earnings"}, {"type": "vault"}, {"type": "gems"},
                                       {"type": "clock"}]},
        {"name": "Everyday", "panels": [{"type": "music"}, {"type": "notify"}, {"type": "battery"},
                                        {"type": "weather"}, {"type": "clock"}]},
    ],
}


def user_home(name=None):
    """Home of the desktop user (GW2TB_USER when we are the root service)."""
    name = name or os.environ.get("GW2TB_USER")
    try:
        return pwd.getpwnam(name).pw_dir if name else os.path.expanduser("~")
    except KeyError:
        return os.path.expanduser("~")


def path(user=None):
    return os.environ.get("GW2TB_CONFIG") or os.path.join(user_home(user), ".config", "gw2-touchbar", "config.toml")


def _color(v):
    return v if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v) else ""


def _list(v):
    return v if isinstance(v, list) else []


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def panel(p):
    """A panel dict with every field filled in and nothing that isn't ours."""
    t = p.get("type") if isinstance(p.get("type"), str) and p["type"] in CATALOG else "spacer"
    out = {"type": t, "width": CATALOG[t]["width"], "color": "", "size": 0, "style": "number", "sub": True}
    try:
        out["width"] = max(0, min(BAR_WIDTH, int(p.get("width", out["width"]))))
        out["size"] = int(p.get("size", 0))
    except (TypeError, ValueError):
        pass
    if out["size"]:
        out["size"] = max(FONT_SIZES[0], min(FONT_SIZES[1], out["size"]))
    out["color"] = _color(p.get("color"))
    if p.get("style") in STYLES:
        out["style"] = p["style"]
    out["sub"] = bool(p.get("sub", True))
    return out


def normalize(data):
    """Whatever the file holds -> a complete, safe config. Keys only from {label, keys}; no commands."""
    given = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    s = {**DEFAULT["settings"], **{k: v for k, v in given.items() if k in DEFAULT["settings"]}}
    for k, v in DEFAULT["settings"].items():          # wrong types back to the default
        if type(s[k]) is not type(v):
            s[k] = v
    s["tp_watch"] = [{"id": int(w["id"]), "target": _int(w.get("target"))} for w in s["tp_watch"]
                     if isinstance(w, dict) and str(w.get("id", "")).isdigit()][:12]
    keys = []
    for k in _list(data.get("keys", DEFAULT_KEYS)):
        if isinstance(k, dict) and isinstance(k.get("keys"), list) and k["keys"]:
            keys.append({"label": str(k.get("label", "?"))[:20], "keys": [str(x) for x in k["keys"]][:4]})
    pages = []
    for pg in _list(data.get("pages")) or DEFAULT["pages"]:
        if isinstance(pg, dict):
            pages.append({"name": str(pg.get("name", "Page"))[:30],
                          "panels": [panel(p) for p in _list(pg.get("panels")) if isinstance(p, dict)]})
    return {"settings": s, "keys": keys, "pages": pages or [dict(name="Page", panels=[])]}


def load(file=None):
    try:
        with open(file or path(), "rb") as f:
            return normalize(tomllib.load(f))
    except (OSError, tomllib.TOMLDecodeError):
        return normalize({})


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {_toml_value(x)}" for k, x in v.items()) + " }"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def dumps(cfg):
    lines = ["# gw2-touchbar, written by gw2-touchbar-settings. The bar reloads it when it changes.", "",
             "[settings]"]
    lines += [f"{k} = {_toml_value(v)}" for k, v in cfg["settings"].items()]
    for k in cfg["keys"]:
        lines += ["", "[[keys]]", f"label = {_toml_value(k['label'])}", f"keys = {_toml_value(k['keys'])}"]
    for pg in cfg["pages"]:
        lines += ["", "[[pages]]", f"name = {_toml_value(pg['name'])}", "panels = ["]
        lines += [f"    {_toml_value(p)}," for p in pg["panels"]]
        lines.append("]")
    return "\n".join(lines) + "\n"


def save(cfg, file=None):
    file = file or path()
    os.makedirs(os.path.dirname(file), exist_ok=True)
    fd = os.open(file + ".part", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)     # holds the API key
    with open(fd, "w") as f:
        f.write(dumps(normalize(cfg)))
    os.replace(file + ".part", file)


def engine_data(cfg, page):
    """The engine's layouts.toml data for one page: every panel an item, the page the default layout."""
    items, left = {}, []
    for i, p in enumerate(cfg["pages"][page]["panels"]):
        name = f"p{i}"
        if p["type"] == "keys":
            left.append("group:keys")
            continue
        if p["type"] == "clock":
            items[name] = {"widget": "core.clock", "width": p["width"] or 100, "size": p["size"] or 20}
        else:
            items[name] = {"widget": "gw2.panel", **p}
        left.append(name)
    for i, k in enumerate(cfg["keys"]):
        items[f"k{i}"] = {"widget": "core.button", "text": k["label"], "keys": k["keys"], "width": 110}
    right = ["gw2.dots"] if cfg["settings"]["page_dots"] and len(cfg["pages"]) > 1 else []
    return {"settings": {"touch_flip": cfg["settings"]["touch_flip"], "group_timeout": 15},
            "items": items,
            "groups": {"keys": {"text": "Keys", "toggle": True, "items": [f"k{i}" for i in range(len(cfg["keys"]))]}},
            "layouts": {"default": {"left": left, "right": right}}}
