"""Shared helpers for Wren's apps: theme colors, light/dark mode, live theme
reloading, and keeping apps warm after their window closes (instant reopen)."""
import glob
import json
import os

THEME_FILE = os.path.join(os.path.expanduser("~"), ".config", "wren", "theme.json")
USER_GTK4 = os.path.join(os.path.expanduser("~"), ".config", "gtk-4.0", "gtk.css")
SAVER_FLAG = os.path.join(os.path.expanduser("~"), ".cache", "wren", "battery-saver")
PREFS_FILE = os.path.join(os.path.expanduser("~"), ".config", "wren", "settings.json")

DARK = {
    "scheme": "dark",
    "bg": "#15181E", "window": "#1A1E25", "surface": "#222730", "surface2": "#2A303A", "deep": "#13161B",
    "border": "#2E343E", "border2": "#3A414D", "line": "#272C35",
    "text": "#EEF1F6", "text2": "#D3D8E1", "dim": "#9AA3B2", "muted": "#7C8594",
    # frosted glass: panels over the (pre-blurred) wallpaper
    "glass": "rgba(30, 34, 42, 0.62)", "glass_strong": "rgba(30, 34, 42, 0.82)",
    "glass_hover": "rgba(255, 255, 255, 0.10)", "glass_border": "rgba(255, 255, 255, 0.14)",
    "glass_edge": "rgba(0, 0, 0, 0.40)", "glass_tint": "rgba(10, 12, 16, 0.30)",
    "shadow": "rgba(0, 0, 0, 0.45)",
}
LIGHT = {
    "scheme": "light",
    "bg": "#F7F9FC", "window": "#EEF1F6", "surface": "#FFFFFF", "surface2": "#E8ECF2", "deep": "#E6EAF1",
    "border": "#D8DEE7", "border2": "#C7CFDA", "line": "#E3E8EF",
    "text": "#1C2230", "text2": "#333B4B", "dim": "#5F6879", "muted": "#8A92A1",
    "glass": "rgba(255, 255, 255, 0.58)", "glass_strong": "rgba(255, 255, 255, 0.80)",
    "glass_hover": "rgba(255, 255, 255, 0.55)", "glass_border": "rgba(255, 255, 255, 0.80)",
    "glass_edge": "rgba(30, 45, 70, 0.12)", "glass_tint": "rgba(236, 241, 248, 0.30)",
    "shadow": "rgba(40, 55, 80, 0.18)",
}
# name: (accent, hover, text-on-dark, text-on-light, on-accent, libadwaita accent name, label)
ACCENTS = {
    "sky":    ("#3B82F6", "#5594F7", "#86B4FA", "#1F63D6", "#FFFFFF", "blue", "Blue"),
    "violet": ("#8B5CF6", "#9C73F7", "#B9A0FA", "#6A3BD9", "#FFFFFF", "purple", "Violet"),
    "rose":   ("#EC4899", "#EF62A8", "#F49CC8", "#C02A74", "#FFFFFF", "pink", "Pink"),
    "ember":  ("#F97316", "#FA8A3C", "#FBA66B", "#C2540A", "#FFFFFF", "orange", "Orange"),
    "gold":   ("#EAB308", "#EFC33A", "#F3D266", "#946F00", "#1A1400", "yellow", "Yellow"),
    "moss":   ("#22C55E", "#43CF75", "#7EDD9F", "#15803D", "#FFFFFF", "green", "Green"),
    "teal":   ("#14B8A6", "#33C4B4", "#6FD8CB", "#0F766E", "#FFFFFF", "teal", "Teal"),
    "slate":  ("#64748B", "#7A8AA0", "#A3B0C2", "#475569", "#FFFFFF", "slate", "Graphite"),
}
DEFAULT_ACCENT = "sky"
DEFAULT_MODE = "light"
ICON_ACCENT = "#3B82F6"  # the accent color the Wren icon set is drawn with
WALLPAPERS = "/usr/share/wren/wallpapers"
DEFAULT_WALLPAPER = WALLPAPERS + "/silk.jpg"

