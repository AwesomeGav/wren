#!/usr/bin/env python3
"""Floe Installer: a guided, point-and-click installer for Floe."""
import json
import os
import re
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

sys.path.insert(0, "/usr/lib/wren")
import wrenlib  # noqa: E402

BACKEND = "/usr/lib/wren/install-backend.sh"
LOGO = "/usr/share/wren/logo-256.png"
MIN_DISK = 12 * 1000**3

LANGUAGES = [
    ("English (United States)", "en_US.UTF-8"), ("English (United Kingdom)", "en_GB.UTF-8"),
    ("Español (España)", "es_ES.UTF-8"), ("Español (México)", "es_MX.UTF-8"),
    ("Français", "fr_FR.UTF-8"), ("Deutsch", "de_DE.UTF-8"), ("Italiano", "it_IT.UTF-8"),
    ("Português (Brasil)", "pt_BR.UTF-8"), ("Português (Portugal)", "pt_PT.UTF-8"),
    ("Nederlands", "nl_NL.UTF-8"), ("Svenska", "sv_SE.UTF-8"), ("Polski", "pl_PL.UTF-8"),
    ("Türkçe", "tr_TR.UTF-8"), ("Русский", "ru_RU.UTF-8"),
]
KEYBOARDS = [
    ("English (US)", "us", "us"), ("English (UK)", "gb", "uk"),
    ("Spanish", "es", "es"), ("Latin American", "latam", "la-latin1"),
    ("French", "fr", "fr"), ("German", "de", "de"), ("Italian", "it", "it"),
    ("Portuguese (Brazil)", "br", "br-abnt2"), ("Portuguese", "pt", "pt-latin1"),
    ("Dutch", "nl", "nl"), ("Swedish", "se", "sv-latin1"), ("Norwegian", "no", "no"),
    ("Danish", "dk", "dk"), ("Finnish", "fi", "fi"), ("Polish", "pl", "pl"),
    ("Turkish", "tr", "trq"), ("Russian", "ru", "ru"),
]
RESERVED_USERS = {"root", "bin", "daemon", "mail", "ftp", "http", "nobody", "dbus", "greeter",
                  "systemd-network", "systemd-resolve", "polkitd", "rtkit", "git", "admin"}

CSS = """
.hero-title { font-size: 32px; font-weight: 600; letter-spacing: -0.01em; }
.hero-body { font-size: 15px; color: alpha(currentColor, 0.72); }
.page-title { font-size: 26px; font-weight: 600; letter-spacing: -0.01em; }
.page-body { color: alpha(currentColor, 0.7); }
.footer { padding: 14px 18px; border-top: 1px solid alpha(currentColor, 0.07); }
.big-button { padding: 10px 26px; border-radius: 10px; font-weight: 600; }
.warn { color: #B45309; }
.error-text { color: #DC2626; }
.steps label { font-size: 12px; color: alpha(currentColor, 0.45); }
.steps label.current { color: @wren_accent_text; font-weight: 700; }
.steps label.done { color: alpha(currentColor, 0.75); }
progressbar trough { min-height: 10px; border-radius: 999px; }
progressbar progress { min-height: 10px; border-radius: 999px; }
.log { font-family: monospace; font-size: 11px; }
"""


def run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def restart_now():
    """Reboot right away. A normal shutdown can hang on the live USB (it runs from
    the stick), and the new system is already safely written and unmounted."""
    os.sync()
    cmd = ["/usr/lib/wren/live-power", "reboot"]
    if os.geteuid() != 0:
        cmd = ["sudo", "-n"] + cmd
    try:
        subprocess.Popen(cmd)
    except OSError:
        subprocess.Popen(["systemctl", "reboot"])


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB", "MB") else f"{n:.1f} {unit}"
        n /= 1000


