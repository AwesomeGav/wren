#!/bin/sh
# Removes the "Loading Linux..." / "Loading initial ramdisk..." lines GRUB prints.
cfg=/boot/grub/grub.cfg
[ -f "$cfg" ] && sed -i "/^[[:space:]]*echo[[:space:]]*'Loading /d" "$cfg"
exit 0
