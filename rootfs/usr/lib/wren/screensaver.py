#!/usr/bin/env python3
"""Floe's screen saver: slabs of glassy ice drifting over your wallpaper under a
slow aurora, with a big clock that wanders a little (so nothing burns in).

Started by wren-idle after the time chosen in Settings; any key, click or mouse
movement ends it. Drawn on the graphics card (GTK render nodes) at a modest
frame rate, lower on battery, so it costs very little.

  python3 -m screensaver            run it
  python3 -m screensaver --preview  run it from Settings (ignores the click that opened it)
"""
import faulthandler
import fcntl
import math
import os
import random
import signal
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Pango", "1.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk, Pango  # noqa: E402
from gi.repository import Gtk4LayerShell as Layer  # noqa: E402

sys.path.insert(0, "/usr/lib/wren")
import wrenlib  # noqa: E402

PREVIEW = "--preview" in sys.argv


def log(*parts):
    print("screensaver:", *parts, file=sys.stderr, flush=True)


def rgba(r, g, b, a=1.0):
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r, g, b, a
    return c


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rect(x, y, w, h):
    return Graphene.Rect().init(x, y, w, h)


def point(x, y):
    return Graphene.Point().init(x, y)


def soft_texture(r, g, b, size=128, edge=False):
    """A soft round glow (or, with edge=True, a dark vignette) as a GPU texture."""
    c = (size - 1) / 2
    stops = ((0.0, 0.0), (0.55, 0.0), (1.0, 0.62)) if edge else ((0.0, 1.0), (0.35, 0.55), (0.7, 0.14), (1.0, 0.0))
    reach = c * (1.45 if edge else 1.0)

    def alpha(d):
        d = min(d / reach, 1.0)
        for (d0, a0), (d1, a1) in zip(stops, stops[1:]):
            if d <= d1:
                k = (d - d0) / (d1 - d0)
                k = k * k * (3 - 2 * k)
                return a0 + (a1 - a0) * k
        return stops[-1][1]
    ramp = [alpha(i / 4) for i in range(int(reach * 4 * 1.5) + 8)]
    rgb = (0, 0, 0) if edge else (r, g, b)
    out = bytearray(size * size * 4)
    i = 0
    for y in range(size):
        dy = (y - c) ** 2
        for x in range(size):
            a = ramp[min(int(math.sqrt((x - c) ** 2 + dy) * 4), len(ramp) - 1)]
            out[i] = int(rgb[0] * a * 255)
            out[i + 1] = int(rgb[1] * a * 255)
            out[i + 2] = int(rgb[2] * a * 255)
            out[i + 3] = int(a * 255)
            i += 4
    return Gdk.MemoryTexture.new(size, size, Gdk.MemoryFormat.R8G8B8A8_PREMULTIPLIED, GLib.Bytes.new(bytes(out)),
                                 size * 4)


