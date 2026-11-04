#!/usr/bin/env bash
# Starts the Wren desktop off-screen inside the freshly built system, as the
# regular live user, and takes screenshots of the main UI so the look can be
# checked without real hardware. Runs after the ISO is built, so nothing here
# ends up in the ISO.
set -uo pipefail
cd "$(dirname "$0")/.."
R=build/work/x86_64/airootfs
OUT=$PWD/screenshots
rm -rf "$OUT" "$R/var/tmp/shots"
mkdir -p "$OUT" "$R/var/tmp/shots"
chmod 777 "$R/var/tmp/shots"

cat > "$R/var/tmp/scenes.sh" <<'EOF'
shot() { sleep "$2"; grim "/var/tmp/shots/$1.png"; }
sleep 2
wren-shell --service >/var/tmp/shots/shell.log 2>&1 &
shot 1-desktop 8
wren-shell launcher; shot 2-launcher 3; wren-shell launcher
wren-shell control;  shot 3-quick-settings 3; wren-shell control
for page in 0 1 3 4; do
  WREN_INSTALLER_PAGE=$page wren-installer & pid=$!
  shot "4-installer-page$page" 5
  kill $pid; sleep 1
done
nautilus --new-window "$HOME" >/var/tmp/shots/files.log 2>&1 & shot 5-files-grid 10
gsettings set org.gnome.nautilus.preferences default-folder-viewer 'list-view'
nautilus --new-window "$HOME/Documents" >/dev/null 2>&1 & shot 5-files-list 6
nautilus -q; sleep 1
WREN_BT_DEMO=1 wren-bluetooth >/var/tmp/shots/bluetooth.log 2>&1 & pid=$!
shot 8-bluetooth 5; kill $pid; sleep 1
wren-bluetooth >>/var/tmp/shots/bluetooth.log 2>&1 & pid=$!
shot 8-bluetooth-no-adapter 5; kill $pid; sleep 1
gnome-text-editor & pid=$!; shot 6-text-editor 5; kill $pid; sleep 1
wren-terminal -e sh -c 'printf "\033[1;38;2;224;137;74mWren Terminal\033[0m\n\n"; ls -la --color=always ~; echo; uname -sr; exec bash' \
  >/var/tmp/shots/terminal.log 2>&1 & shot 9-terminal 6
pkill -f /usr/lib/wren/terminal.py; sleep 1
wren-store >/var/tmp/shots/store.log 2>&1 & shot 10-store 18
pkill -f /usr/lib/wren/store.py; sleep 1
WREN_STORE_PAGE=cat:Game wren-store >>/var/tmp/shots/store.log 2>&1 & shot 10-store-games 15
pkill -f /usr/lib/wren/store.py; sleep 1
WREN_STORE_PAGE=app:org.gimp.GIMP wren-store >>/var/tmp/shots/store.log 2>&1 & shot 10-store-app 15
pkill -f /usr/lib/wren/store.py; sleep 1
labwc --exit
EOF

cat > "$R/var/tmp/run-desktop.sh" <<'EOF'
set -u
# A regular user, like the live USB's "wren" account
id wren >/dev/null 2>&1 || useradd -m -G wheel,video,audio,input -c Wren -s /bin/bash wren
H=/home/wren
mkdir -p "$H"/Documents "$H"/Downloads "$H"/Music "$H"/Pictures "$H"/Videos
cp /usr/share/wren/wallpaper.jpg "$H/Pictures/Topographic.jpg"
cp /usr/share/wren/logo-256.png "$H/Pictures/Wren logo.png"
for f in "Budget 2026.ods" "Meeting notes.txt" "Trip plan.pdf" "Resume.docx"; do echo sample > "$H/Documents/$f"; done
echo sample > "$H/notes.txt"
chown -R wren:wren "$H"
install -d -m 700 -o wren -g wren /tmp/xdg-wren

COMMON="WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1 GSK_RENDERER=cairo LIBGL_ALWAYS_SOFTWARE=1 NO_AT_BRIDGE=1"
runuser -u wren -- env HOME=$H USER=wren XDG_RUNTIME_DIR=/tmp/xdg-wren $COMMON \
  timeout 290 dbus-run-session -- labwc -s 'sh /var/tmp/scenes.sh' >/var/tmp/shots/desktop.log 2>&1

# Wren Login, in demo mode, inside the same kiosk compositor greetd uses
mkdir -p -m 700 /tmp/xdg-root
env XDG_RUNTIME_DIR=/tmp/xdg-root $COMMON timeout 40 dbus-run-session -- cage -s -- sh -c \
  'WREN_GREETER_DEMO=1 python3 /usr/lib/wren/greeter.py & sleep 7; grim /var/tmp/shots/7-login.png; kill %1' \
  >/var/tmp/shots/login.log 2>&1

# Leave the system as we found it
userdel -r wren 2>/dev/null
rm -rf /tmp/xdg-wren /tmp/xdg-root
EOF

arch-chroot "$R" bash /var/tmp/run-desktop.sh >"$OUT/chroot.log" 2>&1 || echo "desktop exited with $?" >>"$OUT/chroot.log"
cp "$R"/var/tmp/shots/* "$OUT/" 2>/dev/null
rm -rf "$R/var/tmp/shots" "$R/var/tmp/scenes.sh" "$R/var/tmp/run-desktop.sh"
ls -la "$OUT"
