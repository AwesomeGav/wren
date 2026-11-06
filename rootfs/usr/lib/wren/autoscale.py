#!/usr/bin/env python3
"""Pick a sensible scale for sharp, high-resolution screens (like a Surface or a 4K laptop)
so text and apps aren't tiny. Only used until a scale is chosen in Settings > Display."""
import json
import subprocess


def scale_for(width_px, width_mm):
    if not width_mm or width_mm < 100:  # projectors and unknown sizes report 0
        return 1.0
    dpi = width_px * 25.4 / width_mm
    for limit, scale in ((250, 2.0), (210, 1.75), (175, 1.5), (140, 1.25)):
        if dpi >= limit:
            return scale
    return 1.0


def ui_scale():
    """Scale factor for the first screen (used by the login screen, which runs before any desktop)."""
    try:
        for card in sorted(__import__("glob").glob("/sys/class/drm/card*-*/")):
            if open(card + "status").read().strip() != "connected":
                continue
            edid = open(card + "edid", "rb").read()
            modes = open(card + "modes").read().split()
            if len(edid) < 128 or not modes:
                continue
            w_px = int(modes[0].split("x")[0])
            # Detailed timing descriptor: image size in mm
            d = edid[54:72]
            w_mm = d[12] | ((d[14] & 0xF0) << 4)
            if not w_mm:
                w_mm = edid[21] * 10
            return scale_for(w_px, w_mm)
    except (OSError, ValueError, IndexError):
        pass
    return 1.0


def main():
    try:
        outputs = json.loads(subprocess.run(["wlr-randr", "--json"], capture_output=True, text=True,
                                            timeout=5).stdout or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return
    for out in outputs:
        if not out.get("enabled", True):
            continue
        mode = next((m for m in out.get("modes", []) if m.get("current")), None)
        size = out.get("physical_size") or {}
        if not mode:
            continue
        want = scale_for(mode["width"], size.get("width", 0))
        if abs(want - float(out.get("scale", 1.0))) > 0.01:
            subprocess.run(["wlr-randr", "--output", out["name"], "--scale", str(want)],
                           capture_output=True, timeout=5)


if __name__ == "__main__":
    main()
