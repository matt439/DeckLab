# Accessibility audit: library, deck page and Game log on a phone (2026-11-04)

E11-S55's first slice: the audit, written up before any fix. It covers the library (`#/library`), every tab of the deck page (a 60-card deck and a Commander deck) and the Game log (`#/play`, alone and for one deck), on a 390 × 844 phone in portrait and 844 × 390 on its side, light and dark, with reduced motion asked for.

## How it was checked

- A full-data sandbox (local PostgreSQL, synthetic card data and art, the fixture decks, sleeves and deck boxes, token cards and 14 recorded games), as in the dark pass of 2026-10-27. The art is synthetic, so contrast over real card pictures is only sampled, not proven.
- axe-core 4.10 with the WCAG 2.0, 2.1 and 2.2 A and AA rules and its best-practice rules: 9 page views × 2 themes × 2 orientations, 36 runs.
- A keyboard walk: 70 presses of Tab (and 20 of Shift+Tab on two pages) from the top of each page, recording each focused control's name, its ring and whether something sits over it.
- Touch targets against the app's own 44 px floor, reflow at 320 px, text at 200 %, the headings and landmarks, the deck tabs' arrow keys, the card viewer's focus, and every running animation or transition under reduced motion.
- Text over gradients and pictures, which axe can't judge (166 nodes), by hiding the text and sampling the pixels behind it.

Not checked: a real screen reader (VoiceOver, TalkBack), real card art, and the Testing tab with saved Forge results (the sandbox has no Forge). Screenshots and the scripts are in the project files' `a11y-audit/` folder.

## What passed

- **Contrast:** no axe contrast failure on any page in either theme. The pixel sampling flagged only the colour pips and the ×N badges on card art, and both read clearly by eye (the badge has its own dark backing).
- **Names:** every control has an accessible name; icon buttons are named ("More for this deck", "Search decks and cards"), pips are named images ("Colours: red, green"), missing cards carry a hidden "Missing", charts' bars are named buttons.
- **Touch targets:** everything meets the 44 px floor on touch, except two narrow-but-tall controls on the Cards tab (the "Card" sort header and the "All" filter, both 44 px tall).
- **Reflow and zoom:** no sideways scroll at 320 px or at 200 % text.
- **Structure:** one h1 a page, header / main / footer and named navigation landmarks, live regions for the counts and toasts.
- **Keyboard:** a skip link first; the deck tabs follow arrow keys; the card viewer takes focus, keeps it, and gives it back to the row on Escape; every focused control has a visible ring (the key-card tiles and chart bars draw theirs on a wrapper, which looks right).
- **Reduced motion:** only the header title's 0.15 s fade and a slowed spinner remain, both acceptable.

## Findings

Ordered by how much they get in the way. Each has a proposed fix slice; none is fixed yet.

### 1. Focus hides under the header, the deck tabs and the tab bar (WCAG 2.4.11, AA)

When Tab moves to a control near the bottom of the screen, the browser scrolls only far enough to bring it into the viewport, which leaves it behind the fixed tab bar; Shift+Tab does the same under the sticky header and the deck page's tab strip. On the deck page's Testing tab the "not played yet" deck links sit wholly under the tab bar; on Cards, 5 of 20 Shift+Tab steps landed wholly under the tab strip; on the Game log "Matt won" is mostly covered. Seen on every deck tab and the Game log, in both orientations.

Screenshots: `findings/testing-link-focus-under-tabbar.png`, `findings/gamelog-focus-under-tabbar.png`, `findings/cards-row-focus-under-tabbar.png`.

Fix (S): `scroll-padding-top` and `scroll-padding-bottom` on the root, from `--shell-top` (plus the deck tab strip on the deck page) and the tab bar's height with the safe area, so focus and in-page links stop clear of the bars. A stylesheet test pins them.

### 2. The Game log's games are hard to tell apart by ear

Each game is an h3 naming only the result ("Matt won", "Matt won", "Sam won"…), with the date and decks after it, so a screen reader's heading list is fourteen near-identical lines; every game's "Correct this game" button and "Recorded decklists" disclosure has the same name too.

Fix (S): put the decks and date in the heading ("Matt won: Gruul Ramp vs Izzet Prowess, 31 Oct", the words shown staying as they are), and describe each game's buttons by that heading (`aria-describedby`).

### 3. Large text (the phone's browser text size at 200 %)

The tab bar's labels truncate ("Testi…", "Colle…", "Shop…"), the skip link peeks out as a purple bar at the top of every page, and the avatar's initial spills out of its circle. Everything else reflows.

Screenshots: `findings/text-200-gamelog.png`, `findings/text-200-deck-overview.png`.

Fix (S): let the tab bar's labels wrap to two lines or hide them under the icons past a size, move the skip link off-screen by its own height rather than a fixed 60 px, and size the avatar's letter to its circle.

### 4. The Cards tab skips a heading level (axe: heading-order, moderate)

The deck's h1 is followed straight by h3 type groups ("Creatures (26)"), with no h2 for the list. Flagged in all four Cards runs.

Fix (S): an h2 for the list ("Planned list", visually hidden where the page already shows it), or the groups as h2.

### 5. Library tiles read as one long sentence

Each deck tile is one link whose name is the whole tile, about 30 words with the sleeves and deck box ("Colours: red, green Gruul Ramp Matt 60 + 6 sideboard Last played 2026-10-31 6 games 53 owned 13 to get Sleeves Dragon Shield Matte (black) Deck box Ultimate Guard Boulder 100+ (black)"). Nothing is missing, but the title isn't heard first and the list is slow to skim.

Fix (S, optional): name the link by the deck's title and describe it by the rest (`aria-describedby`), so the title comes first and the details follow after a pause.

### 6. Smaller points

- The deck Overview has two h3s with the same text ("Sideboard: only against stronger opponents"), one in Sideboard plan and one in How to play.
- Outside this slice's pages: Collection's paging and Receive delivery scroll smoothly even when reduced motion is asked for (`collection-rows.js`, `collection.js`, `receipt-workflow.js` pass `behavior: "smooth"`). Fix (S): a shared helper that uses `"auto"` under reduced motion.

## Notes for the next runs

- Playwright's full-page screenshot under mobile emulation switches the page to `(pointer: fine)` afterwards, so measure before taking one, or screenshot by resizing the viewport instead (the scripts do).
- The story's remaining parts (every page in both densities, UI-KIT's Accessibility section, a fixture test per fix) follow the fix slices.
