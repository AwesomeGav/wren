#!/usr/bin/env python3
"""Floe Login: the sign-in screen. Picks the last (or only) user automatically,
so signing in is just typing the password.

Talks to greetd over its IPC socket ($GREETD_SOCK). Set WREN_GREETER_DEMO=1 to run
without greetd (password "wren" works), for screenshots and testing.
"""
import glob
import json
import os
import pwd
import re
import socket
import struct
import subprocess
import sys
import threading

LAST_USER = "/var/cache/wren-greeter/last-user"
SESSION = ["wren-session"]
DEMO = bool(os.environ.get("WREN_GREETER_DEMO"))
BACKGROUND = "/usr/share/wren/wallpapers/silk.jpg"
NOLOGIN = ("nologin", "false", "sync", "halt", "shutdown")


# ------------------------------------------------------------------ greetd
class GreetdError(Exception):
    pass


class Greetd:
    """Minimal greetd IPC client (4-byte native-endian length + JSON)."""

    def __init__(self, path=None):
        self.path = path or os.environ.get("GREETD_SOCK")
        self.sock = None

    def _connect(self):
        if self.sock is None:
            if not self.path:
                raise GreetdError("GREETD_SOCK is not set")
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect(self.path)

    def _send(self, msg):
        self._connect()
        data = json.dumps(msg).encode()
        self.sock.sendall(struct.pack("=I", len(data)) + data)
        head = self._recv(4)
        (length,) = struct.unpack("=I", head)
        return json.loads(self._recv(length))

    def _recv(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise GreetdError("greetd closed the connection")
            buf += chunk
        return buf

    def cancel(self):
        try:
            self._send({"type": "cancel_session"})
        except Exception:
            pass

    def login(self, username, password, cmd):
        """Returns None on success, or a message to show. Starts the session on success."""
        reply = self._send({"type": "create_session", "username": username})
        answered = False
        while reply.get("type") == "auth_message":
            kind = reply.get("auth_message_type")
            if kind in ("secret", "visible") and not answered:
                answered = True
                reply = self._send({"type": "post_auth_message_response", "response": password})
            elif kind in ("info", "error"):
                reply = self._send({"type": "post_auth_message_response", "response": None})
            else:
                self.cancel()
                return "Signing in needs more than a password on this account."
        if reply.get("type") == "error":
            self.cancel()
            if reply.get("error_type") == "auth_error":
                return "Wrong password. Try again."
            return reply.get("description") or "Couldn't sign in."
        reply = self._send({"type": "start_session", "cmd": cmd, "env": []})
        if reply.get("type") == "error":
            self.cancel()
            return reply.get("description") or "Couldn't start the desktop."
        return None


def list_users():
    users = []
    for p in pwd.getpwall():
        if 1000 <= p.pw_uid < 60000 and not p.pw_shell.endswith(NOLOGIN):
            name = (p.pw_gecos or "").split(",")[0].strip() or p.pw_name
            users.append({"user": p.pw_name, "name": name})
    users.sort(key=lambda u: u["name"].lower())
    return users


def last_user():
    try:
        return open(LAST_USER).read().strip()
    except OSError:
        return ""


def save_last_user(user):
    try:
        with open(LAST_USER, "w") as f:
            f.write(user + "\n")
    except OSError:
        pass


# ------------------------------------------------------------------ UI
def main():
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, GLib, Gtk

    css = """
    window { background-color: #E6EAF1; }
    .shade { background-color: rgba(236, 241, 248, 0.10); }
    .date { font-family: IBM Plex Sans; font-size: 22px; font-weight: 500; color: #343B42; }
    .clock { font-family: IBM Plex Sans; font-size: 120px; font-weight: 300; color: #1E2328; letter-spacing: -2px; }
    .status { font-family: IBM Plex Sans, "Symbols Nerd Font"; font-size: 15px; font-weight: 600; color: #2A3242; }
    .avatar { background-color: #0F7B83; color: #FFFFFF; font-family: IBM Plex Sans;
              font-size: 15px; font-weight: 600; min-width: 34px; min-height: 34px; border-radius: 999px;
              box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.85); }
    .who { font-family: IBM Plex Sans; font-size: 17px; font-weight: 500; color: #1E2328; }
    button.whobtn { background: transparent; box-shadow: none; border: none; padding: 4px 10px; border-radius: 999px; }
    button.whobtn:hover { background: rgba(255, 255, 255, 0.25); }
    .error { font-family: IBM Plex Sans; font-size: 13px; font-weight: 600; color: #FFFFFF; background: rgba(229, 72, 77, 0.85);
             border-radius: 999px; padding: 6px 14px; }
    entry.pw { background: rgba(250, 251, 252, 0.72); color: #1E2328; border: 1px solid rgba(255, 255, 255, 0.95);
               min-height: 50px; padding: 0 20px; font-size: 15px; border-radius: 999px; outline: none;
               box-shadow: 0 8px 24px rgba(30, 40, 50, 0.16); caret-color: #0F7B83; }
    entry.pw:focus-within { border-color: #0F7B83; background: rgba(255, 255, 255, 0.86); }
    entry.pw text placeholder { color: #5D6670; }
    entry.pw image { color: #5D6670; }
    button { box-shadow: none; border: none; font-family: IBM Plex Sans; }
    .roundbtn > button { background: rgba(255, 255, 255, 0.55); color: #2A3242; min-width: 48px; min-height: 48px;
                      border-radius: 999px; border: 1px solid rgba(255, 255, 255, 0.8);
                      box-shadow: 0 6px 18px rgba(30, 45, 70, 0.18); }
    .roundbtn image, entry.pw image { -gtk-icon-size: 18px; }
    .roundbtn > button:hover { background: rgba(255, 255, 255, 0.8); }
    button.menurow { background: transparent; color: #1C2230; padding: 9px 14px; border-radius: 10px; font-size: 14px; }
    button.menurow:hover { background: rgba(15, 123, 131, 0.14); }
    .intro { opacity: 0; transform: translateY(24px);
             transition: opacity 500ms ease-out, transform 700ms cubic-bezier(0.18, 0.9, 0.28, 1.05); }
    .intro.in { opacity: 1; transform: none; }
    entry.pw { transition: transform 70ms ease-in-out, border-color 200ms ease, background-color 200ms ease; }
    entry.pw.shake-l { transform: translateX(-12px); }
    entry.pw.shake-r { transform: translateX(12px); }
    .error { transition: opacity 250ms ease; }
    popover > contents { background: rgba(255, 255, 255, 0.92); border: 1px solid rgba(255, 255, 255, 0.9);
                         border-radius: 16px; padding: 6px; box-shadow: 0 12px 32px rgba(30, 45, 70, 0.25); }
    """

    # Sharp high-resolution screens (e.g. Surface): scale everything up so it isn't tiny.
    # The login screen runs before any desktop, so it works this out from the screen itself.
    try:
        from autoscale import ui_scale
        factor = float(os.environ.get("WREN_UI_SCALE") or ui_scale())
    except Exception:
        factor = 1.0
    css = re.sub(r"(-?\d+)px", lambda m: f"{round(int(m.group(1)) * factor)}px", css)

    def S(n):
        return round(n * factor)

    users = list_users() or [{"user": "wren", "name": "Floe"}]
    chosen = next((u for u in users if u["user"] == last_user()), users[0])
    greetd = None if DEMO else Greetd()

    app = Gtk.Application(application_id="org.wrenlinux.Greeter")

    def activate(app):
        provider = Gtk.CssProvider()
        provider.load_from_string(css)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        settings = Gtk.Settings.get_default()
        settings.set_property("gtk-application-prefer-dark-theme", False)

        win = Gtk.ApplicationWindow(application=app, title="Floe Login")
        overlay = Gtk.Overlay()
        bg = Gtk.Picture.new_for_filename(BACKGROUND)
        bg.set_content_fit(Gtk.ContentFit.COVER)
        bg.set_can_shrink(True)
        overlay.set_child(bg)
        shade = Gtk.Box()
        shade.add_css_class("shade")
        overlay.add_overlay(shade)

        # Date and big time, top left
        corner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.START, valign=Gtk.Align.START,
                         margin_start=S(56), margin_top=S(44))
        date = Gtk.Label(xalign=0)
        date.add_css_class("date")
        clock = Gtk.Label(xalign=0, margin_top=S(-6))
        clock.add_css_class("clock")
        corner.append(date)
        corner.append(clock)
        overlay.add_overlay(corner)

        # Wi-Fi and battery, top right
        status = Gtk.Label(halign=Gtk.Align.END, valign=Gtk.Align.START, margin_end=S(44), margin_top=S(40))
        status.add_css_class("status")
        overlay.add_overlay(status)

        # Name and password, bottom middle
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                         halign=Gtk.Align.CENTER, valign=Gtk.Align.END, margin_bottom=S(64))
        head = Gtk.Box(spacing=10)
        avatar = Gtk.Label()
        avatar.add_css_class("avatar")
        who = Gtk.Label()
        who.add_css_class("who")
        head.append(avatar)
        head.append(who)
        if len(users) > 1:
            switch = Gtk.MenuButton(child=head, halign=Gtk.Align.CENTER, tooltip_text="Switch user")
            switch.add_css_class("whobtn")
            column.append(switch)
        else:
            switch = None
            head.set_halign(Gtk.Align.CENTER)
            column.append(head)
        entry = Gtk.PasswordEntry(show_peek_icon=True, placeholder_text="Enter password")
        entry.add_css_class("pw")
        entry.set_size_request(S(400), -1)
        column.append(entry)
        message = Gtk.Label(halign=Gtk.Align.CENTER, wrap=True, visible=False)
        message.add_css_class("error")
        column.append(message)
        overlay.add_overlay(column)

        # Power, bottom right
        power = Gtk.MenuButton(icon_name="system-shutdown-symbolic", tooltip_text="Power",
                               halign=Gtk.Align.END, valign=Gtk.Align.END, margin_end=S(32), margin_bottom=S(32))
        power.add_css_class("roundbtn")
        pmenu = Gtk.Popover()
        pbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for label, action in (("Restart", "reboot"), ("Shut Down", "poweroff")):
            b = Gtk.Button(label=label)
            b.add_css_class("menurow")
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda _b, a=action: None if DEMO else subprocess.Popen(["systemctl", a]))
            pbox.append(b)
        pmenu.set_child(pbox)
        power.set_popover(pmenu)
        overlay.add_overlay(power)
        win.set_child(overlay)
        go = entry  # sensitivity is toggled together while signing in

        def show_user(u):
            nonlocal chosen
            chosen = u
            avatar.set_text((u["name"][:1] or "?").upper())
            who.set_text(u["name"])
            message.set_visible(False)
            entry.set_text("")
            entry.grab_focus()

        if switch is not None:
            popover = Gtk.Popover()
            plist = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            for u in users:
                b = Gtk.Button(label=u["name"])
                b.add_css_class("menurow")
                b.get_child().set_xalign(0)
                b.connect("clicked", lambda _b, u=u: (popover.popdown(), show_user(u)))
                plist.append(b)
            popover.set_child(plist)
            switch.set_popover(popover)

        def status_text():
            parts = []
            try:
                for dev in os.listdir("/sys/class/net"):
                    if os.path.isdir(f"/sys/class/net/{dev}/wireless") and \
                            open(f"/sys/class/net/{dev}/operstate").read().strip() == "up":
                        parts.append("\U000f05a9")
                        break
            except OSError:
                pass
            for bat in sorted(glob.glob("/sys/class/power_supply/BAT*")):
                try:
                    cap = open(f"{bat}/capacity").read().strip()
                    charging = open(f"{bat}/status").read().strip() == "Charging"
                    parts.append(("\U000f0084 " if charging else "\U000f0079 ") + cap + "%")
                    break
                except OSError:
                    pass
            return "    ".join(parts)

        def tick():
            now = GLib.DateTime.new_now_local()
            clock.set_text(now.format("%-I:%M"))
            date.set_text(now.format("%A, %B %-d"))
            status.set_text(status_text())
            return True
        tick()
        GLib.timeout_add_seconds(5, tick)

        def shake():
            steps = ["shake-l", "shake-r", "shake-l", "shake-r", None]

            def step(i=0):
                entry.remove_css_class("shake-l")
                entry.remove_css_class("shake-r")
                if i < len(steps) and steps[i]:
                    entry.add_css_class(steps[i])
                    GLib.timeout_add(70, step, i + 1)
                return False
            step()

        def finish(result):
            if result is None:
                save_last_user(chosen["user"])
                app.quit()
                return False
            message.set_text(result)
            message.set_visible(True)
            shake()
            entry.set_sensitive(True)
            go.set_sensitive(True)
            entry.set_text("")
            entry.grab_focus()
            return False

        def submit(*_):
            password = entry.get_text()
            if not password:
                return
            entry.set_sensitive(False)
            go.set_sensitive(False)
            message.set_visible(False)

            def work():
                if DEMO:
                    import time
                    time.sleep(0.8)
                    result = None if password == "wren" else "Wrong password. Try again."
                else:
                    try:
                        result = greetd.login(chosen["user"], password, SESSION)
                    except (OSError, GreetdError, ValueError) as e:
                        result = f"Couldn't reach the login service ({e})."
                GLib.idle_add(finish, result)
            threading.Thread(target=work, daemon=True).start()

        entry.connect("activate", submit)
        show_user(chosen)
        # Clock and password box glide in
        for i, w in enumerate((corner, status, column, power)):
            w.add_css_class("intro")
            GLib.timeout_add(120 + i * 90, lambda w=w: w.add_css_class("in") or False)
        win.fullscreen()
        win.present()
        entry.grab_focus()

    app.connect("activate", activate)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
