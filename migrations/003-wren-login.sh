#!/usr/bin/env bash
# Switch the login screen to Wren Login (password-only sign-in).
set -euo pipefail
conf=/etc/greetd/config.toml
if [[ -f $conf ]] && grep -q -- '-- regreet"' "$conf"; then
  sed -i 's#-- regreet"#-- wren-greeter"#' "$conf"
fi
systemd-tmpfiles --create /usr/lib/tmpfiles.d/wren-greeter.conf || true