def list_disks():
    live = ""
    src = run(["findmnt", "-no", "SOURCE", "/run/archiso/bootmnt"])
    if src:
        live = run(["lsblk", "-no", "PKNAME", src]).splitlines()[0:1]
        live = live[0] if live else ""
    try:
        data = json.loads(run(["lsblk", "-J", "-b", "-d", "-o", "NAME,PATH,SIZE,MODEL,TYPE,TRAN,RO"]))
    except json.JSONDecodeError:
        return []
    disks = []
    for d in data.get("blockdevices", []):
        if d.get("type") != "disk" or d.get("ro") in (True, "1", 1) or d["name"] == live:
            continue
        if d["name"].startswith(("zram", "loop", "sr")):
            continue
        size = int(d.get("size") or 0)
        disks.append({"path": d["path"], "name": d["name"], "size": size,
                      "model": (d.get("model") or "").strip() or "Disk",
                      "tran": (d.get("tran") or "").upper(), "big_enough": size >= MIN_DISK})
    return disks


ESP_TYPES = {"c12a7328-f81f-11d2-ba4b-00a0c93ec93b", "0xef"}
SKIP_TYPES = ESP_TYPES | {
    "e3c9e316-0b5c-4db8-817d-f92df00215ae",  # Microsoft reserved
    "de94bba4-06d1-4d40-a16a-bfd50179d6ac",  # Windows recovery
    "21686148-6449-6e6f-744e-656564454649",  # BIOS boot
    "0x5", "0xf", "0x85", "0x27",            # extended / hidden recovery
}
MIB = 1024 * 1024


def disk_layout(path, data=None):
    """Partitions, usable free space and what's on a disk, read with lsblk (no root needed)."""
    if data is None:
        try:
            data = json.loads(run(["lsblk", "-J", "-b", "-o",
                                   "NAME,PATH,SIZE,START,TYPE,FSTYPE,LABEL,PARTTYPE,PARTTYPENAME,PTTYPE,"
                                   "MOUNTPOINTS,PARTN", path]))
        except json.JSONDecodeError:
            data = {}
    devs = data.get("blockdevices") or [{}]
    dev = devs[0]
    size = int(dev.get("size") or 0)
    pttype = (dev.get("pttype") or "").lower()
    parts = []
    for c in dev.get("children") or []:
        if c.get("type") != "part":
            continue
        ptype = (c.get("parttype") or "").lower()
        parts.append({
            "path": c.get("path"), "start": int(c.get("start") or 0) * 512, "size": int(c.get("size") or 0),
            "fstype": (c.get("fstype") or "").lower(), "label": c.get("label") or "", "ptype": ptype,
            "typename": c.get("parttypename") or "", "number": int(c.get("partn") or 0),
            "mounted": any(m for m in (c.get("mountpoints") or []) if m),
            "esp": ptype in ESP_TYPES,
        })
    parts.sort(key=lambda p: p["start"])
    # Free space between and after partitions (1 MiB aligned, room left for the GPT backup)
    gaps, cursor = [], MIB
    end = size - (MIB if pttype == "gpt" else 0)
    for p in parts:
        if p["number"] > 4 and pttype == "dos":
            continue  # logical partitions sit inside the extended one
        if p["start"] > cursor:
            gaps.append((cursor, p["start"] - cursor))
        cursor = max(cursor, p["start"] + p["size"])
    if end > cursor:
        gaps.append((cursor, end - cursor))
    free = []
    for start, length in gaps:
        a = (start + MIB - 1) // MIB * MIB
        length -= a - start
        if length >= MIN_DISK:
            free.append({"start": a, "size": length})
    free.sort(key=lambda g: -g["size"])
    primaries = len([p for p in parts if 0 < p["number"] <= 4]) if pttype == "dos" else 0
    windows = any(p["fstype"] == "ntfs" or "microsoft" in p["typename"].lower() for p in parts)
    others = [p for p in parts if not p["esp"] and p["ptype"] not in SKIP_TYPES]
    uefi = os.path.isdir("/sys/firmware/efi")
    has_esp = any(p["esp"] for p in parts)
    has_biosboot = any(p["ptype"] == "21686148-6449-6e6f-744e-656564454649" for p in parts)

    blocker = None
    if not parts or pttype not in ("gpt", "dos"):
        blocker = "This disk is empty, so there's nothing to keep."
    elif uefi and not has_esp:
        blocker = "This disk has no EFI boot partition, so Floe can't start alongside what's on it."
    elif not uefi and pttype == "gpt" and not has_biosboot:
        blocker = "This older computer can't start Floe from this disk alongside another system."

    can_free = bool(free) and not blocker and not (pttype == "dos" and primaries >= 4)
    replaceable = [p for p in others if not p["mounted"] and p["size"] >= MIN_DISK] if not blocker else []
    return {"size": size, "pttype": pttype, "parts": parts, "free": free, "windows": windows,
            "has_data": bool(others), "can_free": can_free, "replaceable": replaceable,
            "blocker": blocker, "full_primaries": pttype == "dos" and primaries >= 4}


