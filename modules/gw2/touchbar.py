"""gw2: the Touch Bar panels while Guild Wars 2 runs.

Widget gw2.panel takes a panel from the user's config (type, width, color, size, style, sub; see
gw2tb/config.py) and draws it from the state gw2-touchbar-feed gathers. gw2.dots shows the page.
Scenes: "bosses" (long press on the boss panel), "note" (a new desktop notification matching the
notify_filter setting, not in combat).
The daemon runs as root and only draws; everything from the user's session comes through gw2-touchbar-feed.
"""
import os
import re
import time
import weakref
from datetime import datetime, timedelta, timezone

from gi.repository import GLib

from macarchy_touchbar.geometry import Rect
from macarchy_touchbar.layout import Layout, Row
from macarchy_touchbar.widgets import Label, Widget

from gw2tb import config, events, mumble, state

ICONS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "icons")
SECTIONS = [s.strip() for s in os.environ.get("GW2TB_EVENTS", "World bosses,Hard world bosses").split(",") if s.strip()]
LEAD_MIN = 5          # a boss turns amber this many minutes before it starts
DARK = (0.08, 0.08, 0.08)
PROFESSIONS = {1: ("Guardian", (0.45, 0.76, 0.85)), 2: ("Warrior", (1.0, 0.82, 0.4)),
               3: ("Engineer", (0.82, 0.61, 0.35)), 4: ("Ranger", (0.55, 0.86, 0.51)),
               5: ("Thief", (0.75, 0.56, 0.58)), 6: ("Elementalist", (0.96, 0.54, 0.53)),
               7: ("Mesmer", (0.71, 0.47, 0.84)), 8: ("Necromancer", (0.32, 0.65, 0.44)),
               9: ("Revenant", (0.82, 0.43, 0.35))}
BOTTLENECK = {"GPU-bound": (0.95, 0.42, 0.36), "CPU-bound": (0.36, 0.62, 0.98), "headroom": (0.4, 0.82, 0.62)}


def fmt(secs):
    secs = max(0, int(secs))
    h, r = divmod(secs, 3600)
    return f"{h}:{r // 60:02d}:{r % 60:02d}" if h else f"{r // 60}:{r % 60:02d}"


def rgb(hexstr):
    return tuple(int(hexstr[i:i + 2], 16) / 255 for i in (1, 3, 5)) if hexstr else None


def on(c):
    """Text colour that reads on background c: dark on light colours, else white."""
    return DARK if c and 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2] > 0.55 else (1, 1, 1)


def lighter(c, k=0.45):
    return tuple(x + (1 - x) * k for x in c)


class Panel(Widget):
    """One configured panel. Subclasses draw; this handles size, colours and the two text lines."""
    big = 20                                     # default px of the main line

    def __init__(self, api=None, module=None, **p):
        super().__init__(api, **p)
        self.m, self.p = module, config.panel(p)
        self.width = self.p["width"]
        self.stretch = 0 if self.width else 1
        self.color = rgb(self.p["color"])
        self.size = self.p["size"] or self.big

    def measure(self):
        return self.width

    @property
    def t(self):
        return self.api.theme

    @property
    def s(self):
        return self.m.source.get()

    def bg(self, painter, cr, accent=None):
        """Pill in the panel's colour; an accent (state colour like "in combat") wins. -> text colour."""
        c = self.bg_color = accent or self.color
        painter.pill(cr, self.rect, self.t.PILL_PRESSED if self.pressed else (c or self.t.PILL))
        return on(c) if c else self.t.FG

    def lines(self, painter, cr, main, sub, fg, sub_fg=None, x0=None, align="center"):
        r = self.rect
        x = x0 if x0 is not None else r.x + 10
        w = r.right - x - 10
        if self.p["sub"] and sub:
            painter.text(cr, main, Rect(x, r.y + 3, w, 34), size=self.size, color=fg, align=align)
            painter.text(cr, sub, Rect(x, r.y + 35, w, 22), size=max(11, round(self.size * 0.62)),
                         color=sub_fg or (fg if getattr(self, "bg_color", None) else self.t.FG_DIM), align=align)
        else:
            painter.text(cr, main, Rect(x, r.y, w, r.h), size=round(self.size * 1.15), color=fg, align=align)


