# Private by default, public read-only

Design, 2026-10-13, updated 2026-10-18. This is part of the design set in `decklab/design/`. It follows Matt's decision of 2026-10-13: "default is no visibility". Paths are relative to `decklab/` and the original audit line numbers are as of 2026-10-13. Status 2026-10-19: everything in this design is built (phases 1 to 4 before the invite, the switches, full Forge rules, public accessories, Activity, history masking and member departure after it, all on 2026-10-18) and live since 2026-10-19, when migrations 0012 (visibility) and 0013 (member departure) were applied and the server restarted on committed code. Nothing has been switched Public yet, and no member has left. Only per-deck public (E10-S41) waits until someone asks. Matt confirmed on 2026-10-18 that User5's invite has been sent. Section 5 records the phases; [stories.md](stories.md) owns each story's current status and acceptance criteria. Matt's settled decisions are in section 4.

Update 2026-10-18: [member-template.md](member-template.md) (MT below) makes this the setup of every member, starting with User5 (`user5`, the first real member), and Matt accepted its decisions A to K as recommended. "Visible to the family" is now **public**: read-only to every signed-in profile, future members included. There is no family flag or family audience. Public still means behind Cloudflare Access, never the open internet: E10's rule of no public pages, share links or sign-up holds. The new build order is in section 5.

---

## 1. The rule and the switches

### The rule

Nobody sees another space's data unless that space has made it public.

- **Spaces.** Home is one space, shared by Matt and User1. Each member (User5, User2, User3 and User4) has their own, on the same template (MT §1).
- **Accessory owners.** Accessories belong to `matt`, `user1` or `shared`, and each owner's kit is a separate thing that can be made public.
- **What "public" means.** A public thing is seen by every signed-in profile, future members included, and it is **read-only** to them. Only its owner changes it (at home, Matt and User1, exactly as today). Signed in means through Cloudflare Access or the home chooser; nothing is public to the open internet.
- **The admin role doesn't open anything.**
  - Matt reads User2's collection only if User2 made it public.
  - On the page, Matt writes only in his own space.
  - Admin stays a system role only: the simulations setting, Settings, Visits, home's own orders, products and receipts, and stopping any run (as an anonymous item; see section 3).
- **The command line is exempt.** It is not a request, so it still reads and writes everything (`python -m decklab.db`, `sql`, `decklab.lib.*`). Claude manages the data through it. What Claude may pass on from a private space is decision 3.
- **Hidden looks the same as missing.** Any page answer about something hidden is exactly the answer a missing thing gets (for decks, 404 "No deck X"). Visibility is checked **before** any 409 or 403, so no answer can confirm that the thing exists or give its title.
- **Only scripts read everything.** "Naming nobody sees everything" now holds only for a script: a request on the home listener, from loopback, carrying `X-Deck-Lab-Script: 1`, or code running outside any request (job threads, tests). Everyone else who names nobody sees only what is public.
- **The chooser offers only home profiles.** The home network's "Who are you?" lists only home profiles. A home-network request naming a member's profile is refused. Members always come in through decklab.example.com and its login, which works from Matt's Wi-Fi too (decision 1). User5 uses only decklab.example.com.
  - Without this, anyone at home could pick "User2" or "User5" and the rule would protect nothing.
  - Inside home it stays honour-based, as today: Matt could pick User1. That shows only her own accessories, since home is one space.

### The switches

There is one switch per thing, never a per-person list.

| Owner | Switch (`thing`) | What it makes public (read-only) | Who may flip it |
|---|---|---|---|
| A space (`home`, `user5`, `user2`, `user3`, `user4`) | `collection` | The space's Collection and Tokens pages (not raw imports). On decks the viewer can also see: the owned, missing and on-the-way counts, card marks, token lines and the Play-now list's availability. The printing picker's counts when the viewer edits a draft of that space's deck. **For home it never includes** orders, products, the watchlist, receipts, Shopping, the Packing plan, pending token orders, order ids or product names in labels, or the pool's home-record warnings. Those stay with home's profiles; a non-home viewer sees "1 on the way" with no source. | Home: Matt or User1. A person: themselves. |
| A space | `decks` | Every deck in the space, **as its text is written**: list, header, prose (the Substitutes and Notes sections included), stats, history, practice hands, "Try a change" (a dry run), Forge results whose other side is also visible, and a place in other spaces' pickers and fields. For home it also includes product decks and Beginner Box pairings of **owned** products. Ordered and preordered products stay home-only. | As above |
| A space | `games` | The Game log's game records that have one of that space's decks in them. A side whose deck the viewer can't see is anonymised (section 2). Sideboard plans remain readable and writable only by their deck's space (MT decision G), even when games are public. | As above |
| An accessory owner (`matt`, `user1`, `shared`) | `accessories` | That owner's sleeves, deck boxes and playmats, and their pictures. A holder deck's title shows only if the viewer can also see that deck. | `matt`: Matt. `user1`: User1. `shared`: either home profile. |

**Per space, not per deck.** A per-deck switch would leak through every cross-reference inside a space, and each of these would need anonymising deck by deck:

- "2 in use in Gruul Ramp" labels
- Forge results keyed by list
- the field
- Packing plan transfers
- the Collection page's holders

Per space keeps each space all-or-nothing, so the field, the in-use labels and the results stay consistent with no special cases. Each space member has one deck, so for them per space is the same as per deck. Per-deck visibility can be a later `could`: E10-S41, Per-deck public (MT decision A, 2026-10-18).

**Collection and tokens are one switch.** The decision named them together, and tokens matter mainly as a deck's token lines.

**`games` stays a separate switch.** Matt named the Game log separately, and it costs one row on the switches page. Making the Game log follow `decks` instead was considered and rejected (section 7).

**The decks switch shows the text as written.** The switches page says so next to it: "Shows each deck's write-up as written, including notes about cards you own or ordered."

**Words.** `shared` already means "Matt's and User1's together", so the new state is called **"Public"**, its opposite is **"Private"**, and the internal name is `visibility`, never "share". Every page string, command message and audit message says Public and Private. Where the page explains it, it says "public (to everyone signed in)".

Update 2026-10-18: the 2026-10-13 word was "Visible to the family". MT decision B replaced it with Public, since "family" was wrong once members from outside the household joined.

### Storage: the next unused visibility migration

Use the next unused migration number when implementation starts: 0010 is deck aliases and 0011 is Commander-night notes, so neither is available for visibility. Visibility storage can be developed now; the old October 19 build date is superseded by the current order in section 5. A switch can be enabled only when its public-reader criteria are complete.

Built: the table shipped as migration `0012`, applied on 2026-10-19. It is empty, so everything is Private.

The migration follows `db/migrate.py`'s conventions: it runs as `decklab_owner` in one transaction, is never edited once applied, and writes no data.

```sql
create table visibility (
    owner text not null check (owner ~ '^[a-z0-9_-]{1,64}$'),   -- a space id, or an accessory owner
    thing text not null check (thing in ('collection', 'decks', 'games', 'accessories')),
    set_by text null,
    set_by_name text not null,
    since timestamptz not null default now(),
    primary key (owner, thing)
);
-- plus the audit_row trigger (audit.log_row('owner','thing')) and audit_no_truncate, as 0003 does
```

**A row means visible and no row means private,** so missing data fails closed. There are no foreign keys, for the reason 0003 gives at lines 6-9.

The code that has to follow:

