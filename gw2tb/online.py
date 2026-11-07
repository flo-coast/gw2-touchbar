# online.py: the account and everyday panels' data, gathered by gw2-touchbar-feed as the user (adapted from
# letterbox's extras.py, which keeps its own copy). Network data comes from Poller threads that only run while
# a page uses the panel. Item and currency icons, team logos and album covers are cached as files in
# ~/.cache/gw2-touchbar/icons, and the state hands their paths to the bar.
import base64
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib       # noqa: E402

API = "https://api.guildwars2.com/v2"
CACHE = os.environ.get("GW2TB_WEBCACHE") or os.path.expanduser("~/.cache/gw2-touchbar")
TEAM_COLOR_IDS = {9: "blue", 55: "green", 376: "red"}       # MumbleLink identity team_color_id
UPOWER_KINDS = {2: "laptop", 5: "mouse", 6: "keyboard", 12: "controller", 17: "headset", 18: "speakers",
                19: "headphones", 21: "pen", 24: "touchpad"}
WMO = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "cloudy", 45: "fog", 48: "fog", 51: "drizzle",
       53: "drizzle", 55: "drizzle", 61: "rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
       67: "freezing rain", 71: "snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "showers",
       81: "showers", 82: "heavy showers", 85: "snow showers", 86: "snow showers", 95: "thunderstorm",
       96: "thunderstorm", 99: "thunderstorm"}


