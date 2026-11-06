#!/usr/bin/env python3
"""Wren App Store: find and install apps from Flathub. Installs go into the user's
own Flatpak installation, so no password is needed."""
import hashlib
import html
import json
import os
import pty
import re
import select
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

sys.path.insert(0, "/usr/lib/wren")
import wrenlib  # noqa: E402

API = "https://flathub.org/api/v2"
REMOTE_URL = "https://dl.flathub.org/repo/flathub.flatpakrepo"
CACHE = os.path.join(GLib.get_user_cache_dir(), "wren-store")
POOL = ThreadPoolExecutor(max_workers=6)

FEATURED = ("com.spotify.Client", "Spotify", "Music, podcasts and audiobooks. Millions of songs, free.")

SECTIONS = [
    ("Essentials", [
        ("com.google.Chrome", "Google Chrome", "The browser built by Google"),
        ("com.discordapp.Discord", "Discord", "Chat, voice and video with friends"),
        ("org.videolan.VLC", "VLC", "Plays almost any video or music file"),
        ("org.libreoffice.LibreOffice", "LibreOffice", "Documents, spreadsheets and slides"),
        ("us.zoom.Zoom", "Zoom", "Video meetings and calls"),
        ("com.brave.Browser", "Brave", "Fast, private web browser"),
    ]),
    ("Games", [
        ("com.valvesoftware.Steam", "Steam", "Thousands of games, one library"),
        ("org.prismlauncher.PrismLauncher", "Prism Launcher", "Minecraft with easy mod support"),
        ("org.vinegarhq.Sober", "Sober", "Play Roblox on Linux"),
        ("com.heroicgameslauncher.hgl", "Heroic", "Your Epic, GOG and Amazon games"),
        ("org.libretro.RetroArch", "RetroArch", "Classic consoles in one app"),
        ("net.supertuxkart.SuperTuxKart", "SuperTuxKart", "Free kart racing"),
    ]),
    ("Create", [
        ("org.gimp.GIMP", "GIMP", "Edit photos and images"),
        ("org.kde.krita", "Krita", "Digital painting"),
        ("org.inkscape.Inkscape", "Inkscape", "Vector graphics and illustration"),
        ("com.obsproject.Studio", "OBS Studio", "Record and stream your screen"),
        ("org.kde.kdenlive", "Kdenlive", "Edit videos"),
        ("org.blender.Blender", "Blender", "3D modeling and animation"),
    ]),
    ("Chat & Work", [
        ("org.telegram.desktop", "Telegram", "Fast, secure messaging"),
        ("org.signal.Signal", "Signal", "Private messaging"),
        ("com.slack.Slack", "Slack", "Team chat"),
        ("org.mozilla.Thunderbird", "Thunderbird", "Email and calendar"),
        ("md.obsidian.Obsidian", "Obsidian", "Notes that connect"),
        ("org.onlyoffice.desktopeditors", "ONLYOFFICE", "Office suite that opens Microsoft files"),
    ]),
    ("Developer Tools", [
        ("com.visualstudio.code", "Visual Studio Code", "Code editor from Microsoft"),
        ("dev.zed.Zed", "Zed", "Fast, modern code editor"),
        ("io.github.shiftey.Desktop", "GitHub Desktop", "Git made simple"),
        ("com.getpostman.Postman", "Postman", "Build and test APIs"),
    ]),
    ("Utilities", [
        ("com.bitwarden.desktop", "Bitwarden", "Password manager"),
        ("org.qbittorrent.qBittorrent", "qBittorrent", "Download torrents"),
        ("com.usebottles.bottles", "Bottles", "Run Windows programs"),
        ("com.github.tchx84.Flatseal", "Flatseal", "Control app permissions"),
        ("org.gnome.Calendar", "Calendar", "Your schedule at a glance"),
        ("org.chromium.Chromium", "Chromium", "Open-source web browser"),
    ]),
]

CATEGORIES = [
    ("Discover", "starred-symbolic", None),
    ("Games", "input-gaming-symbolic", "Game"),
    ("Music & Video", "folder-music-symbolic", "AudioVideo"),
    ("Graphics & Photos", "image-x-generic-symbolic", "Graphics"),
    ("Office", "x-office-document-symbolic", "Office"),
    ("Internet & Chat", "network-workgroup-symbolic", "Network"),
    ("Developer Tools", "utilities-terminal-symbolic", "Development"),
    ("Education", "accessories-dictionary-symbolic", "Education"),
    ("Utilities", "applications-utilities-symbolic", "Utility"),
]