- **State store.** `visibility()`, `visibility_cached()` and `visibility_set(owner, thing, on, actor, message)` in `lib/state/__init__.py`, `pg.py` (the `simulation_mode*` pattern at `pg.py:642-675`) and `memory.py`. Add a case to `tests/test_state_contract.py`.
- **Nightly jobs.**
  - `db/export.py`: add the table to `TABLES` and `UNTIL_MIGRATED`.
  - The restore check's content digests must cover the table.
  - `db/check.py`: flag a row whose owner is neither a space in config nor one of `matt`, `user1`, `shared` (accessory owners aren't spaces).
- **Profile sync.** `db/profiles_sync.py` deletes a removed space's rows inside its change set, so a later profile with the same id doesn't come back already visible.
- **Command line.** `python -m decklab.db visibility list` reports the switches; `visibility set OWNER THING on|off -m "..."` changes only home's switches, as actor `claude`, source `cli`. There is no command to flip a member's switch: the member does that on the page (MT decision D).
- **Reading.** Each request takes one snapshot of the switches next to `inventory.pinned()` (`lib/server_http.py:306-310`) and passes it into `permissions.py`'s pure functions as `vis=`.
  - If the database can't be read, the last-good cache (60 s) is used. With no cache, everything is private.
  - A flip updates this process's cache at once.
- **Rollback history.** Phase 0 fixed the missing `0008_visits.sql` entry on 2026-10-13. Phase 5b retired the rollback tooling on 2026-10-14, so the visibility migration needs no rollback registration or files-backend instructions.

### Audit trail

- Each flip is one change set. From the page the actor is the profile, with source `web` and `via` home or tunnel. From the command line the actor is `claude`, with source `cli`.
- The message is built from the row, for example "Make the home decks public" or "Make User1's sleeves, deck boxes and playmats private".
- `lib/api/activity.py` gets a row in its docstring table, a `FIELDS` entry `("owner", "thing", "set_by_name")`, and a `_row` branch with a summary.
- **Who sees a flip on Activity:** only the owner's space (home's profiles for any accessory owner). An admin doesn't see other spaces' flips. Everyone else learns that a thing is visible by seeing it.

### Default and rollout

**Build timing.** The table starts empty, so everything is private. Development no longer waits for October 19 or User5's invite, which Matt confirmed sent on 2026-10-18. Section 5 and MT §4 own the implementation order and each switch's reader prerequisites. The side-by-side check week's report remains separate dated work. Built and live since 2026-10-19 (migration `0012`), with the table still empty.

The original timing restriction protected the database gates and the `pre-db-decks` rollback. Phase 5b retired both on 2026-10-14. The gates' reader dump lives on in the tests (`tests/golden_dump.py`, normalised by `tests/golden_p4.py`), which still replay per-viewer views through `permissions.sees_inventory` against the committed goldens: a phase that changes what a viewer sees adds its difference to `golden_p4`'s normaliser, as phase 4's did.

**What changes on the first day:**

- **Space members** lose home's decks in the library, the pickers, `/api/play` and the matchups. Their field is empty (`NO_OPPONENTS`, `field_page.py:188`). Each has one built Commander deck and nothing else. Home has no built decks, so the field uses home's target lists.
- **Matt** loses User2's, User3's and User4's collections, tokens, decks, games, Activity rows and runs on the page. Visits shows their decks as "one of User2's decks".
- **User1** loses nothing. Matt's kit was already hidden from her.
- **Anyone on the home network** without a picked profile, and any LAN script without the script header, sees only what is public.

**Existing data.** No data migration. The 80 Forge results, 2 field notes and 0 variant tests stay as they are (section 3). There are 0 play records today. Accessory pictures change address (`?v=`) when the rule ships, so no browser keeps a cached copy.

**What the rollout note tells Matt** (HISTORY.md): "Everything is private. Make home's decks public (Who sees what, in the avatar menu) when you want everyone signed in to see them. Until then members can't field-test or record games against home decks."

Update 2026-10-18 (MT decision K): home's decks stay private on the space members' migration day. Matt makes them public later if he wants; that shows them to User5 too.

---

## 2. Surfaces: today and after

The tables in this section are the original audit's before/after design, not a current runtime inventory. MT §4 and stories.md record what shipped. Update 2026-10-18: MT §3 traced every route as User5 would reach it (46 checks). It found readers this section misses (opponents, cover, rename, retirement, rankings, restore, products, history subjects, goldfish, the profile roster, the simulations setting). They are listed there with their fixes and stories, and are not repeated here. One is accepted as a known risk: `GET /img/...` timing tells one bit per probe, whether a card image was fetched before.

Shorthand used in the tables:

- **V(deck):** the deck is in the viewer's own space, or its space's `decks` switch is on. Product and pairing decks count as home's, and ordered or preordered ones need H.
- **C(space):** it is the viewer's own space, or its `collection` switch is on.
- **H:** the viewer is a home profile.
- **S:** a script (the loopback home listener with `X-Deck-Lab-Script: 1`, or no request at all).
- **404:** the uniform "No deck X" or "No such …" answer.

### Rule functions and identity