class Num(Panel):
    """A number with unit, its second line and/or a graph of the last graph_seconds."""
    big = 22

    def draw(self, cr, painter):
        r, c, s = self.rect, config.CATALOG[self.p["type"]], self.s
        fg = self.bg(painter, cr)
        val = (s.get("v") or {}).get(c["num"])
        txt = "-" if val is None else c.get("fmt", "{:.0f}").format(val) + (f" {c['unit']}" if c["unit"] else "")
        sub = f"{c['title']} · {(s.get('sub') or {}).get(c['num'], '')}".rstrip(" ·")
        style = self.p["style"]
        if style in ("graph", "both"):
            line = lighter(self.color) if self.color else self.t.ACCENT_BLUE
            hist = (s.get("hist") or {}).get(c["num"], [])[-self.m.graph_seconds:]
            top = r.y + (26 if style == "graph" else 34)
            self.graph(cr, Rect(r.x + 6, top, r.w - 12, r.bottom - 6 - top), hist, c["max"], line)
        if style == "graph":
            painter.text(cr, f"{c['title']} {txt}", Rect(r.x + 10, r.y + 2, r.w - 20, 24),
                         size=max(11, round(self.size * 0.62)), color=fg, align="left")
        elif style == "both":
            painter.text(cr, txt, Rect(r.x + 10, r.y + 2, r.w - 20, 32), size=self.size, color=fg, align="left")
            painter.text(cr, c["title"], Rect(r.x + 10, r.y + 2, r.w - 20, 32), size=11,
                         color=self.t.FG_DIM if fg != DARK else DARK, align="right")
        else:
            self.lines(painter, cr, txt, sub, fg)

    @staticmethod
    def graph(cr, box, hist, vmax, col):
        pts = [(i, v) for i, v in enumerate(hist) if v is not None]
        if len(pts) < 2 or box.w <= 0 or box.h <= 0:
            return
        top = max(vmax, max(v for _, v in pts))
        n = max(len(hist) - 1, 1)
        cr.save()
        cr.move_to(box.x + pts[0][0] / n * box.w, box.bottom)
        for i, v in pts:
            cr.line_to(box.x + i / n * box.w, box.bottom - v / top * box.h)
        cr.line_to(box.x + pts[-1][0] / n * box.w, box.bottom)
        cr.close_path()
        cr.set_source_rgba(*col, 0.25)
        cr.fill_preserve()
        cr.new_path()
        for k, (i, v) in enumerate(pts):
            (cr.move_to if k == 0 else cr.line_to)(box.x + i / n * box.w, box.bottom - v / top * box.h)
        cr.set_source_rgb(*col)
        cr.set_line_width(2)
        cr.stroke()
        cr.restore()


class Char(Panel):
    big = 18

    def draw(self, cr, painter):
        r, g = self.rect, self.s.get("game")
        fg = self.bg(painter, cr)
        if not g:
            self.lines(painter, cr, "GW2 · not in a map", "", self.t.FG_DIM)
            return
        x = r.x + 12
        icon = os.path.join(ICONS, f"{g.get('profession')}.png")
        if os.path.exists(icon) and painter.image(cr, icon, Rect(x, r.y + 12, 36, 36), radius=0):
            x += 46
        bits = [g.get("spec") or g.get("profession") or "",
                f"facing {mumble.compass(g.get('heading'))}" if g.get("heading") is not None else "",
                g.get("mount") or "", "commander" if g.get("commander") else ""]
        self.lines(painter, cr, g.get("map_name") or f"map {g.get('map_id')}", " · ".join(b for b in bits if b),
                   fg, x0=x, align="left")


