#!/usr/bin/env python3
"""Writes panel test variants: the current panel plus one earlier feature each,
so the screenshot test shows which feature stops Waybar from appearing."""
import json, shutil, sys
out = sys.argv[1]
base = json.load(open("rootfs/etc/xdg/wren/waybar/config.jsonc"))
old = json.load(open("tests/panel-old.jsonc"))

def write(name, cfg):
    json.dump(cfg, open(f"{out}/{name}.json", "w"), ensure_ascii=False, indent=1)

write("a-current", base)
v = dict(base, **{"margin-left": 10, "margin-right": 10, "margin-bottom": 8})
write("b-floating-margins", v)
v = json.loads(json.dumps(base))
v["modules-left"] = ["image#wren", "wlr/taskbar"]
v["image#wren"] = old["image#wren"]
write("c-logo-image", v)
v = json.loads(json.dumps(base))
v["modules-right"] = ["tray", "group/status", "clock", "custom/power"]
v["group/status"] = old["group/status"]
write("d-grouped-status", v)
write("e-old-build6", old)
shutil.copy("tests/panel-old.css", f"{out}/old.css")