class Floe:
    """One faceted slab of ice. depth 0 (far, small, slow) .. 1 (near, big)."""

    def __init__(self, w, h, rng, depth, anywhere=True):
        self.rng, self.depth = rng, depth
        self.r = (40 + 150 * depth ** 1.4) * max(w, h) / 1600
        n = rng.choice((5, 6, 6, 7))
        angles = sorted(i * 2 * math.pi / n + rng.uniform(-0.35, 0.35) for i in range(n))
        self.pts = [(math.cos(a) * rng.uniform(0.68, 1.0), math.sin(a) * rng.uniform(0.62, 1.0)) for a in angles]
        self.core = (rng.uniform(-0.22, 0.22), rng.uniform(-0.22, 0.22))
        speed = 7 + 22 * depth
        heading = rng.uniform(-0.55, -0.15)  # drifting right and a little up
        self.vx, self.vy = math.cos(heading) * speed, math.sin(heading) * speed
        self.spin = rng.uniform(-4, 4) * (1.2 - depth)
        self.angle = rng.uniform(0, 360)
        self.bob = rng.uniform(0, 2 * math.pi)
        self.alpha = 0.45 + 0.55 * depth
        self.x = rng.uniform(-self.r, w + self.r) if anywhere else -self.r * 1.5
        self.y = rng.uniform(-self.r, h + self.r) if anywhere else rng.uniform(h * 0.15, h + self.r)

    def step(self, dt, w, h):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.angle += self.spin * dt
        if self.x - self.r * 1.6 > w or self.y + self.r * 1.6 < 0:
            self.__init__(w, h, self.rng, self.depth, anywhere=False)

    def draw(self, snap, t):
        bob = math.sin(t * 0.35 + self.bob) * self.r * 0.06
        snap.save()
        snap.translate(point(self.x, self.y + bob))
        snap.rotate(self.angle)
        r, (cx, cy) = self.r, self.core
        pts = [(x * r, y * r) for x, y in self.pts]
        light = math.radians(-135 - self.angle)  # light from the top left of the screen
        a = self.alpha
        for i, p in enumerate(pts):
            q = pts[(i + 1) % len(pts)]
            mid = math.atan2((p[1] + q[1]) / 2 - cy * r, (p[0] + q[0]) / 2 - cx * r)
            shade = 0.5 + 0.5 * math.cos(mid - light)
            b = Gsk.PathBuilder.new()
            b.move_to(cx * r, cy * r)
            b.line_to(*p)
            b.line_to(*q)
            b.close()
            snap.append_fill(b.to_path(), Gsk.FillRule.WINDING, rgba(0.86, 0.96, 1.0, a * (0.035 + 0.15 * shade ** 2)))
        facets = Gsk.PathBuilder.new()
        for p in pts:
            facets.move_to(cx * r, cy * r)
            facets.line_to(*p)
        snap.append_stroke(facets.to_path(), Gsk.Stroke.new(1.0), rgba(1, 1, 1, a * 0.10))
        rim = Gsk.PathBuilder.new()
        rim.move_to(*pts[0])
        for p in pts[1:]:
            rim.line_to(*p)
        rim.close()
        snap.append_stroke(rim.to_path(), Gsk.Stroke.new(1.4), rgba(1, 1, 1, a * 0.34))
        snap.restore()


