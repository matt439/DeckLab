# Deck Lab UI kit

How Deck Lab's pages are built from shared pieces: the design tokens, the CSS components and the small JavaScript helpers. Page packages follow this; the reasons are in [UI-REVIEW.md](UI-REVIEW.md) sections 2.1–2.3. Everything is plain CSS and classic scripts with no build step, and nothing is loaded from the internet.

## Files and load order

| Kind | Files, in load order | What's in them |
|---|---|---|
| CSS | `tokens.css` → `base.css` → `components.css` → `cards-ui.css` → `shell.css` → page files | Tokens; page reset, type and fields; shared components; card pieces and the viewer; the app shell; page layout |
| JS | the editor's and matchup scripts (`editor.js` first, then `sim-ui.js`, `matchups.js` … `runs-pill.js`) → `core.js` → `ui.js` → `symbols.js` → `cards-ui.js` → `card-viewer.js` → the other page scripts → `shell.js` → `settings.js` → `app.js` (index.html has the exact order) | Forge's result pieces (`sim-ui.js`) and the run activity (`runs-pill.js`); `el()`, `api()`, `toast()`, the routes table and page-head helpers; menu, Undo toast, action bar, a deck's colour pieces; card symbols; card tile and row, printing picker; card viewer; pages; the top bar, tab bar and avatar menu; the Settings page; start-up and routing |

The scripts share one global scope, so a name may be defined only once across all of them (`test_web.test_no_name_is_defined_twice`). Nothing in the shared files runs at load. The sheet helpers (`openSheet`, `sheetActions`, `ask`, `busy`, `unbusy`) are in `editor.js`.

Library title, colour-identity and archetype filters use only its already authorized
summaries. Native Includes choices require every chosen WUBRG colour; known `[]`
is colourless and null/malformed/unreadable stays unknown. Archetypes match whole
normalized literal headers. `q`, `color` and `archetype` retain bookmarks alongside
existing filters. Matching folds open temporarily and lab selection intent stays.
The phone Filter sheet updates results immediately but defers URL replacement
until its temporary history entry lands. Exact owner/profile/route/hash/position
guards preserve Show, Close and Back without a new list read or stale takeover.
`test_library_metadata_filters_ui.py` and `test_library_filter_history_ui.py`
cover these contracts alongside the retained native title-search tests.

`commander-readiness.js` follows `stats.js`. `commanderReadiness(data)` is the
first Commander Overview section, and `commanderDataNote(bracket)` renders the
same actual source dates and freshness note there and in the Stats panel. Both
read the displayed list's stats, never inventory; card names use the existing
viewer helpers. Their wording distinguishes the declared aim from a detected
minimum and incomplete checks.

`commander-night.js` follows `commander-readiness.js` and renders the separate
optional home-only night panel even when card checks or inventory counts are
unavailable. Its notes, household aim, published range and checked date do not
change rule checks or certify fit. Settings uses an inline home-admin form with
explicit unknown choices and a revision-bound Save. An unchanged save adds no
change; a stale form retains edits and requires Load current saved note, while
removal needs a reason and confirmation. Controls count Unicode characters as
the server does. Loads, writes and retries check the original profile, route,
connected form and request sequence; late work cannot replace another viewer's
page. No note is quiet; unavailable storage has explicit wording.

`assembly-chooser.js` follows `assembly.js`. One chooser tree moves between the
shared Decks sheet below 1000px and the 300px lab rail. The same minimum-width
query drives controller and CSS; current deck/control identity restores fresh
focus after redraw, with guarded viewport reveal. Close/Show the plan only dismiss,
and choices keep the existing 250ms read-only preview. All eligible options,
usual-opponent/status groups, the twelve-participant limit, versions and sideboard
recipes remain. One status node moves to the visible home. Busy/stale/permission
guards include sheet controls; route/person cleanup disposes the chooser and its
media listener while ordinary choice changes close only build/stand-in reviews.
The [drawing](design/packing-chooser.svg) preceded implementation. This adds no
allocation, progress, inventory or save contract.

Selected packing participants expose optional `data.decks[].colors` copied from
the already-loaded canonical Planned/library summary, including for Play-now or
partial sideboard recipes. Null means unknown; an empty array means known
colourless. This is decoration only: unselected choices have no added colours,
and selections, task keys, fingerprints, reads and accepted requests stay the same.
The Decks chooser options stay undecorated; the casual switcher uses this field.

`assembly-switcher.js` follows the chooser helper. Below 1000px, all selected
participants (up to twelve) have id/version keyed pressed buttons; inactive
original panels are hidden, never detached or rewired. The lab shows all panels.
Global required-card counts, optional steps, warnings, shared-token guidance and
completion keep the whole-plan scope. Switching makes no request or stored choice.
The packing-only viewer adapter uses original triggers/cards/captions in task order,
including hidden panels and duplicates; generic viewer filtering stays unchanged.
Distinct opening watches and current-plan/trigger/busy guards protect close/resize
focus, with exact return-panel ownership and listener disposal on route/person changes.
Queued reveal only scrolls current focus. Unknown colour identity stays neutral;
strict known identity uses the shared deck pieces, including known colourless.

`assembly-steps.js` follows the finish helper; its CSS follows `assembly.css`.
One native details/summary/body retains original tasks across toggle, polling and
resize. Done derives from a nonempty exact subset of existing ticks. Only casual
auto-folds confirmed completed steps to 56px; lab starts expanded and permits
manual disclosure. Focus, owned viewer return, pending/errors and modal/busy work
defer automatic collapse. Manual reopening persists for the same task scope;
Undo/uncheck reopens without moving focus or participant selection. Guides/viewer
return expand their exact step first. One owned click toggle handles keyboard
activation, and queued native toggle events read current desired state. Resize
reveals the same focused current control through the existing guarded helper.

`assembly-finish.js` follows the switcher helper. A retained bar under the stable
plan column counts global card copies and separate optional steps. The visual meter
has a spoken equivalent; no card tasks means no meter/max/value or 0/0. The primary
uses aria-disabled with one retained described reason and stays keyboard reachable.
Blocked activation only focuses current guidance or reveals the original unchecked
task through the switcher; it never activates Retry/Refresh or changes ticks.
Readiness and build saving stay with the original predicate and review/save path.
Current plan/button/modal guards reject stale actions. Redraw, preview errors and
empty selection remove the bar. The same narrow Decks launcher starts the plan
column, keeping short-window sticky containment and resize focus predictable.

Packing-only lab CSS projects original tile/open/tick nodes into rows with a
46px minimum, 28px thumbnail, decorative mono quantity (including one) and 44px
tick target. Names and donor/List-intent metadata wrap; viewer focus outlines the
row. Casual keeps tiles. Finish labels describe existing selected-list intent,
never allocated printings; returns keep no finish decoration. Done checklist text
uses ink-3/medium without strikethrough. Casual checked actual art uses .42 opacity
and a decorative 40px check; controls retain full opacity. Only an actual image
child hides checked fallback words, so its error removal restores them. Unknown
and no-art cards keep their original text and viewer semantics. Neutral step
badges are 28px casual/20px lab. Task wiring, counts and save readiness are unchanged.

`assembly-overlap.js` follows the steps helper. Optional competition guidance uses
confirmed resolved selected-participant facts with conserved safe whole counts
that match their aggregate row. Effective stand-in names, duplicate/unknown data,
ordinary all-waiting shortages and donor-only/basic rows do not create guidance.
The warning table labels copy units and current assignments; it adds no allocation
or action. Original pull/move pills stay outside viewer/tick hit areas. Casual
shows Also needed with full accessible/tooltip context; lab shows full names/list
context, and the table stays fully named. Only lab fact numbers use mono. Scoped
step-marker reset leaves one visual disclosure arrow. No request, task, fingerprint,
progress, caption or readiness change is introduced.

`assembly-progress.js` loads after the overlap and section helpers: shared Build decks checkmarks,
per-task identities and patches, pending-save status, polling and Clear/Undo.
Sorting remains a browser preference. Progress is shared through the server;
it never changes a deck's status without the explicit Mark as built action.
The optional last-recorded-update line uses only the latest committed audit change
for the current task scope: a known home profile's existing avatar colour, an
absolute semantic date and the count of check updates, including unticks. Unknown
actors are Someone. This is recorded activity, never an online/presence claim or a
card-copy count. Identical polls retain the status nodes and Retry focus; changed
scope, failures and pending tasks outside the current scope hide old metadata.
Older servers without metadata keep the same usable checks.

`assembly-sheets.js` follows the progress script. Its final review collects the
built list and kit for one save, and its stand-in chooser saves only planned
physical markers. Sheets close on plan, route, person and away-lock changes;
late work checks the original viewer, route and plan. Anonymous spare markers
have required card-task ticks; optional kit and token ticks stay optional.
`deck-standins.js` supplies the inventory-visible mappings. Overview links to
the represented card's rules; the printed play sheet records the text mapping.

Build decks groups optional verified `held_elsewhere[].intact_product` evidence
by its opaque product id, using one actual supplied readable deck route for the
existing Product storage review. Only short/waiting cards contribute. The link
keeps one in-memory, profile/address-scoped recipe after shared checks settle;
Browser Back consumes it once and re-previews before showing card instructions.
A refresh failure keeps choices for explicit Retry, never old counts. Pending or
uncertain checks show guidance. No product mutation or transfer is automatic.
`test_assembly_products.py` and `test_assembly_product_review_ui.py` guard source,
privacy, multi-deck grouping and navigation/refresh ownership.

Saved Editor headers use the casual Editing/name/stripe frame and the original
lab context from 1000px. `editorDraftIdentity()` reads loaded cards with canonical
Commander/Companion/Deck policy, excluding Sideboard; unknown stays neutral and
known colourless remains explicit. Signature-only `drawEditorHeaderIdentity()`
refreshes through `changed()` and accepted `fillCards()` hydration, with exact
editor/route/profile/id/version ownership. New/copy/read-only/version modes remain.
Saved details keep one native field/toggle tree with a 60px closed casual row.
`revealEditorDetailsFocus()` uses once-only window/visualViewport hooks to scroll
the same current saved-fold control above overlapping chrome after resize. It
never focuses or edits; stale/new-focus/modal/busy work is ignored, tight margins
shrink and oversized targets align stably. Exact draft/check/save paths are unchanged.

Editor search results are a labelled native list with sibling Inspect, static
facts and retained Add/quantity actions. The highlighted list item has
`aria-current`; the search field keeps focus for arrow selection and uses
live announcements, while Tab reaches the native actions.
`editor-search-quantity.js` shares Add's exact preferred-line resolver: current
section, strict default set/number/finish then the original same-name fallback;
never sum names or infer printing. Actual line section/printing describes the
stepper. Original quantity/remove/Undo/history paths perform mutations, with
exact current line/controller/query/owner guards. Explicit commit handles Enter
and blur without relying on implicit change events; a consumed edit cannot
remove a fallback printing. Focus recovery respects outside destinations through
reentrant refresh. Quick outside-main results resync through original changes.
Actions reject saving/asking/leaving and unrelated dialogs; passive results may
paint, but rejected pending Add intent is consumed and cannot replay. Added expiry and
More append retain existing result/action nodes, including the viewer trigger.
More failure retains accepted rows and retries that exact page. Search ownership
is the exact editor/controller/route/profile and connected wrapper; accepted
async work also matches query and deck id/version/space. Close, replacement and
Quick dismissal invalidate timers/answers without changing request payloads or
aborting the server read. Keep constructor painting separate from mounted actions.

Editor List and Pictures steppers default to a 46px group, yielding 44px
native buttons after the shared border. Pictures footers wrap and retain a
44px More target. Only `min-width:1000px` plus a fine pointer restores the
original dense List token and 34px Pictures group/32px More. Sideboard's exact
`data-section`/`.edit-sideboard` hook supplies the surface-2 band and kind-correct
size-exclusion note; removed-only groups keep original Undo and no zero count.
The existing optional Stand-ins action comes before printing, moves and Remove.

The full Editor retains one Add/search, Stats and Checks tree. `sidePanel()`
owns their original roots and tab buttons; `projectEditorPanes()` changes only
visibility/roles. Lab shows the three areas; casual tabs/fold project the same
nodes. Exact current-draw ownership and per-scroll id/version/space snapshots
reject stale work while allowing legitimate new-deck space changes. Explicit
Add/check jumps leave Notes; passive resize does not. Pane focus uses scroll-only
reveal, with guarded hidden-header rescue and same-route history restoration.
Consumed swap/Notes URLs refresh only the qualified original pane context at
the existing canonicalization point; queued work keeps its invocation hash.
Earlier-address draft recovery does not consume a link before an editor exists.
The side track reserves list width, and the named `editor-cards` container uses
two-line full List rows at most 600px wide. Keep actual printing, cost and
availability visible. Checks headings switch real classes rather than overriding
the shared sr-only rule. Full Editor peek stays suppressed.

Full List rows retain their mana costs beside numeric MV; the native MV button
reverses sorting within each existing group. Unknown values remain unknown and
sort last. Sort moves only presentation nodes, leaving the focused row attached
and saved/request order intact. Changed rows use the teal row treatment only
while no warning/block style applies.