def describe_part(p):
    kind = {"ntfs": "Windows (NTFS)", "ext4": "Linux (ext4)", "btrfs": "Linux (btrfs)", "vfat": "FAT32",
            "exfat": "exFAT"}.get(p["fstype"], p["fstype"].upper() or "Unknown")
    name = f" “{p['label']}”" if p["label"] else ""
    return f"{p['path'].split('/')[-1]}{name} · {kind} · {human_size(p['size'])}"


def string_list(items):
    model = Gtk.StringList()
    for item in items:
        model.append(item)
    return model


def make_label(text, css="", **kw):
    lbl = Gtk.Label(label=text, wrap=True, **kw)
    for c in css.split():
        lbl.add_css_class(c)
    return lbl


class Page:
    """One step of the wizard."""
    title = ""
    step = None

    def __init__(self, win):
        self.win = win
        self.widget = None

    def can_continue(self):
        return True

    def on_show(self):
        pass


def page_shell(title, body):
    """Standard page layout: big title, intro text, then content in a clamp."""
    outer = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
    clamp = Adw.Clamp(maximum_size=560, margin_top=36, margin_bottom=24, margin_start=24, margin_end=24)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
    head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    head.append(make_label(title, "page-title", xalign=0))
    if body:
        head.append(make_label(body, "page-body", xalign=0))
    box.append(head)
    clamp.set_child(box)
    outer.set_child(clamp)
    return outer, box


class WelcomePage(Page):
    def __init__(self, win):
        super().__init__(win)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                      valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER, vexpand=True)
        logo = Gtk.Image.new_from_file(LOGO)
        logo.set_pixel_size(120)
        box.append(logo)
        box.append(make_label("Welcome to Floe", "hero-title", justify=Gtk.Justification.CENTER))
        box.append(make_label("A calm, fast desktop that runs well on any computer.\n"
                              "Take a look around first, or install it now. It only takes a few minutes.",
                              "hero-body", justify=Gtk.Justification.CENTER, max_width_chars=48))
        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER, margin_top=18)
        try_btn = Gtk.Button(label="Keep Exploring")
        try_btn.add_css_class("big-button")
        try_btn.connect("clicked", lambda *_: win.close())
        install_btn = Gtk.Button(label="Install Floe")
        install_btn.add_css_class("big-button")
        install_btn.add_css_class("suggested-action")
        install_btn.connect("clicked", lambda *_: win.go(1))
        buttons.append(try_btn)
        buttons.append(install_btn)
        box.append(buttons)
        self.widget = box


class LanguagePage(Page):
    title = "Language"
    step = "Language"

    def __init__(self, win):
        super().__init__(win)
        self.widget, box = page_shell("Language & keyboard",
                                      "Choose the language for menus and apps, and your keyboard layout.")
        group = Adw.PreferencesGroup()
        self.lang = Adw.ComboRow(title="Language", model=string_list([l[0] for l in LANGUAGES]))
        self.kbd = Adw.ComboRow(title="Keyboard layout", model=string_list([k[0] for k in KEYBOARDS]))
        group.add(self.lang)
        group.add(self.kbd)
        box.append(group)

    def values(self):
        lang = LANGUAGES[self.lang.get_selected()]
        kbd = KEYBOARDS[self.kbd.get_selected()]
        return {"language": lang[0], "locale": lang[1], "keyboard": kbd[0], "xkb": kbd[1], "keymap": kbd[2]}


