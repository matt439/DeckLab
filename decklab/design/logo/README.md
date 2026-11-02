# Deck Lab's logo

The "card counter D" (chosen by Matt, 2026-11-02): a white geometric D on the accent violet (`#6236c4`), whose counter is a playing card tilted 12 degrees. It's in the accent colour because no mana colour is purple.

- `logo.svg`: the mark on a rounded tile. `decklab/web/icons/icon-32.png` (the favicon and the top bar's brand) is drawn from it.
- `logo-maskable.svg`: a full-bleed square with the D scaled to 0.78, so it stays inside the 80% safe zone when the icon is masked. `icon-192.png`, `icon-512.png` (the manifest's `any` and `maskable` icons) and `apple-touch-icon.png` are drawn from it.

To redraw the PNGs, render each SVG at 1024 px (a headless Edge or Chrome screenshot on a transparent background) and scale it down with Lanczos to 32, 180, 192 and 512 px. Keep the four file names and sizes: `decklab/tests/test_web.py` checks them.
