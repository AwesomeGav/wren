#!/usr/bin/env bash
# Wren Linux install backend. Run as root by the Wren Installer.
# Settings come from WREN_* environment variables; the password arrives on stdin.
# Progress lines look like "@@ <percent> <message>"; errors like "@@ERROR <message>".
set -Eeuo pipefail

T=/mnt/wren-target
step() { echo "@@ $1 $2"; }
fail() { echo "@@ERROR $1"; exit 1; }
trap 'echo "@@ERROR Something went wrong while running: ${BASH_COMMAND}"' ERR
cleanup() { sync; umount -R "$T" 2>/dev/null || true; }
trap cleanup EXIT

[[ $EUID -eq 0 ]] || fail "The installer needs administrator rights."
IFS= read -r PASSWORD || true
[[ -n ${PASSWORD:-} ]] || fail "No password was given."
DISK=${WREN_DISK:?}; USERNAME=${WREN_USER:?}; FULLNAME=${WREN_FULLNAME:-$WREN_USER}
HOST=${WREN_HOSTNAME:-wren}; TZ_NAME=${WREN_TZ:-UTC}; LOCALE=${WREN_LOCALE:-en_US.UTF-8}
XKB=${WREN_XKB:-us}; KEYMAP=${WREN_KEYMAP:-us}
[[ -b $DISK ]] || fail "The disk $DISK was not found."
MEDIA=${WREN_MEDIA:-/run/archiso/bootmnt}
if [[ -n ${WREN_FORCE_UEFI:-} ]]; then UEFI=1
elif [[ -d /sys/firmware/efi && -z ${WREN_FORCE_BIOS:-} ]]; then UEFI=1; else UEFI=0; fi
# erase: whole disk | free: new partition in free space | partition: reuse one partition
MODE=${WREN_MODE:-erase}
NVRAM_OPT=(); [[ -n ${WREN_NO_NVRAM:-} ]] && NVRAM_OPT=(--no-nvram)
ESP=""

# ---------------------------------------------------------------- disk
step 2 "Preparing the disk"
swapoff -a 2>/dev/null || true
umount -R "$T" 2>/dev/null || true

