# The member template

Design note, 2026-10-18. It sits beside [privacy-by-default.md](privacy-by-default.md) (PBD below) and the E10 stories in [stories.md](stories.md). Paths are relative to `decklab/`, and audit line numbers are as of 2026-10-18. **Matt accepted decisions A to K on 2026-10-18, all as recommended.** Phases 1 to 4 were built before the invite, which Matt confirmed sent on 2026-10-18, and the remaining items (the switches, full Forge rules, public accessories, Activity, history masking and member departure) were built the same day. All of it has been live since 2026-10-19 (migrations 0012 and 0013 applied). Nothing is switched Public yet. Section 4 records what shipped; only per-deck public (E10-S41) is left, deferred until someone asks.

**Why it exists.** At design time only Matt and User1 had really used Deck Lab; User2, User3 and User4 had been invited but had not come in. User5 (`user5`) was the first intended active member, so this model was settled before their invite. **Their setup is the template for every future member**, and the other three members follow the same setup. Matt confirmed the invite sent on 2026-10-18; that does not establish whether User5 has started using it.

**Matt's decisions (2026-10-18):**
1. User5 sees only what Matt chooses to show them.
2. User5 uses only decklab.example.com, never the home network.
3. **Everything in an account is private by default.** Its owner can set something to **public** so other people can see their decks and the rest. This applies to home's data too.

Decision 3 is PBD's rule with one word changed. PBD already says "a visible thing is visible to everyone with a profile, read-only" (PBD:15). The word "family" was wrong once members from outside the household joined, so it is replaced by **public**. There is no family flag and no separate family audience. Public means public to everyone signed in, behind Cloudflare Access, never the open internet: E10's rule of no public pages, share links or sign-up still holds.

---

## 1. The model for a member

**What a member has.** Everything in their own space (the space id is their profile id):
- their collection, token cards and raw imports;
- their decks: the Planned list (Commander, Companion, Deck and Sideboard), the Play-now list, the prose, the history, retired decks included;
- their Game log: the records where one side is one of their decks;
- their wishlist (already owner-only, `lib/permissions.py:197-202`);
- their profile settings;
- the Forge results, field runs and variant tests made only of their own decks.

A member has no orders, products, watchlist, accessories, Packing plan or Commander-night notes. Those stay home-only for good.

**What a member sees of others.** Nothing, unless the owner made that thing public. A hidden thing gets exactly the answer a missing thing gets: no id, title, count, existence, "who" or "when", no Forge side and no other profile's details (PBD §1, "Hidden looks the same as missing").

**What others see and do in a member's space.**
- **Everyone else, home included:** only what the member made public, and only read-only.
- **The admin (Matt) on the page:** the same as anyone else. There is no read or write override (PBD decision 2). Admin keeps only the system role: the simulations setting, Settings, Visits, and stopping any run (shown to him as an anonymous item).
- **The command line (Claude):** reads and writes everything, because it isn't a request. Claude does the upkeep the owner asks for and says it's done, but doesn't pass on the contents (AGENTS.md, "Spaces").

**How a member gets in.** Only through decklab.example.com, behind Cloudflare Access. The audit confirmed this is sound:
- The tunnel identifies each request by an RS256-signed Access JWT, checking audience, issuer and expiry (`lib/access.py:166-216, 295-315`). The email header is never trusted.
- An email in no profile, or in more than one, is refused everywhere (`lib/access.py:135-147, 318-331`).
- Through the tunnel, the viewer header, `?profile=` and a body `profile` are all replaced by the login's (`lib/server_http.py:311, 635-636, 669-680`).
- The home listener refuses anything that carries Cloudflare headers (`lib/server_http.py:350-357`). The tunnel won't start if an ingress rule points at the home port (`lib/tunnel.py:178-223`).

The gap was at home: the home chooser offered `user5`, so anyone on Matt's Wi-Fi could act as User5 (`lib/access.py:370-375`, `web/app.js:114, 192-200`). E10-S35 fixed that (built 2026-10-18): the chooser offers only home profiles.

### The switches

These are PBD's switches (one per owner and thing: `collection`, `decks`, `games`, and each owner's `accessories` at home), worded **Private** / **Public**. With no row a switch is Private. Public always means read-only, to every signed-in profile, future members included. Only the owner changes a switch. At home that's Matt or User1, and the accessories switch belongs to the owner of each kit.

