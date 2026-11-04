#!/usr/bin/env bash
# Starts the Wren desktop off-screen inside the freshly built system and takes
# screenshots of the main UI, so the look can be checked without real hardware.
set -uo pipefail
cd "$(dirname "$0")/.."
R=build/work/x86_64/airootfs
OUT=$PWD/screenshots
rm -rf "$OUT" "$R/tmp/shots"
mkdir -p "$OUT" "$R/tmp/shots"

cat > "$R/tmp/scenes.sh" <<'EOF'
shot() { sleep "$2"; grim "/tmp/shots/$1.png"; }
shot 1-desktop 8
wren-shell launcher; shot 2-launcher 3; wren-shell launcher
wren-shell control;  shot 3-quick-settings 3; wren-shell control
for page in 0 1 3 4; do
  WREN_INSTALLER_PAGE=$page wren-installer & pid=$!
  shot "4-installer-page$page" 5
  kill $pid; sleep 1
done
nautilus --new-window /usr/share & shot 5-files 6
gnome-text-editor & shot 6-text-editor 5
labwc --exit
EOF

cat > "$R/tmp/run-desktop.sh" <<'EOF'
export HOME=/root XDG_RUNTIME_DIR=/tmp/xdg
mkdir -p -m 700 "$XDG_RUNTIME_DIR"
export WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1
export GSK_RENDERER=cairo LIBGL_ALWAYS_SOFTWARE=1 NO_AT_BRIDGE=1
timeout 150 dbus-run-session -- labwc -s 'sh /tmp/scenes.sh' >/tmp/shots/desktop.log 2>&1
EOF

arch-chroot "$R" bash /tmp/run-desktop.sh || true
cp "$R"/tmp/shots/* "$OUT/" 2>/dev/null
rm -rf "$R/tmp/shots" "$R/tmp/scenes.sh" "$R/tmp/run-desktop.sh" "$R/tmp/xdg" "$R/root/.config/wren"
ls -la "$OUT"
