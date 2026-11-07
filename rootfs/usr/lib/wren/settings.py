#!/usr/bin/env python3
"""Floe Settings: one place for display, sound, network, Bluetooth, mouse and
touchpad, background, default apps, time, accounts and updates.

  wren-settings [page]     page: system, display, sound, notifications, power, storage,
                           about, devices, network, personalization, apps, accounts,
                           time, update
"""
import glob
import json
import os
import platform
import pwd
import re
import shutil
import socket
import subprocess
import sys
import threading
from xml.sax.saxutils import escape

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

sys.path.insert(0, "/usr/lib/wren")
import wrenlib  # noqa: E402

try:
    import theme as wtheme  # noqa: E402
except Exception:  # pragma: no cover
    wtheme = None

CONF = os.path.join(GLib.get_user_config_dir(), "wren")
ENV_FILE = os.path.join(CONF, "settings.env")
PREFS_FILE = os.path.join(CONF, "settings.json")
LABWC_DIR = os.path.join(GLib.get_user_config_dir(), "labwc")
WALLPAPERS = "/usr/share/wren/wallpapers"
LIVE = os.path.isdir("/run/archiso")

CSS = """
.settings { background-color: @wren_bg; }
.nav { background-color: @wren_deep; border-right: 1px solid @wren_line; padding: 0 10px; }
.nav row { padding: 8px 12px; margin: 1px 0; border-radius: 8px; color: @wren_text2; }
.nav row:hover { background-color: alpha(@wren_text, 0.05); color: @wren_text; }
.nav row:selected { background-color: alpha(@wren_accent, 0.10); color: @wren_accent_text; font-weight: 600; }
.nav row:selected image { color: @wren_accent; }
.nav > row, .nav list { background: transparent; }
.me { padding: 18px 8px 14px 8px; }
.me-avatar { background-color: @wren_accent; color: @wren_on_accent;
             font-weight: 500; font-size: 20px; min-width: 48px; min-height: 48px; border-radius: 999px; }
.me-name { font-weight: 600; font-size: 15px; }
.me-sub { color: @wren_muted; font-size: 12px; }
.page-title { font-size: 26px; font-weight: 600; letter-spacing: -0.3px; }
.wordmark { font-family: "IBM Plex Sans"; font-size: 44px; font-weight: 500; letter-spacing: 0.5px; margin-bottom: 6px; }
.crumb { color: @wren_muted; font-size: 13px; }
.group-title { font-size: 15px; font-weight: 600; color: @wren_text; margin: 28px 0 10px 2px; }
.card { background-color: @wren_surface; border: 1px solid @wren_border; border-radius: 12px; box-shadow: none; }
.card + .card { margin-top: 6px; }
.row { padding: 12px 16px; min-height: 34px; }
.row + .row { border-top: 1px solid @wren_line; }
.row.link:hover { background-color: alpha(@wren_text, 0.03); }
.row-icon { color: @wren_dim; min-width: 34px; }
.row-title { font-weight: 500; }
.row-sub { color: @wren_dim; font-size: 12px; }
.big-stat { font-size: 28px; font-weight: 300; }
.btn { padding: 6px 16px; font-weight: 600; border-radius: 8px; }
.btn.primary { background-color: @wren_accent; color: @wren_on_accent; box-shadow: none; }
.btn.primary:hover { background-color: @wren_accent_hover; }
.wall { border: 2px solid transparent; padding: 2px; border-radius: 12px; }
.wall picture { border-radius: 8px; }
.wall.chosen { border-color: @wren_accent; }
.tile-grid > flowboxchild { padding: 0; }
.mode-tile { padding: 0; border: 1px solid @wren_border; background: @wren_surface; border-radius: 12px; }
.mode-tile.chosen { border-color: @wren_accent; box-shadow: inset 0 0 0 1px @wren_accent; }
.mode-tile .preview { min-width: 150px; min-height: 84px; border-radius: 11px 11px 0 0; }
.mode-tile .preview.dark { background-image: linear-gradient(160deg, #2A3140, #12151B); }
.mode-tile .preview.light { background-image: linear-gradient(160deg, #FFFFFF, #DCE3EE); }
.mode-tile .bar { min-height: 10px; margin: 10px 12px 0 12px; border-radius: 999px; }
.mode-tile .dark .bar { background-color: rgba(255, 255, 255, 0.14); }
.mode-tile .light .bar { background-color: rgba(30, 45, 70, 0.12); }
.mode-tile .blob { min-width: 46px; min-height: 8px; margin: 8px 12px 0 12px; background-color: @wren_accent; border-radius: 999px; }
.mode-tile .dark .line2 { background-color: rgba(255, 255, 255, 0.22); min-width: 80px; min-height: 6px; margin: 6px 12px 0 12px; border-radius: 999px; }
.mode-tile .light .line2 { background-color: rgba(30, 45, 70, 0.18); min-width: 80px; min-height: 6px; margin: 6px 12px 0 12px; border-radius: 999px; }
.mode-name { padding: 8px 12px; font-weight: 500; }
.swatch { min-width: 28px; min-height: 28px; padding: 3px; border: 2px solid transparent; border-radius: 999px; background: none; }
.swatch.chosen { border-color: @wren_text; }
.swatch > box { margin: 0; border-radius: 999px; }
levelbar trough { min-height: 10px; background-color: @wren_line; border-radius: 999px; }
levelbar block { border-radius: 999px; }
levelbar block.filled { background-color: @wren_accent; }
levelbar block.empty { background-color: @wren_line; }
"""


# ------------------------------------------------------------------ helpers
def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def ok(cmd, timeout=60):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).returncode == 0
    except Exception:
        return False


def spawn(cmd):
    try:
        subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def background(fn, done=None):
    def work():
        try:
            result = fn()
        except Exception:
            result = None
        if done:
            GLib.idle_add(lambda: done(result) or False)
    threading.Thread(target=work, daemon=True).start()


def load_prefs():
    try:
        return json.load(open(PREFS_FILE))
    except (OSError, ValueError):
        return {}


def save_prefs(prefs):
    os.makedirs(CONF, exist_ok=True)
    with open(PREFS_FILE, "w") as f:
        json.dump(prefs, f, indent=2)
    env = {
        "WREN_WALLPAPER": prefs.get("wallpaper", wrenlib.DEFAULT_WALLPAPER),
        "WREN_LOCK_AFTER": str(prefs.get("lock_after", 600)),
        "WREN_SLEEP_AFTER": str(prefs.get("sleep_after", 0)),
    }
    with open(ENV_FILE, "w") as f:
        for k, v in env.items():
            f.write(f"{k}={GLib.shell_quote(v)}\n")


