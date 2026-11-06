# Live USB only: start the Wren desktop when the live account logs in on the first screen.
if [ "$(id -un)" = wren ] && [ -z "${WAYLAND_DISPLAY:-}" ] && [ -z "${WREN_SESSION:-}" ] && [ "$(tty)" = /dev/tty1 ]; then
  exec wren-session
fi