CSS = """
.store { background-color: @wren_bg; }
.side { background-color: @wren_deep; border-right: 1px solid @wren_line; padding: 0 10px; }
.side row { padding: 9px 12px; margin: 1px 0; border-radius: 12px; color: @wren_dim; }
.side row:hover { background-color: alpha(@wren_text, 0.05); color: @wren_text; }
.side row:selected { background-color: @wren_surface; color: @wren_text; box-shadow: 0 1px 6px alpha(@wren_shadow, 0.6); }
.side row:selected image { color: @wren_accent; }
.side list { background: transparent; }
.side-sep { margin: 8px 12px; background-color: @wren_line; min-height: 1px; }
.side-title { font-size: 12px; font-weight: 700; color: @wren_muted; margin: 16px 14px 6px 14px; }
.page-title { font-size: 28px; font-weight: 800; letter-spacing: -0.5px; }
.section { font-size: 13px; font-weight: 700; color: @wren_dim; margin-top: 18px; }
.hero { background-image: linear-gradient(120deg, alpha(@wren_accent, 0.85) 0%, alpha(@wren_accent, 0.45) 60%, alpha(@wren_accent, 0.15) 100%);
        border: 1px solid @wren_glass_border; border-radius: 22px; padding: 30px;
        box-shadow: 0 10px 30px alpha(@wren_accent, 0.25); }
.hero label { color: #FFFFFF; }
.hero-tag { font-size: 12px; font-weight: 800; letter-spacing: 0.08em; opacity: 0.85; }
.hero-name { font-size: 32px; font-weight: 800; }
.hero-sum { font-size: 14px; opacity: 0.92; }
.card { background-color: @wren_surface; border: 1px solid @wren_glass_edge; border-radius: 18px; padding: 14px;
        box-shadow: 0 2px 10px alpha(@wren_shadow, 0.45); transition: box-shadow 150ms ease, background 150ms ease; }
.card:hover { box-shadow: 0 8px 22px alpha(@wren_shadow, 0.8); }
.card-name { font-weight: 700; }
.card-sum { color: @wren_dim; font-size: 12px; }
.chip { font-size: 11px; font-weight: 700; color: @wren_accent_text; background: @wren_accent_glass;
        border-radius: 999px; padding: 2px 8px; }
.dim { color: @wren_dim; }
.detail-name { font-size: 30px; font-weight: 800; letter-spacing: -0.5px; }
.detail-dev { color: @wren_dim; }
.detail-desc { font-size: 14px; color: @wren_text2; }
.shot { border: 1px solid @wren_glass_edge; border-radius: 14px; }
.btn { padding: 8px 20px; font-weight: 700; border-radius: 999px; }
.btn.primary { background-color: @wren_accent; color: @wren_on_accent; box-shadow: 0 4px 12px alpha(@wren_accent, 0.3); }
.btn.primary:hover { background-color: @wren_accent_hover; }
.btn.danger:hover { background-color: #E5484D; color: #FFFFFF; }
.row-item { padding: 12px 16px; border-bottom: 1px solid @wren_line; }
progressbar trough, progressbar progress { min-height: 6px; border-radius: 999px; }
"""


# ------------------------------------------------------------------ flatpak
PROGRESS_RE = re.compile(r"(?:Installing|Updating|Uninstalling)\s+(\d+)/(\d+)\D*?(\d{1,3})%"
                         r"(?:\s+([\d.,]+\s*[kMG]?B/s))?(?:\s+(\d{1,2}:\d\d(?::\d\d)?))?")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


