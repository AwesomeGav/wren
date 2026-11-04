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
for f in "$ROOT"/usr/local/bin/wren-* "$ROOT"/usr/lib/wren/*.sh "$ROOT"/usr/lib/wren/*.py; do
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

echo ":: Start the desktop automatically on the live USB"
cat >> "$ROOT/root/.zlogin" <<'EOF'

# Wren: launch the desktop on the first console
if [[ -z ${WAYLAND_DISPLAY:-} && $(tty) == /dev/tty1 ]]; then
  exec labwc
fi
EOF

echo ":: Building ISO (this takes a while)"
mkarchiso -v -w build/work -o out "$PROFILE"
ls -lh out/