**A, how fine-grained.** Is it one switch per list (all my decks public), or per deck as well?
**Decided (Matt, 2026-10-18), as recommended:** one switch per list now, as PBD builds it, with per-deck public as a later `could` (E10-S41). Per-deck is the more natural "show User5 this one deck", but every Forge rule (a matchup is visible only when both sides are) then works per deck instead of per space. That is much more to build and test. It's worth doing only once someone actually wants it.

---

## 2. Decisions the template needed

Matt accepted every recommendation below on 2026-10-18.

**B. Wording.** Every page string, command message and audit message says "public" and "private", never "visible to the family" (PBD:54, :93). **Decided (Matt, 2026-10-18), as recommended:** adopt this as written; where public and E10's "no public pages" rule meet, say "public (to everyone signed in)".

**C. The profile roster.** `GET /api/profiles` lists every profile's id, name, role, space and `plays_as` to anyone (`lib/api/settings.py:30-47`). So User5 learns who the admin is, that Matt and User1 share home, and the other members' names.
**Decided (Matt, 2026-10-18), as recommended:** a viewer gets their own profile, plus any profile whose space has something public. The one exception is the admin's display name, used in "ask Matt" wording. Fix it together with the 403 wording, so that no answer names a space the viewer can't see (`lib/api/guard.py:396-405`, `lib/api/collection.py:71-80`). Story E10-S38.