class Combat(Panel):
    def draw(self, cr, painter):
        c = self.s.get("combat") or {}
        now = time.time()
        cur = now - c["since"] if c.get("since") else 0
        fg = self.bg(painter, cr, self.t.ACCENT_RED if c.get("since") else None)
        main = f"combat {fmt(cur)}" if c.get("since") else "out of combat"
        self.lines(painter, cr, main, f"session {fmt((c.get('total') or 0) + cur)}",
                   fg if c.get("since") else self.t.FG_DIM)

    def on_tap(self, x, y):
        state.send("combat.reset")


class Boss(Panel):
    big = 19

    def draw(self, cr, painter):
        nxt = self.m.next_event()
        if not nxt:
            self.lines(painter, cr, "no boss data", "", self.bg(painter, cr))
            return
        a, b, _section, seg = nxt
        now = datetime.now(timezone.utc)
        if a <= now:
            accent, line = self.t.ACCENT_GREEN, f"{seg['name']}  now · {fmt((b - now).total_seconds())} left"
        else:
            soon = (a - now).total_seconds() <= LEAD_MIN * 60
            accent, line = (self.t.ACCENT_ORANGE if soon else None), f"{seg['name']}  in {fmt((a - now).total_seconds())}"
        fg = self.bg(painter, cr, accent)
        self.lines(painter, cr, line, "tap: copy waypoint" + (f"  {self.m.copied}" if self.m.copied else ""), fg)

    def on_tap(self, x, y):
        nxt = self.m.next_event()
        if nxt and nxt[3].get("chatlink"):
            self.m.copy(nxt[3]["chatlink"], nxt[3]["name"])

    def on_long_press(self, x, y):
        self.api.show_scene("bosses", priority=60, timeout=8)


class Timeline(Panel):
    """World bosses of the next two hours on a time axis; tap copies the next one's waypoint."""
    big = 14
    HORIZON = 120

    def draw(self, cr, painter):
        r, t = self.rect, self.t
        self.bg(painter, cr)
        now = datetime.now(timezone.utc)
        x0, w = r.x + 8, r.w - 16
        px = lambda d: x0 + (d - now).total_seconds() / 60 / self.HORIZON * w
        for k in range(0, self.HORIZON + 1, 30):          # grid every 30 min, labelled with the local time
            tick = now + timedelta(minutes=k)
            gx = x0 + k / self.HORIZON * w
            cr.set_source_rgb(*t.RAIL)
            cr.rectangle(gx, r.y + 44, 1, 12)
            cr.fill()
            if k < self.HORIZON:
                painter.text(cr, tick.astimezone().strftime("%H:%M"), Rect(gx + 3, r.y + 42, 60, 16), size=11,
                             color=t.FG_DIM, align="left")
        blocks, lane_end = [], [x0, x0]           # two lanes: world bosses and hard bosses overlap
        for a, b, _s, seg in events.upcoming(self.m.sections, now, self.HORIZON):
            bx, ex = max(px(a), x0), min(px(b), x0 + w)
            if ex - bx < 3:
                continue
            lane = 0 if bx >= lane_end[0] - 1 else 1
            lane_end[lane] = max(lane_end[lane], ex)
            blocks.append((lane, bx, ex, a, seg))
        two = any(lane for lane, *_ in blocks)
        for lane, bx, ex, a, seg in blocks:
            running, soon = a <= now, 0 < (a - now).total_seconds() <= LEAD_MIN * 60
            col = t.ACCENT_GREEN if running else (t.ACCENT_ORANGE if soon else (self.color or (0.33, 0.36, 0.42)))
            box = Rect(bx, r.y + 4 + lane * 19, ex - bx - 2, 17) if two else Rect(bx, r.y + 6, ex - bx - 2, 34)
            painter.pill(cr, box, col, radius=4)
            painter.text(cr, seg["name"], Rect(box.x + 4, box.y, box.w - 8, box.h),
                         size=min(self.size, 12) if two else self.size, color=on(col), align="left")

    def on_tap(self, x, y):
        Boss.on_tap(self, x, y)


