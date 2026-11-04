#!/usr/bin/env bash
# Start-up screen fix: load the graphics driver early and let Plymouth use the
# early display, so the Wren logo shows instead of three dots.
set -euo pipefail
bash /usr/lib/wren/setup-boot-splash.sh --rebuild