ANSI_DARK = ["#2A303A", "#F2777A", "#8BD49C", "#F4C46B", "#79AEF7", "#C49BF2", "#6FD3CC", "#D3D8E1",
             "#566070", "#FF8F91", "#A6E3B5", "#F8D58C", "#9CC3FA", "#D5B5F6", "#93E2DC", "#F4F6FA"]
ANSI_LIGHT = ["#333B4B", "#C9363A", "#2E8A4A", "#9A6A00", "#1F63D6", "#7D45C9", "#15837A", "#D8DEE7",
              "#5F6879", "#DE4B4F", "#3AA35B", "#B88300", "#3B82F6", "#9161DB", "#1E9E93", "#F7F9FC"]


def load_theme():
    try:
        t = json.load(open(THEME_FILE))
    except (OSError, ValueError):
        t = {}
    mode = t.get("mode") if t.get("mode") in ("dark", "light") else DEFAULT_MODE
    accent = t.get("accent") if t.get("accent") in ACCENTS else DEFAULT_ACCENT
    return {"mode": mode, "accent": accent, "animations": t.get("animations", True) and not saver_on()}


# ------------------------------------------------------------------ power
def saver_on():
    return os.path.exists(SAVER_FLAG)


def prefs():
    try:
        return json.load(open(PREFS_FILE))
    except (OSError, ValueError):
        return {}


def battery():
    """(percent, status) of the first battery, or None on a desktop computer."""
    for bat in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        try:
            return int(open(f"{bat}/capacity").read()), open(f"{bat}/status").read().strip()
        except (OSError, ValueError):
            continue
    return None


def on_battery():
    """True only when the computer is running from its battery (not plugged in)."""
    if battery() is None:
        return False
    for ps in glob.glob("/sys/class/power_supply/*"):
        try:
            if open(f"{ps}/type").read().strip() == "Mains" and open(f"{ps}/online").read().strip() == "1":
                return False
        except OSError:
            continue
    b = battery()
    return b is not None and b[1] == "Discharging"


def background_allowed():
    """Apps may keep running with no window open (off by default, to save battery)."""
    return bool(prefs().get("background_apps", False)) and not saver_on()


def _rgb(h):
    h = h.lstrip("#")
    return f"{int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}"


def wallpaper():
    """The picture on the desktop (from Settings), or Wren's default."""
    w = prefs().get("wallpaper")
    return w if w and os.path.exists(w) else DEFAULT_WALLPAPER


def wallpaper_blur():
    """A heavily blurred copy of the wallpaper: what frosted glass panels show through."""
    w = wallpaper()
    pre = w[:-4] + "-blur.jpg" if w.endswith(".jpg") else ""
    if pre and os.path.exists(pre):
        return pre
    cache = os.path.join(os.path.expanduser("~"), ".cache", "wren", "wallpaper-blur.jpg")
    return cache if os.path.exists(cache) else w


def palette(theme=None):
    """Flat dict of every Wren color for the current theme."""
    theme = theme or load_theme()
    base = dict(LIGHT if theme["mode"] == "light" else DARK)
    a = ACCENTS[theme["accent"]]
    base.update(radius="14px", radius_small="10px", radius_big="22px",
                accent_glass=f"rgba({_rgb(a[0])}, 0.18)", accent=a[0], accent_hover=a[1], accent_text=a[3] if theme["mode"] == "light" else a[2],
                on_accent=a[4], adw_accent=a[5], danger="#C4513F",
                ansi=ANSI_LIGHT if theme["mode"] == "light" else ANSI_DARK)
    return base


