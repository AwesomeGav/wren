#!/usr/bin/env python3
"""Wren Login: the sign-in screen. Picks the last (or only) user automatically,
so signing in is just typing the password.

Talks to greetd over its IPC socket ($GREETD_SOCK). Set WREN_GREETER_DEMO=1 to run
without greetd (password "wren" works), for screenshots and testing.
"""
import json
import os
import pwd
import socket
import struct
import subprocess
import sys
import threading

LAST_USER = "/var/cache/wren-greeter/last-user"
SESSION = ["labwc"]
DEMO = bool(os.environ.get("WREN_GREETER_DEMO"))
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
    window { background-color: #141210; }
    .shade { background-color: rgba(12, 10, 9, 0.45); }
    .clock { font-family: Inter; font-size: 96px; font-weight: 300; color: #F1EBE3; }
    .date { font-family: Inter; font-size: 18px; color: #C8BEB2; }
    .card { background-color: rgba(28, 25, 22, 0.94); border: 1px solid #3A342E;
            padding: 28px 30px; box-shadow: 0 18px 48px rgba(0, 0, 0, 0.55); }
    .avatar { background: #E0894A; color: #1A120B; font-family: Inter; font-size: 30px;
              font-weight: 800; min-width: 72px; min-height: 72px; }
    .who { font-family: Inter; font-size: 20px; font-weight: 700; color: #F1EBE3; }
    .hint { font-family: Inter; font-size: 12px; color: #8A8178; }
    .error { font-family: Inter; font-size: 13px; color: #F08A78; }
    entry.pw { background: #141210; color: #F1EBE3; border: 1px solid #3A342E; min-height: 44px;
               padding: 0 12px; font-size: 15px; border-radius: 0; box-shadow: none; outline: none; }
    entry.pw:focus-within { border-color: #E0894A; }
    button { border-radius: 0; box-shadow: none; border: none; font-family: Inter; }
    button.go { background: #E0894A; color: #1A120B; min-width: 44px; min-height: 44px; }
    button.go:hover { background: #EC9A5E; }
    button.go:disabled { background: #5A3D27; color: #1A120B; }
    button.flatlink { background: transparent; color: #A89F94; padding: 4px 8px; font-size: 12px; }
    button.flatlink:hover { color: #F1EBE3; background: rgba(255, 240, 225, 0.06); }
    button.power { background: rgba(28, 25, 22, 0.85); color: #F1EBE3; padding: 10px 16px;
                   border: 1px solid #3A342E; font-size: 13px; }
    button.power:hover { background: #C4513F; color: #FFFFFF; border-color: #C4513F; }
    button.userrow { background: transparent; color: #F1EBE3; padding: 8px 10px; }
    button.userrow:hover { background: rgba(224, 137, 74, 0.15); }
    popover > contents { background: #26221E; border: 1px solid #3A342E; border-radius: 0; padding: 4px; }
    """

    users = list_users() or [{"user": "wren", "name": "Wren"}]
    chosen = next((u for u in users if u["user"] == last_user()), users[0])
    greetd = None if DEMO else Greetd()

    app = Gtk.Application(application_id="org.wrenlinux.Greeter")

    def activate(app):
        provider = Gtk.CssProvider()
        provider.load_from_string(css)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        settings = Gtk.Settings.get_default()
        settings.set_property("gtk-application-prefer-dark-theme", True)

        win = Gtk.ApplicationWindow(application=app, title="Wren Login")
        overlay = Gtk.Overlay()
        bg = Gtk.Picture.new_for_filename("/usr/share/wren/wallpaper.jpg")
        bg.set_content_fit(Gtk.ContentFit.COVER)
        bg.set_can_shrink(True)
        overlay.set_child(bg)
        shade = Gtk.Box()
        shade.add_css_class("shade")
        overlay.add_overlay(shade)

        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0,
                         halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        clock = Gtk.Label()
        clock.add_css_class("clock")
        date = Gtk.Label(margin_bottom=40)
        date.add_css_class("date")
        column.append(clock)
        column.append(date)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        card.add_css_class("card")
        card.set_size_request(380, -1)
        head = Gtk.Box(spacing=16)
        avatar = Gtk.Label()
        avatar.add_css_class("avatar")
        head.append(avatar)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        who = Gtk.Label(xalign=0)
        who.add_css_class("who")
        names.append(who)
        switch = Gtk.MenuButton(label="Not you?", halign=Gtk.Align.START, visible=len(users) > 1)
        switch.add_css_class("flatlink")
        names.append(switch)
        head.append(names)
        card.append(head)

        row = Gtk.Box(spacing=0)
        entry = Gtk.PasswordEntry(show_peek_icon=True, hexpand=True, placeholder_text="Password")
        entry.add_css_class("pw")
        go = Gtk.Button(icon_name="go-next-symbolic", tooltip_text="Sign in")
        go.add_css_class("go")
        row.append(entry)
        row.append(go)
        card.append(row)
        message = Gtk.Label(xalign=0, wrap=True, visible=False)
        message.add_css_class("error")
        card.append(message)
        column.append(card)
        overlay.add_overlay(column)

        power = Gtk.Box(spacing=8, halign=Gtk.Align.END, valign=Gtk.Align.END, margin_end=24, margin_bottom=24)
        for label, action in (("Restart", "reboot"), ("Shut Down", "poweroff")):
            b = Gtk.Button(label=label)
            b.add_css_class("power")
            b.connect("clicked", lambda _b, a=action: None if DEMO else subprocess.Popen(["systemctl", a]))
            power.append(b)
        overlay.add_overlay(power)
        win.set_child(overlay)

        def show_user(u):
            nonlocal chosen
            chosen = u
            avatar.set_text((u["name"][:1] or "?").upper())
            who.set_text(u["name"])
            message.set_visible(False)
            entry.set_text("")
            entry.grab_focus()

        popover = Gtk.Popover()
        plist = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for u in users:
            b = Gtk.Button(label=u["name"])
            b.add_css_class("userrow")
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda _b, u=u: (popover.popdown(), show_user(u)))
            plist.append(b)
        popover.set_child(plist)
        switch.set_popover(popover)

        def tick():
            now = GLib.DateTime.new_now_local()
            clock.set_text(now.format("%-I:%M"))
            date.set_text(now.format("%A, %B %-d"))
            return True
        tick()
        GLib.timeout_add_seconds(5, tick)

        def finish(result):
            if result is None:
                save_last_user(chosen["user"])
                app.quit()
                return False
            message.set_text(result)
            message.set_visible(True)
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
        go.connect("clicked", submit)
        show_user(chosen)
        win.fullscreen()
        win.present()
        entry.grab_focus()

    app.connect("activate", activate)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
