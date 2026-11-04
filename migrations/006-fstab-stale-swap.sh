#!/usr/bin/env bash
# Faster start-up: remove swap entries from /etc/fstab whose disk doesn't exist.
# Earlier installers could record the live USB's temporary zram swap, which gets a
# new ID every boot, so each start-up waited 90 seconds for it.
set -uo pipefail
[[ -f /etc/fstab ]] || exit 0
cp -n /etc/fstab /etc/fstab.before-wren-fix
python3 - <<'PY'
import subprocess
path = "/etc/fstab"
out, changed = [], False
for line in open(path).read().splitlines():
    parts = line.split()
    if len(parts) >= 3 and not line.lstrip().startswith("#") and parts[2] == "swap":
        dev = parts[0]
        if dev.startswith("/dev/zram"):
            found = False
        elif dev.startswith(("UUID=", "PARTUUID=", "LABEL=", "PARTLABEL=")):
            found = subprocess.run(["blkid", "-t", dev], capture_output=True).returncode == 0
        else:
            found = subprocess.run(["test", "-b", dev]).returncode == 0
        if not found:
            out.append("# Removed by Wren (this disk doesn't exist; it slowed start-up): " + line)
            changed = True
            continue
    out.append(line)
if changed:
    open(path, "w").write("\n".join(out) + "\n")
    print("Removed a stale swap entry from /etc/fstab")
PY
systemctl daemon-reload >/dev/null 2>&1 || true