| Where | Today | After |
|---|---|---|
| `permissions.py:156-162` `is_admin`, `:313` `reason()` | An admin passes every write in every space. | An admin passes only in his own space (with home's admin-only actions as today), plus `simulations.edit`, the system routes and stopping any run. S passes everything. |
| `permissions.py:210-219` `inventory_spaces`, `:196-207` `sees_inventory` | An admin gets `None` (every space). One rule also covers home's records. | Split in two: `sees_collection(space)` is C, and `sees_home_records()` is H only and never shareable. The old database gates were retired in phase 5b. |
| New: `permissions.deck_spaces_seen`, `sees_deck(space, deck)` | None (every deck is open) | `[own] + spaces with decks on`, with the product and pairing rule above. |
| `permissions.py:165-185` `accessory_owners`, `sees_accessories` | One set used for both reading and writing | Two sets: `accessory_owners` for writing (unchanged) and new `accessory_readers` (the write set plus owners with accessories on). `reason("accessories.edit")` uses the write set only. |
| `permissions.py:236-254` `sees_play_record` | An admin sees every record. | A record is visible if any of its decks is in the viewer's own space or in a space with `games` on. No admin branch. |
| `permissions.py:222-233` `activity_scope` | An admin gets `"all"`. | `{"space": own, "profile": id, "system": is_admin}`. `system` covers only the `space`, `profile` and `profile_email` rows, unknown tables and empty change sets. |
| `permissions.py:356-400` `summary()` | An admin gets every space in `spaces`, `deck_spaces` and `create`. | Own space only. New keys: `see_inventory`, `see_home_records`, `see_decks`, `see_games`, `accessory_readers`, and `visibility` (the switches the viewer may flip, with their values). |
| `access.py:414-432` `me()`, `server_http.py:399` | At home it answers for nobody (the admin's `may`). | Answers for `guard.viewer()`. `app.js` `chooseProfile` (114-125) fetches `/api/me` again, and fetches it again after a flip. `deriveMay` and `inventorySpacesAs` (`core.js:298-330`) become fallbacks for an older server, with no admin branches. `canEditSpace` and `canEditDeck` (`core.js:366-380`) lose their admin "yes". |
| Naming nobody: `permissions.py:160-162, 172-173, 215-216, 229-230, 247-248`; `history.py:73`; `commits.py:112`; `dbstatus.py:280-285`; `visits.py:109`; `simulations.py:89-94`; `editor.py:150`; `guard.accessory_owners` | Any home-network request without a viewer sees everything. | A new `guard.script()` decides this at each of these call sites. `guard.local()` (`guard.py:176-178`) keeps its meaning ("not through the tunnel"), which `viewer()`, `play_records.py:269` and `receipts.py:81` rely on. The PC's own browser before a pick isn't S: it sends no script header. `::1` counts as loopback. The PC calling its own LAN address doesn't. |
| Home chooser: `app.js:114, 192-200`, `server.py:278-291`, `access.py:370-375` | Lists every profile. The header may name anyone. | Lists home profiles only. On the home listener, a header naming a non-home profile gets 403 "Sign in through decklab.example.com". |
| Test servers (`tests/homenet_support.py:33`, `test_control.py:215`) | Bound to 127.0.0.1 | Tests send the script header to act as S, and leave it out to act as "a LAN device naming nobody". |

### Inventory

| Surface | Today | After |
|---|---|---|
| GET `/api/collection`, `/collection/rows`, `/tokens` (`collection.py:105`, `collection_edit.py:289`, `tokens.py:192`) | `sees_inventory`. An admin sees any space. | Needs C. Inside the answer: <br>- `holders` (`collection.py:143-144`) and the tokens' `uses` and `missing.decks` (`lib/tokens/__init__.py:334-420`) name a deck only if V, otherwise "one of User2's decks" or "one of the home decks". <br>- `incoming` per row (`collection.py:141`) becomes a bare count for non-H viewers. <br>- The Tokens page's `incoming` (`tokens.py:154-160`, order ids and rows) goes to H only. |
| Pool warnings (`pool.py:263-413, 475-479`), sent by `collection.py:174`, `deck_page.py:64, 73` and `saving.py:61-69, 470` | Whole list wherever the pool is read | Split into deck warnings (shown when V) and home-record warnings (order paths, product files, status lines), which go to H only. |
| Collection and import writes (`collection_edit.py:432, 659, 731`), `tokens.py:370` (`_tokens_view` 196-202 skips the read check), `precons.py:236` | An admin may write anywhere. Answers and 409s return the whole list. | Owner only (the admin narrowing above), so whole-list answers reach only people who may read them. Tests pin that a stale-sha write by an outsider gets 403 with only `{"error"}`. |
| GET `/api/precons/preview` (`precons.py:210-214`) | Needs read access. Returns `exists` (a deck id in that space) and the sha. | Needs `collection.edit` in the space. `_may_add` (164-167) follows. |
| Shopping, Receipts, Packing plan, `resolve_check` (`shopping.py:39, 243`, `receipts.py:106, 316, 422`, `assembly.py:103, 125`); home pool warnings (`saving.py:67, 470, 531`) | `sees_inventory(home)` | `sees_home_records()`. `core.js` `ROUTES` (409, 415) use `may.see_home_records`. |
| Printing picker and card search counts (`card_lookup.py:167-176`); `drafts._visible_counts` (`drafts.py:61-68`) | Home's pool if seen, else `seen[0]`. Neither knows the deck. | Both take the draft deck's `space` or `id`. They count that space's pool if V and C, otherwise the viewer's own space's pool, otherwise none. |
| GET `/api/deck/find` (`editor.py:592-609`) | `id` picks the space, and `pool.self_ids(deck_id)` is read for any id. | `id` counts only if V. The pool counts follow the rule above. |
| Deck counts (`deck_page.py:64, 71, 372, 393-415`; `editor.py:74, 145, 179, 492, 595`) | `sees_inventory` | V **and** C. `on_the_way` labels drop the order id and product name for non-H viewers. `in_use` labels (`pool.py:620-644`) name only decks of the deck's own space, which is visible as a whole, so they need no change. |
| `/api/tables/stale`, a save's `stale_tables` (`commits.py:251-256`) | `sees_inventory` per deck | V and C |
| 403 wording (`guard.py:374-388`, `app.js:470-491`) | "only {name} and an admin" | Person spaces: "{Name} hasn't made their collection public." Home records: "Only the home collection's people see this." No answer names a space the viewer can't see (MT decision C, E10-S38): for a space with nothing public, the answer is the one a missing space gets. |

### Decks

`lib/api/library.py` gets `require_visible(deck_id)`. `_find_summary` (`:58-69`) and `_deck_sections` (`:116-142`) answer 404 for a deck that isn't V. That covers:

- `deck_view`, `goldfish`, `cover_cards` and `edit_view`
- `_matchup_lists`, `play_records._snapshot` and `assembly._preview`
- the `from` source of "Save as a new deck" (`saving.create_deck`, `_new_source`, `editor.py:374`)

These readers bypass those two functions, so each gets an explicit check:

- `history._deck` (`history.py:44-58`)
- `commits._stored` (`commits.py:60-73`)
- `editor._snapshot_deck` (`editor.py:79-87`)
- `variant_page._tests_json` (`:208-227`)
- every `decks.list_decks()` consumer: `deck_page.py:60`, `play_records.py:363`, `forge_runs._TodaysLists` (`:243-246`), `field.py:133`, `assembly.py:107`, `shopping.py:92`, `receipts.py:243`, `visits.py:62-64, 136-141`
- `wishlists._source_deck` (`wishlists.py:73-92`)
- added 2026-10-18 from MT §3: `opponents.py`, `rename.py`, `retirement.py` (a retired deck's former space too), `rankings`, restore, product and pairing decks, `history.py`'s revision lookup, and goldfish

Every check is applied after reading, in `lib/api`. Nothing is gated in `lib/decks` or the pool, so background jobs and the command line keep reading everything. Viewer-independent caches (`visits._deck_ids`, `_TodaysLists`) are filtered on use and never stored filtered.

| Surface | Today | After |
|---|---|---|
| GET `/api/decks` (`deck_page.py:28-84`, `shelf_extras` `library.py:286-310`) | Every deck in every space | V decks only, `halves` and product decks included. The library and pickers show an empty state: "Home's decks aren't public yet." |
| GET `/api/deck`, `/deck/edit`, `/deck/cards`, `/goldfish`, `/deck/history`, `/deck/revision` | Open | 404 unless V. History goes with the deck. |
| POST `/api/deck/check` (`editor.py:389-514`) | Open, and compares against the stored prose and fields | 404 unless V (the `from` deck too). On a visible deck it stays open as a dry run. Its counts and availability follow V and C exactly as `deck_view` does. |
| POST `/api/deck/save` (`saving.py:221/225`), `/deck/cover` (`cover.py:93/95`) | `_stored` and the 409 `_conflict` run before the 403. | V first (uniform 404), then permission, then the 409. |
| POST `/api/tables/update` (`saving.py:503-510, 551`) | Conflicts and `skipped_not_allowed` name hidden decks' titles. | Hidden ids are dropped first and treated as not found, without being named. |
| POST `/api/accessories/assign` 409 (`accessories.py:243-268`) | Built inside `_apply`. Safe only while holders are home's. | Check holder V and kit write rights first. A test pins that a person-space holder id answers 404. Since 2026-10-18 it also needs `deck.edit` on the holder (or the product rights for a product), which it never checked (E10-S42, MT §3). |
| GET `/api/play` `lists` and `decks` (`play_records.py:363-372`) | Snapshots of every deck in every space. `_snapshot` errors (with titles) go into `warnings`. | Decks are filtered to V **before** snapshots are taken, so no warning names a hidden deck. |
| Wishlist source deck (`wishlists.py:73-92`) | `{id, title}` of any space's deck | Only if V. Otherwise the source shows as a plain path. |
| Activity deck rows (`activity.py:330-334`) | By the inventory list; an admin sees all | Own space only (visibility doesn't widen Activity; decision 4 of the draft, kept). |
| Visits (`visits.py:64-96, 125-131, 136-180`) | The admin sees every title. The beacon keeps any existing deck id. | The beacon keeps the deck id only if the requester sees the deck. The panel shows a non-V deck as "one of User2's decks", with no id. |
| Library and pickers (`library.js:188, 372`, `matchups-overview.js:345-384`, `variant.js:486`, `deck-tools.js:162`, `editor.js:353`), deep link `#/deck?id=` (`app.js:480`) | Show what they get | They follow `/api/decks`. A deep link to a hidden deck shows the existing 404 page. `matchups-detail.js:48` shows "not available" on a 404. |

### Forge

See section 3.

### Accessories

Reading uses `accessory_readers` and writing uses `accessory_owners`. Every write path passes the write set explicitly.

| Surface | Today | After |
|---|---|---|
| `accessories_view` (`api/accessories.py:93-140`) | One set | `items` come from the readers set, each with an `editable` flag. `sha256` comes from `view_sha256` over the **write** set (`accessories.py:311-320`); a token over the readers set would make every save conflict. `_owner_choices` and `exists` use the write set. `holders_options` and `products` go only to writers. |
| `used_by`, `kit().others`, `hidden_title` (`accessories.py:479-482, 718-719`, `ops_accessories.shown_users` 102-109) | Hidden by accessory owner | A title shows only if the viewer reads the owner **and** V(holder). Otherwise H sees "one of User1's decks" and everyone else sees "a home deck". |
| `image_file` (`api/accessories.py:520-550`) | Owner set; `private, max-age` one week (`server_http.py:28, 595`) | Readers set. Every accessory picture is sent `no-cache` with an ETag. `IMAGE_MAX_AGE` stays for `/img/` card images. Accessory picture addresses get a new `?v=` when this ships. |
| `staged_image` (`:553-575`) | `require_sees_accessories` | `accessories.edit` |
| `guard.require_kit_choice` (262-292), `sees_kit` (327-334) on writes, `saving.py:265, 311, 458`, `precons.py:292`, `editor.py:185`, `drafts.py:455`, every `ops_*` | One set | Write set |
| Read-side `sees_kit` and owner calls (`deck_page.py:65, 76, 268, 403`, `assembly.py:142, 172`, `receipts.py:297-304`, `history.py:214, 290`, `drafts.py:477-483`, `activity.py:336`, `editor.py:182`) | One set | Readers set |
| `web/accessories.js:228, 419-431`, `core.js:301, 320-322, 357-363`, `ROUTES:413` | Visible means editable. Only home sees the route. | Read-only per row from `editable`, rows grouped by owner. The route shows when `may.accessory_readers` isn't empty. |

### Game log, Activity, settings

| Surface | Today | After |
|---|---|---|
| `play_overview` records (`play_records.py:344-383`) | `sees_play_record`; an admin sees all | The new rule. In a visible record, a side that isn't V shows as "a home deck" or "one of User2's decks", with no list snapshot. A plan's `notes` follow the plan's own deck. |
| POST `/api/play/game` and `/sideboard` (`play_records.py:287-323`) | `_read` and the sha 409 come before `guard.require` (`:299-306`). `_selection(previous)` copies an old snapshot back (`:149-157`). The answer returns the whole `record` (`:309, 324`). | Permission first, then the 409. The opponent must be V (404 otherwise). The returned record is anonymised exactly like the overview. Since 2026-10-18 (MT decision G): each side's space edits only its own side (its deck, its mulligans); the result and notes stay with the space that recorded the game; a sideboard plan belongs only to its deck's space. |
| Audit messages "Save game A vs B" (`play_records.py:258-263`), `_play_summary` (`activity.py:426-438`) | Name both titles | New messages carry no titles. On play-record change sets, existing messages show only to a viewer who sees every deck in the record. The summary names only V sides. |
| Activity scope (`activity.py:144-178`, `rules.py:296-369`, `pg.py:211-266`, `memory.py:311`) | One `spaces` list; an admin gets `"all"` | The same single list, fed `[own space]`, plus `system` for an admin. No per-table SQL rewrite: home's records live in space `home`, which only H has as its own. |
| `as_written` (`activity.py:251`) | An admin sees every CLI message and reason. | Shown only to a viewer who sees every row of the change set, the same as the wishlist rule at 252-255. That also covers change sets of `deck.save`, `kit.set` or `tables` that span spaces. |
| Visibility rows | (new) | Owner's space only (section 1) |
| GET `/api/profiles/<id>/settings` (`settings.py:90-95`), `field_page.py:74-78` `&profile=`, `forge_runs.py:732` `&profile=` | No viewer check | Viewer must equal `id`. The Forge routes use `guard.viewer()`. |
| Wishlists | Owner only | No change, apart from the source-deck fix above. |
| Settings, simulations, version, `dbstatus` (`dbstatus.py:280`) | Admin by role | By role, using `guard.script()` instead of "naming nobody". GET `/api/simulations` gives a member only the mode and a reason without names; `by`, `since` and `workers` go to admins only (MT decision F, E10-S34). |
| GET `/api/profiles` (`settings.py:30-47`) | Every profile's id, name, role, space and `plays_as`, to anyone | Added 2026-10-18: the viewer's own profile, plus profiles whose space has something public; the admin's display name only for "ask Matt" wording (MT decision C, E10-S38). |

---

## 3. Forge

### V(side) and the content key

Results are keyed by list content (`engine.matchup_key`), not by deck.

A side is **visible** to a viewer when either:

- (a) one of its `seen_as` entries `(id, version)` names a deck the viewer may currently see, or
- (b) its `card_sha` equals the sha of a list the viewer may see today, worked out through `_TodaysLists`.

Case (b) covers a space member's precon whose list is identical to a home copy that was the one simulated.

The side is shown under the newest visible `seen_as` entry. In case (b) it is shown under the viewer's own deck. `seen_as` ids of hidden decks never reach the page.

A deleted deck's entries count only for its former space (`permissions._deck_space`, `:257`).

The rule lives **inside** `_TodaysLists` (`forge_runs.py:243-280`), which then reads only V decks per viewer. It replaces `views._page_side` (`forge/views.py:197-210`) and `_TodaysLists.side`, so "earlier" results and estimates can't read every space.

**A result is shown only when both sides are visible.** Showing one side anonymised isn't workable: `casts`, `cards` and `ai` (`views.py:271-339`) give away the hidden list.

### Reads, runs and stops

| Surface | Rule |
|---|---|
| GET `/api/matchups` (`forge_runs.py:657-685`) | Results filtered to both sides V. |
| GET `/api/matchup?key=` and `?a&b` (`:632, 688-743`) | 404 (`MATCHUP_NO_KEY` or "No deck X") unless both sides are V. `earlier` (`:489-502`) follows from that. |
| Deck page matchups (`_deck_matchups`, `:840-887`) | Results, earlier results and running jobs are filtered. `forge.list_cards(..., results=visible)` (`cardstats.py:441`) and `list_ai` pool only visible results. |
| Run pill and running lists (`_running_items` `:387-440`, `_job_for_key` `:508`, `_coord_progress` `:532`, `_pair_json` `:365`) | A job is dropped if any of its decks isn't V: matchup sides, field `detail["deck"]`, variant base or `against`. For an admin, such a job shows as "A run of one of User2's decks", with Stop and nothing else (PC load is a system matter). |
| Starter names (`by`, `stopped_by`, `cancelled_by`) in `views.py:318-333`, `_matchup_notice` `:443`, `field_page.py:103-108, 127-129`, field notes and variant tests | A starter from another space shows as "someone". |
| Start: `run_matchup` `:746-795`, `run_field` `field_page.py:165-195`, `run_variant` and `more_variant` `variant_page.py:300, 361` | `run.start` plus V on every named deck (through `_matchup_lists` and `_deck_sections`). **Variant tests also need the base deck in the viewer's own space** (decision 4), because a test stores the draft and the summary is readable by others. `more_variant` checks both decks again from the saved summary. |
| Stop: `:798-837`, `field_page.py:198-214`, `variant_page.py:346` | The viewer sees the run (otherwise 404) **and** started it, belongs to a space that owns one of its decks, or is an admin (an anonymous item is fine). `permissions.py:34` and ACTIONS "run" (`:111`) change to match. Until then (E10-S30's interim) only admins stopped runs, since before it anyone could stop any run and was saved as its stopper (MT §3). Built 2026-10-18 with E10-S31. |
| GET `/api/variant?test=`, `/api/variants?id=`, `/api/variant/estimate` (`variant_page.py:116-255`) | 404 unless V(base) and, for a deck opponent, V(against). The summary's opponent rows are filtered by V. |
| Matrix and pair picker (`matchups-overview.js:357-384`, `variant.js:486-490`) | Offer V decks only (from `/api/decks`). A cell is drawn only from visible results. |

### The field

The field of deck D in format F depends on D's space:

- **D is a home deck:** today's field, unchanged (`field.py:120-180`). That is home's decks (Built version, else target), owned, preordered or ordered products kept intact, then `simulation.json`'s `add` and `remove`. Person decks are never added automatically.
- **D is a person's deck:** F's decks in D's space, plus F's decks in every **other** space whose `decks` is on (home included), with the same Built-version, product and pairing rules, minus D.
- **`simulation.json` `field.add`:** may name only decks in D's space or in a space with decks visible. Other names are skipped, with a note in the view.

Code changes:

- `_field`, `field_lists`, `field_notes`, `opponents`, `plan`, `run_field`, `view` and `_bt_data` (`field.py:120-192, 211, 300, 336, 668, 757, 838`) change from `(fmt)` to `(space, fmt)`.
- Callers pass the space through: `field_page._answer` (`field_page.py:137-147`) and `variants._opponent_entries` (`variants.py:327`). Anything cached by format is keyed by space too.

**The view is always filtered for the viewer.** Opponent rows, `field_lists`, `_field`'s notes (which name home deck titles and products) and the rating keep only members the viewer can see.

- The rating fits only over results whose both sides are visible field members.
- Notes about products go to H only.

One rule covers three cases:

- a space member looking at a visible home deck whose field holds an ordered product;
- a stored field note written before a space went private;
- the rating leaking private matchups.

Nothing is cached filtered. A space member with nothing visible gets `NO_OPPONENTS`, whose wording already works.

### Keys and existing data

| Data | Change |
|---|---|
| Matchup results (`results/<key>.json`, 80 files) | No re-key and no migration. The content key is the right identity, and privacy is applied when a result is shown. All 80 are home-only today. |
| Field job key and note | Key `field:<space>:<card_sha>:<fmt>` (`field_page.py:54-56`). Note `results/field/<card_sha>-<fmt>-<space>.json` (`field.py:336`). A note without the suffix reads as home's, so the 2 existing notes still load and nothing is renamed. |
| Variant `test_id` (`variants.py:224-235`) | A field test's `against` becomes `field:<space>:<fmt>`, and `TEST_VERSION` goes up. There are 0 tests today. |
| Paired keys | No change. |
| Command line | `python -m decklab.lib.forge play`, `field` and `variant`, and the result readers, are unchanged and see everything. |

---

## 4. Consequences for Matt, and the settled decisions

### What Matt can no longer do on the page

The command line can still do all of it.

- **Read another space.** User5's, User2's, User3's or User4's collection, tokens, decks, games, Activity rows, Forge results and runs are hidden until that person makes them public. Matt can still stop their runs, but sees them only as "a run of one of User2's decks". Visits names their decks as "one of User2's decks".
- **Write to another space, even a public one.** That means fixing their collection or tokens, importing for them, using **Add a precon** in their space (`journeys.md:233`'s onboarding step), making, editing or deleting their decks, updating their tables, and recording a game for them.
  - Claude still can: `collection merge --space`, `tokens add --space`, `deck new --space`, `deck push` and `deck tables`.
  - A precon needs a new command, `python -m decklab.db collection add-precon CODE --space S` (E10-S36). Without it, adding a precon for a space member means MTGJSON, then `collection merge`, then `deck new` by hand.
- **Pick a member on the home network's "Who are you?".** Members sign in through decklab.example.com, from home too.
- **Use the API from another LAN device, or from his own browser before picking a profile.** Both see only what is public. Scripts on the PC send `X-Deck-Lab-Script: 1`.
- **Count on members seeing home decks.** Until home's `decks` is Public, they can't see home decks, record games against them, or field-test against them.
- **See User1's accessories.** This is unchanged. Turning on `matt` or `shared` shows those rows to User1 or the space members, read-only.

**Within home, either profile can flip a switch.** User1 could make home's decks public on her own, which would show Matt's deck notes. Activity shows both of them who flipped it.

### Decisions (Matt, 2026-10-13)

All seven were settled the same day: 1-4 and 7 by Matt's answers, 5 and 6 as this design recommended.

1. **Home-network chooser:** home profiles only. Space members always sign in through decklab.example.com (from the home Wi-Fi too), and the home listener refuses a header naming them.
2. **Admin writes in other spaces:** removed from the page. Matt asks Claude, and E10-S36 adds the precon command Claude needs.
3. **What Claude tells Matt about a private space:** upkeep, not contents. Claude does what the space's owner asked and says it's done, but doesn't relay a private space's cards, decks or games to anyone outside it (AGENTS.md, "Spaces").
4. **Tests of a change to someone else's visible deck:** own space only. Matchups and field runs against a visible deck stay open.
5. **Who flips home's switches:** either home profile; the last flip wins.
6. **Per space or per deck for `decks`:** per space now; per deck is a later `could`.
7. **Original build timing (superseded):** phase 0 (the `ROLLBACK_MIGRATION` 0008 fix) done 2026-10-13; phase 1 (E10-S35 + E10-S28) was to follow the side-by-side week, with phase 2 onwards after Matt's 5b decision.

Update 2026-10-18: decision 6 is MT decision A (per-deck public is E10-S41). Section 5 replaces decision 7's phases and date gate: phases 1 to 4 are built, 5b is done and Matt confirmed the invite sent. Remaining development can proceed; enabling each switch waits for its completed reader rules. Decisions A to K remain settled.

### Decisions (Matt, 2026-10-18)

MT sets out eleven more, A to K. Matt accepted all of them as recommended. In short:

- **A. Fine-grained:** one switch per list (collection, decks, games, each owner's accessories); per-deck public is a later `could` (E10-S41).
- **B. Wording:** Public and Private everywhere, never "visible to the family".
- **C. The profile roster:** a viewer sees only their own profile and profiles whose space has something public (the admin's display name excepted). No answer names a space the viewer can't see (E10-S38).
- **D. Relayed requests:** Matt passing on User5's request counts as the owner asking, for upkeep only (merges, `add-precon`, table refreshes). Claude reports counts and "done", never contents, and never flips a member's switches. This narrows decision 3.
- **E. Visits:** kept; User5's invite says so.
- **F. Simulations wording:** members see only the mode and a reason without names (E10-S34).
- **G. Mixed Game-log records:** each side edits only its own side; the result and notes stay with the recording space; a sideboard plan belongs only to its deck's space; naming an opponent deck needs it public or the viewer's own (E10-S32).
- **H. Leaving:** a new command exports a member's space and removes it in one audited change (E10-S40).
- **I. Admin narrowing:** E10-S29 ships before User5's invite.
- **J. Home members:** User1 may edit home's collection and tokens, as Matt can (E10-S43).
- **K. Migration day:** home's decks stay private when the space members move onto the template.

---

## 5. New stories for `stories.md`, epic E10

### Build order (phases)

Update 2026-10-18: [MT §4](member-template.md#4-what-shipped-and-the-remaining-build-order) owns the remaining build order. This replaces the original phases and their date/invite gates. With no switch rows everything remains private; implementation does not itself make any member's data public.

| Phase | Stories | Notes |
|---|---|---|
| 0, done 2026-10-13 | — | Add `0008_visits.sql` to `ROLLBACK_MIGRATION` (`db/inv_inventory.py:71-74`). A bug fix, not a story. |
| 1, built 2026-10-18 | **E10-S35 + E10-S42** | Who counts as a script, the home chooser offering home profiles only, `/api/me` per viewer. Sleeve assignment checks the deck's edit right. |
| 2, built 2026-10-18 | **E10-S30**, without the switches | Own-space deck visibility, all audited readers and write-route checks, plus a coarse Forge filter. Only admins stop runs for now. |
| 3, built 2026-10-18 | **E10-S36, then E10-S29 (+ E10-S43)** | The precon command, inventory privacy and admin narrowing (decision I), with User1 editing home's collection and tokens (decision J). |
| 4, built 2026-10-18 | **E10-S32's member rules + E10-S38 + part of E10-S34 + E10-S39** | Mixed Game-log records (decision G); roster and wording (C); settings GET and simulations wording (F); neutral static examples. |
| Invite, sent | — | Matt confirmed on 2026-10-18; Access policy/profile email previously verified. Decisions D and E still govern upkeep and Visits. |
| After the invite, built 2026-10-18; live 2026-10-19 | **E10-S28 (with S32's `games` switch), E10-S34's Activity, E10-S37, E10-S31, E10-S40** | The switches, own-space Activity, server-side history masking, full Forge rules and member departure. Migrations `0012` (visibility) and `0013` (member departure) were applied and the server restarted on 2026-10-19. Nothing is switched Public yet; no member export or removal has been run. |
| Built 2026-10-18; live 2026-10-19 | **E10-S33** | Public accessory readers, owner-only writes, writable-row hashes and no-cache pictures at new addresses. |
| Deferred until requested | **E10-S41** | Per-deck public remains a later `could`, per decision A. |

**Enabling Public is a separate readiness check within the build** (all four kinds' readers are now built, so every switch is offered; each still starts Private). S28 must not expose or accept a switch until its complete public-reader criteria pass: collection uses S29's read-only and home-record redaction rules; games use S32's record visibility and hidden-side rules, with every sideboard plan still owner-only under decision G; decks require S30 plus S31's full Forge rules and S37's server history masking; accessories require S33, including write ownership and no-cache pictures at new addresses. All kinds integrate with S38's roster and S34's own-space Activity rules. Only the owner then decides whether to make anything public.

The coarse Forge filter in S30 shows a result or a running job only when every side has some `seen_as` id the viewer can see, and lets only admins stop runs in the meantime. It means phase 2 ships alone without Forge leaking the lists it has just hidden.

The story copies below are the 2026-10-13 design text with their status kept current; [stories.md](stories.md) owns the live criteria, which have moved on since (for example E10-S31's stop rule).

**New stories of 2026-10-18** (their text is in [stories.md](stories.md); the reasons in MT; all built 2026-10-18 except E10-S41): E10-S37 History subjects for outside viewers (should); E10-S38 Profiles and spaces an outsider can see (must, decision C); E10-S39 Scrub real names and results from the page's code, plus a grep test (must, S); E10-S40 A member leaving: export and remove a space (should, decision H); E10-S41 Per-deck public (could, decision A); E10-S42 Sleeve assignment checks the deck's edit right (must, S); E10-S43 Home members edit home's collection and tokens (must, S, decision J).

---

**E10-S35** · Matt · must · S · built · *added for a decision*

As Matt, I want only scripts on the PC to read everything when no profile is named, and the home network's chooser to offer only home profiles, so that neither a phone on the home Wi-Fi nor someone picking a space member's name can read a private space.

- Given a request to the home listener from 127.0.0.1 or ::1 with `X-Deck-Lab-Script: 1` and no viewer, when it asks for `/api/collection?space=user2`, then it is answered as today.
- Given a request from another home-network device naming nobody, or the PC's browser before a profile is picked (no script header), when it asks for `/api/collection?space=user2`, then it is refused unless User2's collection is public.
- Given the tunnel's listener on 127.0.0.1, when a request carries the script header, then it gets nothing extra.
- Given the home network's "Who are you?", when it lists profiles, then only Matt and User1 are offered.
- Given a home-network request whose `X-Deck-Lab-Viewer` names User2, when it reaches any route, then the answer is 403 "Sign in through decklab.example.com".
- Given a job thread (Forge coordinator, goldfish), when it reads decks, then it reads every space as today.
- Given the history, commits, dbstatus, visits, simulations and editor call sites that treat naming nobody as everything, when they're checked, then each asks `guard.script()`, and `guard.local()` still means "not through the tunnel".

Decision (Matt, 2026-10-13): default is no visibility; only the PC's command line is exempt.

Evidence:
- `decklab/lib/permissions.py:160-162,172-173,215-216,229-230,247-248` (naming nobody sees everything)
- `decklab/lib/api/guard.py:176-178,236-247` (local() and viewer())
- `decklab/lib/api/history.py:73`, `decklab/lib/api/commits.py:112`, `decklab/lib/dbstatus.py:280-285`, `decklab/lib/api/visits.py:109`, `decklab/lib/api/simulations.py:89-94`, `decklab/lib/api/editor.py:150`
- `decklab/server.py:228-236` and `decklab/lib/server_run.py:44` (the tunnel listener is on 127.0.0.1 too)
- `decklab/lib/access.py:370-375` (anyone may name anyone), `decklab/web/app.js:114,192-200` (the chooser lists every profile)
- `decklab/tests/homenet_support.py:33` (test servers bind loopback)

**E10-S28** · Matt · must · M · built · *added for a decision*

As Matt, I want one switch for each thing our space owns (collection, decks, games, and each kit owner's sleeves, boxes and playmats), all starting private, so that nothing of ours is seen outside the household until one of us chooses to show it.

- Given the database after the visibility migration (the next unused number), when no switch has been flipped, then `python -m decklab.db visibility list` shows every thing as Private.
- Given User1 is the viewer, when she opens Who sees what in the avatar menu, then she sees switches for home's collection, decks and games, her own kit and the shared kit, and none for Matt's kit or another space; each switch appears only once its rule is built.
- Given User2 is the viewer, then he sees switches only for his own collection, decks and games.
- Given Matt makes home's decks public, then one change set by Matt is saved, and Activity shows "Make the home decks public" to Matt and User1 only.
- Given Matt sends a flip for User2's space, then the answer is 403 "Only the owner can change who sees this.", naming no one.
- Given GET `/api/me` on the home network with User1 picked, then its `may` is User1's, including `visibility`; and after she flips a switch the page fetches it again.
- Given the database can't be read and nothing is cached, when a rule asks for the switches, then everything counts as private.
- Given User2's profile is removed and synced, then his visibility rows are deleted in the same change set.
- Given the nightly, then the table is exported and covered by the restore check's digests, and `check` flags a row whose owner is neither a space nor a kit owner (a home profile or shared; E11-S48).

Decision (Matt, 2026-10-13): default is no visibility. A switch makes a thing visible to everyone with a profile, read-only, and is flipped only by its owner (home: Matt or User1; the last flip wins).

Evidence:
- `decklab/db/migrations/0003_personal_state.sql:6-9,42-49,70-86` (no foreign keys; the simulation_mode and audit trigger pattern)
- `decklab/lib/state/pg.py:642-675` (simulation_mode_cached / _set)
- `decklab/db/export.py:43,81-82`, `decklab/db/check.py`, `decklab/db/profiles_sync.py:53-63,118-119`
- `decklab/lib/access.py:414-432` (me() answers for nobody at home)
- `decklab/lib/server_http.py:306-310,399`
- `decklab/web/core.js:298-330` (deriveMay works out may from the profile alone), `decklab/web/shell.js:108,125,184-188`, `decklab/web/index.html:135`

**E10-S36** · Claude Code · must · S · built · *added for a decision*

As Claude Code, I want a command that adds a published precon to any space, so that Matt can still onboard a space member's precon once the page no longer lets him write in their space.

- Given `python -m decklab.db collection add-precon CODE --space user4 -m "..." --dry-run`, then it previews the cards to add (plain basics left out) and the deck it would make, the same as the page's Add a precon.
- Given it is run without `--dry-run`, then the cards and the built deck are saved in one change set, with the deck's table worked out after the cards are added.
- Given a slug already taken in that space, then it is refused with the existing id.

Decision (Matt, 2026-10-13): the admin role doesn't override; the command line still writes every space.

Evidence:
- `decklab/lib/api/precons.py:164-167,210-321` (the page's preview and add)
- `decklab/design/journeys.md:233` (onboarding uses Add a precon on the person's page)

**E10-S29** · Space members · must · L · built · *added for a decision*

As User2, with my own space, I want my collection and tokens seen only by me unless I make them public, and changed only by me even then, so that the admin can't browse or edit my cards on the page.

- Given User2's collection is private, when Matt opens `#/collection?space=user2`, then the answer is 403 "User2 hasn't made his collection public."
- Given it is public, when Matt opens it, then he sees it read-only; and POST `/api/collection/save`, `/collection/import/preview`, `/collection/import/apply`, `/api/tokens/save` and `/api/precons/add` for space user2 each answer 403 with only `{"error"}`, even with a stale sha256.
- Given Matt asks for GET `/api/precons/preview?space=user2`, then the answer is 403, so no deck id is probed.
- Given home's collection is public, when User2 opens `#/shopping`, `#/receipt` or `#/assembly`, then they aren't in his navigation and their APIs answer 403.
- Given home's collection is public, when User2 opens Collection or Tokens, then he sees no order ids, no pending token orders and no warnings about order or product files; rows on the way show only a count.
- Given home's collection is public but its decks private, when User2 opens Collection or Tokens, then decks are named only as "one of the home decks".
- Given User3 edits his own deck while home's collection is public, when he opens the printing picker or pastes a list, then the counts and default printings are User3's, not home's.
- Given the PC's command line, when `collection merge --space user2` runs, then it still works.

Decision (Matt, 2026-10-13): the admin role doesn't override visibility; visible means read-only; Shopping, receipts and the Packing plan stay home's.

Evidence:
- `decklab/lib/permissions.py:156-162,196-219,313,387-389`
- `decklab/lib/api/collection.py:105,141-144,174`, `decklab/lib/api/collection_edit.py:233-236,289,432,459,659-766`
- `decklab/lib/api/tokens.py:154-160,192-202,346,447`
- `decklab/lib/api/precons.py:164-167,210-214,315-321`
- `decklab/lib/api/card_lookup.py:167-176`, `decklab/lib/api/drafts.py:61-68`
- `decklab/lib/pool.py:263-413,475-479` (warnings name order and product files)
- `decklab/lib/api/shopping.py:39,243-244`, `decklab/lib/api/receipts.py:106,316,422`, `decklab/lib/api/assembly.py:103,125`

Supersedes E10-S19 (built when this is).

**E10-S30** · Matt · must · XL · built · *added for a decision*

As Matt, I want each space's decks seen only by that space unless it makes them public, so that the household's decks and plans stay ours until we choose to make them public, and a member's stay theirs.

Size: XL. It is built as (a) the library and deck pages through `_find_summary` and `_deck_sections`, and (b) the readers that bypass them, the write-route checks and a coarse Forge filter. (a) and (b) merge together.

- Given home's decks are private, when User2 asks for GET `/api/decks`, then no home deck, product deck or pairing is in it, and his library says "Home's decks aren't public yet."
- Given he asks for `/api/deck`, `/deck/edit`, `/deck/history`, `/deck/revision`, `/deck/cards`, `/goldfish` or POST `/api/deck/check` on `casual/gruul-ramp`, or "Save as a new deck" from `product/...`, then each answers exactly what a missing id answers (404 "No deck casual/gruul-ramp").
- Given he posts `/api/deck/save`, `/deck/cover` or `/tables/update` naming a home deck, then the answer is the same 404, never a 409 or a title.
- Given GET `/api/play`, then `lists`, `decks` and `warnings` hold or name only decks he may see.
- Given GET `/api/matchups`, `?running=1`, `/api/matchup?key=`, `/api/variant?test=` or `/api/variants?id=` for anything with a home side, then nothing of it reaches him (404 for a key, test or id).
- Given home's decks are public, then User2 sees them read-only, with "Try a change" but no Edit, its counts only if home's collection is public too, and no ordered or preordered product's decks.
- Given a wishlist entry whose source is a hidden deck, then the page shows the path, not the deck.
- Given User2 opens a hidden home deck's address, then Visits records no deck id; and given Matt opens Visits, then User2's private deck shows as "one of User2's decks".

Decision (Matt, 2026-10-13): decklists are private by default and can be made visible, reversing E10-S09; a visible deck shows its text as written.

Evidence:
- `decklab/lib/api/library.py:58-69,116-142,286-310`
- `decklab/lib/api/deck_page.py:28-84,303-427`
- `decklab/lib/api/history.py:44-58`, `decklab/lib/api/commits.py:60-73`, `decklab/lib/api/editor.py:79-87,374,389-514`
- `decklab/lib/api/saving.py:221-225,503-510,551`, `decklab/lib/api/cover.py:93-95`
- `decklab/lib/api/play_records.py:363-372`
- `decklab/lib/api/visits.py:64-96,125-131`, `decklab/lib/api/wishlists.py:73-92`
- `decklab/lib/api/forge_runs.py:243-280,387-440,632-685`, `decklab/lib/api/variant_page.py:116-255`
- `decklab/decks/__init__.py:317-407` (product decks include ordered ones)
- `decklab/tests/test_deck_readers_p4.py` (asserts R6d)

**E10-S31** · Matt · must · L · built · *added for a decision*

As Matt, I want Forge results, runs and fields to follow the decks' visibility exactly, so that a matchup never shows a list its viewer may not see, and nobody loses results for their own list.

- Given a result whose `seen_as` names only a home deck, and User2's deck has the identical list, when User2 opens his deck, then the result shows under his deck, never under the home deck's id or title.
- Given a deck page, then its matchups, earlier results, per-card stats and "cards the AI can't play" count only results whose both sides the viewer sees.
- Given User2 runs a field run of his own deck, then its field is his space's decks plus the decks of spaces with public decks; and with nothing public the answer is "No opponents".
- Given a home deck's field, then it is today's field, the 2 existing field notes still load, and a non-home viewer's view leaves out ordered products and any member they can't see, with the rating fitted only over visible results.
- Given User1 asks to test a change to one of User2's visible decks, then `/api/variant/run` answers 403, while a matchup run against it is allowed.
- Given a run User4 can't see, when he posts stop with its key, then the answer is 404; and given Matt, then the pill shows it as "A run of one of User4's decks" with Stop.
- Given a starter from another space, then results and runs name them "someone".
- Given the PC's command line, when `python -m decklab.lib.forge field` runs, then it is unchanged.

Decision (Matt, 2026-10-13): results take their decks' visibility and are never made visible on their own; the field depends on the deck's space.

Evidence:
- `decklab/lib/api/forge_runs.py:181-206,243-280,365,387-440,489-532,632-887`
- `decklab/lib/forge/views.py:197-210,271-339` (seen_as[-1]; casts and cards reveal lists)
- `decklab/lib/forge/field.py:120-192,211,300,336,668,757,838`
- `decklab/lib/api/field_page.py:54-56,74-78,103-147,165-214`
- `decklab/lib/api/variant_page.py:116-394`, `decklab/lib/forge/variants.py:224-235,327,957`
- `decklab/lib/forge/cardstats.py:441`, `decklab/lib/permissions.py:34`

**E10-S32** · Matt · must · M · built · *added for a decision*

As Matt, I want the Game log visible only to a record's own spaces unless a space makes its games visible, so that no admin or space member reads games they weren't part of, and a game with someone else's deck doesn't show its list.

- Given User4's games are private, when Matt opens `#/play`, then no game with only User4's decks appears.
- Given a game of User2's deck against a home deck, with home's decks private, when User2 views it, edits it or receives its saved answer, then the home side reads "a home deck", with no list snapshot.
- Given someone posts an edit of a record they may not see with a stale sha, then the answer is 404, not 409.
- Given Activity, when anyone reads a game's change set, then no side they may not see is named, and older "Save game A vs B" messages show only to viewers who see both decks.
- Given User2 records a game against a deck he may not see, then the answer is 404.

Decision (Matt, 2026-10-13): the Game log is private by default and can be made visible; the admin role doesn't override.

Evidence:
- `decklab/lib/permissions.py:236-254`
- `decklab/lib/api/play_records.py:130-157,250-263,287-389`
- `decklab/lib/api/activity.py:342-349,426-438`

This settles E10-S15's third criterion and removes E10-S24's admin branch.

Built on 2026-10-18 as decision G's member rules (stories.md has the note); the `games` switch comes with E10-S28.

**E10-S33** · User1 · should · M · built · *added for a decision*

As User1, I want to make my sleeves, deck boxes and playmats public while only I can change them, so that I can show them off without anyone else choosing them for decks.

- Given User1's kit is public, when Matt opens `#/accessories`, then her rows show read-only, grouped under her name, with no Edit, and their pictures load.
- Given that, when Matt chooses sleeves for a deck Played by wife, saves one of her rows or stages a picture for it, then the answer is 403.
- Given her kit is public but home's decks private, when User2 views it, then holders read "a home deck" and no holder or product list is sent to him.
- Given she makes it private again, when Matt's browser asks for one of her pictures, then it is refused at once (pictures are sent no-cache, and their addresses changed when this shipped).
- Given any accessories save by Matt, then its sha256 covers only rows he may change, so a change of User1's never makes his save conflict.

Decision (Matt, 2026-10-13): owners can make their accessories visible, read-only.

Evidence:
- `decklab/lib/permissions.py:165-185,305-310`
- `decklab/lib/api/guard.py:262-334`
- `decklab/lib/api/accessories.py:93-140,243-268,520-575`
- `decklab/lib/accessories.py:311-320,468-482,718-719`, `decklab/lib/inventory/ops_accessories.py:81-109`
- `decklab/lib/server_http.py:28,570-595`
- `decklab/web/accessories.js:228,419-431,569`

**E10-S34** · Matt · should · M · built · *added for a decision*

As Matt, I want Activity and profile settings to show me only my own space's changes plus system rows, so that being admin doesn't show me the space members' changes or Claude's messages about their cards.

- Given Claude merges cards into User4's collection, when Matt opens Activity, then the change isn't listed and its `-m` message never reaches him.
- Given User4's collection is public, then Matt still doesn't see its Activity rows.
- Given Matt, then he still sees profile, email and space rows and change sets with no rows.
- Given a change set with rows in two spaces, from the command line or the page, then its message shows only to a viewer who sees every row.
- Given User1 asks for `/api/profiles/matt/settings`, then the answer is 403.

Decision (Matt, 2026-10-13): the admin role doesn't override; making something visible doesn't widen Activity.

Built on 2026-10-18: settings GET and the simulations wording (MT decision F) before the invite, then the Activity criteria after it. stories.md owns the complete acceptance criteria and implementation notes.

Evidence:
- `decklab/lib/permissions.py:222-233`
- `decklab/lib/api/activity.py:144-178,242-260,305-358`
- `decklab/lib/state/rules.py:296-369`, `decklab/lib/state/pg.py:211-266`
- `decklab/lib/api/settings.py:90-95`

### Changes to existing stories

- **E10-S09:** add a Decision line (2026-10-13: reversed by default-no-visibility). Set it to `not_wanted` when S30 ships (done: `wont`, `not_wanted`). Hiding the counts survives for a deck that is visible while its space's collection isn't.
- **E10-S12:** the third criterion becomes "unless the owner made it public".
- **E10-S15:** its review note is resolved by S30 and S32.
- **E10-S19:** superseded by S29.
- **E10-S24:** the admin branch is removed (S32), and its Built note about open deck lists becomes untrue.
- **E10-S25:** hidden decks are anonymised and the beacon gated (S30).
- **E8-S16:** pictures follow the readers set, sent no-cache (S33).
- **E10 intro:** the trusted-chooser paragraph changes (S35).

---

## 6. Other docs to update (when each story ships)

**AGENTS.md "Spaces":**
- "Who may change what": replace "an admin edits everything".
- Rewrite "Who may read the inventory": the switches, no admin override, home records for home profiles only, the script header, and the home-only chooser.
- Delete "anyone may see a deck's list, prose, stats and matchups".
- Accessories paragraph: add "public (to everyone signed in), read-only".
- Replace every "visible to the family" with public and private (MT decision B), and say that public means signed-in profiles, not the open internet.
- Add the Claude relaying rule (decision 3).
- Add `visibility` to the `sql` tables in "Wishlists and other database data", and `visibility list|set` and `collection add-precon` to the Layout block and "The inventory".

**`lib/permissions.py` docstring:**
- 1-126: the rules, "an admin may do everything", "anyone may stop any run" (34), accessories, inventory, Activity, the Game log, "the deck lists stay open" (92-95), "Everything else is open to read".
- ACTIONS (`visibility.edit`, run stop).
- Function docstrings 156-254 and 356-400.

**`lib/api/guard.py` docstring:**
- 16-62: the route list, the stop rule, and `PUT /api/visibility`.
- 64-169: rewrite the five read rules and add decks and Forge.
- 176-178: `local()` vs `script()`.
- 374-399: the 403 wording.

**Other module docstrings:**
- `lib/access.py:370-375, 414-432`
- `lib/api/activity.py:6-56`
- `lib/api/accessories.py:30-36`
- `lib/inventory/ops_accessories.py:12-14`
- `lib/accessories.py:19-24`
- `lib/api/play_records.py:345-352`
- `lib/api/drafts.py:61-65`
- `lib/api/wishlists.py:76`
- `lib/api/precons.py:208`
- `lib/api/__init__.py:80-85`
- `server.py:116-119, 245-265, 308-313`
- `server_http.py:550-568`

**`decklab/README.md`:**
- "People's own collections" (around 184-190): roles, the read rules, the Game log, accessories, and "anyone may name anyone".
- "Database": the new table and command; rollback tooling was retired in phase 5b, so no rollback registration is needed.
- "From outside the home": space members sign in there from home too, and only the script header on loopback counts as a script.

**`decklab/design/`:**
- `stories.md`: E10 intro, the summary counts, the stories above.
- `README.md`: epic counts.
- `personas.md:51` ("can read every person's space's inventory").
- `gap-analysis.md`: counts, roadmap, the trusted-header line at 71.
- `journeys.md`: E10's map, the onboarding step at 233 (via S36), stage 5's "looks at home decks read-only".

**`TODO.md`, `PLAN.md`, `HISTORY.md`:**
- TODO: rows for the phases above, in order.
- PLAN: keep remaining privacy work aligned with MT §4; the side-by-side report is separate dated work, not a privacy build gate.
- HISTORY: a dated line per phase, and the rollout note.

**Tests to rewrite:**
- `test_permissions.py`
- `test_api_permissions.py`
- `test_deck_readers_p4.py`
- `test_receipts_api.py`
- `test_shopping_ui.py`
- `test_accounts_ui.py`
- `test_activity_ui.py`
- `test_shell_ui.py`
- `test_inventory_ops.py`
- `test_play_records.py`
- `test_visits.py`
- `test_server_access.py`
- `test_state_contract.py`
- `homenet_support.py`, so it sends the script header

The old database gates were retired in phase 5b. Maintain their surviving reader goldens through `tests/golden_p4.py` when a phase changes a viewer's answers.

---

## 7. Critiques rejected or changed

Most of both reviews is folded in above. These are the exceptions.

- **Merging `games` into `decks`** (risk review, medium 10): rejected. Matt named the Game log as its own shareable thing. It is one extra row on the switches page, and records already anonymise sides the viewer can't see.
- **Visibility flips as admin system rows** (code critique 14): rejected in favour of the risk review's simpler rule (medium 9), owner's space only. Showing admins other spaces' flips would be a small override in itself.
- **A second factor for space members on the home network** (code critique 1, one option): rejected for the home-only chooser. Space members already have a working login through decklab.example.com, which works from home.
- **Cutting the Substitutes prose and owned version from a visible deck when the collection isn't visible** (code critique 6, one option): rejected. The text is hand-written and cutting it reliably isn't possible. Instead, the `decks` switch shows the text as written and says so. Computed availability still follows C.
- **Per-table space lists in Activity's SQL** (the earlier draft): dropped, as the risk review suggested (medium 8). With Activity limited to the viewer's own space, one list is enough.
- **Shipping S30 and S31 together as one XL+L slice** (the earlier draft): changed as the risk review suggested (serious 5). A coarse Forge filter moves into S30, so S30 ships alone and S31 refines it.
- **"Every field member is visible to whoever sees D"** (the earlier draft): dropped. Ordered products and stored notes broke it. The field view is now always filtered for the viewer, which also fixes stale field notes (risk review, medium 6).
- **No-cache only for pictures the viewer doesn't own** (the earlier draft): replaced by no-cache for every accessory picture plus new addresses at ship (risk review low 14, code critique 16).
