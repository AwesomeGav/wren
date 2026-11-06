#!/usr/bin/env python3
"""Wren Shell: the app launcher and quick-settings panel for the Wren desktop.

Runs as one resident process (started at login with --service). The taskbar
calls `wren-shell launcher` or `wren-shell control`, which toggles the panel
instantly in the running process.
"""
import glob
import os
import re
import subprocess
import sys
import threading
from ctypes import CDLL

CDLL("libgtk4-layer-shell.so")  # must load before GTK

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

sys.path.insert(0, "/usr/lib/wren")
import wrenlib  # noqa: E402
from gi.repository import Gtk4LayerShell as Layer  # noqa: E402

LIVE = os.path.isdir("/run/archiso")

# Helper and technical entries that clutter the app grid
HIDDEN_APPS = {
    "foot.desktop", "foot-server.desktop", "footclient.desktop", "org.codeberg.dnkl.foot.desktop",
    "org.codeberg.dnkl.foot-server.desktop", "org.codeberg.dnkl.footclient.desktop", "lftp.desktop", "qv4l2.desktop", "qvidcap.desktop",
    "vim.desktop", "gvim.desktop", "nm-connection-editor.desktop", "avahi-discover.desktop",
    "bssh.desktop", "bvnc.desktop", "blueman-manager.desktop", "blueman-adapters.desktop", "xgps.desktop", "xgpsspeed.desktop", "lstopo.desktop",
    "org.freedesktop.IBus.Setup.desktop", "cmake-gui.desktop", "htop.desktop", "btop.desktop",
    "nvim.desktop", "mpv.desktop", "uxterm.desktop", "xterm.desktop", "gcr-prompter.desktop",
}
HIDDEN_PREFIXES = ("stoken", "org.gnome.Tecla", "electron", "jshell", "java")
LOCK_CMD = ["wren-lock"]

CSS = """
window.wren-layer { background: transparent; }
.frost { opacity: 0; transition: opacity 120ms ease-out; }
.frost.shown { opacity: 1; }
.backdrop { background-color: transparent; transition: background-color 120ms ease-out; }
.backdrop.shown { background-color: @wren_glass_tint; }
.sheet { opacity: 0; transform: translateY(14px) scale(0.97);
         transition: opacity 90ms ease-out, transform 200ms cubic-bezier(0.2, 0.9, 0.25, 1.06); }
.sheet.shown { opacity: 1; transform: none; }
flowboxchild, .tile, .pill-btn, .net-row { transition: background-color 120ms ease-out, box-shadow 120ms ease-out; }
.sheet {
  background-color: @wren_glass;
  border: 1px solid @wren_glass_border;
  border-radius: 26px;
  padding: 22px;
  box-shadow: 0 24px 60px @wren_shadow, 0 0 0 1px @wren_glass_edge, inset 0 1px 0 alpha(#FFFFFF, 0.35);
  color: @wren_text;
}
.search {
  min-height: 46px; border-radius: 999px; font-size: 15px; padding: 0 8px;
  background: @wren_glass_hover; border: 1px solid @wren_glass_border; box-shadow: none;
}
flowboxchild { border-radius: 18px; padding: 0; outline: none; }
flowboxchild:hover { background: @wren_glass_hover; }
flowboxchild:selected, flowboxchild:focus-visible { background: @wren_accent_glass; }
.app-tile { padding: 14px 6px 12px 6px; }
.app-name { font-size: 12px; font-weight: 500; color: @wren_text2; }
.muted { color: @wren_dim; }
.empty { color: @wren_muted; font-size: 14px; }
.big-clock { font-size: 40px; font-weight: 600; letter-spacing: -1px; }
.tile {
  border-radius: 18px; padding: 12px 14px; min-height: 40px;
  background: @wren_glass_hover; color: @wren_text;
  border: 1px solid @wren_glass_border; box-shadow: none;
}
.tile:hover { background: alpha(@wren_text, 0.10); }
.tile.on { background: @wren_accent; color: @wren_on_accent; border-color: transparent;
           box-shadow: 0 6px 16px alpha(@wren_accent, 0.35); }
.tile.on:hover { background: @wren_accent_hover; }
.tile .title { font-weight: 600; }
.tile .sub { font-size: 11px; opacity: 0.75; }
.row-icon { color: @wren_dim; }
.pill-btn {
  border-radius: 16px; padding: 9px 10px; background: @wren_glass_hover;
  border: 1px solid @wren_glass_border; box-shadow: none; color: @wren_text;
}
.pill-btn:hover { background: alpha(@wren_text, 0.10); }
.pill-btn.danger:hover, .pill-btn.confirm { background: #E5484D; color: #FFFFFF; border-color: transparent; }
.net-row { border-radius: 12px; padding: 8px 10px; background: transparent; box-shadow: none; border: none; color: @wren_text; }
.net-row:hover { background: alpha(@wren_text, 0.07); }
.net-list { background: alpha(@wren_text, 0.05); border-radius: 16px; padding: 6px; }
scale trough { min-height: 8px; border-radius: 999px; background: alpha(@wren_text, 0.12); }
scale highlight { background: @wren_accent; border-radius: 999px; }
scale slider { min-width: 22px; min-height: 22px; border-radius: 999px; background: #FFFFFF;
               box-shadow: 0 1px 6px rgba(0, 0, 0, 0.25); border: none; }
"""