class Scene(Gtk.Widget):
    def __init__(self, app, seed):
        super().__init__(hexpand=True, vexpand=True)
        self.app = app
        self.rng = random.Random(seed)
        self.size = (0, 0)
        self.floes, self.flakes = [], []
        self.last = None
        pal = wrenlib.palette()
        self.glows = [soft_texture(*hex_rgb(pal["accent"])), soft_texture(0.37, 0.88, 0.90),
                      soft_texture(0.55, 0.49, 0.96)]
        self.vignette = soft_texture(0, 0, 0, edge=True)
        try:
            self.wall = Gdk.Texture.new_from_filename(wrenlib.wallpaper_blur())
        except GLib.Error:
            self.wall = None
        self.h24 = bool(wrenlib.prefs().get("clock_24h"))
        self.big = Pango.FontDescription.from_string("IBM Plex Sans Light")
        self.small = Pango.FontDescription.from_string("IBM Plex Sans")
        self.wander = (self.rng.uniform(0, 6.3), self.rng.uniform(0, 6.3))

    def populate(self, w, h):
        self.size = (w, h)
        count = max(7, int(w * h / 190000))
        self.floes = sorted((Floe(w, h, self.rng, self.rng.random()) for _ in range(count)), key=lambda f: f.depth)
        self.flakes = [[self.rng.uniform(0, w), self.rng.uniform(0, h), self.rng.uniform(0.8, 2.4),
                        self.rng.uniform(5, 16), self.rng.uniform(0, 6.3)] for _ in range(int(count * 5))]

    def text(self, s, font, px):
        layout = self.create_pango_layout(s)
        font = font.copy()
        font.set_absolute_size(px * Pango.SCALE)
        layout.set_font_description(font)
        return layout, layout.get_pixel_size()

    def do_snapshot(self, snap):
        w, h = self.get_width(), self.get_height()
        if not w or not h:
            return
        if not self.size[0]:
            log(f"first frame {w}x{h} after {time.monotonic() - self.app.t0:.2f}s")
        if self.size != (w, h):
            self.populate(w, h)
        t = self.app.clock()
        dt = 0 if self.last is None else min(t - self.last, 0.25)
        self.last = t
        snap.push_opacity(self.app.fade(t))

        # wallpaper, slowly zooming and panning
        snap.append_color(rgba(0.03, 0.06, 0.10), rect(0, 0, w, h))
        if self.wall:
            z = 1.10 + 0.05 * math.sin(t / 47)
            tw, th = self.wall.get_width(), self.wall.get_height()
            s = max(w / tw, h / th) * z
            dx = (w - tw * s) / 2 + math.sin(t / 61) * w * 0.02
            dy = (h - th * s) / 2 + math.cos(t / 53) * h * 0.02
            snap.append_texture(self.wall, rect(dx, dy, tw * s, th * s))
        snap.append_color(rgba(0.02, 0.04, 0.09, 0.68), rect(0, 0, w, h))

        # aurora
        m = max(w, h)
        for i, glow in enumerate(self.glows):
            p = 41 + i * 13
            cx = w * (0.5 + 0.38 * math.sin(t / p + i * 2.1))
            cy = h * (0.35 + 0.28 * math.cos(t / (p * 1.3) + i))
            size = m * (0.75 + 0.15 * math.sin(t / 23 + i))
            snap.push_opacity(0.40 + 0.14 * math.sin(t / 17 + i * 1.7))
            snap.append_texture(glow, rect(cx - size / 2, cy - size / 2, size, size))
            snap.pop()

        # ice, far to near, with glinting flakes in between
        half = len(self.floes) // 2
        for f in self.floes[:half]:
            f.step(dt, w, h)
            f.draw(snap, t)
        flakes, bright = Gsk.PathBuilder.new(), Gsk.PathBuilder.new()
        lit = 0
        for fl in self.flakes:
            fl[1] += fl[3] * dt
            fl[0] += math.sin(t * 0.5 + fl[4]) * 6 * dt
            if fl[1] > h + 4:
                fl[0], fl[1] = self.rng.uniform(0, w), -4
            glint = math.sin(t * 1.3 + fl[4] * 5) > 0.75
            lit += glint
            (bright if glint else flakes).add_circle(point(fl[0], fl[1]), fl[2])
        if lit < len(self.flakes):
            snap.append_fill(flakes.to_path(), Gsk.FillRule.WINDING, rgba(1, 1, 1, 0.30))
        if lit:
            snap.append_fill(bright.to_path(), Gsk.FillRule.WINDING, rgba(1, 1, 1, 0.85))
        for f in self.floes[half:]:
            f.step(dt, w, h)
            f.draw(snap, t)
        snap.append_texture(self.vignette, rect(-w * 0.1, -h * 0.1, w * 1.2, h * 1.2))

        # the clock, wandering slowly around the middle
        now = time.localtime()
        clock = time.strftime("%H:%M" if self.h24 else "%-I:%M", now)
        date = time.strftime("%A, %B %-d", now)
        big, (bw, bh) = self.text(clock, self.big, min(w, h) * 0.20)
        small, (sw, sh) = self.text(date, self.small, min(w, h) * 0.032)
        ox = math.sin(t / 97 + self.wander[0]) * w * 0.16
        oy = math.sin(t / 131 + self.wander[1]) * h * 0.14
        x, y = w / 2 + ox, h / 2 + oy - (bh + sh) / 2
        for layout, lw, ly, col in ((big, bw, y, rgba(1, 1, 1, 0.94)), (small, sw, y + bh * 0.96, rgba(1, 1, 1, 0.76))):
            snap.save()
            snap.translate(point(x - lw / 2, ly + 3))
            snap.append_layout(layout, rgba(0, 0, 0, 0.22))
            snap.translate(point(0, -3))
            snap.append_layout(layout, col)
            snap.restore()
        snap.pop()


