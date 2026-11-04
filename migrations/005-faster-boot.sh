#!/usr/bin/env bash
# Faster start-up: switch off cloud-server and live-USB services that make the
# login screen wait (cloud-init can hold it up for a minute or more).
set -uo pipefail
units="cloud-init-main.service cloud-init-local.service cloud-init-network.service cloud-config.service
cloud-final.service systemd-time-wait-sync.service ModemManager.service pcscd.socket
systemd-networkd-wait-online.service systemd-networkd.service systemd-networkd.socket iwd.service
vmware-vmblock-fuse.service pacman-init.service choose-mirror.service reflector.service sshd.service"
for u in $units; do
  systemctl disable "$u" >/dev/null 2>&1 || true
  find /etc/systemd/system -name "$u" -type l -delete 2>/dev/null || true
done
rm -rf /etc/systemd/system/cloud-init.target.wants /etc/systemd/system/systemd-networkd-wait-online.service.d
mkdir -p /etc/cloud && touch /etc/cloud/cloud-init.disabled
if pacman -Q cloud-init >/dev/null 2>&1; then
  pacman -Rns --noconfirm cloud-init >/dev/null 2>&1 || true
fi
# Rebuild the boot image with the shorter start-up screen wait
sed -i 's/^DeviceTimeout=.*/DeviceTimeout=5/' /etc/plymouth/plymouthd.conf 2>/dev/null || true
mkinitcpio -P >/dev/null 2>&1 || true
