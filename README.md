# Wren Linux

A modern, point-and-click Linux distro that stays fast on old and low-power computers.
Built on Arch Linux, like Omarchy, but you never need to learn keyboard shortcuts.

## What you get

- **A familiar desktop**: an **Apps** button and taskbar at the bottom, windows with
  minimize / maximize / close buttons, and a right-click menu on the desktop.
- **Drag to snap**: drag a window to the top edge to maximize it, or to a side to fill half the screen.
- **Clickable everything**: Wi-Fi, Bluetooth, volume, brightness, battery and power are all in the bottom bar.
- **Built for weak hardware**:
  - Lightweight Wayland desktop (labwc), with no blur or animation overhead
  - Compressed RAM swap (zram) so 2–4 GB machines can keep more open
  - earlyoom keeps the system responsive when memory runs out
  - TLP battery tuning for laptops
  - Hardware video decoding enabled in Firefox, so video uses less battery
  - Small system logs and weekly SSD trim
- **Included apps**: Firefox, Thunar files, Mousepad text editor, Ristretto image viewer,
  archive manager, sound / display / network / Bluetooth settings.

Keyboard shortcuts still exist if you want them (press the Windows key to open Apps),
but nothing needs them.

## Get it

1. Open the **Releases** page of this repo and download the latest `wren-….iso`.
2. Flash it to a USB stick (4 GB or more) with [balenaEtcher](https://etcher.balena.io) or [Ventoy](https://www.ventoy.net).
3. Boot the computer from the USB stick. The Wren desktop starts automatically, so you can try it first.
4. To install, click **Apps → Install Wren Linux** and follow the on-screen steps.

> ⚠️ Installing erases the disk you choose. Back up anything important first.

## How it's built

Every push to `main` makes GitHub build a fresh ISO and publish it on the Releases page.

| Path | What it is |
|---|---|
| `packages.txt` | Every package Wren adds on top of Arch |
| `rootfs/` | Desktop settings and tuning, used by both the live USB and installed systems |
| `live/` | Files only for the live USB (the installer) |
| `wren-setup` | Turns a fresh Arch install into Wren (the installer runs it automatically) |
| `build.sh` | Builds the ISO from Arch's official live profile |

To build on your own Arch machine instead: `sudo pacman -S archiso && sudo bash build.sh`.
