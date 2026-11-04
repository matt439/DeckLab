# Accessibility audit: the other pages and the lab layout (2026-11-04)

E11-S55's second slice, after [the phone audit](accessibility-audit-phone-2026-11-04.md) of the library, the deck page and the Game log. It covers every other page: Who are you?, Wishlist, Shopping, Sleeves & boxes, Tokens, Collection, Build decks (`#/assembly`), a deck's History, Compare, Activity, Receive delivery, Settings, Visibility, the editor (a saved deck and a new one) and Testing (`#/matchups`); and every page, the first slice's included, in the lab layout.

## How it was checked

- The same full-data sandbox as before, rebuilt in a cloud container: local PostgreSQL, synthetic card data and art, the eleven fixture decks (three built with sleeves and deck boxes), the collection, token cards, the purchase queue, a wishlist, a pending order with a check and 14 recorded games. The art is synthetic.
- axe-core 4.10 with the WCAG 2.0, 2.1 and 2.2 A and AA rules and its best-practice rules: 24 page views on a 390 × 844 phone and a 1440 × 900 desktop (the lab: a fine pointer, 1000 px and up), light and dark, with reduced motion asked for; 96 runs.
- A keyboard walk of 70 presses of Tab on every run, recording each focused control's name, its ring and whether something sits over it.
- Touch targets against the 44 px floor on the phone and on an iPad on its side (1180 × 820, touch: the lab layout at touch sizes).
- Reflow at 320 px and text at 200 % on the phone and the desktop, with headings checked for one h1 and no skipped level, and every field for a label.

Not checked: a real screen reader, real card art, Testing with saved Forge results (the sandbox has no Forge), and the sheets and dialogs one at a time (they are native `<dialog>`s, which keep focus by themselves; the card viewer was checked in the first slice).

## What passed

- **Contrast:** no axe contrast failure on any page, in either theme or layout.
- **Labels and names:** every field has a label; every control has a name. The Who are you? screen had no findings at all.
- **Headings:** one h1 a page everywhere; no skipped level except the editor on a phone (finding 3).
- **Reflow and large text:** no sideways scroll at 320 px or 200 % text on any page but the editor (finding 2), on the phone and the desktop.
- **Focus rings:** every focused control shows a ring. The ones the walk flagged draw it on a wrapper, which looks right: the top bar's search field (its pill), card tiles (the tile), chart bars (the bar's band) and the Settings date field (checked by hand).
- **Lab layout:** apart from the shared findings below, the desktop needed nothing of its own: nothing hid under the sticky header, and the lab's denser controls are only offered with a fine pointer.
- **Reduced motion:** only the header title's 0.15 s fade and a slowed spinner remain, as on the phone.

## Findings

Ordered by how much they get in the way. All are fixed in the same change; `decklab/tests/test_page_accessibility.py` keeps them fixed.

### 1. Focus hides under Build decks' and Receive delivery's bars (WCAG 2.4.11, AA)

The first slice's fix keeps focus clear of a page's action bar by its usual height, `--bar-h` (72 px on a phone, 60 in the lab). These two pages' bars grow well past it, with a status line, the step's buttons or a warning: 165 px on Build decks and 139 px on Receive delivery on a phone, about 90 px on the desktop. Tabbing down Build decks left 34 of 70 focus stops on a phone, and 13 on the desktop, under the bar ("Abrade: choose which printing", "Choose sleeves"); on Receive delivery 4 to 10 ("Inspect Night's Whisper").

Fixed: `shell.js`'s `watchPageBar()` keeps `--page-bar-h` at the page's action bar's real height (a ResizeObserver on whichever bar `#main` holds), and `base.css` clears the larger of `--bar-h` and it, as does Build decks' own scroll margin.

### 2. The editor is wider than a 320 px phone (WCAG 1.4.10, AA)

On a 320 px screen, and at 200 % text on a 390 px phone, the editor's list pushed the page 15 px (63 px) wider than the screen: a card's "2 missing" badge had a column with no room left, after the stepper, the name and ⋯, and spilled out.

At 200 % text the Planned list / Play-now list switch, kept to one row with its words unbroken, pushed it 12 px wider as well.

Fixed: on a narrow list (`@container quick-list (max-width: 20em)`, so large text counts too), the badge takes a line of its own under the printing, and the switch's words wrap inside their buttons once the row can't hold them. At 390 px and normal text nothing changes.

### 3. The editor skips a heading level on a phone

When the Cards and Notes tabs show, the list had no h2: the h1 was followed straight by the sections' h3s ("Deck 60"), and in the lab the sections came after the Checks pane's h3s.

Fixed: a visually hidden h2 naming the list ("Planned list", "Play-now list") sits beside the tabs, as the deck page's Cards tab has.

### 4. The top bar's search field carries an ARIA attribute it may not (axe: aria-allowed-attr, critical)

The desktop's search field set `aria-expanded`, which a search field (role searchbox) may not have; its results are groups of links, not a listbox, so it isn't a combobox either. Flagged on every desktop run.

Fixed: the attribute is gone. The field still names its results (`aria-controls`), and its status line says what was found.

### 5. Landmarks with the same name (axe: landmark-unique)

- Sleeves & boxes named each owner's parts only by kind, so Matt's and the shared "Sleeves (1)" were two regions of the same name, and each kind was an h2 beside its owner's h2.
- Shopping's two queue tables (To buy, Long-term plan) were both "Purchase queue table, scroll for more columns".
- The lab editor's Add pane held a second region also named "Add cards".

Fixed: an accessory part is named by its owner and kind ("Matt Sleeves (1)") and its kind is an h3 under the owner's h2; the long-term table is "Long-term plan table"; the Add part inside the pane is a plain group.

### 6. Compare's tables have an empty header (axe: empty-table-header)

The first column's header, over the row names, was empty. Fixed: it says "Figure" to a screen reader.

### 7. Small touch targets

- Compare's two deck titles (the links to each deck) were 20 px tall on a phone. Fixed: 44 px wherever there's no fine pointer.
- Build decks' **Which printing?** buttons were 32 px tall at every size, so an iPad on its side (lab layout, touch) had 32 px targets. Fixed: 44 px on touch.

Left as they are: the deck page's card links inside the play guide's sentences (19 px tall), which WCAG 2.5.8 exempts as links in text, as the first slice found.

## Notes for the next runs

- The scripts are in the project files' `a11y-audit/tools/` (`audit2.js` for this slice's pages and both layouts, `extra2.js` for reflow and large text, `tl.js` for touch targets in the lab, `sem2.js` for headings and labels).
- An inline link that wraps onto two lines is reported as "covered" by its neighbour (the walk samples the middle of its box); Testing's "Not played yet against" links are that, not a finding.
- Left for E11-S55: a real screen reader (VoiceOver, TalkBack, NVDA), real card art, Testing with Forge results, and the sheets one by one.
