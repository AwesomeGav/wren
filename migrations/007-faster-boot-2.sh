#!/usr/bin/env bash
# Faster start-up, part 2: don't wait for a TPM chip at boot (old computers can
# stall up to 90 s), mask services that wait for the network or for disks to
# "settle", shorter waits for the start-up screen. Rebuilds the boot menu and image.
set -euo pipefail
bash /usr/lib/wren/setup-boot-splash.sh --rebuild