The bar retains change counts, copy deltas, Undo and guarded Discard alongside
its original controls. Its split Save is one retained group. Phone history
actions use two rows in the same native focus order; bar height remains measured
by the Dock. `editor-forge.js` shows optional saved evidence only after exact
ID/version/playable-fingerprint matching and current page/person/frame checks.
The API computes hashes from the parsed edit snapshot; field cache identity
includes version. Missing evidence supplies no numbers; partial coverage stays
explicit.

An unchecked post-save field choice is transient and available only for a full
saved writable list. Simulation updates refresh its control/reason. A successful
save submits at most once with the returned playable fingerprint, then finalizes
the saved UI immediately. Deferred run outcomes update only the owned message;
they never reload an editor, remove a draft or retry. Save-and-view receipts are
profile-scoped. The read-only evidence path never starts games.

`editorCurveBaseline()` compares only the current actual saved edit/version,
including a readable trial, never a new/copy/unstarted list. Saved quantities
stay immutable; same-name current card metadata may fill a local projection,
while missing/contradictory mana-value/land knowledge suppresses comparison.
`editorCurvePart()` uses a common saved/current scale, canonical deck gradient,
neutral deltas and exact spoken counts. Grown old-height marks use on-scrim
with scrim-edge; shrunk caps use ink-4. Zero spells retain saved caps without
an invalid average. Undo/restore/rebase/hydration recalculate from source;
row order/global dirty state and unrelated Stats remain independent.

`syncEditorRowChanges()` uses exact section/printing tallies against an actual
saved edit, including readable trials. New/copy/unstarted lists are undecorated.
Retained dot/prior-count/description nodes update without replacing actions;
duplicate exact keys suppress per-row prior counts. `changed({list:false})`
refreshes them in place, merging only their own description ID. Pictures keeps
its original two-line name and places the retained prior count after metadata
inside the same trigger. Removed text is struck, filled in casual and dashed
in lab; original Undo and global dirty/ordering semantics remain unchanged.
`showQty()` also refreshes only the current original viewer entry's caption through
`syncEditorLineCaption()`, checking line/section/row/trigger/card/profile ownership.
The next open gets current quantities; an already-open viewer is not live-updated.

`editor-swaps.js` (after `editor-cards.js`) and `deck-swaps.js` (after
`deck-standins.js`) are E2-S07's strategic stand-ins, kept apart from those
physical markers: owned cards that could take a missing card's slot in the
Play-now list (`GET`/`POST /api/deck/swaps`, only for a viewer who sees the
space's collection). In the editor a short Play-now line's ⋯ menu has
"Stand-ins…", a side sheet with one `cardRow` per candidate, its note as `.sub`
text and a plain `.btn` "Use n" (no primary: several rows each have one). A
pick is one change with the Substitutes note it adds once; the toast's Undo
and Ctrl+Z take back both. The note goes into a table only when its headings
say where the stand-in goes ("Stand-in", "Play now", "Owned"), else as a
bullet. The deck page's Missing filter shows "Owned stand-ins" (its first
five rows, then "Show all") and links into the editor (`&swap=<name>`) only
when the Play-now list is short of the card too; the Play-now list's
Overview and Cards tab show "Swaps from the Planned list" to every viewer of
the deck, with "Edit notes" (`&tab=notes`) for whoever may change it. Late
answers check the editor, route and person.

`product-storage.js` supplies the product Overview's inventory-visible storage
state and preview/confirm sheet. Its opaque review token binds both revisions;
successful saves keep warnings visible until Done refreshes the deck page.
`accessory-pictures.js` follows `accessories.js`: local photo selection, preview,
crop and shared accessory-dialog tracking. Photos stay local until atomic Save.
`closeProductStorageSheets` and `closeAccessorySheets` run on route, person and
away-lock changes, including nested accessory pickers and confirmations; late
work checks its original viewer and route.

`shopping-order-edit.js` shares reviewed order changes. Cancellation and mistaken-order
removal collect a one-line reason, then show queue-restoration quantities and affected
deck tables before the final destructive primary action. Cancellation has an explicit
restoration checkbox; removal always restores known intent. Saved results keep warnings
and the **Tables out of date** link until Done. Sheets and late results follow the
original person and Shopping view; a successful late save still invalidates library
availability. Closing a confirmed save before its response refreshes the same active
Shopping view after success; a changed person or route stays untouched.
`library-tables.js` supplies the shared `TABLES_HREF` link.

`deck-prices.js` follows `deck.js` and owns the inventory-visible price table.
Its five columns keep the unit estimate under the card name and the extended
missing cost in the last column. Native `.th-sort` buttons for Card, Missing and
~AUD missing maintain `aria-sort` and focus, reorder each whole per-card `tbody`
with its labels, and leave the total footer last. Sorting copies the row list,
keeps unknown costs last in either direction, and makes no fetch or write. Late
controls check the original person, route and connected table.

`shopping-buying.js` follows `shopping.js`. It draws dated reference-price footers,
Missing cards across decks and the folded By shop view from the current Shopping
answer and queue. These views add no edit or purchase actions. Combined quantities
sum individual home-deck shortfalls, not concurrent packing needs; known token
rows cannot annotate same-name playable cards. Partial and unavailable calculations
keep explicit errors. The selected shop and open fold survive a local queue redraw,
not navigation or reload. Price, shop and checked date stay visible without a card
picture and describe recorded research rather than live retailer stock.

`shopping-reprints.js` follows `shopping-buying.js`. Its shared `reprintInfo` draws
known upcoming paper-printing set/date evidence as a sibling of the card viewer
button, also in missing deck-price rows. Source and coverage exposes the actual
cache/comparison dates and limits. Waiting rows can open the manual Check prices
again sheet, retaining the exact preference and prior dated observation, with
Scryfall USD-source links and exact-name copying (selectable fallback). Opening
sources or copying makes no queue, price, check-date or scheduler write. Sheets
close on route, person and away-lock changes; old controls and late clipboard
results check their original viewer and route. Queue saves replace returned
reprint evidence, including an explicit null that removes an obsolete hint.

`receipt-workflow.js` follows `receipts.js` and owns selection/progress, preview,
apply, success and profile-bound drafts. Keep component selection and row ticks
separate: cards/token ticks choose arrived rows, and Split copies makes a partial
tile quantity explicit. `rcptRequest` sends complete edited rows plus 1-based
`take` indexes into that submitted order when a subset is selected; products stay
whole. `rcptAssignments` renders the server's received/pending ids and counts.
`rcptReceived` freezes reviewed arrived rows for Where these go before the request.
Apply's `remaining` covers all pending components, including unselected parts, and
Continue pending delivery reloads them; the response's new fingerprint identifies
the saved inventory. Quantities count physical card copies (a product uses its
card-list quantity); tracked-addition totals may exclude plain basics. A 503 keeps
the same preview for Retry recording arrival; a 409 requires Reload the delivery,
with the draft retained on failure; loading a new fingerprint drops older drafts. Record arrival is the one constant primary: client blockers set `aria-disabled` with a live described reason, and its guarded handler focuses the first actionable blocker. Ready calls the same exact server preview/confirmation/apply; blank condition/language and partial remainder do not block it. Busy/reload/done or inactive/unauthorised views keep native disabling. Date checks require a string real calendar day, preserving invalid saved values for correction.
`openReceiptSheet`/`closeReceiptSheets` track row, preview, blocker, draft and
confirmation dialogs for route/person/away cleanup. Preserve busy, changed-preview
and original-viewer guards. The partial split, receipt, checks/provenance and table
refresh are one save.

## Rules

