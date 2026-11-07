#!/usr/bin/env bash
# Floe Passkeys: the built-in passkey authenticator needs the uhid module and
# access for the signed-in person. Also undoes the short-lived Bitwarden add-on setting.
set -uo pipefail
pacman -Q python-cryptography >/dev/null 2>&1 || pacman -S --needed --noconfirm python-cryptography || true
modprobe uhid 2>/dev/null || true
udevadm control --reload 2>/dev/null || true
udevadm trigger --action=change /sys/devices/virtual/misc/uhid 2>/dev/null || true
pol=/etc/firefox/policies/policies.json
if [[ -f $pol ]] && grep -q '446900e4-71c2-419f-a6a7-df9c091e268b' "$pol"; then
  python3 - "$pol" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
pol = d.get("policies", {})
pol.get("ExtensionSettings", {}).pop("{446900e4-71c2-419f-a6a7-df9c091e268b}", None)
if not pol.get("ExtensionSettings"):
    pol.pop("ExtensionSettings", None)
pol.pop("OfferToSaveLogins", None)
json.dump(d, open(p, "w"), indent=2)
PY
fi
