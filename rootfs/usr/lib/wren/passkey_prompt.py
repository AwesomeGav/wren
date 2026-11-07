#!/usr/bin/env python3
"""The prompt Floe Passkeys shows when a site wants to save or use a passkey.
Reads the request as JSON on stdin; prints {"pin": ..., "choice": n} or nothing."""
import json
import os
import sys
import threading

from ctypes import CDLL

CDLL("libgtk4-layer-shell.so")  # must load before GTK, or windows can't float above the desktop

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as Layer  # noqa: E402

sys.path.insert(0, "/usr/lib/wren")
import passkeys  # noqa: E402
import wrenlib  # noqa: E402

CSS = """
window.passkey { background: transparent; }
.scrim { background-color: alpha(black, 0.22); }
.card { background-color: @wren_surface; border: 1px solid @wren_border; border-radius: 20px; padding: 26px;
        box-shadow: 0 24px 60px @wren_shadow; }
.title { font-size: 20px; font-weight: 600; }
.sub { color: @wren_dim; }
.site { color: @wren_accent_text; font-weight: 600; }
.pin { min-height: 44px; font-size: 18px; border-radius: 10px; }
.err { color: #C8343A; font-weight: 500; }
.acct { border-radius: 10px; padding: 8px 10px; }
.acct:checked { background: alpha(@wren_accent, 0.10); }
.go { padding: 8px 20px; border-radius: 10px; font-weight: 600; }
"""