def http_json(url, key=None, timeout=10):
    if key:
        url += ("&" if "?" in url else "?") + "access_token=" + key
    req = urllib.request.Request(url, headers={"User-Agent": "gw2-touchbar"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def api(path, key=None):
    return http_json(f"{API}/{path}", key)


def load_json(name, default):
    try:
        return json.load(open(os.path.join(CACHE, name)))
    except (OSError, ValueError):
        return default


def save_json(name, data):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    with open(p + ".part", "w") as fh:
        json.dump(data, fh)
    os.replace(p + ".part", p)


def icon(url):
    """Local file of an image URL (https or file://), downloaded once in the background; None until then."""
    if not url:
        return None
    if url.startswith("file://"):
        p = urllib.parse.unquote(url[7:])
        return p if os.path.exists(p) else None
    d = os.path.join(CACHE, "icons")
    p = os.path.join(d, hashlib.sha1(url.encode()).hexdigest()[:20] + ".png")
    if os.path.exists(p):
        return p
    if url not in _fetching:
        _fetching.add(url)
        threading.Thread(target=_download, args=(url, d, p), daemon=True).start()
    return None


_fetching = set()


def _download(url, d, p):
    try:
        os.makedirs(d, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "gw2-touchbar"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read(2_000_000)
        with open(p + ".part", "wb") as f:
            f.write(data)
        os.replace(p + ".part", p)
    except Exception:
        time.sleep(60)
    finally:
        _fetching.discard(url)


class Poller:
    """fetch() every `every` seconds in a thread while touch() was called in the last two minutes."""

    def __init__(self, fetch, every):
        self.fetch, self.every = fetch, every
        self.value, self.err = None, "loading…"
        self.last_touch, self.thread = 0, None
        self.key, self.wake = None, threading.Event()

    def setting(self, key):
        if key != self.key:
            self.key = key
            self.value, self.err = None, "loading…"
            self.wake.set()

    def touch(self):
        self.last_touch = time.monotonic()
        if not self.thread or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.loop, daemon=True)
            self.thread.start()
        return self

    def loop(self):
        while time.monotonic() - self.last_touch < 120:
            try:
                self.value, self.err = self.fetch(), ""
            except urllib.error.HTTPError as ex:
                self.err = "API key refused (needs account, wallet, progression, tradingpost)" \
                    if ex.code in (401, 403) else f"GW2 API: {ex.code}"
            except Exception as ex:                  # network down, API busy: show it, try again later
                self.err = str(ex)[:80]
            self.wake.wait(self.every)
            self.wake.clear()

    def out(self):
        return self.value if self.value is not None else {"err": self.err}


# ---------- the account panels ----------
def chat_link_item(text):
    """Item id from an in-game chat link ([&AgH0TQAA]) or a plain number."""
    text = text.strip()
    if text.isdigit():
        return int(text)
    m = re.match(r"^\[&([A-Za-z0-9+/=]+)\]$", text)
    if not m:
        return None
    raw = base64.b64decode(m.group(1) + "==")
    return raw[2] | raw[3] << 8 | raw[4] << 16 if len(raw) >= 5 and raw[0] == 2 else None   # 2 = item


def parse_coins_text(copper):
    """copper -> '1g20s5c' (the watchlist's target, as typed back into the settings)."""
    g, s, c = copper // 10000, copper // 100 % 100, copper % 100
    return "".join(f"{v}{u}" for v, u in ((g, "g"), (s, "s"), (c, "c")) if v) or "0c"


def parse_coins(text):
    """'1g 20s 5c', '12s', '1.5g' or plain copper -> copper (None if unreadable)."""
    text = text.strip().lower().replace(",", ".")
    if not text:
        return 0
    if re.fullmatch(r"\d+", text):
        return int(text)
    total, found = 0, False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([gsc])", text):
        total += float(num) * {"g": 10000, "s": 100, "c": 1}[unit]
        found = True
    return int(round(total)) if found else None


class Online:
    def __init__(self):
        self.cfg = {}
        self.pollers = {}
        self.wallet_start = None
        self.wvw_team = None
        self.music = None
        self.batt, self.batt_at = None, -99.0
        self.notes, self.notify_conn = [], None

    def poll(self, name, fetch, every, key):
        if name not in self.pollers:
            self.pollers[name] = Poller(fetch, every)
        pl = self.pollers[name]
        pl.setting(key)
        return pl.touch().out()

    @property
    def key(self):
        return self.cfg.get("api_key", "")

    def need_key(self):
        return None if self.key else {"err": "add a GW2 API key in the settings"}

    def gather(self, cfg, used, game):
        """{panel type: data} for the panel types any page uses."""
        self.cfg, out = cfg, {}
        if "wvw" in used:
            out["wvw"] = self.need_key() or self.poll("wvw", self.fetch_wvw, 30, self.key)
            if "err" not in out["wvw"] and game and not out["wvw"].get("mine"):
                out["wvw"]["mine"] = TEAM_COLOR_IDS.get(game.get("team_color_id"))
        if "tp" in used:
            out["tp"] = self.poll("tp", self.fetch_tp, 120, (self.key, json.dumps(cfg.get("tp_watch", []))))
        if "earnings" in used:
            out["earnings"] = self.need_key() or self.poll("wallet", self.fetch_wallet, 60, self.key)
        if "vault" in used:
            out["vault"] = self.need_key() or self.poll("vault", self.fetch_vault, 300, self.key)
        if "gems" in used:
            out["gems"] = self.poll("gems", self.fetch_gems, 300, "")
        if "weather" in used:
            city = cfg.get("weather_city", "").strip()
            out["weather"] = self.poll("weather", self.fetch_weather, 900, city) if city else \
                {"err": "set your town in the settings"}
        if "scores" in used:
            out["scores"] = self.poll("scores", self.fetch_scores, 60, cfg.get("sports_league", ""))
        if "music" in used:
            out["music"] = self.now_playing()
        if "battery" in used:
            if time.monotonic() - self.batt_at > 30:
                self.batt, self.batt_at = self.batteries(), time.monotonic()
            out["battery"] = self.batt
        if "notify" in used or cfg.get("notify_popup"):
            out["notes"] = self.notifications()
        return out

    def fetch_wvw(self):
        if self.wvw_team is None:
            # the team only comes with a newer schema version; "world" can point to another matchup since
            # the WvW restructuring, so it isn't used
            acc = api("account?v=2024-07-20T01:00:00Z", self.key)
            self.wvw_team = (acc.get("wvw") or {}).get("team_id") or 0
        if not self.wvw_team:
            return {"err": "no WvW team on this account yet"}
        try:
            m = api(f"wvw/matches?world={self.wvw_team}")
        except urllib.error.HTTPError:
            return {"err": "no matchup found for your team"}
        mine = next((c for c, ws in m.get("all_worlds", {}).items() if self.wvw_team in ws), None)
        start = datetime.fromisoformat(m["start_time"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(m["end_time"].replace("Z", "+00:00"))
        n = m["skirmishes"][-1]["id"] if m.get("skirmishes") else 0
        ppt = {"red": 0, "green": 0, "blue": 0}
        for mp in m.get("maps", []):
            for o in mp["objectives"]:
                c = o.get("owner", "").lower()
                if c in ppt:
                    ppt[c] += o.get("points_tick", 0)
        return {"mine": mine, "vp": m["victory_points"], "sk": m["skirmishes"][-1]["scores"] if n else {},
                "n": n, "of": round((end - start).total_seconds() / 7200),
                "ends": (start + timedelta(hours=2 * n)).timestamp(), "ppt": ppt}

    def fetch_tp(self):
        watch = [w for w in self.cfg.get("tp_watch", []) if w.get("id")]
        out = {"items": [], "delivery": None}
        if self.key:
            try:
                out["delivery"] = api("commerce/delivery", self.key)
            except urllib.error.HTTPError:
                pass
        if not watch:
            return out if out["delivery"] else {"err": "add items in the settings"}
        ids = ",".join(str(w["id"]) for w in watch)
        items = {i["id"]: i for i in api(f"items?ids={ids}")}
        prices = {p["id"]: p for p in api(f"commerce/prices?ids={ids}")}
        hist = load_json("tp-history.json", {})              # first price seen each day, for the trend
        today, yday = str(date.today()), str(date.today() - timedelta(days=1))
        for w in watch:
            p = prices.get(w["id"], {})
            buy, sell = p.get("buys", {}).get("unit_price", 0), p.get("sells", {}).get("unit_price", 0)
            hist.setdefault(today, {}).setdefault(str(w["id"]), [buy, sell])
            prev = hist.get(yday, {}).get(str(w["id"]))
            it = items.get(w["id"], {})
            out["items"].append({"id": w["id"], "name": it.get("name", f"item {w['id']}"), "icon_url": it.get("icon"),
                                 "buy": buy, "sell": sell, "prev": prev[1] if prev else None,
                                 "target": w.get("target", 0)})
        for d in sorted(hist)[:-8]:
            del hist[d]
        save_json("tp-history.json", hist)
        return out

    def fetch_wallet(self):
        names = load_json("gw2-currencies.json", {})
        if not names:
            names = {str(c["id"]): {"name": c["name"], "icon": c["icon"]} for c in api("currencies?ids=all")}
            save_json("gw2-currencies.json", names)
        now = {str(x["id"]): x["value"] for x in api("account/wallet", self.key)}
        if self.wallet_start is None:                 # the first look is the session's start
            self.wallet_start = (time.time(), now)
        t0, start = self.wallet_start
        diff = {k: now.get(k, 0) - start.get(k, 0) for k in set(now) | set(start)}
        others = sorted(((k, v) for k, v in diff.items() if k != "1" and v), key=lambda z: -abs(z[1]))[:3]
        return {"gold": diff.get("1", 0), "since": t0,
                "others": [{"name": names.get(k, {}).get("name", k), "value": v,
                            "icon_url": names.get(k, {}).get("icon")} for k, v in others]}

    def fetch_vault(self):
        out = {}
        for per in ("daily", "weekly"):
            v = api(f"account/wizardsvault/{per}", self.key) or {}
            objs = v.get("objectives", [])
            out[per] = {"done": sum(1 for o in objs if o.get("progress_current", 0) >= o.get("progress_complete", 1)),
                        "of": len(objs), "claimed": bool(v.get("meta_reward_claimed")),
                        "open": [o.get("title", "") for o in objs
                                 if o.get("progress_current", 0) < o.get("progress_complete", 1)][:3]}
        return out

    def fetch_gems(self):
        rate = api("commerce/exchange/coins?quantity=1000000")            # what 100 gold buy
        hist = load_json("gem-history.json", {})
        hist.setdefault(str(date.today()), rate["coins_per_gem"])
        for d in sorted(hist)[:-8]:
            del hist[d]
        save_json("gem-history.json", hist)
        return {"per_gem": rate["coins_per_gem"], "for_100g": rate["quantity"],
                "yesterday": hist.get(str(date.today() - timedelta(days=1)))}

    def fetch_weather(self):
        city = self.cfg.get("weather_city", "").strip()
        geo = load_json("geo.json", {})
        if city not in geo:
            g = http_json("https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + urllib.parse.quote(city))
            if not g.get("results"):
                return {"err": f"'{city}' not found"}
            r = g["results"][0]
            geo[city] = [r["latitude"], r["longitude"], r["name"]]
            save_json("geo.json", geo)
        lat, lon, name = geo[city]
        w = http_json(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&timezone=auto"
                      "&current=temperature_2m,weather_code,wind_speed_10m&hourly=precipitation_probability"
                      "&daily=temperature_2m_max,temperature_2m_min&forecast_days=1")
        cur, day, hrs = w["current"], w["daily"], w.get("hourly", {})
        now_h = datetime.now().hour
        rain = [(t[11:16], p) for t, p in zip(hrs.get("time", []), hrs.get("precipitation_probability", []))
                if int(t[11:13]) > now_h and p is not None and p >= 50]
        return {"place": name, "temp": cur["temperature_2m"], "sky": WMO.get(cur["weather_code"], ""),
                "min": day["temperature_2m_min"][0], "max": day["temperature_2m_max"][0],
                "wind": cur["wind_speed_10m"], "rain": rain[0] if rain else None}

    def fetch_scores(self):
        league = self.cfg.get("sports_league", "basketball/nba")
        if not re.fullmatch(r"[a-z\-]+/[a-z0-9.\-]+", league):
            return {"err": "league like basketball/nba"}
        data = http_json(f"https://site.api.espn.com/apis/site/v2/sports/{league}/scoreboard")
        games = []
        for ev in data.get("events", []):
            comp = ev["competitions"][0]
            teams = sorted(comp["competitors"], key=lambda c: c.get("homeAway") != "away")          # away first
            games.append({"teams": [[t["team"].get("abbreviation", "?"), t.get("score", ""), t["team"].get("logo")]
                                    for t in teams], "state": ev["status"]["type"].get("state"),
                          "detail": ev["status"]["type"].get("shortDetail", ""), "start": ev.get("date")})
        self.pollers["scores"].every = 30 if any(g["state"] == "in" for g in games) else 600       # live: often
        fav = self.cfg.get("sports_team", "").strip().upper()
        games.sort(key=lambda g: (not any(t[0] == fav for t in g["teams"]) if fav else 0,
                                  {"in": 0, "pre": 1, "post": 2}.get(g["state"], 3), g["start"] or ""))
        return {"games": games, "fav": fav}

    # ---------- the desktop: music, batteries, notifications (session and system bus) ----------
    def now_playing(self):
        best = None
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION)
            names = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                  "ListNames", None, None, Gio.DBusCallFlags.NONE, 500, None).unpack()[0]
            for n in (n for n in names if n.startswith("org.mpris.MediaPlayer2.")):
                try:
                    pr = bus.call_sync(n, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "GetAll",
                                       GLib.Variant("(s)", ("org.mpris.MediaPlayer2.Player",)), None,
                                       Gio.DBusCallFlags.NONE, 500, None).unpack()[0]
                except GLib.Error:
                    continue
                md = pr.get("Metadata", {})
                if not md.get("xesam:title"):
                    continue
                cur = {"player": n, "status": pr.get("PlaybackStatus", ""), "title": md["xesam:title"],
                       "artist": ", ".join(md.get("xesam:artist") or []), "icon_url": md.get("mpris:artUrl", ""),
                       "length": (md.get("mpris:length") or 0) / 1e6, "pos": (pr.get("Position") or 0) / 1e6,
                       "app": n.split(".")[3]}
                if best is None or (cur["status"] == "Playing" and best["status"] != "Playing"):
                    best = cur
        except GLib.Error:
            pass
        self.music = best
        return best or {"err": "nothing playing"}

    def music_toggle(self):
        if self.music:
            Gio.bus_get_sync(Gio.BusType.SESSION).call(self.music["player"], "/org/mpris/MediaPlayer2",
                                                       "org.mpris.MediaPlayer2.Player", "PlayPause", None, None,
                                                       Gio.DBusCallFlags.NONE, 500, None, None)

    def batteries(self):
        out = []
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
            devs = bus.call_sync("org.freedesktop.UPower", "/org/freedesktop/UPower", "org.freedesktop.UPower",
                                 "EnumerateDevices", None, None, Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
            for dev in devs:
                p = bus.call_sync("org.freedesktop.UPower", dev, "org.freedesktop.DBus.Properties", "GetAll",
                                  GLib.Variant("(s)", ("org.freedesktop.UPower.Device",)), None,
                                  Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
                if p.get("Type") in (0, 1) or not p.get("IsPresent", True):          # unknown, power supply
                    continue
                kind = UPOWER_KINDS.get(p.get("Type"), "device")
                out.append({"kind": kind, "name": p.get("Model") or kind, "pct": p.get("Percentage", 0),
                            "charging": p.get("State") == 1, "full": p.get("State") == 4})
        except GLib.Error:
            pass
        return sorted(out, key=lambda b: b["pct"]) or [{"err": "no devices with a battery"}]

    def notifications(self):
        """The latest desktop notifications. A second session bus connection becomes a monitor for Notify
        calls (like dbus-monitor); nothing is changed or answered."""
        if self.notify_conn is None:
            try:
                addr = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
                c = Gio.DBusConnection.new_for_address_sync(
                    addr, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                    | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
                c.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus.Monitoring",
                            "BecomeMonitor", GLib.Variant("(asu)", (["type='method_call',interface="
                                                                     "'org.freedesktop.Notifications',member='Notify'"], 0)),
                            None, Gio.DBusCallFlags.NONE, 1000, None)
                c.add_filter(self._on_notify)   # only now: a monitor keeps every message for itself
                self.notify_conn = c
            except GLib.Error:
                self.notify_conn = False
        return self.notes

    def _on_notify(self, _c, msg, _incoming):
        try:
            if msg.get_member() == "Notify" and msg.get_body() is not None:
                app, _id, _icon, summary, body = msg.get_body().unpack()[:5]
                body = re.sub(r"<[^>]+>", "", body or "").replace("\n", " ").strip()
                body = re.sub(r"^\S*discord\.com\s*", "", body, flags=re.IGNORECASE)   # Chrome puts the site first
                self.notes = ([{"app": app or "?", "summary": summary, "body": body, "t": time.time()}]
                              + self.notes)[:10]
        except Exception:
            pass
        return None
