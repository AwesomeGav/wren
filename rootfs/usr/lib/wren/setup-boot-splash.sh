#!/usr/bin/env bash
# Sets up Wren's start-up screen (Plymouth) and a quiet boot.
#   setup-boot-splash.sh            configure only (the installer rebuilds afterwards)
#   setup-boot-splash.sh --rebuild  configure, then rebuild the boot image and menu
set -euo pipefail

# Plymouth theme
mkdir -p /etc/plymouth
cat > /etc/plymouth/plymouthd.conf <<'CONF'
[Daemon]
Theme=wren
ShowDelay=0
DeviceTimeout=8
CONF

# Add the plymouth hook to the boot image, right after systemd or udev
conf=/etc/mkinitcpio.conf
if ! grep -qE '^HOOKS=.*\bplymouth\b' "$conf"; then
  if grep -qE '^HOOKS=.*\bsystemd\b' "$conf"; then
    sed -i -E 's/^(HOOKS=\(.*\bsystemd\b)/\1 plymouth/' "$conf"
  else
    sed -i -E 's/^(HOOKS=\(.*\budev\b)/\1 plymouth/' "$conf"
  fi
fi

# Load this computer's graphics driver at the very start of boot (early KMS), so the
# start-up screen can draw right away instead of falling back to plain dots.
for card in /sys/class/drm/card[0-9]*; do
  [[ -e $card/device/driver/module ]] || continue
  mod=$(basename "$(readlink -f "$card/device/driver/module")")
  [[ -n $mod ]] || continue
  if ! grep -qE "^MODULES=\(.*\b$mod\b" "$conf"; then
    sed -i -E "s/^MODULES=\((.*)\)/MODULES=(\1 $mod)/; s/^MODULES=\( /MODULES=(/" "$conf"
  fi
done

# Quiet boot with the splash, no visible boot menu
if [[ -f /etc/default/grub ]]; then
  sed -i -e 's/^GRUB_DISTRIBUTOR=.*/GRUB_DISTRIBUTOR="Wren"/' \
         -e 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=0/' \
         -e 's/^GRUB_TIMEOUT_STYLE=.*/GRUB_TIMEOUT_STYLE=hidden/' \
         -e 's/^#\?GRUB_GFXPAYLOAD_LINUX=.*/GRUB_GFXPAYLOAD_LINUX=keep/' \
         -e 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet splash plymouth.use-simpledrm loglevel=3 rd.udev.log_level=3 systemd.show_status=false rd.systemd.show_status=false vt.global_cursor_default=0"/' \
         /etc/default/grub
  grep -q '^GRUB_GFXPAYLOAD_LINUX=' /etc/default/grub || echo 'GRUB_GFXPAYLOAD_LINUX=keep' >> /etc/default/grub
fi

# Keep the splash up until the login screen is ready
mkdir -p /etc/systemd/system/greetd.service.d
cat > /etc/systemd/system/greetd.service.d/wren-splash.conf <<'CONF'
[Unit]
After=plymouth-quit-wait.service
Wants=plymouth-quit-wait.service
CONF

if [[ ${1:-} == --rebuild ]]; then
  mkinitcpio -P
  grub-mkconfig -o /boot/grub/grub.cfg
  sh /usr/lib/wren/quiet-grub-cfg.sh
fi
