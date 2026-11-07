#!/usr/bin/env bash
# Wren is now Floe: new name, start-up screen and boot menu.
set -uo pipefail
cp -f /usr/share/wren/os-release /usr/lib/os-release 2>/dev/null || true
pacman -Q ttf-ibm-plex >/dev/null 2>&1 || pacman -S --needed --noconfirm ttf-ibm-plex || true
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
# Puts the new splash into the start-up image and renames the boot entry
bash /usr/lib/wren/setup-boot-splash.sh --rebuild || true