part_list() { lsblk -lnpo NAME,TYPE "$DISK" | awk '$2 == "part" {print $1}'; }
settle() {
  partprobe "$DISK" 2>/dev/null || partx -u "$DISK" 2>/dev/null || true
  udevadm settle 2>/dev/null || true
  sleep 1
  # Without udev (e.g. in a container) partition device files may be missing; create them
  local p want have
  for p in $(part_list); do
    [[ -r /sys/class/block/${p##*/}/dev ]] || continue
    want=$(cat "/sys/class/block/${p##*/}/dev")
    have=$(stat -c '%Hr:%Lr' "$p" 2>/dev/null || true)
    if [[ $have != "$want" ]]; then
      rm -f -- "$p"
      mknod "$p" b "${want%%:*}" "${want##*:}"
    fi
  done
}
# Partition types straight from the partition table (works without udev)
part_types() {
  sfdisk -d "$DISK" 2>/dev/null | awk -F'[ ,=]+' '/^\// {
    t = ""; for (i = 1; i <= NF; i++) if ($i == "type") t = tolower($(i + 1)); print $1, t }'
}
find_esp() {
  part_types | awk '$2 == "c12a7328-f81f-11d2-ba4b-00a0c93ec93b" || $2 == "ef" {print $1; exit}'
}

case $MODE in
erase)
  while read -r part; do
    umount "$part" 2>/dev/null || true
    swapoff "$part" 2>/dev/null || true
  done < <(lsblk -lnpo NAME "$DISK" | tail -n +2)
  wipefs -af "$DISK" >/dev/null
  if ((UEFI)); then
    sfdisk --wipe always --wipe-partitions always "$DISK" <<'EOF'
label: gpt
size=1GiB, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, name="WREN-BOOT"
type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name="WREN"
EOF
  else
    sfdisk --wipe always --wipe-partitions always "$DISK" <<'EOF'
label: gpt
size=1MiB, type=21686148-6449-6E6F-744E-656564454649, name="BIOS-BOOT"
type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name="WREN"
EOF
  fi
  settle
  mapfile -t PARTS < <(part_list)
  [[ ${#PARTS[@]} -ge 2 ]] || fail "The new partitions didn't appear on $DISK."
  BOOT=${PARTS[0]}; ROOTP=${PARTS[1]}
  ;;
free)
  LABEL=$(sfdisk -d "$DISK" 2>/dev/null | sed -n 's/^label: *//p')
  [[ $LABEL == gpt || $LABEL == dos ]] || fail "This disk has no partition table, so there's no free space to use."
  SS=$(blockdev --getss "$DISK")
  MIB=$((1024 * 1024))
  START_B=$(( (${WREN_FREE_START:?} + MIB - 1) / MIB * MIB ))
  END_B=$(( WREN_FREE_START + ${WREN_FREE_SIZE:?} ))
  [[ $LABEL == gpt ]] && END_B=$(( END_B - MIB ))
  END_B=$(( END_B / MIB * MIB ))
  (( END_B - START_B >= 12 * 1000 * 1000 * 1000 )) || fail "The free space is too small (Wren needs 12 GB)."
  if [[ $LABEL == gpt ]]; then TYPE=0FC63DAF-8483-4772-8E79-3D69D8477DE4; else TYPE=83; fi
  mapfile -t BEFORE < <(part_list)
  echo "start=$((START_B / SS)), size=$(((END_B - START_B) / SS)), type=$TYPE" |
    sfdisk --append --no-reread --wipe-partitions always "$DISK"
  settle
  ROOTP=""
  for p in $(part_list); do
    if [[ " ${BEFORE[*]} " != *" $p "* ]]; then ROOTP=$p; fi
  done
  [[ -n $ROOTP ]] || fail "The new partition didn't appear on $DISK."
  ;;
partition)
  ROOTP=${WREN_TARGET:?}
  [[ -b $ROOTP ]] || fail "The partition $ROOTP was not found."
  [[ $(lsblk -no PKNAME "$ROOTP" | head -n1) == "$(basename "$DISK")" ]] || fail "$ROOTP isn't on $DISK."
  [[ $ROOTP != "$(find_esp)" ]] || fail "That's the computer's boot partition. Pick a different one."
  umount "$ROOTP" 2>/dev/null || true
  wipefs -af "$ROOTP" >/dev/null
  ;;
*) fail "Unknown install type: $MODE" ;;
esac

if [[ $MODE != erase ]]; then
  if ((UEFI)); then
    ESP=$(find_esp)
    [[ -n $ESP ]] || fail "This disk has no EFI boot partition, so Wren can't start alongside the other system. Choose \"Erase the whole disk\" or use a different disk."
  elif [[ $(sfdisk -d "$DISK" 2>/dev/null | sed -n 's/^label: *//p') == gpt ]]; then
    part_types | grep -q 21686148-6449-6e6f-744e-656564454649 ||
      fail "This older computer can't start Wren from this disk alongside another system. Choose \"Erase the whole disk\" instead."
  fi
fi

step 6 "Formatting"
mkfs.ext4 -F -q -L wren "$ROOTP"
if [[ $MODE == erase ]] && ((UEFI)); then mkfs.fat -F 32 -n WRENBOOT "$BOOT" >/dev/null; fi
mkdir -p "$T"
mount "$ROOTP" "$T"
if [[ $MODE == erase ]] && ((UEFI)); then
  mkdir -p "$T/boot"
  mount "$BOOT" "$T/boot"
elif ((UEFI)); then
  # Share the existing EFI partition (never formatted); Wren's kernel stays on its own partition
  mkdir -p "$T/efi"
  mount "$ESP" "$T/efi"
fi

# ---------------------------------------------------------------- copy
SRC=${WREN_SOURCE:-}
if [[ -z $SRC ]]; then
  for candidate in /run/archiso/airootfs /run/archiso/sfs/airootfs; do
    if [[ -d $candidate/usr/bin ]]; then SRC=$candidate; break; fi
  done
fi
[[ -n $SRC ]] || SRC=/
echo "Copying from $SRC"

step 10 "Copying Wren to your computer"
rsync -aAXH --no-inc-recursive --info=progress2 \
  --exclude='/dev/*' --exclude='/proc/*' --exclude='/sys/*' --exclude='/run/*' \
  --exclude='/tmp/*' --exclude='/mnt/*' --exclude='/media/*' --exclude='/boot/*' \
  --exclude='/lost+found' --exclude='/var/cache/pacman/pkg/*' \
  "$SRC/" "$T/" |
  tr '\r' '\n' |
  awk 'match($0, /[0-9]+%/) { p = substr($0, RSTART, RLENGTH - 1) + 0;
         q = int(10 + p * 0.62); if (q != last) { print "@@ " q " Copying Wren to your computer"; fflush(); last = q } }'

