# Deck Lab personas

> **Dated 2026-10-13.** Part of Deck Lab's design set: [README.md](README.md) (method and index), personas (this file), [journeys.md](journeys.md), [stories.md](stories.md) and [gap-analysis.md](gap-analysis.md). The deck states, page names and permissions below describe Deck Lab on that date. Matt's answers to the open questions, given the same day, are worked in as facts sourced "Matt, 2026-10-13" and listed under [Answered 2026-10-13](#answered-2026-10-13). Updated 2026-10-18 for the member template ([member-template.md](member-template.md)): User5 joins as the member persona, "visible to the family" becomes **public** (read-only to everyone signed in), and Matt's decisions A to K are under [Answered 2026-10-18](#answered-2026-10-18). Updated 2026-10-19 to match [stories.md](stories.md): private by default, the Public / Private switches and member departure are built and live (migrations 0012 and 0013 applied 2026-10-19), nothing is switched Public yet, and gaps that have since been built are marked so.

## What a persona is here

A persona is a short description of one kind of person (or actor) that Deck Lab is built for, or deliberately not built for. It sums up who they are, what they want from Deck Lab, what gets in their way and what that means for the pages. The [user stories](stories.md) and [journeys](journeys.md) are written for these personas, and the [gap analysis](gap-analysis.md) checks Deck Lab against them.

These personas aren't composites of interviewed strangers. Deck Lab has a handful of real users, the household plus a few members (User5 since 2026-10-18), so each human persona is a real person or a small group of real people, and the anti-personas are kinds of user Deck Lab turns away on purpose.

### How they were built

1. **Code and docs readers** went through the repo: `CLAUDE.md`, [PLAN.md](../PLAN.md), [HISTORY.md](../HISTORY.md), [UI-REVIEW.md](../UI-REVIEW.md), [UI-KIT.md](../UI-KIT.md), [README.md](../README.md), `decklab/config.json`, `decklab/lib/permissions.py`, `decklab/lib/api/guard.py` and the other modules cited below, plus `python -m decklab.db deck list` and the git history. These give the roles, permissions, decks and what each page can and can't do.
2. **Owner notes**: what Matt has said in earlier sessions about how Deck Lab is used.
3. **A three-lens critique** of the drafts: one lens checked each claim against its source, one looked for assumptions passed off as facts, and one checked that every design implication could be tested and that the two primary personas' needs were settled where they clash.

### Facts and assumptions

Each persona keeps two separate lists:

- **Facts** have a source: a file (with a line range where it helps), a command's output, a commit, "owner notes" for something Matt said in earlier sessions, or "Matt, 2026-10-13" (and "Matt, 2026-10-18") for his answers to this model's open questions. Facts about User1 or the other members sourced to Matt are his view of them, not their own words.
- **Assumptions** are anything not yet confirmed: likely habits, devices nobody has named, how often someone uses Deck Lab. They are there to be checked, and the [open questions](#open-questions-to-validate-with-matt) at the end list the ones that matter most; those already answered are under [Answered 2026-10-13](#answered-2026-10-13).

Elsewhere in each persona, goals, frustrations and behaviours that are assumptions say so. Each quote is **illustrative**: written to sum the persona up, not something the person said.

## All personas

| Persona | Kind | In one line |
|---|---|---|
| [Matt, the deck builder and buyer](#matt-the-deck-builder-and-buyer) | Primary | Builds decks from the shared pool, decides what to buy, and runs Deck Lab as the admin. |
| [User1, the themed-deck player](#user1-the-themed-deck-player) | Primary | Plays Tolkien- and Stardew Valley-themed decks against Matt; edits her own decks and wishlist on her phone. |
| [User5, the member](#user5-the-member) | Secondary | The first real member; his setup is the template for every member. Tunnel only, everything private to start. |
| [User2, User3 and User4, the person-space members](#user2-user3-and-user4-the-person-space-members) | Secondary | Members with their own space, collection and Commander deck each; on the same terms as User5; occasional users at most, on phones. |
| [The Commander-night table](#the-commander-night-table-served-persona) | Supplementary (served) | The players at a social Commander night who face the decks Deck Lab helps build, but never open it. |
| [Claude Code, the command-line operator](#claude-code-the-command-line-operator) | Non-human actor | The AI assistant on Matt's PC that does most inventory, order and deck work through `python -m decklab.db`. |
| [The value collector](#the-value-collector-anti-persona) | Anti-persona | Collects cards as assets; Deck Lab tracks no value, spending or price history. |
| [The tournament grinder](#the-tournament-grinder-anti-persona) | Anti-persona | Tunes for a sanctioned metagame; Deck Lab ignores legality for casual decks. |
| [The stranger on the internet](#the-stranger-on-the-internet-anti-persona) | Anti-persona | Anyone not invited; Deck Lab has no pages open to the internet. |

---

## Matt, the deck builder and buyer

**Kind:** primary

### Summary

Newer Magic player who collects only to play physical cards. His main job in Deck Lab is building and refining decks from the shared pool and deciding which cards to buy for them at Australian shops. He also plays the decks at home and, as the household's admin, keeps Deck Lab running (operator duties, noted separately below). Most bulk work reaches the database through Claude Code at the PC; he checks the result on Deck Lab's pages.

### Role in Deck Lab

Profile `matt`, role `admin`, home space, `plays_as` `user`. He edits everything at home, but not User1's accessories or anyone else's wishlist (`permissions.accessory_owners`; wishlist privacy). Under private by default ([privacy-by-default.md](privacy-by-default.md), [member-template.md](member-template.md); built 2026-10-18, live since 2026-10-19) the admin role doesn't open another space on the page: he reads a member's collection, decks or games only if they make them **public** (read-only to everyone signed in), writes only in home, and asks Claude for upkeep in their spaces. Nothing is switched Public yet. When he passes on a member's request to Claude, that counts as the owner asking, for upkeep only, and Claude reports counts and "done" to him, never the contents (decision D). He picks the simulations setting on Settings (`#/settings`) and may stop any run, shown to him anonymously if he can't see its decks.

His main role, and the pages it governs:

- **Buyer and builder:** the editor, Shopping (`#/shopping`), Matchups and Test this change, on the iPad and the QHD PC.
- **Player:** the library and the deck page, which he shares with User1 (see the surface ownership rule under design implications).

Operator duties (the server and tunnel, which start at his logon since 2026-10-13, nightly backups, Forge upkeep, Settings) are served by the command line and Settings, not by the everyday pages, and don't drive their design.

### Background

Australian, thinks in AUD. Plays casual 60-card 1v1 at home with User1 from a shared pool, with Commander at a local shop's social nights as the next step. No home deck is built yet. His decks on 2026-10-13: Izzet Otters (casual, building), Gruul Ramp (casual, idea), Finneas, Ace Archer (Commander, building) and Alela Faeries (Commander, idea, Bracket 2). The only thing kept intact at home is the Lightning Aggro product.

### Goals

- **Primary end goal:** build decks that are strong and fun in 1v1 from the shared pool first, and buy only the cards that improve a deck most per dollar, at Australian shops that have them in stock.
- **End goal:** share postage by topping up any shop order from the watchlist, long-term rows included.
- **End goal:** know quickly how far each deck is from being playable, and where the missing cards are (storage, another deck, on the way, to buy).
- **End goal:** get Commander decks ready for the social nights, aiming for Bracket 2 (Matt, 2026-10-13). In progress: Finneas, Ace Archer (building) and Alela Faeries (idea, Bracket 2, buys queued long-term).
- **End goal:** change the purchase queue and record orders on the pages himself, not only through Claude at the PC (Matt, 2026-10-13).
- **End goal:** decks strong enough to enjoy games against more experienced players.
- **Experience goal:** Deck Lab shouldn't feel clunky (his word about the old UI); answers first, details on request.

### Frustrations

- **Stated:** the old Deck Lab UI felt "clunky and ugly", which led to the 2026-10-13 redesign.
- **Stated:** he doesn't want spending tracked or to be asked what he paid.
- **Gap (assumption):** Deck Lab's prices are converted US estimates, while he judges deals only against Australian in-stock prices.
- **Gap:** orders and watchlist edits were command-line only, so they needed Claude at the PC. He wanted to change the queue (state, quantity, remove, add) and record orders on the pages himself (Matt, 2026-10-13). Built: E5-S06, E6-S02.
- **Gap:** the Sleeves picker and `deck push` refused a sleeve design another deck or intact product had, but he wants one design usable by several decks (Matt, 2026-10-13). Built: E8-S20.
- **Gap:** every command-line write was recorded as Claude's, even one he ran himself; he wanted his own shown as his on Activity (Matt, 2026-10-13). Built: E11-S07 (`--actor`).
- **Gap (assumption):** after a collection, token or receipt change made outside a deck save, no page lists the decks whose tables are now out of date. (After a page save the editor does list them with **Update their tables**, and `deck list` / `deck tables --check` list them on the command line.) Built 2026-10-13 (E7-S09): the Decks page's Tables out of date list, with Update all.
- **Gap (assumption):** unsaved drafts stay on the device they were started on.
- **Gap (assumption):** Forge's AI misplays some decks and cards, so how far to trust a verdict isn't obvious.
- **Gap (assumption):** a Test this change result isn't linked to the card's price or the watchlist.

### Behaviours

- Hands bulk work (orders, receipts, deck rewrites, buylist research) to Claude Code at the PC and reviews the outcome on the pages.
- Buys singles from several shops and keeps long-term plans in the watchlist so orders can share postage.
- Uses Forge matchups, the field view and Test this change to judge decks and swaps.
- Cares about card art in some decks.
- Deck Lab starts when he logs on to the PC (turned on 2026-10-13 at his request); before that he started it by hand.
- Uses several devices across the day.

### Devices and context

A phone, a tablet, a laptop, and a Windows PC with QHD monitors (owner notes). The PC hosts Deck Lab, Postgres and Forge, so Deck Lab is reachable only while the PC is on and he has logged on (the server starts at logon since 2026-10-13). The PC stays logged on while it's on, so in practice it's reachable whenever the PC is on (Matt, 2026-10-13). When it's off, a plain "Deck Lab is off" message is enough for him (Matt, 2026-10-13). He reaches it on the home network (port 8642) or at decklab.example.com behind Cloudflare Access.

Contexts: at the PC with Claude for building and buying; on a tablet for editing; on the phone in a shop or at the table (the last is an assumption).

### Skill level

- **Magic:** newer player.
- **Tech:** comfortable with the PC, the command line through Claude, and running the server; a heavy multi-device user.

### Illustrative quote

> *Illustrative, not a real quote:* "How many cards is Izzet Otters short, and which one is worth buying?"

### Facts

| Claim | Source |
|---|---|
| Australian; thinks in AUD. | owner notes |
| A newer player. | owner notes |
| Collects Magic only to play, with physical cards; no MTG Arena. | `AGENTS.md` ("What each game is for"); owner notes |
| Doesn't want spending or budget tracked and doesn't want to be asked what he paid. | owner notes; `AGENTS.md` ("No budget tracking") |
| Judges deals only against Australian in-stock prices; converted US prices and out-of-stock listings aren't benchmarks. | owner notes |
| Keeps long-term buying plans in the watchlist (`long_term` state) to share postage across shop orders. | owner notes; `AGENTS.md` ("Share postage") |
| The only admin profile; home space; `plays_as` `user`. | `decklab/config.json`; `decklab/lib/permissions.py` |
| Found the old Deck Lab UI clunky and ugly, which led to the 2026-10-13 redesign. | owner notes; [HISTORY.md](../HISTORY.md) ("UI redesign (2026-10-13)"); [UI-REVIEW.md](../UI-REVIEW.md) |
| No home deck is built yet. His decks: Izzet Otters (casual, building), Gruul Ramp (casual, idea), Finneas, Ace Archer (Commander, building), Alela Faeries (Commander, idea). The only thing kept intact at home is the Lightning Aggro product. | `python -m decklab.db deck list` (2026-10-13) |
| Alela Faeries targets Bracket 2, with its buys queued as long-term. | commits 57c0a12 and 13741bb; `magic/reports/2026-10-10-dimir-commander-options.md` |
| Most inventory, order, deck and buylist work runs through `python -m decklab.db` commands operated by Claude Code. | owner notes |
| Wants to change the purchase queue (state, quantity, remove, add) and record orders on the pages himself, not only through Claude at the PC. | Matt, 2026-10-13 |
| Wants his own command-line writes shown as his on Activity, separate from Claude's. | Matt, 2026-10-13 |
| Thinks the household will aim for Bracket 2 at Commander nights. | Matt, 2026-10-13 |
| One sleeve design should be usable by several decks; it's up to the players not to play two decks in the same sleeves against each other. This reversed the old one-holder rule; E8-S20 built it. | Matt, 2026-10-13; [stories.md](stories.md), E8-S20 |
| Orders shouldn't get an expected arrival date; naming the order is enough. | Matt, 2026-10-13 |
| When the PC is off, a friendly "Deck Lab is off" message is enough; cached deck lists aren't wanted. | Matt, 2026-10-13 |
| Deck Lab starts at his logon since 2026-10-13 (`homenet install --at-logon`). | Matt, 2026-10-13; `python -m decklab.lib.homenet status` (2026-10-13) |
| The PC stays logged on while it's on, so it is either logged on or off; the nightly backup needn't run without a logon (it catches up after the PC was off). | Matt, 2026-10-13; `decklab/db/schedule.py:79` (StartWhenAvailable) |
| As admin, needs usage visibility: whether members use Deck Lab and which pages they open, as evidence for which features are worth building. | Matt, 2026-10-13; built the same day (E10-S25) |
| Forge results don't need backing up; they can be regenerated. | Matt, 2026-10-13 |

### Assumptions

- He reaches for the phone more than the iPad when in a shop or away from home.
- He values simulation evidence over written opinion when deciding a swap (suggested by PLAN.md's "No AI-written evaluations" goal, not stated by him).
- Whether he reads Activity (`#/activity`) to see what Claude changed is unknown.

### Design implications

- **Surface ownership (tie-break between the two primaries):** the library and the deck page on the phone follow User1's needs (plain verdict, card pictures, How to play); the editor, Shopping, Matchups and Test this change on the iPad and QHD follow Matt's (dense numbers allowed); each Wishlist follows its owner. Where the phone deck page and Matt's needs conflict, the verdict and pictures come first and numbers go behind a disclosure.
- **Check:** on a phone viewport (393 px wide), the deck page shows the readiness verdict and the count of missing cards without scrolling.
- **Check:** every buy suggestion shows `listed_aud`, the shop and the checked date; no converted Scryfall price appears without the word "estimate" and its rate date.
- **Check:** no page shows spend totals, price-paid fields or "you have spent" summaries.
- **Check:** from a shop name, one view lists every watchlist row (`long_term` included) last seen in stock there.
- **Check:** after any collection, token or receipt change, one place lists every home deck whose table is out of date, with Update all. (Met 2026-10-13, E7-S09.)
- **Check:** every Forge verdict shows games played, a confidence range and any cards in the deck known to be misplayed by Forge.
- **Check:** a Test this change result for a card not owned offers "queue to watchlist" with its AU reference price when one is recorded.
- **Check:** Matt can pick any deck he may see as an opponent in a matchup: home's, or a member's once that member makes their decks public (E10-S31; nothing is public yet).
- **Check:** Claude's changes and Matt's own changes are distinguishable in Activity (decided; met, E11-S07).
- **Check:** on the iPad or QHD, Matt can change a queue row's state and quantity, add and remove rows, and record an order with its fulfilled rows, without the command line (decided; met, E5-S06, E6-S02).
- **Check:** choosing a sleeve design another deck or intact product already uses is accepted on the page and by `deck push`, and `accessories check` doesn't report it (decided; met, E8-S20). At most, a note when two decks in the same sleeves are packed together (the Packing plan has one).
- **Check:** with the PC off, decklab.example.com shows a plain "Deck Lab is off" message, not a generic failure (E11-S02). No cached deck lists.
- "On the way" shows the order a card is on, never an expected arrival date.

---

## User1, the themed-deck player

**Kind:** primary

### Summary

Co-owner of the shared card pool. She plays Tolkien- and Stardew Valley-themed decks in casual 1v1 games at home with Matt. She edits the decks Played by her and her own wishlist. She uses Deck Lab on her phone (Matt, 2026-10-13), so she is primary for its phone surfaces: the deck page, the library, her Wishlist, the Packing plan and the Game log on a phone. Matt doesn't think she uses Matchups or Stats, so those, and Forge generally, are Matt's surfaces. Her own view hasn't been asked yet.

### Role in Deck Lab

Profile `user1`, role `member`, home space, `plays_as` `wife`.

Through decklab.example.com (Cloudflare Access email one-time code) she may change:

- decks Played by `wife` (not `either` decks, which count as Matt's);
- her wishlist;
- her own and shared accessories;
- her settings, and play records involving her decks;
- home's collection and tokens, as Matt can (decision J, E10-S43, built 2026-10-18).

She may see Shopping, Receive delivery and the Packing plan, but may not receive deliveries or place orders.

On the home network her writes follow the picked profile's permissions, as through the tunnel, with scripts naming nobody still passing (Matt's decision of 2026-10-13, E10-S03, built the same day). Starting Forge runs follows the admin's simulations setting by role everywhere: she can start runs only when that setting is Everyone.

### Background

A second home player, newer to Magic. She shares the card pool with Matt and plays casual 60-card 1v1 at home. Her decks on 2026-10-13: The Free Peoples (casual 60, Tolkien, building) and Gandalf and the Valley (Commander, Tolkien plus Stardew Valley, green-blue, building).

### Goals

- **End goal:** play enjoyable games against Matt with decks whose theme and art she likes.
- **End goal:** know how close her decks are to ready, and which order the cards she's waiting for are on (orders won't get an expected arrival date; Matt, 2026-10-13).
- **End goal:** tweak her own decks, on her phone.
- **End goal:** say which cards she'd like without running the buying process herself. Matt agrees she should be able to ask from the page, with him approving, though she'd probably also just say it in person (Matt, 2026-10-13).
- **Later goal** (reported by Matt as a joint view, owner notes): play Commander at a social Commander night with a deck that's fun to bring.

### Frustrations

These are gaps that may affect her. They are assumptions, not reported by User1.

- The real-device pass isn't finished on her phone (E2-S22, partial). Quick edit's missing Notes, header details and Paste a list are built (E2-S05, 2026-10-15).
- Her wishlist has no path to "please buy this" on the page (wanted, not urgent: E5-S15).
- Starting a matchup depends on the admin's simulations setting, and there's no way to ask for a run. Matt doesn't think she uses Matchups, so this matters little (a could).
- Until 2026-10-18 she couldn't change home's collection or tokens on the page, only an admin could; found by that day's audit and fixed the same day (E10-S43).

### Behaviours

- Uses Deck Lab on her phone (Matt, 2026-10-13).
- Doesn't use Matchups or Stats, as far as Matt knows (Matt, 2026-10-13).
- Has used the Wishlist page (owner notes; audit trail).
- Plays casual 1v1 at home with Matt. Both her decks are still being built, so games so far use in-progress decks, other pool decks or stand-ins (how exactly is an assumption).
- Her decks are themed: The Free Peoples (Tolkien) and Gandalf and the Valley (Tolkien and Stardew Valley).

### Devices and context

Uses Deck Lab on a phone (Matt, 2026-10-13). Which phone, and whether she also uses a tablet, are still to be asked. Uses Deck Lab at home and, through decklab.example.com, away from home.

Contexts: before a game, checking her deck's missing cards; adding to her wishlist.

### Skill level

- **Magic:** newer player (assumption for design).
- **Tech:** everyday phone user (assumption).

### Illustrative quote

> *Illustrative, not a real quote:* "How close is The Free Peoples, and when do the new cards come?"

### Facts

| Claim | Source |
|---|---|
| Second home player; newer to Magic; plays casual 60-card 1v1 at home. | owner notes |
| Shares the card pool with Matt; each deck records who plays it. | `AGENTS.md` ("Shared collection") |
| Member role in the home space, `plays_as` `wife`. | `decklab/config.json` |
| A member at home may change decks Played by her `plays_as`, not `either` decks, and (since E10-S43) home's collection and tokens; receipts, products and orders are admins'. A home-network request has the picked profile's rights, as through the tunnel. | `decklab/lib/permissions.py`; `decklab/lib/api/guard.py`; [stories.md](stories.md), E10-S03 and E10-S43 |
| Her decks: The Free Peoples (casual 60, Tolkien, building) and Gandalf and the Valley (Commander, Tolkien plus Stardew Valley, green-blue, building). | `python -m decklab.db deck list` (2026-10-13); owner notes |
| Reaches Deck Lab from outside via a Cloudflare Access email one-time code. | owner notes; [README.md](../README.md) ("From outside the home") |
| Has used the Wishlist page. | owner notes; audit trail |
| Sees and changes only her own and shared accessories; Matt doesn't see hers. | `decklab/lib/permissions.py` (`accessory_owners`); `AGENTS.md` ("Accessories") |
| Uses Deck Lab on her phone. | Matt, 2026-10-13 |
| Doesn't use Matchups or Stats, as far as Matt knows. | Matt, 2026-10-13 |
| Should be able to ask from the page for a card to be bought or a Forge run, with Matt approving; she'd probably also just say it in person. | Matt, 2026-10-13 |
| Teaching rules and play in Deck Lab should be minimal; products like the Beginner Box do that. | Matt, 2026-10-13 |
| Home's collection and tokens are hers and Matt's alike, so she should edit them as he can (E10-S43). | Matt, 2026-10-18 (decision J) |

### Assumptions

- Matt's answers about her devices and habits are his view; she hasn't been asked herself.
- She chooses some printings for their art (suggested by her themed decks; not recorded).
- How often she'd use an ask-to-buy or ask-for-a-run button rather than just telling Matt is unknown.

### Design implications

- **Basis:** member permissions, themed decks, wishlist use, and (Matt, 2026-10-13) phone-first use without Matchups or Stats. Her phone surfaces come first: the phone deck page, the library, her Wishlist, the Packing plan and recording a game on the Game log. Stories about Matchups, Stats and Forge for her are low priority (could) or belong to Matt.
- **Check:** a newer player can tell, without help text, whether her deck is ready and what's missing, on a phone viewport without scrolling.
- **Check:** she can finish any edit to her own deck on her phone, notes and header details included (E2-S05).
- **Check:** she can turn a wishlist card into a purchase request in 3 taps or fewer, landing in Matt's queue for him to approve, without watchlist rights (wanted, not urgent: E5-S15).
- **Check:** "on the way" cards on her deck page name the order and its status; no expected arrival date.
- **Check:** packing on her phone while Matt uses another device keeps both devices on the same progress (E4-S02, raised to should), and recording a game on a phone takes one tap (E4-S11).
- **Check:** a Commander deck's bracket verdict is in plain words a beginner can repeat at the table.
- **Check:** signed in as User1, she can add, change and remove home's collection and token cards on their pages, as Matt can (decided 2026-10-18; met, E10-S43).
- Choosing a printing for its art is in scope (`exact`-printing watchlist rows, the printing picker); tracking a printing's value isn't (see [the value collector](#the-value-collector-anti-persona)).
- Keep beginner wording: Planned list and Play-now list, plain verdicts, no jargon without an explanation. Keep teaching minimal: the in-context help that exists (How to play from the deck's Notes, the card viewer's rules text) stays, but no rules glossary or lessons (E4-S07 not wanted).

---

## User5, the member

**Kind:** secondary

> **Added 2026-10-18** with the member template ([member-template.md](member-template.md)). Little is known about User5 yet, so most of this persona is the template's rules plus assumptions to check once he has used Deck Lab.

### Summary

A member about to be invited, and likely to really use Deck Lab: the first member who will (Matt, 2026-10-18). He uses only decklab.example.com, never the home network. Everything in his space starts private, and only he can make parts of it public. **His setup is the template for every member**: the other members move onto it with no config change, and every later member gets it too. His stories are mostly privacy ones, and those are musts.

### Role in Deck Lab

Profile `user5` (shown as User5), role `member`, his own space `user5` (deck ids like `user5/casual/...`). He edits his own collection, tokens, decks, Game log records and wishlist.

- **What he has:** his collection, token cards and raw imports; his decks with their history; the Game log records where one side is his deck; his wishlist and settings; Forge results made only of his own decks. No orders, products, watchlist, accessories, Packing plan or Commander-night notes, which stay home-only.
- **What he sees of others:** nothing, unless its owner made it public. A hidden thing looks the same as a missing one: no id, title, count or "who". The roster shows him only himself, profiles whose space has something public, and the admin's display name for "ask Matt" wording (decision C, E10-S38).
- **What others see of his:** only what he made public, read-only. Matt as admin gets no read or write override on the page (E10-S29, shipping before the invite, decision I). Matt keeps the system role: the simulations setting, Settings, Visits and stopping runs.
- **Upkeep:** when User5 asks Matt and Matt asks Claude (a merge, a precon), that counts as User5 asking, for upkeep only; Claude reports counts and "done", never the contents, and never changes his switches (decision D).
- **Simulations:** he sees only the mode and a reason without names (decision F). He may stop a run only if he started it or one of its decks is his own (E10-S31).
- **Mixed games:** in a record with his deck on one side, he edits only his own side; the result and notes stay with the space that recorded it, and he can name an opponent deck only if it's public or his own (decision G, E10-S32).
- **Visits:** Matt sees which days he came in and which pages he opened; the invite says so (decision E).
- **Switches:** he makes his collection, decks or games Public on Who sees what, in the avatar menu (E10-S28). Each starts Private.
- **Leaving:** `space export` and `space remove` give him his data and remove his space in one audited change (decision H, E10-S40).

All of this is built: what he'd meet first shipped before the invite on 2026-10-18, and the switches, full Forge rules and leaving the same day, live since 2026-10-19 ([member-template.md](member-template.md), section 4). Nothing is switched Public yet, and no member has left.

### Background

A member with his own space. Nothing more is recorded about him: his Magic experience, his collection and whether he plays with Matt are unknown.

### Goals

These are assumptions until he has used it.

- **End goal (assumption):** keep his own collection and decks in Deck Lab and use its deck tools on them.
- **End goal (assumption):** decide for himself what, if anything, others see.
- **Experience goal (assumption):** not be shown anyone else's data, names or pages that don't apply to him.

### Frustrations

These are gaps that may affect him (assumptions), from the 2026-10-18 audit.

- At the 2026-10-18 audit he'd have seen every space's decks, matchups, history and products, the profile roster, and could stop anyone's Forge runs ([member-template.md](member-template.md), section 3). All of that was fixed before the invite (E10-S29, E10-S30, E10-S38, with E10-S31 after it).
- His space starts empty: cards go in by import, or a precon through Claude (`collection add-precon --space`, E10-S36, built 2026-10-18).
- With nothing public anywhere yet, he has no opponents for a field run or a game against another space's deck.

### Behaviours

- Likely to really use Deck Lab (Matt, 2026-10-18); how often, and on which pages, is unknown. Visits will show it.

### Devices and context

Only through decklab.example.com, behind Cloudflare Access with his email (Matt, 2026-10-18). Never on the home network, and the home chooser doesn't offer him (E10-S35, built 2026-10-18). Which devices he uses is unknown.

### Skill level

- **Magic:** unknown.
- **Tech:** unknown.

### Illustrative quote

> *Illustrative, not a real quote:* "Who can see my decks?"

### Facts

| Claim | Source |
|---|---|
| The first real member, likely to really use Deck Lab. | Matt, 2026-10-18 |
| Profile `user5`, name User5, role `member`, space `user5`, with one email. | `decklab/config.json`; commits 949004c and cd2c6a6 |
| His space has no decks yet. | `python -m decklab.db deck list --space user5` (2026-10-18) |
| Uses only decklab.example.com, never the home network. | Matt, 2026-10-18 |
| Sees only what Matt chooses to show him; everything in an account is private by default, and its owner can make it public. | Matt, 2026-10-18 |
| His setup is the template for every member; the other members move onto it with no config change. | Matt, 2026-10-18; [member-template.md](member-template.md), section 5 |
| Decks are private to their space: `guard.sees_deck` checks the viewer, and a hidden deck answers as a missing one. Until 2026-10-18 every deck was readable by any profile. | [stories.md](stories.md), E10-S30; [member-template.md](member-template.md), section 3 |
| Through the tunnel, the profile comes from a verified Access token; the viewer header, `?profile=` and a body `profile` are replaced by the login's. | `decklab/lib/access.py`; `decklab/lib/server_http.py` |
| The home chooser offers only Matt and User1; a home-network request naming him gets 403 "Sign in through decklab.example.com". | [stories.md](stories.md), E10-S35 |
| Everything in his space starts Private; nothing has been switched Public yet. | [stories.md](stories.md), E10-S28 (live 2026-10-19) |

### Assumptions

- He'll keep a real collection and decks in his space (rather than only browsing).
- He'll want some of it public eventually; until then nobody sees it.
- He'll ask Matt for upkeep (scans, precons), which Matt then passes on to Claude.
- Whether he plays Magic, and at what level, is unknown.

### Design implications

- **Priority:** the template's privacy stories are musts. All are built (2026-10-18; live since 2026-10-19); only per-deck public (E10-S41, could) waits until someone asks.
- **Check:** signed in as User5 with no public switches anywhere, every route in the audit's route table answers a missing thing (404 or empty) for another space's data, and no answer names another space, deck, profile or Forge side.
- **Check:** signed in as User5, `GET /api/profiles` lists only his own profile, plus the admin's display name (E10-S38).
- **Check:** as User5, stopping a run is refused unless he started it or one of its decks is his own (E10-S31).
- **Check:** the page's JavaScript contains no profile names, real deck titles or results, and a grep test keeps it so (E10-S39).
- **Check:** Matt, signed in as admin, gets a missing-thing answer for User5's collection, decks, Game log and Activity on the page (E10-S29).
- Word everything Public / Private. Public means read-only to every signed-in profile behind Cloudflare Access, never the open internet: there are still no open pages, share links or sign-up (see [the stranger](#the-stranger-on-the-internet-anti-persona)).
- Don't build features justified only by him until he asks; read Visits first.

---

## User2, User3 and User4, the person-space members

**Kind:** secondary

### Summary

Members, each with their own space holding their own collection and decks. They range from an experienced player (User2) to members about whom little is known (User3 and User4). Each space so far holds one precon's cards and one built Commander deck, entered by Matt. Matt expects occasional use at most, mostly on phones (Matt, 2026-10-13). They are served by the primary interface plus privacy and own-space editing, and their stories rank below Matt's and User1's. Since 2026-10-18 they are members exactly like [User5](#user5-the-member), on the same template, with no config change; the template's rules apply to them as written there.

### Role in Deck Lab

Profiles `user2`, `user3` and `user4`, role `member`, each with their own space (deck ids like `user2/commander/...`). Each edits their own collection, tokens, decks and wishlist.

- Under private by default ([privacy-by-default.md](privacy-by-default.md); built 2026-10-18, live since 2026-10-19) they see only their own space, plus whatever another space makes **public** (read-only to everyone signed in). Nothing is public yet, so they see no home decks, no other member's decks and none of User5's, and never home's Shopping, Receive delivery, Packing plan or anyone's sleeves and boxes. Their own spaces are private from Matt too. Home's decks stayed private when they moved onto the template (decision K).
- They can start Forge runs only when the admin's simulations setting is Everyone.
- Their spaces have no orders, products, watchlist or accessories.
- They see only the games and sideboard plans with one of their own decks on the Game log, not the household's (Matt, 2026-10-13; E10-S24, E10-S32).
- A person's deck's Forge field is its own space's decks plus public ones (E10-S31). With nothing public, a member's single deck has no opponents.
- Matt sees whether they visit and which pages they open, on the Settings page's Visits panel (E10-S25, built 2026-10-13). Only page opens are recorded (the day, home or remote, the page, and a deck's id), and only admins see them.

### Background

User2 is an experienced player. Little is recorded about User3 and User4 beyond their spaces. Each space's contents were entered by Matt from a precon list.

### Goals

- **End goal:** keep their own cards and decks separate from the household's.
- **End goal (assumption):** look at their own deck, and the household's decks, before games against them. (Under the privacy decision, the household's decks only once home makes them public, E10-S30.)
- **Experience goal (assumption):** enter cards without typing each one, and not be shown pages that don't apply to them.

### Frustrations

These are gaps that may affect them (assumptions).

- Older or unusual cards may need care to match exact Scryfall printings on import.
- Activity may be mostly empty for them, and so may the Game log, which shows only their own decks' games (E10-S24, built 2026-10-13) and stays in their navigation.

### Behaviours

- Matt expects occasional use at most (Matt, 2026-10-13).
- Each space's contents were entered by Matt from a precon list.

### Devices and context

Mostly phones, if they use it at all (Matt, 2026-10-13); which phones is unknown. They reach Deck Lab only through decklab.example.com with an email one-time code, at the household too, as User5 does; the home chooser doesn't offer them (E10-S35, built 2026-10-18).

### Skill level

- **Magic:** User2 experienced; User3 and User4 unknown.
- **Tech:** unknown.

### Illustrative quote

> *Illustrative, not a real quote:* "Where are my decks?"

### Facts

| Claim | Source |
|---|---|
| User2 is an experienced player. | owner notes |
| User2, User3 and User4 each have their own space. | `decklab/config.json` |
| Each of their spaces holds one precon's cards and one built Commander deck, entered by Matt from a precon list. | `python -m decklab.db deck list` |
| A person's deck's Forge field is its own space's decks plus the decks of spaces whose decks are public; a home deck's field is home's. | [stories.md](stories.md), E10-S31 |
| Members in their own space can't see home's inventory, Shopping, the Packing plan or accessories. | `decklab/lib/permissions.py`; `AGENTS.md` ("Who may read the inventory") |
| Likely to use Deck Lab rarely, and mostly on phones if at all. | Matt, 2026-10-13 |
| Shouldn't see the household's Game log. Since 2026-10-13 `GET /api/play` sends them only the games and plans with a deck of their own space. | Matt, 2026-10-13; `decklab/lib/permissions.py` (sees_play_record); `decklab/lib/api/play_records.py` (play_overview) |
| Move onto User5's member template with no config change; home's decks stay private on that day, and Matt makes them public if he wants. | Matt, 2026-10-18 (decision K); [member-template.md](member-template.md), section 5 |
| An admin needs usage visibility, to judge which features are worth building for them. Their use is visible to Matt on Settings, Visits: first and last seen, days visited and pages opened, or "not seen yet". | Matt, 2026-10-13; `decklab/lib/visits.py`; `decklab/web/settings.js` (E10-S25) |

### Assumptions

- A member may own old or powerful cards, and their real collection may be much larger than what's recorded.
- A member would import a collection-app export (ManaBox and others) if they catalogue older cards.
- Whether they sign in at all, and whether User3 and User4 play regularly and with whom, is unknown. Settings, Visits will now show whether they sign in (E10-S25).
- They may prefer someone else enters their cards.

### Design implications

- **Priority:** their stories rank below Matt's and User1's (mostly should or could), except privacy, which stays a must. Their privacy checks are User5's (see [User5's design implications](#user5-the-member)); nothing is built separately for them.
- **Check:** as one of these members, `#/play` and `GET /api/play` return only games and plans with a deck in their space (E10-S24, built 2026-10-13).
- **Check:** a member with one deck and no tokens lands on that deck on a phone, and the navigation hides Game log, Activity and other pages that are empty for them.
- **Check:** importing a 5,000-row ManaBox export finishes, and its preview lists unmatched rows grouped by set before anything is applied (E7-S02, lowered to should).
- Design their pages for a phone first; don't build tablet-only tools for them.
- Don't add features justified only by these members (such as a field within a person's space or a compact list view) until one of them asks.
- Read Settings, Visits before deciding anything for them: which pages they open is the evidence their stories have lacked (E10-S25).

---

## The Commander-night table (served persona)

**Kind:** supplementary

### Summary

The other players at a social Commander night at a local game store: staff-made pairings into pods, with a published bracket range. Not every venue publishes one. The household aims for Bracket 2. These players never open Deck Lab, but every Commander deck Deck Lab helps build lands on their table, so their experience shapes the bracket and table-fun rules.

### Role in Deck Lab

None. No profile, no access. Affected only through the decks Matt and User1 bring.

### Background

A social bracket night at a shop, played in timed rounds.

### Goals

- **Assumption:** games where every deck in the pod is near the same power.
- **Assumption:** a beginner-friendly social atmosphere, consistent with a social bracket night.

### Frustrations

- **Assumption:** a deck far above or below the pod's bracket, or one that is un-fun to face (mass land denial, extra turns, long solo turns).

### Behaviours

- Plays timed rounds in staff-made pods.

### Devices and context

A shop's play area; four-player pods; no Deck Lab.

### Skill level

Mixed, from beginners to experienced (assumption).

### Illustrative quote

> *Illustrative, not a real quote:* "What bracket is your deck?"

### Facts

| Claim | Source |
|---|---|
| A social Commander night at a local game store: a published bracket range, staff-made pairings, timed rounds. | owner notes; Matt, 2026-10-13 |
| Matt and User1 will aim for Bracket 2 at Commander nights (Matt's expectation). | Matt, 2026-10-13 |
| Other venues may not publish a bracket range. | Matt, 2026-10-13 |
| Matt and User1 see it as a beginner-friendly next step and want Commander decks fun for the table at a social bracket. | owner notes |
| The Commander ban list and the current Commander Brackets and Game Changers list apply to these decks. | `AGENTS.md` ("Later: Commander") |
| Deck Lab's Commander check reports a minimum bracket with reasons: the Game Changers, mass land denial and extra-turn cards it found (from Scryfall's oracle tags), or "none", and since 2026-10-21 any two-card combo from Commander Spellbook's list. It doesn't check tutors, longer combos or intent. | `decklab/lib/stats/commander.py:24-34, 256-300` |
| Deck Lab simulates 1v1 Commander on the page; 4-player pods are command-line only, and "fun for the table" isn't measured. | [PLAN.md](../PLAN.md) (lines 22, 235) |

### Assumptions

- The table's preferences, the shops' house rules and the bracket most pods actually play aren't verified.

### Design implications

- **Check:** a Commander deck's bracket check is judged against the household's Bracket 2 target (a new Commander deck starts with Target bracket 2), and a night with no published range still has that target to go by (E9-S03, E9-S20).
- **Check:** a Commander deck page lists every Game Changer, extra-turn and mass land denial card it contains, each with the brackets it rules out and the date of the list used, and says plainly that tutors, combos and intent aren't checked. (Mostly met: E9-S06's "What opponents will face" and E9-S04's card-data dates, built 2026-10-15; two-card combos are E9-S23, built 2026-10-21; listing tutors would be new.)
- Show what an opponent will face (extra turns, mass land denial) in plain words.
- Help with the physical night: the Packing plan for a Commander deck, token cards, a printable play sheet.
- Strength comparisons for Commander serve fitting the bracket, not winning the pod.

---

## Claude Code, the command-line operator

**Kind:** non-human actor

### Summary

The AI assistant on Matt's PC, acting on his requests. It does inventory, order, receipt, watchlist, deck and accessory work through `python -m decklab.db` and the `decklab.lib` command lines, and writes dated buylists and reports. It needs commands that are unambiguous, previewable, safe to retry, and that refuse clearly rather than guess.

### Role in Deck Lab

Actor `claude` in the audit trail (or the profile `--actor` names). It runs on the PC command line, which reads every space and every owner's accessories and wishlists, unbound by the page's per-viewer privacy; privacy there depends on Claude following `AGENTS.md`. Under private by default ([privacy-by-default.md](privacy-by-default.md); built 2026-10-18, live since 2026-10-19) the command line stays exempt, and Claude relays upkeep, not contents: it does what a space's owner asks without passing that space's cards, decks or games to anyone outside it. Since 2026-10-18 (decision D) Matt passing on a member's request counts as the owner asking, for upkeep only (merges, `add-precon`, table refreshes): Claude reports counts and "done", never the contents, and never changes a member's Public/Private switches (`visibility set` takes home's switches only). It writes only through typed commands with `-m` messages, `--reason` for removals, `--expect` revisions or shas, and `--dry-run` previews; never SQL writes or recreated files. It runs Forge simulations serially only.

### Background

Works from `AGENTS.md`, Matt's memory notes and the repo. Sessions are bounded, so anything it needs to know next time has to be written down there.

### Goals

- Carry out Matt's request with one correct, audited change, without clobbering a concurrent edit by Matt or User1.
- Know before writing what a change will do (dry runs, previews listing the decks whose tables would change).
- Keep deck prose in step with lists (the "Decklist changed" line) and deck tables current after inventory changes.
- Leave audit messages anyone using Deck Lab can understand.
- Never leak private material (wishlist notes, another owner's accessories) into places others can read.

### Frustrations

- `deck push` doesn't refresh other decks' tables; `collection merge` and token edits don't either, so the follow-up `deck tables --apply` is easy to forget.
- A forced order, or one deck with an unknown card, blocks every table refresh in a space.
- A `receive` preview and a later `--apply` aren't linked on the command line.
- A single collection card is changed or removed with `collection edit` (since 2026-10-21, E7-S25), and many at once, as one change, with `collection apply` (E7-S26), but not moved to another printing or finish: that's still the page's.
- Some error messages still name old file paths from before the database move.

### Behaviours

- Pulls a deck to the scratchpad, edits it, pushes it with `--expect`, then runs `deck tables --reprice --apply`.
- Records orders in one `order add` with `--fulfils`, after a `--dry-run`.
- Looks up card text, legality and prices live (Scryfall, EDHREC, Australian shops) rather than from memory.
- Writes dated buylists and reports to the repo and commits them.

### Devices and context

The Windows PC: Git Bash and PowerShell, system Python with the repo's `.venv` on the path, and the live Postgres database (a test server also writes to it).

### Skill level

Expert with the command line; depends entirely on documented contracts (`AGENTS.md`, [README.md](../README.md)) and live lookups.

### Facts

| Claim | Source |
|---|---|
| Most inventory, order, deck and buylist work goes through `python -m decklab.db` commands run by Claude. | owner notes |
| Every write needs a non-blank `-m`; removals and cancellations need `--reason`; order, product and watchlist writes take `--dry-run`. | `AGENTS.md` ("The inventory": Changing) |
| Exit codes: 0 done, 1 refused, 2 database unreachable, 3 saved but deck tables not refreshed. | `AGENTS.md`; `decklab/db/__main__.py` |
| The command line and `sql` read every space, including wishlists and accessories. | `AGENTS.md` ("Wishlists": Privacy; "Accessories") |
| A command-line change's actor is recorded as a profile id, `system` or `claude`. | `decklab/db/conn.py:121-132` |
| A change's message shows on Activity only to a viewer who sees every row of that change, and for wishlist rows only to the list's owner. | `decklab/lib/api/activity.py:38-53`; [README.md](../README.md) ("Activity") |
| Forge simulations must never run from parallel agents. | owner notes |
| Command-line writes are recorded as `claude` unless `--actor` names a configured profile, so writes Matt runs himself show as his (an unknown actor is refused). | Matt, 2026-10-13; [stories.md](stories.md), E11-S07; `AGENTS.md` ("Command-line actor") |

### Assumptions

- Other AI operators (or future scheduled agents) would have the same needs.

### Design implications

- **Check:** every write command has `--dry-run` and an explicit concurrency token (`--expect`), saves one change set, and on refusal says why and what to do next.
- **Check:** a command that leaves other decks' tables stale prints those decks and the exact follow-up command, or does the refresh in the same change. (Met 2026-10-13, E11-S10.)
- **Check:** commands that print another owner's wishlist or accessories label them as private, and Claude-written audit messages never quote wishlist notes.
- **Check:** a write Matt runs himself can name him as the actor, a write with no actor stays Claude's, and an unknown actor is refused (met, E11-S07).
- Keep command and page behaviour identical (same rules, same checks), so Claude's changes look normal on the pages.
- Remove stale file-era wording from errors and docstrings.

---

## The value collector (anti-persona)

**Kind:** anti-persona

### Summary

Someone who collects Magic cards as assets: tracks portfolio value, foils, grading, price history and profit. Deck Lab deliberately doesn't serve them.

### Role in Deck Lab

Not a user. Nothing in Deck Lab should be built for this need.

### Goals

- Track the market value of the collection and its change over time.
- Record purchase prices, spending and profit.

### Frustrations

- Deck Lab has no price-paid fields, no totals and no value history, by design.

### Behaviours

- Would ask for portfolio dashboards, price alerts on owned cards and grading fields.

### Devices and context

Not applicable.

### Facts

| Claim | Source |
|---|---|
| Magic is collected to play: judge cards by how well they play, not collector value; default to the cheapest printing unless a particular one is asked for. | `AGENTS.md` ("What each game is for") |
| No budget tracking: don't track spending or total what's been spent; orders never store prices. | `AGENTS.md`; owner notes |
| Pokémon, where value and condition matter, is a separate inventory outside Deck Lab and out of scope. | `AGENTS.md` ("What each game is for"; "Layout"); owner notes |

### Assumptions

None.

### Design implications

- Reject features for collection value, spending totals or price history of owned cards.
- Show prices only as forward estimates for missing cards, dated and labelled.
- Choosing a printing for its art isn't value collecting and stays in scope.
- Keep Pokémon out of Deck Lab.

---

## The tournament grinder (anti-persona)

**Kind:** anti-persona

### Summary

A competitive player tuning for a sanctioned metagame: format legality, ban lists, rotation, metagame shares, MTG Arena. Deck Lab's 60-card side ignores legality entirely, and its Commander side aims at a social bracket.

### Role in Deck Lab

Not a user.

### Goals

- Track format legality and rotation.
- Optimise against the current tournament metagame.

### Frustrations

- Deck Lab never flags banned or rotated cards in casual decks and has no metagame data.

### Behaviours

- Would ask for legality warnings, metagame imports and Arena exports.

### Devices and context

Not applicable.

### Facts

| Claim | Source |
|---|---|
| Casual 60-card decks ignore ban lists and format legality; "competitive" means strong in 1v1, not tuned for a tournament. | `AGENTS.md` ("How Magic gets played") |
| Physical cards only; no MTG Arena. | `AGENTS.md`; owner notes |

### Assumptions

None.

### Design implications

- **Check:** no legality or ban badge ever appears on a casual 60-card deck.
- **Check:** Commander decks show only the Commander ban list, colour identity and the bracket checks.
- Strength is measured only against the household's decks, never a public metagame.

---

## The stranger on the internet (anti-persona)

**Kind:** anti-persona

### Summary

Anyone not invited who finds decklab.example.com or wants a public deck site. Deck Lab is a private tool for the household and the members Matt invites (User5 since 2026-10-18), not a public service. "Public" in Deck Lab's switches means read-only to everyone signed in, never to this persona.

### Role in Deck Lab

Must never get in. Cloudflare Access email login gates the internet address, and an email not mapped to a profile is refused.

### Goals

- Browse or share decks publicly; sign up for an account.

### Frustrations

- There's no sign-up, share link or public view, by design.

### Behaviours

- Would arrive at decklab.example.com and be stopped at Cloudflare Access.

### Devices and context

The public internet.

### Facts

| Claim | Source |
|---|---|
| decklab.example.com is behind Cloudflare Access email login; Deck Lab verifies the token and maps the email to exactly one profile. | `decklab/lib/access.py`; [README.md](../README.md) ("From outside the home") |
| Profiles are added only by hand in `decklab/config.json` plus the Access policy. | `decklab/lib/profiles.py` |

### Assumptions

None.

### Design implications

- No pages open to the internet, share links, sign-up or social features. A Public switch shares only with signed-in profiles.
- Never bypass Access; fail closed when identity is missing.
- Design copy may assume every visitor was invited, but not that every visitor belongs to the household (members don't).

---

## Scenarios

Short stories of each persona using Deck Lab. Most describe Deck Lab as it is on 2026-10-13; those marked **assumption-based** or **future-state** describe a likely situation or a design target rather than something observed. The step-by-step versions are in [journeys.md](journeys.md).

### Matt

**matt-1. How close is Izzet Otters?**
Matt opens Izzet Otters on his phone. The banner says how many cards it's short. Show them splits them into cards in storage, cards on the way and cards to buy. He decides to pull the storage cards tonight and leave the rest for an order.

**matt-2. Topping up a shop order**
At the PC, Matt asks Claude whether a card for Alela Faeries is in stock at an Australian shop. Claude checks that shop for every watchlist row, long-term ones included, and suggests in-stock add-ons that would share postage. Matt agrees. Claude records the order with a dry run first, then for real, and the fulfilled watchlist rows drop in the same change. Later, on a tablet, Matt sees the delivery under Shopping's On the way.

**matt-3. Is this swap worth buying?**
On a tablet, Matt edits a deck to swap one card for a card he doesn't own yet and taps Test this change against the field. While Forge plays, the pill in the top bar shows progress. The verdict says "Makes little difference", so he drops the idea. (Today the result doesn't show the card's AU price or offer to queue it; with a large difference he'd have to ask Claude to add it to the watchlist, a gap.)

**matt-4. Deck Lab is off while he's out** (assumption-based)
At a shop, Matt opens decklab.example.com on his phone to check what a deck still needs, but the PC at home is off. Today he'd see a generic failure. The design target, as decided on 2026-10-13: a friendly page says Deck Lab is off. Cached last-seen deck lists aren't wanted.

### User1

**user1-1. Before a game** (partly future-state)
User1 opens Deck Lab on her phone, picks her name on "Who are you?", and switches the library to Mine. She opens The Free Peoples, reads its How to play topics and deals a practice hand on the Practice tab. Because the deck is still being built, the banner tells her which cards are missing and which are on the way, so she knows whether tonight's game uses stand-ins. After the game, one tap on the Game log records who won.

**user1-2. Waiting for cards**
Away from home, User1 signs in to decklab.example.com with her email code to see whether the cards for Gandalf and the Valley have come. The deck's banner says how many cards it is waiting for; Show them lists the cards and the order they're on. Shopping shows the delivery as on the way. Matt records its arrival when the parcel comes.

**user1-3. A card she'd like**
Browsing on her phone, User1 sees an alternate-art printing she likes for her Stardew-themed Commander deck. She adds it to her Wishlist with the printing chosen. To get it bought she has to tell Matt, who asks Claude to add it to the watchlist, because there's no "ask to buy" path on the page (a gap; Matt wants one, not urgently: E5-S15).

**household-1. Two players, one tablet** (assumption-based)
Matt and User1 sit down with a shared tablet between them. User1 picks her name, checks her deck's How to play, then hands the tablet over; Matt switches to himself to open the Packing plan for both decks. After the game the winner is recorded. The design needs fast switching between people and every action attributed to whoever is actually picked.

### User5

**user5-1. A first sign-in** (future-state)
After the invite, User5 opens decklab.example.com and signs in with his email code. Deck Lab shows his own empty space and nobody else's: no home decks, no other members, no matchups. He imports a collection export on his Collection page and builds a deck. Nothing he adds is seen by anyone else until he sets it to Public, and then only by people signed in.

### User2, User3 and User4

**space-members-1. Bringing his own deck to a game** (assumption-based)
Before a game against home's decks, User2 signs in on his phone and opens his Commander deck in his space. He checks its Stats tab for the bracket and card count, then browses the household's decklists to see what he might face (under the privacy decision, only once home makes its decks public, E10-S30). Shopping, the household's counts and the household's games don't appear for him (the games since 2026-10-13, E10-S24).

**space-members-2. Entering older cards** (assumption-based)
User2 exports part of an older collection from a scanner app and imports the file on his Collection page. The preview lists rows it couldn't match to a Scryfall printing, grouped by set, which he fixes or leaves out before applying.

**space-members-3. A first look** (assumption-based)
User3 opens Deck Lab for the first time and lands on his Commander deck, with its How to play guide and a list he can print. Nothing on the page asks him to manage inventory he doesn't have, and empty pages aren't in his navigation.

### The Commander-night table

**commander-table-1. Sitting down in a pod** (future-state)
At a Commander night, a staff member seats Matt in a pod of four. Someone asks what bracket his deck is. Deck Lab's check showed the deck's minimum bracket and listed the cards behind it (no Game Changers, no mass land denial, no extra turns) and said that tutors and combos aren't checked, so he answers honestly and mentions the one tutor he knows is in it. The table gets the evening they expected.

### Claude Code

**claude-1. Receiving a delivery for Matt**
Matt says the cards part of an order has arrived and the Sol Ring is near mint. Claude previews the receipt, fixes the row's condition with `order edit`, applies the receipt with `--verified`, and reports the rows and cards added. Exit code 3 would have meant the tables didn't refresh; Claude would then explain why and run `deck tables --apply` once the cause is fixed.

---

## Answered 2026-10-13

Matt's answers to the design model's open questions, each a dated owner decision (Matt, 2026-10-13). The stories they changed carry a matching Decision line in [stories.md](stories.md).

| # | Question | Answer |
|---|---|---|
| 1 | Which device does User1 use, and does she open Matchups or Stats? | A phone. Matt doesn't think she uses Matchups or Stats. Her phone surfaces (deck page, library, Wishlist, Packing plan, Game log) matter more; her Matchups, Stats and Forge stories drop to could or move to Matt. |
| 2 | Should home-network writes follow the picked profile's permissions instead of passing as an admin's? | Yes; scripts naming nobody still pass. A must (E10-S03), built 2026-10-13. |
| 3 | Should User1 be able to ask from the page for a card to be bought or a Forge run, with Matt approving? | Yes, though she'd probably also just say it in person. Wanted, not urgent (E5-S15 should, E3-S13 could). |
| 4 | Does Matt want to change the purchase queue and record orders on the pages himself, or keep that as Claude's job at the PC? | On the pages himself: state, quantity, remove and add on the queue, and recording orders (E5-S06, E6-S02, both should). |
| 5 | Which bracket will the household aim for at Commander nights, and what do the shops say? | Bracket 2, Matt thinks. The usual store publishes a bracket range for its social Commander night; other venues may not (E9-S03, E9-S20). |
| 6 | Should orders get an expected arrival date? | No. Naming the order a card is on stays (E6-S23 not wanted; E6-S03). |
| 7 | Should Deck Lab start at logon, and should the nightly backup run without anyone logged on? | Start at logon: yes, turned on 2026-10-13 with `homenet install --at-logon` (E11-S23 built). Without a logon: not needed. The PC stays logged on while it's on, so it is either logged on or off; at-logon tasks are enough, and the nightly's catch-up run after the PC was off covers the rest (E11-S24 not wanted). |
| 8 | What should a phone show when the PC or server is off? | A friendly "Deck Lab is off" message is enough (E11-S02). Cached last-seen deck lists aren't wanted (E11-S27). |
| 9 | May several decks use one sleeve design? | Yes: it's up to the players not to play both at once. This reversed the one-holder rule; E8-S20 (a must) is built. E8-S07 and E8-S10 (separate sleeves per deck within a product) are not wanted. |
| 10 | Should Matt's own command-line writes show as his on Activity, separate from Claude's? | Yes (E11-S07, should). |
| 11 | Will User2, User3 and User4 use Deck Lab, and on which devices? | Occasionally at most, Matt expects; mostly phones, if at all. Their stories drop in priority. |
| 12 | Should members outside home see the household's Game log? | No. A must privacy story (E10-S24), built 2026-10-13. |
| 13 | How much should Deck Lab teach rules and play to newer players? | Minimal; products like the Beginner Box do that. The in-context help that exists stays (E4-S07 not wanted, E4-S09 could). |
| 14 | Do Forge results need backing up? | No; they can be regenerated (E11-S17 not wanted). |
| 15 | Who sees another space's data? (asked later the same day) | Nobody, unless that space makes it visible to everyone with a profile, read-only; the admin role doesn't override, and the home chooser offers home profiles only. See [privacy-by-default.md](privacy-by-default.md), section 4 (E10-S28 to E10-S36). Changed 2026-10-18: "visible to the family" is now **public**, read-only to everyone signed in (see below). |

## Answered 2026-10-18

Matt accepted every recommendation of [member-template.md](member-template.md) on 2026-10-18 (Matt, 2026-10-18). User5 (`user5`) is the first real member and his setup is the template; the other members move onto it with no config change.

| # | Question | Answer |
|---|---|---|
| Base | What do members see? | Everything in an account is private by default; its owner can make it **public**, read-only to every signed-in profile, future members included. No family flag or family audience. Public never means the open internet: still no open pages, share links or sign-up. |
| A | One switch per list, or per deck too? | One per list (collection, decks, games, each owner's accessories) now; per-deck public later (E10-S41, could). |
| B | Wording? | Public / Private everywhere, never "visible to the family". |
| C | Who's on the profile roster? | A viewer's own profile plus profiles whose space has something public, and the admin's display name; no answer names a space the viewer can't see (E10-S38, must). |
| D | Does Matt passing on a member's request count as the owner asking? | Yes, for upkeep only (merges, `add-precon`, table refreshes). Claude reports counts and "done", never contents, and never changes a member's switches. |
| E | Keep Visits for members? | Yes, and User5's invite says so. |
| F | What do members see of the simulations setting? | Only the mode and a reason without names (part of E10-S34). |
| G | Who edits a Game-log record naming two spaces? | Each side's space edits only its own side; the result and notes stay with the recording space; a sideboard plan belongs only to its deck's space; naming an opponent deck needs it public or the viewer's own (E10-S32). |
| H | What happens when a member leaves? | A new command exports their space and removes it in one audited change (E10-S40, should). |
| I | Does the admin narrowing (E10-S29) ship before the invite? | Yes. |
| J | May User1 edit home's collection and tokens? | Yes, as Matt can (E10-S43, must). |
| K | Make home's decks public when the other members move? | No: they stay private, and Matt switches them on if he wants. |

**Build order, now done** (it replaced PBD's phases). Before inviting User5, all built 2026-10-18: phase 1, E10-S35 and E10-S42; phase 2, E10-S30 without the switches; phase 3, E10-S36 then E10-S29 with E10-S43; phase 4, E10-S32's member rules, E10-S38, E10-S34's settings GET and simulations wording, and E10-S39. Matt confirmed the invite sent on 2026-10-18. After it, also built 2026-10-18 and live since 2026-10-19 (migrations 0012 and 0013): E10-S28's switches (Public / Private), E10-S31 in full, E10-S33, the rest of E10-S34, E10-S37 and E10-S40. Nothing is switched Public yet. E10-S41 (per-deck public) waits until someone asks.

## Open questions to validate with Matt

1. **User1's own view.** Matt's answers about her (phone-first, no Matchups or Stats) are his view. Ask User1: which phone, whether she also uses a tablet, and what she does before a game.
2. Is a tablet shared between Matt and User1 with profile switching?
3. Do User2, User3 and User4 sign in at all, and would any of them want a larger collection in Deck Lab?
4. Will the household play at other venues, and do their house rules need respecting?
5. ~~With several decks in one sleeve design, should Deck Lab warn at all (E8-S20)?~~ *Answered (Matt, 2026-10-19): warn when sleeves or a deck box already in use are chosen. Sleeves now warn every time they're chosen for a second holder; a deck box still can't be chosen once every box is in use, and one with a spare box free doesn't warn.*
6. Does Deck Lab's pricing need live AU retailer prices, or are the dated watchlist reference prices enough?
7. Are there other anti-personas Matt wants named (for example, a trader or an online-only player)?
8. **User5** (asked once he has used Deck Lab): which devices he uses, how much Magic he plays and with whom, and what he'd want public.
