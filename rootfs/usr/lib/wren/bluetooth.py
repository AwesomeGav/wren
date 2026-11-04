#!/usr/bin/env python3
"""Wren Bluetooth: turn Bluetooth on or off, pair new devices, connect and forget them.

Talks to BlueZ over D-Bus. Set WREN_BT_DEMO=1 to show sample devices (for screenshots).
"""
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

BLUEZ = "org.bluez"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
BATTERY = "org.bluez.Battery1"
PROPS = "org.freedesktop.DBus.Properties"
AGENT_PATH = "/org/wrenlinux/bluetooth/agent"
NOISY = {"RSSI", "ManufacturerData", "ServiceData", "TxPower", "AdvertisingFlags", "AdvertisingData"}
DEMO = bool(os.environ.get("WREN_BT_DEMO"))

AGENT_XML = """<node><interface name="org.bluez.Agent1">
  <method name="Release"/>
  <method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
  <method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
  <method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
  <method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
  <method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
  <method name="RequestAuthorization"><arg type="o" direction="in"/></method>
  <method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
  <method name="Cancel"/>
</interface></node>"""

CSS = """
.bt-window { background-color: #181512; }
.bt-hero { padding: 22px 24px 18px 24px; background-color: #1C1916; border-bottom: 1px solid #2E2924; }
.bt-hero-title { font-size: 22px; font-weight: 800; }
.bt-hero-sub { color: #A89F94; }
.bt-section { font-size: 11px; font-weight: 800; letter-spacing: 0.12em; color: #8A8178;
              margin: 18px 24px 8px 24px; }
.bt-list { background-color: transparent; }
.bt-list > row { padding: 0; border-left: 3px solid transparent; border-bottom: 1px solid #2A2520; }
.bt-list > row:hover { background-color: rgba(255, 240, 225, 0.04); }
.bt-list > row.connected { border-left-color: #E0894A; background-color: rgba(224, 137, 74, 0.08); }
.bt-row { padding: 12px 20px 12px 18px; }
.bt-icon { min-width: 40px; min-height: 40px; background-color: #26221E; color: #D9D1C7; }
.connected .bt-icon { background-color: #E0894A; color: #1A120B; }
.bt-name { font-weight: 700; }
.bt-status { color: #A89F94; font-size: 12px; }
.connected .bt-status { color: #F0A06A; }
.bt-btn { padding: 6px 14px; font-weight: 700; }
.bt-btn.primary { background-color: #E0894A; color: #1A120B; }
.bt-btn.primary:hover { background-color: #EC9A5E; }
.bt-empty { color: #8A8178; padding: 18px 24px; }
.bt-power { padding: 6px 16px; font-weight: 800; }
.bt-power.on { background-color: #E0894A; color: #1A120B; }
.bt-power.on:hover { background-color: #EC9A5E; }
"""


def friendly_error(err):
    msg = str(err)
    if "Blocked" in msg or "NotReady" in msg:
        return "Bluetooth is turned off."
    if "AuthenticationCanceled" in msg or "Canceled" in msg or "Rejected" in msg:
        return "Pairing was cancelled."
    if "AuthenticationFailed" in msg:
        return "Pairing failed. Check the code and try again."
    if "page-timeout" in msg or "Timeout" in msg or "AuthenticationTimeout" in msg:
        return "The device didn't respond. Make sure it's on and close by."
    if "profile-unavailable" in msg:
        return "This kind of device can't be connected here."
    if "InProgress" in msg:
        return "Already working on it…"
    return "That didn't work. Try again."


def device_icon(name):
    return {
        "audio-headset": "audio-headset-symbolic", "audio-headphones": "audio-headphones-symbolic",
        "audio-card": "audio-speakers-symbolic", "input-mouse": "input-mouse-symbolic",
        "input-keyboard": "input-keyboard-symbolic", "input-gaming": "input-gaming-symbolic",
        "input-tablet": "input-tablet-symbolic", "phone": "phone-symbolic",
        "computer": "computer-symbolic", "printer": "printer-symbolic",
        "camera-photo": "camera-photo-symbolic", "camera-video": "camera-video-symbolic",
    }.get(name or "", "bluetooth-active-symbolic")


