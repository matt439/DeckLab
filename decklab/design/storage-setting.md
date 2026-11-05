# A space's storage as a setting: inventory and proposal (E8-S25)

Written 2026-11-05 against `09ec735`, as E8-S25's first slice. It changes no code. Part 1 lists every place that assumes the household's storage; part 2 proposes the setting's shape; part 3 is the build order; part 4 is the questions for Matt. Nothing here is decided until Matt answers part 4.

## 0. What "storage" means today

Home's cards that aren't in a built deck or a product kept intact are kept unsleeved in one 4-row storage box that holds about 2,400 cards (AGENTS.md, "Sleeves and storage"). Inside the box, cards go creatures, then spells, then lands, each by colour (white, blue, black, red, green, multicolour, then colourless and artifacts), with token cards apart. A collection row may also record a location (E8-S22), a free line such as `Row 2, B` or `Binder`.

Deck Lab uses the word "storage" in two senses:
- **Loose cards in general:** "the copies not held by a deck". The In storage only filter, a deck taken apart ("its cards go back into storage unsleeved"), Break up into storage and the Put back step all mean this. That sense is true of any space and needs no setting, only the word.
- **The household's own box:** its four rows, its 2,400 places, its colour-and-type order, "the storage box". That sense is what E8-S25 makes a setting. Part 1 lists only the places that use it, and then (1.7) the generic ones that only need a check of their words.

## 1. The inventory

Line numbers are at `09ec735`.

### 1.1 The box's count on the Card list (E8-S19)

| Where | What it assumes | What a setting changes |
|---|---|---|
| `decklab/lib/api/collection_locations.py:13-15` (module docstring) | "the 4-row storage box's fill"; capacity "about 2,400 unsleeved cards" | Describe the count as the default container's fill |
| `collection_locations.py:28` `CAPACITY = 2400` | The household's box size as the built-in default | Becomes home's built-in default container's capacity only; other spaces have no default capacity |
| `collection_locations.py:29` `BOX_ROW = re.compile(r"row\s*\d", re.IGNORECASE)` | A location starting "Row N" (any N) is in the box | A location belongs to a container when it starts with one of its section names, or its name |
| `collection_locations.py:116-121` `capacity()` | Capacity comes from `config.json`'s `storage_box_capacity`, one number for the whole install | Read the space's saved setting; `storage_box_capacity` only seeds home's default (see question Q6) |
| `collection_locations.py:124-127` `in_box()` | No location means "in the box"; a "Row N" location means in the box; anything else is "elsewhere" | No location means the space's default container (if it has one); a location is matched to a container by its sections |
| `collection_locations.py:130-150` `storage_box()` | `space != spaces.HOME` gets None: only home has a box. One box, one count | Any space with a saved setting gets one count per container that has a capacity; a space with none still gets None |
| `decklab/lib/api/collection_edit.py:355-363` `_extras` | One `storage_box` answer beside the rows | Becomes a list (or a keyed object) of containers' counts; keep `storage_box` for home's default container until the page has moved (an older page reads it) |
| `decklab/web/storage-locations.js:89-102` `drawColStorageBox` | "Storage box: about N of 2,400 cards"; "The storage box is over capacity"; "Cards kept outside the box's rows (… such as in a binder) aren't counted" | One line per container, by its name ("Binder: about 310 of 360 cards"); "outside the box's rows" becomes "not in a container with a capacity" |
| `decklab/web/collection-rows.js:53` `cv.boxNote` (one `<p>`) | One box line | A short list when there are several containers |
| `decklab/web/collection.js:256` comment of `colInStorage` | "may be in the storage box" | Comment only: "loose (not in a deck)" |

Tests that pin it: `decklab/tests/test_collection_locations.py:119-136` (`StorageBoxTests`: capacity 2400, `storage_box_capacity`, `user2` gets None) and `:146-150`; `test_collection_locations_ui.py:18,41-47` (`capacity: 2400`, the over-capacity words); `test_collection_locations_bulk.py:131`.

