#!/usr/bin/env bash
# Installs Wren next to a fake Windows on two virtual disks and checks Windows is
# untouched and the boot menu offers both:
#   1. newer computer: UEFI + GPT (Windows boot files on the EFI partition)
#   2. older computer: BIOS + MBR, which is then booted in QEMU to capture the real
#      boot menu, start-up screen and login screen (and how long boot takes)
set -uo pipefail
cd "$(dirname "$0")/.."
SRC="$PWD/build/work/x86_64/airootfs"
MEDIA="$PWD/build/work/iso"
SHOTS="$PWD/screenshots"
mkdir -p "$SHOTS"
pacman -S --noconfirm --needed rsync dosfstools e2fsprogs grub arch-install-scripts util-linux ntfs-3g \
  qemu-system-x86 python-pillow socat >/dev/null

problems=()
fail() { problems+=("$1"); }
note() { echo "::notice title=Dual boot::$1"; }
warnmsg() { echo "::warning title=Dual boot::$1"; }

mknodes() {  # partition device nodes (no udev in containers)
  local loop=$1 p
  local want have
  for p in /sys/block/"${loop##*/}"/"${loop##*/}"p*; do
    [[ -e $p/dev ]] || continue
    want=$(cat "$p/dev"); have=$(stat -c '%Hr:%Lr' "/dev/${p##*/}" 2>/dev/null || true)
    if [[ $have != "$want" ]]; then rm -f -- "/dev/${p##*/}"; mknod "/dev/${p##*/}" b "${want%%:*}" "${want##*:}"; fi
  done
}

debug_windows() {  # <label> <esp device or ""> [env...]: trace the Windows detection step
  local label=$1 esp=$2; shift 2
  {
    [[ -n $esp ]] && mkdir -p /mnt/wren/efi && mount "$esp" /mnt/wren/efi
    env "$@" arch-chroot /mnt/wren sh -x /etc/grub.d/35_wren_windows 2>&1 | tail -n 7
    [[ -n $esp ]] && umount /mnt/wren/efi
  } 2>&1 | while IFS= read -r l; do echo "::error title=$label Windows detection::$l"; done
}

free_region() {  # prints "<start bytes> <size bytes>" of the biggest free region
  local loop=$1 ss
  ss=$(blockdev --getss "$loop")
  sfdisk -F "$loop" | awk -v ss="$ss" '$1 ~ /^[0-9]+$/ && NF >= 3 {print $1 * ss, $3 * ss}' | sort -k2 -n | tail -n1
}

install_alongside() {  # <loop> <extra env...>
  local loop=$1; shift
  read -r start size < <(free_region "$loop")
  echo "Free region: start=$start size=$size"
  printf 'test-password\n' | env WREN_DISK="$loop" WREN_MODE=free WREN_FREE_START="$start" WREN_FREE_SIZE="$size" \
    WREN_USER=tester WREN_FULLNAME="Test User" WREN_HOSTNAME=wren-dual WREN_TZ=America/Los_Angeles \
    WREN_LOCALE=en_US.UTF-8 WREN_XKB=us WREN_KEYMAP=us WREN_SOURCE="$SRC" WREN_MEDIA="$MEDIA" "$@" \
    bash live/usr/lib/wren/install-backend.sh > /tmp/dual.log 2>&1
  local rc=$?
  tail -n 15 /tmp/dual.log
  return $rc
}

# ------------------------------------------------------------- 1. UEFI + GPT
img=/tmp/win-uefi.img
rm -f "$img"; truncate -s 40G "$img"
sfdisk "$img" >/dev/null <<'EOF'
label: gpt
size=300MiB, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, name="EFI system partition"
size=16MiB, type=E3C9E316-0B5C-4DB8-817D-F92DF00215AE, name="Microsoft reserved partition"
size=20GiB, type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7, name="Basic data partition"
EOF
loop=$(losetup -fP --show "$img"); mknodes "$loop"
mkfs.fat -F 32 -n SYSTEM "${loop}p1" >/dev/null
mkfs.ntfs -Q -L Windows "${loop}p3" >/dev/null
mkdir -p /mnt/esp && mount "${loop}p1" /mnt/esp
mkdir -p /mnt/esp/EFI/Microsoft/Boot /mnt/esp/EFI/Boot
echo "fake windows boot manager" > /mnt/esp/EFI/Microsoft/Boot/bootmgfw.efi
echo "fallback belongs to windows" > /mnt/esp/EFI/Boot/bootx64.efi
umount /mnt/esp
esp_uuid=$(blkid -p -s UUID -o value "${loop}p1"); win_uuid=$(blkid -p -s UUID -o value "${loop}p3")