- **Page files lay components out; they never restyle them.** A page stylesheet sets grid, gap, order and width. It doesn't change a `.btn`, an input, a chip or a tile. If a component lacks something, add it to `components.css` or `cards-ui.css`.
- **Only tokens.** Page files may not contain font-size, radius, shadow or colour literals; `test_web.test_page_files_use_the_scales` fails if they do. The only colour definitions are in `tokens.css`, and the dark theme is written once, in `:root[data-theme="dark"]`. Never use `prefers-color-scheme` in CSS.
- **Fonts come from `web/fonts/` only.** A preload in `index.html` must name exactly its `@font-face` URL in `base.css`, with no `?v=` (the server stamps only scripts and stylesheets), or the font downloads twice. Figtree's upright face and JetBrains Mono are preloaded (mono since slice 6, which put Forge's mono figures in Matchups' first view); Figtree's italic loads when it's used. A character outside the subset is drawn in the system font that follows (`decklab/fonts-licences/README.md` lists the gaps).
- **One primary per view.** `.btn-primary` is the single main action on a screen, sheet or bar. Everything else is `.btn` (outlined) or `.btn-quiet`. A red fill (`.btn-danger.btn-primary`) is only for the last step of a confirm sheet.
- **Teal is for action, selection and what's yours** (`design/visual-design.md` 4.5 and section 6 question 2): the primary and secondary buttons, the chosen segment, an on toggle chip, a selected or matching table row, a ticked box, and a line you've changed and not saved (a changed stepper). A delivery state ("Part received") is a neutral outline (`status("outline", …)`), and presence avatars keep their per-person colours.
- **Chips only for exceptions.** Show a chip for a state worth noticing ("2 missing", "On the way", "Condition ?"). Don't show one for "all fine", for zero, or for the normal case.
- **Notes describe the item, not settings.** `.note` and `.box` are for the state of this thing, never for explaining a normal setting.
- **Click to edit.** A record opens its sheet when tapped, and Remove sits at the bottom of that sheet. Don't put an Edit and Remove pair on every row.
- **Card pictures use the shared viewer.** Use `cardTile`/`cardRow` with `viewerGroup`, or call `viewerItem` on your own element. Don't build a separate zoom. Receive native check labels use their separate Inspect action to reach the existing sheet/viewer.
- **Mana and rules text use symbols.** Use `manaCost()` for costs and `renderSymbols()`/`oracleParagraphs()` for text containing `{…}`. Never print raw `{T}`.
- **Touch targets are 44 px.** The components read P1's size tokens (`--btn-h`, `--seg-h`, `--stepper-h`, `--input-h`, `--check-size`, `--row-h`), which are 44 px without a fine pointer at every width and denser with a mouse. On top of that, one `@media (pointer: coarse)` block at the end of `components.css` holds every control at `min-height: var(--tap)` (buttons and steppers' − and + at `min-width` too), so a page never sets a control's touch height itself. Use `--tap` for anything tappable that isn't a control; a page that fits a smaller control in on purpose (the editor's picture tiles) sets `--tap` (and `--stepper-h`) on it.
- **Hover only with a mouse.** A component's `:hover` look is inside `@media (hover: hover) and (pointer: fine)`, so it doesn't stick after a tap; touch gets `:active` in `--accent-soft`. `kbd` hints show only with a mouse from 1000px.
- **A page's own states win over a component's defaults.** The table hover and the lab's `td.num` size are `:where()`-weighted, so a page's row state (Collection's problem rows, the deck table's missing rows) or column size isn't overridden. A component that fills something teal (the chosen segment) makes the words inside it inherit its ink, so a page's grey count never sits on teal.
- **Hide nothing behind colour alone.** Chips have an icon and a word, a tick has a ring as well as its colour, and every symbol picture has alt words.

## Tokens (`tokens.css`)

| Group | Tokens |
|---|---|
| Type | `--font` (Figtree) and `--font-mono` (JetBrains Mono), self-hosted subset variable woff2 files in `web/fonts/` declared in `base.css` (licences and the subset command in `decklab/fonts-licences/`); `--fs-xs` (chips and badges only), `--fs-sm` (the smallest text people read), `--fs-md` (body, inputs), `--fs-lg`, `--fs-xl`, `--fs-2xl`; `--fw-regular`, `--fw-semibold`, `--fw-bold`; `--lh-body`, `--lh-tight`. P1's density type (switches level, below): `--fs-h1`, `--fs-hero`, `--fs-eyebrow`, `--fs-group`, `--fs-body`, `--fs-row`, `--fs-meta`, `--fs-btn`, `--fs-input` (16px wherever there's no fine pointer), `--fs-th`, `--fs-kbd`, `--fs-cell-num`, `--fs-qty`, `--fw-qty`, `--font-num`, `--fs-fig-mid`, `--fs-fig`, `--fs-fig-unit`, `--fs-fig-sm`, `--fs-fig-range`; `--fs-pip-sm/md/lg/xl` (a pip's letter, 9–12px); Forge's pieces: `--fs-flag` (14, 13, 12px), `--fs-axis` (a range bar's 20 / 50 / 80: 14px casual, 11 in the lab), `--fs-fresh` and `--fs-fresh-row` (a freshness badge's words: 13px casual, 12 and 11 in the lab), `--fs-swap` (a swap test's difference: 16px, 15 in the lab), `--fs-wr-caption` ("Forge field" under a tile's win rate: 13px, casual only); `--fw-medium`, `--fw-heavy`; `--ls-h1`, `--ls-hero`, `--ls-fig`, `--ls-caps`, `--ls-th`; `--lh-copy` |
| Space | `--s-1` 4px, `--s-2` 8, `--s-3` 12, `--s-4` 16, `--s-5` 24, `--s-6` 32, `--s-7` 48, `--s-8` 64; `--gutter` (the page's side margin) |
| Radii | `--r-sm` (4px: art thumbnails, small swatches, a `kbd`), `--r-md` (anything not yet moved to P1's radii), `--r-lg` (panels, until their page slices), `--r-pill` (buttons, segmented controls, chips, steppers, search fields), `--r-card` (a Magic card's corners); P1's `--r-panel` (14px casual, 8px lab: notices, boxes, sheets), `--r-row` (8px: menus, selected rows), `--r-field` (12px casual, 8px lab: selects and text inputs); `--r-swatch` (2px: a deck swatch) |
| Sizes | `--ctl-h`, `--field-h` (older; pages still read them), `--tap`; `--tile-w` and `--peek-w` (from 1600px); P1's `--btn-h`, `--seg-h`, `--input-h`, `--stepper-h`, `--check-size`, `--row-h` (table rows), `--th-h` (a table's header and group rows, 30px), `--list-row-h`, `--tile-min`, `--tile-min-forge`, `--flag-h`, `--gutter-list`; a deck's colours: `--pip-sm/md/lg/xl` (16, 20, 22, 24px), `--stripe-h` (5px), `--stripe-h-thin` (3px, under a thumbnail), `--swatch-w`, `--swatch-h` (14 × 8px, 12px tall on a phone); Forge's pieces: `--range-h` (a range bar, 12px casual, 10 in the lab), `--range-h-compact` (6px, a Matchups row), `--fresh-h` (a freshness badge, 24px casual, 20 in the lab), `--fresh-h-row` (17px in a lab row), `--activity-size` (the run activity's ring, 24px casual, 20 in the lab), `--ring-size` (a run's progress ring, 24px casual, 16 in the lab), `--icon-xs` (12px: the badge's clock) |
| Elevation | `--shadow-1` (cards; its 1px ring waits for slice 8, when tiles and panels lose their borders), `--shadow-2` (sheets, menus), `--shadow-up` (bottom bars), `--shadow-img` (card pictures), `--shadow-img-sm` (thumbnails in rows), `--shadow-primary` (a primary button and the chosen segment), `--shadow-pip-art` (a pip over a picture: a white ring and a shadow); `--focus-halo` (the 3px halo round a focused field) |
| Surfaces | `--page`, `--surface`, `--surface-2` (sunken: in dark it's darker than `--surface`; table headers, a stepper's number well), `--surface-3` (tracks), `--surface-chip`, `--track` (also a primary that can't act yet), `--seg-track` (a segmented track: `--track` at every level until slice 8 puts lab content on `--surface`, then `--surface-chip` in the lab), `--btn-bg` (a secondary's fill: `--surface` in light, none in dark), `--hover` (every row and button hover: raised in dark), `--bar-bg` (a sticky bottom bar, `--surface` at 97%); `--ink`, `--ink-2`, `--ink-3` (the lightest text), `--ink-4` (never text); `--border`, `--border-strong`, `--divider` (table rows, card rows), `--rule` (all solid) |
| Accent | `--accent` (teal: primary buttons, the selected tab, active nav, ticks), `--accent-strong` (teal text), `--accent-ink`, `--accent-soft` (translucent in dark: never as a gap over something teal), `--accent-line`, `--accent-track`, `--ring-track`, `--run-line` (the 1px edge of a run in the activity's details); `--focus`; `--icon-tick-on-accent` (a tick drawn on teal: white in light, `--accent-ink` in dark), `--kbd-on-accent` (a `kbd` box on a primary) |
| Links, info | `--link` (dark teal; light teal in dark), `--info-ink`, `--info-soft` (blue, the info pills only: info notices are amber) |
| Status | `--good`/`--good-ink`/`--good-soft`, `--warn…` (`--warn-ink` and `--warn-ink-sm` only on `--warn-soft`; `--warn-text` for amber words straight on a surface; `--warn-line`, `--warn-icon`), `--building-ink`, `--missing` ("to buy" text), `--crit…`; `--win` (a calmer green than `--good`), `--loss`, `--even`; Forge results only: `--strong-soft`/`--strong-ink`, `--weak-soft`/`--weak-ink` (flags, verdict pills, a swap's +1 and −1: never on a win-rate figure), `--range-band`, `--range-track` (`--win` and `--loss` are only the matchup matrix's cells now); `--chip-on-tint`, `--chip-on-tint-line` (a badge on a deck's tint); `--on-crit` (words on a `--crit` fill: near-black in dark). Red (`crit`) is only for what stops a deck being played (missing cards, a broken deck rule); advice such as lands against the formula is amber. |
| Charts | `--series-1`, `--series-2`, `--series-muted`, `--grid`, `--baseline` |
| Over pictures | `--scrim`, `--scrim-strong`, `--on-scrim`, `--on-scrim-2`, `--badge-bg`, `--badge-ink`, `--badge-ring`; `--viewer-bg`, `--viewer-btn`, `--viewer-line`, `--viewer-panel` (the viewer's text panel); `--foil-sheen` |
| Mana | `--mana-w/u/b/r/g/c` and `--mana-ink` (the identity pips' fills and letters, and the lettered stand-in symbols), `--mana-edge` (the stand-in symbols only), `--mana-ring` (a colour-identity pip's ring) |
| Deck colours | `--stripe-w/u/b/r/g/c` (lighter in dark), `--tint-w/u/b/r/g/c` with `--tint-*-deep` (a one-colour tint's second stop) and `--tint-multi` (four or five colours), `--art-w/u/b/r/g/c` and `--art-multi` (three or more) (a picture's placeholder). In dark the tints are the dark stripes, translucent over `--surface`. Only on decks, and only through `deckColourPieces` (visual-design.md 4.3). |

**Breakpoints:** below 600px is a phone; 600–999px a tablet in portrait; 1000–1599px a desktop or an iPad in landscape; 1600px and up a QHD screen (with a hover peek when there's a fine pointer). Media queries can't read custom properties, so the numbers are written out.

**Density levels** (P1, `design/visual-design.md` 3): the density tokens above have one name and three values. **Casual** (`:root`, under 1000px: phones and the iPad in portrait), the **touch lab** (`@media (min-width: 1000px)`: the iPad in landscape, lab type and radii at touch sizes, body 14px, buttons 15px, fields 16px) and the **lab** (`(min-width: 1000px) and (pointer: fine)`: 13px body, 28–32px controls). Sizes shrink only under `(pointer: fine)`, so a touch screen keeps 44px at every width; a narrow window with a mouse gets today's 36–38px. Slice 4's components read them; the older tokens (`--fs-xs`…`--fs-2xl`, `--r-md/lg`, `--ctl-h`, `--field-h`) keep one value for the page files that still use them. `--font-num` (Figtree casual, JetBrains Mono from 1000px), `--fs-qty` and `--fw-qty` set counts and a stepper's number per level (2.3).

## CSS components (`components.css`)

| Class | Use |
|---|---|
| `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-quiet`, `.btn-danger`, `.btn-discard` | Buttons: round, 700, `--btn-h` tall. `.btn` alone is the secondary: a 1.5px teal outline and `--accent-strong` words. `.btn-primary` is the teal fill with `--shadow-primary`. `.btn-quiet` is the tertiary: teal words, no box. `.btn-danger` is a destructive tertiary (red `--weak-ink` words, no box: Remove…, Stop); the red fill `.btn-danger.btn-primary` only for a confirm sheet's last step. `.btn-discard` is "Discard my changes": `--ink-2` words, neither teal nor red (sheetActions kind `"discard"`). A sheet's Remove… is `btn-danger btn-quiet`: from 600px it sits alone at the left of the sheet's foot. **A primary that can't act yet** (Mark as built before every card is ticked, Record arrival with blockers) is `.btn-primary` with `aria-disabled="true"`, not `disabled`: drawn in `--track` with `--ink-3` words, still focusable, its reason beside it ("20 cards still to tick"), and its click moves focus to the first thing in the way (the page does this, and guards its own click). Native `disabled` stays for busy and frozen. A button that opened a menu (`aria-haspopup="menu"`, `aria-expanded="true"`) shows it's open: a tertiary gets a 1px teal ring inside its edge, a secondary (whose 1.5px edge already is teal) an `--accent-soft` fill, a primary a ring standing off its fill. On a dark background (the toast, the card viewer) a button sets its own focus-ring colour, since teal is under 3:1 there. |
| `.btn-quiet.btn-inline` | A text button straight after prose or a list (a note's More, a list's Show all N): no side padding, so it starts flush with the text above, in teal. |
| `.kbd` | A keyboard hint inside a button (mono, `--fs-kbd`, a 1px box; on a primary, `--kbd-on-accent`). Shown only with a mouse from 1000px; `aria-hidden`, with the shortcut in the control's `aria-keyshortcuts`. |
| `.actions`, `.toolbar` | A wrapping row of buttons. A toolbar puts the search on the left and filters on the right, with `.result-count` below. |
| `.page-head`, `.page-head-actions`, `.crumbs` | A page's head and its back crumb (the shell package adds `crumb()`). |
| `.filters`, `.field`, `.field-hint`, `.field-problem`, `.choice`, `.form-error` | Forms. `.choice` is a tick box or radio button with its words, in a row at least 44px tall. Inputs and selects (base.css) are `--input-h` tall with `--r-field` corners (search fields round) and `--fs-input` text; focused, a teal edge and a 3px `--focus-halo`. Ticks are native, `--check-size`, in the accent. |
| `.segmented` | The only way to pick 2–6 options. Its children are buttons with `aria-pressed`, or links with `aria-current`. A round track (`--seg-track`, `--seg-h`) with the chosen segment filled teal (words inside it, such as a count, take its ink). With a mouse the segments sit 3px inside the track; on touch the track drops that inset (`--seg-pad: 0`), so each segment and the track are 44px. Corners are half the one-row height, so a track that wraps to two rows is a rounded rectangle. |
| `.filter-chips`, `.filter-chip`, `.filter-chips-scroll` | A row of filter pills (the Activity page's kinds and people): links with `aria-current` or toggles with `aria-pressed`, `--btn-h` tall. The same pill is the **toggle chip**, a filter that's on or off ("In storage only"): off white with a grey edge, on `--accent-soft` with an `--accent-line` edge, `--accent-strong` words and a ✓ (never a teal fill, never a switch). A toggle chip can also be a `<label class="filter-chip">` round a checkbox: the box is hidden but focusable, and the label takes the on look while it's ticked. With `-scroll`, under 600px the row scrolls sideways with a fade at its right edge. |
| `.stepper` | − [n] +: a round group, `--stepper-h` tall, with − and + in teal and the number (`--fs-qty`: Figtree 16 / 700 casual, mono in the lab). A typeable one (`.qty-input`, or any `<input>` in it) sits in a sunken `--surface-2` well and keeps 16px wherever there's no fine pointer (no iOS zoom on focus); a read-only `<output>` has no fill. A line changed and not saved gets `.is-changed` (or `data-changed="true"`): a teal edge and a bold teal number (the editor sets it in slice 14). |
| `.id-pips`, `.id-pip`, `.deck-stripe`, `.deck-swatch`, `.deck-tint` | A deck's colour pieces; make them with `deckColourPieces` (below), never by hand. `.id-pips` is a `role="img"` group of `.id-pip` circles (a `--mana-*` fill, the letter in Figtree 800, a `--mana-ring`; `.is-over-art` a white ring with a shadow), sized `.id-pips-sm/md/lg/xl`. The stripe and the swatch draw `--deck-stripe` (the helper sets it), the tint `--deck-tint` over `--surface`. Not `.pip`: that's `deck.js`'s lettered stand-in for a cost symbol. |
| `.wr` (`-inline`, `-tile`, `-hero`), `.range-bar` (`-compact`, `.is-live`, `.is-muted`), `.range-key`, `.fresh` (`-row`, `-panel`, `-casual`; `.is-fresh`, `.is-aging`, `.is-stale`, `.is-unsaved`, `.on-tint`), `.flag` (`-strong`, `-weak`), `.swap-result`, `.swap-verdict-*`, `.sim-num` | Forge's result pieces (`design/visual-design.md` 4.9); make them with `sim-ui.js` (below), never by hand. Every Forge number is mono (`.sim-num` for a number among words) and in ink: a win rate is never green or red, only the flags and verdict pills wear `--strong-*`/`--weak-*`, always with words. The range bar is a round `--range-track` on the fixed 20–80% scale with a dashed `--ink-4` tick at 50%, the 95% band in `--range-band` and the win rate as a 3px `--ink` mark; a live run's band is a dashed outline. The freshness badge is a round clock-and-words pill: neutral while fresh (plain words in a lab row, from 1000px; a casual row keeps the pill), amber aging (8–30 days), amber with a refresh icon when stale (over 30 days, or the list changed since), amber "for the saved list" in the editor. |
| `.run-activity`, `.activity-ring`, `.run-popover`, `.run-entry`, `.run-ring` | The run activity (`runs-pill.js`): a 44px button in `#shell-status` with a slowly turning `--accent` ring (still, with a dot, under reduced motion); its details are `.run-popover` under it from 1000px (`--surface`, `--shadow-2`) or a sheet below, each run on `--accent-soft` with a `--run-line` edge, its progress ring (`--ring-track`, an `--accent` arc) and Stop. |
| `.chip` + `-good`/`-warn`/`-crit`/`-info`/`-outline`/`-plain`; `.chips` | A pill with an icon and a word. core.js `status(kind, text)` makes one; `.status-*` is the older name for the same thing. `-outline` is a neutral delivery state ("Part received"): an `--ink-4` outline and a half-filled circle, never teal. |
| `.note` (+ `-warn`/`-stale`/`-crit`/`-good`), `.box` (+ `-crit`/`-warn`/`-stale`/`-info`/`-good`), `.box-head` | State boxes, `--r-panel` corners. Every **notice** is `--warn-soft` with an inset `--warn-line` and `--warn-ink` words; its stroke icon in `--warn-icon` says the kind: an info circle (`.box-info`, a plain `.note`: something worth a look), a refresh (`-stale`: something out of date, "Update all") or a triangle (`-warn`: a check or a conflict). The icon is on its `.box-head` when it has one, else in the box's left padding; a box holding a `.spinner` (a run in progress) shows the spinner instead. A note's one trailing button sits at its right. Crit and good aren't notices and keep their fills. A plain `.box` is a neutral container. |
| `.empty` | An empty list: one line, plus the one action that fills it. |
| `.loading`, `.spinner`, `.progress` | Waiting. |
| `summary` | Gets a chevron automatically. Opt out with `summary::before { content: none }`. |
| `.tabs` | Tabs that scroll sideways and show an edge shade. Set `--strip-bg` to the colour they sit on. |
| `dialog.sheet` (+ `.sheet-wide`, `.sheet-side`) | Sheets, `--r-panel` corners; a phone's bottom sheet has a 40×5 grabber (only a picture). Its × is `--ink-2`, not teal. Use `openSheet()`; don't write the markup by hand. |
| `.menu`, `.menu-sep` | A popover menu, `--r-row` corners, items `--btn-h` tall in `--fs-btn` at 600; the item under the pointer or the arrow keys is `--hover`; a disabled item `--ink-3`; destructive items (`.menu-danger`, `--weak-ink`) last, after a `.menu-sep`. Use `openMenu()`. A `menuButton` menu is shifted sideways to stay 8px inside the window when it opens (core.js `keepInWindow`), and a page head's More opens under its button, right-aligned. |
| `.action-bar`, `.action-bar-status` | A sticky bottom bar (`--bar-bg`, a 1px `--border` on top). Use `actionBar()`. Its height and place above the tab bar come with the shell (slice 7). |
| `.toast` | Use `toast()` or `showToast()`. |
| `table.data`, `.th-sort`, `.num` | Data tables: rows `--row-h` tall and middle-aligned with `--divider` lines and a `--hover` hover (mouse only); a 30px sticky header in mono uppercase on `--surface-2`; sortable columns marked with `aria-sort` (44px tall on touch); numbers right-aligned and tabular, mono from 1000px (words under a number, in a `<small>`, stay Figtree), and a words column after a number column gets a 16px gutter. A card's `tr.label-row` (its labels on a second row) takes no row height; it and the row above it stay top-aligned and hover together. Row states for the page slices: `tr[data-selected]` with `aria-current="true"` on its name button (teal soft, a 2px teal bar on its first cell); `tr[data-match]` with `.cell-match` on the matching cell (a 7px teal dot); `tr.group-row` (`role="row"`, one `th` with `role="rowheader"` spanning the columns, `.group-count` for its mono count). Unknown data is `.cell-unknown` (a mono em dash, `aria-hidden`) beside `.sr-only` words, never an `aria-label` on a span. |
| `.panels`/`.panel`, `.tiles`/`.tile`, `.legend`, `.chart`, `.meter` | Layout for stats. |
| `.card-names`, `.card-link`, `.card-link.card-link-text` | Card names inline (deck.js `cardLink`). `-text` is a name inside prose (the play guide): a dotted underline that wraps like the words around it. |

## Card pieces (`cards-ui.css`, `cards-ui.js`, `symbols.js`)

A **card** is the object the API sends for one card (`lib/api/card_lookup.py` `_card_json`): `name`, `mana_cost`, `type_line`, `oracle_text`, `img` and `img_small` (Deck Lab `/img/` addresses, or null), `faces`, and `power`, `toughness`, `loyalty`, `defense`.

### `cardTile(card, opts)` → `<div class="card-tile">`

A card shown as its picture. Put tiles in a `.card-tiles` grid: 3 columns on a phone, about 156px wide on a tablet or desktop, and 196px from 2200px.

| opt | Meaning |
|---|---|
| `qty` | Shows a ×N badge on the picture, only when N > 1 |
| `name` | The words under the picture. The default is the card's front name; when it's shortened, the full name goes in `title`. |
| `meta` | One line, such as `"MSC 143 · Nonfoil"` |
| `finish` | `"foil"` adds a rainbow sheen and a chip; `"etched"` adds a chip |
| `state` | A node for the top-right corner (a tick button, a status badge). It sits outside the open button, so it can be a button itself. |
| `check` | Opt in to a native checkbox label containing static phrasing content. Supply one checkbox; keep chips non-interactive. `state`, `onclick` and `viewerGroup` are unused; place inspection in a separate sibling control. |
| `ticked` | Adds an accent ring and dims the picture (the item is checked off); hover elevation preserves the ring, and keyboard focus has its own outline |
| `unrecorded` | Ribbon words, shown with a dashed frame (`"Default picture: printing not recorded"`) |
| `chips` | Nodes under the meta line: deck chips, `status("warn", "Condition ?")`. Use them only for exceptions. |
| `onclick` | Overrides opening the card viewer (for example, opening an edit sheet) |
| `viewerGroup`, `caption`, `viewerStatus` | Join a viewer group (see below). `viewerStatus` is a function returning chips the viewer shows under its counter, always in sight (the deck page's "Missing · need 1, have 0"). |
| `label`, `sizes` | The open button's accessible name, and `<img sizes>` (the default is `TILE_SIZES`) |
| `large` | A bigger picture's address (the `/img/` route's `large`, 672px) to offer too, for big tiles (the deck page's key cards). If it fails, the tile drops back to the normal picture. |

**A tick on a tile** (Build decks): pass `state: el("button", {type: "button", class: "tile-tick", "aria-pressed": "false", "aria-label": "<name>: done"})` and toggle `aria-pressed` and `.is-ticked` together. Build decks puts `pack-tick` at the picture's bottom-left, clear of costs/copy badges. `.tile-tick` is a 44px button with a ring/circle, and `.tile-tick-plain` is its row variant. Active Receive Pictures instead opt into `check`: the whole tile is a native label, with a separate sibling Inspect button and the page's checkbox sizing/descriptions. Read-only/off parts keep viewer-only tiles.

Without a card, or without a picture, the tile shows the name and type line in card proportions. The same words sit under the picture while it loads, and show if it fails. Class names: `.card-tile-open`, `-pic`, `-img`, `-text`, `-qty`, `-name`, `-meta`, `-state`, `-chips`, `-ribbon`, `-tick`, and the states `.is-foil`, `.is-etched`, `.is-ticked`, `.is-unrecorded`, `.is-text`. Add `.is-missing` (every copy missing: the picture greyed) or `.is-partly-missing` (some missing: half grey) to a tile or a `cardRow`; the deck page does, and then a fully missing card carries no "Missing" chip (the grey says it; a screen reader gets the word), only a partly missing one ("1 of 2 missing"). A tile's name takes up to two lines. A `.card-tiles` grid with `.card-tiles-printing` lets each tile's meta (a printing, such as `TEOC 3/12 · 2/2`) wrap. A printing ("FDN 227") is in the body font with tabular numbers on every page, never monospace; a finish shown as a chip (`finishChip`) isn't repeated in the meta. While a tile with a ×N badge has no picture, its words start under the badge.

### `cardRow(card, opts)` → `<button class="card-row">`

A card as one line of a list: a 40×56 thumbnail, the copies, the name with one meta line (the type line by default), any chips, and the mana cost at the end. Its opts are `qty` (`null` removes the column, giving `.card-row-noqty`), `name`, `meta`, `unknownMeta`, `chips`, `aside` (replaces the cost; `null` for nothing), `onclick`, `viewerGroup`, `caption`, and `thumbWide` (`"(min-width: 1600px) 220px"` where the row is drawn as a picture grid). Without a card it's a `<div>` that opens nothing. The deck page's decklist (`deck.js` `deckCardRow`) is the reference.

### `tokenTile(token, opts)`

`token` is `{front, back?, img?, back_img?}`. Images are loaded only from Deck Lab's `/img/` addresses. The back's picture overlaps the front's corner, and the viewer can flip between the two. `opts` are the same as `cardTile`'s; for `meta` use something like `"TM11 5 · 2/2 Ooze"`.

### `pickPrinting(name, {current, title})` → `Promise`

Opens a sheet with a grid of the card's printings, built from `GET /api/cards/printings` (which now includes `set_name` and `img`). Each tile shows the set code and collector number with the year, the set's name, the copies owned and on the way, and a button for each finish when there's more than one. The current printing is ticked. The promise resolves with `{set, number, finish, set_name, img_small, img, aud, owned, on_the_way}`. For a basic land's "Any printing" it's `{set: null, number: null, finish: "nonfoil"}`. If the sheet is closed, it resolves with `null`. `opts.actions` (`[{text, value, kind}]`, destructive last) adds buttons to the sheet's foot, each resolving with `{action: value}` (the editor's Move and Remove).

`opts.onOpen(sheet)` lets a caller include the picker in its page/profile cleanup,
as Shopping does when its queue editor is left or the person changes.

### `factLine(cls, parts)` (core.js)

A line of facts joined by "·" ("Casual 60 · Matt · 60 cards + 2 sideboard"): each fact stays whole, and a wrapped line never starts with a "·" (each fact carries its dot in front; `.fact-line` clips the dot of whichever fact starts a line). The library tiles and the deck head use it.

### Symbols

| Helper | Use |
|---|---|
| `manaCost(cost, small)` (deck.js) | A cost such as `{2}{R}{R}` drawn as symbol pictures. The cost element has `role="img"` and an `aria-label` ("Mana cost: 2 generic, red, red"). |
| `renderSymbols(text, {small})` | Text with `{…}` in it, returned as a list of parts for `el()` or `add()`. Each symbol is an `<img class="sym">` whose `alt` is its words (`{T}` → "tap"). Braces that don't hold a symbol stay as written. |
| `oracleParagraphs(text, cls)` | Rules text as one `<p>` per line, with symbols drawn and reminder text in italics. |
| `symbolImg(symbol, {small, alt})`, `symbolCode(symbol)`, `symbolAlt(symbol)` | The building blocks. |

The pictures come from the server's `GET /sym/<code>.svg` (`lib/api/symbols.py`). It caches Scryfall's SVGs in `decklab/data/symbols/`: `{W/U}` is stored as `WU.svg`, `{2/W}` as `2W.svg`, `{T}` as `T.svg` and `{½}` as `HALF.svg`. A picture that can't load is swapped for the lettered circle (`pip()` in deck.js).

## The card viewer (`card-viewer.js`)

- `openCard(card, trigger)` is what every page calls. If `trigger` is marked with a viewer group, the viewer opens over the whole group at that card. Otherwise it shows the one card.
- `openCardViewer(items, start, {trigger, caption})` takes `items` as cards or `{card, caption}` objects. `caption(card, index)` supplies a line for items that don't carry their own.
- `viewerItem(node, card, group, caption, status)` marks your own element (`status`: a function returning chips for under the counter). `cardTile` and `cardRow` call it when given `opts.viewerGroup`. `viewerGroup(node)` returns `{items, index}` for a marked element.

How it behaves:

- **Phone:** the card fills the screen on a dark background. A swipe follows the finger and snaps: it moves to the next card past 20% of the width, or on a flick. A "3 / 15" count sits between the Previous and Next buttons. Text opens the rules panel over the bottom of the card without shrinking the portrait image, and that choice is remembered from card to card within the current opening. A new opening starts with Text closed. Touch screens show ?Swipe left or right? beneath the count; touch capture covers the dialog, including the empty space beside the image. Flip appears for cards with a back picture. Back closes the viewer, through a history entry that carries its `pos`. Tapping the dark space around the card closes it too.
- **A phone on its side** (landscape, at most 500px tall, under 1000px wide): Previous and Next run the screen's full height at its edges, the card fills the height, and the head and the words sit beside it, always shown (no Text button). A swipe on the card moves; an up-and-down swipe on the words scrolls them. Swipes are taken on the whole dialog, so on every layout a swipe that starts on the dark space beside the card moves too (a press on a button or link never starts one).
- **From 1000px:** the card with Previous and Next a fixed distance either side of it and the rules panel beside them, the group centred; the panel is as tall as its words, from the card's top. The panel is dark (`--viewer-panel`) on every screen, a one-face card's cost ends its type line, and there's no data-source footnote. The arrow keys, Home and End move between cards, and Escape closes.
- The cards either side are always drawn and the next two are fetched ahead, so a swipe never waits for its picture. The small image shows at once and the normal one replaces it when it arrives; the viewer offers the `/img/` route's `large` (672px) too, through `srcset` (`viewerLargeUrl`, `viewerSrcset`, `VIEWER_SIZES`), so a big screen gets the sharper one.
- **Accessibility:** it's a modal `<dialog>`. Focus goes to Close and returns to the trigger afterwards, the change of card is announced ("Card 3 of 15: Name"), and only the current slide is exposed to screen readers. Under `prefers-reduced-motion`, cards change without sliding.

**Wiring a list.** Give every tile or row on the page the same `viewerGroup`. The group follows page order and skips elements that aren't shown (a folded section, for example), so filters work without extra code.

Groups wired so far:

| Page | Groups |
|---|---|
| Deck page | the decklist (`deck`), the stand-ins sheet and the Play-now list's swaps (`deck-swaps`), the Overview's key cards (`key`), the test hand (`hand`), the play guide's names (`guide`, opened with each card once), other card names drawn with `cardLink` (`names`; `owned-table` for the price table) |
| Matchups | the pair page's per-card tables (`matchup-cards-0`/`-1`), its casts tables (`matchup-casts-0`/`-1`) and its AI-limits names |
| Library | the picture picker's cards (`cover`; its Automatic tile opens the viewer at its card's own tile) |
| Editor | the rows and picture stacks (`editor`), the search results' thumbnails (`editor-results`), a missing card's stand-ins (`editor-swaps`) |
| Receipts | each part's grid (`receipt-<n>`, the part's index) |
| Collection | Find cards lab tiles (`collection`) and casual rows (`collection-find`), Card list thumbnails (`collection-rows`), lab names (`collection-lab-rows`), casual rows (`collection-casual-rows`), precon preview (`precon`) |
| Tokens | the token cards (`tokens`), the Missing and On the way tiles (`tokens-missing`) |
| Wishlist | the cards (`wishlist`), the search results (`wishlist-search`) |
| Shopping | a delivery's strip and its "+N" sheet (one group per delivery), the purchase queue |
| Build decks | every tile of the plan (`packing`) |
| Activity, History | one group per change (`activity-<id>`), per revision, and the revision sheet (`history-sheet`) |

```js
grid.append(...rows.map((r) => cardTile(r.card, {
  qty: r.quantity, meta: `${r.set.toUpperCase()} ${r.collector_number} · ${capitalise(r.finish)}`,
  finish: r.finish, viewerGroup: "receipt", caption: `${r.quantity} in this delivery`,
})));
```

When a tap should open an edit sheet instead, pass `onclick`. The sheet can then offer "Zoom", which calls `openCard(card, button)` for the rules text, or call `openCardViewer(groupItems, i)` itself.

Shopping's order forms live in `shopping-orders.js` (record a placed order) and
`shopping-order-edit.js` (correct record fields and pending arrival checks), with
`shopping-order-rows.js` for full pending row corrections and additional-copy marks.
They share the page's tracked-sheet lifecycle, revision, busy and stale state.
Each preview belongs to the displayed inputs; editing, switching people or
leaving the page invalidates it. Corrections save through their opaque preview
token and refresh Shopping after success. Row forms retain every recorded field,
including blank unknowns and token pairings. Printing pickers belong to the same
sheet lifecycle and block preview while open; splitting rows preserves the
component's total and each playable card's quantity. Confirmation shows the
resulting rows, additional-copy state and affected deck tables.

## The deck page's address

`#/deck?id=<deck id>&v=target|owned[&tab=overview|cards|stats|practice|matchups][&filter=all|missing|coming|held]` (deck.js `deckViewOf`, `deckAddress`). The tab and the Cards tab's filter change in place (`history.replaceState`), so Back leaves the deck rather than stepping through its tabs; an old `?part=field` opens Matchups. Link to a part with `openDeckTab(name, {filter, to})` on the page, or with the address from elsewhere. `GET /api/deck` takes `omit=matchups` (the answer's slowest part, its `matchups` left out): the page asks with it unless it opens on Matchups, and the Matchups tab fetches them when it first opens. `GET /api/deck/cards` is the light read of a deck's cards (the picture picker's), `GET /api/deck/find` the editor's finder.

The head keeps its small library picture on casual widths and promotes it to a 184 px art hero in the lab, with an identity stripe and tinted metadata band (`deckHeadCover`, `deckColourPieces`). From 1000 to 1280 px the actions fold over a 148 px hero; without art the title uses normal ink, and image failure removes the white-on-art treatment. More's "Change library picture." opens `openCoverPicker` for a deck text the viewer may change; a save draws the page again.

`deck-header.js` follows `deck.js`: its previous/next links read a fresh `/api/decks` answer and follow the library's grouped filters/sort while the current deck is included, otherwise all visible ordinary decks. They keep the current tab and card filter, and select Play-now only when the neighbour has it. The first/last arrows are disabled, and the selected deck is remembered for returning to the library. No cached profile's names are reused; late reads check route, screen, profile, connection and request sequence. At narrow lab widths the 44 px opaque `.btn-art` circles sit over the hero, whose top padding reserves their space even for a 100-character title. Both themes use the same white art-control surface and dark teal ink tokens.

The tint metadata's `<time>` reads `summary.edited` from `/api/deck`: the actual last recorded deck edit, ISO UTC seconds at the API, a local-device date on the page and a full date/time in its title. Null/invalid dates add no label, and metadata read failure does not block the deck. The timestamp is looked up only after the deck's visibility check, and matches the library's edit metadata.

`deck-overview.js` follows `deck-header.js`; `deck-overview.css` follows `deck.css`. Overview reads `/api/field` and `/api/variants` once for the displayed list, drawing the existing Forge figure, freshness, range, flags and newest swap result, plus a mana curve with the deck's identity gradient. From 1000 px these panels sit in two columns. Field view and All tests open the existing Matchups controls; reading Overview never starts a run. Loading, empty and unavailable states are explicit. Late answers require the original route, profile, screen and attached panel. The panels do not read inventory, so public-deck viewers get no collection counts from them. The five existing tabs and their lazy loading are retained.

More's **Retire deck…** opens a sheet for an editable unbuilt saved deck
(`deck-retirement.js`). Read its current eligibility, SHA and revision first;
require a reason and explicit confirmation. Retiring retains its history and
saved matchup links, with a link to History after success. Built decks and held
kit must be taken apart or cleared by their owner first. A stale confirmation
requires a fresh read. Close the sheet on navigation, profile changes and the
away lock, and ignore late responses from its old context.

A retired deck's `#/history?id=` remains readable and links back to the library.
Historical revision sheets have no current editor comparison or list-as-draft
action. **Restore deck** restores the last saved text under the same id, with an
explicit confirmation tied to the latest deletion revision. Preserve the
existing historical-owner kit and revision-message redactions.

## The editor at each width

`canBuildDecks()` (editor.js) is true from 600px, except on a touch screen 500px tall or less (a phone on its side): a tablet in either orientation and anything bigger gets the full editor, and app.js routes on the same function. A phone gets the Quick edit (`quickEditing()`): compact rows with steppers, a search sheet offering Paste a list, printings, Status above folded Deck details, Notes and Save; a new deck also has its title, format and "Start from". So Edit, New deck, Save as a new deck and History's "Open … as a draft" are offered at every width; only "Try a change" (someone else's deck, for testing a change against other decks) waits for a tablet or bigger. Don't add a "use a bigger screen" note for anything else.

## Sheets, menus, toasts and the action bar

| Helper | Where | What it does |
|---|---|---|
| `openSheet(title, opts)` or `openSheet({title, body, actions, wide, side, onClose})` | editor.js | Opens a bottom sheet on a phone, a dialog box in the middle on desktop, and with `side`, a panel on the right from 1280px. Returns `{dialog, heading, body, foot, closed, close(result)}`. Destructive actions go last in the foot. |
| `sheetActions(sheet, [{text, kind, onclick, disabled, value}])` | editor.js | Sets the sheet's foot buttons. `kind` is `"primary"`, `"danger"` (a destructive answer), `"danger btn-quiet"` (Remove…), `"discard"` (Discard my changes) or empty. |
| `ask(title, paragraphs, choices)` → `Promise<value\|null>` | editor.js | Asks a question in a sheet. |
| `busy(button, text)`, `unbusy(button)` | editor.js | Puts a spinner in a button while a request runs. |
| `openMenu(anchor, items)` → `{node, close()}` | ui.js | Opens an overflow menu under `anchor`, or above it when it doesn't fit below (the editor's Save caret in the bottom bar); focusing it never scrolls the page. `items` are `{text, onclick?, href?, current?, danger?, disabled?}` objects or `"-"` for a separator. The arrow keys, Home, End, Escape and Tab work in it, and focus returns to the anchor. |
| `toast(message)` | core.js | Shows a plain message for 5 seconds. |
| `showToast(message, {undo, undoText, ms})` → `{close()}` | ui.js | With `undo`, adds an Undo button and stays 8 seconds. Use it for removals and picks that take effect at once, never in place of a confirm for something that can't be undone. |
| `actionBar({status, actions})` → `{node, status(...parts), actions(...nodes)}` | ui.js | A sticky bottom bar with a live status on the left and the primary action on the right. |
| `winRateFigure(rate, {size, what, games, rank, tested, caption, barred})` | sim-ui.js | A win rate (`{value, low, high}`, shares) as a mono figure in ink: `inline` ("61% 59–63", a row), `tile` (61% and "Forge field") or `hero` (the big number with "59–63% 95% range" and "3,400 games · rank 3 of 11" under it). `role="img"`, its words spelt out ("Forge field win rate 61 percent, range 59 to 63, tested 3 days ago"); `what` names the rate. `?` with "not known yet" for no rate. `barred`: it's beside a decorative range bar, so its words also say when that bar clamps the rate. |
| `rangeBar(rate, {compact, axis, what, label, live, muted, decorative})`, `rangeKey()` | sim-ui.js | A rate's range on the fixed 20–80% scale (`left = (value − 20%) / 60%`, so bars compare across pages); a value outside clamps to that end and its spoken words (`role="img"`) say the real one. `compact` 6px (a Matchups row); `axis` adds 20 / 50 / 80; `live` a run's range so far (dashed band); `muted` a result that means nothing (no band). `decorative` beside a win-rate figure (a row, the pair page's verdict, the field's headline): `aria-hidden`, no role or words, and the figure is given `barred`, so a row link's name says the win rate once. Only a bar with no figure beside it (a live run's range) speaks. `rangeKey()` is its legend. |
| `freshnessBadge(when, {verb, byDate, changed, unsaved, size, compact, onTint, staleWords, now})` → node or `null` | sim-ui.js | How old a result, or any dated check, is: "tested 3 days ago" (`compact`: "3 days ago"), aging from 8 days, stale from 31 ("retest: 5 weeks ago"; "check again" for a check that isn't a test), `changed` "retest: changed since", `unsaved` "for the saved list". `verb` "pulled" with `byDate` gives "pulled 24 Oct" (prices), "checked" a shop's check. `null` without a date (except `unsaved`, and `changed`, whose words don't need one), so draw nothing. The real date is in its spoken words, on a `role="img"`. `size`: `row` (plain words while fresh), `panel`, `casual`. |
| `forgeFlag(kind, {name, rate, short})` | sim-ui.js | "Strong against" or "weak against": a round pill in Forge's colours with a chevron, the opponent's name (it truncates) and the mono win rate; without a name it says "strong against" (after the name in a list); `short` "strong"/"weak". Screen readers always get the words. |
| `swapResult({changes, delta, low, high, games, gamesText, verdict, neutral})`, `swapVerdict(...)` | sim-ui.js | A test of a change: the swap ("−1 Abrade" in `--weak-ink`, "+1 Burst Lightning" in `--strong-ink`, quantities mono), the difference ("+3.1 points"), a verdict pill worked out from the range ("better" when it's all above 0, "worse" all below, "probably better/worse, not proven" when it leans, "no clear difference" otherwise or when the server found little difference) and "−0.4 to +6.6 · 600 paired games". `neutral` greys the +1 and −1 of a curve or count change. |
| `deckColourPieces(identity)` → `{colours, label, pips(size, {overArt, cls}), stripe(thin), swatch(), tint(angle), art, vars(angle)}` or `null` | ui.js | A deck's colour pieces (`design/visual-design.md` 4.3) from its colour identity: the W/U/B/R/G of its commander's `color_identity`, else its cards' (the library's `colors` from `/api/decks`, `null` when no card could be read; the deck page's `deckPageColours`), never typed. `[]` is colourless (one C); `null` (no card could be read) gives `null`, so draw nothing. `pips` is a `role="img"` group named "Colours: blue, red" ("Colourless"), WUBRG, at 16 (a lab row), 20 (a casual tile, a lab band), 22 (a casual deck head) or 24px (a filter toggle). `stripe` (5px; `thin` 3px under a thumbnail) and `swatch` (before a deck's name on a page that isn't about decks) are `aria-hidden`: put the pips or the name beside them. `tint` is a background image (135deg on tiles, 90 on bands; neutral for four or five colours), `art` a picture's placeholder colour, and `vars` sets `--deck-stripe`, `--deck-tint` and `--deck-art` on an element for its own rules (the library's cover). Pips are only a deck's (or a card's) identity; a cost is `manaCost()`. Used by the library's tiles and the deck page's head. |
| `ownedBar(owned, waiting, total)` | ui.js | The owned bar (4.10): an `aria-hidden` 4px track (`--surface-3`, `--accent-track` on a selected row) with the owned part in `--accent` and the cards on the way hatched after it. Put the counts in words beside it (the library's `deckOwned`: "51 owned · 1 on the way · 8 to get" on a tile, mono "48 +4 · 8 to get" with an `aria-label` in a lab row). |

Centered sheets limit their height with dynamic viewport units so Safari's
visible browser bars cannot cover their heading or Close control, including a
phone turned sideways. Their body scrolls; phone-bottom-sheet and desktop
side-panel rules keep their existing limits.

## The app shell (`core.js`, `shell.js`, `shell.css`)

The shell is drawn once by `shell.js`; pages only fill `#main`. Its parts are in `index.html`: `#topbar` (sticky, with `#topbar-back`, `.brand`, `#topbar-title`, `#main-nav`, `#shell-status` and the avatar menu), `#tabbar` and `dialog#more-sheet` under 1000px, and the one-line footer `#footer-data`.

Two chromes (`design/visual-design.md` 3.1 and section 6 decision 5; E11-S30 slice 7): **the lab top bar** from 1000px, and on a phone on its side (`(orientation: landscape) and (max-height: 500px)`): the brand, the nav as round pills (`.nav-item`, `--ctl-h` tall, the page's section in `--accent-strong` on `--accent-soft`, hover only with a mouse), `#shell-status` and the avatar. **The casual header and tab bar** everywhere else under 1000px, the iPad in portrait included: the way back or the brand, the page's title once its h1 scrolls away, `#shell-status`, the avatar, and the tab bar fixed to the bottom with the first `TAB_COUNT` (4) main pages and More (Decks, Collection, Shopping, Matchups, More for home), its tabs in the middle 640px from 600px. The media query for "casual" is written out in `shell.css` (`(max-width: 599px), (max-width: 999px) and (min-height: 501px), (max-width: 999px) and (orientation: portrait)`); copy it exactly when a rule must follow the chrome rather than the density. No page hides the tab bar: a page's bar (`.action-bar`, the editor's `.edit-bar`, Receive delivery's Record bar) sits on it, and only `body.keyboard-up` (the on-screen keyboard over the editor's search) puts it away. There's no global search yet (E11-S31).

The Shopping link's count of deliveries waiting (`.nav-badge`, in the top bar and the tab bar) is `aria-hidden`; its words are in the link's own name, starting with the visible word (`aria-label="Shopping, 2 deliveries waiting"`, `showDeliveries`), as screen readers skip an `aria-label` on a plain `<span>` (`design/visual-design.md` 4.5 and section 6 item 12).

### The routes table

`ROUTES` in `core.js` is the one place a page's name lives. Each entry is `{path, label, h1, title, icon, nav, visible}` for a top-level page (`nav` is `"main"`, `"more"` or `"account"`) or `{path, label, h1, title, parent}` for a child page (`deck`, `edit`, `new`, `history`, `variant`, `receipt`, `matchup`). `visible(profile, may)` hides a page from people who may not use it (Shopping and Build decks need home's inventory, Sleeves & boxes a home profile, Settings an admin).

| Helper | What it gives |
|---|---|
| `routeFor(path)` | The route (the library's for an unknown path). Use `routeFor(path).label` for a link's words. |
| `routeH1(path)` | The page's heading. Never type a page's name by hand. |
| `routeSection(path)` | The nav section a child page counts under (a deck page is under Decks). |
| `navRoutes(group[, profile, may])`, `routeVisible(route[, profile, may])` | The visible routes of a nav group; whether one route shows. |
| `seesHomeInventory(may)`, `isAdminProfile([profile, may])` | Who sees home's inventory; who is an admin (by the config role). Use these for admin-only or inventory-only UI. |
| `setTitle(text)` | Sets `document.title` to "text – Deck Lab" and the phone's top-bar title. `route()` sets the route's title before a page draws; a page calls `setTitle(subject)` to name what it shows. Never assign `document.title` directly. |

### The two lists' names

`LIST_NAME = {target: "Planned list", owned: "Play-now list"}` and `listName(version, lower = false)` ("planned list" inside a sentence). Use them for every word the page shows about a deck's two lists. The version keys (`target`, `owned`) and the deck text's headings don't change.

### Page heads

- **`crumb(href, label)`** → `<nav class="crumbs shell-crumb">` with "← label". Use it only on child pages, named after the parent ("← Decks", "← Gruul Ramp", "← Shopping"). It also records `state.crumb`, which the casual header shows as its back link, so the page's own copy is hidden there (under 1000px, but on a phone on its side). `route()` resets it on every route.
- **`pageHead({crumb: [href, label], title, description, primary, more, id})`** → the nodes to `add(main, [...])`: the crumb, the h1, a one-line description, one primary action and a "More" menu for the rest. `more` items are `{label, href}`, `{label, onclick, danger?, current?}`, `"sep"` or `null` (skipped).
- **`menuButton(label, items, {aria, buttonClass})`** → `<span class="menu-wrap">`: a button that opens a menu of the same items as `more`. `wireMenu(button, menuEl)` turns any popover into such a menu (Esc, a click outside, the arrow keys, `aria-expanded`), and `closeMenus()` closes them all.
- `menuButton` is for a menu that is always on the page (a head's "More", a row's "⋯"). `openMenu(anchor, items)` in `ui.js` opens a one-off menu built when it's needed. Both close on Esc and an outside click.

### Simulations

`simulationsGate()` (version.js) → `{may, why}`, from `GET /api/simulations`; `why` is the sentence to show beside a disabled run button ("Only an admin can start simulations right now. Saved results still show."; it names nobody, E10-S34). `mayStartRuns()` is `simulationsGate().may`, and `syncRunControls()` keeps `data-run` buttons in step. The setting itself is on the Settings page (`#/settings`, admins only). **There is no page-wide simulations banner; don't add one.** In the matchup scripts, `runsAllowed()` and `runGate()` (matchups.js) wrap these for pages that may load without version.js; hide a run choice (and a "Play a matchup" link) when `!runsAllowed()`.

The matchup scripts' shared run pieces (matchups.js): `runChoiceControl(options, value, onPick)` → `{node, redraw()}`, the one run vocabulary (Quick look, Settle it, Precise, and a set number under More options) used for matchups, field budgets and variant tests; `runModeChoice(data, onChange)` (with `setCommander()` and `setEstimates()`) and `gamesChoice(...)` (with `setEstimates()`) build on it. `checkBar(label)` is a progress bar marked at a run's planned checks. `plainVerdict(result, titles)` is a result's one-sentence verdict ("Mono-White Angels is a big favourite: wins about 9 in 10").

A blocked run control stays the page's own button, disabled, with the reason on the line under its row. This replaces WP2's idea of swapping the button for "Ask Matt to play this": a button that can't do anything shouldn't look like one you can press, and the same line covers every reason (admins only, or simulations paused), naming who can start runs.

### Matchups opponent views

The Matchups home uses `matchupEntries` for one best saved result per opponent, ordered best first and uninformative results last. Mouse input from 1000 px gets a real six-column table; casual widths get cards; coarse input from 1000 px gets whole-row links with 44 px targets and an inset focus ring. Both views retain exact perspective and saved-result destinations, current-list/engine selection, exceptions and start permissions. Table/list semantics are not mixed. Adjacent range bars are decorative, and a linked row's spoken name says the opponent and rate once. No pair percentage is treated as a field rating or residual flag.

`simulationsChip()` adds a neutral, noninteractive lock chip beside the title through `pageHead`'s optional `badge`. It shows the server's known mode only (Admins only, Anyone or Paused), updates through `renderSimulations`, and discloses no setter identity, date or worker count. Unknown modes stay hidden. Reasons remain beside run controls; saved results stay readable.

`matchups-summary.js` follows the overview and uses the shared field/swap renderers. Two named panels show the selected deck's explicit Planned or built Play-now list; the field API must echo that exact identity and format. Recorded swaps keep the cards they tested. The per-view cache is bounded, keyed by person/list/revisions/saved results, and uses the existing foreground watcher to refresh independently changing swap history. Route, person, selection, attachment and request-sequence guards reject stale answers; reads time out with an explicit retry. Reading never starts a simulation. Casual panels stack and freshness wraps inside the swap panel.

All tests links use `part=tests`, focus `sec-tests` while its deck remains current, and clear the shell/sticky tabs. Late field and matchup content redraws use the app's existing `keepPlace` anchor, which yields when the reader scrolls.

### Matchups rankings

`matchups-overview.js` owns the Matchups / Rankings segmented control on `#/matchups`; both views share the existing format selection. Rankings reads `GET /api/rankings?format=Constructed|Commander` and starts no simulations. Render each server-connected group separately, sorted by percentage rating, with the 95% rating range, likely rank range, decided games and Unsettled reasons. The rating estimates the win rate against an average current field list in that group, balanced for who starts. Keep unrated and excluded current lists visible; excluded rows show the reason without a game count. Never imply a rank between disconnected groups or compare formats. Ratings use `winRateFigure`; rank, range and game numerals use `simNumbers`, so words keep the body font. Casual widths stack the rating below its deck name; the shared hero value never wraps its percent sign onto another line.

While Rankings is selected and visible, its read is single-flight: refresh after 15 seconds without a result change, or promptly after results change. Its AbortController cancels on hidden/pagehide, stop, route or view exit; reject stale route/profile answers. Each read has a 12-second deadline and a clear failure state. Keep this lifecycle within the existing Matchups overview; `matchups.css` supplies its responsive rows.

### `#shell-status`

A slot in the top bar, right of the nav, for the run activity (`runs-pill.js`; `design/visual-design.md` 4.9 and section 6 decision 3): while Forge plays or waits, one 44px button with a turning ring, named "Forge is playing: show progress" ("A Forge run is waiting: …"), and nothing at all otherwise. There's no pill of words. The button opens the details, a popover under it from 1000px (it closes on Escape, a click elsewhere or a new page, but not on a click in Stop's question over it nor the Escape that closes that question) and a sheet below: each run playing ("Forge playing: A vs B" as a `role="status"` line, a `role="progressbar"` ring, "game 37 of 200", about how long is left from the server's `eta_s`, "Open it" unless it's of a space the viewer can't see, and Stop named "Stop the Forge run" when its `may_stop` lets the viewer), the runs waiting, and "Every run on Matchups". Stop goes through `stopListedRun` (it asks first, by the run's key); while its question is open the details don't redraw. Each redraw gives the focus back to the link or button that had it (each has a `data-focus`), or to the first one once it's gone. `syncShell()` calls `syncRunsPill()` and `hideShell()` calls `stopRunsPill()`. It asks `GET /api/matchups?running=1` (no saved results read) every 4s while a run plays and every 45s when idle, only while the page is visible; pages that already have the runs pass them with `noteRuns(running)`. The slot is a size container: the icon goes when there's under 44px of free space (between 600 and 720px there's no room beside the nav). Keep it the only thing there. It's in the lab top bar and the casual header alike (slice 7).

### Offsets: `--shell-top` and `--shell-bottom`

- `--shell-top` (tokens.css) is the top bar's or casual header's height with the safe area: 56px at both. Anything sticky at the top uses `top: var(--shell-top)` (a deck page's section nav, `table.data`'s head, the editor's side panel), and anchors scrolled to use it in `scroll-margin-top`. In JS, `NAV_SPACE` already includes it.
- A phone on its side (`(orientation: landscape) and (max-height: 500px)`) has no sticky top bar: there it's `position: static` and `--shell-top` is just the safe-area inset, so only the deck tabs (or the part's own sticky head) stay on screen. In JS, read a sticky element's computed `top` rather than assuming `SHELL_TOP`.
- Sticky bars that run edge to edge (`.deck-tabs`, `.action-bar`, `.edit-bar`) pad their sides with `max(var(--gutter), env(safe-area-inset-left/right))`, so a phone on its side keeps them clear of the Dynamic Island.
- `--shell-bottom` is set on `body.has-shell` wherever the tab bar shows (56px plus the safe area; 0 while `keyboard-up`). Anything sticky or fixed at the bottom uses `bottom: var(--shell-bottom, 0px)` (`.action-bar`, toasts); the editor's bar uses `max()` of it and `--editor-keyboard-bottom`.
- A page's bar is at least `--bar-h` tall (72px casual, 60px in the lab) plus the safe area; on the tab bar it drops the safe area, which the tab bar has. A toast goes `--bar-h` higher while the page has one (`body.has-edit-bar`, `body:has(#main .action-bar)`), and the Matchups tab gets an 8px dot (`.tab.has-run`, runs-pill.js) while a run plays or waits.
- The editor's bar adds `--editor-keyboard-bottom` while a touch keyboard reduces the visible height. It tracks both visual-viewport resize and pan, keeping Save above Safari's input accessory row. Desktop resizing and pinch zoom alone leave the inset at zero; searching keeps its existing bar-hiding rule.
- The card viewer and sheets are modal dialogs in the top layer, so they cover the bars without any offset.

### This is my device

The avatar menu?s **Reload page** calls `reloadDeckLab()` (version.js), also used by the update banner. It changes only the page?s `v` query token, retaining the route and other options, and navigates through the normal unsaved-editor guard. The HTTP layer stamps CSS/JS URLs in the served HTML with the web revision so changed assets have new addresses. It does not clear local or session storage.

The avatar menu's "This is my device" (home network only) stores the profile id in `localStorage` key `decklab.myDevice`; that profile is chosen at start without the Who screen and isn't forgotten when the page has been away. Read it with `isMyDevice(profile)` or `myDeviceId()`.

## Remembered on the device

Per-viewer conveniences only, through core.js's `local` (every key gets the prefix `decklab.`, and every read and write is wrapped in try/catch, so a page works without storage): `myDevice`, `lastProfile`, `theme.<profile>`, the library's `library.products.open`, the deck page's `deck.cardsView` (List or Pictures), the editor's drafts (`draft.<profile>.<deck id>.<version>`, `draft.<profile>.new.…`) and its `editLook`, `editSide`, `editFilters` and `editAddTip`, the Receipts board's `receiptLayout` and its unfinished check (`receipt:<profile>:<order>:<fingerprint>`), Build decks ticks (`packing.<decks and lists, sorted>.<plan fingerprint>`), `packing-order.<profile>` (Name or Storage order), `collection.rowsSort`, `tokens.filter`, `tokens.search`, `accessories.filter`, and the Matchups home's `matchups.view`, `matchups.format`, `matchups.deck` and `matchups.engineNoteSeen`. core.js's `session` (`sessionStorage`) holds the visit's `profile` and `hiddenAt`. Nothing that has to last or be shared goes here.

## Other shared pieces added by the pages

- Build decks (`assembly.js`) sorts each storage group by ascending mana value, then name, with unknown values last. Card-step and group headings count copies, including basic lands; totals stay fixed as ticks change. Per-deck `finishes` describe the selected list: uniform foil/etched uses `cardTile`'s finish chip, mixed finishes show the list quantities. Returns never inherit target-list finishes. The sticky bar's **Mark as built** action is enabled after the card tasks are checked and the server confirms availability and edit permission; optional token and kit ticks do not block it. Saving keeps the checked checklist visible and shows Built on each saved deck. Selection changes disable completion until the new preview arrives, and failed saves retain ticks with an inline Refresh plan action.
- `accessoryThumb` (accessories.js) draws a dashed "None chosen" slot when nothing is chosen, on the deck page, Build decks, the kit pickers and the editor's Sleeves and Deck box tiles (its None tile; older free text shows its first letter).
- `tokenThumb(url, px, label)` (tokens.js) is a token's picture or its first letter. A token with no printing shows example art of a token with that name, always labelled "Example art": the Tokens page's tiles (`tokTileParts`) and the deck page's token needs (the API's `example` beside a need's `image`).
- The wishlist's Remove has an Undo toast that puts the card back at its old place (the add's `at`, the index it had; `rules.insert_slot` in the state store).
- `openCoverPicker(deckId, onDone)` (cover.js) opens the deck picture picker (`GET /api/deck/cards`, saved with `POST /api/deck/cover`); `onDone(cover, revision)` runs after a save. The library's "Choose deck pictures" and the deck page's More menu use it, only for a deck text the viewer may change (never a product or pairing).
- The editor's card finder is `GET /api/deck/find` (not `/api/deck/cards`, which is the picker's).

The deck Overview's opponent-specific sideboard section (`deck-sideboard.js`) uses `cardTile` in the shared `card-tiles` grid for historical in/out printings, in two columns that stack on phones. It loads viewer-filtered play records only when Overview is drawn, checks route/profile/node before applying replies, and uses the Game log's preview/save sheet with both chosen list versions. Stored records and their hashes contain no presentation fields.

The Overview's `deck-opponents.js` section uses ordinary links and a checkbox
sheet for usual opponents. The API resolves reciprocal links and filters both
ends for visibility. Saves use the reviewed text hash; a conflict requires
Reload choices. `closeDeckOpponentSheets` closes these sheets on navigation,
profile changes and the away lock; delayed reads and saves check their original
viewer and route. Packing and new Forge matchup pickers put eligible usual
opponents in a leading group while preserving explicit selections.

Collection Card list presentation lives in `collection-rows.js`, loaded after `collection.js`: unknown condition/language cells pair a decorative em dash with spoken words, lab metadata shows codes, and casual metadata shows unusual or unknown words. Foil/etched use the shared neutral finish pill; non-foil is plain. The missing-details info notice and storage toggle retain their native checkbox filters. The bulk action visibly names every filtered row, including rows beyond the displayed page. Prices remain per-copy estimates for each printing/finish, with one rate and a local-calendar source-date freshness badge; unknown dates stay explicit. Collection language options match the backend supported codes.

The lab table has separate Colour identity, Type, Printing, Finish, Copies, Condition, Language, In decks, price and Notes columns. Identity pips come from `card.color_identity`, including explicit colourless/unknown handling. Usage remains anonymous held/free counts with spoken uncertainty and basic-land unknowns. Container queries hide identity, type and language first, then notes. The named, keyboard-focusable table region scrolls independently with a local sticky header; preferred widths fit wide panes, while the 1000px edge keeps local horizontal scrolling. Fine-pointer rows include their divider in 36px; coarse controls retain their 44px floor. Within the table, J/K follows the current filtered order across page boundaries without wrapping. Enter restores the selected page and opens the card from a fresh visible lab viewer-group trigger, so Close returns focus correctly; unknown cards use the existing permitted edit flow or focus the read-only preview. Headers retain native Enter, and text fields/modifiers/busy/stale contexts retain their guards. Keyboard hints show only in the fine-pointer hover lab.

`collection-rows.js` also owns the lab's keyed selection/preview and casual list. A lab name selects the current printing/finish; Edit copies opens the existing guarded sheet. The preview is 400px, 340px at 1000–1280, with local scrolling in its narrow table. Casual rows share the same filtered set, show 24 at a time and focus the first added row after Show more. Their viewer captions preserve recorded notes and alternate-printing warnings. The search/filter band stays below the shell; its tracked sheet changes the same native predicates and sort. Neither pagination nor Show more changes bulk scope. Storage is expressed as counts/uncertainty/basic-land wording, never inferred holder names.

Shopping's `.shop-layout` uses a 560px list pane from 1281px: existing deliveries, follow-ups and By shop research stay left; buying, Missing cards, legacy deck shortfalls and long-term plans stay right. It stacks through 1280px with Parts of this page links that focus their destinations while retaining `#/shopping`. Buying redraws keep delivery, follow-up Undo and history nodes. Empty/last-row transitions mount or remove the same frame. The queue identity, permissions and receipt workflow are unchanged; canonical queue rows are grouped into Ready, Waiting (with stock/reprint reasons) and Deferred, with Long-term still grouped by deck. Native shop radio rows show row/copy counts and mark canonical rows; no duplicate research viewers or write controls remain. A removable matching chip resets to All and returns focus. Matching Long-term groups reveal through their append-only Show all path, preserving existing controls. Research/check-date/stock facts remain on canonical rows without a price/image; zero stays valid. The lab now uses real tables through `shopping-queue.js`, with 36px mouse rows including inset dividers and 30px headers/group rows. Their bounded, focusable scroll region has local sticky headers; the detail grid has explicit minimum-width constraints. CSS minimums are 840/750px (with/without For) and 890/800px on coarse input; the fine immediate fixture needs about 891px for complete actions and printing facts (about 801px without For). A single attached representation moves original viewer/deck/research/write nodes at 1000px, preserving focus and current row/revision guards. Full notes/reprint details expand in an adjacent row; clipped words retain full text/title. Fixed menus escape the frame and clear coordinates in casual density. Notes controls use `--btn-h` (32px fine, 44px coarse) and remain inside ordinary rows. `test_shopping_queue_table_ui.py` covers projection, viewer/research close, read-only/unknown data, matching and save/move/remove lifecycle. Deliveries use native details/summary rows with a 54px minimum collapsed height, wrapping full names and explicit pending-copy/date/status metadata. Bodies retain all existing checks and guarded actions; 44px strip pictures keep responsive hidden-copy counts and the complete-contents sheet. Summary/thumbnail focus rings stay inset, and the delivery-only chevron suppresses the global summary marker without changing nested checks. A focused delivery summary exposes R to open its Receive page, with `aria-keyshortcuts` and a linked description distinguishing native Enter/Space expansion. A fine-hover hint accompanies the action. Navigation rechecks the live root/route/profile/current order, pending parts and receipts permission; busy/stale/modifier/composition/repeat and child-control events are ignored. It performs no read or arrival write. Casual research uses the shared freshness badge only for valid non-future saved check days; unknown/invalid/future dates stay factual, and lab cells retain exact semantic ISO dates. Casual printing intent pairs full spoken wording with decorative exact/any and neutral finish presentation. Concise viewer names retain the full saved evidence in captions. `test_shopping_metadata_ui.py` covers dates, unknown/zero facts, printing and retained projection identity. Linked queue rows and Long-term headings use validated optional Planned/library swatches from the current answer; unknown has none and known colourless is neutral. The server checks visible home choices before target reads and memoizes per request, without using card colours or a library/owned cache. Colour fields remain outside canonical queue data and writes. A typed malformed returned-card identity fault removes only optional decoration in Shopping and the existing pool colour projection; physical counts and holder provenance stay intact. `test_shopping_colors.py`, `test_pool_optional_identity.py` and `test_shopping_colors_ui.py` cover these boundaries. Casual By state/By shop controls regroup the same immediate rows/viewer/research/write nodes; shop groups preserve saved category wording and explicit unchecked shops, independently of matching and Long-term reveal. The view-local choice survives lab state tables and write redraws. One existing Add node moves after layout mounting between its header home and a 44px casual round slot; its label uses the shared visually hidden treatment only while round. Sheet/focus, busy/stale and permission guards remain intact. `test_shopping_casual_controls_ui.py` covers these lifecycle boundaries. Dense Printing cells use shared neutral finish pills in a 16px line, with collector number/finish held visible and long set tags clipped with full title/spoken intent. Nonfoil remains plain, missing/older values stay factual and waiting reasons remain separate. The 156px preferred column preserves ordinary 36px rows and bounded scrolling. `test_shopping_metadata_ui.py` and `test_shopping_queue_table_ui.py` cover intent, retained controls and state/resize boundaries.

Receive uses `receipt-layout.js` for its order/date header, card-copy progress and loaded-data guidance. Products count separately. The board and a 452px named, focusable, sticky/scrollable aside sit together from 1000px; narrower views stack. Advice uses only selected/ticked rows and loaded needs/kit data, with capped split hints and explicit unknown/basic destinations. The Record bar remains the one existing action surface outside the frame. Its actual height is measured into `--rcpt-bar-height`; lab max-height and focus-scroll margins reserve the greater of that height and `--bar-h`. The scoped observer disconnects on stale/detached/done views; sync updates support the fallback. `test_receipt_layout_ui.py` covers copy units, uncertainty, unchanged preview/apply, lifecycle and clearance. Pre-record and success renderers share `rcptDestinationAdvice`: only the supplied selected/ticked or frozen recorded copies contribute. Unknown metadata and untracked basics remain separate from storage, with repeated split hints capped; known-empty nonbasic metadata permits storage advice. The API preserves per-row `null` for unresolved logical names and `[]` for known cards without a matching deck; missing printing/picture data alone does not remove logical destination confidence. Product/token scope and all preview/apply payloads remain unchanged. `test_receipt_destinations_ui.py` guards post-record uncertainty and frozen partial quantities. Attention and fill labels explicitly count rows; header/bar progress counts card copies, with whole products separate. Filtering and bulk-fill scope are unchanged, including hidden rows. List mode opts into `cardRow(card, {compact:true})` without changing other callers. Native checkboxes live in sibling labels, not inside inspection buttons. Lab ordinary rows are 44px including the divider with zero list gap; labels are 40px wide (44px coarse) with an 18px checkbox. Metadata, attention and pending split cues remain visible and may grow the row. Controls reference unique row details/part descriptions. Rejected changes restore accepted checked state, and sheet/filtered-row close focuses a fresh visible trigger. Read-only/products and the remembered layout choice stay unchanged. `test_receipt_compact_ui.py` guards native-change, scope, descriptions, attention and focus. Ticked is a view-only fourth filter, preserving Attention ordering and all hidden-row bulk/request scope. An optional validated filter field joins existing v1 drafts; older/malformed values restore All, and a filter alone creates no draft. Filter changes retain valid previews, with active/done guards and fresh visible check/Show all focus. Hidden-blocker navigation persists All. `test_receipt_ticked_ui.py` covers scope, draft compatibility, preview retention and both layouts. Active Pictures use the opt-in shared native label path with a sibling Inspect button as the sole per-row viewer trigger. `receipt-tiles.js` owns both layouts' rendering; runtime and fixture registries include it. Native changes roll back if rejected; descriptions and fresh filtered/sheet focus preserve split/attention scope. Casual checks are 28px in 52px cells, lab checks 18px in 44px cells, Inspect at least 44px. Casual checked card images use .42 opacity plus one decorative 40px disc, omitted/hidden for missing or failed art. `test_receipt_pictures_ui.py` guards native structure, scope, guards, defaults, tokens and focus. Component checks remain separate until an authoritative row association exists. The final bar keeps native date semantics and shared field sizing, with measured wrapping/clearance. `test_receipt_bar_ui.py` covers primary/blocker focus, partial blanks, exact review/apply, product/token choices, dates including malformed restored types, and stale/recovery guards. Receipt destination hints carry optional canonical Planned identity from the same already-read target sections, after home/kind/visibility checks. Unknown/null and known colourless/empty remain distinct; typed/local-index decoration faults preserve canonical rows, counts, fingerprints, provenance and read counts. Guidance, frozen success headings, inspection links and plain row-name chips use validated decorative swatches, without extra requests, forms or viewer triggers. Compact lab chips retain their existing hiding. `test_receipt_colors.py` and `test_receipt_colors_ui.py` cover privacy, shared identity, per-output copies, optional faults, unchanged scope/draft/preview and label phrasing. The retained Selected row facts/action resolve exact current component id/runtime key, preserving split identity, unknown details and explicit hidden-row recovery. Initial context is a visible selected-part row, never an arrival claim. The single Edit details action reuses the guarded inspector/form/viewer; edits, split/merge and draft restoration refresh current facts and close focus. Casual values use words and lab values use codes. No extra reads, canonical fields, checks, draft creation or preview invalidation come from context selection. `test_receipt_selected_ui.py` covers lifecycle/membership, uncertainty, hidden parts and current values. Inline component-check association remains a separate data-contract gate.

Find cards keeps its name-level API/counts and lab card grid, with one panel of 56px-picture rows below 1000px. Identity pips use `color_identity`; the clearly labelled Card colour selector still uses the existing card-colour predicate. This is a compatibility default, not a new semantic decision. Owned/free/incoming/held/basic-land facts stay server-provided, and name-level rows do not invent per-printing prices. Separate viewer groups exclude the hidden density. The closed casual filter band is sticky with a 48px search and 50px filter button, live active count and a scrolling availability row. Expanded filters enter page flow so short landscape windows can reach results. Query keys, space/paging limits, async sequencing and guarded Edit copies are retained.

Collection storage answers add optional `listed_holders: [{id, title, quantity, version, colors?}]` and `unattributed` beside unchanged `held`/`guess`. These are visible, uncontested saved packing-list printing hints, not verified physical assignments. Source kind is `target`/`owned`; an assembly snapshot may retain older lines, so this is no historical-revision guarantee. Stand-in-affected names, competing/overcommitted claims and cheapest remainders remain anonymous. The existing deck/product visibility gate runs before identities are returned; expected visibility-read failures clear every optional name while retaining aggregate counts. Basics keep null allocation. Metadata stays outside canonical rows/hash and uses the existing pool/recipe read.

The Card list consumes those hints only when the full identity/title/quantity/version list validates and named quantities plus anonymous remainder equal held copies. Malformed, overcommitted, basic, unsupported and older answers stay anonymous. A static table marker preserves density; full guarded links appear in the selected preview and both casual/lab viewer captions. Links name Planned/Play-now, open the current list, and revalidate the active route/person/root/current row and hint before and after viewer close. The copy explains that saved lists may differ from boxes/current lists. `colWithoutHints` clones retained legacy storage and strips named metadata when saves/conflicts omit fresh storage, even with the same hash; fresh answers restore it. Shared viewer links use `--viewer-link` on their always-dark panel, independent of page theme (7.17:1 measured); `test_viewer_contrast.py` guards the shared two-theme contrast requirement. Optional hint swatches describe canonical Planned/library identity, independently of source kind; viewed owned-hero colours may differ. Unknown/invalid colours draw nothing without discarding valid hints, while an explicit empty array means known colourless. Colours pass the same visibility gate and use already-read target sections; an expected local-index failure removes only the optional swatch. Viewer hint swatches reuse the existing dark stripe palette locally; normal previews retain their page-theme palette. Minimum decorative-cue contrast on the viewer panel is 4.20:1, separate from the link text requirement.

Collection row editing and conflict recovery live in `collection-cards.js`; `collection-guards.js` owns optional reduction reasons, advisory held-copy confirmations and repeat-import warnings; `collection-bulk.js` owns the Card list's Set condition & language sheet (E7-S29). They use the shared sheet, field, button and warning components. Collection sheets open through `colOpenSheet`; the shared printing picker joins the same tracking set through its `onOpen` hook. They close on route/profile/away-lock changes via `colCloseSheets`; delayed work checks the original viewer before opening another sheet. Import apply captures the reviewed preview and disables file selection while it waits.

## Tests

- `decklab/tests/test_card_inspector.py`: the viewer under Node, covering faces and flip, rules with symbols, image errors and retry, tap versus backdrop, Escape, focus, groups, the arrow keys, swipes (distance, flick, the ends, vertical moves), Back, and reduced versus normal motion.
- `decklab/tests/test_symbols.py`: the `/sym/` cache and route, with the network mocked.
- `decklab/tests/test_shell_ui.py`: the routes table, the shell's nav and avatar menu, and This is my device.
- `decklab/tests/test_web.py`: load order, one definition per name, history entries, the token scales, and the decklist's picture grid.
- `decklab/tests/test_device_layout_ui.py`: the device-specific rules listed under "Test devices" (stylesheet text), `canBuildDecks` for each device class, `DensityTokenTests` (every density token's value on each test device, worked out from `tokens.css`'s media blocks, the 1000px switch and the 44px touch floor), `ShellTests` (the casual chrome's media query and a phone on its side, no page hiding the tab bar, `--bar-h`, the nav pills, the iPad's 640px tabs, the Matchups tab's dot), `ComponentTests` (the components read the tokens, the one touch-floor block, hovers only with a mouse, teal for selected and changed but not "Part received"), `DeckColourTests` (each colour's deck tokens in both themes, the pieces' rules, and the library and deck head using the helper), `DeckColourUiTests` (`deckColourPieces` under Node for every colour count, colourless and unknown), `SimComponentTests` (Forge's pieces mono and in ink, flags and verdicts in Forge's colours, `--win`/`--loss` only in the matrix, the freshness badge's states, the run activity and its forced colours) and `SimComponentUiTests` (`sim-ui.js` under Node: the figure's sizes and words, the range bar's 20–80 positions and clamping and its decorative form, the badge's ages, flags and the swap test's verdicts); `test_ui_menu` (menus opening above), `test_accessories_sheet_ui` (the edit sheet's focus on touch) and `test_history_strip_ui` (History's one-row strips).
- Each page has its own Node tests over the same DOM double (`fixtures/workspace_ui_runner.js`): `test_deck_page_ui`, `test_deck_sideboard_ui`, `test_library_ui` (tiles, the lab's rows and detail pane, the Forge line), `test_editor_ui`, `test_receipts_ui`, `test_shopping_ui`, `test_play_ui`, `test_wishlist_ui`, `test_feature_ui` (Collection, Build decks, History), `test_feature_ui_accessories` (Sleeves & boxes), `test_feature_ui_tokens` (Tokens), `test_activity_ui`, `test_web_matchups` (with the run activity's icon and details) and `test_web_variant`; `test_forge_stop_ui` covers Stop in the run activity's details, its popover and its sheet.

## Test devices

Check a UI change at the sizes of the devices Deck Lab is actually used on. Sizes are CSS pixels (portrait × landscape for touch devices). "Browser" is the page's viewport with the browser's bars showing, which is what the layout really gets; for the iOS devices it's approximate, since Safari's bars grow and shrink.

| Device | Screen | Browser viewport | DPR | Input | Breakpoints it lands in |
|---|---|---|---|---|---|
| iPhone 15 Pro (Safari) | 393 × 852 | about 393 × 700, 852 × 330 | 3 | touch | under 600 (phone); under 430 (tight deck tabs) |
| iPhone 17 Pro (Safari) | 402 × 874 | about 402 × 720, 874 × 340 | 3 | touch | under 600; under 430 |
| iPad Air 11-inch M2 (Safari) | 820 × 1180 | 820 × 1106, 1180 × 746 | 2 | touch | 600-999 portrait (folded editor panel); 1000+ landscape with `pointer: coarse` |
| MacBook Air 13-inch M5, default scaling | 1470 × 956 | about 1470 × 830 | 2 | trackpad | 1400-1599 with a short window |
| MacBook Air 13-inch M5, More Space | 1710 × 1112 | about 1710 × 986 | 2 | trackpad | 1600+ |
| QHD monitor at 100%, Chrome maximised (Windows) | 2560 × 1440 | 2560 × 1305 | 1 | mouse | 2200+ |

Emulate them in Chrome over CDP (`Emulation.setDeviceMetricsOverride` with the width, height, DPR and `mobile: true` for the touch devices, plus `Emulation.setTouchEmulationEnabled`): headless Chrome on Windows can't make a window under 500 px wide. Emulation isn't Safari, so an iOS-only quirk still needs a look on the real device.

Rules added for these devices (the device pass of 2026-10-13), besides those above under the viewer, the editor and the offsets:

- **iPad landscape and wider (1000px+):** a deck's Stats and Practice panels stack (deck.js `stackPanels`: each spans small 8px rows to its own height, with dense flow), so a short panel doesn't leave a hole beside a tall one. The editor's side panel raises itself and scrolls its search box to its top while searching on a touch or short screen, takes its height from `--vvh` (the visual viewport, which shrinks for the iPad's keyboard where `100dvh` doesn't), hides its tip and filters while the keyboard is up, and wraps result names to two lines. Sleeves & boxes' edit sheet focuses its heading, not Name, on a coarse pointer, so the keyboard doesn't cover the picture.
- **MacBook (1400-1599):** the card peek is on from 1400px with a fine pointer (`--peek-w` 280px there, 240px in the editor), and Matchups has its side list (a 300-360px column) and pick buttons; the matrix's frame is capped at the screen's height with its column names sticky. The mana curve is capped at 900px from 1000px.
- **1600px+:** search boxes and form controls keep a reading width (Tokens' search 720px, Collection's 760px, the Game log's quick record 1100px, the Wishlist search 760px), and a button stays next to what it acts on.
- **QHD (2200px+):** the deck Overview is two columns (key cards and the rest on the left, How to play on the right at its reading width, the verdict strip across both); the verdict strip's tiles are at most 280px each at any width from 600px; Build decks fits four decks across with smaller tiles; the Collection list is capped at 1400px.
- **Every width:** History's card strips are one row (as many pictures as fit, then the +N tile). A grid whose column holds a picture strip (Shopping's deliveries) needs `minmax(0, 1fr)` columns and `min-width: 0`, or the strip's min-content widens the card.

Receive delivery inspection panels (`rcptSheetPicture`) are separate from the shared full-screen viewer: on a phone the picture is up to 320px wide, inside a full-width swipe surface. Previous/Next, a count and a swipe/enlarge hint accompany multi-card lists. Vertical gestures scroll; form controls keep their own input behaviour. Tapping the image opens the shared viewer.

## Keyboard ownership

The two menu implementations share `keyboardEditing`, `keyboardDialog`,
`keyboardShown` and `keyboardMenuOpen` in core.js. Popovers include native-control
avatar menus; body-mounted overflow menus retain their anchor and join ordinary
popover/route cleanup. Detached/background anchors do not open, menu types are
exclusive, held activation does not reopen a returned anchor, and native Tab is
not prevented. Core menus use Up/Down; overflow menus also use Home/End.
Page handlers check current view/focus, modifiers, composition and consumed
events before acting. Navigation may repeat; activation does not. Collection
sort/pager redraws restore only their fresh owned control. Dialog focus order,
not reusable-viewer DOM order, owns fallback navigation. No new binding belongs
to this reliability slice; contextual help and fast routes follow separately.

Editor keyboard actions use the view-only `ed.dom.keyboardOwner` and
`editorKeyboardCurrent()` before Save/Undo. `editorKeyIgnored()` and per-input
`editorComposition()` retain event/IME ownership and exact Enter variants.
`editorUndoFocus()`/`restoreEditorUndoFocus()` retain semantic row occurrence or
stable bar-part addresses, with visible existing-control fallbacks and no stale
focus reclamation. Main quantity callbacks require current mounted ownership,
exact line/input, enabled control and no asking/leaving context. They deliberately
retain typing during the pre-save check; post-request input retention remains
a separate Save-state limit in HISTORY. No payload or save-path change is part
of this reliability slice.

`keyboard-help.js` owns current page command descriptors, `aria-keyshortcuts`
and non-destructive hints. Registration requires the current mounted root and
profile; stale routes, unavailable controls and busy actions lose active hints.
Avatar help is available to every profile, uses the shared sheet and returns
focus only to its still-visible owned anchor. Help lists commands for after
closing the sheet. Core menu Up/Down and overflow Home/End remain distinct.
The browser-local per-profile character preference defaults on; storage failure
keeps a session fallback with a notice. Turning it off leaves native controls,
navigation and Ctrl/Cmd editing intact. Save entry/finally refresh metadata only;
pre-save typing and the remaining post-request input limitation are unchanged.

Current-page character routes use explicit descriptors: F focuses existing
Editor/Collection search, M opens the exact eligible Editor row's retained More,
and semantic ? opens help. Editor / stays compatible; global search is separate.
Dispatch counts eligible owners before help de-duplication, preserves native
editing/modifiers/IME/repeat and yields to overlays and busy operations. Frame
rebinding is explicit at the legitimate new-deck space action, not arbitrary
model changes. Modal Quick fields do not advertise the inactive F route.

The full Editor's labelled `.edit-forge` section retains its one original
`vtTestRow` beside, not inside, replaceable `.edit-stats`. `drawBar` synchronizes
eligibility and panel visibility through the same row; the reason is visible.
The original secondary button, native disabled state and description remain.
Quick scope and all Forge request/test/Save behavior are unchanged. Result
figures, unsaved evidence and after-save testing are separate work.

`editor-search-dock.js` projects the retained Add root as a labelled nonmodal
region/tabpanel in casual density. It measures the existing bar and viewport,
reserves document clearance, and scrolls only the same current owned control.
The original heading and query/results survive reopening and density changes;
generation/query/route/profile guards cancel stale frames and pending actions.
Escape follows search's first-clear handling, then owned dismissal. Back/Paste
and saved-editor takeover use exact transient tokens/positions; unrelated live
overlays retain ownership. The ordinary Save path is unchanged. Current F/help
registration follows lazy Quick mount; nontext Dock Undo resolves a fresh visible
launcher/Cards fallback, while input Undo remains native. Target sizing reads
the shared --tap/--btn-h and panel/font rules; keyboard-up tab policy is unchanged.