def write_labwc_user_config(prefs):
    """Mouse, touchpad and keyboard settings for the window manager: Wayfire's config, plus
    the labwc files used by the fallback session on computers that can't run Wayfire."""
    os.makedirs(LABWC_DIR, exist_ok=True)
    yn = lambda b: "yes" if b else "no"  # noqa: E731
    rc = f"""<?xml version="1.0"?>
<!-- Written by Floe Settings. Merged on top of /etc/xdg/labwc/rc.xml. -->
<labwc_config>
  <libinput>
    <device category="non-touch">
      <naturalScroll>{yn(prefs.get("mouse_natural", False))}</naturalScroll>
      <pointerSpeed>{prefs.get("mouse_speed", 0.0):.2f}</pointerSpeed>
      <leftHanded>{yn(prefs.get("left_handed", False))}</leftHanded>
    </device>
    <device category="touchpad">
      <tap>{yn(prefs.get("tap_to_click", True))}</tap>
      <naturalScroll>{yn(prefs.get("touchpad_natural", True))}</naturalScroll>
      <disableWhileTyping>{yn(prefs.get("dwt", True))}</disableWhileTyping>
      <pointerSpeed>{prefs.get("touchpad_speed", 0.0):.2f}</pointerSpeed>
      <leftHanded>{yn(prefs.get("left_handed", False))}</leftHanded>
    </device>
  </libinput>
  <keyboard>
    <repeatRate>{int(prefs.get("repeat_rate", 25))}</repeatRate>
    <repeatDelay>{int(prefs.get("repeat_delay", 600))}</repeatDelay>
  </keyboard>
</labwc_config>
"""
    with open(os.path.join(LABWC_DIR, "rc.xml"), "w") as f:
        f.write(rc)
    env_path = os.path.join(LABWC_DIR, "environment")
    try:
        keep = [l for l in open(env_path).read().splitlines()
                if l.strip() and not l.startswith(("XKB_DEFAULT_LAYOUT=", "XCURSOR_SIZE="))]
    except OSError:
        keep = []
    if prefs.get("keyboard"):
        keep.append(f"XKB_DEFAULT_LAYOUT={escape(prefs['keyboard'])}")
    if prefs.get("cursor_size"):
        keep.append(f"XCURSOR_SIZE={int(prefs['cursor_size'])}")
    with open(env_path, "w") as f:
        f.write("\n".join(keep) + ("\n" if keep else ""))
    # Wayfire (the normal window manager) reloads its config file by itself
    if wtheme:
        try:
            wtheme.wm_config()
        except Exception:
            pass
    if os.environ.get("LABWC_PID"):
        spawn(["labwc", "--reconfigure"])


def label(text, css="", **kw):
    kw.setdefault("xalign", 0)
    lbl = Gtk.Label(label=text, **kw)
    for c in css.split():
        lbl.add_css_class(c)
    return lbl


def dropdown(items, selected=0, on_change=None):
    dd = Gtk.DropDown.new_from_strings(items)
    dd.set_valign(Gtk.Align.CENTER)
    if 0 <= selected < len(items):
        dd.set_selected(selected)
    if on_change:
        dd.connect("notify::selected", lambda d, _p: on_change(d.get_selected()))
    return dd


def switch(active, on_change):
    sw = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
    sw.connect("notify::active", lambda s, _p: on_change(s.get_active()))
    return sw


def button(text, cb, primary=False):
    b = Gtk.Button(label=text, valign=Gtk.Align.CENTER)
    b.add_css_class("btn")
    if primary:
        b.add_css_class("primary")
    b.connect("clicked", lambda *_: cb())
    return b


def screen_title(out, name):
    """A name people recognise: "Built-in screen", or the monitor's brand and model."""
    if name.split("-")[0] in ("eDP", "LVDS", "DSI"):
        return "Built-in screen"
    brand = " ".join(x for x in (out.get("make"), out.get("model")) if x and x not in ("Unknown", "None"))
    return brand or f"Screen ({name})"


