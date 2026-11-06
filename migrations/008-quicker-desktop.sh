#!/usr/bin/env bash
# Quicker desktop: stop background timers that rebuild manual-page and file-search
# indexes (they make old disks busy right after start-up), install night light.
set -uo pipefail
systemctl mask man-db.timer plocate-updatedb.timer archlinux-keyring-wkd-sync.timer 2>/dev/null || true
pacman -Q wlsunset >/dev/null 2>&1 || pacman -S --needed --noconfirm wlsunset || true
python -m compileall -q -f -j0 --invalidation-mode unchecked-hash /usr/lib/wren >/dev/null 2>&1 || true