class Prompt(Adw.Application):
    def __init__(self, req):
        super().__init__(application_id=None)
        self.req = req
        self.answer = None
        self.tries = 0

    def do_activate(self):
        wrenlib.setup_app_style(CSS)
        win = Gtk.Window(application=self, title="Floe Passkeys")
        win.add_css_class("passkey")
        Layer.init_for_window(win)
        Layer.set_namespace(win, "floe-passkeys")
        Layer.set_layer(win, Layer.Layer.OVERLAY)
        for e in (Layer.Edge.TOP, Layer.Edge.BOTTOM, Layer.Edge.LEFT, Layer.Edge.RIGHT):
            Layer.set_anchor(win, e, True)
        Layer.set_keyboard_mode(win, Layer.KeyboardMode.EXCLUSIVE)
        Layer.set_exclusive_zone(win, -1)
        self.win = win

        scrim = Gtk.Box()
        scrim.add_css_class("scrim")
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, halign=Gtk.Align.CENTER,
                       valign=Gtk.Align.CENTER, hexpand=True, vexpand=True)
        card.add_css_class("card")
        card.set_size_request(420, -1)
        scrim.append(card)
        win.set_child(scrim)

        head = Gtk.Box(spacing=12)
        icon = Gtk.Image.new_from_icon_name("dialog-password-symbolic")
        icon.set_pixel_size(28)
        head.append(icon)
        self.title = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        self.title.add_css_class("title")
        head.append(self.title)
        card.append(head)
        self.sub = Gtk.Label(xalign=0, wrap=True, use_markup=True)
        self.sub.add_css_class("sub")
        card.append(self.sub)

        self.accounts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        card.append(self.accounts)
        self.pin = Gtk.PasswordEntry(show_peek_icon=True)
        self.pin.add_css_class("pin")
        self.pin.connect("activate", lambda *_: self.go())
        card.append(self.pin)
        self.pin2 = Gtk.PasswordEntry(show_peek_icon=True, placeholder_text="Type it again", visible=False)
        self.pin2.add_css_class("pin")
        self.pin2.connect("activate", lambda *_: self.go())
        card.append(self.pin2)
        self.err = Gtk.Label(xalign=0, wrap=True, visible=False)
        self.err.add_css_class("err")
        card.append(self.err)

        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END, margin_top=6)
        cancel = Gtk.Button(label="Cancel")
        cancel.add_css_class("go")
        cancel.connect("clicked", lambda *_: self.finish(None))
        self.ok = Gtk.Button()
        self.ok.add_css_class("go")
        self.ok.add_css_class("suggested-action")
        self.ok.connect("clicked", lambda *_: self.go())
        buttons.append(cancel)
        buttons.append(self.ok)
        card.append(buttons)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, _k, _s: kv == Gdk.KEY_Escape and (self.finish(None) or True))
        win.add_controller(keys)
        self.fill()
        win.present()
        self.pin.grab_focus()
        GLib.timeout_add_seconds(170, lambda: self.finish(None) or False)  # the site gives up after a while

    def fill(self):
        r = self.req
        site = GLib.markup_escape_text(r.get("rp", ""))
        kind = r.get("kind")
        self.choice = 0
        if kind == "create":
            self.title.set_text("Save a passkey?")
            who = r.get("user") or r.get("display") or ""
            self.sub.set_markup(f"<span weight='600'>{site}</span> wants to save a passkey"
                                + (f" for {GLib.markup_escape_text(who)}" if who else "") + " on this computer.")
            if not r.get("has_pin"):
                self.sub.set_markup(self.sub.get_label() + "\n\nFirst, choose a passkey PIN. You'll type it "
                                    "whenever you sign in with a passkey. Use at least 4 characters.")
                self.pin.set_property("placeholder-text", "New passkey PIN")
                self.pin2.set_visible(True)
            else:
                self.pin.set_property("placeholder-text", "Passkey PIN")
            self.ok.set_label("Save passkey")
        elif kind == "signin":
            self.title.set_text(f"Sign in to {r.get('rp', '')}")
            accts = r.get("accounts") or []
            if len(accts) > 1:
                self.sub.set_text("Choose an account, then enter your passkey PIN.")
                group = None
                for i, a in enumerate(accts):
                    b = Gtk.CheckButton(label=a.get("user") or a.get("display") or f"Account {i + 1}", group=group)
                    b.add_css_class("acct")
                    group = group or b
                    b.set_active(i == 0)
                    b.connect("toggled", lambda btn, i=i: btn.get_active() and setattr(self, "choice", i))
                    self.accounts.append(b)
            else:
                who = (accts[0].get("user") or accts[0].get("display")) if accts else ""
                self.sub.set_text((f"as {who}. " if who else "") + "Enter your passkey PIN to continue.")
            self.pin.set_property("placeholder-text", "Passkey PIN")
            self.ok.set_label("Sign in")
        else:  # already saved
            self.title.set_text("This passkey is already saved")
            self.sub.set_markup(f"Floe already has a passkey for this account on <span weight='600'>{site}</span>.")
            self.pin.set_visible(False)
            self.ok.set_label("OK")

    def show_error(self, text):
        self.err.set_text(text)
        self.err.set_visible(True)

    def go(self):
        kind = self.req.get("kind")
        if kind not in ("create", "signin"):
            return self.finish(None)
        pin = self.pin.get_text()
        if kind == "create" and not self.req.get("has_pin"):
            if len(pin) < 4:
                return self.show_error("Use at least 4 characters.")
            if pin != self.pin2.get_text():
                return self.show_error("Those PINs don't match.")
            passkeys.set_pin(pin)
            return self.finish({"pin": pin, "choice": 0})
        self.ok.set_sensitive(False)

        def check():
            ok = passkeys.unlock(pin) is not None
            GLib.idle_add(lambda: self.checked(ok, pin) or False)
        threading.Thread(target=check, daemon=True).start()

    def checked(self, ok, pin):
        self.ok.set_sensitive(True)
        if ok:
            return self.finish({"pin": pin, "choice": self.choice})
        self.tries += 1
        if self.tries >= 5:
            return self.finish(None)
        self.pin.set_text("")
        self.show_error("That PIN isn't right. Try again.")

    def finish(self, answer):
        self.answer = answer
        self.quit()


def main():
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        req = {}
    if os.environ.get("FLOE_PASSKEY_TEST_PIN"):  # automated tests only
        print(json.dumps({"pin": os.environ["FLOE_PASSKEY_TEST_PIN"], "choice": 0}))
        return
    app = Prompt(req)
    app.run([])
    if app.answer:
        print(json.dumps(app.answer))


if __name__ == "__main__":
    main()