step 73 "Adding the system kernel"
KERNEL=""
for k in "$SRC/boot/vmlinuz-linux" $(find "$MEDIA" -name vmlinuz-linux 2>/dev/null); do
  if [[ -f $k ]]; then KERNEL=$k; break; fi
done
[[ -n $KERNEL ]] || fail "Couldn't find the Linux kernel on the install media."
install -Dm644 "$KERNEL" "$T/boot/vmlinuz-linux"
for uc in intel-ucode.img amd-ucode.img; do
  f=$(find "$SRC/boot" "$MEDIA" -name "$uc" 2>/dev/null | head -n1 || true)
  if [[ -n $f ]]; then install -Dm644 "$f" "$T/boot/$uc"; fi
done

# ---------------------------------------------------------------- tidy live-only bits
step 76 "Setting up your system"
rm -f "$T/etc/mkinitcpio.conf.d/archiso.conf" \
      "$T/etc/systemd/journald.conf.d/volatile-storage.conf" \
      "$T/etc/systemd/logind.conf.d/do-not-suspend.conf" \
      "$T/etc/ssh/sshd_config.d/10-archiso.conf" \
      "$T/etc/motd" "$T/root/.zlogin" "$T/root/.automated_script.sh" \
      "$T/usr/local/bin/wren-installer" "$T/usr/share/applications/wren-installer.desktop" \
      "$T/usr/lib/wren/installer.py" "$T/usr/lib/wren/install-backend.sh" "$T/usr/lib/wren/live-power" \
      "$T/etc/sudoers.d/wren-live" "$T/etc/polkit-1/rules.d/49-wren-live.rules" \
      "$T/etc/profile.d/wren-live.sh" "$T/etc/systemd/system/wren-live-user.service"
rm -rf "$T/etc/systemd/system/getty@tty1.service.d"
rm -rf "$T/etc/systemd/system/cloud-init.target.wants" "$T/etc/systemd/system/systemd-networkd-wait-online.service.d"
mkdir -p "$T/etc/cloud" && touch "$T/etc/cloud/cloud-init.disabled"
for unit in pacman-init.service choose-mirror.service etc-pacman.d-gnupg.mount sshd.service \
            reflector.service livecd-talk.service livecd-alsa-unmuter.service iwd.service \
            systemd-networkd.service systemd-networkd.socket systemd-networkd-wait-online.service \
            wren-live-user.service systemd-time-wait-sync.service ModemManager.service pcscd.socket \
            cloud-init-main.service cloud-init-local.service cloud-init-network.service \
            cloud-config.service cloud-final.service vmware-vmblock-fuse.service; do
  find "$T/etc/systemd/system" -name "$unit" \( -type l -o -type f \) -delete 2>/dev/null || true
done
cat > "$T/etc/mkinitcpio.d/linux.preset" <<'EOF'
# mkinitcpio preset file for the 'linux' package
ALL_kver="/boot/vmlinuz-linux"
PRESETS=('default')
default_image="/boot/initramfs-linux.img"
EOF

# Wren uses compressed RAM swap (zram), never a swap partition. Leave swap out of
# fstab: the live USB's zram swap gets a new ID every boot, and listing it would
# make every start-up wait 90 seconds for a disk that never appears.
genfstab -U "$T" | awk '$3 != "swap"' > "$T/etc/fstab"

# ---------------------------------------------------------------- settings
echo "$HOST" > "$T/etc/hostname"
cat > "$T/etc/hosts" <<EOF
127.0.0.1 localhost
::1       localhost
127.0.1.1 $HOST.localdomain $HOST
EOF
ln -sf "/usr/share/zoneinfo/$TZ_NAME" "$T/etc/localtime"
sed -i 's/^#\?\s*\(en_US.UTF-8 UTF-8\)/\1/' "$T/etc/locale.gen"
sed -i "s/^#\s*\(${LOCALE//./\\.} UTF-8\)/\1/" "$T/etc/locale.gen"
echo "LANG=$LOCALE" > "$T/etc/locale.conf"
echo "KEYMAP=$KEYMAP" > "$T/etc/vconsole.conf"
if [[ $XKB != us ]]; then
  echo "XKB_DEFAULT_LAYOUT=$XKB" >> "$T/etc/xdg/labwc/environment"