class Timer(Panel):
    def draw(self, cr, painter):
        tm = self.s.get("timer") or {}
        start = tm.get("start")
        fg = self.bg(painter, cr, self.t.ACCENT_BLUE if start else None)
        runs = tm.get("runs") or []
        if start:
            self.lines(painter, cr, fmt(time.time() - start), "running · tap to stop", fg)
        else:
            self.lines(painter, cr, fmt(runs[0]) if runs else "run timer",
                       ("last runs " + " ".join(fmt(x) for x in runs[1:4])) if len(runs) > 1 else "tap to start", fg)

    def on_tap(self, x, y):
        state.send("timer.toggle")


class Playtime(Panel):
    def draw(self, cr, painter):
        pl = self.s.get("play") or {}
        fg = self.bg(painter, cr)
        self.lines(painter, cr, f"today {fmt(pl.get('today') or 0)}", f"this session {fmt(pl.get('session') or 0)}", fg)


class Squad(Panel):
    big = 18

    def draw(self, cr, painter):
        r, b = self.rect, self.s.get("squad")
        fg = self.bg(painter, cr)
        if not b or not b.get("rtapi"):
            self.lines(painter, cr, "Squad", "needs the letterbox bridge + RealTime API in Nexus", self.t.FG_DIM)
            return
        members = b.get("members", [])
        kind = {1: "Party", 2: "Squad", 3: "Squad"}.get(b.get("group_type"), "Solo")
        me = next((m for m in members if m.get("self")), {})
        here = [m for m in members if m.get("here") or m.get("self")]
        cmd = next((m for m in members if m.get("commander")), None)
        head = f"{kind} {b.get('group_count') or len(members)}" if kind != "Solo" else "Solo"
        if cmd:
            head += f" · tag {cmd.get('name') or cmd.get('account')}"
        if kind == "Squad" and me.get("sub"):
            head += f" · sub {me['sub']}"
        painter.text(cr, head, Rect(r.x + 10, r.y + 3, r.w - 20, 30), size=self.size, color=fg, align="left")
        counts = {}
        for m in here:
            counts[m.get("prof", 0)] = counts.get(m.get("prof", 0), 0) + 1
        bx, bw = r.x + 10, r.w - 20
        for prof in sorted(counts, key=lambda p: -counts[p]):
            name, col = PROFESSIONS.get(prof, ("?", (0.4, 0.4, 0.4)))
            sw = bw * counts[prof] / max(1, len(here))
            painter.pill(cr, Rect(bx, r.y + 36, max(1, sw - 2), 18), col, radius=3)
            if sw > 44:
                painter.text(cr, f"{counts[prof]} {name[:3]}", Rect(bx + 3, r.y + 36, sw - 6, 18), size=11,
                             color=DARK, align="left")
            bx += sw


class Bottleneck(Panel):
    def draw(self, cr, painter):
        kind, why = self.s.get("bottleneck") or ["-", "no data"]
        fg = self.bg(painter, cr, BOTTLENECK.get(kind) if kind != "headroom" else None)
        self.lines(painter, cr, kind, why, fg)


class Sensors(Panel):
    def draw(self, cr, painter):
        v = self.s.get("v") or {}
        hot = (v.get("gtemp") or 0) >= 90
        fg = self.bg(painter, cr)
        gpu = f"GPU {v['gtemp']:.0f}°" if v.get("gtemp") is not None else "GPU -"
        cpu = f"CPU {v['cpu'] / 1000:.1f} GHz" if v.get("cpu") is not None else "CPU -"
        self.lines(painter, cr, gpu, cpu, self.t.ACCENT_ORANGE if hot else fg)


class Spacer(Panel):
    def draw(self, cr, painter):
        if self.color:
            self.bg(painter, cr)


