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
wren-shell search;   shot 17-search 3; wren-shell search
wren-osd volume up; sleep 0.4; grim /var/tmp/shots/16-volume-popup.png
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
  >/var/tmp/shots/terminal.log 2>&1 & pid=$!; shot 9-terminal 6; kill $pid; sleep 1
wren-store >/var/tmp/shots/store.log 2>&1 & pid=$!; shot 10-store 18; kill $pid; sleep 2
WREN_STORE_PAGE=cat:Game wren-store >>/var/tmp/shots/store.log 2>&1 & pid=$!; shot 10-store-games 15; kill $pid; sleep 2
WREN_STORE_PAGE=app:org.gimp.GIMP wren-store >>/var/tmp/shots/store.log 2>&1 & pid=$!; shot 10-store-app 15; kill $pid; sleep 2
WREN_STORE_PAGE=search:minecraft wren-store >>/var/tmp/shots/store.log 2>&1 & pid=$!; shot 10-store-search 15; kill $pid; sleep 2
wren-settings system >/var/tmp/shots/settings.log 2>&1 & pid=$!; shot 11-settings-system 5
for page in about devices personalization apps time power display accounts; do
  wren-settings $page >>/var/tmp/shots/settings.log 2>&1; shot "11-settings-$page" 4
done
# The window list reader used to stop background apps
PYTHONPATH=/usr/lib/wren python3 -m winlist >/var/tmp/shots/winlist.log 2>&1
# Dark mode, switched live while Settings stays open
wren-theme set dark sky >/var/tmp/shots/theme.log 2>&1; shot 12-dark-settings 5
kill $pid; sleep 1
shot 12-dark-desktop 2
wren-shell launcher; shot 12-dark-launcher 3; wren-shell launcher
wren-shell control;  shot 12-dark-quick-settings 3; wren-shell control
nautilus --new-window "$HOME" >/dev/null 2>&1 & shot 12-dark-files 8
nautilus -q; sleep 1
wren-terminal >/dev/null 2>&1 & pid=$!; shot 12-dark-terminal 5; kill $pid; sleep 1
wren-theme set light violet >>/var/tmp/shots/theme.log 2>&1
wren-shell launcher; shot 13-light-violet-launcher 4; wren-shell launcher
wren-theme set light teal >>/var/tmp/shots/theme.log 2>&1; sleep 2
# A window zooming open, caught part-way through
echo "compositor: $(pgrep -x wayfire >/dev/null && echo wayfire || echo labwc)" >/var/tmp/shots/compositor.txt
gnome-calculator >/dev/null 2>&1 &
for i in 1 2 3 4 5 6 7 8; do grim "/var/tmp/shots/15-open-anim-$i.png"; done
sleep 2; pkill -x gnome-calculator; sleep 1
cp "$HOME/.cache/wren/panel.log" /var/tmp/shots/panel.log 2>/dev/null
# Screen saver: fading in, then a few seconds later
pkill -USR1 -f "m screensaver"; sleep 0.5   # one started by the idle timer: where is it?
wren-screensaver --stop; sleep 1
wren-screensaver --preview & pid=$!
shot 18-screensaver-a 8; shot 18-screensaver-b 5
pkill -USR1 -f "m screensaver"; sleep 0.5
pgrep -af screensaver >>"$HOME/.cache/wren/screensaver.log"
cp "$HOME/.cache/wren/screensaver.log" /var/tmp/shots/screensaver.log
wren-screensaver --stop; sleep 1; kill $pid 2>/dev/null
# Lock screen last: a killed locker leaves the session locked
wren-lock >/var/tmp/shots/lock.log 2>&1 & shot 14-lock-screen 5
wren-logout
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

COMMON="WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 GSK_RENDERER=cairo LIBGL_ALWAYS_SOFTWARE=1 NO_AT_BRIDGE=1 XDG_CONFIG_DIRS=/etc/xdg/wren:/etc/xdg"
WAYFIRE_ENV="WLR_RENDERER=gles2 WLR_RENDERER_ALLOW_SOFTWARE=1 XDG_CURRENT_DESKTOP=Wren:wlroots"
# vgem gives a render node backed by software (Mesa llvmpipe) on machines without a GPU
RN=""
for c in /sys/class/drm/card[0-9]*; do
  # the vgem card node: buffers can be made there (render nodes refuse plain buffers)
  [ "$(basename "$(readlink -f "$c/device/driver" 2>/dev/null)")" = vgem ] && RN=/dev/dri/$(basename "$c")
done
[ -n "$RN" ] || RN=$(ls /dev/dri/renderD* 2>/dev/null | head -1)
[ -n "$RN" ] && { chmod 666 /dev/dri/*; WAYFIRE_ENV="$WAYFIRE_ENV WLR_RENDER_DRM_DEVICE=$RN"; }
echo "render node: ${RN:-none}" >/var/tmp/shots/render-node.txt
# The real Wren window manager (Wayfire), with the scenes added to its start-up list
runuser -u wren -- env HOME=$H XDG_RUNTIME_DIR=/tmp/xdg-wren wren-theme ensure >/var/tmp/shots/theme-ensure.log 2>&1
cp "$H/.config/wren/wayfire.ini" /var/tmp/wayfire-test.ini
printf 'scenes = sh /var/tmp/scenes.sh\n' >>/var/tmp/wayfire-test.ini
cp /var/tmp/wayfire-test.ini /var/tmp/shots/wayfire-test.ini.txt
chmod 644 /var/tmp/wayfire-test.ini
runuser -u wren -- env HOME=$H USER=wren XDG_RUNTIME_DIR=/tmp/xdg-wren $COMMON $WAYFIRE_ENV \
  timeout 600 dbus-run-session -- wayfire -c /var/tmp/wayfire-test.ini >/var/tmp/shots/desktop.log 2>&1
if [ ! -f /var/tmp/shots/1-desktop.png ]; then
  # Wayfire couldn't start here: fall back like a real computer would
  echo "Wayfire failed; using labwc" >>/var/tmp/shots/desktop.log
  runuser -u wren -- env HOME=$H USER=wren XDG_RUNTIME_DIR=/tmp/xdg-wren $COMMON WLR_RENDERER=pixman \
    timeout 540 dbus-run-session -- labwc -m -s 'sh /var/tmp/scenes.sh' >/var/tmp/shots/desktop-labwc.log 2>&1
fi

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