class Saver(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=None)
        self.t0 = time.monotonic()
        self.ending = None
        self.scenes, self.windows = [], []
        self.still = not wrenlib.load_theme()["animations"]
        self.start_pointer = {}

    def clock(self):
        t = time.monotonic() - self.t0
        return 0.0 if self.still else t

    def fade(self, _t):
        now = time.monotonic()
        a = min(1.0, (now - self.t0) / 1.4)
        a = a * a * (3 - 2 * a)
        if self.ending is not None:
            a *= max(0.0, 1 - (now - self.ending) / 0.28)
        return a

    def fps(self):
        if self.still:
            return 1
        if wrenlib.saver_on():
            return 12
        if wrenlib.on_battery():
            return 20 if time.monotonic() - self.t0 < 600 else 8
        return 30

    def do_activate(self):
        css = Gtk.CssProvider()
        css.load_from_string("window.floe-saver { background: transparent; }")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        monitors = Gdk.Display.get_default().get_monitors()
        for i in range(max(1, monitors.get_n_items())):
            self.add_screen(monitors.get_item(i) if monitors.get_n_items() else None, i)
        self.hold()
        log("showing on", len(self.windows), "screen(s)")
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: self.end() or True)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: self.end() or True)
        self.tick()

    def add_screen(self, monitor, i):
        win = Gtk.Window(application=self, title="Floe screen saver")
        win.add_css_class("floe-saver")
        Layer.init_for_window(win)
        Layer.set_namespace(win, "floe-screensaver")
        Layer.set_layer(win, Layer.Layer.OVERLAY)
        if monitor is not None:
            Layer.set_monitor(win, monitor)
        for e in (Layer.Edge.TOP, Layer.Edge.BOTTOM, Layer.Edge.LEFT, Layer.Edge.RIGHT):
            Layer.set_anchor(win, e, True)
        Layer.set_exclusive_zone(win, -1)
        Layer.set_keyboard_mode(win, Layer.KeyboardMode.EXCLUSIVE if i == 0 else Layer.KeyboardMode.NONE)
        scene = Scene(self, seed=int(time.time()) + i * 7919)
        win.set_child(scene)
        win.set_cursor(Gdk.Cursor.new_from_name("none", None))

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda *_: self.end() or True)
        win.add_controller(keys)
        click = Gtk.GestureClick(button=0)
        click.connect("pressed", lambda *_: self.end())
        win.add_controller(click)
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll.connect("scroll", lambda *_: self.end() or True)
        win.add_controller(scroll)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda _c, x, y, w=win: self.moved(w, x, y))
        win.add_controller(motion)
        win.present()
        self.windows.append(win)
        self.scenes.append(scene)

    def moved(self, win, x, y):
        # the pointer "arrives" when the window appears; only real movement counts
        if time.monotonic() - self.t0 < (1.5 if PREVIEW else 0.6):
            self.start_pointer[win] = (x, y)
            return
        sx, sy = self.start_pointer.setdefault(win, (x, y))
        if abs(x - sx) + abs(y - sy) > 10:
            self.end()

    def end(self):
        if self.ending is None:
            self.ending = time.monotonic()
            GLib.timeout_add(300, self.quit)

    def tick(self):
        for s in self.scenes:
            s.queue_draw()
        GLib.timeout_add(int(1000 / (60 if self.ending else self.fps())), lambda: self.tick() and False)
        return True


def main():
    faulthandler.register(signal.SIGUSR1)  # `pkill -USR1 -f "m screensaver"` prints where it is
    log("starting", "(preview)" if PREVIEW else "")
    run = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    lock = open(os.path.join(run, "floe-screensaver.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("already showing")
        return
    if not PREVIEW and os.system("pidof -q hyprlock") == 0:
        return  # the lock screen is up; nothing to cover
    Saver().run([])


if __name__ == "__main__":
    main()