class Dots(Widget):
    """Which page is shown: one dot per page (Module.page, set by gw2tb.barbuild.Pages)."""

    def __init__(self, api=None, module=None, **p):
        super().__init__(api, **p)
        self.m = module

    def measure(self):
        return 14 * self.m.page[1] + 10

    def draw(self, cr, painter):
        r = self.rect
        cur, n = self.m.page
        x = r.x + (r.w - 14 * n) / 2 + 7
        for i in range(n):
            cr.set_source_rgb(*(self.api.theme.FG if i == cur else self.api.theme.RAIL))
            cr.arc(x + 14 * i, r.y + r.h / 2, 4 if i == cur else 3, 0, 6.2832)
            cr.fill()

GOLD, SILVER, COPPER = "#e8c24a", "#c9ccd1", "#c87f4a"
TEAM = {"red": (0.92, 0.33, 0.3), "green": (0.38, 0.8, 0.42), "blue": (0.36, 0.6, 0.96)}


def esc(text):
    return GLib.markup_escape_text(str(text))


def coins(copper, sign=False):
    """Pango markup like 12g 34s 5c in the coin colours."""
    neg, c = copper < 0, abs(int(copper))
    g, sv, cp = c // 10000, c // 100 % 100, c % 100
    parts = [f'<span foreground="{col}">{v}{u}</span>' for v, u, col in
             ((g, "g", GOLD), (sv, "s", SILVER), (cp, "c", COPPER)) if v] or [f'<span foreground="{COPPER}">0c</span>']
    return ("-" if neg else "+" if sign else "") + " ".join(parts)


def hm(secs):
    return f"{int(secs // 3600)}:{int(secs % 3600 // 60):02d}"


class Online(Panel):
    """A panel whose data comes from the feed's online part: shows the error or "waiting" by itself."""
    key = None

    def data(self, painter, cr):
        d = self.s.get(self.key or self.p["type"])
        if not d or (isinstance(d, dict) and d.get("err")) or (isinstance(d, list) and d and d[0].get("err")):
            self.bg(painter, cr)
            why = (d.get("err") if isinstance(d, dict) else d[0].get("err")) if d else "waiting for data"
            self.lines(painter, cr, config.CATALOG[self.p["type"]]["title"], why, self.t.FG_DIM)
            return None
        return d

    def icon_text(self, painter, cr, x, y, h, path, markup, size, color, w):
        """An icon (if cached) and markup text after it -> x after both."""
        if path and painter.image(cr, path, Rect(x, y + (h - size - 6) / 2, size + 6, size + 6), radius=3):
            x += size + 12
        painter.text(cr, markup, Rect(x, y, w - (x - self.rect.x), h), size=size, color=color, align="left",
                     markup=True)


class Wvw(Online):
    def draw(self, cr, painter):
        d = self.data(painter, cr)
        if not d:
            return
        r, fg = self.rect, self.bg(painter, cr)
        order = sorted(d["vp"], key=lambda c: -d["vp"][c])
        left = max(0, d["ends"] - time.time())
        sub = f"skirmish {d['n']}/{d['of']} · {hm(left)} left"
        painter.text(cr, sub, Rect(r.x + 10, r.y + 38, r.w - 20, 20), size=12, color=self.t.FG_DIM, align="left")
        top, cw = max(1, max(d["sk"].values() or [1])), (r.w - 20) / 3
        for i, c in enumerate(order):
            x = r.x + 10 + i * cw
            mine = c == d.get("mine")
            bw = (cw - 8) * d["sk"].get(c, 0) / top
            cr.set_source_rgba(*TEAM[c], 0.95 if mine else 0.45)
            cr.rectangle(x, r.y + 30, max(2, bw), 5)
            cr.fill()
            painter.text(cr, f"{'▸ ' if mine else ''}{c.title()} {d['vp'][c]}  +{d['ppt'][c]}",
                         Rect(x, r.y + 3, cw - 6, 28), size=self.size - 3,
                         color=TEAM[c] if not mine else fg, align="left")


