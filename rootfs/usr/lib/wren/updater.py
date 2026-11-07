#!/usr/bin/env python3
"""Floe Software Update: checks GitHub for a newer Floe release and installs it."""
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

UPDATE = "/usr/local/bin/wren-update"
LOGO = "/usr/share/wren/logo-256.png"
CACHE = os.path.expanduser("~/.cache/wren/update-available")

CSS = """
.title { font-size: 24px; font-weight: 600; }
.dim { color: alpha(currentColor, 0.7); }
.big-button { padding: 10px 26px; border-radius: 10px; font-weight: 600; }
.error-text { color: #DC2626; }
progressbar trough, progressbar progress { min-height: 10px; border-radius: 999px; }
"""


def current_build():
    try:
        for line in open("/etc/wren-release"):
            if line.startswith("WREN_BUILD="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return "0"


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Software Update", default_width=480, default_height=460)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=28, margin_bottom=28,
                      margin_start=32, margin_end=32, valign=Gtk.Align.CENTER, vexpand=True)
        logo = Gtk.Image.new_from_file(LOGO)
        logo.set_pixel_size(84)
        box.append(logo)
        self.title = Gtk.Label(label="Software Update", wrap=True, justify=Gtk.Justification.CENTER)
        self.title.add_css_class("title")
        box.append(self.title)
        self.status = Gtk.Label(label="Checking for updates…", wrap=True, justify=Gtk.Justification.CENTER)
        self.status.add_css_class("dim")
        box.append(self.status)
        self.bar = Gtk.ProgressBar(visible=False, margin_top=6)
        box.append(self.bar)
        self.button = Gtk.Button(label="Check Again", halign=Gtk.Align.CENTER, margin_top=8)
        self.button.add_css_class("big-button")
        self.button.connect("clicked", self.on_button)
        box.append(self.button)
        self.details = Gtk.Expander(label="Details", visible=False)
        self.log = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                wrap_mode=Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow(min_content_height=140)
        scroll.set_child(self.log)
        self.details.set_child(scroll)
        box.append(self.details)

        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar(show_title=False))
        view.set_content(box)
        self.set_content(view)
        self.mode = "check"
        self.busy = False
        self.connect("close-request", lambda *_: self.busy)
        self.check()

    def set_button(self, text, mode, suggested=False):
        self.mode = mode
        self.button.set_label(text)
        self.button.set_visible(True)
        if suggested:
            self.button.add_css_class("suggested-action")
        else:
            self.button.remove_css_class("suggested-action")

    def on_button(self, *_):
        if self.mode == "check":
            self.check()
        elif self.mode == "install":
            self.install()
        elif self.mode == "restart":
            subprocess.Popen(["systemctl", "reboot"])

    def check(self):
        self.status.remove_css_class("error-text")
        self.status.set_text("Checking for updates…")
        self.button.set_visible(False)

        def work():
            try:
                return subprocess.run([UPDATE, "--check"], capture_output=True, text=True, timeout=40).stdout.strip()
            except Exception:
                return "offline"

        def done(result):
            here = current_build()
            if result.startswith("available"):
                tag = result.split()[1]
                self.title.set_text("An update is ready")
                self.status.set_text(f"Floe {tag.replace('build-', 'build ')} is available. You have build {here}.\n"
                                     "This also installs the latest system and app updates.")
                self.set_button("Install Update", "install", suggested=True)
            elif result.startswith("current"):
                self.title.set_text("Floe is up to date")
                self.status.set_text(f"You have the latest version (build {here}).")
                self.set_button("Check Again", "check")
                try:
                    os.remove(CACHE)
                except OSError:
                    pass
            else:
                self.title.set_text("Couldn't check for updates")
                self.status.set_text("Make sure you're connected to the internet, then try again.")
                self.set_button("Try Again", "check")
            return False
        threading.Thread(target=lambda: GLib.idle_add(done, work()), daemon=True).start()

    def install(self):
        self.busy = True
        self.button.set_visible(False)
        self.bar.set_visible(True)
        self.bar.set_fraction(0)
        self.details.set_visible(True)
        self.title.set_text("Updating Floe")
        self.status.set_text("Waiting for your password…")
        try:
            proc = subprocess.Popen(["pkexec", UPDATE, "--apply"], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1)
        except OSError as e:
            self.finish(False, str(e))
            return
        threading.Thread(target=self.watch, args=(proc,), daemon=True).start()

    def watch(self, proc):
        error = None
        for line in proc.stdout:
            line = line.rstrip("\n")
            m = re.match(r"^@@ (\d+) (.*)$", line)
            if m:
                GLib.idle_add(self.progress, int(m.group(1)), m.group(2))
            elif line.startswith("@@ERROR"):
                error = line[7:].strip()
            else:
                GLib.idle_add(self.append, line)
        code = proc.wait()
        if code == 0:
            GLib.idle_add(self.progress, 99, "Updating apps from the App Store…")
            try:
                subprocess.run(["flatpak", "update", "--user", "-y", "--noninteractive"],
                               capture_output=True, timeout=1800)
            except Exception:
                pass
        if code in (126, 127) and not error:
            error = "The update was cancelled."
        GLib.idle_add(self.finish, code == 0, error or f"The update stopped (code {code}).")

    def append(self, text):
        buf = self.log.get_buffer()
        buf.insert(buf.get_end_iter(), text + "\n")

    def progress(self, pct, msg):
        self.bar.set_fraction(pct / 100)
        self.status.set_text(msg)

    def finish(self, success, error):
        self.busy = False
        if success:
            try:
                os.remove(CACHE)
            except OSError:
                pass
            self.title.set_text("Update installed")
            self.status.set_text("Restart your computer to finish updating.")
            self.bar.set_fraction(1)
            self.set_button("Restart Now", "restart", suggested=True)
        else:
            self.title.set_text("Update didn't finish")
            self.status.set_text(error)
            self.status.add_css_class("error-text")
            self.details.set_expanded(True)
            self.set_button("Try Again", "check")
        return False


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.wrenlinux.Update", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.restyle = wrenlib.setup_app_style(CSS)

    def do_activate(self):
        (self.get_active_window() or Window(self)).present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
