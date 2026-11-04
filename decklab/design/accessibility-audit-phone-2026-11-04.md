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

Ordered by how much they get in the way. Matt asked for all of them (2026-11-04), and all are fixed in the same change, as described under each; `decklab/tests/test_phone_accessibility.py` keeps them fixed.

### 1. Focus hides under the header, the deck tabs and the tab bar (WCAG 2.4.11, AA)

When Tab moves to a control near the bottom of the screen, the browser scrolls only far enough to bring it into the viewport, which leaves it behind the fixed tab bar; Shift+Tab does the same under the sticky header and the deck page's tab strip. On the deck page's Testing tab the "not played yet" deck links sit wholly under the tab bar; on Cards, 5 of 20 Shift+Tab steps landed wholly under the tab strip; on the Game log "Matt won" is mostly covered. Seen on every deck tab and the Game log, in both orientations.

Screenshots: `findings/testing-link-focus-under-tabbar.png`, `findings/gamelog-focus-under-tabbar.png`, `findings/cards-row-focus-under-tabbar.png`.

Fixed: every focusable control has `scroll-margin-top` and `-bottom` from `--focus-clear-top` (the header, plus the deck tab strip on the deck page) and `--focus-clear-bottom` (the tab bar, plus a page's own bar), at no specificity so a part's own scroll margin still wins (`base.css`). Root `scroll-padding` was the first idea, but it would have doubled the scroll margins several parts already set.

### 2. The Game log's games are hard to tell apart by ear

Each game is an h3 naming only the result ("Matt won", "Matt won", "Sam won"…), with the date and decks after it, so a screen reader's heading list is fourteen near-identical lines; every game's "Correct this game" button and "Recorded decklists" disclosure has the same name too.

Fixed: the heading says "Matt won: Gruul Ramp vs Izzet Prowess, 31 Oct" to a screen reader (the decks and date in a hidden span; the words shown are unchanged), and each game's Recorded decklists and Correct this game are described by it (`aria-describedby`). A Commander pod's card does the same.

### 3. Large text (the phone's browser text size at 200 %)

The tab bar's labels truncate ("Testi…", "Colle…", "Shop…"), the skip link peeks out as a purple bar at the top of every page, and the avatar's initial spills out of its circle. Everything else reflows.

Screenshots: `findings/text-200-gamelog.png`, `findings/text-200-deck-overview.png`.

Fixed: the tab bar's labels wrap (hyphenated) and the bar grows, with `shell.js` keeping `--shell-bottom` at its height so the page's padding and the focus clearance follow; the skip link hides by its own height (a transform); the avatar's initial stops growing at 18 px (`--fs-avatar`), as it's a picture of the person and the button's name says who. The tab labels themselves grow only to 15 px (`--fs-tab`), where "Collection" still fits a phone's tab; past that they wrap.

Found while checking the fix: the deck page's own layout grew wider than the screen at 200 % text, pushing the fixed tab bar off it (the earlier reflow check missed it, as the phone's layout viewport widened with the page). Four parts did it: the sleeves tile's "66 needed · 200 owned · 134 spare" chip (now wraps), the Cards tab's price table (its number columns are capped at a share of the width), Practice's colour-source table (now its own sideways-scrolling region, keyboard-reachable and named) and Practice's reading list (long titles wrap).

### 4. The Cards tab skips a heading level (axe: heading-order, moderate)

The deck's h1 is followed straight by h3 type groups ("Creatures (26)"), with no h2 for the list. Flagged in all four Cards runs.

Fixed: a visually hidden h2 naming the list ("Planned list" or "Play-now list") comes first on the Cards tab.

### 5. Library tiles read as one long sentence

Each deck tile is one link whose name is the whole tile, about 30 words with the sleeves and deck box ("Colours: red, green Gruul Ramp Matt 60 + 6 sideboard Last played 2026-10-31 6 games 53 owned 13 to get Sleeves Dragon Shield Matte (black) Deck box Ultimate Guard Boulder 100+ (black)"). Nothing is missing, but the title isn't heard first and the list is slow to skim.

Fixed: the cover's pips are hidden from screen readers and the colours are said after the title instead ("Gruul Ramp (Colours: red, green) Matt …"). The rest of the tile is still in the link's name: shortening it further would hide facts people use.

### 6. Smaller points

- The deck Overview has two h3s with the same text ("Sideboard: only against stronger opponents"), one in Sideboard plan and one in How to play. Left as it is: the same notes are deliberately shown in both places, each under its own h2.
- Outside this slice's pages: Collection's paging and Receive delivery scroll smoothly even when reduced motion is asked for (`collection-rows.js`, `collection.js`, `receipt-workflow.js` pass `behavior: "smooth"`). Fixed: `scrollBehaviour()` in core.js gives `"auto"` under reduced motion, and those scrolls use it.

## Notes for the next runs

- Playwright's full-page screenshot under mobile emulation switches the page to `(pointer: fine)` afterwards, so measure before taking one, or screenshot by resizing the viewport instead (the scripts do).
- UI-KIT.md now has an Accessibility section. The story's remaining parts are every other page, the lab density, and a check with a real screen reader.