class Tp(Online):
    def draw(self, cr, painter):
        d = self.data(painter, cr)
        if not d:
            return
        r, fg = self.rect, self.bg(painter, cr)
        blocks = []
        for it in d.get("items", []):
            trend = ""
            if it.get("prev"):
                ch = (it["sell"] - it["prev"]) / it["prev"] * 100
                trend = f'  <span foreground="{"#5fd16b" if ch >= 0 else "#ef5b4f"}">{ch:+.0f} %</span>'
            hit = it["target"] and it["sell"] and it["sell"] <= it["target"]
            name = f'<span foreground="{GOLD}">{esc(it["name"])}</span>' if hit else esc(it["name"])
            blocks.append((it.get("icon"), f"{name}\n{coins(it['sell'])}{trend}"))
        dl = d.get("delivery") or {}
        if dl.get("coins") or dl.get("items"):
            n = sum(i.get("count", 1) for i in dl.get("items", []))
            blocks.append((None, f"to pick up\n{coins(dl.get('coins', 0))}" + (f"  {n} items" if n else "")))
        if not blocks:
            self.lines(painter, cr, "Trading Post", "nothing to show", self.t.FG_DIM)
            return
        bw = (r.w - 12) / len(blocks)
        for i, (ic, mk) in enumerate(blocks):
            x = r.x + 8 + i * bw
            if ic and painter.image(cr, ic, Rect(x, r.y + 10, 40, 40), radius=4):
                tx = x + 48
            else:
                tx = x + 4
            painter.text(cr, mk, Rect(tx, r.y + 2, x + bw - tx - 6, r.h - 4), size=max(11, self.size - 6),
                         color=fg, align="left", markup=True, ellipsize=False)


class Earnings(Online):
    key = "earnings"

    def draw(self, cr, painter):
        d = self.data(painter, cr)
        if not d:
            return
        fg = self.bg(painter, cr)
        hours = max(1 / 60, (time.time() - d["since"]) / 3600)
        others = " · ".join(f"{o['value']:+,} {esc(o['name'])}".replace(",", " ") for o in d["others"][:2])
        main = coins(d["gold"], sign=True)
        r = self.rect
        painter.text(cr, main, Rect(r.x + 10, r.y + 3, r.w - 20, 34), size=self.size, color=fg, align="left",
                     markup=True)
        if self.p["sub"]:
            painter.text(cr, f"{coins(d['gold'] / hours)} per hour" + (f" · {others}" if others else ""),
                         Rect(r.x + 10, r.y + 35, r.w - 20, 22), size=12, color=self.t.FG_DIM, align="left",
                         markup=True)


class Vault(Online):
    def draw(self, cr, painter):
        d = self.data(painter, cr)
        if not d:
            return
        dy, wk = d["daily"], d["weekly"]
        ready = (dy["done"] == dy["of"] and dy["of"] and not dy["claimed"])
        fg = self.bg(painter, cr, self.t.ACCENT_AMBER if ready else None)
        sub = "daily reward ready to claim" if ready else (dy["open"][0] if dy["open"] else "daily done")
        self.lines(painter, cr, f"daily {dy['done']}/{dy['of']} · weekly {wk['done']}/{wk['of']}", sub, fg)


class Gems(Online):
    def draw(self, cr, painter):
        d = self.data(painter, cr)
        if not d:
            return
        r, fg = self.rect, self.bg(painter, cr)
        painter.text(cr, f"1 gem = {coins(d['per_gem'])}", Rect(r.x + 10, r.y + 3, r.w - 20, 34), size=self.size,
                     color=fg, align="left", markup=True)
        sub = f"100g buy {d['for_100g']} gems"
        if d.get("yesterday"):
            ch = (d["per_gem"] - d["yesterday"]) / d["yesterday"] * 100
            sub += f" · {ch:+.1f} % since yesterday"
        if self.p["sub"]:
            painter.text(cr, sub, Rect(r.x + 10, r.y + 35, r.w - 20, 22), size=12, color=self.t.FG_DIM, align="left")