### 1.2 The pending-delivery storage scenario (E8-S19)

| Where | What it assumes | What a setting changes |
|---|---|---|
| `decklab/lib/api/collection_forecast.py:1-6` and `:396` `build()` | Home only (`space != spaces.HOME` returns None); one box | Stays home-record-readers only (orders are home's), but routes each pending copy to a container instead of "box" or "elsewhere" |
| `collection_forecast.py:162` | `places.in_box(location)` decides "box" or "elsewhere" | The same container match as 1.1; the dispositions gain a container id |
| `collection_forecast.py:48-52` `_base(box)` | One `current_cards` and one `capacity` | Per container, or only for the default container in a first slice |
| `decklab/web/storage-locations.js:107-128` (`COL_FORECAST_PROBLEMS`) and `:248-290` (`drawColStorageForecast`) | "box routing", "box candidates", "filed in the box", "off-box location", "an unrecorded location means the box" | Name the default container; "off-box" becomes "in another place" |
| `storage-locations.js:163-165` | The scenario's `current_cards` and `capacity` must equal the one box count | Checked against the matching container's count |

Tests that pin it: `decklab/tests/test_collection_forecast.py` (`test_extras_preserves_existing_storage_box_shape_and_adds_separate_sibling`, and the "box"/"elsewhere" dispositions), `test_collection_forecast_ui.py:48,153-178,345-348`.

### 1.3 Location suggestions (E8-S22, E8-S23)

| Where | What it assumes | What a setting changes |
|---|---|---|
| `decklab/web/storage-locations.js:8` `STORAGE_LOCATION_ROWS = ["Row 1", "Row 2", "Row 3", "Row 4"]` | Every space's card sheet suggests the household's four rows first, a member's included | Suggest the space's containers' sections (or a container's name when it has none); a space with no setting suggests only the locations it has used |
| `storage-locations.js:45-48` `colLocationChoices` | As above (its comment: "the four rows of the storage box") | As above |
| `storage-locations.js:57` placeholder "Such as Row 2, B or Binder" | The household's row names as the example | Use the space's first section, or a neutral example |
| `storage-locations.js:429` (the bulk Set storage location sheet) | Same `colLocationChoices` | Follows `colLocationChoices` |
| `decklab/README.md:393` | "suggesting Row 1 to Row 4" | Say "suggesting the space's storage sections" |

Tests that pin it: `decklab/tests/test_collection_locations_ui.py:56` (`['Row 1', 'Row 2', 'Row 3', 'Row 4', 'Row 2, B']`). The many `Row 1`/`Row 4` values in `test_collection_locations.py`, `test_collection_locations_bulk.py`, `test_collection_locations_bulk_ui.py` and `test_collection_locations_pg.py` are only sample location text and don't need to change.

### 1.4 Build decks' Storage order (built 2026-10-14)

Build decks is home's only, so this is the household's order today, not a member-facing wrong. It becomes a setting so that home can change its order and a self-hoster's home isn't given the household's.