class TimezonePage(Page):
    title = "Time Zone"
    step = "Time Zone"

    def __init__(self, win):
        super().__init__(win)
        self.widget, box = page_shell("Time zone", "Pick the city closest to you. Start typing to search.")
        zones = run(["timedatectl", "list-timezones"]).splitlines() or ["UTC"]
        self.zones = zones
        group = Adw.PreferencesGroup()
        self.row = Adw.ComboRow(title="Time zone", model=string_list([z.replace("_", " ") for z in zones]),
                                enable_search=True)
        self.row.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        self._select("America/Los_Angeles")
        group.add(self.row)
        box.append(group)
        self.detected = make_label("", "page-body", xalign=0)
        box.append(self.detected)
        threading.Thread(target=self._detect, daemon=True).start()

    def _select(self, zone):
        if zone in self.zones:
            self.row.set_selected(self.zones.index(zone))
            return True
        return False

    def _detect(self):
        tz = run(["curl", "-fs", "--max-time", "4", "https://ipapi.co/timezone"])
        if tz and re.fullmatch(r"[A-Za-z_]+(/[A-Za-z0-9_+\-]+)*", tz):
            GLib.idle_add(lambda: self._select(tz) and self.detected.set_text(
                f"Detected automatically: {tz.replace('_', ' ')}"))

    def values(self):
        return {"timezone": self.zones[self.row.get_selected()]}