def load_prefs():
    try:
        import json
        return json.load(open(os.path.expanduser("~/.config/wren/settings.json")))
    except (OSError, ValueError):
        return {}


def run(cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def ok(cmd, timeout=20):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).returncode == 0
    except Exception:
        return False


def spawn(cmd):
    try:
        subprocess.Popen(cmd, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def in_thread(fn, done=None):
    def work():
        result = fn()
        if done:
            GLib.idle_add(done, result)
    threading.Thread(target=work, daemon=True).start()


def label(text="", css=None, xalign=0.0, **kw):
    w = Gtk.Label(label=text, xalign=xalign, **kw)
    for c in (css or "").split():
        w.add_css_class(c)
    return w


class Sheet(Gtk.Window):
    """A full-screen transparent overlay with a floating card; click outside or Esc to close."""

    def __init__(self, app, name):
        super().__init__(application=app)
        self.add_css_class("wren-layer")
        self.set_decorated(False)
        Layer.init_for_window(self)
        Layer.set_namespace(self, "wren-" + name)
        Layer.set_layer(self, Layer.Layer.OVERLAY)
        for edge in (Layer.Edge.TOP, Layer.Edge.BOTTOM, Layer.Edge.LEFT, Layer.Edge.RIGHT):
            Layer.set_anchor(self, edge, True)
        Layer.set_exclusive_zone(self, -1)
        Layer.set_keyboard_mode(self, Layer.KeyboardMode.EXCLUSIVE)

        # Frosted glass: a pre-blurred copy of the wallpaper fades in behind the card
        overlay = Gtk.Overlay()
        self.frost = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_target=False)
        self.frost.add_css_class("frost")
        self.frost_src = None
        overlay.set_child(self.frost)
        self.backdrop = Gtk.Box()
        self.backdrop.add_css_class("backdrop")
        overlay.add_overlay(self.backdrop)
        self.set_child(overlay)
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.card.add_css_class("sheet")
        self.card.set_hexpand(True)
        self.card.set_vexpand(True)
        self.backdrop.append(self.card)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self.backdrop.add_controller(click)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    def _on_click(self, _g, _n, x, y):
        if self.backdrop.pick(x, y, Gtk.PickFlags.DEFAULT) is self.backdrop:
            self.hide_sheet()

    def _on_key(self, _c, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            self.hide_sheet()
            return True
        return self.on_key(keyval)

    def on_key(self, keyval):
        return False

    def toggle(self):
        if self.get_visible():
            self.hide_sheet()
        else:
            self.open_sheet()

    def _load_frost(self):
        src = wrenlib.wallpaper_blur()
        try:
            key = (src, os.path.getmtime(src))
        except OSError:
            key = (src, 0)
        if key != self.frost_src:
            self.frost_src = key
            self.frost.set_filename(src)

    def open_sheet(self):
        self.card.remove_css_class("shown")
        self.backdrop.remove_css_class("shown")
        self.frost.remove_css_class("shown")
        self._load_frost()
        self.refresh()
        self.present()

        def show():
            self.card.add_css_class("shown")
            self.backdrop.add_css_class("shown")
            self.frost.add_css_class("shown")
            return False
        self.card.add_tick_callback(lambda *_: show())

    def hide_sheet(self):
        self.card.remove_css_class("shown")
        self.backdrop.remove_css_class("shown")
        self.frost.remove_css_class("shown")
        self.set_visible(False)

    def refresh(self):
        pass


# ---------------------------------------------------------------- launcher

class Launcher(Sheet):
    def __init__(self, app):
        super().__init__(app, "launcher")
        self.card.set_halign(Gtk.Align.CENTER)
        self.card.set_valign(Gtk.Align.CENTER)
        self.card.set_size_request(680, 540)

        self.entry = Gtk.SearchEntry(placeholder_text="Search apps")
        self.entry.add_css_class("search")
        self.entry.connect("search-changed", self._on_search)
        self.entry.connect("activate", lambda *_: self._launch_first())
        self.card.append(self.entry)

        self.flow = Gtk.FlowBox(
            valign=Gtk.Align.START, homogeneous=True,
            min_children_per_line=3, max_children_per_line=6,
            row_spacing=6, column_spacing=6,
            selection_mode=Gtk.SelectionMode.SINGLE,
            activate_on_single_click=True)
        self.flow.set_filter_func(self._filter)
        self.flow.connect("child-activated", lambda _f, child: self._launch(child))
        self.scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.scroller.set_child(self.flow)
        self.card.append(self.scroller)

        self.empty = label("No apps match your search", "empty", xalign=0.5, visible=False)
        self.card.append(self.empty)
        self.apps = {}

        self.dirty = True
        self.monitor = Gio.AppInfoMonitor.get()
        self.monitor.connect("changed", lambda *_: self._mark_dirty())
        Gtk.Settings.get_default().connect("notify::gtk-icon-theme-name", lambda *_: self._mark_dirty())
        GLib.idle_add(lambda: self.rebuild() or False)  # build ahead of time, while idle

    def _mark_dirty(self):
        self.dirty = True
        if not self.get_visible():
            GLib.idle_add(lambda: self.rebuild() or False)

    def refresh(self):
        if self.dirty:
            self.rebuild()
        self.entry.set_text("")
        self.flow.invalidate_filter()
        self.empty.set_visible(False)
        adj = self.scroller.get_vadjustment()
        adj.set_value(0)
        self.entry.grab_focus()
        wrenlib.stagger(list(wrenlib.children(self.flow))[:30], step=6, cap=30, kind="wren-pop")

    def rebuild(self):
        self.dirty = False
        self.flow.remove_all()
        self.apps = {}
        infos = [a for a in Gio.AppInfo.get_all() if a.should_show()
                 and (a.get_id() or "") not in HIDDEN_APPS
                 and not (a.get_id() or "").startswith(HIDDEN_PREFIXES)]
        infos.sort(key=lambda a: a.get_display_name().lower())
        for info in infos:
            tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            tile.add_css_class("app-tile")
            icon = info.get_icon()
            img = Gtk.Image.new_from_gicon(icon) if icon else Gtk.Image.new_from_icon_name("application-x-executable")
            img.set_pixel_size(52)
            tile.append(img)
            name = Gtk.Label(label=info.get_display_name(), max_width_chars=12,
                             ellipsize=3, justify=Gtk.Justification.CENTER)
            name.add_css_class("app-name")
            tile.append(name)
            child = Gtk.FlowBoxChild()
            child.set_child(tile)
            child.set_tooltip_text(info.get_description() or info.get_display_name())
            words = [info.get_display_name(), info.get_description() or "", info.get_executable() or ""]
            if isinstance(info, Gio.DesktopAppInfo):
                words += info.get_keywords() or []
                words += [info.get_generic_name() or ""]
            self.apps[child] = (info, " ".join(words).lower())
            self.flow.append(child)

    def _filter(self, child):
        query = self.entry.get_text().strip().lower()
        entry = self.apps.get(child)
        return not query or (entry is not None and all(q in entry[1] for q in query.split()))

    def _visible_children(self):
        return [c for c in self.apps if self._filter(c)]

    def _on_search(self, *_):
        self.flow.invalidate_filter()
        self.empty.set_visible(not self._visible_children())

    def _launch_first(self):
        visible = sorted(self._visible_children(), key=lambda c: c.get_index())
        if visible:
            self._launch(visible[0])

    def _launch(self, child):
        entry = self.apps.get(child)
        if not entry:
            return
        self.hide_sheet()
        try:
            ctx = Gdk.Display.get_default().get_app_launch_context()
            entry[0].launch([], ctx)
        except GLib.Error:
            pass

    def on_key(self, keyval):
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Tab) and self.entry.has_focus():
            visible = sorted(self._visible_children(), key=lambda c: c.get_index())
            if visible:
                self.flow.select_child(visible[0])
                visible[0].grab_focus()
                return True
        return False


