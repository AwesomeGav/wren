#!/usr/bin/env bash
# Starts the Wren desktop off-screen inside the freshly built system and takes
# screenshots of the main UI, so the look can be checked without real hardware.
set -uo pipefail
cd "$(dirname "$0")/.."
R=build/work/x86_64/airootfs
OUT=$PWD/screenshots
rm -rf "$OUT" "$R/var/tmp/shots"
mkdir -p "$OUT" "$R/var/tmp/shots"

mkdir -p "$R/var/tmp/variants"
python3 tests/panel-variants.py "$R/var/tmp/variants"

cat > "$R/var/tmp/scenes.sh" <<'EOF'
shot() { sleep "$2"; grim "/var/tmp/shots/$1.png"; }
# Restart the panel and shell with logging, to diagnose display problems
sleep 3
stop_panels() { for p in /proc/[0-9]*; do [ "$(cat "$p/comm" 2>/dev/null)" = waybar ] && kill "${p#/proc/}"; done; sleep 1; }
stop_panels
waybar -l debug -c /etc/xdg/wren/waybar/config.jsonc -s /etc/xdg/wren/waybar/style.css >/var/tmp/shots/waybar.log 2>&1 &
shot 1-desktop 8
# Try each panel variant on its own
for cfg in /var/tmp/variants/*.json; do
  name=$(basename "$cfg" .json)
  css=/etc/xdg/wren/waybar/style.css
  [ "$name" = e-old-build6 ] && css=/var/tmp/variants/old.css
  stop_panels
  waybar -l debug -c "$cfg" -s "$css" >"/var/tmp/shots/panel-$name.log" 2>&1 &
  shot "panel-$name" 4
done
stop_panels
waybar -c /etc/xdg/wren/waybar/config.jsonc -s /etc/xdg/wren/waybar/style.css >/dev/null 2>&1 &
sleep 2
wren-shell launcher; shot 2-launcher 3; wren-shell launcher
wren-shell control;  shot 3-quick-settings 3; wren-shell control
for page in 0 1 3 4; do
  WREN_INSTALLER_PAGE=$page wren-installer & pid=$!
  shot "4-installer-page$page" 5
  kill $pid; sleep 1
done
nautilus --new-window /usr/share & shot 5-files 12
gnome-text-editor & shot 6-text-editor 5
labwc --exit
EOF

cat > "$R/var/tmp/run-desktop.sh" <<'EOF'
export HOME=/root XDG_RUNTIME_DIR=/tmp/xdg
mkdir -p -m 700 "$XDG_RUNTIME_DIR"
export WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1
export GSK_RENDERER=cairo LIBGL_ALWAYS_SOFTWARE=1 NO_AT_BRIDGE=1
timeout 150 dbus-run-session -- labwc -s 'sh /var/tmp/scenes.sh' >/var/tmp/shots/desktop.log 2>&1
# Login screen, in demo mode (no real logins), inside the same kiosk compositor greetd uses
timeout 40 dbus-run-session -- cage -s -- sh -c 'regreet --demo --config /usr/share/wren/greetd/regreet.toml --style /usr/share/wren/greetd/regreet.css & sleep 8; grim /var/tmp/shots/7-login.png; kill %1' >/var/tmp/shots/login.log 2>&1
EOF

arch-chroot "$R" bash /var/tmp/run-desktop.sh >"$OUT/chroot.log" 2>&1 || echo "desktop exited with $?" >>"$OUT/chroot.log"
cp "$R"/var/tmp/shots/* "$OUT/" 2>/dev/null
rm -rf "$R/var/tmp/shots" "$R/var/tmp/scenes.sh" "$R/var/tmp/run-desktop.sh" "$R/tmp/xdg" "$R/root/.config/wren"
ls -la "$OUT"
