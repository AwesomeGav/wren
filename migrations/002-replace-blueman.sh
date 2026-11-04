#!/usr/bin/env bash
# Wren has its own Bluetooth app now; remove the old Bluetooth manager.
if pacman -Q blueman >/dev/null 2>&1; then
  pacman -Rns --noconfirm blueman || true
fi