if install_alongside "$loop" WREN_FORCE_UEFI=1 WREN_NO_NVRAM=1; then
  mknodes "$loop"
  [[ $(blkid -p -s UUID -o value "${loop}p1") == "$esp_uuid" ]] || fail "UEFI: EFI partition was reformatted"
  [[ $(blkid -p -s UUID -o value "${loop}p3") == "$win_uuid" ]] || fail "UEFI: Windows partition changed"
  [[ $(blkid -p -s TYPE -o value "${loop}p4") == ext4 ]] || fail "UEFI: no new ext4 partition for Wren"
  mount "${loop}p1" /mnt/esp
  [[ -f /mnt/esp/EFI/Microsoft/Boot/bootmgfw.efi ]] || fail "UEFI: Windows boot manager file is gone"
  grep -q "belongs to windows" /mnt/esp/EFI/Boot/bootx64.efi 2>/dev/null || fail "UEFI: Windows' fallback boot file was overwritten"
  [[ -f /mnt/esp/EFI/Wren/grubx64.efi ]] || fail "UEFI: Wren's boot loader wasn't added to the EFI partition"
  umount /mnt/esp
  mkdir -p /mnt/wren && mount "${loop}p4" /mnt/wren
  grep -qE '\s/efi\s' /mnt/wren/etc/fstab || fail "UEFI: EFI partition not in fstab at /efi"
  [[ -f /mnt/wren/etc/wren/dual-boot ]] || fail "UEFI: dual-boot marker missing"
  grep -q LOCAL /mnt/wren/etc/adjtime || fail "UEFI: clock not set to Windows-style local time"
  grep -q 'set timeout=5' /mnt/wren/boot/grub/grub.cfg || fail "UEFI: boot menu isn't shown"
  grep -q 'themes/wren/theme.txt' /mnt/wren/boot/grub/grub.cfg || warnmsg "UEFI: Wren boot menu theme not referenced"
  if ! grep -q "menuentry 'Windows'" /mnt/wren/boot/grub/grub.cfg; then
    fail "UEFI: Windows isn't in the boot menu"
    debug_windows UEFI "${loop}p1" WREN_FORCE_UEFI=1
  fi
  grep -q "menuentry 'Wren Linux'" /mnt/wren/boot/grub/grub.cfg || fail "UEFI: Wren isn't in the boot menu"
  umount /mnt/wren
else
  fail "UEFI: install alongside Windows failed: $(grep '^@@ERROR' /tmp/dual.log | tail -n1)"
  tail -n 12 /tmp/dual.log | while IFS= read -r l; do echo "::error title=UEFI install log::$l"; done
fi
losetup -d "$loop"

# ------------------------------------------------------------- 2. BIOS + MBR
img=/tmp/win-bios.img
rm -f "$img"; truncate -s 40G "$img"
sfdisk "$img" >/dev/null <<'EOF'
label: dos
size=100MiB, type=7, bootable
size=20GiB, type=7
EOF
loop=$(losetup -fP --show "$img"); mknodes "$loop"
mkfs.ntfs -Q -L "System Reserved" "${loop}p1" >/dev/null
mkfs.ntfs -Q -L Windows "${loop}p2" >/dev/null
echo "fake bootmgr" > /tmp/bootmgr
mkdir -p /mnt/ntfs
if mount -t ntfs3 "${loop}p1" /mnt/ntfs 2>/dev/null || ntfs-3g "${loop}p1" /mnt/ntfs 2>/dev/null; then
  cp /tmp/bootmgr /mnt/ntfs/bootmgr && mkdir -p /mnt/ntfs/Boot && echo x > /mnt/ntfs/Boot/BCD
  umount /mnt/ntfs
else
  ntfscp -f "${loop}p1" /tmp/bootmgr bootmgr >/dev/null 2>&1 || true