| Where | What it assumes | What a setting changes |
|---|---|---|
| `decklab/web/assembly.js:331-332` `packOrderControls` | The second order is called "Storage order" | Name it after the default container's rule, or keep "Storage order" and follow the setting |
| `assembly.js:347-371` `packStorageGroup` | The fixed order: creatures by colour (WUBRG, multicolour, colourless), artifact creatures; spells the same, artifacts; lands by the colour of mana they make; then "Other cards". Ranks 0-23 are hard-coded | One of a few named ordering rules (part 2.3); `colour-type` is today's function unchanged |
| `assembly.js:373-394` `packCardGroups` | Groups by that function, then by mana value, then name | Groups by the chosen rule; later, by container first (from the cards' recorded locations) |
| `assembly.js:496-502` | In Storage order, basic lands join the pull step and tokens come after Put back | Only for rules that file basics with the other lands; ask (Q4) |
| `decklab/web/assembly.css:18-19` `.pack-storage-group` | Nothing about the box; style only | None |
| `decklab/README.md:330` | Describes the order in words | Say it follows the space's storage setting, with today's order as home's default |
| `decklab/HISTORY.md:6809` ("Build decks: storage order", 2026-10-14) | "Storage order follows four rows" | History: leave it |

Tests that pin it: `decklab/tests/test_assembly_sort_ui.py` (`test_storage_dividers_use_front_types_and_actual_colours` pins the group labels such as "Creatures · White" and "Lands · Multicolour"), and the "Storage order" button text in `test_assembly_bulk_ui.py:140`, `test_assembly_completion_ui.py:233` and `test_assembly_progress_ui.py:71`.

### 1.5 Where these go (E7-S15) and Receive delivery

| Where | What it assumes | What a setting changes |
|---|---|---|
| `decklab/web/receipt-workflow.js:478` | "Broken up: its cards go into the storage box." | Name the default container, or "with your loose cards" |
| `receipt-workflow.js:502-504` | Heading "To storage"; "No deck is waiting for these: they go unsleeved into the storage box." | Heading "To <default container>"; later, each card's section by the rule ("Row 1 · Creatures") |
| `receipt-workflow.js:462` (comment) | "the rest to storage; token cards to the token box" | Comment only |
| `decklab/web/receipts.js:1075` | Product choice card: "Its cards go into the storage box, free for any deck." | Same as `:478` |
| `decklab/web/receipt-layout.js:183,207,212` | `kind: "storage"`; "break up into storage"; "storage; no deck is waiting" | Generic "storage" words; fine as they are. A later slice adds the container |
| `decklab/lib/api/collection_filing.py:211` | Every copy no deck waits for is `{"kind": "storage"}` | Add the container (and section) the setting files it in; keep `kind: "storage"` |
| `decklab/web/collection-filing.js:92-94` | "To storage"; "keep them with your unsleeved cards" | Generic, works in any space now. With a setting: the container's name |
| `decklab/db/inv_collection.py:362` (`collection merge`'s guide) | "  Storage:" | "  Storage (<container>):" once there is one |

Receive delivery is home's (orders are home's), so its "storage box" words are true today; they are listed because a self-hoster's home has no such box. Tests that pin it: `decklab/tests/test_receipt_destinations_ui.py`, `test_receipts_ui.py`, `test_collection_filing_ui.py`, `test_collection_add_filing_ui.py`, `test_precon_filing_ui.py` (the "To storage" and "storage box" words), and `test_collection_merge_filing_cli.py` for the CLI's `Storage:` line.

### 1.6 The docs

| Where | What it says | Change |
|---|---|---|
| `AGENTS.md:28` | "All other cards are stored unsleeved in a 4-row storage box that holds about 2,400 unsleeved cards." | Keep as the household's fact, and add that Deck Lab reads it from home's storage setting |
| `AGENTS.md:146` | The pending scenario "leaves the current `storage_box` unchanged" | Name the containers' counts when they're built |
| `decklab/README.md:393,395` | Row 1 to Row 4 suggestions; "the 4-row storage box", "about 1,234 of 2,400 cards", `storage_box_capacity` | Describe the setting, with home's default |
| `decklab/config.example.json` | Has no `storage_box_capacity` | None (see Q6) |
| `decklab/design/stories.md`, E8-S19 (`:3299`) | "the 4-row box (about 2,400 cards)" | The story is the household's; leave it, and point to E8-S25 |
| `decklab/design/journeys.md:11,178` | "the storage box" as a physical touchpoint | Leave: it describes the household |
| `decklab/design/visual-design.md:337` | "hard to read at the storage box" | Leave |

### 1.7 Generic "storage" that needs no setting

These mean "loose, not in a deck" and are true in any space. Check their words when the setting ships, but they don't read it:
- `decklab/web/collection-rows.js:115-120,192-196,306-310,503,525-531` and `collection.js:250-259`: In storage only, "In storage" on each row.
- `decklab/web/assembly.js:450-452,501`: Pull from storage, Put back ("put them back in storage, unsleeved"); `assembly-sheets.js:101`.
- `decklab/web/editor.js:321,395`, `editor-details.js:78-86`, `decklab/lib/api/drafts.py:379-413`, `decklab/lib/decks/deckfile.py:27`, `decklab/lib/inventory/ops_decks.py:150`: a deck taken apart goes back into storage unsleeved.
- `decklab/web/product-storage.js` and `decklab/lib/api/products.py`: Product storage, Break up into storage.
- `decklab/lib/inventory/rules.py:286`, `files.py:578`, `pool.py:330`: a broken-up product's cards are stored unsleeved.
- `decklab/lib/api/assembly*.py` (`from_storage`, `step["storage"]`, "only printing in storage"): the plan's copies from loose cards.

One small exception: "unsleeved" assumes loose cards are kept unsleeved. A binder or a sleeved shelf breaks that (Q5).

## 2. The proposal

### 2.1 The data

One record per space, saved whole with a revision, as Commander-night notes and shop postage are:

```
{"v": 1,
 "default": "box",
 "containers": [
   {"id": "box", "name": "Storage box", "kind": "box", "capacity": 2400,
    "sections": ["Row 1", "Row 2", "Row 3", "Row 4"], "order": "colour-type"},
   {"id": "binder", "name": "Binder", "kind": "binder", "capacity": 360,
    "sections": [], "order": "none"}
 ]}
```

- **`containers`**: 0 to 20 of them, in the order the space lists them.
  - `id`: a slug made once from the name (as accessory ids are), so a rename keeps it.
  - `name`: 1-40 characters, one line, unique in the space ignoring case. It's what the pages say ("Binder: about 310 of 360 cards").
  - `kind`: `box`, `binder`, `shelf` or `other`. It only changes words and an icon; Deck Lab doesn't treat kinds differently.
  - `capacity`: how many cards it holds, 1-100,000, or blank when not known (then it gets no count line, only a card total).
  - `sections`: 0 to 50 short names (each 1-40 characters), such as `Row 1` or `Page 1-20`. They're the location suggestions, and a recorded location starting with one belongs to this container.
  - `order`: how cards are ordered inside, one of a few named rules (2.3).
- **`default`**: the container loose cards go to when no location is recorded, or blank. Today that's the box: no location counts as "in the box".
- A location matches a container when it starts with one of its sections, or with its name, ignoring case and followed by the end, a space or a comma. When two match, the longer match wins. A location matching nothing is "somewhere else", as `Binder` is today.

Today's `BOX_ROW` (`row\s*\d`) also counts `Row 9` and `row3` as in the box. Under the proposal home's default sections are `Row 1` to `Row 4`, so `Row 5` would stop counting. Home's live locations should be listed before the switch (`python -m decklab.db collection locations`), and any that would move named to Matt (Q3).

### 2.2 Where it's kept

**A database table, `public.space_storage`, in a new migration `0023_space_storage.sql`:** `space_id` (primary key, referencing `space`), `revision`, `content jsonb` with a check on its shape, and the audit triggers, as `0021_shop_postage.sql` does. A save sends `expect` (the revision it read), and an older revision is refused as a conflict.

Why not the other places:
- **`profile_setting`** is a profile's, private to that profile with no sharing. Home's storage is Matt's and User1's together, and a profile's settings are read only by that profile (E10-S38).
- **`config.json`** (where `storage_box_capacity` lives now) is on the PC only: a member can't change it, it isn't backed up with the database, and it isn't per space.

A new per-space table also has to join the per-space lists:
- the export's table list and its set of tables that may not be migrated yet (`decklab/db/export.py:57,95`, where `shop_postage` is; not `LATER_INVENTORY_TABLES`, which holds inventory tables such as `dice_counter`);
- `db check`'s references (`check.py:444`), member admission (`profile_admission.py:110`), a member's departure (`space_apply.py:26-32`) and the space export (`space_export.py:120`);
- the Activity page: a row rule of its own in `decklab/lib/api/activity.py` (and its line in the module's docstring table), and its group in `activity_headlines.py`'s table map. Without one, a table falls through to the "anything else: admins" rule (`activity.py:382-390`, `UNKNOWN_CHANGED`), so a member's own save would show to Matt as "changed", with a web change's message, and never to the member (see 2.4);
- `STATE_TABLES` and `UNDO_MIGRATION` in `decklab/tests/db_support.py`. While the migration isn't applied, every space reads as "no setting" (home keeps its built-in default), and a save is refused with the words E8-S22 uses for locations ("Deck Lab's database needs updating on the PC").

### 2.3 Ordering rules

A short fixed list, each a function on the page, never a free-form rule:
- `colour-type` (home's default): today's `packStorageGroup`, unchanged, with its groups labelled as now.
- `type-colour`: lands, creatures and spells first, colour inside each (if Matt wants it; Q4).
- `colour`: by colour only, then mana value.
- `set`: by set, then collector number (how a binder by set is kept).
- `name`: by name.
- `none`: no order; Build decks' order offers only Name.

A rule may say which section each group goes in (`colour-type` with four rows: creatures in Row 1, spells in Row 2, lands in Row 3…), so Where these go can say "Row 1 · Creatures · White". That needs Matt to say how the rows are really used (Q2), and is a later slice.

### 2.4 Who reads and changes it

- **Changes:** the space's own people, the same as its collection (home: Matt and User1; a member: only that member). No admin override (E10-S29). A new rule `storage.edit` in `decklab/lib/permissions.py`, equal to the collection's edit rule, checked on the server's write as every write is.
- **Reads:** whoever may see that space's inventory (`permissions.sees_inventory`). When a space makes its collection Public, its storage setting follows it, read-only (Q7).
- **Activity:** a save's row shows only to the space's own people (`scope_spaces`, as `collection_card`'s rows; no admin override), with a fixed summary, "Storage setup updated", never container names or sections; its message and reason follow the module's usual rules within that space. A test checks that an admin doesn't see a member space's storage row or its message.
- **Command line:** `python -m decklab.db storage show [--space S] [--json]` and `storage set FILE [--space S] --expect N -m "..."` (a JSON file in the scratchpad, as `watchlist apply` takes a CSV), with `--actor` and `--dry-run` as the other writes. Every save is one audited change set. Member upkeep through Claude follows the existing relay rule: report only that it's done.

### 2.5 Defaults

- **Home with no saved record:** a built-in default that is today's behaviour: one container `Storage box`, kind box, sections `Row 1` to `Row 4`, capacity `storage_box_capacity` from `config.json` or 2,400, order `colour-type`, and it's the default. Nothing on the page changes until someone saves.
- **Any other space with no record** (a member's space): no containers. No count line, no Row suggestions (only locations already used), and the words "storage" and "loose cards" only, never "the storage box". Where these go keeps "To storage".
- **A saved record always wins**, home's included. Saving an empty list of containers is allowed and means "no particular storage": it's how a self-hosted install's home opts out of the built-in box (Q8).

This is the one default rule: home's built-in box applies whenever home has no saved record, whatever `config.json` holds and whether or not any location is recorded. Slices 2 and 3 build it that way; Q8 asks only whether a fresh install should be told how to opt out.

### 2.6 Where it's edited

**On the Collection page, More, Storage setup…**, a sheet for the space's own people. Not Settings: Settings is admins only, and a member's own storage is theirs, not an admin's.

The sheet:
- One row per container: name, kind, capacity, its sections (one per line, or a count such as "4 rows" that makes `Row 1` to `Row 4`), and its order. Add, remove, move up and down.
- "Cards with no location go to": a choice of the containers, or none.
- Before Save, a preview of what changes: the counts per container now, how many recorded locations would move between containers (by count, never naming the rows), and the new location suggestions. Save sends the revision it read.
- The Card list's count line links to it ("Change…"), and so does an empty space's start.

### 2.7 What follows the setting

| Feature | With a setting |
|---|---|
| Card list's count (1.1) | One line per container with a capacity, by name; "not in a container with a capacity" for the rest; basic lands still left out |
| Pending scenario (1.2) | Each pending copy routed to the container its printing's location matches, else the default; home's only, as now |
| Location suggestions (1.3) | The containers' sections and names, then the space's used locations |
| Build decks' order (1.4) | The default container's rule. Later: grouped by container first, from the copies' recorded locations |
| Where these go and Receive delivery (1.5) | "To <default container>", and later each card's section |

## 3. Build order

Each slice keeps every space's page as it is now unless the space saves a setting.

1. **This inventory and proposal** (2026-11-05). Matt answers part 4.
2. **The record and its reader.** Migration `0023_space_storage.sql`, the state-store read and write with a revision and the audit trail, the per-space table lists of 2.2 (export, check, admission, departure, space export, Activity's row rule and headline group with its privacy test, `STATE_TABLES`), `permissions.storage.edit`, `GET`/`PUT /api/storage?space=`, the `storage show|set` commands, home's built-in default (2.5's rule), and the fixture tests (the in-memory store) plus `UNDO_MIGRATION`. No page change. Applying the migration live is Matt's, separately.
3. **The count and the suggestions.** `collection_locations.py` reads the setting (containers, matching, default) instead of `BOX_ROW`, `CAPACITY` and `in_box`; the rows answers gain per-container counts beside `storage_box`; the Card list draws one line per container; the location suggestions come from the setting; the pending scenario routes by container. Home's default keeps every current test's numbers; a member's space loses the Row 1-4 suggestions (a fix, 1.3).
4. **Storage setup… on the Collection page.** The sheet, its preview, its conflict and permission refusals, and its UI tests.
5. **Build decks' order follows the rule.** `packStorageGroup` becomes the `colour-type` rule among the others; the toggle's label follows the setting.
6. **Words.** Receive delivery, Where these go and the CLI merge guide name the default container; README, AGENTS.md and the E8 stories updated.
7. **Later, if wanted:** sections from the rule (Where these go says "Row 1 · Creatures"), Build decks grouped by container from recorded locations, and a container's fill shown on Shopping before an order.

## 4. Questions for Matt

1. **One record per space, edited on the Collection page by that space's own people,** as in 2.2 and 2.6: is that right, or should home's be on Settings too?
2. **How are the four rows really used?** Does each row hold one group (creatures, spells, lands, tokens?), or do the groups run on from row to row? The answer decides whether a rule can name a card's section.
3. **Locations that stop matching.** Today any location starting "Row" and a digit counts as in the box. With sections `Row 1` to `Row 4`, a `Row 5` wouldn't. Is that right, or should home's sections be a pattern?
4. **Which ordering rules?** `colour-type` (today's), plus which of `type-colour`, `colour`, `set`, `name`, `none`? And in today's order, do basic lands stay in the pull step and tokens after Put back?
5. **Unsleeved.** Pages say loose cards are "unsleeved". Should a container say whether its cards are sleeved (a binder, a sleeved shelf), so Put back and Where these go stop saying "unsleeved" there?
6. **`storage_box_capacity` in `config.json`.** Keep it as the seed for home's built-in default until the first save, then ignore it (proposed), or retire it now?
7. **Public.** When a space makes its collection Public, should its storage setting be readable too (proposed), or always private?
8. **A self-hosted install's home.** Under 2.5 a new install's home starts with today's box, as the household's does, and opts out by saving an empty list of containers. Is that right, or should a new install start with no containers? Choosing no containers would need a signal telling the household's home apart, and neither candidate is reliable: `storage_box_capacity` is optional (2,400 when it's missing, and `config.example.json` doesn't have it), and a blank location already counts as in the box, so the household may have no `Row N` locations at all. The household would then lose its "Storage box: about N of 2,400" line, and `StorageBoxTests` would break. Proposed: keep 2.5's rule, and say in the README how to opt out.
9. **Containers as accessories?** A storage box is a physical thing like a deck box. Should a container be able to point to an accessory row (a `deck_box` with a capacity), or stay a separate list (proposed: separate, since accessories are home's only and a member's space has none)?
