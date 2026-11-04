#!/usr/bin/env bash
# Builds the Wren Linux ISO. Runs on Arch Linux (or an Arch container) as root,
# with the archiso package installed. Output goes to ./out/
set -euo pipefail
cd "$(dirname "$0")"

PROFILE="build/profile"
ROOT="$PROFILE/airootfs"
UNITS="$ROOT/etc/systemd/system"

rm -rf build out
mkdir -p build out

echo ":: Starting from the official Arch live profile"
cp -r /usr/share/archiso/configs/releng "$PROFILE"

echo ":: Branding"
sed -i \
  -e 's/^iso_name=.*/iso_name="wren"/' \
  -e 's/ARCH_/WREN_/' \
  -e 's/^iso_publisher=.*/iso_publisher="Wren Linux <https:\/\/github.com\/AwesomeGav\/wren>"/' \
  -e 's/^iso_application=.*/iso_application="Wren Linux Live\/Install"/' \
  "$PROFILE/profiledef.sh"
grep -rlI "Arch Linux install medium" "$PROFILE" | xargs -r sed -i 's/Arch Linux install medium/Wren Linux/g'
echo "wren" > "$ROOT/etc/hostname"

echo ":: Faster compression (quicker builds, and quicker start-up on slow computers)"
sed -i "s/^airootfs_image_tool_options=.*/airootfs_image_tool_options=('-comp' 'zstd' '-Xcompression-level' '17' '-b' '1M')/" "$PROFILE/profiledef.sh"

echo ":: Silence the boot menu start-up beep"
find "$PROFILE" -name '*.cfg' -path '*grub*' -exec sed -i '/^[[:space:]]*play[[:space:]]/d' {} +
find "$PROFILE" -name 'loader.conf' -exec sed -i '/^[[:space:]]*beep[[:space:]]/d' {} +
if grep -rqE '^[[:space:]]*(play|beep)[[:space:]]' "$PROFILE"/grub "$PROFILE"/efiboot 2>/dev/null; then
  echo "::warning::A boot menu beep line is still present"
fi

echo ":: Version stamp (used by the updater)"
mkdir -p "$ROOT/etc"
cat > "$ROOT/etc/wren-release" <<EOF
WREN_BUILD=${GITHUB_RUN_NUMBER:-0}
WREN_TAG=build-${GITHUB_RUN_NUMBER:-0}
EOF

echo ":: Adding Wren packages"
while read -r p; do
  [[ -z $p ]] && continue
  if pacman -Si "$p" >/dev/null 2>&1; then
    echo "$p" >> "$PROFILE/packages.x86_64"
  else
    echo "::warning::Package not in Arch repos, skipped: $p"
  fi
done < <(sed 's/#.*//; s/[[:space:]]//g' packages.txt)
sort -u -o "$PROFILE/packages.x86_64" "$PROFILE/packages.x86_64"

echo ":: Copying Wren files into the live system"
cp -r rootfs/. "$ROOT/"
cp -r live/. "$ROOT/"
install -Dm755 wren-setup "$ROOT/usr/local/bin/wren-setup"
mkdir -p "$ROOT/usr/share/xsessions" "$ROOT/usr/share/wren/migrations"
cp migrations/*.sh "$ROOT/usr/share/wren/migrations/"
# (mkarchiso resets file modes, so every executable must be listed here)
for f in "$ROOT"/usr/local/bin/wren-* "$ROOT"/usr/lib/wren/*.sh "$ROOT"/usr/lib/wren/*.py "$ROOT"/usr/lib/wren/live-power \
         "$ROOT"/etc/grub.d/35_wren_windows; do
  chmod 755 "$f"
  rel="/${f#"$ROOT"/}"
  sed -i "/^file_permissions=(/a\\  [\"$rel\"]=\"0:0:755\"" "$PROFILE/profiledef.sh"
done

echo ":: Wren theme for the live session's user (root)"
cp -r rootfs/etc/skel/. "$ROOT/root/"

echo ":: Keep the file manager's background indexer off (saves CPU and battery)"
mkdir -p "$ROOT/etc/systemd/user"
ln -sf /dev/null "$ROOT/etc/systemd/user/localsearch-3.service"
ln -sf /dev/null "$ROOT/etc/systemd/user/tracker-miner-fs-3.service"

echo ":: Faster boot: drop cloud-server tools and services a desktop doesn't need"
sed -i '/^cloud-init$/d' "$PROFILE/packages.x86_64"
rm -rf "$UNITS/cloud-init.target.wants" "$UNITS/systemd-networkd-wait-online.service.d"
rm -f "$UNITS/sysinit.target.wants/systemd-time-wait-sync.service" \
      "$UNITS/multi-user.target.wants/ModemManager.service" "$UNITS/dbus-org.freedesktop.ModemManager1.service" \
      "$UNITS/sockets.target.wants/pcscd.socket" "$UNITS/multi-user.target.wants/vmware-vmblock-fuse.service"
mkdir -p "$ROOT/etc/cloud" && touch "$ROOT/etc/cloud/cloud-init.disabled"

echo ":: Services: NetworkManager instead of the default networkd/iwd"
rm -f "$UNITS"/multi-user.target.wants/systemd-networkd.service \
      "$UNITS"/multi-user.target.wants/iwd.service \
      "$UNITS"/sockets.target.wants/systemd-networkd.socket \
      "$UNITS"/network-online.target.wants/systemd-networkd-wait-online.service
mkdir -p "$UNITS/multi-user.target.wants"
for svc in NetworkManager bluetooth earlyoom; do
  ln -sf "/usr/lib/systemd/system/$svc.service" "$UNITS/multi-user.target.wants/$svc.service"
done
ln -sf /usr/lib/systemd/system/NetworkManager.service "$UNITS/dbus-org.freedesktop.NetworkManager.service"
ln -sf /usr/lib/systemd/system/bluetooth.service "$UNITS/dbus-org.bluez.service"

echo ":: Live USB logs in as a regular account (some apps refuse to run as root)"
sed -i 's/--autologin root/--autologin wren/' "$ROOT/etc/systemd/system/getty@tty1.service.d/autologin.conf"
ln -sf /etc/systemd/system/wren-live-user.service "$UNITS/multi-user.target.wants/wren-live-user.service"
sed -i "/^file_permissions=(/a\\  [\"/etc/sudoers.d/wren-live\"]=\"0:0:440\"" "$PROFILE/profiledef.sh"
sed -i "/^file_permissions=(/a\\  [\"/etc/sudoers.d\"]=\"0:0:750\"" "$PROFILE/profiledef.sh"

echo ":: Building ISO (this takes a while)"
mkarchiso -v -w build/work -o out "$PROFILE"
ls -lh out/