class DiskPage(Page):
    title = "Disk"
    step = "Disk"

    def __init__(self, win):
        super().__init__(win)
        self.widget, self.box = page_shell("Where should Floe go?",
                                           "Pick a disk, then choose how to install.")
        self.group = Adw.PreferencesGroup(title="Disk")
        self.box.append(self.group)
        self.how = Adw.PreferencesGroup(title="How to install", visible=False)
        self.box.append(self.how)
        self.hint = make_label("", "page-body", xalign=0, visible=False)
        self.box.append(self.hint)
        warn = Gtk.Box(spacing=10, margin_top=4)
        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        icon.add_css_class("warn")
        warn.append(icon)
        self.warning = make_label("", "warn", xalign=0, hexpand=True)
        warn.append(self.warning)
        self.warn_box = warn
        self.box.append(warn)
        refresh = Gtk.Button(label="Refresh disk list", halign=Gtk.Align.START)
        refresh.add_css_class("flat")
        refresh.connect("clicked", lambda *_: self.on_show())
        self.box.append(refresh)
        self.rows, self.how_rows = [], []
        self.selected = None
        self.layout = None
        self.mode = None
        self.part_dd = None

    def on_show(self):
        for row in self.rows:
            self.group.remove(row)
        self.rows = []
        self.selected = None
        first = None
        disks = list_disks()
        if not disks:
            row = Adw.ActionRow(title="No disks found", subtitle="Connect a drive and press Refresh.")
            self.group.add(row)
            self.rows.append(row)
        for disk in disks:
            subtitle = f"{human_size(disk['size'])} · {disk['path']}" + (f" · {disk['tran']}" if disk["tran"] else "")
            if not disk["big_enough"]:
                subtitle += " · too small (needs 12 GB)"
            row = Adw.ActionRow(title=disk["model"], subtitle=subtitle)
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            if first:
                check.set_group(first)
            else:
                first = check
            check.set_sensitive(disk["big_enough"])
            check.connect("toggled", lambda c, d=disk: self._pick(c, d))
            row.add_prefix(Gtk.Image.new_from_icon_name("drive-harddisk-symbolic"))
            row.add_suffix(check)
            row.set_activatable_widget(check)
            row.set_sensitive(disk["big_enough"])
            self.group.add(row)
            self.rows.append(row)
        usable = [d for d in disks if d["big_enough"]]
        self._show_modes()
        if len(usable) == 1:
            for row, disk in zip(self.rows, disks):
                if disk is usable[0]:
                    row.get_activatable_widget().set_active(True)
        self.win.update_buttons()

    def _pick(self, check, disk):
        if check.get_active():
            self.selected = disk
            self.layout = disk_layout(disk["path"])
            self._show_modes()
        self.win.update_buttons()

    def _show_modes(self):
        for row in self.how_rows:
            self.how.remove(row)
        self.how_rows = []
        self.mode = None
        self.part_dd = None
        self.hint.set_visible(False)
        self.warn_box.set_visible(False)
        L = self.layout if self.selected else None
        self.how.set_visible(L is not None)
        if L is None:
            return

        first = None

        def add(mode, title, subtitle, enabled, extra=None):
            nonlocal first
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER, sensitive=enabled)
            if first:
                check.set_group(first)
            else:
                first = check
            check.connect("toggled", lambda c: c.get_active() and self._set_mode(mode))
            row.add_prefix(check)
            if extra:
                row.add_suffix(extra)
            row.set_activatable_widget(check)
            row.set_sensitive(enabled)
            self.how.add(row)
            self.how_rows.append(row)
            return check

        # Alongside
        if L["can_free"]:
            sub = f"Uses {human_size(L['free'][0]['size'])} of free space. Everything else stays as it is."
        elif L["blocker"] and L["has_data"]:
            sub = L["blocker"]
        elif L["full_primaries"]:
            sub = "This disk already has 4 main partitions, the most it can hold."
        elif L["has_data"]:
            sub = "There's no free space yet. See below for how to make room."
        else:
            sub = "This disk is empty, so there's nothing to keep."
        c_free = add("free", "Install alongside" + (" Windows" if L["windows"] else " what's already here"),
                     sub, L["can_free"])

        # Replace a partition
        repl = L["replaceable"]
        if repl:
            self.part_dd = Gtk.DropDown.new_from_strings([describe_part(p) for p in repl])
            self.part_dd.set_valign(Gtk.Align.CENTER)
            self.part_dd.connect("notify::selected", lambda *_: self._set_mode(self.mode))
        add("partition", "Replace a partition",
            "Erases one partition and installs Floe there." if repl else "No partition here is big enough (12 GB).",
            bool(repl), self.part_dd)

        # Erase
        c_erase = add("erase", "Erase the whole disk", "Removes everything on this disk, including other systems.", True)

        if L["windows"] and not L["can_free"] and not L["blocker"]:
            self.hint.set_text("Want to keep Windows? Make room first: in Windows, open Disk Management "
                               "(right-click Start), right-click your C: drive, choose Shrink Volume, and shrink "
                               "it by at least 20 GB (20,000 MB). Then restart from this USB stick and pick "
                               "“Install alongside Windows”.")
            self.hint.set_visible(True)
        if L["can_free"]:
            c_free.set_active(True)
        elif not L["has_data"]:
            c_erase.set_active(True)

    def _set_mode(self, mode):
        self.mode = mode
        L = self.layout
        msg = ""
        if mode == "erase":
            msg = "Everything on this disk will be erased. Back up anything you want to keep first."
        elif mode == "partition" and self.part_dd is not None:
            p = L["replaceable"][self.part_dd.get_selected()]
            msg = f"Everything on {describe_part(p)} will be erased."
            if p["fstype"] == "ntfs":
                msg += " This looks like a Windows partition. Windows may stop working."
        elif mode == "free":
            msg = ("Nothing on the disk will be erased. A menu will let you choose Floe or "
                   f"{'Windows' if L['windows'] else 'your other system'} each time you start. "
                   "If Windows uses BitLocker, have your recovery key handy.")
        self.warning.set_text(msg)
        self.warn_box.set_visible(bool(msg))
        self.win.update_buttons()

    def can_continue(self):
        if self.selected is None or self.mode is None:
            return False
        if self.mode == "partition":
            return self.part_dd is not None
        if self.mode == "free":
            return bool(self.layout and self.layout["can_free"])
        return True

    def values(self):
        d = self.selected
        v = {"disk": d["path"], "mode": self.mode, "disk_label": f"{d['model']} ({human_size(d['size'])})"}
        if self.mode == "free":
            g = self.layout["free"][0]
            v.update(free_start=g["start"], free_size=g["size"],
                     where=f"{human_size(g['size'])} of free space on {v['disk_label']}")
        elif self.mode == "partition":
            p = self.layout["replaceable"][self.part_dd.get_selected()]
            v.update(target=p["path"], where=describe_part(p))
        else:
            v["where"] = v["disk_label"]
        return v


