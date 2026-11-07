#!/usr/bin/env bash
# Keep firmware boot options (network boot, USB, other loaders) out of the boot menu.
set -uo pipefail
bash /usr/lib/wren/setup-boot-splash.sh --rebuild || true