class Music(Online):
    def draw(self, cr, painter):
        d = self.data(painter, cr)
        if not d:
            return
        r, playing = self.rect, d["status"] == "Playing"
        fg = self.bg(painter, cr)
        x = r.x + 8
        if d.get("icon") and painter.image(cr, d["icon"], Rect(x, r.y + 6, 48, 48), radius=4):
            x += 56
        self.lines(painter, cr, d["title"], f"{d['artist'] or d['app']} · {'playing' if playing else 'paused'}",
                   fg if playing else self.t.FG_DIM, x0=x, align="left")
        if d.get("length"):
            cr.set_source_rgb(*self.t.ACCENT_BLUE)
            cr.rectangle(x, r.bottom - 4, (r.right - 10 - x) * min(1, d["pos"] / d["length"]), 2)
            cr.fill()

    def on_tap(self, x, y):
        state.send("music.toggle")


class Notify(Online):
    key = "notes"

    def draw(self, cr, painter):
        notes = self.s.get("notes") or []
        fg = self.bg(painter, cr)
        if not notes:
            self.lines(painter, cr, "Notifications", "nothing since the game started", self.t.FG_DIM)
            return
        n = notes[0]
        age = time.time() - n["t"]
        when = "now" if age < 60 else f"{int(age // 60)} min ago" if age < 3600 else f"{int(age // 3600)} h ago"
        text = f"{n['summary']}: {n['body']}" if n["body"] else n["summary"]
        self.lines(painter, cr, text, f"{n['app']} · {when}" + (f" · {len(notes) - 1} more" if len(notes) > 1 else ""),
                   fg if age < 60 else self.t.FG_DIM)


class Battery(Online):
    def draw(self, cr, painter):
        d = self.data(painter, cr)
        if not d:
            return
        low = d[0]
        warn = low["pct"] < 15 and not low["charging"]
        fg = self.bg(painter, cr, self.t.ACCENT_RED if warn else None)
        state_txt = " charging" if low["charging"] else " full" if low["full"] else ""
        others = " · ".join(f"{b['kind']} {b['pct']:.0f} %" for b in d[1:3])
        self.lines(painter, cr, f"{low['kind']} {low['pct']:.0f} %{state_txt}", others or low["name"], fg)


class Weather(Online):
    def draw(self, cr, painter):
        d = self.data(painter, cr)
        if not d:
            return
        fg = self.bg(painter, cr)
        rain = f"rain from {d['rain'][0]}" if d.get("rain") else "no rain expected"
        self.lines(painter, cr, f"{d['temp']:.0f} °C {d['sky']}",
                   f"{d['place']} · {d['min']:.0f} to {d['max']:.0f} °C · {rain}", fg)


