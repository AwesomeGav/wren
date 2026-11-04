#!/usr/bin/env python3
"""Wren Terminal: tabs, Wren colors, copy/paste, zoom.

  wren-terminal                       open a terminal (new window if one is running)
  wren-terminal -e COMMAND [ARGS...]  run a command in a new terminal
  wren-terminal --working-directory=DIR
"""
import os
import pwd
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Vte", "3.91")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango, Vte  # noqa: E402

FONT = "Monospace 11"
BG = "#181512"
FG = "#F1EBE3"
CURSOR = "#E0894A"
PALETTE = [
    "#26221E", "#E26D5C", "#9CC98C", "#E9C46A", "#86A8C7", "#C79BC0", "#86C2B6", "#D9D1C7",
    "#4A433C", "#F08A78", "#B2DBA3", "#F2D488", "#A3C1DC", "#DBB4D4", "#A3D8CD", "#F1EBE3",
]

CSS = """
.wren-terminal { background-color: #181512; }
vte-terminal { padding: 10px 12px; }
tabbar .box { background-color: #1C1916; }
tabbar tab { border-radius: 0; margin: 0; padding: 0 6px; min-height: 32px; }
tabbar tab:selected { background-color: #181512; box-shadow: inset 0 2px #E0894A; }
tabbar tab:not(:selected) { color: #8A8178; }
"""


def rgba(hexstr):
    c = Gdk.RGBA()
    c.parse(hexstr)
    return c


def user_shell():
    try:
        return pwd.getpwuid(os.getuid()).pw_shell or "/bin/bash"
    except KeyError:
        return os.environ.get("SHELL", "/bin/bash")