class BlueZ:
    """Small helper around the BlueZ D-Bus API."""

    def __init__(self, changed):
        self.changed = changed
        self.bus = None
        self.manager = None
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            self.manager = Gio.DBusObjectManagerClient.new_for_bus_sync(
                Gio.BusType.SYSTEM, Gio.DBusObjectManagerClientFlags.NONE, BLUEZ, "/", None, None, None)
        except GLib.Error:
            return
        for sig in ("object-added", "object-removed", "interface-added", "interface-removed"):
            self.manager.connect(sig, lambda *_: self.changed())
        self.manager.connect("interface-proxy-properties-changed", self._props_changed)
        self.manager.connect("notify::name-owner", lambda *_: self.changed())

    def _props_changed(self, _mgr, _obj, _proxy, changed, _invalidated):
        keys = set(changed.keys()) if changed is not None else set()
        if not keys or not keys <= NOISY:
            self.changed()

    @staticmethod
    def _get(proxy, name, default=None):
        v = proxy.get_cached_property(name) if proxy else None
        return v.unpack() if v is not None else default

    def adapter(self):
        if not self.manager:
            return None
        for obj in self.manager.get_objects():
            proxy = obj.get_interface(ADAPTER)
            if proxy:
                return {"path": obj.get_object_path(), "powered": self._get(proxy, "Powered", False),
                        "discovering": self._get(proxy, "Discovering", False),
                        "alias": self._get(proxy, "Alias", "this computer")}
        return None

    def devices(self):
        out = []
        if not self.manager:
            return out
        for obj in self.manager.get_objects():
            d = obj.get_interface(DEVICE)
            if not d:
                continue
            name = self._get(d, "Name")
            alias = self._get(d, "Alias")
            bat = obj.get_interface(BATTERY)
            out.append({
                "path": obj.get_object_path(), "name": alias or name, "named": bool(name),
                "icon": self._get(d, "Icon"), "paired": self._get(d, "Paired", False),
                "connected": self._get(d, "Connected", False), "rssi": self._get(d, "RSSI", -999),
                "battery": self._get(bat, "Percentage") if bat else None,
            })
        return out

    def call(self, path, iface, method, args, done, timeout=60000):
        if not self.bus:
            return
        def finish(conn, res):
            try:
                conn.call_finish(res)
                done(None)
            except GLib.Error as e:
                done(e)
        self.bus.call(BLUEZ, path, iface, method, args, None, Gio.DBusCallFlags.NONE, timeout, None, finish)

    def set_prop(self, path, iface, name, variant, done):
        self.call(path, PROPS, "Set", GLib.Variant("(ssv)", (iface, name, variant)), done, 15000)