**D. Relayed requests.** User5 will ask Matt to do things, and Matt will ask Claude (merge a scan into User5's collection, add a precon).
**Decided (Matt, 2026-10-18), as recommended:** count Matt passing on User5's request as the owner asking, for upkeep only: merges, `add-precon` (E10-S36, built 2026-10-18) and table refreshes. Claude reports counts and "done" to Matt, never the contents. Claude never changes User5's switches on a relayed request: User5 does that on the page.

**E. Visits.** Matt's Visits page shows each day User5 came in and which pages they opened (`ops.visit_day`, `ops.visit_page`).
**Decided (Matt, 2026-10-18), as recommended:** keep it, and say so in the invite. Under E10-S30, Visits names a private deck only as "one of User5's decks".

**F. Simulations wording.** A member gets the mode, who set it, when, the worker counts and the admins' names (`lib/api/simulations.py:84-109`).
**Decided (Matt, 2026-10-18), as recommended:** members get only the mode and a reason without names ("Simulations are limited to the admin"). `by`, `since` and `workers` go to admins only.

**G. Mixed Game-log records.** Today any space a record names may overwrite the whole record (`lib/api/play_records.py:306-310`, `lib/permissions.py:345-348`). So User5 can rewrite Matt's notes on a game against User5's deck, or create games naming home decks that then show in Matt's and User1's Game log.
**Decided (Matt, 2026-10-18), as recommended:**
- each side's space edits only its own side (its deck, its mulligans), and the result and notes stay with the space that recorded the game;
- a sideboard plan belongs only to its deck's space;
- naming an opponent deck needs that deck to be public or the viewer's own (PBD already gives a 404 otherwise).

**H. Leaving.** A member may stop using Deck Lab. PBD covers only the switch rows when a profile is removed (PBD:83).
**Decided (Matt, 2026-10-18), as recommended:** a `space export` command (E10-S40) writes the member's collection and decks out for them, then removes the space's data in one audited change. Their email comes out of the Access policy as well.

**I. The admin narrowing in User5's space (E10-S29, built 2026-10-18).** Until it shipped, Matt could read and change User5's collection, tokens, decks and Game log and read their Activity, on the page.
**Decided (Matt, 2026-10-18), as recommended:** ship it before the invite (§4). If it waits, the invite says so.

---

## 3. The pre-build audit, and the fix for each

The audit traced every route in the server's route table (2026-10-18, 46 checks). The tables record what the audit found before phases 1 to 4, not what User5 can reach now; section 4 and the stories record what shipped. Each leak was checked again by a separate reviewer, and none was refuted. **V(deck)** means the deck is in the viewer's own space, or its space's `decks` switch is Public. The common cause was `guard.sees_deck`, which ignored the viewer and always returned True (`lib/api/guard.py:381-387`). E10-S30 made it `sees_deck(target, profile)` (built 2026-10-18).

### High

| What User5 gets | Fix | Story |
|---|---|---|
| The library (`GET /api/decks`) lists every deck in every space: titles, kinds, status, who plays it, covers, colours, revisions, edit times, aliases, usual opponents (`lib/api/deck_page.py:65-97`, `lib/api/library.py:288-312`) | Only V decks, with `halves`, `usual_opponents`, `shelf_extras`, `aliases`, `edited` and `revision` filtered too; `decks_revision` worked out per viewer | E10-S30 (built 2026-10-18) |
| Any deck's page (`GET /api/deck?id=`): every section, stats, goldfish results, the Notes prose, usual opponents, every saved matchup (home-vs-home win rates included), running jobs, Commander-night notes (`lib/api/deck_page.py:348, 476-488`) | 404 unless V; matchups filtered on both sides | E10-S30 (built 2026-10-18; matchups E10-S31) |
| Any deck's editor (`GET /api/deck/edit?id=`): both lists, the Substitutes and Notes prose, every header field (`lib/api/editor.py:36-77, 99`) | 404 unless V | E10-S30 (built 2026-10-18) |
| Any deck's history (`GET /api/deck/history`): every revision's date, who saved it and the first line of its message, so Claude's `-m` subjects and git commit subjects too, which Activity hides (`lib/api/history.py:146, 309`) | 404 unless V. Even for a public deck, a message follows Activity's `as_written` rule; a table refresh from an order or receipt shows as "Tables refreshed"; actors from other spaces show as "someone". The mask in `web/history.js:79` moves to the server | E10-S30 (built 2026-10-18) + E10-S37, "History subjects for outside viewers" |

### Medium

| What User5 gets | Fix | Story |
|---|---|---|
| Home's products, ordered and preordered ones included, as product decks with full card lists (`lib/decks/__init__.py:322-366`) | Product and pairing decks to home only (owned ones also when home's decks are public); ordered and preordered never outside home | E10-S30 (built 2026-10-18) |
| Old revisions' full text (`GET /api/deck/revision`), and retired decks' history (`lib/api/history.py:69-94, 329-361`, `lib/api/retirement.py:31-45`) | V checked before the revision lookup, and V of a retired deck's former space | E10-S30 (built 2026-10-18, with `history.py` and `retirement.py`) |
| Every Forge result and running job (`GET /api/matchups`, `/api/matchups?running=1`), any pair's matchup (`GET /api/matchup`) (`lib/api/forge_runs.py:408-487, 685-779`) | Only when every side is V; `by`, `stopped_by` and `cancelled_by` from other spaces anonymised | E10-S30 coarse (built 2026-10-18), E10-S31 |
| **He can stop anyone's runs**: matchups, field runs and variant tests, whatever the simulations mode. His name is saved as the one who stopped it (`lib/api/forge_runs.py:850`, `lib/api/field_page.py:206-213`, `lib/api/variant_page.py:375-380`, `lib/permissions.py:326`) | Stop only a visible run that the viewer started, or one with a deck of their own, or as an admin | E10-S31 (interim in E10-S30: admins only, built 2026-10-18; the page shows Stop only to an admin) |
| A home deck's field (`GET /api/field`), rankings across every space (`GET /api/rankings`), variant tests of home decks (`GET /api/variants`, `/api/variant`), any deck's goldfish (`GET /api/goldfish`) | 404 unless V; rankings rows and ratings only over V decks; the field per space, and product entries to home only | E10-S30 (rows, goldfish; built 2026-10-18), E10-S31 |
| The Game log's deck picker lists every deck in every space (`GET /api/play`, `lib/api/play_records.py:394-405`) | Only V decks | E10-S30 (built 2026-10-18) |
| Mixed Game-log records: he reads home's sideboard plans for games against his deck in full, and can overwrite them (`lib/api/play_records.py:306-310, 388`) | Decision G | E10-S32 |

### Low

