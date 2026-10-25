# Deck Lab's typefaces

The page's two typefaces ([design/visual-design.md](../design/visual-design.md) 2.3) are files in `decklab/web/fonts/`, served by Deck Lab itself: nothing is loaded from the internet. Both are under the SIL Open Font License 1.1; the licence texts are here because the server serves only `.woff2` from that folder, and each file's name table keeps the licence too.

| File | Family | Source | Version | Axis |
|---|---|---|---|---|
| `web/fonts/figtree.woff2` | Figtree | `google/fonts`, `ofl/figtree/Figtree[wght].ttf` | 2.002 | wght 300-900 |
| `web/fonts/figtree-italic.woff2` | Figtree, italic | `google/fonts`, `ofl/figtree/Figtree-Italic[wght].ttf` | 2.002 | wght 300-900 |
| `web/fonts/jetbrains-mono.woff2` | JetBrains Mono | `google/fonts`, `ofl/jetbrainsmono/JetBrainsMono[wght].ttf` | 2.211 | wght 100-800 |

Downloaded 2026-10-24 and subset with fontTools (with the brotli module, for woff2) to Basic Latin, Latin-1 and the punctuation Deck Lab prints:

```
python -m fontTools.subset "Figtree[wght].ttf" --flavor=woff2 --output-file=figtree.woff2 \
  --name-IDs='*' --name-languages='*' --layout-features=kern,liga,calt,tnum,lnum,zero,case,ss01 \
  --unicodes=U+0020-007E,U+00A0-00FF,U+0131,U+0152-0153,U+02C6,U+02DA,U+02DC,U+2009,U+2013-2014,U+2018-201A,U+201C-201E,U+2020-2022,U+2026,U+2032-2033,U+2039-203A,U+2044,U+20AC,U+2122,U+2190-2193,U+2212,U+2215,U+2248,U+2260,U+2264-2265,U+25B2,U+25BC,U+00D7
```

The same command makes `figtree-italic.woff2` from `Figtree-Italic[wght].ttf` and `jetbrains-mono.woff2` from `JetBrainsMono[wght].ttf`. `--name-IDs='*'` keeps each file's name table, its licence entries included.

A character outside the subset, or one the family doesn't have, is drawn in the system font that follows in `--font` or `--font-mono`, as before. Figtree has no ▲ ▼ ′ ″ ≈ or thin space (so the table sort arrows come from the system font), and neither family has the symbols the page uses for menus and marks (⋯ ▾ ✓ ↻ ⚑ ⤢ ★ φ). JetBrains Mono has every listed character but the thin space. To add characters, subset the original files again with a longer `--unicodes` list.