class AccountPage(Page):
    title = "Account"
    step = "Account"

    def __init__(self, win):
        super().__init__(win)
        self.widget, box = page_shell("Create your account",
                                      "This is the account you'll sign in with.")
        group = Adw.PreferencesGroup()
        self.name = Adw.EntryRow(title="Your name")
        self.user = Adw.EntryRow(title="Username")
        self.host = Adw.EntryRow(title="Computer name")
        self.pw1 = Adw.PasswordEntryRow(title="Password")
        self.pw2 = Adw.PasswordEntryRow(title="Confirm password")
        for row in (self.name, self.user, self.host, self.pw1, self.pw2):
            group.add(row)
            row.connect("changed", self._changed)
        box.append(group)
        self.hint = make_label("", "error-text", xalign=0)
        box.append(self.hint)
        self.user_edited = self.host_edited = False
        self._auto = False
        self.user.connect("changed", lambda *_: self._mark("user"))
        self.host.connect("changed", lambda *_: self._mark("host"))

    def _mark(self, which):
        if not self._auto:
            setattr(self, f"{which}_edited", True)

    def _changed(self, row):
        if row is self.name:
            first = (self.name.get_text().strip().split() or [""])[0]
            slug = re.sub(r"[^a-z0-9]", "", first.lower())
            self._auto = True
            if not self.user_edited:
                self.user.set_text(slug)
            if not self.host_edited:
                self.host.set_text(f"{slug}-wren" if slug else "")
            self._auto = False
        self.hint.set_text(self._problem() or "")
        self.win.update_buttons()

    def _problem(self):
        user, host = self.user.get_text(), self.host.get_text()
        pw1, pw2 = self.pw1.get_text(), self.pw2.get_text()
        if user and (not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user) or user in RESERVED_USERS):
            return "Usernames use lowercase letters and numbers, and must start with a letter."
        if host and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}", host):
            return "Computer names use letters, numbers and dashes only."
        if pw1 and len(pw1) < 4:
            return "Use a password of at least 4 characters."
        if pw2 and pw1 != pw2:
            return "The passwords don't match."
        return None

    def can_continue(self):
        return bool(self.name.get_text().strip() and self.user.get_text() and self.host.get_text()
                    and self.pw1.get_text() and self.pw1.get_text() == self.pw2.get_text()
                    and not self._problem())

    def values(self):
        return {"fullname": self.name.get_text().strip(), "user": self.user.get_text(),
                "hostname": self.host.get_text(), "password": self.pw1.get_text()}


class ReviewPage(Page):
    title = "Review"
    step = "Review"

    def __init__(self, win):
        super().__init__(win)
        self.widget, box = page_shell("Ready to install", "Check everything below. Nothing has changed yet.")
        self.group = Adw.PreferencesGroup()
        box.append(self.group)
        self.rows = []

    def on_show(self):
        for row in self.rows:
            self.group.remove(row)
        v = self.win.values()
        items = [
            ("drive-harddisk-symbolic",
             {"erase": "Disk (will be erased)", "partition": "Partition (will be erased)",
              "free": "Free space (nothing is erased)"}[v["mode"]], v["where"]),
            ("avatar-default-symbolic", "Account", f"{v['fullname']} ({v['user']})"),
            ("computer-symbolic", "Computer name", v["hostname"]),
            ("preferences-desktop-locale-symbolic", "Language", v["language"]),
            ("input-keyboard-symbolic", "Keyboard", v["keyboard"]),
            ("preferences-system-time-symbolic", "Time zone", v["timezone"].replace("_", " ")),
        ]
        self.rows = []
        for icon, title, sub in items:
            row = Adw.ActionRow(title=title, subtitle=sub)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            self.group.add(row)
            self.rows.append(row)