fi
fake_windows_ok=1
if ntfscat "${loop}p1" bootmgr 2>/dev/null | grep -q "fake bootmgr"; then
  note "BIOS: fake Windows has a bootmgr file"
else
  fake_windows_ok=0
  warnmsg "BIOS: couldn't write bootmgr into the fake Windows here; skipping the Windows menu check"
fi
sysr_uuid=$(blkid -p -s UUID -o value "${loop}p1"); win_uuid=$(blkid -p -s UUID -o value "${loop}p2")

if install_alongside "$loop" WREN_FORCE_BIOS=1; then
  mknodes "$loop"
  [[ $(blkid -p -s UUID -o value "${loop}p1") == "$sysr_uuid" ]] || fail "BIOS: System Reserved partition changed"
  [[ $(blkid -p -s UUID -o value "${loop}p2") == "$win_uuid" ]] || fail "BIOS: Windows partition changed"
  [[ $(blkid -p -s TYPE -o value "${loop}p3") == ext4 ]] || fail "BIOS: no new ext4 partition for Wren"
  dd if="$loop" bs=512 count=1 2>/dev/null | grep -aq GRUB || fail "BIOS: GRUB not installed in the boot sector"
  mkdir -p /mnt/wren && mount "${loop}p3" /mnt/wren
  grep -q 'set timeout=5' /mnt/wren/boot/grub/grub.cfg || fail "BIOS: boot menu isn't shown"
  if ((fake_windows_ok)) && ! grep -q "menuentry 'Windows'" /mnt/wren/boot/grub/grub.cfg; then
    fail "BIOS: Windows isn't in the boot menu"
    debug_windows BIOS ""
  fi
  grep -q "menuentry 'Wren Linux'" /mnt/wren/boot/grub/grub.cfg || fail "BIOS: Wren isn't in the boot menu"
  cp /mnt/wren/boot/grub/grub.cfg "$SHOTS/dualboot-bios-grub.cfg.txt"
  # Test only: the boot image was tailored to the build server's hardware; make a
  # generic one so the virtual machine below can start it
  mkdir -p /mnt/wren/boot && arch-chroot /mnt/wren mkinitcpio -P -S autodetect >/dev/null 2>&1 ||
    warnmsg "Couldn't build a generic boot image for the QEMU test"
  umount /mnt/wren
else
  fail "BIOS: install alongside Windows failed: $(grep '^@@ERROR' /tmp/dual.log | tail -n1)"
  tail -n 12 /tmp/dual.log | while IFS= read -r l; do echo "::error title=BIOS install log::$l"; done
fi
losetup -d "$loop"

# ------------------------------------------------------------- 3. real boot in QEMU
boot_test() {
  local accel="-accel tcg" speed="emulated (slow)"
  if [[ -w /dev/kvm ]]; then accel="-enable-kvm -cpu host"; speed="hardware-accelerated"; fi
  note "Booting the BIOS install in QEMU ($speed)"
  rm -f /tmp/qmon
  qemu-system-x86_64 $accel -m 2048 -smp 2 -drive file=/tmp/win-bios.img,format=raw,if=virtio \
    -vga std -display none -monitor unix:/tmp/qmon,server,nowait -no-reboot &
  local qpid=$! t=0
  for when in 4 8 12 18 25 35 50 70 95 125 160; do
    while ((t < when)); do sleep 1; t=$((t + 1)); done
    echo "screendump /tmp/boot-$when.ppm" | socat - UNIX-CONNECT:/tmp/qmon >/dev/null 2>&1
    sleep 0.5
    [[ -f /tmp/boot-$when.ppm ]] && python -c "from PIL import Image; Image.open('/tmp/boot-$when.ppm').save('$SHOTS/boot-$(printf %03d "$when")s.png')"
  done
  echo quit | socat - UNIX-CONNECT:/tmp/qmon >/dev/null 2>&1
  wait "$qpid" 2>/dev/null
}
boot_test || warnmsg "QEMU boot test didn't run"

if ((${#problems[@]})); then
  for p in "${problems[@]}"; do echo "::error title=Dual boot::$p"; done
  exit 1
fi
note "Installed next to Windows (UEFI and BIOS) without touching it"