class Card(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("card")

    def row(self, icon, title, subtitle="", control=None, on_click=None):
        box = Gtk.Box(spacing=14)
        box.add_css_class("row")
        img = Gtk.Image.new_from_icon_name(icon) if icon else Gtk.Image()
        img.add_css_class("row-icon")
        box.append(img)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        text.append(label(title, "row-title", wrap=True))
        sub = label(subtitle, "row-sub", wrap=True, visible=bool(subtitle))
        text.append(sub)
        box.append(text)
        if control is not None:
            box.append(control)
        if on_click:
            box.add_css_class("link")
            box.append(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            click = Gtk.GestureClick()
            click.connect("released", lambda *_: on_click())
            box.add_controller(click)
            box.set_cursor(Gdk.Cursor.new_from_name("pointer"))
        box.subtitle = sub
        self.append(box)
        return box


# ------------------------------------------------------------------ pages
class Pages:
    """Each page is a method returning a widget; 'nav' lists the sidebar."""

    nav = [
        ("system", "System", "computer-symbolic"),
        ("devices", "Bluetooth & devices", "bluetooth-active-symbolic"),
        ("network", "Network & internet", "network-wireless-symbolic"),
        ("personalization", "Personalization", "applications-graphics-symbolic"),
        ("apps", "Apps", "view-app-grid-symbolic"),
        ("accounts", "Accounts", "avatar-default-symbolic"),
        ("time", "Time & language", "preferences-system-time-symbolic"),
        ("update", "Floe Update", "software-update-available-symbolic"),
    ]

    def __init__(self, win):
        self.win = win
        self.prefs = load_prefs()

    def save(self):
        save_prefs(self.prefs)

    def page(self, title, crumb=None):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        if crumb:
            back = Gtk.Box(spacing=6)
            link = Gtk.Button(label=crumb[0])
            link.add_css_class("flat")
            link.add_css_class("crumb")
            link.connect("clicked", lambda *_: self.win.open(crumb[1]))
            back.append(link)
            back.append(label("›", "crumb"))
            box.append(back)
        box.append(label(title, "page-title", margin_bottom=10))
        return box

    def group(self, box, title):
        box.append(label(title, "group-title"))
        card = Card()
        box.append(card)
        return card

    # -------------------------------------------------------- System
    def system(self):
        box = self.page("System")
        host = socket.gethostname()
        head = Card()
        r = head.row("computer-symbolic", host, f"Floe, build {wren_build()}",
                     button("Rename", lambda: self.win.open("about")))
        r.get_first_child().set_pixel_size(32)
        box.append(head)
        card = self.group(box, "Settings")
        for key, title, sub, icon in (
            ("display", "Display", "Brightness, resolution, scale", "video-display-symbolic"),
            ("sound", "Sound", "Volume, output and input devices", "audio-volume-high-symbolic"),
            ("notifications", "Notifications", "Do not disturb", "preferences-system-notifications-symbolic"),
            ("power", "Power & battery", "Battery, screen lock and sleep", "battery-good-symbolic"),
            ("storage", "Storage", "Space used on your drive", "drive-harddisk-symbolic"),
            ("about", "About", "Device name and specs", "help-about-symbolic"),
        ):
            card.row(icon, title, sub, on_click=lambda k=key: self.win.open(k))
        return box

    def display(self):
        box = self.page("Display", ("System", "system"))
        card = self.group(box, "Brightness")
        bri = run(["brightnessctl", "-m", "-c", "backlight"]).split(",")
        if len(bri) > 3 and bri[3].endswith("%"):
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
            scale.set_value(int(bri[3].rstrip("%")))
            scale.set_size_request(260, -1)
            scale.connect("value-changed", lambda s: spawn(["brightnessctl", "-q", "-c", "backlight", "set",
                                                            f"{int(s.get_value())}%"]))
            card.row("display-brightness-symbolic", "Brightness", "", scale)
        else:
            card.row("display-brightness-symbolic", "Brightness", "This screen's brightness can't be changed here.")

        outputs = []
        try:
            outputs = json.loads(run(["wlr-randr", "--json"]) or "[]")
        except ValueError:
            pass
        for out in [o for o in outputs if o.get("enabled", True)]:
            name = out.get("name", "")
            card = self.group(box, screen_title(out, name))
            modes = out.get("modes", [])
            uniq = []
            for m in modes:
                key = (m["width"], m["height"])
                if key not in [(u["width"], u["height"]) for u in uniq]:
                    uniq.append(m)
            uniq.sort(key=lambda m: -m["width"] * m["height"])
            cur = next((m for m in modes if m.get("current")), uniq[0] if uniq else None)
            labels = [f"{m['width']} × {m['height']}" + ("  (recommended)" if m.get("preferred") else "") for m in uniq]
            sel = next((i for i, m in enumerate(uniq) if cur and (m["width"], m["height"]) == (cur["width"], cur["height"])), 0)
            scales = [1.0, 1.25, 1.5, 1.75, 2.0]
            cur_scale = float(out.get("scale", 1.0))
            ssel = min(range(len(scales)), key=lambda i: abs(scales[i] - cur_scale))
            res_dd = dropdown(labels, sel)
            scale_dd = dropdown([f"{int(s * 100)}%" for s in scales], ssel)
            card.row("video-display-symbolic", "Display resolution", "", res_dd)
            card.row("zoom-in-symbolic", "Scale", "", scale_dd)

            def apply(name=name, uniq=uniq, res_dd=res_dd, scale_dd=scale_dd):
                if not uniq:
                    return
                m = uniq[res_dd.get_selected()]
                cmd = ["wlr-randr", "--output", name, "--mode", f"{m['width']}x{m['height']}",
                       "--scale", str(scales[scale_dd.get_selected()])]
                if ok(cmd, 15):
                    os.makedirs(CONF, exist_ok=True)
                    path = os.path.join(CONF, "display.sh")
                    lines = []
                    try:
                        lines = [l for l in open(path).read().splitlines()
                                 if l.strip() and not l.startswith("#!") and f"--output {name} " not in l]
                    except OSError:
                        pass
                    lines.append(" ".join(GLib.shell_quote(c) for c in cmd))
                    with open(path, "w") as f:
                        f.write("#!/bin/sh\n# Written by Floe Settings\n" + "\n".join(lines) + "\n")
                    os.chmod(path, 0o755)
                    self.win.toast("Display settings applied")
                else:
                    self.win.toast("That display setting didn't work")
            card.row(None, "Apply changes", "", button("Apply", apply, primary=True))
        if not outputs:
            box.append(label("Display details aren't available right now.", "row-sub", margin_top=8))

        night = self.group(box, "Night light")
        temps = [(4500, "Mild"), (3800, "Warm"), (3200, "Warmer"), (2700, "Warmest")]
        scheds = [("always", "All the time"), ("evening", "7 PM to 7 AM"), ("late", "9 PM to 7 AM")]

        def setn(key, value):
            self.prefs[key] = value
            self.save()
            spawn(["wren-nightlight"])
        cur_t = self.prefs.get("night_temp", 3800)
        cur_s = self.prefs.get("night_schedule", "evening")
        night.row("night-light-symbolic", "Night light", "",
                  switch(self.prefs.get("night_light", False), lambda v: setn("night_light", v)))
        night.row(None, "Strength", "", dropdown([t for _, t in temps],
                  next((i for i, (v, _) in enumerate(temps) if v == cur_t), 1),
                  lambda i: setn("night_temp", temps[i][0])))
        night.row(None, "When", "", dropdown([t for _, t in scheds],
                  next((i for i, (v, _) in enumerate(scheds) if v == cur_s), 1),
                  lambda i: setn("night_schedule", scheds[i][0])))
        more = self.group(box, "More")
        more.row("preferences-desktop-display-symbolic", "Arrange multiple displays", "Position, rotate and turn screens on or off",
                 on_click=lambda: spawn(["wdisplays"]))
        return box

    def sound(self):
        box = self.page("Sound", ("System", "system"))

        def devices(kind):
            try:
                items = json.loads(run(["pactl", "-f", "json", "list", kind]) or "[]")
            except ValueError:
                items = []
            default = run(["pactl", "get-default-sink" if kind == "sinks" else "get-default-source"])
            items = [d for d in items if not (kind == "sources" and d.get("monitor_source") == "" and
                                              ".monitor" in d.get("name", ""))]
            items = [d for d in items if ".monitor" not in d.get("name", "")]
            return items, default

        for kind, title, icon, setcmd, volcmd, getvol in (
            ("sinks", "Output", "audio-speakers-symbolic", "set-default-sink", "set-sink-volume", "get-sink-volume"),
            ("sources", "Input", "audio-input-microphone-symbolic", "set-default-source", "set-source-volume",
             "get-source-volume"),
        ):
            card = self.group(box, title)
            items, default = devices(kind)
            if not items:
                card.row(icon, f"No {title.lower()} devices found", "")
                continue
            names = [d.get("description") or d.get("name") for d in items]
            sel = next((i for i, d in enumerate(items) if d.get("name") == default), 0)
            dd = dropdown(names, sel, lambda i, items=items, setcmd=setcmd: spawn(["pactl", setcmd, items[i]["name"]]))
            card.row(icon, f"Choose where sound {'plays' if kind == 'sinks' else 'comes from'}", "", dd)
            target = "@DEFAULT_SINK@" if kind == "sinks" else "@DEFAULT_SOURCE@"
            m = re.search(r"(\d+)%", run(["pactl", getvol, target]))
            vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
            vol.set_value(int(m.group(1)) if m else 50)
            vol.set_size_request(260, -1)
            vol.connect("value-changed", lambda s, volcmd=volcmd, target=target: spawn(
                ["pactl", volcmd, target, f"{int(s.get_value())}%"]))
            card.row("audio-volume-high-symbolic" if kind == "sinks" else "microphone-sensitivity-high-symbolic",
                     "Volume", "", vol)
        more = self.group(box, "More")
        more.row("preferences-system-symbolic", "More sound settings", "Per-app volume and advanced options",
                 on_click=lambda: spawn(["pavucontrol"]))
        return box

    def notifications(self):
        box = self.page("Notifications", ("System", "system"))
        card = self.group(box, "Notifications")
        dnd = "do-not-disturb" in run(["makoctl", "mode"])
        card.row("notifications-disabled-symbolic", "Do not disturb",
                 "Hide notification pop-ups. They're still saved.",
                 switch(dnd, lambda on: spawn(["makoctl", "mode", "-a" if on else "-r", "do-not-disturb"])))
        return box

    def power(self):
        box = self.page("Power & battery", ("System", "system"))
        bats = sorted(glob.glob("/sys/class/power_supply/BAT*"))
        if bats:
            try:
                cap = open(f"{bats[0]}/capacity").read().strip()
                status = open(f"{bats[0]}/status").read().strip()
            except OSError:
                cap, status = "?", "Unknown"
            card = self.group(box, "Battery")
            stat = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            stat.append(label(f"{cap}%", "big-stat"))
            nice = {"Charging": "Charging", "Discharging": "On battery", "Full": "Fully charged",
                    "Not charging": "Plugged in, not charging"}.get(status, status)
            stat.append(label(nice, "row-sub"))
            lvl = Gtk.LevelBar(min_value=0, max_value=100, hexpand=True, valign=Gtk.Align.CENTER)
            try:
                lvl.set_value(float(cap))
            except ValueError:
                pass
            row = Gtk.Box(spacing=24)
            row.add_css_class("row")
            row.append(stat)
            row.append(lvl)
            card.append(row)

            saver = self.group(box, "Battery saver")
            saver_sw = switch(wrenlib.saver_on(), lambda v: background(
                lambda: run(["wren-battery-saver", "on" if v else "off"], 20)))
            saver.row("battery-caution-symbolic", "Battery saver",
                      "Dims the screen and cuts background activity", saver_sw)
            autos = [(10, "At 10%"), (20, "At 20%"), (30, "At 30%"), (50, "At 50%"), (0, "Never")]
            cur_a = self.prefs.get("saver_auto_at", 20)

            def set_auto(i):
                self.prefs["saver_auto_at"] = autos[i][0]
                self.save()
            saver.row(None, "Turn on automatically", "It turns off again when you plug in",
                      dropdown([t for _, t in autos], next((i for i, (v, _) in enumerate(autos) if v == cur_a), 1),
                               set_auto))
        self.background_row(self.group(box, "Background apps"))
        card = self.group(box, "Screen and sleep")
        lock_opts = [(60, "1 minute"), (300, "5 minutes"), (600, "10 minutes"), (900, "15 minutes"),
                     (1800, "30 minutes"), (0, "Never")]
        sleep_opts = [(900, "15 minutes"), (1800, "30 minutes"), (3600, "1 hour"), (0, "Never")]

        def pick(opts, key, default):
            cur = self.prefs.get(key, default)
            return next((i for i, (v, _) in enumerate(opts) if v == cur), 0)

        def set_opt(key, opts, i):
            self.prefs[key] = opts[i][0]
            self.save()
            spawn(["wren-idle"])
        card.row("system-lock-screen-symbolic", "Lock the screen after", "",
                 dropdown([t for _, t in lock_opts], pick(lock_opts, "lock_after", 600),
                          lambda i: set_opt("lock_after", lock_opts, i)))
        card.row("weather-clear-night-symbolic", "Sleep after", "",
                 dropdown([t for _, t in sleep_opts], pick(sleep_opts, "sleep_after", 0),
                          lambda i: set_opt("sleep_after", sleep_opts, i)))
        return box

    def storage(self):
        box = self.page("Storage", ("System", "system"))
        card = self.group(box, "Your drive")
        u = shutil.disk_usage("/")
        gb = lambda n: f"{n / 1e9:.1f} GB"  # noqa: E731
        stat = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        stat.add_css_class("row")
        stat.append(label(f"{gb(u.used)} used of {gb(u.total)}", "row-title"))
        lvl = Gtk.LevelBar(min_value=0, max_value=1)
        lvl.set_value(u.used / u.total if u.total else 0)
        stat.append(lvl)
        stat.append(label(f"{gb(u.free)} free", "row-sub"))
        card.append(stat)
        more = self.group(box, "Clean up")
        more.row("drive-harddisk-symbolic", "See what's using space", "Find big files and folders",
                 on_click=lambda: spawn(["baobab"]))
        more.row("user-trash-symbolic", "Empty the trash", "",
                 button("Empty", lambda: (ok(["gio", "trash", "--empty"]), self.win.toast("Trash emptied"))))
        return box

    def about(self):
        box = self.page("About", ("System", "system"))
        # The Floe mark and name (set as text, so it follows light and dark mode)
        brand = Gtk.Box(spacing=14, margin_top=8, margin_bottom=4)
        mark = Gtk.Image.new_from_file("/usr/share/wren/logo-128.png")
        mark.set_pixel_size(64)
        brand.append(mark)
        brand.append(label("floe", "wordmark", valign=Gtk.Align.CENTER))
        box.append(brand)
        card = self.group(box, "This computer")
        name_entry = Gtk.Entry(text=socket.gethostname(), valign=Gtk.Align.CENTER, width_chars=18)

        def rename():
            new = name_entry.get_text().strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}", new):
                self.win.toast("Use letters, numbers and dashes only")
                return
            background(lambda: ok(["hostnamectl", "set-hostname", new]),
                       lambda r: self.win.toast("Renamed. It'll show everywhere after a restart." if r
                                                else "Couldn't rename the computer"))
        row = Gtk.Box(spacing=8)
        row.append(name_entry)
        row.append(button("Rename", rename))
        card.row("computer-symbolic", "Device name", "", row)
        specs = self.group(box, "Specifications")
        for title, value in (("Floe", f"Build {wren_build()}"),
                             ("Processor", cpu_name()),
                             ("Memory", mem_total()),
                             ("Graphics", gpu_name()),
                             ("Linux kernel", platform.release()),
                             ("System type", f"{platform.machine()} (64-bit)")):
            specs.row(None, title, value)
        return box

    # -------------------------------------------------------- Devices
    def devices(self):
        box = self.page("Bluetooth & devices")
        card = self.group(box, "Bluetooth")
        bt = run(["bluetoothctl", "show"], 3)
        if "Controller" in bt:
            card.row("bluetooth-active-symbolic", "Bluetooth", "",
                     switch("Powered: yes" in bt, lambda on: background(
                         lambda: (subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True) if on else None,
                                  run(["bluetoothctl", "power", "on" if on else "off"])))))
        else:
            card.row("bluetooth-disabled-symbolic", "Bluetooth", "No Bluetooth adapter found on this computer")
        card.row("list-add-symbolic", "Pair and manage devices", "Headphones, mice, keyboards, phones",
                 on_click=lambda: spawn(["wren-bluetooth"]))

        def setp(key, value):
            self.prefs[key] = value
            self.save()
            write_labwc_user_config(self.prefs)

        def speed(key):
            s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -1, 1, 0.05)
            s.set_value(self.prefs.get(key, 0.0))
            s.set_size_request(220, -1)
            s.set_draw_value(False)
            s.connect("value-changed", lambda w: setp(key, round(w.get_value(), 2)))
            return s

        mouse = self.group(box, "Mouse")
        mouse.row("input-mouse-symbolic", "Pointer speed", "", speed("mouse_speed"))
        mouse.row(None, "Natural scrolling", "",
                  switch(self.prefs.get("mouse_natural", False), lambda v: setp("mouse_natural", v)))
        mouse.row(None, "Left-handed buttons", "",
                  switch(self.prefs.get("left_handed", False), lambda v: setp("left_handed", v)))
        pad = self.group(box, "Touchpad")
        pad.row("input-touchpad-symbolic", "Tap to click", "",
                switch(self.prefs.get("tap_to_click", True), lambda v: setp("tap_to_click", v)))
        pad.row(None, "Natural scrolling", "",
                switch(self.prefs.get("touchpad_natural", True), lambda v: setp("touchpad_natural", v)))
        pad.row(None, "Ignore the touchpad while typing", "",
                switch(self.prefs.get("dwt", True), lambda v: setp("dwt", v)))
        pad.row(None, "Touchpad speed", "", speed("touchpad_speed"))
        return box

    # -------------------------------------------------------- Network
    def network(self):
        box = self.page("Network & internet")
        status = self.group(box, "Status")
        conn_row = status.row("network-wireless-symbolic", "Checking…", "")
        wifi_on = run(["nmcli", "radio", "wifi"]) == "enabled"
        card = self.group(box, "Wi-Fi")
        card.row("network-wireless-symbolic", "Wi-Fi", "",
                 switch(wifi_on, lambda on: background(lambda: run(["nmcli", "radio", "wifi", "on" if on else "off"]),
                                                       lambda _r: self.win.open("network"))))
        all_off = run(["nmcli", "radio", "all"]).split()
        card.row("airplane-mode-symbolic", "Airplane mode", "Turns off Wi-Fi and Bluetooth",
                 switch(bool(all_off) and all(x == "disabled" for x in all_off[-2:]),
                        lambda on: background(lambda: (run(["nmcli", "radio", "all", "off" if on else "on"]),
                                                       run(["rfkill", "block" if on else "unblock", "bluetooth"])),
                                              lambda _r: self.win.open("network"))))
        nets = self.group(box, "Available networks")
        waiting = nets.row(None, "Looking for networks…", "")

        def status_info():
            dev = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
            for line in dev.splitlines():
                p = line.split(":")
                if len(p) >= 4 and p[2] == "connected" and p[1] in ("wifi", "ethernet"):
                    ip = run(["nmcli", "-g", "IP4.ADDRESS", "device", "show", p[0]]).split("|")[0]
                    return p[1], p[3], ip
            return None

        def show_status(info):
            if info:
                kind, name, ip = info
                conn_row.get_first_child().set_from_icon_name(
                    "network-wired-symbolic" if kind == "ethernet" else "network-wireless-symbolic")
                title = conn_row.get_first_child().get_next_sibling().get_first_child()
                title.set_text(f"Connected to {name}")
                conn_row.subtitle.set_text(f"IP address {ip.split('/')[0]}" if ip else "")
                conn_row.subtitle.set_visible(bool(ip))
            else:
                title = conn_row.get_first_child().get_next_sibling().get_first_child()
                title.set_text("Not connected")
        background(status_info, show_status)

        def scan():
            out = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes"], 20)
            seen = {}
            for line in out.splitlines():
                p = [x.replace("\\:", ":") for x in re.split(r"(?<!\\):", line)]
                if len(p) >= 4 and p[1]:
                    sig = int(p[2] or 0)
                    if p[1] not in seen or sig > seen[p[1]]["signal"]:
                        seen[p[1]] = {"ssid": p[1], "signal": sig, "secure": p[3] not in ("", "--"), "inuse": p[0] == "*"}
            return sorted(seen.values(), key=lambda n: (not n["inuse"], -n["signal"]))[:15]

        def show(nets_found):
            nets.remove(waiting)
            if not wifi_on:
                nets.row(None, "Wi-Fi is off", "")
                return
            if not nets_found:
                nets.row(None, "No networks found", "")
                return
            for n in nets_found:
                lvl = "excellent" if n["signal"] > 75 else "good" if n["signal"] > 50 else "ok" if n["signal"] > 25 else "weak"
                ctl = label("Connected", "row-sub") if n["inuse"] else button("Connect", lambda n=n: self.connect_wifi(n))
                nets.row(f"network-wireless-signal-{lvl}-symbolic", n["ssid"],
                         "Secured" if n["secure"] else "Open network", ctl)
        background(scan, show)
        more = self.group(box, "More")
        more.row("preferences-system-network-symbolic", "Advanced network settings",
                 "VPN, proxies, static IP, hidden networks", on_click=lambda: spawn(["nm-connection-editor"]))
        return box

    def connect_wifi(self, n):
        def attempt(password=None):
            cmd = ["nmcli", "dev", "wifi", "connect", n["ssid"]] + (["password", password] if password else [])
            self.win.toast(f"Connecting to {n['ssid']}…")
            background(lambda: ok(cmd, 45), lambda r: (self.win.toast(f"Connected to {n['ssid']}"), self.win.open("network"))
                       if r else (ask() if n["secure"] else self.win.toast("Couldn't connect")))

        def ask():
            entry = Gtk.PasswordEntry(show_peek_icon=True)
            d = Adw.AlertDialog(heading=f"Connect to {n['ssid']}", body="Enter the Wi-Fi password.")
            d.set_extra_child(entry)
            d.add_response("cancel", "Cancel")
            d.add_response("ok", "Connect")
            d.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
            d.set_default_response("ok")
            d.connect("response", lambda _d, r: r == "ok" and attempt(entry.get_text()))
            d.present(self.win)
        if n["secure"] and not run(["nmcli", "-g", "NAME", "connection", "show"]).count(n["ssid"]):
            ask()
        else:
            attempt()

    # -------------------------------------------------------- Personalization
    def personalization(self):
        box = self.page("Personalization")
        self.colors(box)
        box.append(label("Background", "group-title"))
        current = self.prefs.get("wallpaper", wrenlib.DEFAULT_WALLPAPER)
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, min_children_per_line=2,
                           row_spacing=8, column_spacing=8, homogeneous=True)
        flow.add_css_class("tile-grid")
        buttons = []

        def choose(path):
            self.prefs["wallpaper"] = path
            self.save()
            spawn(["wren-wallpaper"])
            if wtheme:  # the lock screen uses the same picture
                background(lambda: wtheme.generate(reload=False))
            for b in buttons:
                (b.add_css_class if b.path == path else b.remove_css_class)("chosen")

        walls = sorted(glob.glob(f"{WALLPAPERS}/*.jpg"))
        walls = [w for w in walls if not w.endswith(("-thumb.jpg", "-blur.jpg"))]
        if current not in walls and os.path.exists(current):
            walls.append(current)
        for w in walls:
            thumb = w.replace(".jpg", "-thumb.jpg")
            pic = Gtk.Picture.new_for_filename(thumb if os.path.exists(thumb) else w)
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.set_size_request(180, 112)
            nice = os.path.basename(w).rsplit(".", 1)[0].replace("-", " ").title()
            tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            tile.append(pic)
            tile.append(label(nice if w.startswith(WALLPAPERS) else "Your photo", "row-sub", margin_start=4,
                              margin_bottom=4))
            b = Gtk.Button(child=tile, tooltip_text=nice)
            b.add_css_class("wall")
            b.add_css_class("flat")
            b.path = w
            if w == current:
                b.add_css_class("chosen")
            b.connect("clicked", lambda _b, w=w: choose(w))
            buttons.append(b)
            flow.append(b)
        box.append(flow)

        def browse():
            dlg = Gtk.FileDialog(title="Choose a photo")
            f = Gtk.FileFilter()
            f.set_name("Pictures")
            f.add_mime_type("image/*")
            filters = Gio.ListStore.new(Gtk.FileFilter)
            filters.append(f)
            dlg.set_filters(filters)

            def done(d, res):
                try:
                    file = d.open_finish(res)
                except GLib.Error:
                    return
                if file:
                    choose(file.get_path())
                    self.win.open("personalization")
            dlg.open(self.win, None, done)
        card = Card()
        card.set_margin_top(8)
        card.row("folder-pictures-symbolic", "Use your own photo", "", button("Browse photos", browse))
        box.append(card)

        text = self.group(box, "Text")
        iface = Gio.Settings.new("org.gnome.desktop.interface")
        sizes = [(1.0, "Default"), (1.1, "Larger"), (1.25, "Large"), (1.5, "Extra large")]
        cur = iface.get_double("text-scaling-factor")
        sel = min(range(len(sizes)), key=lambda i: abs(sizes[i][0] - cur))
        text.row("format-text-larger-symbolic", "Text size", "",
                 dropdown([t for _, t in sizes], sel, lambda i: iface.set_double("text-scaling-factor", sizes[i][0])))
        cursors = [(24, "Default"), (32, "Large"), (48, "Extra large")]
        cur_c = self.prefs.get("cursor_size", 24)

        def set_cursor(i):
            self.prefs["cursor_size"] = cursors[i][0]
            self.save()
            iface.set_int("cursor-size", cursors[i][0])
            write_labwc_user_config(self.prefs)
            self.win.toast("Pointer size changes fully the next time you sign in")
        text.row("input-mouse-symbolic", "Pointer size", "",
                 dropdown([t for _, t in cursors], next((i for i, (v, _) in enumerate(cursors) if v == cur_c), 0),
                          set_cursor))

        bar = self.group(box, "Taskbar")

        def setp(key, value):
            self.prefs[key] = value
            self.save()
            spawn(["wren-theme", "panel"])
        bar.row("view-dual-symbolic", "Taskbar position", "",
                dropdown(["Bottom", "Top"], 1 if self.prefs.get("panel_position") == "top" else 0,
                         lambda i: setp("panel_position", "top" if i else "bottom")))
        bar.row("preferences-system-time-symbolic", "24-hour clock", "",
                switch(bool(self.prefs.get("clock_24h")), lambda v: setp("clock_24h", v)))
        return box

    def colors(self, box):
        t = wrenlib.load_theme()
        box.append(label("Colors", "group-title"))
        modes = Gtk.Box(spacing=10)
        mode_buttons = []

        def set_theme(**kw):
            if not wtheme:
                return
            background(lambda: wtheme.set_theme(**kw))

        def pick_mode(m):
            for b in mode_buttons:
                (b.add_css_class if b.mode == m else b.remove_css_class)("chosen")
            set_theme(mode=m)
        for m, name in (("dark", "Dark"), ("light", "Light")):
            prev = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            prev.add_css_class("preview")
            prev.add_css_class(m)
            for css in ("bar", "blob", "line2"):
                part = Gtk.Box(halign=Gtk.Align.FILL if css == "bar" else Gtk.Align.START)
                part.add_css_class(css)
                prev.append(part)
            tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            tile.append(prev)
            tile.append(label(name, "mode-name"))
            b = Gtk.Button(child=tile)
            b.add_css_class("mode-tile")
            b.mode = m
            if t["mode"] == m:
                b.add_css_class("chosen")
            b.connect("clicked", lambda _b, m=m: pick_mode(m))
            mode_buttons.append(b)
            modes.append(b)
        box.append(modes)

        card = Card()
        card.set_margin_top(8)
        swatches = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        sw_buttons = []
        acc_row = None

        def pick_accent(a):
            for b in sw_buttons:
                (b.add_css_class if b.accent == a else b.remove_css_class)("chosen")
            acc_row.subtitle.set_text(wrenlib.ACCENTS[a][6])
            set_theme(accent=a)
        provider = Gtk.CssProvider()
        provider.load_from_string("".join(f".sw-{k} {{ background-color: {v[0]}; }}\n"
                                          for k, v in wrenlib.ACCENTS.items()))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        for key, val in wrenlib.ACCENTS.items():
            dot = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            dot.set_size_request(22, 22)
            dot.add_css_class(f"sw-{key}")
            b = Gtk.Button(child=dot, tooltip_text=val[6], valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
            b.set_size_request(32, 32)
            b.add_css_class("swatch")
            b.add_css_class("flat")
            b.accent = key
            if key == t["accent"]:
                b.add_css_class("chosen")
            b.connect("clicked", lambda _b, k=key: pick_accent(k))
            sw_buttons.append(b)
            swatches.append(b)
        acc_row = card.row("applications-graphics-symbolic", "Accent color", wrenlib.ACCENTS[t["accent"]][6], swatches)
        card.row("view-reveal-symbolic", "Animations", "",
                 switch(bool(t["animations"]), lambda v: set_theme(animations=v)))
        box.append(card)

    # -------------------------------------------------------- Apps
    def apps(self):
        box = self.page("Apps")
        card = self.group(box, "Default apps")
        kinds = [
            ("web-browser-symbolic", "Web browser", ["x-scheme-handler/http", "x-scheme-handler/https", "text/html"]),
            ("video-x-generic-symbolic", "Videos", ["video/mp4", "video/x-matroska", "video/webm", "video/quicktime"]),
            ("audio-x-generic-symbolic", "Music", ["audio/mpeg", "audio/flac", "audio/ogg", "audio/mp4"]),
            ("image-x-generic-symbolic", "Photos", ["image/png", "image/jpeg", "image/webp", "image/gif"]),
            ("x-office-document-symbolic", "PDF documents", ["application/pdf"]),
            ("text-x-generic-symbolic", "Text files", ["text/plain"]),
        ]
        for icon, title, mimes in kinds:
            apps = [a for a in Gio.AppInfo.get_all_for_type(mimes[0]) if a.should_show()]
            if not apps:
                card.row(icon, title, "No app installed for this")
                continue
            default = Gio.AppInfo.get_default_for_type(mimes[0], False)
            sel = next((i for i, a in enumerate(apps) if default and a.get_id() == default.get_id()), 0)

            def set_default(i, apps=apps, mimes=mimes, title=title):
                for m in mimes:
                    try:
                        apps[i].set_as_default_for_type(m)
                    except GLib.Error:
                        pass
                self.win.toast(f"{apps[i].get_display_name()} is now the default for {title.lower()}")
            card.row(icon, title, "", dropdown([a.get_display_name() for a in apps], sel, set_default))

        self.background_row(self.group(box, "Background apps"))
        store = self.group(box, "Get more apps")
        store.row("system-software-install-symbolic", "App Store", "",
                  on_click=lambda: spawn(["wren-store"]))
        installed = self.group(box, "Installed apps")
        apps = sorted([a for a in Gio.AppInfo.get_all() if a.should_show()], key=lambda a: a.get_display_name().lower())
        for a in apps:
            app_id = (a.get_id() or "").removesuffix(".desktop")
            is_flatpak = "flatpak" in (getattr(a, "get_filename", lambda: "")() or "")
            ctl = button("Uninstall", lambda app_id=app_id, a=a: self.uninstall(app_id, a.get_display_name())) \
                if is_flatpak else label("Part of Floe", "row-sub")
            img = a.get_icon()
            row = installed.row(None, a.get_display_name(), (a.get_description() or "")[:80], ctl)
            icon = Gtk.Image.new_from_gicon(img) if img else Gtk.Image.new_from_icon_name("application-x-executable")
            icon.set_pixel_size(28)
            row.prepend(icon)
        return box

    def background_row(self, card):
        def setb(v):
            self.prefs["background_apps"] = v
            self.save()
        card.row("view-app-grid-symbolic", "Let apps run in the background",
                 "When off, closed apps stop after about two minutes",
                 switch(bool(self.prefs.get("background_apps", False)), setb))

    def uninstall(self, app_id, name):
        d = Adw.AlertDialog(heading=f"Uninstall {name}?", body="You can get it again from the App Store.")
        d.add_response("cancel", "Cancel")
        d.add_response("go", "Uninstall")
        d.set_response_appearance("go", Adw.ResponseAppearance.DESTRUCTIVE)

        def go():
            background(lambda: ok(["flatpak", "uninstall", "--user", "-y", "--noninteractive", app_id], 300),
                       lambda r: (self.win.toast(f"Uninstalled {name}" if r else f"Couldn't uninstall {name}"),
                                  self.win.open("apps")))
        d.connect("response", lambda _d, r: r == "go" and go())
        d.present(self.win)

    # -------------------------------------------------------- Accounts
    def accounts(self):
        box = self.page("Accounts")
        me = pwd.getpwuid(os.getuid())
        full = (me.pw_gecos or "").split(",")[0] or me.pw_name
        card = Card()
        head = Gtk.Box(spacing=16)
        head.add_css_class("row")
        av = label(full[:1].upper(), "me-avatar", xalign=0.5)
        head.append(av)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        info.append(label(full, "me-name"))
        info.append(label(f"{me.pw_name}, administrator", "me-sub"))
        head.append(info)
        card.append(head)
        box.append(card)
        sign = self.group(box, "Sign-in options")
        sign.row("dialog-password-symbolic", "Change password", "",
                 on_click=lambda: spawn(["wren-terminal", "-e", "sh", "-c",
                                         "passwd; echo; echo 'You can close this window.'; read _"]))
        self.passkeys(box)
        return box

    # Floe Passkeys: the built-in passkey authenticator
    def passkeys(self, box):
        try:
            import passkeys as pk
        except Exception:
            return
        off_flag = os.path.join(os.path.expanduser("~"), ".config", "wren", "passkeys-off")
        card = self.group(box, "Passkeys")

        def set_on(on):
            # The passkey service checks this before every request
            if on:
                try:
                    os.remove(off_flag)
                except OSError:
                    pass
            else:
                os.makedirs(os.path.dirname(off_flag), exist_ok=True)
                open(off_flag, "w").close()
        card.row("dialog-password-symbolic", "Floe Passkeys", "Sign in to websites and apps with a passkey",
                 switch(not os.path.exists(off_flag), set_on))

        pin_slot = Gtk.Box(valign=Gtk.Align.CENTER)

        def change_pin():
            dlg = Adw.AlertDialog(heading="Change passkey PIN" if pk.has_pin() else "Set a passkey PIN")
            form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            old = Gtk.PasswordEntry(placeholder_text="Current PIN", show_peek_icon=True, visible=pk.has_pin())
            new1 = Gtk.PasswordEntry(placeholder_text="New PIN (at least 4 characters)", show_peek_icon=True)
            new2 = Gtk.PasswordEntry(placeholder_text="New PIN again", show_peek_icon=True)
            for w in (old, new1, new2):
                form.append(w)
            dlg.set_extra_child(form)
            dlg.add_response("cancel", "Cancel")
            dlg.add_response("save", "Save PIN")
            dlg.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

            def done(_d, resp):
                if resp != "save":
                    return
                if len(new1.get_text()) < 4 or new1.get_text() != new2.get_text():
                    self.win.toast("The new PINs must match and be at least 4 characters")
                    return
                background(lambda: pk.set_pin(new1.get_text(), old.get_text() or None),
                           lambda r: self.win.toast("Passkey PIN saved" if r else "The current PIN isn't right"))
            dlg.connect("response", done)
            dlg.present(self.win)
        pin_slot.append(button("Change" if pk.has_pin() else "Set PIN", change_pin))
        card.row("system-lock-screen-symbolic", "Passkey PIN", "Asked for every time you use a passkey", pin_slot)

        saved = self.group(box, "Saved passkeys")
        items = pk.list_passkeys()
        if not items:
            saved.row("dialog-information-symbolic", "No passkeys yet",
                      "When a site offers to create a passkey, Floe saves it here")
        for item in items:
            def remove(item=item):
                dlg = Adw.AlertDialog(heading=f"Delete the passkey for {item['site']}?",
                                      body="You won't be able to sign in with it any more. Make sure you have "
                                           "another way to sign in to this account first.")
                dlg.add_response("cancel", "Cancel")
                dlg.add_response("delete", "Delete")
                dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

                def done(_d, resp):
                    if resp == "delete" and pk.delete_passkey(item["id"]):
                        self.win.toast("Passkey deleted")
                        self.win.open("accounts")
                dlg.connect("response", done)
                dlg.present(self.win)
            when = GLib.DateTime.new_from_unix_local(item["created"]).format("%B %-d, %Y") if item["created"] else ""
            saved.row("web-browser-symbolic", item["site"],
                      ", ".join(x for x in (item["user"] or item["display"], f"saved {when}" if when else "") if x),
                      button("Delete", remove))
        box.append(label("Your passkeys are kept on this computer and locked with your passkey PIN. When a site "
                         "asks you to sign in with a passkey or a security key, Floe asks for your PIN and signs "
                         "you in. In Chrome, choose \u201cUse a different device\u201d, then \u201cUSB security key\u201d.",
                         "row-sub", wrap=True, margin_top=8, margin_start=2, max_width_chars=80))

    # -------------------------------------------------------- Time & language
    def time(self):
        box = self.page("Time & language")
        card = self.group(box, "Date & time")
        now = GLib.DateTime.new_now_local()
        card.row("preferences-system-time-symbolic", now.format("%-I:%M %p"), now.format("%A, %B %-d, %Y"))
        ntp = "NTP=yes" in run(["timedatectl", "show", "-p", "NTP"])
        card.row(None, "Set time automatically", "",
                 switch(ntp, lambda on: background(lambda: ok(["timedatectl", "set-ntp", "true" if on else "false"]))))
        zones = run(["timedatectl", "list-timezones"]).splitlines() or ["UTC"]
        cur = run(["timedatectl", "show", "-p", "Timezone", "--value"]) or "UTC"
        model = Gtk.StringList()
        for z in zones:
            model.append(z.replace("_", " "))
        dd = Gtk.DropDown(model=model, enable_search=True, valign=Gtk.Align.CENTER)
        dd.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        if cur in zones:
            dd.set_selected(zones.index(cur))
        dd.connect("notify::selected", lambda d, _p: background(
            lambda: ok(["timedatectl", "set-timezone", zones[d.get_selected()]]),
            lambda r: self.win.toast("Time zone changed" if r else "Couldn't change the time zone")))
        card.row("mark-location-symbolic", "Time zone", "", dd)

        kb = self.group(box, "Keyboard")
        layouts = [("English (US)", "us"), ("English (UK)", "gb"), ("Spanish", "es"), ("Latin American", "latam"),
                   ("French", "fr"), ("German", "de"), ("Italian", "it"), ("Portuguese (Brazil)", "br"),
                   ("Portuguese", "pt"), ("Dutch", "nl"), ("Swedish", "se"), ("Norwegian", "no"), ("Danish", "dk"),
                   ("Finnish", "fi"), ("Polish", "pl"), ("Turkish", "tr"), ("Russian", "ru")]
        cur_kb = self.prefs.get("keyboard") or os.environ.get("XKB_DEFAULT_LAYOUT", "us")
        sel = next((i for i, (_, c) in enumerate(layouts) if c == cur_kb), 0)

        def set_kb(i):
            self.prefs["keyboard"] = layouts[i][1]
            self.save()
            write_labwc_user_config(self.prefs)
            self.win.toast(f"Keyboard set to {layouts[i][0]}")
        kb.row("input-keyboard-symbolic", "Keyboard layout", "", dropdown([n for n, _ in layouts], sel, set_kb))

        def key_scale(key, lo, hi, default, step):
            s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
            s.set_value(self.prefs.get(key, default))
            s.set_size_request(220, -1)
            s.set_draw_value(False)
            pending = {"src": None}

            def changed(w):
                self.prefs[key] = int(w.get_value())
                if pending["src"]:
                    GLib.source_remove(pending["src"])

                def commit():
                    pending["src"] = None
                    self.save()
                    write_labwc_user_config(self.prefs)
                    return False
                pending["src"] = GLib.timeout_add(400, commit)
            s.connect("value-changed", changed)
            return s
        kb.row(None, "Repeat delay", "", key_scale("repeat_delay", 200, 1000, 600, 50))
        kb.row(None, "Repeat speed", "", key_scale("repeat_rate", 10, 60, 25, 1))
        return box

    # -------------------------------------------------------- Update
    def update(self):
        box = self.page("Floe Update")
        card = Card()
        status = card.row("software-update-available-symbolic", "Checking for updates…", f"You have build {wren_build()}",
                          button("Open Software Update", lambda: spawn(["wren-updater"]), primary=True))
        box.append(card)

        def done(result):
            title = status.get_first_child().get_next_sibling().get_first_child()
            result = result or ""
            if result.startswith("available"):
                title.set_text(f"An update is ready: {result.split()[1].replace('build-', 'build ')}")
            elif result.startswith("current"):
                title.set_text("You're up to date")
            else:
                title.set_text("Couldn't check for updates. Are you online?")
        background(lambda: run(["wren-update", "--check"], 30), done)
        more = self.group(box, "More")
        more.row("system-software-install-symbolic", "App updates", "Update apps from the App Store",
                 on_click=lambda: spawn(["wren-store"]))
        return box


# ------------------------------------------------------------------ system info
def wren_build():
    try:
        for line in open("/etc/wren-release"):
            if line.startswith("WREN_BUILD="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return "unknown"


def cpu_name():
    try:
        for line in open("/proc/cpuinfo"):
            if line.startswith("model name"):
                return re.sub(r"\s+", " ", line.split(":", 1)[1]).strip()
    except OSError:
        pass
    return platform.processor() or "Unknown"


def mem_total():
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal"):
                return f"{int(line.split()[1]) / 1024 / 1024:.1f} GB"
    except OSError:
        pass
    return "Unknown"


def gpu_name():
    names = []
    for card in sorted(glob.glob("/sys/class/drm/card[0-9]")):
        drv = os.path.realpath(f"{card}/device/driver")
        if os.path.exists(drv):
            names.append(os.path.basename(drv))
    friendly = {"i915": "Intel graphics", "xe": "Intel graphics", "amdgpu": "AMD Radeon graphics",
                "radeon": "AMD Radeon graphics (older)", "nouveau": "NVIDIA graphics (open driver)",
                "nvidia": "NVIDIA graphics", "vmwgfx": "VMware virtual graphics", "virtio_gpu": "Virtual graphics",
                "virtio-pci": "Virtual graphics", "bochs-drm": "Virtual graphics", "qxl": "Virtual graphics",
                "vboxvideo": "VirtualBox graphics", "simple-framebuffer": "Basic display"}
    return ", ".join(dict.fromkeys(friendly.get(n, n) for n in names)) or "Unknown"


# ------------------------------------------------------------------ window
class Window(Adw.ApplicationWindow):
    def __init__(self, app, start="system"):
        super().__init__(application=app, title="Settings", default_width=1040, default_height=720)
        self.add_css_class("settings")
        self.pages = Pages(self)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=260)
        side.add_css_class("nav")
        me = pwd.getpwuid(os.getuid())
        full = (me.pw_gecos or "").split(",")[0] or me.pw_name
        card = Gtk.Box(spacing=12)
        card.add_css_class("me")
        card.append(label(full[:1].upper(), "me-avatar", xalign=0.5))
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        info.append(label(full, "me-name"))
        info.append(label("Live session" if LIVE else "Local account", "me-sub"))
        card.append(info)
        side.append(card)
        self.search = Gtk.SearchEntry(placeholder_text="Find a setting", margin_start=12, margin_end=12, margin_bottom=8)
        self.search.connect("search-changed", self.on_search)
        side.append(self.search)
        self.nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav.add_css_class("nav")
        self.rows = {}
        for key, title, icon in Pages.nav:
            row = Gtk.ListBoxRow()
            b = Gtk.Box(spacing=12)
            b.append(Gtk.Image.new_from_icon_name(icon))
            b.append(label(title))
            row.set_child(b)
            row.key = key
            row.title = title
            self.rows[key] = row
            self.nav.append(row)
        self.nav.connect("row-activated", lambda _l, r: self.open(r.key))
        side.append(self.nav)

        self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True, vexpand=True)
        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(self.scroll)
        body = Gtk.Box()
        body.append(side)
        body.append(self.toasts)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar(show_title=False))
        view.set_content(body)
        self.set_content(view)
        self.open(start)

    KEYWORDS = {
        "display": "screen monitor brightness resolution scale", "sound": "audio volume speaker microphone headphones",
        "notifications": "do not disturb dnd", "power": "battery sleep lock screen idle",
        "storage": "disk space trash", "about": "device name hostname specs ram cpu",
        "devices": "bluetooth mouse touchpad trackpad scroll pointer", "network": "wifi wi-fi internet airplane ip",
        "personalization": "background wallpaper text size font", "apps": "default browser uninstall",
        "accounts": "password user passkey passkeys security key sign in login pin", "time": "date clock timezone keyboard layout language",
        "update": "software upgrade",
    }

    def on_search(self, entry):
        q = entry.get_text().strip().lower()
        if not q:
            return
        for key, words in self.KEYWORDS.items():
            title = dict((k, t) for k, t, _ in Pages.nav).get(key, key)
            if q in key or q in words or q in title.lower():
                self.open(key)
                return

    def open(self, key):
        parent = {"display": "system", "sound": "system", "notifications": "system", "power": "system",
                  "storage": "system", "about": "system"}.get(key, key)
        if parent in self.rows:
            self.nav.select_row(self.rows[parent])
        builder = getattr(self.pages, key, None)
        if builder is None or key == "nav":
            builder = self.pages.system
        clamp = Adw.Clamp(maximum_size=860, margin_top=28, margin_bottom=40, margin_start=32, margin_end=32)
        page = builder()
        clamp.set_child(page)
        self.scroll.set_child(clamp)
        # Page content glides up into place, section by section
        wrenlib.stagger(list(wrenlib.children(page)), step=16, cap=10)

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.wrenlinux.Settings", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.restyle = wrenlib.setup_app_style(CSS)
        wrenlib.keep_warm(self)
        action = Gio.SimpleAction.new("open-page", GLib.VariantType.new("s"))
        action.connect("activate", lambda _a, param: self.show_page(param.get_string()))
        self.add_action(action)

    def show_page(self, page="system"):
        win = self.get_active_window()
        if win:
            win.open(page)
        else:
            win = Window(self, page)
        win.present()

    def do_activate(self):
        win = self.get_active_window()
        if win:
            win.present()
        else:
            self.show_page("system")

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        self.show_page(args[0] if args else "system")
        return 0


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
