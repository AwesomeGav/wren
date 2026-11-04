# Wren Linux

A calm, modern desktop that stays fast on old and low-power computers.
Built on Arch Linux, with its own desktop shell, look and installer. You never need keyboard shortcuts.

## What you get

- **Its own desktop**: a floating dock-style panel, a searchable app grid (click the wren),
  and a quick-settings panel for Wi-Fi, Bluetooth, volume, brightness, battery, Do Not Disturb and power.
- **One consistent look**: warm graphite and ember colors across windows, apps, notifications,
  the login screen and the lock screen.
- **Modern apps**: Firefox, Files, Text Editor, Image Viewer, Calculator, Archive Manager.
- **Its own installer**: a point-and-click setup that opens when you boot the USB stick and
  works on both new (UEFI) and older (BIOS) computers, with no internet needed.
- **Built for weak hardware**:
  - Lightweight Wayland desktop (labwc) with animations off
  - Compressed RAM swap (zram) so 2–4 GB machines can keep more open
  - earlyoom keeps the system responsive when memory runs out
  - TLP battery tuning, hardware video decoding in Firefox
  - The file indexer is switched off, logs are kept small, and SSDs get a weekly trim

## Get it

1. Open the **Releases** page of this repo and download the latest `wren-….iso`.
2. Flash it to a USB stick (4 GB or more) with [balenaEtcher](https://etcher.balena.io) or [Ventoy](https://www.ventoy.net).
3. Boot the computer from the USB stick. Wren starts and the installer opens.
4. Choose **Keep Exploring** to try it first, or **Install Wren** and follow the steps.
   You can reopen the installer any time from the app grid.

> ⚠️ Installing erases the disk you choose. Back up anything important first.

## How it's built

Every push to `main` makes GitHub build a fresh ISO, take screenshots of the desktop
(see the `screenshots` branch), test the installer on a virtual disk, and publish the ISO on the Releases page.

| Path | What it is |
|---|---|
| `packages.txt` | Every package Wren adds on top of Arch |
| `rootfs/` | The desktop: Wren Shell, theme, panel, window style, login and lock screens |
| `live/` | The installer (only on the USB stick) |
| `tests/` | Installer test and screenshot scripts used by the build |
| `wren-setup` | Turns an existing Arch install into Wren |
| `build.sh` | Builds the ISO from Arch's official live profile |
