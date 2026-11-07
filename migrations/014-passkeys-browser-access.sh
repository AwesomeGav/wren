#!/usr/bin/env bash
# Floe Passkeys: let browsers open the built-in security key, and restart it so
# the new version (with its journal messages) is the one running.
set -uo pipefail
udevadm control --reload 2>/dev/null || true
systemctl daemon-reload
systemctl enable floe-passkeys.service 2>/dev/null || true
systemctl restart floe-passkeys.service 2>/dev/null || true
sleep 1
udevadm trigger --subsystem-match=hidraw 2>/dev/null || true