# ---------------------------------------------------------- quick settings

class Tile(Gtk.Button):
    def __init__(self, icon, title, on_click):
        super().__init__()
        self.add_css_class("tile")
        box = Gtk.Box(spacing=12)
        self.icon = Gtk.Image.new_from_icon_name(icon)
        self.icon.set_pixel_size(18)
        box.append(self.icon)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.title = label(title, "title", ellipsize=3)
        self.sub = label("", "sub", ellipsize=3)
        text.append(self.title)
        text.append(self.sub)
        box.append(text)
        self.set_child(box)
        self.set_hexpand(True)
        self.connect("clicked", lambda *_: on_click())

    def set_state(self, on, sub):
        if on:
            self.add_css_class("on")
        else:
            self.remove_css_class("on")
        self.sub.set_text(sub)


class Control(Sheet):
    def __init__(self, app):
        super().__init__(app, "control")
        self.card.set_halign(Gtk.Align.END)
        self.card.set_valign(Gtk.Align.END)
        self.card.set_margin_end(12)
        self.card.set_margin_top(10)
        self.card.set_margin_bottom(74)
        self.card.set_size_request(380, -1)
        self.state = {}
        self._quiet = False

        # Clock + battery
        head = Gtk.Box(spacing=12)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.clock = label("", "big-clock")
        self.date = label("", "muted")
        left.append(self.clock)
        left.append(self.date)
        head.append(left)
        self.battery = label("", "muted", xalign=1.0, hexpand=True, valign=Gtk.Align.END)
        head.append(self.battery)
        self.card.append(head)

        # Toggle tiles
        grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
        self.wifi = Tile("network-wireless-symbolic", "Wi-Fi", self.toggle_wifi)
        self.bt = Tile("bluetooth-active-symbolic", "Bluetooth", self.toggle_bt)
        self.dnd = Tile("notifications-disabled-symbolic", "Do Not Disturb", self.toggle_dnd)
        self.shot = Tile("camera-photo-symbolic", "Screenshot", self.screenshot)
        self.shot.set_state(False, "Whole screen")
        self.upd = Tile("software-update-available-symbolic", "Updates", self.open_updates)
        self.files = Tile("emblem-system-symbolic", "Settings", lambda: self.open_app(["wren-settings"]))
        self.files.set_state(False, "All settings")
        self.saver = Tile("battery-caution-symbolic", "Battery saver", self.toggle_saver)
        grid.attach(self.wifi, 0, 0, 1, 1)
        grid.attach(self.bt, 1, 0, 1, 1)
        grid.attach(self.dnd, 0, 1, 1, 1)
        grid.attach(self.shot, 1, 1, 1, 1)
        if not LIVE:
            grid.attach(self.upd, 0, 2, 1, 1)
            grid.attach(self.files, 1, 2, 1, 1)
        if wrenlib.battery() is not None:
            grid.attach(self.saver, 0, 3, 2, 1)
        self.card.append(grid)

        # Wi-Fi network picker
        links = Gtk.Box(spacing=10, homogeneous=True)
        self.net_btn = Gtk.Button(label="Wi-Fi networks…")
        self.net_btn.add_css_class("pill-btn")
        self.net_btn.connect("clicked", lambda *_: self.toggle_networks())
        links.append(self.net_btn)
        self.bt_btn = Gtk.Button(label="Bluetooth devices…")
        self.bt_btn.add_css_class("pill-btn")
        self.bt_btn.connect("clicked", lambda *_: self.open_app(["wren-bluetooth"]))
        links.append(self.bt_btn)
        self.card.append(links)
        self.net_reveal = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                                       transition_duration=150)
        self.net_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.net_box.add_css_class("net-list")
        net_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                        propagate_natural_height=True, max_content_height=260)
        net_scroll.set_child(self.net_box)
        self.net_reveal.set_child(net_scroll)
        self.card.append(self.net_reveal)

        # Sliders
        self.vol_row, self.vol = self._slider("audio-volume-high-symbolic", self.set_volume)
        self.bri_row, self.bri = self._slider("display-brightness-symbolic", self.set_brightness)
        self.card.append(self.vol_row)
        self.card.append(self.bri_row)

        # Power row
        power = Gtk.Box(spacing=8, homogeneous=True)
        self.lock_btn = self._power_btn("system-lock-screen-symbolic", "Lock", lambda b: self.power("lock", b))
        power.append(self.lock_btn)
        power.append(self._power_btn("system-log-out-symbolic", "Log Out", lambda b: self.power("logout", b)))
        power.append(self._power_btn("system-reboot-symbolic", "Restart", lambda b: self.power("reboot", b), True))
        power.append(self._power_btn("system-shutdown-symbolic", "Shut Down", lambda b: self.power("poweroff", b), True))
        self.card.append(power)
        self.lock_btn.set_visible(not LIVE)
        self._confirm = None

    # -- builders
    def _slider(self, icon, callback):
        row = Gtk.Box(spacing=12)
        img = Gtk.Image.new_from_icon_name(icon)
        img.add_css_class("row-icon")
        row.append(img)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        scale.set_draw_value(False)
        scale.set_hexpand(True)
        scale.connect("value-changed", lambda s: None if self._quiet else callback(int(s.get_value())))
        row.append(scale)
        return row, scale

    def _power_btn(self, icon, text, callback, danger=False):
        btn = Gtk.Button()
        btn.add_css_class("pill-btn")
        if danger:
            btn.add_css_class("danger")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(Gtk.Image.new_from_icon_name(icon))
        lbl = label(text, xalign=0.5)
        lbl.add_css_class("caption")
        box.append(lbl)
        btn.set_child(box)
        btn.text_label = lbl
        btn.default_text = text
        btn.connect("clicked", callback)
        return btn

    # -- state
    def refresh(self):
        prefs = load_prefs()
        top = prefs.get("panel_position") == "top"
        self.card.set_valign(Gtk.Align.START if top else Gtk.Align.END)
        self.card.set_margin_top(74 if top else 12)
        self.card.set_margin_bottom(12 if top else 74)
        now = GLib.DateTime.new_now_local()
        self.clock.set_text(now.format("%H:%M" if prefs.get("clock_24h") else "%-I:%M %p"))
        self.date.set_text(now.format("%A, %B %-d"))
        self.battery.set_text(self._battery_text())
        self._show_saver()
        pending = os.path.exists(os.path.expanduser("~/.cache/wren/update-available"))
        self.upd.set_state(pending, "Update ready" if pending else "Up to date")
        self.net_reveal.set_reveal_child(False)
        self._reset_confirm()
        in_thread(self._read_state, self._apply_state)

    def _battery_text(self):
        for bat in sorted(glob.glob("/sys/class/power_supply/BAT*")):
            try:
                cap = open(f"{bat}/capacity").read().strip()
                status = open(f"{bat}/status").read().strip()
            except OSError:
                continue
            if status == "Charging":
                return f"Charging · {cap}%"
            if status == "Full":
                return "Fully charged"
            return f"Battery {cap}%"
        return ""

    def _read_state(self):
        s = {}
        s["wifi_on"] = run(["nmcli", "radio", "wifi"]) == "enabled"
        ssid = ""
        for line in run(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"]).splitlines():
            if line.startswith("yes:"):
                ssid = line[4:].replace("\\:", ":")
        s["ssid"] = ssid
        wired = any(l.split(":")[1:3] == ["ethernet", "connected"]
                    for l in run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "dev"]).splitlines())
        s["wired"] = wired
        bt = run(["bluetoothctl", "show"], timeout=3)
        s["bt_present"] = "Controller" in bt
        s["bt_on"] = "Powered: yes" in bt
        s["dnd"] = "do-not-disturb" in run(["makoctl", "mode"])
        m = re.search(r"([\d.]+)", run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"]))
        s["volume"] = round(float(m.group(1)) * 100) if m else None
        bri = run(["brightnessctl", "-m", "-c", "backlight"]).split(",")
        s["brightness"] = int(bri[3].rstrip("%")) if len(bri) > 3 and bri[3].endswith("%") else None
        return s

    def _apply_state(self, s):
        self.state = s
        if s["wired"] and not s["ssid"]:
            self.wifi.set_state(s["wifi_on"], "Wired connection")
        else:
            self.wifi.set_state(s["wifi_on"], s["ssid"] or ("Not connected" if s["wifi_on"] else "Off"))
        self.net_btn.set_visible(s["wifi_on"])
        self.bt.set_sensitive(s["bt_present"])
        self.bt.set_state(s["bt_on"], "On" if s["bt_on"] else ("Off" if s["bt_present"] else "Not available"))
        self.bt_btn.set_visible(s["bt_present"])
        self.dnd.set_state(s["dnd"], "On" if s["dnd"] else "Off")
        self._quiet = True
        self.vol_row.set_visible(s["volume"] is not None)
        if s["volume"] is not None:
            self.vol.set_value(min(s["volume"], 100))
        self.bri_row.set_visible(s["brightness"] is not None)
        if s["brightness"] is not None:
            self.bri.set_value(s["brightness"])
        self._quiet = False

    # -- actions
    def toggle_wifi(self):
        on = self.state.get("wifi_on")
        in_thread(lambda: run(["nmcli", "radio", "wifi", "off" if on else "on"]),
                  lambda _r: in_thread(self._read_state, self._apply_state))

    def toggle_bt(self):
        on = self.state.get("bt_on")
        def work():
            if not on:
                run(["rfkill", "unblock", "bluetooth"])
            run(["bluetoothctl", "power", "off" if on else "on"])
        in_thread(work, lambda _r: in_thread(self._read_state, self._apply_state))

    def _show_saver(self):
        on = wrenlib.saver_on()
        self.saver.set_state(on, "On · longer battery life" if on else "Off")

    def toggle_saver(self):
        in_thread(lambda: run(["wren-battery-saver", "toggle"], timeout=20), lambda _r: self._show_saver())
        GLib.timeout_add(150, lambda: self._show_saver() or False)

    def toggle_dnd(self):
        in_thread(lambda: run(["makoctl", "mode", "-t", "do-not-disturb"]),
                  lambda _r: in_thread(self._read_state, self._apply_state))

    def open_app(self, cmd):
        self.hide_sheet()
        spawn(cmd)

    def open_updates(self):
        self.open_app(["wren-updater"])

    def screenshot(self):
        self.hide_sheet()
        GLib.timeout_add(350, lambda: spawn(["wren-screenshot"]) or False)

    def set_volume(self, value):
        spawn(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{value / 100:.2f}"])
        if value > 0:
            spawn(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"])

    def set_brightness(self, value):
        spawn(["brightnessctl", "-q", "-c", "backlight", "set", f"{max(value, 1)}%"])

    def _reset_confirm(self):
        if self._confirm:
            self._confirm.remove_css_class("confirm")
            self._confirm.text_label.set_text(self._confirm.default_text)
        self._confirm = None

    def power(self, action, btn):
        if action in ("reboot", "poweroff") and self._confirm is not btn:
            self._reset_confirm()
            self._confirm = btn
            btn.add_css_class("confirm")
            btn.text_label.set_text("Confirm")
            return
        self.hide_sheet()
        if action == "lock":
            spawn(LOCK_CMD)
        elif action == "logout":
            spawn(["wren-logout"])
        elif LIVE and os.path.exists("/usr/lib/wren/live-power"):
            # The live USB runs from the stick; switch off/restart instantly so it can't hang
            cmd = ["/usr/lib/wren/live-power", action]
            spawn(cmd if os.geteuid() == 0 else ["sudo", "-n"] + cmd)
        else:
            spawn(["systemctl", action])

    # -- wifi networks
    def toggle_networks(self):
        showing = not self.net_reveal.get_reveal_child()
        self.net_reveal.set_reveal_child(showing)
        if showing:
            self._net_message("Looking for networks…")
            in_thread(self._scan, self._show_networks)

    def _net_message(self, text):
        child = self.net_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.net_box.remove(child)
            child = nxt
        self.net_box.append(label(text, "muted", margin_top=8, margin_bottom=8, margin_start=10))

    def _scan(self):
        out = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
                   "dev", "wifi", "list", "--rescan", "yes"], timeout=15)
        nets = {}
        for line in out.splitlines():
            parts = [p.replace("\\:", ":") for p in re.split(r"(?<!\\):", line)]
            if len(parts) < 4 or not parts[1]:
                continue
            inuse, ssid, signal, sec = parts[0] == "*", parts[1], int(parts[2] or 0), parts[3]
            if ssid not in nets or signal > nets[ssid]["signal"] or inuse:
                nets[ssid] = {"ssid": ssid, "signal": signal, "secure": sec not in ("", "--"), "inuse": inuse}
        return sorted(nets.values(), key=lambda n: (not n["inuse"], -n["signal"]))[:12]

    def _show_networks(self, nets):
        if not nets:
            self._net_message("No networks found")
            return
        self.net_box.remove(self.net_box.get_first_child())
        for net in nets:
            btn = Gtk.Button()
            btn.add_css_class("net-row")
            row = Gtk.Box(spacing=10)
            level = "excellent" if net["signal"] > 75 else "good" if net["signal"] > 50 else "ok" if net["signal"] > 25 else "weak"
            row.append(Gtk.Image.new_from_icon_name(f"network-wireless-signal-{level}-symbolic"))
            row.append(label(net["ssid"], hexpand=True, ellipsize=3))
            if net["inuse"]:
                row.append(label("Connected", "muted"))
            elif net["secure"]:
                row.append(Gtk.Image.new_from_icon_name("system-lock-screen-symbolic"))
            btn.set_child(row)
            btn.connect("clicked", lambda _b, n=net: self._connect(n))
            self.net_box.append(btn)

    def _connect(self, net):
        if net["inuse"]:
            return
        self._net_message(f"Connecting to {net['ssid']}…")
        ssid = net["ssid"]

        def done(success):
            if success:
                in_thread(self._read_state, self._apply_state)
                self.net_reveal.set_reveal_child(False)
            elif net["secure"]:
                self._ask_password(net)
            else:
                self._net_message("Couldn't connect. Try again.")
        in_thread(lambda: ok(["nmcli", "dev", "wifi", "connect", ssid], timeout=40), done)

    def _ask_password(self, net):
        self._net_message(f"Password for {net['ssid']}")
        box = Gtk.Box(spacing=8, margin_start=6, margin_end=6, margin_bottom=6)
        entry = Gtk.PasswordEntry(show_peek_icon=True, hexpand=True)
        go = Gtk.Button(label="Connect")
        go.add_css_class("suggested-action")
        box.append(entry)
        box.append(go)
        self.net_box.append(box)
        entry.grab_focus()

        def submit(*_):
            pw = entry.get_text()
            if not pw:
                return
            self._net_message(f"Connecting to {net['ssid']}…")
            in_thread(lambda: ok(["nmcli", "dev", "wifi", "connect", net["ssid"], "password", pw], timeout=40),
                      lambda success: (in_thread(self._read_state, self._apply_state),
                                       self.net_reveal.set_reveal_child(False)) if success
                      else self._net_message("Wrong password or the network didn't respond."))
        go.connect("clicked", submit)
        entry.connect("activate", submit)


# ------------------------------------------------------------------- app

class Shell(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.wrenlinux.Shell",
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.sheets = {}
        self.held = False

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.restyle = wrenlib.setup_app_style(CSS)
        for name in ("launcher", "control"):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, n=name: self.toggle_sheet(n))
            self.add_action(action)

    def do_activate(self):
        pass

    # -- power: Battery saver on low battery, and no apps left running without a window
    def watch_power(self):
        self._windowless = set()
        self._was_on_battery = None
        GLib.timeout_add_seconds(60, self._power_tick)

    def _power_tick(self):
        in_thread(self._power_work)
        return True

    def _power_work(self):
        p = wrenlib.prefs()
        bat = wrenlib.battery()
        if bat is not None:
            pct, _status = bat
            on_bat = wrenlib.on_battery()
            flag = wrenlib.SAVER_FLAG
            auto_at = p.get("saver_auto_at", 20)
            now_on = wrenlib.saver_on()
            # Turned off by hand while the battery is low: don't switch it straight back on
            if not on_bat:
                self._declined = False
            elif getattr(self, "_saver_was_on", False) and not now_on:
                self._declined = True
            self._saver_was_on = now_on
            if on_bat and auto_at and pct <= auto_at and not now_on and not getattr(self, "_declined", False):
                run(["wren-battery-saver", "on", "--auto"], timeout=20)
                self._saver_was_on = True
            elif not on_bat and wrenlib.saver_on():
                try:
                    auto = open(flag).read().strip() == "auto"
                except OSError:
                    auto = False
                if auto:
                    run(["wren-battery-saver", "off"], timeout=20)
                    self._saver_was_on = False
            self._was_on_battery = on_bat
        if not wrenlib.background_allowed():
            self._stop_background_apps()

    def _stop_background_apps(self):
        import winlist
        running = [l.split("\t") for l in run(["flatpak", "ps", "--columns=application"]).splitlines()]
        apps = {r[0].strip() for r in running if r and r[0].strip()}
        if not apps:
            self._windowless = set()
            return
        windows = winlist.app_ids()
        if not windows:  # couldn't read the list (or nothing open at all): leave everything alone
            return
        open_ids = {w.lower() for w in windows if w}

        def has_window(app):
            a = app.lower()
            last = a.rsplit(".", 1)[-1]
            return any(w == a or w == last or w.startswith(a) or w.rsplit(".", 1)[-1] == last for w in open_ids)
        idle = {a for a in apps if not has_window(a)}
        # Only stop an app after it has had no window for two checks in a row
        for app in idle & self._windowless:
            run(["flatpak", "kill", app], timeout=10)
        self._windowless = idle

    def toggle_sheet(self, what):
        for name, sheet in self.sheets.items():
            if name != what:
                sheet.hide_sheet()
        self.sheet(what).toggle()

    def sheet(self, name):
        if name not in self.sheets:
            self.sheets[name] = (Launcher if name == "launcher" else Control)(self)
        return self.sheets[name]

    def do_command_line(self, cmdline):
        if not self.held:
            self.hold()
            self.held = True
        args = cmdline.get_arguments()[1:]
        what = args[0] if args else "--service"
        if what in ("launcher", "control"):
            self.toggle_sheet(what)
        elif what == "--service":
            # build both ahead of time so the first open is instant
            self.sheet("launcher")
            self.sheet("control")
            if not getattr(self, "_watching", False):
                self._watching = True
                self.watch_power()
        return 0


if __name__ == "__main__":
    sys.exit(Shell().run(sys.argv))
