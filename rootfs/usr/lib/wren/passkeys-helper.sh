#!/bin/bash
# Turns the Bitwarden add-on on or off in Firefox for everyone on this computer
# (Firefox installs it by itself on its next start). Run through pkexec.
#   passkeys-helper.sh enable | disable
set -euo pipefail
action="${1:-}"
[[ $action == enable || $action == disable ]] || { echo "usage: $0 enable|disable" >&2; exit 2; }
mkdir -p /etc/firefox/policies
python3 - "$action" <<'PY'
import json, os, sys
path = "/etc/firefox/policies/policies.json"
GUID = "{446900e4-71c2-419f-a6a7-df9c091e268b}"
try:
    data = json.load(open(path))
except (OSError, ValueError):
    data = {}
pol = data.setdefault("policies", {})
ext = pol.setdefault("ExtensionSettings", {})
if sys.argv[1] == "enable":
    ext[GUID] = {"installation_mode": "normal_installed",
                 "install_url": "https://addons.mozilla.org/firefox/downloads/latest/bitwarden-password-manager/latest.xpi"}
    # Bitwarden offers to save logins and passkeys, so Firefox doesn't ask as well
    pol["OfferToSaveLogins"] = False
else:
    ext.pop(GUID, None)
    pol.pop("OfferToSaveLogins", None)
    if not ext:
        pol.pop("ExtensionSettings", None)
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(data, f, indent=2)
os.chmod(tmp, 0o644)
os.replace(tmp, path)
PY