class Scores(Online):
    def draw(self, cr, painter):
        d = self.data(painter, cr)
        if not d:
            return
        r, fg = self.rect, self.bg(painter, cr)
        games = d["games"]
        if not games:
            self.lines(painter, cr, "Scores", "no games today", self.t.FG_DIM)
            return
        n = max(1, min(len(games), int(r.w // 230)))
        gw = (r.w - 12) / n
        for i, g in enumerate(games[:n]):
            (a, sa, la), (b, sb, lb) = g["teams"][:2]
            x = r.x + 8 + i * gw
            fav = d.get("fav") and d["fav"] in (a, b)
            col = (1.0, 0.82, 0.3) if fav else fg
            if g["state"] == "pre":
                st = datetime.fromisoformat(g["start"].replace("Z", "+00:00")).astimezone()
                score, info = "vs", st.strftime("%H:%M")
            else:
                score, info = f"{sa}:{sb}", g["detail"]
            for k, logo in enumerate((la, lb)):
                if logo:
                    painter.image(cr, logo, Rect(x + k * (gw - 36), r.y + 4, 30, 30), radius=0)
            painter.text(cr, f"{a} {score} {b}", Rect(x + 32, r.y + 4, gw - 70, 30), size=self.size - 2, color=col)
            painter.text(cr, info, Rect(x, r.y + 36, gw - 8, 20), size=11,
                         color=self.t.ACCENT_GREEN if g["state"] == "in" else self.t.FG_DIM)


KINDS = {"char": Char, "combat": Combat, "boss": Boss, "timeline": Timeline, "timer": Timer,
         "playtime": Playtime, "squad": Squad, "bottleneck": Bottleneck, "sensors": Sensors, "spacer": Spacer,
         "wvw": Wvw, "tp": Tp, "earnings": Earnings, "vault": Vault, "gems": Gems, "music": Music,
         "notify": Notify, "battery": Battery, "weather": Weather, "scores": Scores}


class Module:
    def setup(self, api):
        self.api = api
        self.source = state.Source()
        self.sections = events.load(SECTIONS)
        self.graph_seconds = 60
        self.page = (0, 1)             # (current, count), set by gw2tb.barbuild.Pages
        self.settings = {}             # the user's [settings], set by gw2tb.barbuild.Pages
        self.note_t = 0
        self.copied = ""
        self.note = None
        self.widgets = weakref.WeakSet()
        self.in_combat = False
        api.widget("panel", self.make_panel)
        api.widget("dots", lambda a, **p: Dots(a, module=self, **p))
        api.scene("bosses", self.bosses_scene)
        api.scene("note", self.note_scene)
        api.ipc("state", lambda *a: repr(self.source.get().get("game")))
        api.every(0.5, self.poll)

    def make_panel(self, api, **p):
        t = p.get("type")
        cls = KINDS.get(t) or (Num if config.CATALOG.get(t, {}).get("num") else Spacer)
        w = cls(api, module=self, **p)
        self.widgets.add(w)
        return w

    def poll(self):
        s = self.source.get()
        self.in_combat = bool((s.get("combat") or {}).get("since"))
        if self.in_combat:
            self.api.hide_scene("note")
        self.check_notes(s)
        for w in list(self.widgets):
            w.invalidate()

    def next_event(self):
        up = events.upcoming(self.sections, datetime.now(timezone.utc), 240)
        return up[0] if up else None

    def copy(self, text, label):
        if state.send(f"copy {text}"):
            self.copied = f"copied {label}"
            self.api.after(4, self._clear_copied)

    def _clear_copied(self):
        self.copied = ""

    def bosses_scene(self, api):
        now = datetime.now(timezone.utc)
        parts = []
        for a, b, _s, seg in events.upcoming(self.sections, now, 240)[:5]:
            when = "now" if a <= now else a.astimezone().strftime("%H:%M")
            parts.append(f"{when} {seg['name']}")
        return Layout(Row([Label(api, text="   ·   ".join(parts) or "no boss data", stretch=1, align="left", size=18)]),
                      Row([]))

    def note_scene(self, api):
        app, summary, body = self.note or ("", "", "")
        text = f"{summary}  ·  {body}" if body else summary
        return Layout(Row([Label(api, text=app, width=200, color=api.theme.FG_DIM, size=16),
                           Label(api, text=text[:160], stretch=1, align="left", size=18)]), Row([]))

    def check_notes(self, s):
        """A new desktop notification (from the feed) slides over the bar, if it matches the filter."""
        notes = s.get("notes") or []
        if not notes or notes[0]["t"] <= self.note_t:
            return
        n = notes[0]
        first = self.note_t == 0
        self.note_t = n["t"]
        st = self.settings
        try:
            match = re.search(st.get("notify_filter") or ".", f"{n['app']} {n['summary']} {n['body']}", re.IGNORECASE)
        except re.error:
            match = True
        if first or not st.get("notify_popup", True) or not match or self.in_combat or time.time() - n["t"] > 10:
            return
        self.note = (n["app"], n["summary"], n["body"])
        self.api.show_scene("note", priority=70, timeout=6)
