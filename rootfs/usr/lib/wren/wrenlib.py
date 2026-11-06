"""Shared helpers for Wren's apps: theme colors, light/dark mode, live theme
reloading, and keeping apps warm after their window closes (instant reopen)."""
import json
import os

THEME_FILE = os.path.join(os.path.expanduser("~"), ".config", "wren", "theme.json")
USER_GTK4 = os.path.join(os.path.expanduser("~"), ".config", "gtk-4.0", "gtk.css")

DARK = {
    "bg": "#181512", "window": "#1C1916", "surface": "#1F1B18", "surface2": "#26221E", "deep": "#141210",
    "border": "#2E2924", "border2": "#3A342E", "line": "#2A2520",
    "text": "#F1EBE3", "text2": "#D9D1C7", "dim": "#A89F94", "muted": "#8A8178",
}
LIGHT = {
    "bg": "#FBF8F4", "window": "#F4EFE8", "surface": "#FFFFFF", "surface2": "#F1EBE3", "deep": "#ECE5DB",
    "border": "#DDD3C6", "border2": "#CFC4B5", "line": "#E8E0D5",
    "text": "#221C16", "text2": "#3A322A", "dim": "#6E6459", "muted": "#8C8277",
}
# name: (accent, hover, text-on-dark, text-on-light, on-accent, libadwaita accent name, label)
ACCENTS = {
    "ember":  ("#E0894A", "#EC9A5E", "#F0A06A", "#B4602A", "#1A120B", "orange", "Ember"),
    "gold":   ("#D4A23A", "#E0B24E", "#E8C36E", "#93700F", "#1C1404", "yellow", "Gold"),
    "moss":   ("#7FA65A", "#8DB566", "#A2C483", "#557A33", "#10170A", "green", "Moss"),
    "sky":    ("#5B9BD5", "#6FAAE0", "#8DBDE8", "#2F6DAB", "#081421", "blue", "Sky"),
    "violet": ("#9B7BD8", "#AA8DE0", "#BCA6E8", "#6D50AE", "#140D22", "purple", "Violet"),
    "rose":   ("#D9607A", "#E37489", "#EB91A2", "#AE3B55", "#22080E", "pink", "Rose"),
    "slate":  ("#8C9AAB", "#9CA9B8", "#B3BDC9", "#56657A", "#0F141A", "slate", "Slate"),
}
DEFAULT_ACCENT = "ember"

ANSI_DARK = ["#26221E", "#E26D5C", "#9CC98C", "#E9C46A", "#86A8C7", "#C79BC0", "#86C2B6", "#D9D1C7",
             "#4A433C", "#F08A78", "#B2DBA3", "#F2D488", "#A3C1DC", "#DBB4D4", "#A3D8CD", "#F1EBE3"]
ANSI_LIGHT = ["#3A322A", "#B83A2C", "#4E7F3A", "#946B0B", "#2F6098", "#8B4A86", "#2D7B70", "#D9D1C7",
              "#6E6459", "#D04A3A", "#5E9447", "#B0830F", "#3B74B5", "#A65AA0", "#378F83", "#F4EFE8"]


def load_theme():
    try:
        t = json.load(open(THEME_FILE))
    except (OSError, ValueError):
        t = {}
    mode = t.get("mode") if t.get("mode") in ("dark", "light") else "dark"
    accent = t.get("accent") if t.get("accent") in ACCENTS else DEFAULT_ACCENT
    return {"mode": mode, "accent": accent, "animations": t.get("animations", True)}


def palette(theme=None):
    """Flat dict of every Wren color for the current theme."""
    theme = theme or load_theme()
    base = dict(LIGHT if theme["mode"] == "light" else DARK)
    a = ACCENTS[theme["accent"]]
    base.update(accent=a[0], accent_hover=a[1], accent_text=a[3] if theme["mode"] == "light" else a[2],
                on_accent=a[4], adw_accent=a[5], danger="#C4513F",
                ansi=ANSI_LIGHT if theme["mode"] == "light" else ANSI_DARK)
    return base


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
    state = {"src": None, "held": False}

    def release():
        state["src"] = None
        if state["held"]:
            state["held"] = False
            app.release()
        return False

    def removed(_app, _win):
        if app.get_windows():
            return
        if not state["held"]:
            app.hold()
            state["held"] = True
        if state["src"]:
            GLib.source_remove(state["src"])
        state["src"] = GLib.timeout_add_seconds(seconds, release)

    app.connect("window-removed", removed)