class DemoBlueZ:
    """Sample data for screenshots."""

    def __init__(self, changed):
        self.changed = changed
        self.powered = True
        self.devs = [
            {"path": "/d/1", "name": "Pixel Buds Pro", "named": True, "icon": "audio-headset", "paired": True,
             "connected": True, "rssi": -40, "battery": 80},
            {"path": "/d/2", "name": "MX Master 3S", "named": True, "icon": "input-mouse", "paired": True,
             "connected": False, "rssi": -60, "battery": None},
            {"path": "/d/3", "name": "JBL Flip 6", "named": True, "icon": "audio-card", "paired": False,
             "connected": False, "rssi": -55, "battery": None},
            {"path": "/d/4", "name": "Galaxy S24", "named": True, "icon": "phone", "paired": False,
             "connected": False, "rssi": -70, "battery": None},
        ]

    def adapter(self):
        return {"path": "/a", "powered": self.powered, "discovering": self.powered, "alias": "gavin-wren"}

    def devices(self):
        return self.devs if self.powered else []

    def call(self, path, iface, method, args, done, timeout=0):
        for d in self.devs:
            if d["path"] == path:
                if method == "Connect":
                    d["connected"] = True
                elif method == "Disconnect":
                    d["connected"] = False
                elif method == "Pair":
                    d["paired"] = True
        if method == "RemoveDevice":
            self.devs = [d for d in self.devs if d["path"] != args.unpack()[0]]
        GLib.timeout_add(600, lambda: done(None) or False)

    def set_prop(self, path, iface, name, variant, done):
        if name == "Powered":
            self.powered = variant.unpack()
        GLib.timeout_add(300, lambda: done(None) or False)


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Bluetooth", default_width=480, default_height=640)
        self.add_css_class("bt-window")
        self.busy = set()
        self.pending = False
        self.discovery_asked = False
        self.agent_id = None
        self.dialog = None
        self.bt = (DemoBlueZ if DEMO else BlueZ)(self.queue_refresh)

        header = Adw.HeaderBar(show_title=False)
        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self.toasts)
        self.set_content(view)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        self.toasts.set_child(self.stack)

        # Hero strip with power button
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        hero = Gtk.Box(spacing=16)
        hero.add_css_class("bt-hero")
        icon = Gtk.Image.new_from_icon_name("bluetooth-active-symbolic")
        icon.set_pixel_size(28)
        hero.append(icon)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        text.append(self._label("Bluetooth", "bt-hero-title"))
        self.hero_sub = self._label("", "bt-hero-sub")
        text.append(self.hero_sub)
        hero.append(text)
        self.power = Gtk.Button(valign=Gtk.Align.CENTER)
        self.power.add_css_class("bt-power")
        self.power.connect("clicked", lambda *_: self.toggle_power())
        hero.append(self.power)
        page.append(hero)

        self.body = Gtk.Stack(vexpand=True)
        page.append(self.body)

        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        lists = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.mine_title = self._label("MY DEVICES", "bt-section")
        self.mine = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.mine.add_css_class("bt-list")
        nearby_head = Gtk.Box(spacing=8)
        nearby_head.append(self._label("NEARBY", "bt-section"))
        self.spinner = Gtk.Spinner(valign=Gtk.Align.CENTER, margin_top=10)
        nearby_head.append(self.spinner)
        self.nearby = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.nearby.add_css_class("bt-list")
        self.nearby_empty = self._label("Looking for devices… Put the device you want to add in pairing mode.",
                                        "bt-empty", wrap=True)
        for w in (self.mine_title, self.mine, nearby_head, self.nearby, self.nearby_empty):
            lists.append(w)
        scroll.set_child(lists)
        self.body.add_named(scroll, "on")

        off = Adw.StatusPage(icon_name="bluetooth-disabled-symbolic", title="Bluetooth is off",
                             description="Turn it on to use wireless headphones, mice, keyboards and more.")
        self.body.add_named(off, "off")
        self.stack.add_named(page, "main")

        none = Adw.StatusPage(icon_name="bluetooth-disabled-symbolic", title="No Bluetooth found",
                              description="This computer doesn't seem to have Bluetooth, or it's switched off "
                                          "with a hardware switch or in the BIOS.")
        self.stack.add_named(none, "none")

        self.connect("close-request", self.on_close)
        self.register_agent()
        self.refresh()

    @staticmethod
    def _label(text, css, **kw):
        lbl = Gtk.Label(label=text, xalign=0, **kw)
        lbl.add_css_class(css)
        return lbl

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=4))

    # ------------------------------------------------------------ refresh
    def queue_refresh(self):
        if not self.pending:
            self.pending = True
            GLib.timeout_add(150, self.refresh)

    def refresh(self):
        self.pending = False
        adapter = self.bt.adapter()
        if not adapter:
            self.stack.set_visible_child_name("none")
            return False
        self.stack.set_visible_child_name("main")
        self.adapter_path = adapter["path"]
        on = adapter["powered"]
        self.power.set_label("On" if on else "Off")
        if on:
            self.power.add_css_class("on")
        else:
            self.power.remove_css_class("on")
        self.hero_sub.set_text(f"Visible to nearby devices as “{adapter['alias']}”" if on else "Turned off")
        self.body.set_visible_child_name("on" if on else "off")
        if not on:
            self.discovery_asked = False
            self.spinner.stop()
            return False
        if not adapter["discovering"] and not self.discovery_asked:
            self.discovery_asked = True
            self.bt.call(self.adapter_path, ADAPTER, "StartDiscovery", None, lambda e: None, 10000)
        if adapter["discovering"]:
            self.spinner.start()
        else:
            self.spinner.stop()

        devices = self.bt.devices()
        mine = sorted([d for d in devices if d["paired"]], key=lambda d: (not d["connected"], d["name"].lower()))
        nearby = sorted([d for d in devices if not d["paired"] and d["named"]], key=lambda d: -(d["rssi"] or -999))
        self._fill(self.mine, mine)
        self._fill(self.nearby, nearby)
        self.mine_title.set_visible(bool(mine))
        self.mine.set_visible(bool(mine))
        self.nearby.set_visible(bool(nearby))
        self.nearby_empty.set_visible(not nearby)
        return False

    def _fill(self, listbox, devices):
        listbox.remove_all()
        for d in devices:
            listbox.append(self._row(d))

    def _row(self, d):
        row = Gtk.ListBoxRow(activatable=False)
        if d["connected"]:
            row.add_css_class("connected")
        box = Gtk.Box(spacing=14)
        box.add_css_class("bt-row")
        icon = Gtk.Image.new_from_icon_name(device_icon(d["icon"]))
        icon.set_pixel_size(20)
        icon.add_css_class("bt-icon")
        box.append(icon)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        text.append(self._label(d["name"], "bt-name", ellipsize=3))
        if d["paired"]:
            status = "Connected" if d["connected"] else "Not connected"
            if d["connected"] and d["battery"] is not None:
                status += f" · Battery {d['battery']}%"
        else:
            status = "Ready to pair"
        text.append(self._label(status, "bt-status"))
        box.append(text)

        if d["path"] in self.busy:
            spin = Gtk.Spinner(valign=Gtk.Align.CENTER)
            spin.start()
            box.append(spin)
        elif d["paired"]:
            btn = Gtk.Button(label="Disconnect" if d["connected"] else "Connect", valign=Gtk.Align.CENTER)
            btn.add_css_class("bt-btn")
            if not d["connected"]:
                btn.add_css_class("primary")
            btn.connect("clicked", lambda *_: self.connect_device(d))
            box.append(btn)
            forget = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                tooltip_text="Forget this device")
            forget.add_css_class("flat")
            forget.connect("clicked", lambda *_: self.forget(d))
            box.append(forget)
        else:
            btn = Gtk.Button(label="Pair", valign=Gtk.Align.CENTER)
            btn.add_css_class("bt-btn")
            btn.add_css_class("primary")
            btn.connect("clicked", lambda *_: self.pair(d))
            box.append(btn)
        row.set_child(box)
        return row

    # ------------------------------------------------------------ actions
    def _done(self, path, ok_msg=None, then=None):
        def finish(err):
            if err:
                self.busy.discard(path)
                self.toast(friendly_error(err))
                self.queue_refresh()
                return
            if then:
                then()
                return
            self.busy.discard(path)
            if ok_msg:
                self.toast(ok_msg)
            self.queue_refresh()
        return finish

    def toggle_power(self):
        adapter = self.bt.adapter()
        if not adapter:
            return
        want = not adapter["powered"]
        def done(err):
            if err and want and "Blocked" in str(err):
                subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True)
                self.bt.set_prop(adapter["path"], ADAPTER, "Powered", GLib.Variant("b", True),
                                 lambda e: self.toast(friendly_error(e)) if e else self.queue_refresh())
            elif err:
                self.toast(friendly_error(err))
            self.queue_refresh()
        self.bt.set_prop(adapter["path"], ADAPTER, "Powered", GLib.Variant("b", want), done)

    def connect_device(self, d):
        self.busy.add(d["path"])
        self.queue_refresh()
        method = "Disconnect" if d["connected"] else "Connect"
        self.bt.call(d["path"], DEVICE, method, None,
                     self._done(d["path"], None if d["connected"] else f"Connected to {d['name']}"))

    def pair(self, d):
        path = d["path"]
        self.busy.add(path)
        self.queue_refresh()

        def trusted():
            self.bt.call(path, DEVICE, "Connect", None, self._done(path, f"{d['name']} is ready to use"))

        def paired_ok():
            self.bt.set_prop(path, DEVICE, "Trusted", GLib.Variant("b", True), lambda _e: trusted())

        def after_pair(err):
            if err and "AlreadyExists" not in str(err):
                self.busy.discard(path)
                self.toast(friendly_error(err))
                self.queue_refresh()
            else:
                paired_ok()
        self.bt.call(path, DEVICE, "Pair", None, after_pair, 90000)

    def forget(self, d):
        dialog = Adw.AlertDialog(heading=f"Forget {d['name']}?",
                                 body="You'll need to pair it again to use it with this computer.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("forget", "Forget")
        dialog.set_response_appearance("forget", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")

        def respond(_d, r):
            if r == "forget":
                self.busy.add(d["path"])
                self.bt.call(self.adapter_path, ADAPTER, "RemoveDevice", GLib.Variant("(o)", (d["path"],)),
                             self._done(d["path"], f"Forgot {d['name']}"))
        dialog.connect("response", respond)
        dialog.present(self)

    # ------------------------------------------------------------ pairing agent
    def register_agent(self):
        if DEMO or not getattr(self.bt, "bus", None):
            return
        try:
            info = Gio.DBusNodeInfo.new_for_xml(AGENT_XML).interfaces[0]
            self.agent_id = self.bt.bus.register_object(AGENT_PATH, info, self.on_agent_call, None, None)
        except GLib.Error:
            return
        self.bt.call("/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                     GLib.Variant("(os)", (AGENT_PATH, "KeyboardDisplay")),
                     lambda err: None if err else self.bt.call(
                         "/org/bluez", "org.bluez.AgentManager1", "RequestDefaultAgent",
                         GLib.Variant("(o)", (AGENT_PATH,)), lambda e: None))

    def device_name(self, path):
        for d in self.bt.devices():
            if d["path"] == path:
                return d["name"]
        return "the device"

    def close_dialog(self):
        if self.dialog:
            self.dialog.force_close()
            self.dialog = None

    def ask(self, heading, body, ok_label, on_ok, on_cancel, entry=None):
        self.close_dialog()
        self.present()
        d = Adw.AlertDialog(heading=heading, body=body)
        if entry:
            d.set_extra_child(entry)
        d.add_response("cancel", "Cancel")
        if ok_label:
            d.add_response("ok", ok_label)
            d.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
            d.set_default_response("ok")
        d.set_close_response("cancel")

        def respond(_d, r):
            self.dialog = None
            (on_ok if r == "ok" else on_cancel)()
        d.connect("response", respond)
        self.dialog = d
        d.present(self)

    def on_agent_call(self, _conn, _sender, _path, _iface, method, params, inv):
        args = params.unpack()
        reject = lambda: inv.return_dbus_error("org.bluez.Error.Rejected", "Rejected by user")  # noqa: E731
        if method in ("Release", "RequestAuthorization", "AuthorizeService"):
            inv.return_value(None)
        elif method == "Cancel":
            self.close_dialog()
            inv.return_value(None)
        elif method == "RequestConfirmation":
            name, code = self.device_name(args[0]), f"{args[1]:06d}"
            self.ask(f"Pair with {name}?", f"Check that this code is showing on {name}:\n\n{code}",
                     "Pair", lambda: inv.return_value(None), reject)
        elif method in ("DisplayPasskey", "DisplayPinCode"):
            name = self.device_name(args[0])
            code = f"{args[1]:06d}" if method == "DisplayPasskey" else args[1]
            self.ask(f"Type this code on {name}", f"{code}\n\nThen press Enter on {name}.",
                     None, lambda: None, lambda: None)
            inv.return_value(None)
        elif method in ("RequestPinCode", "RequestPasskey"):
            name = self.device_name(args[0])
            entry = Gtk.Entry(placeholder_text="Code", input_purpose=Gtk.InputPurpose.DIGITS)

            def ok():
                text = entry.get_text().strip()
                if method == "RequestPinCode":
                    inv.return_value(GLib.Variant("(s)", (text,)))
                elif text.isdigit():
                    inv.return_value(GLib.Variant("(u)", (int(text),)))
                else:
                    reject()
            self.ask(f"Enter the code for {name}", f"Type the PIN shown on {name} or in its manual.",
                     "Pair", ok, reject, entry)
        else:
            inv.return_dbus_error("org.bluez.Error.Rejected", "Unknown request")

    def on_close(self, *_):
        if not DEMO and getattr(self, "adapter_path", None) and self.bt.adapter():
            self.bt.call(self.adapter_path, ADAPTER, "StopDiscovery", None, lambda e: None, 3000)
        if self.agent_id:
            self.bt.call("/org/bluez", "org.bluez.AgentManager1", "UnregisterAgent",
                         GLib.Variant("(o)", (AGENT_PATH,)), lambda e: None, 3000)
        return False


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.wrenlinux.Bluetooth", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        (self.get_active_window() or Window(self)).present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
