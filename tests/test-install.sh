#!/usr/bin/env bash
# Runs the Wren installer backend against a virtual 20 GB disk, using the
# system that build.sh just assembled, then checks the result boots-ready.
set -uo pipefail
cd "$(dirname "$0")/.."

pacman -S --noconfirm --needed rsync dosfstools e2fsprogs grub arch-install-scripts util-linux >/dev/null

img=/tmp/wren-test.img
rm -f "$img"
truncate -s 20G "$img"
loop=$(losetup -fP --show "$img")
log=/tmp/wren-install.log
echo "Installing to virtual disk $loop"

printf 'test-password\n' | env \
  WREN_DISK="$loop" WREN_USER=tester WREN_FULLNAME="Test O'Brien" WREN_HOSTNAME=wren-test \
  WREN_TZ=America/Los_Angeles WREN_LOCALE=en_US.UTF-8 WREN_XKB=gb WREN_KEYMAP=uk \
  WREN_FORCE_BIOS=1 WREN_SOURCE="$PWD/build/work/x86_64/airootfs" WREN_MEDIA="$PWD/build/work/iso" \
  bash live/usr/lib/wren/install-backend.sh 2>&1 | tee "$log"
status=${PIPESTATUS[1]}

problems=()
if [[ $status -ne 0 ]]; then
  problems+=("Installer exited with code $status: $(grep '^@@ERROR' "$log" | tail -n1)")
else
  mkdir -p /mnt/check
  mount "${loop}p2" /mnt/check
  for f in boot/vmlinuz-linux boot/initramfs-linux.img boot/grub/grub.cfg home/tester \
           etc/greetd/regreet.toml etc/sudoers.d/10-wheel usr/lib/wren/shell.py; do
    [[ -e /mnt/check/$f ]] || problems+=("Missing after install: /$f")
  done
  for f in etc/mkinitcpio.conf.d/archiso.conf usr/lib/wren/installer.py root/.zlogin \
           etc/sudoers.d/wren-live etc/polkit-1/rules.d/49-wren-live.rules etc/profile.d/wren-live.sh \
           etc/systemd/system/multi-user.target.wants/wren-live-user.service usr/lib/wren/live-power; do
    [[ -e /mnt/check/$f ]] && problems+=("Live-only file left behind: /$f")
  done
  grep -q '^tester:.*:Test O'"'"'Brien:' /mnt/check/etc/passwd || problems+=("User account not created correctly")
  grep -q 'XKB_DEFAULT_LAYOUT=gb' /mnt/check/etc/xdg/labwc/environment || problems+=("Keyboard layout not set")
  [[ -L /mnt/check/etc/systemd/system/display-manager.service ]] || problems+=("Login screen (greetd) not enabled")
  grep -q 'menuentry' /mnt/check/boot/grub/grub.cfg || problems+=("Boot menu has no entries")
  grep -qE '^HOOKS=.*plymouth' /mnt/check/etc/mkinitcpio.conf || problems+=("Start-up screen hook missing")
  grep -q 'splash' /mnt/check/boot/grub/grub.cfg || problems+=("Start-up screen not enabled in boot menu")
  grep -q 'plymouth.use-simpledrm' /mnt/check/boot/grub/grub.cfg || problems+=("Start-up screen early display option missing")
  grep -q 'systemd.tpm2_wait=0' /mnt/check/boot/grub/grub.cfg || problems+=("TPM wait not disabled")
  [[ -f /mnt/check/etc/systemd/system.conf.d/wren-fast-boot.conf ]] || problems+=("Fast-boot timeouts missing")
  [[ "$(readlink /mnt/check/etc/systemd/system/NetworkManager-wait-online.service)" == /dev/null ]] || problems+=("NetworkManager-wait-online not masked")
  grep -q "echo.*'Loading " /mnt/check/boot/grub/grub.cfg && problems+=("Boot menu still prints Loading messages")
  grep -q 'Theme=wren' /mnt/check/etc/plymouth/plymouthd.conf || problems+=("Start-up theme not selected")
  grep -q 'wren-greeter' /mnt/check/etc/greetd/config.toml || problems+=("Wren Login not set as the login screen")
  awk '$1 !~ /^#/ && $3 == "swap"' /mnt/check/etc/fstab | grep -q . && problems+=("fstab lists a swap device (slows start-up)")
  for u in cloud-init.target.wants/cloud-init-main.service sysinit.target.wants/systemd-time-wait-sync.service \
           multi-user.target.wants/ModemManager.service network-online.target.wants/systemd-networkd-wait-online.service; do
    [[ -e /mnt/check/etc/systemd/system/$u ]] && problems+=("Slow-boot service still enabled: $u")
  done
  umount /mnt/check
fi
losetup -d "$loop" || true

if ((${#problems[@]})); then
  for p in "${problems[@]}"; do echo "::error title=Installer test::$p"; done
  tail -n 25 "$log" | while IFS= read -r l; do echo "::error title=Installer log::$l"; done
  exit 1
fi
echo "::notice title=Installer test::Installed to a virtual disk and passed all checks"
