# Deck Lab UI and UX review

20 November 2026 · public checkout `b113430`

## What to fix first

A player can follow **Ready to build** all the way to a refusal, ask to queue the missing cards in front of them and see different cards offered for review, or type a new card name and have the previous one selected. These problems affect what players put in a deck, what they intend to buy and whether they can trust the collection.

**My recommended first change is Collection → Add card.** It puts an unintended printing one confirmation away from the inventory, and the fix has a precise test. Next, make deck readiness and purchase actions describe the list and physical copies actually being used. Treat keyboard access to the account controls as a release-priority fix alongside those changes.

Priority below reflects consequence and available recovery. The walkthrough used invented records, so it does not estimate how often the household encounters each condition. Existing story IDs identify where the behavior belongs. The ordering here is a review recommendation.

### 1. An old lookup can select the wrong card for the collection

In **Collection → Add card**, look up Lightning Bolt, then type Counterspell before the printing lookup returns. At both 393 and 1440 pixels, the late response replaced the visible name with Lightning Bolt and selected its printing. Someone holding the second card can proceed with the first card selected. The walkthrough stopped before saving.

Invalidate the pending lookup and printing selection on every name edit. Only enable Add when the selected printing belongs to the current name. Test both a single-printing response that auto-selects and a response with several choices. This belongs with the existing single-card entry workflow, E7-S01. [Printing lookup and selection](../web/collection-cards.js#L130)

### 2. A zero-card idea is presented as ready for the table

Open an idea with zero cards. Overview presents **Build deck** and says “Ready to build: you have every card.” Cards says the list has no cards and Prices says “Nothing to buy.” Follow Build deck and the empty checklist says “Cards checked” with **Mark as built** enabled. An isolated call to the same completion operation refused the empty list. The observed consequence is a dead end after the interface has twice promised success.

Give an editable empty idea one primary action, **Add cards**. Show a neutral empty state on Cards and Overview, and make assembly preview explain that it needs a nonempty list. Check the same condition on a direct assembly link and retain genuinely buildable decks with zero missing copies. [Phone screenshot](ui-ux-review-2026-11-20/deck-empty-phone.png) · [Readiness banner](../web/deck-availability.js#L122) · [Checklist verdict](../web/assembly-finish.js#L58) · [Completion eligibility](../lib/api/assembly_completion.py#L70)

### 3. Queue missing cards switches from Play-now to Planned

On **Play-now → Cards → Missing**, the fixture showed three missing copies of Opt. **Queue missing cards…** opened a review offering four Elvish Mystic and one Llanowar Elves. The review explains its Planned scope and requires confirmation. The misleading part is the button beside the three Opts. Planned and Play-now can legitimately contain different lists.

Keep E5-S25’s Planned-only purchase rule. On Play-now, offer **Review Planned list shortages** if that transition is useful. Keep the current queue action on Planned. Use disjoint shortages for the two versions in the acceptance case, and verify the label before the sheet opens. [Phone screenshot](ui-ux-review-2026-11-20/play-now-queue.png) · [Queue action](../web/deck-queue-missing.js#L35) · [Proposal](../lib/api/shopping_queue_missing.py) · [Purchase story](stories.md?plain=1#L2526)

### 4. Keyboard users cannot move through the account menu

At desktop width, focus the avatar and press Enter. Focus moves to **Auto**. Arrow Down stays there. Tab closes the menu and lands on **New deck**. This skips the other theme choices, shortcut help, profile switching where available, visibility settings and Settings within that menu. The shared handler navigates menu items, while this panel contains ordinary controls.

Let Tab and Shift+Tab visit each visible control, Escape close the panel and focus return to the avatar. Verify the sequence with both an admin and a member. This was reproduced with keyboard input in Chromium and can be repaired ahead of the E11-S55 VoiceOver session. [Account panel](../web/index.html#L275) · [Shared keyboard handler](../web/core.js#L745)

### 5. Refreshing a changed purchase queue discards a prepared order

In **Shopping → New order**, enter a seller and two exact-printing singles. When preview returns a conflict because the queue changed, Preview is disabled. **Refresh Shopping** closes the form. Reopen it and the seller and card rows are gone. The conflict path at final save can also tell the buyer to preview again while preview is disabled.

Keep the buyer’s typed seller, order details and card rows while refreshing. Mark the old preview invalid, identify any changed queue allocations and require a fresh preview before saving. Reproduce with a manually pasted order (E6-S02) as well as one started from a shop basket (E6-S28). [Refresh and save handlers](../web/shopping-orders.js#L321)

### 6. “Free tonight” includes a commander still in the post at the point of choice

With the only copy of a commander on the way, **Commanders we could build** showed “1 free” and offered **Build from cards free tonight**. The next screen refused because the commander needed a physical copy. Both the candidate response and the refusal were reproduced with fixture inventory, then walked through the phone and desktop controls.

Show **On the way** for that copy and keep **New deck from it** available for planning. Offer the tonight action when the commander, or both members of a pair, can actually come out of storage. Check again at preview in case the collection has changed. This is a mismatch between two built features, E9-S28 and E9-S39. [Candidate counting](../lib/api/commander_candidates.py#L97) · [Candidate actions](../web/commander-candidates.js#L142) · [Tonight’s pool](../lib/api/commander_draft.py#L46)

## Where the visual hierarchy gets in the way

Desktop uses width well in the two places where comparison matters most. The Decks list keeps a selected deck’s details beside the other choices. Shopping puts deliveries and buying decisions side by side. On a phone, Shopping’s four labeled section links let the player jump straight to missing cards without scrolling through parcels. Both light and dark themes keep the action colour recognizable. Keep those layouts and spend the visual effort on what appears before them. [Deck selection](../web/library.js#L596) · [Shopping navigation walkthrough](../ui_review/shopping-navigation.js)

**The phone library works when it opens on decks.** At 393 × 700, with the same four synthetic decks and healthy status answers, title search starts at y=249 and the first deck title at y=447. The card shows its name, format cues, number owned, incoming copies and copies to get. The bottom navigation starts at y=644. There is enough room to choose a deck. [Healthy first screen](ui-ux-review-2026-11-20/deck-library-healthy.png)

With refreshable and blocked tables present, the table notice takes 498 CSS pixels. With the additional admin card-data warning present, neither title search nor a deck appears on the first screen. The same ordering also pushes the first title below the opening desktop viewport. These measurements come from fresh loads of the same fixture with controlled status responses.

| Viewport | First deck title, healthy | With stale-table panel | With panel and admin warning |
|---|---:|---:|---:|
| Phone, 393 × 700 | 447 px | 953 px | 1,127 px |
| Tablet, 820 × 1,106 | 547 px | 907 px | 1,033 px |
| Desktop, 1,470 × 830 | 465 px | 792 px | 891 px |

Keep a short, visible warning that availability may be stale. Put the list of blocked decks, explanations and the admin command behind an explicit disclosure. Open it automatically for someone following **See them on Decks**. In a personal space, explain only causes that apply there. The existing panel mentions recent orders even though a personal space has none. The same admin command also consumes the first part of **Receive delivery** on a phone. Keep actionable warnings visible at the task where they affect the decision. [Phone with both notices](ui-ux-review-2026-11-20/deck-library-warnings.png) · [Library ordering](../web/library.js#L314) · [Table details](../web/editor-deckpage.js#L153) · [Admin warning](../web/version.js#L175)

## Friction through the rest of the journey

### Build and edit a deck

| What the player encounters | Change and acceptance |
|---|---|
| **Add a commander** accepts a basic Forest, announces it as commander and switches the picker to **The 99**. The subsequent automatic check correctly warns that Forest cannot lead the deck. | Use the existing eligibility rules in the guided picker. Exercise an ineligible card, an eligible exception and a legal pair. Preserve the ability to save a work in progress. [Phone screenshot](ui-ux-review-2026-11-20/commander-picker-phone.png) · [Picker](../web/editor-cards.js#L901) · [Eligibility](../lib/stats/commander.py#L118) |
| A blank **New deck → Commander** offers paste, a precon and another deck. The collection-powered starter is under **Collection → More → Commanders we could build**. Its ranked chooser stops at 50 with no way to find an eligible commander outside that set. | Offer **Build from my collection** in the new Commander editor and allow an eligible commander to be looked up by name. Preserve an existing draft, the preview’s reasons for each pick, its open-slot count and one-step Undo. [Editor entry points](../web/editor-import.js#L242) · [Candidate chooser](../web/commander-candidates.js#L106) |

### Find, scan and buy physical cards

| What the player encounters | Change and acceptance |
|---|---|
| The global search can open the previous query’s deck. With “elves” results visible, type “dragon” and press Enter while the second response is pending. At 393 and 1440 pixels the old deck opened. Escape from a result can also refocus the field and reopen the results. | Invalidate old results as soon as the query changes. Check both Enter and a pointer selection during the wait, and make Escape dismiss the results in one press. [Search handlers](../web/global-search.js#L165) |
| Global search offers **See all 200+**, then opens a card viewer labeled **1 / 50**. | Either make all matches reachable or say how many can be browsed and invite the user to refine the search. [Search action](../web/global-search.js#L272) · [Result limit](../lib/api/global_search.py#L40) |
| In **Scan cards**, Escape closed a nonempty pending batch. Reopening showed “Nothing yet.” This happened for collection cards and tokens. A collection CSV checkpoint helps only when the user has already downloaded it. | On dismissal of a nonempty batch, offer **Keep scanning** and **Discard batch** with its count. Cover Escape, the close button and phone Back, while retaining profile isolation. This can be addressed independently of camera recognition. [Scan workflow](../web/collection-scan.js#L63) · [First-use story](stories.md?plain=1#L3843) |
| Holding a particular printing, the player can hit two dead ends. With ten matching printings, manual scan offers eight. To choose the tenth the player must first add a different one and edit it. In **Collection → Card list**, searching the displayed **M11 149** returns zero rows while **M11** finds it. | Offer **Other printings…** before adding anything to the batch. Accept set plus collector number in Card list, including the common number-sign variant. Test the ninth or later printing against the physical card. [Scan choices](../web/collection-scan.js#L333) · [Pending row](../web/collection-scan.js#L500) · [Card list search](../web/collection-rows.js#L80) |
| At a shop, a player can see **1 of 4 missing** but **Copy decklist** copies all four plus fully owned cards. Per-card shop links and per-shop basket exports serve other purposes. Personal **Cards to get** combines all saved Planned decks. The queue review also takes every newly missing row together. | Add a read-only **Copy missing cards** next to the selected deck’s Missing filter, using shortfall quantities and the same inventory permission as the view. Keep the whole-deck export. For a buyer choosing only some rows, offer a selection before adding them to the queue. [Deck export](../web/deck-tools.js#L25) · [Queue review](../web/deck-queue-missing.js#L116) · [Shop baskets](../web/shopping-baskets.js#L232) |
| In a member’s personal **Cards to get**, a failed count explains that the collection needs checking. The only action on that result is **Close**. The page-level More contains this tool while the phone’s bottom More opens a different menu. | Offer a link to the member’s own Collection or affected deck when the reason permits, plus **Try again**. Test whether a first-time member can find the tool unprompted. [Member result](../web/member-tools.js#L37) · [Member story](stories.md?plain=1#L5487) |

Archidekt documents a purchase action at the deck with selectable export scope. Deckbox documents a deck-specific missing-cards-to-wishlist tool. Deck Lab already accounts for incoming deliveries, held copies and deck-specific queued copies. The useful pattern to borrow is keeping the chosen scope visible when a player takes the result out of the deck. [Archidekt FAQ](https://archidekt.com/faq) · [Deckbox developer release note](https://deckbox.org/forum/topics/32065)

### Play, record and test

| What the player encounters | Change and acceptance |
|---|---|
| At 393 × 852, **Record a pod game** was 1,589 CSS pixels down the Game log with one saved pod. Adding ten duel records pushed it to 3,423 pixels. **Start pod counter** was inside that form. With just the pod, the deck filter disappeared altogether. | Put **Start a pod** and **Record a pod** near the top beside the duel actions. Show the deck filter when either game type exists. Test with zero duels and with a long duel history. [Game log](../web/play.js#L94) · [Pod entry](../web/play-pods.js#L280) |
| A pod-only Commander deck can say **Not played at home yet** in the library and Overview while the Commander night line-up knows its last game. The library metric intentionally counts duels. | Label the metric as 1v1, or use the last physical game across modes for the general label. Verify one Commander deck with a pod and no duels on all three surfaces. [Library calculation](../lib/api/library_played.py#L60) · [Line-up calculation](../lib/api/commander_lineup.py#L60) |
| **Testing → Popular decks → Play** described 20 opponents and about 100 games each. The confirmation referred the player to the deck’s Testing tab for the time estimate and offered only Play or Cancel. Previously completed games can substantially change the new work. | Put estimated **additional games and time** in the confirmation, or link directly to the estimate. Test zero additional work and an overnight estimate. The review cancelled the confirmation. [Board dialog](../web/gauntlet-board.js#L248) · [Existing estimate](../web/gauntlet.js#L776) |
| Selecting **Matchups** with Enter in Testing moved focus to the document body. The next Tab returned to **Popular decks**. In a separate simulated failure, returning to the Game log deletion sheet after a backgrounded request left both decision buttons disabled and the error area blank. | Restore focus to the selected Testing view after a redraw. Reconcile the deletion reply when the same sheet and profile return, keep the typed reason and present the current record before any retry. Verify backgrounding on a phone. [Testing navigation](../web/matchups-overview.js#L588) · [Game deletion](../web/play-delete.js#L59) |

### Reflow and accessibility

**Pasting an order makes the phone form scroll sideways at normal text size.** Open **Shopping → New order → Paste a card list**. At 393 pixels the outer page still fits, but the sheet holds 442 pixels of content. The rightmost 49 pixels of **Copies** and the end of the paste instructions fall outside the initial view. At 320 pixels the entire Copies field starts offscreen. Panning reaches it. The unbroken CSV header determines the grid’s minimum width. Allowing that hint to wrap in the browser removed the excess at 320, 393 and 430 pixels, including after adding a row. [Phone screenshot](ui-ux-review-2026-11-20/order-paste-phone.png) · [CSV hint](../web/shopping-orders.js#L134) · [Order form grid](../web/shopping-orders.css#L5)

Across 17 routes, normal-size content fit the page viewport at 320, 393 and 844 CSS pixels. Two page-level problems appeared at 320 pixels with the root font doubled. **Deck rules · Followed** widened the Commander Overview to 343 pixels. A stale-result badge widened the Popular decks board to 331 pixels. Both fit at 393 with the same enlargement. Let those labels wrap or stack. The order sheet illustrates why both the page and its open panels need measuring. [Deck verdict layout](../web/stats.css#L12) · [Testing badge layout](../web/gauntlet-board.css#L25)

## Interactions worth keeping

- **Planned → Show missing** goes straight to a filtered list, distinguishes copies on the way and presents owned stand-ins beside the result. The queue review deducts copies already queued for the same deck. These are valuable distinctions for a shared physical pool. [Deck availability](../web/deck-availability.js#L102) · [Queue review](../web/deck-queue-missing.js)
- **Start with physical cards** gives a newcomer a choice they can answer with the cards in front of them. A loose pile, an unchanged precon and an existing export each lead to a different working path. Import preview exposes problem lines. Accessory controls also explain where an in-use item must be changed. [First-use guide](../web/collection-scan.js#L36) · [Accessory controls](../web/accessories.js#L451)
- **Receipt and deck editing** make substantial work reviewable. Receipt filters, checked progress and the return to a local draft worked in the fixture. In the editor, Keep editing returns from a blocked review and Undo restores an edit. The dark receipt screen also keeps **Record arrival** beside the checked count. [Receipt walkthrough](../ui_review/receipt-layout.js) · [Editor walkthrough](../ui_review/editor.js)
- **Testing results and shop baskets** show the basis for a decision. Testing distinguishes 1v1, opponent sample and historical results. Shopping can show which printing, shop, postage and outstanding quantities support a basket estimate. Keep that detail reachable from the concise headline. [Testing board](../web/gauntlet-board.js) · [Basket review](../web/shopping-baskets.js) · [Compare deck groups](../web/shopping-compare.js)

## Verification and the next household session

The review used the repository’s disposable Chromium fixture, synthetic home and member profiles, controlled delayed and failed responses, source inspection and targeted fixture API checks. The current-tree browser suites below completed with browser and fixture cleanup. The first strict-console runs of Composition and Page families flagged HTTP 503 responses deliberately injected for their failure screens. Both suites were rerun in their normal mode, which checks the application’s response to those failures. [Harness and repeat commands](../ui_review/README.md)

| Suite | Completed cases |
|---|---:|
| Deck and library composition | 40 |
| Page families, including Shopping, Collection, Tokens, kit, Game log, Activity, Settings and Wishlist | 114 |
| First use | 24 |
| Personal member tools | 12 |
| Shopping navigation | 18 |
| Shopping card links, smoke subset | 6 |
| Receipt layout and interaction | 24 |
| Editor interaction | 2 |
| Commander line-up, visibility, storage and shopping hierarchy | 4 |

Targeted walkthroughs exercised the timing, list-version, empty-deck, order-conflict, keyboard, member, scan, pod and warning-layout cases described above. Images in this review are synthetic. The review did not access household records or start a Forge game. Fresh physical-device, VoiceOver, actual camera and person-observed usability evidence remain outstanding. The previous Safari Simulator run is dated 5 November and covers an earlier revision. [Simulator evidence](../safari/EVIDENCE.md) · [Current device and session backlog](../../TODO.md#now)

Use the household phone and iPad session for questions the fixtures cannot answer. Start each task with the player’s goal and record the first place they look, assistance needed, the outcome they predict and any accidental action.

1. **Build for tonight.** Hand the player a commander and ask them to make a first draft using cards physically available. Observe whether they start with New deck, Collection or Build decks, and whether they can explain what an incoming copy changes.
2. **Take a list to the shop.** Give a deck different Planned and Play-now shortages, with one copy on the way. Ask the player to prepare a list for the version they mean to buy. Compare the card names and quantities they take away with that version.
3. **Record a small pile.** Include two printings of one card. Ask the player to enter the exact copy, pause midway, then resume. Observe lookup, camera use, the software keyboard and whether they know which choices are saved.
4. **Start a four-player game.** From the phone home screen, ask the player to choose a deck, start the counter and find the game afterward. Repeat account navigation and a result-to-field search dismissal with VoiceOver. The existing member session covers sign-in, first use and privacy for that audience. [Member session guide](user-testing-user2.md)
