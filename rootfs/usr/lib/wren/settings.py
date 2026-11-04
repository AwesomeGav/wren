#!/usr/bin/env python3
"""Wren Settings: one place for display, sound, network, Bluetooth, mouse and
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

CONF = os.path.join(GLib.get_user_config_dir(), "wren")
ENV_FILE = os.path.join(CONF, "settings.env")
PREFS_FILE = os.path.join(CONF, "settings.json")
LABWC_DIR = os.path.join(GLib.get_user_config_dir(), "labwc")
WALLPAPERS = "/usr/share/wren/wallpapers"
LIVE = os.path.isdir("/run/archiso")

CSS = """
.settings { background-color: #181512; }
.nav { background-color: #141210; border-right: 1px solid #2E2924; }
.nav row { padding: 9px 14px; border-left: 3px solid transparent; color: #BDB4A9; }
.nav row:hover { background-color: rgba(255, 240, 225, 0.05); color: #F1EBE3; }
.nav row:selected { background-color: rgba(224, 137, 74, 0.13); border-left-color: #E0894A; color: #F1EBE3; }
.nav row:selected image { color: #F0A06A; }
.me { padding: 18px 16px 14px 16px; }
.me-avatar { background: #E0894A; color: #1A120B; font-weight: 800; font-size: 20px; min-width: 48px; min-height: 48px; }
.me-name { font-weight: 800; font-size: 15px; }
.me-sub { color: #8A8178; font-size: 12px; }
.page-title { font-size: 28px; font-weight: 800; }
.crumb { color: #8A8178; font-size: 13px; }
.group-title { font-size: 11px; font-weight: 800; letter-spacing: 0.12em; color: #8A8178; margin: 14px 0 4px 2px; }
.card { background-color: #1F1B18; border: 1px solid #2A2520; }
.card + .card { margin-top: 4px; }
.row { padding: 14px 18px; min-height: 36px; }
.row + .row { border-top: 1px solid #2A2520; }
.row.link:hover { background-color: #26221E; }
.row-icon { color: #D9D1C7; min-width: 36px; }
.row-title { font-weight: 600; }
.row-sub { color: #A89F94; font-size: 12px; }
.big-stat { font-size: 30px; font-weight: 800; }
.btn { padding: 6px 14px; font-weight: 700; }
.btn.primary { background-color: #E0894A; color: #1A120B; }
.btn.primary:hover { background-color: #EC9A5E; }
.wall { border: 2px solid transparent; padding: 0; }
.wall.chosen { border-color: #E0894A; }
.tile-grid > flowboxchild { padding: 0; }
levelbar trough { min-height: 10px; background-color: #2A2520; }
levelbar block.filled { background-color: #E0894A; }
levelbar block.empty { background-color: #2A2520; }
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
        "WREN_WALLPAPER": prefs.get("wallpaper", f"{WALLPAPERS}/topographic.jpg"),
        "WREN_LOCK_AFTER": str(prefs.get("lock_after", 600)),
        "WREN_SLEEP_AFTER": str(prefs.get("sleep_after", 0)),
    }
    with open(ENV_FILE, "w") as f:
        for k, v in env.items():
            f.write(f"{k}={GLib.shell_quote(v)}\n")


def write_labwc_user_config(prefs):
    """User rc.xml merged on top of Wren's (labwc -m): mouse, touchpad, keyboard."""
    os.makedirs(LABWC_DIR, exist_ok=True)
    yn = lambda b: "yes" if b else "no"  # noqa: E731
    rc = f"""<?xml version="1.0"?>
<!-- Written by Wren Settings. Merged on top of /etc/xdg/labwc/rc.xml. -->
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
</labwc_config>
"""
    with open(os.path.join(LABWC_DIR, "rc.xml"), "w") as f:
        f.write(rc)
    layout = prefs.get("keyboard")
    env_path = os.path.join(LABWC_DIR, "environment")
    if layout:
        with open(env_path, "w") as f:
            f.write(f"XKB_DEFAULT_LAYOUT={escape(layout)}\n")
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


class Card(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("card")

    def row(self, icon, title, subtitle="", control=None, on_click=None):
        box = Gtk.Box(spacing=14)
        box.add_css_class("row")
        if icon:
            img = Gtk.Image.new_from_icon_name(icon)
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
        ("update", "Wren Update", "software-update-available-symbolic"),
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
        box.append(label(title.upper(), "group-title"))
        card = Card()
        box.append(card)
        return card

    # -------------------------------------------------------- System
    def system(self):
        box = self.page("System")
        host = socket.gethostname()
        head = Card()
        r = head.row("computer-symbolic", host, f"Wren Linux · build {wren_build()}",
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
            card = self.group(box, f"{out.get('make', '')} {out.get('model', '') or name}".strip())
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
            card.row("zoom-in-symbolic", "Scale", "Makes text and apps bigger", scale_dd)

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
                        f.write("#!/bin/sh\n# Written by Wren Settings\n" + "\n".join(lines) + "\n")
                    os.chmod(path, 0o755)
                    self.win.toast("Display settings applied")
                else:
                    self.win.toast("That display setting didn't work")
            card.row(None, "Apply changes", "", button("Apply", apply, primary=True))
        if not outputs:
            box.append(label("Display details aren't available right now.", "row-sub", margin_top=8))
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
        card.row("system-lock-screen-symbolic", "Lock the screen after", "When you're not using the computer",
                 dropdown([t for _, t in lock_opts], pick(lock_opts, "lock_after", 600),
                          lambda i: set_opt("lock_after", lock_opts, i)))
        card.row("weather-clear-night-symbolic", "Put the computer to sleep after", "Saves battery and power",
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
        for title, value in (("Wren Linux", f"Build {wren_build()}"),
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
            card.row("bluetooth-active-symbolic", "Bluetooth", "Turn on to connect wireless devices",
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
        mouse.row(None, "Natural scrolling", "Content moves the same way as your fingers",
                  switch(self.prefs.get("mouse_natural", False), lambda v: setp("mouse_natural", v)))
        mouse.row(None, "Swap left and right buttons", "For left-handed use",
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
        box.append(label("BACKGROUND", "group-title"))
        current = self.prefs.get("wallpaper", f"{WALLPAPERS}/topographic.jpg")
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, min_children_per_line=2,
                           row_spacing=8, column_spacing=8, homogeneous=True)
        flow.add_css_class("tile-grid")
        buttons = []

        def choose(path):
            self.prefs["wallpaper"] = path
            self.save()
            spawn(["wren-wallpaper"])
            for b in buttons:
                (b.add_css_class if b.path == path else b.remove_css_class)("chosen")

        walls = sorted(glob.glob(f"{WALLPAPERS}/*.jpg"))
        walls = [w for w in walls if not w.endswith("-thumb.jpg")]
        if current not in walls and os.path.exists(current):
            walls.append(current)
        for w in walls:
            thumb = w.replace(".jpg", "-thumb.jpg")
            pic = Gtk.Picture.new_for_filename(thumb if os.path.exists(thumb) else w)
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.set_size_request(180, 112)
            b = Gtk.Button(child=pic, tooltip_text=os.path.basename(w).rsplit(".", 1)[0].replace("-", " ").title())
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
        text.row("format-text-larger-symbolic", "Text size", "Applies to apps",
                 dropdown([t for _, t in sizes], sel, lambda i: iface.set_double("text-scaling-factor", sizes[i][0])))
        return box

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

        store = self.group(box, "Get more apps")
        store.row("system-software-install-symbolic", "App Store", "Install, update and remove apps",
                  on_click=lambda: spawn(["wren-store"]))
        installed = self.group(box, "Installed apps")
        apps = sorted([a for a in Gio.AppInfo.get_all() if a.should_show()], key=lambda a: a.get_display_name().lower())
        for a in apps:
            app_id = (a.get_id() or "").removesuffix(".desktop")
            is_flatpak = isinstance(a, Gio.DesktopAppInfo) and "flatpak" in (a.get_filename() or "")
            ctl = button("Uninstall", lambda app_id=app_id, a=a: self.uninstall(app_id, a.get_display_name())) \
                if is_flatpak else label("Part of Wren", "row-sub")
            img = a.get_icon()
            row = installed.row(None, a.get_display_name(), (a.get_description() or "")[:80], ctl)
            icon = Gtk.Image.new_from_gicon(img) if img else Gtk.Image.new_from_icon_name("application-x-executable")
            icon.set_pixel_size(28)
            row.prepend(icon)
        return box

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
        info.append(label(f"{me.pw_name} · Administrator", "me-sub"))
        head.append(info)
        card.append(head)
        box.append(card)
        sign = self.group(box, "Sign-in options")
        sign.row("dialog-password-symbolic", "Change your password", "You'll type your current password, then the new one",
                 on_click=lambda: spawn(["wren-terminal", "-e", "sh", "-c",
                                         "passwd; echo; echo 'You can close this window.'; read _"]))
        return box

    # -------------------------------------------------------- Time & language
    def time(self):
        box = self.page("Time & language")
        card = self.group(box, "Date & time")
        now = GLib.DateTime.new_now_local()
        card.row("preferences-system-time-symbolic", now.format("%-I:%M %p"), now.format("%A, %B %-d, %Y"))
        ntp = "NTP=yes" in run(["timedatectl", "show", "-p", "NTP"])
        card.row(None, "Set time automatically", "Uses the internet to keep the clock right",
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
        return box

    # -------------------------------------------------------- Update
    def update(self):
        box = self.page("Wren Update")
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
        "accounts": "password user", "time": "date clock timezone keyboard layout language",
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
        clamp.set_child(builder())
        self.scroll.set_child(clamp)

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.wrenlinux.Settings", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        page = args[0] if args else "system"
        win = self.get_active_window()
        if win:
            win.open(page)
        else:
            win = Window(self, page)
        win.present()
        return 0


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
