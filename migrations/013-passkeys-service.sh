#!/usr/bin/env bash
# Floe Passkeys runs as a system service from start-up (no per-login helper,
# no special device permission for the signed-in person).
set -uo pipefail
rm -f /etc/udev/rules.d/70-floe-passkeys.rules
udevadm control --reload 2>/dev/null || true
modprobe uhid 2>/dev/null || true
pkill -f "passkeys --daemon" 2>/dev/null || true
systemctl daemon-reload
systemctl enable --now floe-passkeys.service || true