fi

# Login screen
mkdir -p "$T/etc/greetd"
cp "$SRC/usr/share/wren/greetd/config.toml" "$SRC/usr/share/wren/greetd/regreet.toml" \
   "$SRC/usr/share/wren/greetd/regreet.css" "$T/etc/greetd/"
if [[ $XKB != us ]]; then
  sed -i "s|^command = \"cage|command = \"env XKB_DEFAULT_LAYOUT=$XKB cage|" "$T/etc/greetd/config.toml"
fi

# Alongside another system: show a boot menu and keep the clock the way Windows expects
if [[ $MODE != erase ]]; then
  mkdir -p "$T/etc/wren"
  touch "$T/etc/wren/dual-boot"
  printf '0.0 0 0.0\n0\nLOCAL\n' > "$T/etc/adjtime"
fi

# Start-up screen and quiet boot (boot image and menu are built further down)
arch-chroot "$T" bash /usr/lib/wren/setup-boot-splash.sh

# ---------------------------------------------------------------- inside the new system
step 80 "Creating your account"
arch-chroot "$T" env WREN_FULLNAME="$FULLNAME" WREN_USER="$USERNAME" /bin/bash -e <<'EOF'
locale-gen >/dev/null
[[ -f /etc/wren/dual-boot ]] || hwclock --systohc 2>/dev/null || true
useradd -m -G wheel,video,audio,input -c "$WREN_FULLNAME" -s /bin/bash "$WREN_USER"
passwd -l root >/dev/null
echo '%wheel ALL=(ALL:ALL) ALL' > /etc/sudoers.d/10-wheel
chmod 440 /etc/sudoers.d/10-wheel
EOF
printf '%s:%s\n' "$USERNAME" "$PASSWORD" | arch-chroot "$T" chpasswd

step 84 "Turning on services"
arch-chroot "$T" /bin/bash <<'EOF'
for svc in greetd.service NetworkManager.service bluetooth.service earlyoom.service tlp.service fstrim.timer; do
  systemctl enable "$svc" 2>/dev/null || echo "could not enable $svc"
done
systemctl mask systemd-rfkill.service systemd-rfkill.socket 2>/dev/null || true
systemctl --global mask localsearch-3.service tracker-miner-fs-3.service 2>/dev/null || true
pacman-key --init >/dev/null 2>&1
pacman-key --populate archlinux >/dev/null 2>&1
EOF

step 88 "Preparing the system to start"
arch-chroot "$T" mkinitcpio -P

step 94 "Installing the boot loader"
if ((UEFI)) && [[ $MODE == erase ]]; then
  arch-chroot "$T" grub-install --target=x86_64-efi --efi-directory=/boot --bootloader-id=Wren --recheck "${NVRAM_OPT[@]}"
  # Second copy at the fallback path, for computers that ignore boot entries
  arch-chroot "$T" grub-install --target=x86_64-efi --efi-directory=/boot --removable --recheck
elif ((UEFI)); then
  # Alongside another system: add Wren's own entry, leave the other system's files alone
  arch-chroot "$T" grub-install --target=x86_64-efi --efi-directory=/efi --bootloader-id=Wren --recheck "${NVRAM_OPT[@]}"
else
  arch-chroot "$T" grub-install --target=i386-pc --recheck "$DISK"
fi
arch-chroot "$T" grub-mkconfig -o /boot/grub/grub.cfg
arch-chroot "$T" sh /usr/lib/wren/quiet-grub-cfg.sh
# This system already has everything the upgrade steps add
mkdir -p "$T/var/lib/wren/migrations"
for m in "$SRC"/usr/share/wren/migrations/*.sh; do
  if [[ -f $m ]]; then touch "$T/var/lib/wren/migrations/$(basename "$m" .sh)"; fi
done

step 100 "Finished"
