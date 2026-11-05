# Review: the More menus (2026-11-05)

E11-S61's review. Matt couldn't find Build decks on the iPad, though he had used it before, because it was in the deck page's More. That button has since moved out: the deck page's head now has **Build deck** (or **Review build**) beside Edit. This review lists every item in every More menu at each width, says what it opens and whether there's already another way to it in plain sight, and recommends keep, move into plain sight or remove. Matt decides; nothing here changes the page.

## How it was checked

- **The code, not a running page.** The menus come from the routes table (`decklab/web/core.js`, `ROUTES`, each route's `nav`), the shell (`decklab/web/shell.js`, `drawShell`), the deck page's head (`decklab/web/deck.js`, `deckHeader` and `deckMoreItems`) and each page's `pageHead({ more })`. The widths come from `shell.css`, `deck.css` and `tokens.css`.
- **Page visits weren't available.** The visits are on the live server's database; this PC's development database doesn't have them (`python -m decklab.db visits --days 90` here says the database doesn't exist). So the recommendations below rest on the structure. Visits also record only pages opened (a route, and a deck for the deck, editor and History pages), never a menu click, so they can say how often Build decks or the Game log is opened but not whether people reached it through More, and nothing about actions such as Copy decklist or Rename deck. To weigh the page items with real numbers, run this on the server PC (read-only, and it gives counts by page only, no people):

  ```
  python -m decklab.db sql "select route, sum(opens) as opens, count(distinct day) as days from ops.visit_page where day >= current_date - 90 group by route order by opens desc"
  ```

## The widths

| Width | Who it is | Navigation | The deck page's More |
|---|---|---|---|
| 1000 px and up (the lab) | the desktop, an iPad 11-inch on its side (1194 px) | top bar: Decks · Testing · Collection · Shopping · **More ▾**, then search and the avatar | "More ▾" beside Edit and Build deck |
| 600 to 999 px, 501 px tall or more | an iPad 11-inch upright (834 px) | casual: a header and a bottom tab bar, Decks · Testing · Collection · Shopping · **More** (a sheet) | "More ▾" beside Edit and Build deck |
| under 600 px | a phone | the same tab bar and sheet | a square "⋯" beside Edit |

A phone on its side is the exception: any landscape screen 500 px tall or less gets the lab's top bar from 600 px wide (`shell.css`, the casual query), and most phones on their side are 667 to 932 px wide. So the lab's top bar shows from 1000 px, or from 600 px on a phone on its side. Its bar scrolls away with the page and keeps the search as an icon, as it has no room beside the pills for the field. The menus hold the same items in both densities. A member's tab bar has no Shopping (three tabs and More), and a member never sees Build decks or Sleeves & boxes.

## The top bar's More (and the phone's More sheet)

In the lab the top bar's More ▾ holds six pages. Under 1000 px the More sheet holds the same six, then the avatar menu's pages: Who sees what (when there's a switch to show) and Settings (admins).

| Item | Opens | Already in plain sight? | Recommendation |
|---|---|---|---|
| Tokens | `#/tokens`, the token and reminder cards | the deck page's Tokens part ("Edit your tokens"), Build decks' More, Receive delivery's links | **Keep.** Upkeep, reached from where tokens come up. |
| Sleeves & boxes (home only) | `#/accessories` | the deck page's kit **Choose…**, Build decks' More and its Choose sleeves | **Keep.** Mostly reached through a deck's kit. |
| Build decks (home only) | `#/assembly`, the packing plan | the deck page's **Build deck** / **Review build**, the Overview's In its box **Review build**, the Collection page's More | **Move into plain sight in the lab from 1000 px:** a fifth top-bar pill after Shopping. It's the step before every game night and the item Matt lost. Below 1000 px leave it in More (the sheet, or a phone on its side's More ▾): a fifth tab would crowd a 375 px bar, a fifth pill a phone on its side's, and the deck page's button covers the usual way in. |
| Game log | `#/play`, played games, pods and sideboard plans | none from the deck page except its More; the Overview's Played at home panel says when it was last played but doesn't link | **Keep, and add a plain-sight way in:** an "Open the Game log" (or "Record a game") link in the deck Overview's Played at home panel, as Compare already has. Recording a game after playing is a common step on a phone. |
| Wishlist | `#/wishlist` | Shopping's More and its empty state | **Keep.** Personal and occasional. |
| Activity | `#/activity`, the audit trail | none | **Keep.** A reference page, opened rarely. |
| Who sees what (sheet only) | `#/visibility` | the avatar menu | **Keep.** The sheet is where a phone user looks; the duplicate costs nothing. |
| Settings (sheet only, admins) | `#/settings` | the avatar menu | **Keep**, for the same reason. |

Making Build decks a main route (`nav: "main"`, after Shopping) isn't enough on its own. The tab bar takes only the first four main pages (`TAB_COUNT`), so the casual sheet would still hold it, but the lab's top bar draws every main page (`drawShell`'s `main.map`), and a phone on its side gets that bar from 600 px. A bare `nav: "main"` would add a fifth pill there too: on a phone 667 px wide the bar would need the logo, Decks · Testing · Collection · Shopping · Build decks · More ▾, the search icon and the avatar, and `.nav-items` doesn't wrap, so it risks overflowing. The change needs a rule as well: the Build decks pill shown only from 1000 px (a CSS rule on its nav item), with Build decks kept in the top bar's More ▾ below that, so a phone on its side still reaches it. Checking it means the bar at 667 px and 932 px landscape and at 1000 px. It would sit in the top bar for everyone who may see it (Matt and User1), and a member's top bar is unchanged.

## The deck page's More

"More ▾" from 600 px, "⋯" on a phone. Its items, in order, with separators where shown:

| Item | Shown when | Opens or does | Already in plain sight? | Recommendation |
|---|---|---|---|---|
| Game log | always | `#/play?id=`, the Game log narrowed to this deck | no (see above) | **Move into plain sight** (the Overview's Played at home link above); it can stay in More too. |
| History | not a product or pairing | `#/history?id=`, every saved revision | only from the Overview's Played at home, and only when the list changed since the last game by more than the panel lists (`since.more`); a list changed by a few cards gets no History link | **Keep.** Occasional. |
| Compare with… | always | a chooser, then `#/compare` | the library's More, Compare two decks… | **Keep.** |
| Copy decklist | always | the list shown, to the clipboard | none | **Keep.** An export, used now and then. |
| Download decklist | always | the list shown, as a text file | none | **Keep.** |
| Print play sheet | always | a printable sheet | none | **Keep.** |
| Print proxies | the viewer sees the deck's inventory and the Planned list has missing copies | a printable page of proxies for the missing cards | none | **Keep.** |
| Print box label | a built deck, or a product kept intact | a printable deck-box label | none | **Keep**, and consider offering it once more at Build decks' Finish building, when the box is in hand. |
| Change library picture… | a deck text the viewer may change | the cover picker | the library's More, Choose deck pictures | **Keep.** |
| Rename deck… | the viewer may rename it | the rename sheet | none | **Keep.** Rare, and an overflow menu is the right place. |
| Retire deck… | an unbuilt deck the viewer may retire | the retire sheet | a trial precon's Remove trial | **Keep.** Rare and destructive. |

Nothing on it needs removing. With Build deck out, what's left is exports, rare changes and two pages; only the Game log is something people do after most games.

## The pages' own More menus

Each page head puts one primary action in sight and the rest under "More ▾" (`pageHead`), the same at every width.

| Page | Items | Recommendation |
|---|---|---|
| Decks (library) | Choose deck pictures; Compare two decks… (a "⋯" at the end of the filter row when the viewer can't make decks) | **Keep both.** Occasional. |
| Collection | Import cards…, Scan cards…, Add a precon…, Precons we could build…, Commanders we could build…, Record a trade…, Download collection (CSV), Build decks | **Keep** all but the last. It's the longest menu (eight), but each is occasional. **Remove Build decks** from it if Build decks becomes a top-bar pill; until then keep it. Precons we could build and Commanders we could build are discovery features people may not find here: if Matt wants them used more, a line on the Find cards view would show them, but nothing says they're missed. |
| Tokens | Scan token cards…, Plan packed token cards…, Refresh | **Keep.** Refresh reloads the list without the avatar menu's Reload page, which reloads all of Deck Lab. |
| Sleeves & boxes | Refresh | **Keep.** A menu of one is a little odd, but harmless. |
| Shopping | Wishlist, Refresh | **Keep.** |
| Build decks | Sleeves & boxes, Tokens | **Keep.** The pages the plan's sleeves and token cards come from. |
| Compare | Swap sides, Compare with another deck… | **Keep.** |
| Testing, Game log, Activity, History, Settings, Wishlist | no More | nothing to do |

The row-level "⋯" menus (an editor line's, a Considering card's) and Shopping's Move menu are actions on one row, not places, and aren't part of this review.

## Recommendation in short

1. Make Build decks a pill in the lab's top bar from 1000 px only, leaving it in the phone's and upright iPad's More sheet and in a phone on its side's More ▾ (a bare `nav: "main"` would also put it in a phone on its side's bar; see above).
2. Add a Game log link to the deck Overview's Played at home panel.
3. Then remove Build decks from the Collection page's More.
4. Keep everything else where it is. Once the server's page counts are in (the query above), check that Tokens, Sleeves & boxes, Wishlist and Activity are opened rarely enough to stay in More; if one is opened as often as Shopping, look again.