class Window(Adw.ApplicationWindow):
    def __init__(self, app, command=None, cwd=None):
        super().__init__(application=app, title="Terminal", default_width=920, default_height=580)
        self.add_css_class("wren-terminal")
        self.scale = 1.0

        self.tabs = Adw.TabView()
        self.tabs.connect("close-page", self.on_close_page)
        self.tabs.connect("notify::selected-page", lambda *_: self.on_selected())
        tabbar = Adw.TabBar(view=self.tabs, autohide=True)

        header = Adw.HeaderBar()
        new_tab = Gtk.Button(icon_name="tab-new-symbolic", tooltip_text="New tab (Ctrl+Shift+T)")
        new_tab.connect("clicked", lambda *_: self.add_tab())
        header.pack_start(new_tab)
        menu = Gio.Menu()
        menu.append("New Window", "app.new-window")
        menu.append("Zoom In", "win.zoom-in")
        menu.append("Zoom Out", "win.zoom-out")
        menu.append("Normal Size", "win.zoom-reset")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.add_top_bar(tabbar)
        view.set_content(self.tabs)
        self.set_content(view)

        for name, cb in (("zoom-in", lambda: self.zoom(1.1)), ("zoom-out", lambda: self.zoom(1 / 1.1)),
                         ("zoom-reset", lambda: self.zoom(None)), ("new-tab", self.add_tab),
                         ("close-tab", self.close_tab), ("copy", self.copy), ("paste", self.paste),
                         ("next-tab", lambda: self.cycle(1)), ("prev-tab", lambda: self.cycle(-1))):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, cb=cb: cb())
            self.add_action(action)

        self.add_tab(command=command, cwd=cwd)

    # ------------------------------------------------------------ tabs
    def add_tab(self, command=None, cwd=None):
        if not cwd:
            current = self.current_term() if hasattr(self, "tabs") else None
            cwd = self._cwd_of(current) if current else None
        term = Vte.Terminal()
        term.set_font(Pango.FontDescription.from_string(FONT))
        term.set_colors(rgba(FG), rgba(BG), [rgba(c) for c in PALETTE])
        term.set_color_cursor(rgba(CURSOR))
        term.set_color_cursor_foreground(rgba(BG))
        term.set_cursor_blink_mode(Vte.CursorBlinkMode.OFF)
        term.set_scrollback_lines(10000)
        term.set_audible_bell(False)
        term.set_mouse_autohide(True)
        term.set_font_scale(self.scale)
        term.set_hexpand(True)
        term.set_vexpand(True)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(term)
        page = self.tabs.append(scroller)
        page.set_title("Terminal")
        page.term = term
        self.tabs.set_selected_page(page)

        term.connect("child-exited", lambda *_: self.tabs.close_page(page))
        term.connect("notify::window-title", lambda t, _p: self._title(page, t))
        try:
            term.connect("window-title-changed", lambda t: self._title(page, t))
        except TypeError:
            pass

        menu = Gio.Menu()
        menu.append("Copy", "win.copy")
        menu.append("Paste", "win.paste")
        menu.append("New Tab", "win.new-tab")
        popover = Gtk.PopoverMenu(menu_model=menu, has_arrow=False)
        popover.set_parent(term)
        click = Gtk.GestureClick(button=3)
        click.connect("pressed", lambda _g, _n, x, y: (popover.set_pointing_to(Gdk.Rectangle(int(x), int(y), 1, 1)),
                                                      popover.popup()))
        term.add_controller(click)

        argv = command or [user_shell()]
        term.spawn_async(Vte.PtyFlags.DEFAULT, cwd or os.path.expanduser("~"), argv, None,
                         GLib.SpawnFlags.SEARCH_PATH, None, None, -1, None, None, None)
        term.grab_focus()
        return page

    @staticmethod
    def _cwd_of(term):
        uri = term.get_current_directory_uri() if hasattr(term, "get_current_directory_uri") else None
        if uri:
            try:
                return GLib.filename_from_uri(uri)[0]
            except GLib.Error:
                pass
        return None

    def _title(self, page, term):
        title = term.get_window_title() if hasattr(term, "get_window_title") else None
        page.set_title(title or "Terminal")
        if page is self.tabs.get_selected_page():
            self.set_title(title or "Terminal")

    def on_selected(self):
        page = self.tabs.get_selected_page()
        if page and getattr(page, "term", None):
            self.set_title(page.get_title())
            page.term.grab_focus()

    def on_close_page(self, view, page):
        view.close_page_finish(page, True)
        if view.get_n_pages() == 0:
            self.close()
        return True

    def current_term(self):
        page = self.tabs.get_selected_page()
        return getattr(page, "term", None) if page else None

    def close_tab(self):
        page = self.tabs.get_selected_page()
        if page:
            self.tabs.close_page(page)

    def cycle(self, step):
        n = self.tabs.get_n_pages()
        if n > 1:
            i = (self.tabs.get_page_position(self.tabs.get_selected_page()) + step) % n
            self.tabs.set_selected_page(self.tabs.get_nth_page(i))

    def copy(self):
        t = self.current_term()
        if t and t.get_has_selection():
            t.copy_clipboard_format(Vte.Format.TEXT)

    def paste(self):
        t = self.current_term()
        if t:
            t.paste_clipboard()

    def zoom(self, factor):
        self.scale = 1.0 if factor is None else max(0.5, min(3.0, self.scale * factor))
        for i in range(self.tabs.get_n_pages()):
            self.tabs.get_nth_page(i).term.set_font_scale(self.scale)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.wrenlinux.Terminal",
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        new_window = Gio.SimpleAction.new("new-window", None)
        new_window.connect("activate", lambda *_: Window(self).present())
        self.add_action(new_window)
        for action, keys in (("win.new-tab", ["<Ctrl><Shift>t"]), ("win.close-tab", ["<Ctrl><Shift>w"]),
                             ("win.copy", ["<Ctrl><Shift>c"]), ("win.paste", ["<Ctrl><Shift>v"]),
                             ("win.zoom-in", ["<Ctrl>plus", "<Ctrl>equal"]), ("win.zoom-out", ["<Ctrl>minus"]),
                             ("win.zoom-reset", ["<Ctrl>0"]), ("app.new-window", ["<Ctrl><Shift>n"]),
                             ("win.next-tab", ["<Ctrl>Page_Down"]), ("win.prev-tab", ["<Ctrl>Page_Up"])):
            self.set_accels_for_action(action, keys)

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        command, cwd = None, cmdline.get_cwd()
        i = 0
        while i < len(args):
            a = args[i]
            if a in ("-e", "-x", "--"):
                command = args[i + 1:] or None
                break
            if a.startswith("--working-directory="):
                cwd = a.split("=", 1)[1]
            elif a in ("--working-directory", "-w") and i + 1 < len(args):
                cwd = args[i + 1]
                i += 1
            i += 1
        if command and len(command) == 1 and " " in command[0]:
            command = ["/bin/sh", "-c", command[0]]
        Window(self, command=command, cwd=cwd).present()
        return 0


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