# Entrance animation used across Wren's apps: things fade up into place, one after another
ANIM_CSS = """
.wren-enter { opacity: 0; transform: translateY(16px) scale(0.985);
  transition: opacity 180ms ease-out, transform 320ms cubic-bezier(0.18, 0.9, 0.28, 1.06); }
.wren-enter.in { opacity: 1; transform: none; }
.wren-pop { opacity: 0; transform: scale(0.88);
  transition: opacity 140ms ease-out, transform 260ms cubic-bezier(0.2, 1.1, 0.3, 1.15); }
.wren-pop.in { opacity: 1; transform: none; }
button, .card, row, flowboxchild, switch, switch > slider, checkbutton, scale slider, entry {
  transition: background-color 160ms ease, box-shadow 200ms ease, color 160ms ease, border-color 160ms ease,
              transform 180ms ease, opacity 160ms ease; }
button:active { transform: scale(0.96); }
"""


def children(widget):
    c = widget.get_first_child()
    while c is not None:
        yield c
        c = c.get_next_sibling()


def animate_in(widget, delay=0, kind="wren-enter"):
    """Fade/slide a widget into place (after `delay` ms). Instant when animations are off."""
    from gi.repository import GLib
    widget.add_css_class(kind)
    widget.remove_css_class("in")

    def show():
        widget.add_css_class("in")
        return False
    GLib.timeout_add(16 + delay, show)


def stagger(widgets, step=16, start=0, cap=12, kind="wren-enter"):
    for i, w in enumerate(widgets):
        animate_in(w, start + min(i, cap) * step, kind)


def setup_app_style(css=None, on_change=None):
    """Call from Adw.Application.do_startup: light/dark mode, app CSS, and a provider that
    re-reads the user's theme CSS whenever the theme changes (GTK doesn't do this itself)."""
    from gi.repository import Adw, Gdk, Gio, Gtk
    display = Gdk.Display.get_default()
    manager = Adw.StyleManager.get_default()

    fallback = Gtk.CssProvider()
    try:
        fallback.load_from_path("/usr/share/wren/palette.css")
    except Exception:
        pass
    Gtk.StyleContext.add_provider_for_display(display, fallback, Gtk.STYLE_PROVIDER_PRIORITY_SETTINGS)
    theme_provider = Gtk.CssProvider()
    Gtk.StyleContext.add_provider_for_display(display, theme_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 10)

    def apply(*_):
        t = load_theme()
        manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT if t["mode"] == "light" else Adw.ColorScheme.FORCE_DARK)
        if os.path.exists(USER_GTK4):
            try:
                theme_provider.load_from_path(USER_GTK4)
            except Exception:
                pass
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property("gtk-enable-animations", bool(t["animations"]))
        if on_change:
            on_change(t)

    apply()
    anim = Gtk.CssProvider()
    anim.load_from_string(ANIM_CSS)
    Gtk.StyleContext.add_provider_for_display(display, anim, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION - 1)
    if css:
        provider = Gtk.CssProvider()
        provider.load_from_string(css)
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    os.makedirs(os.path.dirname(THEME_FILE), exist_ok=True)
    monitor = Gio.File.new_for_path(THEME_FILE).monitor_file(Gio.FileMonitorFlags.NONE, None)
    monitor.connect("changed", lambda *_a: apply())
    setup_app_style.monitor = monitor  # keep a reference
    return apply


def keep_warm(app, seconds=300):
    """After the last window closes, keep the app running for a while so reopening it
    is instant (the window is rebuilt, but Python and GTK are already loaded)."""
    from gi.repository import GLib
    state = {"src": None, "held": False, "left": 0}

    def release():
        state["src"] = None
        if state["held"]:
            state["held"] = False
            app.release()
        return False

    def tick():
        # With Battery saver on, closed apps really quit.
        state["left"] -= 15
        if state["left"] <= 0 or saver_on():
            return release()
        return True

    def removed(_app, _win):
        if app.get_windows():
            return
        if saver_on():
            return
        if not state["held"]:
            app.hold()
            state["held"] = True
        if state["src"]:
            GLib.source_remove(state["src"])
        state["left"] = seconds
        state["src"] = GLib.timeout_add_seconds(15, tick)

    app.connect("window-removed", removed)
