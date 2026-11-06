#!/usr/bin/env bash
# Battery saver and longer battery life: Wren's TLP settings take effect now,
# kernel watchdog wake-ups are turned off (boot menu rebuilt).
set -uo pipefail
pacman -Q iw >/dev/null 2>&1 || pacman -S --needed --noconfirm iw || true
systemctl enable tlp.service 2>/dev/null || true
tlp start >/dev/null 2>&1 || true
bash /usr/lib/wren/setup-boot-splash.sh --rebuild || true