| What User5 gets | Fix | Story |
|---|---|---|
| Any deck's Play-now list, which approximates part of that space's collection (`version=owned` on deck, editor, revision and history) | Covered by the 404s above. The Public switch's page warns that the Play-now list hints at what's owned (PBD:52) | E10-S30 (built 2026-10-18) |
| Opponents picker, cover picker, rename and retire previews of any deck (`lib/api/opponents.py:79-106`, `lib/api/cover.py:127-153`, `lib/api/rename.py:25-47`, `lib/api/retirement.py:39-45`) | 404 unless V | E10-S30 (built 2026-10-18, with these files) |
| Existence oracles: restore, and the 409s on save, cover, check and table updates for a deleted deck (`lib/api/retirement.py:140-150`, `lib/api/commits.py:61-71, 153-193`, `lib/api/saving.py:226-229, 535-552`) | V first (a uniform 404), then permission, then the 409 | E10-S30 (built 2026-10-18) |
| Running a matchup, field or variant against home decks, if the simulations mode is ever `everyone` (`lib/api/forge_runs.py:804-822`, `lib/api/field_page.py:164-200`, `lib/api/variant_page.py:320-423`) | Both sides V; a variant's base deck in the viewer's own space | E10-S31 |
| Anyone's settings (`GET /api/profiles/<id>/settings`, `lib/api/settings.py:90-95`) | GET only for one's own id | E10-S34 |
| The profile roster and space names (`GET /api/profiles`; 403 bodies) | Decision C | E10-S38, "Profiles and spaces an outsider can see" (+ E10-S29 wording) |
| The simulations setting's who and when (`GET /api/simulations`) | Decision F | E10-S34 (add a criterion) |
| An Activity change set that touches his space and others shows its whole message, such as an "Update all" naming every rewritten deck's title (`lib/api/activity.py:276-282`) | `as_written` for web change sets too: the message only to a viewer who sees every row | E10-S34 (widen to source `web`) |
| The page's JavaScript has two real home deck names with a real win rate, and household names in comments (`web/matchups-results.js:60-61`, `web/accessories.js:186-187`, `web/core.js:322-326`) | Neutral examples, plus a test that greps `web/` for profile names and deck titles | E10-S39 |
| Image-cache timing (`GET /img/...`) tells one bit per probe: whether a card image was fetched before | Accept as a known risk, recorded in PBD | none |

**Already sound:** the collection, tokens, raw imports, wishlists, accessories and their pictures, Shopping, receipts, products, the Packing plan, Commander-night notes, `/api/me`, Visits and Settings all refuse User5 or hide another space's data.

### Found along the way (home, not User5)

- User1 can't change home's collection or tokens: only an admin can (`lib/permissions.py:350-357`). AGENTS.md says the Tokens page works "any device". Either that's intended and AGENTS.md should say so, or home members get those rights. **J, decided (Matt, 2026-10-18), as recommended:** home's collection and tokens are Matt's and User1's alike, so User1 edits them as Matt can (E10-S43, built 2026-10-18).
- `POST /api/accessories/assign` never checks `deck.edit`, so User1 can set or move sleeves on `either` decks through the API even though the page hides that (`lib/api/accessories.py:467-490`). Fix: require `deck.edit` on the holder (or the product rights for a product) (E10-S42, built on 2026-10-18).
- A home page that hasn't picked a profile reads every space and every owner's accessories (`lib/permissions.py:181-182, 224-225`). E10-S35 already fixes this.

---

## 4. What shipped, and the remaining build order

**Built on 2026-10-18, before the invite:**

1. **Phase 1: E10-S35 + E10-S42.** The home chooser offers home profiles only, and only scripts read everything. Sleeve assignment checks the holder's edit right.
2. **Phase 2: E10-S30 without the switches.** Deck readers and write-route checks use own-space visibility, with a coarse Forge filter and only admins stopping runs for now.
3. **Phase 3: E10-S36, then E10-S29 with E10-S43.** The precon command supports upkeep; no admin reads or writes another space's inventory on the page; User1 edits home's collection and tokens.
4. **Phase 4: E10-S32's member rules, E10-S38, E10-S34's settings GET and simulations wording, and E10-S39.** Mixed Game-log records, the roster, settings, simulations wording and static examples follow decisions C, F and G. E10-S32's `games` switch remains part of E10-S28; the rest of E10-S34 is Activity.

**Invite complete.**

- [x] User5's email is in Cloudflare Access's policy (verified 2026-10-18), and the `user5` profile in `config.json` has it too, as a member in their own space. Nothing broader (such as a whole domain) is allowed.
- [x] Matt confirmed on 2026-10-18 that the invite has been sent.

The agreed invite information remains: sign in at https://decklab.example.com with that email's code; everything starts private and Public switches are still to come; Visits records days and pages (decision E); upkeep through Matt and Claude reports counts and "done", never private contents (decision D). Only the member changes their switches.