class ProgressPage(Page):
    def __init__(self, win):
        super().__init__(win)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, valign=Gtk.Align.CENTER,
                      vexpand=True, margin_start=48, margin_end=48)
        clamp = Adw.Clamp(maximum_size=560)
        clamp.set_child(box)
        logo = Gtk.Image.new_from_file(LOGO)
        logo.set_pixel_size(72)
        box.append(logo)
        self.heading = make_label("Installing Floe", "page-title", justify=Gtk.Justification.CENTER)
        box.append(self.heading)
        self.status = make_label("Getting ready…", "page-body", justify=Gtk.Justification.CENTER)
        box.append(self.status)
        self.bar = Gtk.ProgressBar(margin_top=8)
        box.append(self.bar)
        self.expander = Gtk.Expander(label="Details", margin_top=8)
        self.log = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.log.add_css_class("log")
        scroll = Gtk.ScrolledWindow(min_content_height=180)
        scroll.set_child(self.log)
        self.scroll = scroll
        self.expander.set_child(scroll)
        box.append(self.expander)
        self.actions = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER, margin_top=12, visible=False)
        box.append(self.actions)
        self.widget = clamp

    def append_log(self, text):
        buf = self.log.get_buffer()
        buf.insert(buf.get_end_iter(), text + "\n")
        adj = self.scroll.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()))


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Install Floe", default_width=880, default_height=640)
        self.pages = [WelcomePage(self), LanguagePage(self), TimezonePage(self), DiskPage(self),
                      AccountPage(self), ReviewPage(self), ProgressPage(self)]
        self.progress = self.pages[-1]
        self.index = 0
        self.installing = False

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT, transition_duration=320,
                               vexpand=True)
        for i, page in enumerate(self.pages):
            self.stack.add_named(page.widget, str(i))

        header = Adw.HeaderBar()
        self.steps = Gtk.Box(spacing=18)
        self.steps.add_css_class("steps")
        self.step_labels = []
        for page in self.pages:
            if page.step:
                lbl = Gtk.Label(label=page.step)
                self.steps.append(lbl)
                self.step_labels.append((page, lbl))
        header.set_title_widget(self.steps)

        self.back = Gtk.Button(label="Back")
        self.back.add_css_class("big-button")
        self.back.connect("clicked", lambda *_: self.go(self.index - 1))
        self.next = Gtk.Button(label="Continue")
        self.next.add_css_class("big-button")
        self.next.add_css_class("suggested-action")
        self.next.connect("clicked", lambda *_: self.on_next())
        self.footer = Gtk.Box(spacing=12)
        self.footer.add_css_class("footer")
        self.footer.append(self.back)
        self.footer.append(Gtk.Box(hexpand=True))
        self.footer.append(self.next)

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self.stack)
        view.add_bottom_bar(self.footer)
        self.set_content(view)
        self.connect("close-request", self.on_close)
        self.go(int(os.environ.get("WREN_INSTALLER_PAGE", "0")))  # used for screenshots

    def values(self):
        v = {}
        for page in self.pages:
            if hasattr(page, "values"):
                v.update(page.values())
        return v

    def go(self, index):
        index = max(0, min(index, len(self.pages) - 1))
        self.index = index
        page = self.pages[index]
        page.on_show()
        self.stack.set_visible_child_name(str(index))
        self.footer.set_visible(page.step is not None)
        self.steps.set_visible(page.step is not None)
        passed = True
        for p, lbl in self.step_labels:
            for c in ("current", "done"):
                lbl.remove_css_class(c)
            if p is page:
                lbl.add_css_class("current")
                passed = False
            elif passed:
                lbl.add_css_class("done")
        self.update_buttons()

    def update_buttons(self):
        page = self.pages[self.index]
        self.back.set_sensitive(self.index > 0)
        self.next.set_sensitive(page.can_continue())
        review = isinstance(page, ReviewPage)
        mode = self.pages[3].mode if hasattr(self.pages[3], "mode") else "erase"
        label = {"erase": "Erase Disk & Install", "partition": "Erase Partition & Install",
                 "free": "Install"}.get(mode, "Install")
        self.next.set_label(label if review else "Continue")
        if review and mode == "free":
            self.next.remove_css_class("destructive-action")
            self.next.add_css_class("suggested-action")
        elif review:
            self.next.remove_css_class("suggested-action")
            self.next.add_css_class("destructive-action")
        else:
            self.next.remove_css_class("destructive-action")
            self.next.add_css_class("suggested-action")

    def on_next(self):
        if isinstance(self.pages[self.index], ReviewPage):
            v = self.values()
            if v["mode"] == "free":
                heading, body, go = ("Install Floe alongside?",
                                     f"Floe will use {v['where']}. Nothing else will be changed.", "Install")
            elif v["mode"] == "partition":
                heading, body, go = ("Erase this partition?",
                                     f"Everything on {v['where']} will be permanently deleted.", "Erase & Install")
            else:
                heading, body, go = ("Erase this disk?",
                                     f"Everything on {v['disk_label']} will be permanently deleted and Floe "
                                     "will be installed.", "Erase & Install")
            dialog = Adw.AlertDialog(heading=heading, body=body)
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("install", go)
            dialog.set_response_appearance("install", Adw.ResponseAppearance.SUGGESTED if v["mode"] == "free"
                                           else Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")
            dialog.connect("response", lambda _d, r: self.start_install() if r == "install" else None)
            dialog.present(self)
        else:
            self.go(self.index + 1)

    def on_close(self, *_):
        return self.installing  # block closing mid-install

    # -- install
    def start_install(self):
        v = self.values()
        self.installing = True
        self.go(len(self.pages) - 1)
        env = dict(os.environ, WREN_DISK=v["disk"], WREN_USER=v["user"], WREN_FULLNAME=v["fullname"],
                   WREN_HOSTNAME=v["hostname"], WREN_TZ=v["timezone"], WREN_LOCALE=v["locale"],
                   WREN_XKB=v["xkb"], WREN_KEYMAP=v["keymap"], WREN_MODE=v["mode"],
                   WREN_FREE_START=str(v.get("free_start", "")), WREN_FREE_SIZE=str(v.get("free_size", "")),
                   WREN_TARGET=v.get("target", ""))
        wren_env = {k: env[k] for k in env if k.startswith("WREN_")}
        cmd = [BACKEND] if os.geteuid() == 0 else \
            ["sudo", "-n", "env"] + [f"{k}={v}" for k, v in wren_env.items()] + [BACKEND]
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, env=env, bufsize=1)
        except OSError as e:
            self.finish(False, str(e))
            return
        proc.stdin.write(v["password"] + "\n")
        proc.stdin.close()
        threading.Thread(target=self._watch, args=(proc,), daemon=True).start()

    def _watch(self, proc):
        error = None
        for line in proc.stdout:
            line = line.rstrip("\n")
            m = re.match(r"^@@ (\d+) (.*)$", line)
            if m:
                pct, msg = int(m.group(1)), m.group(2)
                GLib.idle_add(self._progress, pct, msg)
            elif line.startswith("@@ERROR"):
                error = line[7:].strip()
            else:
                GLib.idle_add(self.progress.append_log, line)
        code = proc.wait()
        GLib.idle_add(self.finish, code == 0, error or f"The installer stopped (code {code}).")

    def _progress(self, pct, msg):
        self.progress.bar.set_fraction(pct / 100)
        self.progress.status.set_text(msg)
        self.progress.append_log(f"== {msg}")

    def finish(self, success, error):
        self.installing = False
        p = self.progress
        for child in list(self._children(p.actions)):
            p.actions.remove(child)
        p.actions.set_visible(True)
        if success:
            p.heading.set_text("Floe is installed")
            p.status.set_text("Click Restart Now. When the screen goes dark, remove the USB stick.")
            p.bar.set_fraction(1.0)
            btn = Gtk.Button(label="Restart Now")
            btn.add_css_class("big-button")
            btn.add_css_class("suggested-action")
            btn.connect("clicked", lambda *_: restart_now())
            later = Gtk.Button(label="Later")
            later.add_css_class("big-button")
            later.connect("clicked", lambda *_: self.close())
            p.actions.append(later)
            p.actions.append(btn)
        else:
            p.heading.set_text("Installation didn't finish")
            p.status.set_text(f"{error}\nYour disk may be partly erased. You can try again.")
            p.status.add_css_class("error-text")
            p.expander.set_expanded(True)
            again = Gtk.Button(label="Try Again")
            again.add_css_class("big-button")
            again.add_css_class("suggested-action")
            again.connect("clicked", lambda *_: (p.status.remove_css_class("error-text"),
                                                 p.heading.set_text("Installing Floe"),
                                                 p.actions.set_visible(False),
                                                 p.bar.set_fraction(0), self.go(5)))
            p.actions.append(again)
        return False

    @staticmethod
    def _children(widget):
        child = widget.get_first_child()
        while child:
            yield child
            child = child.get_next_sibling()


class Installer(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.wrenlinux.Installer", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.restyle = wrenlib.setup_app_style(CSS)

    def do_activate(self):
        win = self.get_active_window() or Window(self)
        win.present()


if __name__ == "__main__":
    sys.exit(Installer().run(sys.argv))
