#!/usr/bin/env bash
# Adds the Wren start-up screen to systems installed before it existed.
set -euo pipefail
bash /usr/lib/wren/setup-boot-splash.sh --rebuild