class FlatpakJob:
    """Runs a flatpak command in a pseudo-terminal so it reports real progress
    (piped output has none), and reports (fraction, status text) as it goes."""

    def __init__(self, cmd, on_progress):
        self.cmd = cmd
        self.on_progress = on_progress
        self.proc = None
        self.cancelled = False
        self.error = ""

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except OSError:
                pass

    def run(self):
        os.makedirs(CACHE, exist_ok=True)
        log = open(os.path.join(CACHE, "last-run.log"), "w")
        log.write("$ " + " ".join(self.cmd) + "\n")
        master, slave = pty.openpty()
        env = dict(os.environ, COLUMNS="160", LINES="50", TERM="xterm", LANG="C.UTF-8", LC_ALL="C.UTF-8")
        try:
            self.proc = subprocess.Popen(self.cmd, stdin=subprocess.DEVNULL, stdout=slave, stderr=slave,
                                         env=env, start_new_session=True)
        except OSError as e:
            os.close(master)
            os.close(slave)
            self.error = str(e)
            return False
        os.close(slave)
        pending, last = "", (None, None)
        errors = []
        while True:
            ready, _, _ = select.select([master], [], [], 1.0)
            if ready:
                try:
                    data = os.read(master, 4096)
                except OSError:
                    data = b""
                if not data:
                    break
                text = ANSI_RE.sub("", data.decode(errors="replace"))
                log.write(text)
                pending += text
                parts = re.split(r"[\r\n]", pending)
                pending = parts.pop()
                for line in parts + [pending]:
                    m = PROGRESS_RE.search(line)
                    if m:
                        i, n, pct = int(m.group(1)), int(m.group(2)), min(int(m.group(3)), 100)
                        frac = ((i - 1) + pct / 100) / max(n, 1)
                        status = f"Downloading part {i} of {n}" if n > 1 else "Downloading"
                        if m.group(4):
                            status += f" · {m.group(4).replace(chr(160), ' ')}"
                        if m.group(5) and m.group(5) not in ("00:00", "0:00"):
                            status += f" · {m.group(5)} left"
                        if (round(frac, 2), status) != last:
                            last = (round(frac, 2), status)
                            self.on_progress(frac, status)
                    elif line.lower().startswith("error:"):
                        errors.append(line[6:].strip())
            elif self.proc.poll() is not None:
                break
        code = self.proc.wait()
        os.close(master)
        log.write(f"\n[exit {code}]\n")
        log.close()
        if errors:
            self.error = errors[-1]
        return code == 0 and not self.cancelled


# ------------------------------------------------------------------ data
def http_json(url, body=None, timeout=12):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": "WrenStore/1.0", "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def cached_json(key, url, max_age=3 * 86400):
    path = os.path.join(CACHE, "data", hashlib.sha1(key.encode()).hexdigest() + ".json")
    try:
        if time.time() - os.path.getmtime(path) < max_age:
            return json.load(open(path))
    except (OSError, ValueError):
        pass
    try:
        data = http_json(url)
    except Exception:
        try:
            return json.load(open(path))  # stale is better than nothing
        except (OSError, ValueError):
            return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)
    return data


def appstream(app_id):
    return cached_json("app:" + app_id, f"{API}/appstream/{app_id}")


def appstream_cached(app_id):
    """Cached details only, never touches the network (safe on the UI thread)."""
    path = os.path.join(CACHE, "data", hashlib.sha1(("app:" + app_id).encode()).hexdigest() + ".json")
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return None


def download(url):
    if not url:
        return None
    path = os.path.join(CACHE, "img", hashlib.sha1(url.encode()).hexdigest())
    if os.path.exists(path):
        return path
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WrenStore/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
    except Exception:
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".part", "wb") as f:
        f.write(data)
    os.replace(path + ".part", path)
    return path