**Coverage (updated 2026-10-19; statuses as in [stories.md](stories.md)).** The accepted public reader/control and member-departure slices were built on 2026-10-18 and tested with disposable data. Migrations `0012` and `0013` were applied and the server restarted on committed code on 2026-10-19 (07:44), so both are live; no live visibility choice or member removal has been made. Per-deck public stays deferred until requested. This table owns slices and dependencies; [TODO.md NOW](../../TODO.md#now) is the only scheduling order.

| Prerequisite | Story | Status | Bounded next slice |
|---|---|---|---|
| Complete; live 2026-10-19 | **E10-S28**, switches | BUILT | Storage, request snapshots, public readers and owner controls; defaults Private. Live since migration `0012` and the restart of 2026-10-19; nothing is switched Public yet. |
| Complete | **E10-S34**, Activity | BUILT | Own-space changes plus admin system rows; all-row message masking for CLI and web (2026-10-18). Public visibility never widens Activity. |
| Complete | **E10-S37**, history | BUILT | Server-side outsider message and actor masking, including "Tables refreshed"; the browser mask is removed (2026-10-18). |
| Complete | **E10-S31**, Forge | BUILT | Visible aliases/hash evidence, per-viewer fields/ratings, variant ownership and starter/owner stop rights with anonymous admin controls (2026-10-18). No real Forge games were run for it. |
| Complete; live 2026-10-19 | **E10-S40**, leaving | BUILT | Scoped export/preview, audited apply, lifecycle claims, durable recovery, departure admission and removed-deck readers (2026-10-18). Live since migration `0013`. Actual departure is deliberate maintenance and was not performed. |
| Complete | **E10-S33**, accessories | BUILT | Public read-only rows, writable-only hashes and choices, private holder words and authorized no-cache pictures with new addresses (2026-10-18). |
| Deferred | **E10-S41**, per-deck public | MISSING (could) | Waits until someone asks (decision A). |

The readiness rule each switch was built to (all four kinds are now complete, so every switch is offered, each starting Private): a control appears only when the corresponding public-reader criteria are complete, and the API enforces the same readiness, so an unsupported flip cannot bypass the page:

- **Collection:** E10-S29's public read-only criteria, including hidden holders, home-record redaction, own-space printing counts and the roster's public-space hook (E10-S38).
- **Games:** E10-S32's public record reads and hidden-side redaction. Sideboard plans remain owner-only under decision G, even when games are public.
- **Decks:** E10-S31's full Forge rules and E10-S37's server-side history masking, alongside E10-S30's public deck criteria.
- **Accessories:** E10-S33's complete read/write and picture-revalidation rules.

Every switch starts Private. S34's Activity rules apply to flips, and the roster follows whichever kinds are actually public. Developing or installing this work never makes a member's data public for them. **E10-S41 remains deferred until someone asks for per-deck public**, as decision A requires; it is not part of the six built items.

This order replaces the earlier PBD phases and their date/invite sequencing. Decisions A to K are unchanged; enabling a switch depends on its completed readers, not on an outside event.

---

## 5. User2, User3 and User4 follow the same template

These are the migration effects recorded by the pre-build audit. All of it has since shipped (live 2026-10-19), and the Public switches did not require moving any collection data.

- **No config change.** Role and space stay as they are. Without a family flag, they're members exactly like User5.
- **What they lose:** home's decks, products, matchups, field and runs, which they see today, plus each other's decks and User5's. Each has one built Commander deck, so their field shows "No opponents" (PBD:110) until home makes its decks public. **K, decided (Matt, 2026-10-18), as recommended:** home's decks stay private on migration day, as PBD's rollout says, and Matt switches them on if he wants. Public would show them to User5 too.
- **Access:** they come in only through decklab.example.com, at home too (E10-S35, built 2026-10-18; the chooser no longer offers them). Each needs their email in the Access policy to get in at all; whether all three are there isn't recorded here, so Matt checks.
- **Their own switches start private.** Tell them that making their decks public is their choice.
- **Admin:** Matt stops seeing their collections, decks, games and Activity on the page; upkeep goes through Claude.
- **Data:** nothing to migrate. There are no play records and no variant tests, and the Forge results are all home-only (PBD:115, 294). Wishlists are unchanged.

**Docs to update as this ships:** PBD §1 ("public" for "visible to the family", and decision A); its build order (§4 here); [personas.md](personas.md) (User5 as the member persona); AGENTS.md, "Spaces" and "Private by default" (public/private, User5, the template).
