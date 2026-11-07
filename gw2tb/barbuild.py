# barbuild.py: puts the macarchy-touchbar engine together with our gw2 module and the user's pages.
# Shared by the service (gw2-touchbar) and the settings app's preview. The caller has the engine on
# sys.path already.
import os

import cairo
import gi

gi.require_version("PangoCairo", "1.0")
from gi.repository import PangoCairo        # noqa: E402

from macarchy_touchbar import bar as bar_module
from macarchy_touchbar import draw
from macarchy_touchbar.bar import Bar
from macarchy_touchbar.config import Config
from macarchy_touchbar.draw import Painter
from macarchy_touchbar.hypr import Context
from macarchy_touchbar.loop import EventLoop
from macarchy_touchbar.modules import ModuleHost, Registry, discover
from macarchy_touchbar.output import HeadlessOutput

from gw2tb import config

MODULES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modules")
SWIPE = 120           # px of horizontal travel that flips the page

# Without the 15 MB Material Symbols font the engine writes icon names as text. The few icons the
# engine itself uses (group close, broken widget) get a plain character instead.
GLYPHS = {"close": "✕", "warning": "!"}
_icon = draw.Painter.icon


def _plain_icon(self, cr, name, cx, cy, size=draw.Theme.ICON, tint=draw.Theme.FG, fill=0.0, weight=500):
    if draw.icon_font_available() or name not in GLYPHS:
        return _icon(self, cr, name, cx, cy, size, tint, fill, weight)
    layout = self._layout(cr, GLYPHS[name], draw.Theme.FONT, int(size * 0.6))
    ink = layout.get_pixel_extents()[0]
    cr.save()
    cr.set_source_rgb(*tint)
    cr.move_to(cx - ink.width / 2 - ink.x, cy - ink.height / 2 - ink.y)
    PangoCairo.show_layout(cr, layout)
    cr.restore()


draw.Painter.icon = _plain_icon
bar_module.REDRAW_MIN_INTERVAL = 0.1    # 10 fps is plenty, and gentler on the T2's appletbdrm


class Pages:
    """The user's pages on one engine Bar: each page is the engine's default layout in turn."""

    def __init__(self, bar, cfg, page=0):
        self.bar, self.cfg, self.page = bar, cfg, 0
        self.show(page)

    def show(self, page):
        self.page = max(0, min(page, len(self.cfg["pages"]) - 1))
        gw2 = self.bar.host.modules.get("gw2")
        if gw2:
            gw2.page = (self.page, len(self.cfg["pages"]))
            gw2.graph_seconds = int(self.cfg["settings"]["graph_seconds"])
            gw2.settings = self.cfg["settings"]
        self.bar.reload_config(Config(config.engine_data(self.cfg, self.page)))
        self.bar.invalidate(None)

    def flip(self, step):
        if len(self.cfg["pages"]) > 1:
            self.show((self.page + step) % len(self.cfg["pages"]))

    def reload(self, cfg):
        self.cfg = cfg
        self.show(self.page)


def gesture_filter(bar, pages):
    """bar.gesture with horizontal swipes turned into page flips (when swipe is on)."""
    start = {"x": None}

    def deliver(g):
        if g.kind == "press":
            start["x"] = g.x
        elif g.kind == "drag_end" and start["x"] is not None and pages.cfg["settings"]["swipe"]:
            dx = g.x - start["x"]
            if abs(dx) >= SWIPE and not bar._capture:
                bar.gesture(g)
                pages.flip(-1 if dx > 0 else 1)
                return
        bar.gesture(g)
    return deliver


def build(output, loop, cfg, page=0, keyboard=None):
    """-> (bar, host, pages) drawing into output."""
    registry = Registry()
    host = ModuleHost(loop, None, registry)
    bar = Bar(output, loop, Painter(output.surface), Config(config.engine_data(cfg, 0)), registry, host)
    host.hooks = bar
    bar.host = host
    for spec in discover(MODULES, "/nonexistent", {}):
        host.load(spec)
    bar.set_context(Context())
    bar.keyboard = keyboard
    return bar, host, Pages(bar, cfg, page)


def render(cfg, page, st):
    """One page drawn with a fixed state (the settings preview) -> cairo.ImageSurface 2008x60."""
    from gw2tb import state
    state.override = st
    out = HeadlessOutput()
    bar, host, _pages = build(out, EventLoop(), cfg, page)
    bar.redraw()
    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, out.width, out.height)
    cr = cairo.Context(img)
    cr.set_source_surface(out.surface, 0, 0)
    cr.paint()
    for m in list(host.modules):
        host.unload(m)
    return img