def plain_text(desc):
    if not desc:
        return ""
    t = re.sub(r"<li>\s*", "• ", desc)
    t = re.sub(r"</(p|li|ul|ol)>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line.strip() for line in t.splitlines())).strip()


def run(cmd, timeout=60):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def installed_apps():
    r = run(["flatpak", "list", "--app", "--columns=application,installation"], 20)
    apps = {}
    if r and r.returncode == 0:
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if parts and parts[0]:
                apps[parts[0]] = parts[1] if len(parts) > 1 else "user"
    return apps


def in_background(fn, done=None, *args):
    def work():
        try:
            result = fn(*args)
        except Exception:
            result = None
        if done:
            GLib.idle_add(lambda: done(result) or False)
    POOL.submit(work)


def load_icon(image, url, app_id=None):
    """Fill a Gtk.Image from a URL (or from the app's appstream icon if no URL)."""
    def work():
        u = url
        if not u and app_id:
            info = appstream(app_id) or {}
            u = info.get("icon")
        return download(u)

    def done(path):
        if path:
            image.set_from_file(path)
    in_background(work, done)


def label(text, css="", **kw):
    lbl = Gtk.Label(label=text, xalign=0, **kw)
    for c in css.split():
        lbl.add_css_class(c)
    return lbl


# ------------------------------------------------------------------ window
class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="App Store", default_width=1120, default_height=740)
        self.add_css_class("store")
        self.installed = {}
        self.busy = {}          # app_id -> progress (0..1), or -1 while removing
        self.busy_text = {}     # app_id -> status line ("Downloading part 2 of 4 · 1.2 MB/s")
        self.jobs = {}          # app_id -> running FlatpakJob
        self.watchers = {}      # app_id -> [callbacks]
        self.history = []

        header = Adw.HeaderBar()
        self.back = Gtk.Button(icon_name="go-previous-symbolic", visible=False, tooltip_text="Back")
        self.back.connect("clicked", lambda *_: self.go_back())
        header.pack_start(self.back)
        self.search = Gtk.SearchEntry(placeholder_text="Search apps", width_chars=36)
        self.search.connect("activate", lambda *_: self.do_search())
        header.set_title_widget(self.search)
        self.toasts = Adw.ToastOverlay()

        body = Gtk.Box()
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=230)
        side.add_css_class("side")
        side.append(label("APP STORE", "side-title"))
        self.nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav.add_css_class("side")
        self.nav_rows = []
        for name, icon, cat in CATEGORIES:
            self.nav.append(self._nav_row(name, icon, ("cat", cat, name)))
        side.append(self.nav)
        sep = Gtk.Box()
        sep.add_css_class("side-sep")
        side.append(sep)
        self.mine = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.mine.add_css_class("side")
        self.mine.append(self._nav_row("Installed", "object-select-symbolic", ("installed",)))
        self.mine.append(self._nav_row("Updates", "software-update-available-symbolic", ("updates",)))
        side.append(self.mine)
        self.nav.connect("row-activated", self.on_nav)
        self.mine.connect("row-activated", self.on_nav)
        body.append(side)

        self.content = Gtk.Stack(hexpand=True, vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE,
                                 transition_duration=300)
        self.toasts.set_child(self.content)
        body.append(self.toasts)

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(body)
        self.set_content(view)

        self.refresh_installed(lambda: None)
        self.nav.select_row(self.nav.get_row_at_index(0))
        self.show_page(self.discover_page(), remember=False)
        start = os.environ.get("WREN_STORE_PAGE", "")  # used by the screenshot test
        if start.startswith("app:"):
            self.show_page(self.details_page(start[4:]))
        elif start.startswith("cat:"):
            self.show_page(self.category_page(start[4:], start[4:]), remember=False)
        elif start.startswith("search:"):
            self.search.set_text(start[7:])
            self.do_search()

    # ------------------------------------------------------------ navigation
    def _nav_row(self, name, icon, target):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(spacing=12)
        box.append(Gtk.Image.new_from_icon_name(icon))
        box.append(label(name))
        row.set_child(box)
        row.target = target
        return row

    def on_nav(self, listbox, row):
        other = self.mine if listbox is self.nav else self.nav
        other.unselect_all()
        self.history.clear()
        t = row.target
        if t[0] == "cat":
            page = self.discover_page() if t[1] is None else self.category_page(t[1], t[2])
        elif t[0] == "installed":
            page = self.installed_page()
        else:
            page = self.updates_page()
        self.show_page(page, remember=False)

    def show_page(self, widget, remember=True):
        current = self.content.get_visible_child()
        if remember and current:
            self.history.append(current)
        self.content.add_child(widget)
        self.content.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT if remember
                                         else Gtk.StackTransitionType.CROSSFADE)
        self.content.set_visible_child(widget)
        if current and not remember:
            GLib.timeout_add(320, lambda: (self.content.remove(current) if current.get_parent() else None) or False)
        self.back.set_visible(bool(self.history))

    def go_back(self):
        if not self.history:
            return
        current = self.content.get_visible_child()
        previous = self.history.pop()
        self.content.set_transition_type(Gtk.StackTransitionType.SLIDE_RIGHT)
        self.content.set_visible_child(previous)
        GLib.timeout_add(320, lambda: (self.content.remove(current) if current.get_parent() else None) or False)
        self.back.set_visible(bool(self.history))

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=4))

    @staticmethod
    def scroller(child):
        s = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        clamp = Adw.Clamp(maximum_size=1000, margin_top=24, margin_bottom=32, margin_start=28, margin_end=28)
        clamp.set_child(child)
        s.set_child(clamp)
        wrenlib.stagger(list(wrenlib.children(child)), step=30, cap=10)
        return s

    # ------------------------------------------------------------ pages
    def discover_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(self.hero(*FEATURED))
        for title, apps in SECTIONS:
            box.append(label(title.upper(), "section"))
            box.append(self.grid([{"app_id": a, "name": n, "summary": s} for a, n, s in apps]))
        return self.scroller(box)

    def category_page(self, category, title):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(label(title, "page-title"))
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER, margin_top=40)
        holder.append(spinner)
        box.append(holder)

        def done(data):
            holder.remove(spinner)
            hits = [h for h in (data or {}).get("hits", []) if h.get("type", "desktop-application") != "runtime"]
            if not hits:
                holder.append(self.offline_notice())
            else:
                holder.append(self.grid(hits))
        in_background(lambda: cached_json(f"cat:{category}", f"{API}/collection/category/{category}?page=1&per_page=48",
                                          max_age=86400), done)
        return self.scroller(box)

    def do_search(self):
        q = self.search.get_text().strip()
        if not q:
            return
        self.nav.unselect_all()
        self.mine.unselect_all()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(label(f"Results for “{q}”", "page-title"))
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER, margin_top=40)
        holder.append(spinner)
        box.append(holder)

        def work():
            try:
                return http_json(f"{API}/search", {"query": q, "hits_per_page": 36})
            except Exception:
                return None

        def done(data):
            holder.remove(spinner)
            if data is None:
                holder.append(self.offline_notice())
                return
            hits = [h for h in data.get("hits", []) if h.get("app_id")]
            if not hits:
                holder.append(label("No apps found. Try a different word.", "dim", margin_top=20))
            else:
                holder.append(self.grid(hits))
        in_background(work, done)
        self.history.clear()
        self.show_page(self.scroller(box), remember=False)

    def installed_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(label("Installed", "page-title"))
        box.append(label("Apps you installed from the App Store.", "dim"))
        lst = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=8)
        box.append(lst)

        def fill():
            child = lst.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                lst.remove(child)
                child = nxt
            apps = sorted(self.installed)
            if not apps:
                lst.append(label("Nothing yet. Find something on Discover.", "dim", margin_top=12))
            for app_id in apps:
                lst.append(self.list_row(app_id))
        self.refresh_installed(fill)
        return self.scroller(box)

    def updates_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(label("Updates", "page-title"))
        status = label("Checking for app updates…", "dim")
        box.append(status)
        btn = Gtk.Button(label="Update All", halign=Gtk.Align.START, visible=False)
        btn.add_css_class("btn")
        btn.add_css_class("primary")
        box.append(btn)
        bar = Gtk.ProgressBar(visible=False)
        box.append(bar)

        def check():
            r = run(["flatpak", "remote-ls", "--updates", "--user", "--app", "--columns=application"], 60)
            if r is None or r.returncode != 0:
                return None
            return [x for x in r.stdout.split() if x]

        def checked(apps):
            if apps is None:
                status.set_text("Couldn't check for updates. Are you online?")
            elif not apps:
                status.set_text("All your apps are up to date.")
            else:
                status.set_text(f"{len(apps)} app update{'s' if len(apps) != 1 else ''} available.")
                btn.set_visible(True)

        def update_all(*_):
            btn.set_sensitive(False)
            bar.set_visible(True)
            status.set_text("Updating apps…")

            def work():
                return self.flatpak_stream(["flatpak", "update", "--user", "-y", "--noninteractive"],
                                           lambda p: GLib.idle_add(bar.set_fraction, p))

            def done(ok):
                bar.set_visible(False)
                btn.set_visible(not ok)
                btn.set_sensitive(True)
                status.set_text("All your apps are up to date." if ok else "Some updates didn't finish. Try again.")
            in_background(work, done)
        btn.connect("clicked", update_all)
        in_background(check, checked)
        return self.scroller(box)

    def details_page(self, app_id, name="", summary="", icon=None):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        top = Gtk.Box(spacing=20)
        img = Gtk.Image(pixel_size=112, icon_name="application-x-executable")
        load_icon(img, icon, app_id)
        top.append(img)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True, spacing=4)
        title = label(name or app_id, "detail-name", wrap=True)
        dev = label("", "detail-dev")
        sumlbl = label(summary, "dim", wrap=True)
        info.append(title)
        info.append(dev)
        info.append(sumlbl)
        top.append(info)
        top.append(self.action_area(app_id, big=True))
        box.append(top)
        shot = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN, height_request=0, visible=False)
        shot.add_css_class("shot")
        box.append(shot)
        desc = label("", "detail-desc", wrap=True, selectable=True)
        box.append(desc)

        def done(data):
            if not data:
                desc.set_text("Couldn't load details. Check your internet connection.")
                return
            title.set_text(data.get("name") or name or app_id)
            sumlbl.set_text(data.get("summary") or summary)
            if data.get("developer_name"):
                dev.set_text(data["developer_name"])
            desc.set_text(plain_text(data.get("description")))
            shots = data.get("screenshots") or []
            if shots:
                sizes = shots[0].get("sizes") or []
                best = None
                for s in sizes:
                    w = int(s.get("width") or 0)
                    if 600 <= w <= 1300 and (best is None or w < int(best.get("width") or 0)):
                        best = s
                best = best or (sizes[0] if sizes else None)
                if best and best.get("src"):
                    in_background(download, lambda p: p and (shot.set_filename(p), shot.set_size_request(-1, 380),
                                                              shot.set_visible(True)), best["src"])
        in_background(appstream, done, app_id)
        return self.scroller(box)

    # ------------------------------------------------------------ widgets
    def hero(self, app_id, name, summary):
        box = Gtk.Box(spacing=24)
        box.add_css_class("hero")
        img = Gtk.Image(pixel_size=96, icon_name="application-x-executable")
        load_icon(img, None, app_id)
        box.append(img)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True, spacing=4)
        text.append(label("FEATURED", "hero-tag"))
        text.append(label(name, "hero-name"))
        text.append(label(summary, "hero-sum", wrap=True))
        box.append(text)
        box.append(self.action_area(app_id, big=True))
        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self.show_page(self.details_page(app_id, name, summary)))
        img.add_controller(click)
        return box

    def grid(self, apps):
        flow = Gtk.FlowBox(homogeneous=True, min_children_per_line=2, max_children_per_line=3,
                           selection_mode=Gtk.SelectionMode.NONE, row_spacing=10, column_spacing=10)
        for a in apps:
            flow.append(self.card(a))
        return flow

    def card(self, a):
        app_id = a["app_id"]
        btn = Gtk.Button()
        btn.add_css_class("card")
        btn.add_css_class("flat")
        box = Gtk.Box(spacing=14)
        img = Gtk.Image(pixel_size=56, icon_name="application-x-executable")
        load_icon(img, a.get("icon"), app_id)
        box.append(img)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True, spacing=2)
        text.append(label(a.get("name") or app_id, "card-name", ellipsize=3))
        text.append(label(a.get("summary") or "", "card-sum", ellipsize=3, lines=2, wrap=True))
        chip = label("INSTALLED", "chip", visible=app_id in self.installed)
        text.append(chip)
        self.watch(app_id, lambda: chip.set_visible(app_id in self.installed))
        box.append(text)
        btn.set_child(box)
        btn.connect("clicked", lambda *_: self.show_page(
            self.details_page(app_id, a.get("name", ""), a.get("summary", ""), a.get("icon"))))
        return btn

    def list_row(self, app_id):
        row = Gtk.Box(spacing=14)
        row.add_css_class("row-item")
        img = Gtk.Image(pixel_size=40, icon_name="application-x-executable")
        load_icon(img, None, app_id)
        row.append(img)
        name = label(app_id, "card-name", hexpand=True)
        row.append(name)
        in_background(appstream, lambda d: d and name.set_text(d.get("name") or app_id), app_id)
        row.append(self.action_area(app_id))
        return row

    def action_area(self, app_id, big=False):
        box = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)

        def render():
            child = box.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                box.remove(child)
                child = nxt
            if app_id in self.busy:
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, width_request=220 if big else 180)
                p = self.busy[app_id]
                removing = p is not None and p < 0
                col.append(label("Removing…" if removing else self.busy_text.get(app_id, "Installing…"),
                                 "dim", ellipsize=3))
                col.append(Gtk.ProgressBar(fraction=max(p or 0, 0)))
                box.append(col)
                if not removing and app_id in self.jobs:
                    stop = Gtk.Button(icon_name="process-stop-symbolic", tooltip_text="Cancel")
                    stop.add_css_class("btn")
                    stop.connect("clicked", lambda *_: self.jobs[app_id].cancel() if app_id in self.jobs else None)
                    box.append(stop)
            elif app_id in self.installed:
                open_btn = Gtk.Button(label="Open")
                open_btn.add_css_class("btn")
                open_btn.add_css_class("primary")
                open_btn.connect("clicked", lambda *_: self.open_app(app_id))
                box.append(open_btn)
                rm = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Remove")
                rm.add_css_class("btn")
                rm.add_css_class("danger")
                rm.connect("clicked", lambda *_: self.confirm_remove(app_id))
                box.append(rm)
            else:
                inst = Gtk.Button(label="Install")
                inst.add_css_class("btn")
                inst.add_css_class("primary")
                inst.connect("clicked", lambda *_: self.install(app_id))
                box.append(inst)
        render()
        self.watch(app_id, render)
        return box

    def offline_notice(self):
        return Adw.StatusPage(icon_name="network-offline-symbolic", title="Can't reach the App Store",
                              description="Check that you're connected to the internet, then try again.")

    # ------------------------------------------------------------ state
    def watch(self, app_id, cb):
        self.watchers.setdefault(app_id, []).append(cb)

    def notify(self, app_id):
        for cb in self.watchers.get(app_id, []):
            try:
                cb()
            except Exception:
                pass

    def refresh_installed(self, then):
        def done(apps):
            before = set(self.installed)
            self.installed = apps or {}
            for app_id in before ^ set(self.installed):
                self.notify(app_id)
            then()
        in_background(installed_apps, done)

    # ------------------------------------------------------------ actions
    @staticmethod
    def flatpak_stream(cmd, progress):
        cmd = [c for c in cmd if c != "--noninteractive"]
        return FlatpakJob(cmd, lambda frac, _status: progress(frac)).run()

    def install(self, app_id):
        self.busy[app_id] = 0.0
        self.busy_text[app_id] = "Getting ready…"
        self.notify(app_id)

        def progress(frac, status):
            self.busy[app_id] = frac
            self.busy_text[app_id] = status
            GLib.idle_add(lambda: self.notify(app_id) or False)

        job = FlatpakJob(["flatpak", "install", "--user", "-y", "flathub", app_id], progress)
        self.jobs[app_id] = job

        def work():
            run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", REMOTE_URL], 60)
            ok = job.run()
            GLib.idle_add(lambda: done(ok) or False)

        def done(ok):
            self.busy.pop(app_id, None)
            self.busy_text.pop(app_id, None)
            self.jobs.pop(app_id, None)
            info = appstream_cached(app_id) or {}
            nice = info.get("name") or app_id
            if ok:
                self.toast(f"{nice} is installed. Find it in your apps.")
                subprocess.Popen(["notify-send", "-a", "App Store", f"{nice} installed", "It's ready in your apps."],
                                 stderr=subprocess.DEVNULL)
            elif job.cancelled:
                self.toast(f"Stopped installing {nice}")
            else:
                why = f": {job.error}" if job.error else ". Check your connection and try again."
                self.toast(f"Couldn't install {nice}{why}")
            self.refresh_installed(lambda: self.notify(app_id))
        threading.Thread(target=work, daemon=True).start()

    def confirm_remove(self, app_id):
        info = appstream_cached(app_id) or {}
        nice = info.get("name") or app_id
        dialog = Adw.AlertDialog(heading=f"Remove {nice}?", body="You can install it again any time.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, r: r == "remove" and self.remove(app_id, nice))
        dialog.present(self)

    def remove(self, app_id, nice):
        self.busy[app_id] = -1
        self.notify(app_id)
        scope = "--system" if self.installed.get(app_id) == "system" else "--user"
        cmd = ["flatpak", "uninstall", scope, "-y", "--noninteractive", app_id]
        if scope == "--system":
            cmd = ["pkexec"] + cmd

        def done(r):
            self.busy.pop(app_id, None)
            self.toast(f"Removed {nice}" if r and r.returncode == 0 else f"Couldn't remove {nice}")
            self.refresh_installed(lambda: self.notify(app_id))
        in_background(lambda: run(cmd, 300), done)

    def open_app(self, app_id):
        subprocess.Popen(["flatpak", "run", app_id], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.wrenlinux.Store", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.restyle = wrenlib.setup_app_style(CSS)
        wrenlib.keep_warm(self)

    def do_activate(self):
        (self.get_active_window() or Window(self)).present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
