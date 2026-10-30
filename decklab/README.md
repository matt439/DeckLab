# Deck Lab

A web page for Magic decks: the deck library, personal card wishlists, shared shopping and delivery status, each deck's cards and stats, practice-hand results (how its mana holds up over 100,000 simulated games), matchups between decks and against the rest of a deck's format (full games played by Forge's computer players), what's owned vs still needed, and an editor that saves the decks (in Deck Lab's database) and can test a change on the deck's own games first. It runs on this PC and is used from phones and the iPad on the home network, and in a browser on the PC itself. [PLAN.md](PLAN.md) has the full plan. This file is the reference for one household's PC, so it names that PC's folders and people; to set up your own Deck Lab, start with [SELF-HOSTING.md](../SELF-HOSTING.md).

## Start it

For a new setup or a setup problem, `python -m decklab.doctor` reports the core
runtime, configuration, driver, database metadata and card-index checks with next
steps; `--json` gives the same fixed findings. It contacts the configured database
read-only, without starting the server or running setup. Exit codes are `0` for
core checks passed, `1` for known missing setup, and `2` for unverified core checks
or invalid arguments. Optional Java/Forge file checks never block the core app and
do not qualify simulation execution. See [SELF-HOSTING.md, step 7](../SELF-HOSTING.md#7-start-it-and-open-it)
for the bounds, privacy and separate simulation checks.

Deck Lab runs in the background, with no window, once you start it:

```
python -m decklab.lib.homenet start
```

That has to run from the repo root. From any folder, run `C:\VSProjects\TradingCardCollection\scripts\decklab.cmd` instead (or just `decklab` once `scripts\` is on your PATH). With no arguments it starts the server; anything else is passed to `homenet`, so `decklab stop`, `decklab restart` and `decklab status` work too.

It doesn't start by itself when you log on to Windows (since 2026-10-01; see `--at-logon` below for turning that on). `start` has Task Scheduler run `decklab/server.py` with `pythonw.exe`, which has no window. The server keeps running until you stop it, log off or shut down. The PC has to be on and logged on for the page to work.

Set up the task `start` uses once, in this order. First, from the repo root, in an ordinary PowerShell or command prompt (no administrator needed):

```
python -m decklab.lib.homenet install --no-start
```

Then do the network setup (see "Network setup (once, as administrator)" below). It needs the task to be there first, because that's where it finds which `pythonw.exe` runs Deck Lab. Then start the server:

```
python -m decklab.lib.homenet start
```

Starting it after the network setup means the firewall rules are already there, so Windows has no reason to stop and ask about Python's access to the network.

- `install` registers a task called "Deck Lab" for this Windows user only. Without `--no-start` it also starts the server straight away: if a server is already running, it says so and doesn't start a second one, and if another program has the port, it says so and fails.
- **Starting at logon is off.** The task has a logon trigger, but `install` leaves it turned off. To have Deck Lab start by itself 30 seconds after each logon, run `python -m decklab.lib.homenet install --at-logon`. Running `install` again without `--at-logon` turns it off again.
- **Restarting after a crash** (E11-S26, since 2026-10-20) comes with `--at-logon`: it also registers a second task, "Deck Lab watchdog". Every 5 minutes while you're logged on it runs `pythonw.exe -m decklab.lib.homenet ensure` (no window), which starts Deck Lab through the "Deck Lab" task if it has stopped unexpectedly, so it's back within about 5 minutes.
  - It leaves Deck Lab alone when it was stopped on purpose (see "Stop, start and restart"), when anything answers or holds the port (a stuck server isn't killed: `status` shows it), when the "Deck Lab" task is missing, broken, turned off or doesn't start at logon, and for 2 minutes after you log on or `start`, `restart` or `install` starts it (the logon trigger waits 30 seconds, and a server takes a few more to answer), so a check that lands in a start doesn't start it early or count a crash that didn't happen.
  - After 3 restarts in a row that don't stay up (a server has to run 10 minutes to count as up), it gives up until `start`, `restart` or your next logon, and `status` shows that as a PROBLEM.
  - **A task set up before 2026-10-20 has no watchdog.** Run `python -m decklab.lib.homenet install --at-logon --no-start` once (it doesn't touch the running server; if Deck Lab is off, it writes the stop marker, so it stays off until `start` or your next logon), then `restart` so the running server records stops on purpose too. `status` warns until then.
  - `install` without `--at-logon` removes the watchdog (starts are manual then, and off is normal), and so does `remove`.
- Run `install` again after moving the repo or upgrading Python, since the task names the exact `pythonw.exe` and `server.py`. Then run the network setup again too, since its "Deck Lab (pythonw)" rule names that `pythonw.exe`. Until then, `start` and `restart` say the program or script "isn't there any more" and stop nothing, and `status` (see "When a phone can't reach it") shows it as a PROBLEM.
- `python -m decklab.lib.homenet remove` stops the server and deletes the task. `start` can't start it again until `install` sets the task up again.
- The first start downloads Scryfall's card data into `decklab/data/` (about 100 MB, a few minutes). Until that's done the page says the card data isn't ready and retries by itself. After that it checks once a day and downloads again when the data is over a week old.
- A deck page's **Practice** tab plays the deck's practice games the first time it opens for that list: about 1-1.5 seconds with every core busy. The result is saved in `decklab/data/goldfish/`, so after that it shows at once, on any device. One simulation runs at a time; others wait their turn. Stopping the server stops a run in progress too.
- A Beginner Box half has no practice games of its own, since it's only ever played shuffled with another half: its page links to its 40-card pairings instead.

**In a window instead.** To watch the log as it happens, run the server in a window. Only one server can use port 8642, so stop the background one first:

```
python -m decklab.lib.homenet stop
python decklab/server.py
```

- Each request is logged in the window. Ctrl+C (or Ctrl+Break, or closing the window) stops it. Then `python -m decklab.lib.homenet start` brings the background one back.
- If the background server is still running, the window says so and how to stop it.
- `--no-update` skips the card-data download and uses the data already there. `--port` and `--host` change where it listens (the defaults are `"port"` and `"host"` in `config.json`, else port 8642 on every network interface).
- **A server for testing** can run beside the background one on another port, listening on this PC only: `python decklab/server.py --host 127.0.0.1 --port 8643`.
  - It needs another port: a port takes only one server, even on another address, so a second server on 8642 says Deck Lab is already running.
  - It needs `--host 127.0.0.1`: a server on every network interface, on a port no firewall rule lets in, makes Windows ask about Python's access to the network (see "The firewall prompt for Python").
- `--log FILE` writes the log to FILE instead of the window (rotated like the background server's log; see "The log").
- `--stop` stops the server on the port (8642, or the one `--port` gives) the way Ctrl+C would, from any window: for example `python decklab/server.py --port 8643 --stop`. It's what `homenet stop` does. With `--port` it doesn't read `config.json`, so it still works when that file is broken. Without `--port`, a `config.json` that can't be read gets a message saying to pass `--port`.

## Stop, start and restart

From the repo root, in any window:

```
python -m decklab.lib.homenet stop
python -m decklab.lib.homenet start
python -m decklab.lib.homenet restart
```

On Linux (E11-S33) the same commands act on a systemd user service, `~/.config/systemd/user/decklab.service`, which `install` writes (`--at-logon` enables it, so it starts when the user's systemd does: at login, or at boot with `loginctl enable-linger`). It runs `decklab/server.py --background` with the Python `install` was run from, logging to `decklab/data/logs/server.log` like the Windows task. `Restart=on-failure` does the watchdog's job: a server that crashes is started again after 10 seconds, one stopped on purpose stays stopped. stop is `systemctl --user stop`, a SIGTERM the server takes as a stop request (`KillMode=mixed`: the server stops its own Forge games). `status` shows the server, the service (installed, enabled, running, restarts, whether its unit is out of date, lingering) and the tunnel; the firewall, sleep and network checks are Windows'. A server started in a terminal hears the same SIGTERM, so `homenet stop` and `server.py --stop` stop it too (the state file names its process, and `/proc` must still show that process running `server.py`).

- **stop** asks the server to stop the way Ctrl+C does, and waits up to 30 seconds for it to end. A practice-hand run stops. The matchups that are playing stop within about a second and save every game they finished (the server waits up to 15 seconds for that), and then the warm pool's Forge workers quit (any still there after 3 seconds are killed). It stops a server in a window too. If the server runs as administrator or in another Windows session, stop can't reach it and says so: run the same command from an administrator PowerShell, or end its `pythonw.exe` in Task Manager.
- **start** starts the "Deck Lab" task (run `install` first), waits up to 20 seconds for the page to answer, and prints its addresses. If the page doesn't answer, it shows what the server wrote to its log since this start, or says it wrote nothing. It never starts a second server: if one is running, it says so.
- **restart** is stop, then start. **Run it after changing Deck Lab's code or a `git pull`:** the running server keeps the code it started with. `status` warns when the code has changed since the server started.
- Before doing anything, **start** and **restart** check that the `pythonw.exe` and `server.py` the task names are still there. If not, they say to run `install` again, and stop nothing.
- **`taskkill /PID <process id>`** without `/F` stops it the same way as stop. Its log then says "Asked to close (taskkill): stopping." `status` shows the process id.
- **A stop stays a stop** (with the watchdog, see "Start it"): `stop`, `server.py --stop`, `taskkill` without `/F`, Ctrl+C or closing the window of a server in a window, and `install --at-logon --no-start` while it's off all count as on purpose, so the watchdog leaves Deck Lab off until `start`, `restart`, `install` (when it starts it) or your next logon. They write a marker, `decklab/data/stopped-<port>.json`, which a server clears once it's listening. `stop` writes it before it asks, so Deck Lab stays off even if the stop times out and you then end it in Task Manager, or it had already crashed. A `restart` whose stop times out leaves a restart's marker instead: once the old server has stopped (or you end it in Task Manager), the watchdog starts it again, as `start` would. Ending it from Task Manager, `taskkill /F` or `Stop-ScheduledTask` *without* a `stop` first counts as unexpected, and the watchdog starts it again. So does a crash; logging off or shutting down leaves no marker either, as the next logon starts it anyway.
- **Don't end it from Task Manager, `taskkill /F`, `Stop-ScheduledTask` or Task Scheduler's End button.** Those kill it at once:
  - a matchup that's playing loses every game of that run, since a run's games are only saved when it stops properly (its Forge processes still end with the server);

  If `stop` says the server is still running after 30 seconds, try again in a minute. Use Task Manager only as a last resort.
- **Logging off or shutting down Windows** stops it the way closing its window does. Windows only allows a few seconds, so it waits at most 4 seconds for the matchups to save their games, then kills the warm workers at once.

## The log

- The background server writes its log to `decklab/data/logs/server.log` (not in git). It has a line for each request (time, the phone's address, method, path, status and milliseconds), the server's start and stop, and each error with its details. A crash at start-up lands there too.
- At 2 MB the log is renamed `server.log.1` (older ones move up to `.2` and `.3`, and the oldest is deleted), and a new `server.log` starts. So the logs never take more than about 8 MB.
- A server in a window logs in the window, unless it was started with `--log FILE`.
- `python -m decklab.lib.homenet status` says where the running server's log is, and `start` shows what the server wrote to it when the server doesn't answer.
- Opening the log in an editor is fine. If another program is holding `server.log` open when it's due to be renamed, nothing is renamed and the old logs are kept: the server keeps adding to it and tries again a little later.
- A file called `server.log.rotating` can appear for a moment while the log is renamed, or stay behind after a rename that couldn't finish. The next rename turns it into `server.log.1`.
- The watchdog writes `decklab/data/logs/watchdog.log` (rotated at 200 KB, one old file kept): a line only when what it finds changes (stopped on purpose, running, another program on the port, ...) and for each restart, with what the start said. It never copies the server's request lines. Its record of restarts is `decklab/data/watchdog-<port>.json`. Neither is in git.

## Open it

- **On this PC:** http://localhost:8642.
- **From a phone or the iPad:** http://192.0.2.10:8642 (the PC's address on the home network; `status` prints it).
- **By name:** http://homepc.local:8642 may work on the iPhone and iPad. On 2026-10-01 the PC answered to `homepc.local` on the home network, but that hasn't been tried from a phone yet, and some Android phones don't understand `.local` names. If the name doesn't work, use the address. `status` checks whether the PC still answers to it.
- **From anywhere (outside the home too):** https://decklab.example.com (or `www.`). The first visit on each device asks for an email address and sends a one-time code; only the emails in Cloudflare Access's policy get in, and a login lasts a month. See "From outside the home" below.
- On the iPad or phone, "Add to Home Screen" makes it open like an app.

**Reserve the address in the router.** The router hands out addresses itself (DHCP), so the PC's address can change, and the phones' bookmarks would then stop working. To keep it:

1. Open your router's admin page (often http://192.168.0.1/) on the PC and log in to the router.
2. Find the DHCP address reservation page. On many routers it's under **DHCP Server > Address Reservation**, but the menus differ between models.
3. Add a reservation for the PC's MAC address (the one `status` prints for the wired network adapter, such as `00-00-5E-00-53-01`) with its current address (such as `192.0.2.10`), and save.

`status` prints the MAC address and the current address too, in case either changes (a new network card, say). It can't tell whether the reservation has been made.

The page starts by asking **Who are you?** (the home's profiles in `config.json`, Matt and User1; since 2026-10-18 the other members sign in through decklab.example.com, from the home Wi-Fi too). It asks again after the page has been in the background for 30 minutes, since the iPad is shared, unless that person has chosen **This is my device** in the avatar menu (home network only): that device then opens as them without asking, and isn't forgotten while away. **Switch person** in the same menu goes back to the question. Through the tunnel the login is the person, so neither is offered.

Each profile's settings (the theme, a matchup's games and mode, and the field budget) are rows of the database's `profile_setting` table, so they follow the person to every device (`GET/PUT /api/profiles/<id>/settings`; only values Deck Lab offers are kept). Only the profile itself reads them (E10-S34, 2026-10-18: no admin override, so Matt doesn't read User1's either; a script naming nobody reads any): anyone else gets 403 "You can only see your own settings.", the same for a profile that doesn't exist, and the matchup and field pages' defaults (`?profile=`) come only from the viewer's own. A PUT reads no one else's either: an admin changing another profile of his space (at home) gets back only the keys he sent, an empty PUT nothing. A change is one change set, "Change User1's settings: theme", made by the tunnel's login or, at home, the profile the page names (else "someone at home"). While the database can't be reached, the page keeps the device's theme, a save answers 503, and the matchup and field pages go on with the last values the server read, else the defaults (on any database error, not only when it's down).

### The page's layout

Since the UI redesign of 2026-10-13 ([HISTORY.md](HISTORY.md), "UI redesign"; the reasons are in [UI-REVIEW.md](UI-REVIEW.md), and the shared pieces every page is built from in [UI-KIT.md](UI-KIT.md)) every page sits in one shell, and each page has one name (core.js's routes table):

- **From 1,000 px wide** (a desktop, an iPad in landscape, and a phone on its side) a top bar: **Decks** (`#/library`), **Collection**, **Shopping** (with a count of deliveries waiting), **Matchups** and **More** (Tokens, Sleeves & boxes, Build decks, Game log, Wishlist, Activity) as round buttons, the page's own one tinted. Beside them, while Forge plays or waits, a small turning ring ("Forge is playing: show progress") that opens each run's progress and Stop (E11-S30 slice 6), then the avatar menu: Theme (Auto, Light, Dark), Switch person, This is my device, and for an admin **Settings** and **About Deck Lab**.
- **Under 1,000 px** (a phone, and an iPad in portrait; E11-S30 slice 7) a header (the way back or the logo, the page's title once its heading scrolls away, the turning ring while Forge plays, the avatar) and a tab bar at the bottom: Decks, Collection, Shopping, Matchups (with a dot while Forge plays) and More (a sheet with the rest). The tab bar stays on every page: the editor's and Receive delivery's own bars sit on it. A phone's Back closes an open sheet or the card viewer before it leaves the page.
- **Pages a profile can't use are left out:** Shopping and Build decks need home's inventory, Sleeves & boxes a home profile, and Settings an admin (see "People's own collections").
- **Child pages** (a deck, its editor and history, a test of a change, Receive delivery, a matchup) have a crumb back to their parent ("← Gruul Ramp", "← Shopping").
- **Settings** (`#/settings`, admins only): **Simulations** (who may start Forge runs, and how many Forge workers the PC uses; see "Pausing simulations" under Matchups), **Commander night** (home admins only; the optional usual-night expectations shown on home Commander pages), **Members** (home admins only; add a member with their own space or replace an existing member's sign-in email), **Database maintenance**, **Visits** (who has used Deck Lab, when and from where, and the pages they opened; see "Visits" under Database) and **About Deck Lab** (`#/settings?part=about`: the running version, Check for updates and the card data; see "Checking which version is running"). The footer is one quiet line: the prices' date and the exchange rate.
- **Database maintenance history** (E11-S35, 2026-10-28): Settings shows the latest recorded attempt and last successful run separately for backup, export, integrity check and restore check, plus at most five recent attempts for each. A failed latest attempt stays failed even when an older success is recent; never-recorded and unavailable outcomes remain explicit. Backup freshness uses its last success's finish, integrity checks use their start, and both use `stale_backup_hours`; export uses that existing nightly grace window too. Restore checks use `restore_check_days` from the last success's start, matching the nightly scheduler. **Refresh history** only reads `GET /api/settings/maintenance`, in one read-only consistent transaction. Only a selected admin may read it; responses and failures include no paths, credentials, private records or raw database errors. Jobs record their outcomes after completing, so an absent row does not prove no unrecorded attempt happened, and the view never infers Running. Existing status warnings and schedules are unchanged.
- **Private CLI-read notices** (E11-S21, 2026-10-28): wishlist, collection, tokens, decks and accessories list commands add privacy guidance on stderr while preserving human/CSV/JSON stdout, hashes and exit codes. Wishlists are owner-private; collection/tokens and decks follow their separate space switches, and accessory notices identify each output row's owner or shared home kit. Shared does not mean Public. A Public claim uses one fresh command-local visibility read, with no cached-grant fallback; unknown visibility gives conservative private guidance. Public applies only to signed-in readers, and a deck switch does not publish private inventory-derived status/errors or kit. The notices quote no card/item/notes contents or raw errors and introduce no CLI access restriction; `--actor` remains attribution only. Wishlist help also says audit messages and removal reasons must never quote notes.
- **A deck's two lists** are called the **Planned list** (the deck text's target list) and the **Play-now list** (its substitute list, the old "owned-only" version) everywhere on the page and in its warnings. The deck text's headings, the `Built version` values (`target`, `owned-only`) and the version keys (`target`, `owned`, as in `&v=owned`) don't change.
- **Widths:** a phone is under 600 px, a tablet in portrait 600-999 px (with the phone's header and tab bar), a desktop or an iPad in landscape 1,000-1,599 px, and from 1,600 px (a maximised window on the QHD screen is about 2,545 px) the grids take more columns and, with a mouse, a column on the right of the deck page and the editor shows the card last pointed at, full size (the editor's from 1,400 px).
- **Light and dark** follow the avatar menu's Theme; Auto follows the device. Red is kept for what stops a deck being played (missing cards, a broken deck rule); advice, such as lands against the formula, is amber. Chips show only exceptions, never "all fine" or zero.

### Cards and the card viewer

Every card picture or card name opens the **card viewer** over the list it's in, so a phone can swipe through the cards: a decklist, a delivery, the Collection, the Wishlist, a test hand, a revision's changes. On a phone the card fills the screen and a swipe moves to the next one (past a fifth of the width, or a flick), with "3 / 15" between Previous and Next; **Text** shows the rules text with Scryfall's mana symbols, **Flip** a double-faced card's back. From 1,000 px the card sits in the middle with Previous and Next beside it and its rules text in a dark panel on the right; the arrow keys, Home and End move between cards, and Escape closes. Pictures come from `/img/` in four sizes, and mana and other symbols from `/sym/` (see "Pictures and symbols" below).

### Decks (the library)

**Decks** (`#/library`) is a shelf of tiles, the home decks first, then each person's in a part that folds away, then the products (folded until opened). Each tile shows its library picture (below) with its colours over it, a status pill on Building and Idea decks, one line of facts, the owned bar with its words ("51 owned · 1 on the way · 8 to get"), a Forge line when the deck has been tested ("58% Forge field" and how long ago), and only when there's something to say a readiness chip in plain words ("Play-now list ready", "3 on the way") and a token line. From 1000 px wide (the desktop, the iPad on its side) the decks are rows under Built, Building and Ideas instead, beside the selected deck's detail pane: a click selects a row (the address keeps it), Enter or a click with Ctrl or ⌘ opens it, J and K move through them, and the pane has Edit deck and Open deck. The Forge numbers are each casual deck's field average (`GET /api/library/forge`, worked out on the PC from the saved games and cached until a result or a field list changes; nothing plays); a lab row shows `—` for an untested casual deck and nothing for a Commander deck. The whole tile is the link, to the deck's Cards tab filtered to what's missing when it misses cards. The filters (whose decks, format, status, Planned list availability: all cards here, cards on the way, cards to get, availability needs checking) and the sort (Ready first, Recently changed, Name) are kept in the address; on a phone they're behind **Filter**. **New deck** is the page's main action for anyone who may make one, on every width.

**Tables out of date** (`library-tables.js`): between the warnings and the filters, a panel lists the decks whose owned-vs-needed tables no longer match the collection (`GET /api/tables/stale`, fetched after the shelf draws; hidden when there's nothing to show or Deck Lab can't say), with how many cards changed in each, and **Update all**, which rewrites every table on it the viewer may change (today's prices, keeping hand notes) in one change (`POST /api/tables/update`; each entry's `may_update` says which). Decks the viewer can't change are said to wait for whoever plays them. Under it, the decks whose tables can't be updated, each with why in plain words (no owned-vs-needed table, no decklist, card names Deck Lab doesn't know in its Planned or Play-now list), and a note for a space whose card pool is incomplete, whose tables Update all, receipts and orders leave as they are until it's fixed (`pool.table_blockers()`, the same checks the refresh makes). Only the decks the viewer may see (their own space's, `guard.sees_deck`) of spaces whose inventory the viewer may see are listed, so the admin isn't shown another space's decks there either. `#/library?tables=1` scrolls to the panel; the Collection page's and Receive delivery's notes link there.

**Library pictures.** Each deck's tile shows the art of one card, its cover card, also shown small beside the title on its deck page. It's automatic (the commander, else the non-land with the most copies in the Planned list; on a tie a creature) unless the deck's text has an optional header line `- **Cover card:** <exact Scryfall name>`, or `- **Cover card:** <exact Scryfall name> (SET) <number>` for one printing's art. Choose it with the library's More, **Choose deck pictures** (then tap a deck), or the deck page's More, **Change library picture…**: the picker (`GET /api/deck/cards` for the cards, `POST /api/deck/cover` to save) shows Automatic and the deck's cards as art tiles, with a search and **Different printing…**, and writes or removes only that line, as one saved revision with Undo. Only the picker changes the line: Deck Lab's other saves (the editor, `deck tables`, a table refresh) keep it as written. A line it can't use (a name that isn't a Scryfall card) falls back to the automatic picture, which the picker then says; choosing Automatic removes it. Only someone who may change the deck text sees the picker (never for a product or pairing). By hand: `deck pull`, add or change the line under the title with the other header lines, `deck push`.

### A deck's page

A deck's page (`#/deck?id=<deck id>&v=target|owned`) answers "what is this deck, and can I build it?" first: a head (the title with its colour pips and picture, a status pill, one line of facts, **Edit** and a **More** menu: Build decks, Game log, History, Copy decklist, Download decklist, Print play sheet, Change library picture…), then an **availability banner** ("Ready to build", "Ready once 3 cards arrive", or "32 missing, about A$41 · 3 held by other decks" with **Show missing**), which holds the Planned list / Play-now list switch. For cards on the way it names their orders or products, the copies needed from each, and whether they're ordered or preordered; no arrival date is estimated. The banner and the card marks show only to viewers who may see the deck's space's inventory.

Then five tabs, kept in the address (`&tab=overview|cards|stats|practice|matchups`, and the Cards tab's `&filter=all|missing|coming|held`), each drawn the first time it opens:

- **Overview:** the stats' verdict strip, the key cards as large pictures, a token problem, a built deck's sleeves and deck box, an opponent-specific **Sideboard plan**, and **How to play**, drawn from the deck's game plan, mulligan and sideboard notes, with card names that open the viewer. Notes marked out of date after a list edit keep that warning, and to the deck's own space it names the cards the guide mentions that the deck's saved revisions once held and neither list holds now (E2-S27). The Sideboard plan picker matches this list and the chosen opponent/list; its in/out pictures retain the recorded printings. An exact current plan takes precedence; an older matching plan stays visible with a warning. With no plan, Sideboard notes show if present. Make or Revise opens the usual review/save sheet with both lists selected, only when the viewer may record that pair. The section follows Game log visibility.
- **Buying information for test additions** (E5-S17, 2026-10-28): a finished saved home swap test shows its added cards' current collection, on-the-way and still-to-find coverage to home's people. It uses the saved tested recipe and reserves the copies needed by its unchanged cards and preserved Sideboard/Companion. If today's list no longer matches the tested base or change, availability is unknown. Existing queue requests remain separate, with state, purpose and printing/finish. Recorded AUD references show shop and checked date; otherwise a cached Scryfall estimate shows printing/finish, price date and the USD-to-AUD rate/date. Missing evidence is unpriced/unknown and leaves the saved verdict available. The view makes no network price refresh. For a missing addition without an existing request, a home admin can choose **Review for Shopping**, keep Any printing, nonfoil or choose an exact printing/finish, then review the server-calculated quantity, deck and saved-test provenance before **Add to Shopping**. The ten-minute review is checked against the current saved result, inventory, decks and actor again under the write transaction; a changed or expired review needs another review. Any matching playable-card request across states/purposes/printing choices is shown instead of duplicated. The one audited request uses the supported deck source with the saved-test link in notes; retailer price/stock fields remain blank. **Open Shopping** reviews the queue. A lost save response asks you to check Shopping before reviewing another request.
- **Considering in the editor** (E2-S26, 2026-10-28): saved decks' full and Quick edit have a separate Considering area under Cards. **Add a card to consider**, quantity controls and Remove change the local draft; normal Save keeps alternatives with the deck. Undo, local draft resume, conflict rebase and Discard include them. They stay outside Planned/Play-now counts, availability, packing and Forge. A Considering-only save works before Play-now is started, without starting it. Missing legacy data is preserved; an explicit empty list clears alternatives, and unavailable changed drafts remain on the device until they can be loaded safely. The review shows normalized rows as they will save. Move to Planned or Move to Planned sideboard checks the complete destination before moving all copies in one draft change, which Undo reverses. Exact printings, finish and category are retained; checked defaults stay pinned through Save. In Play-now this edits a separate Planned draft and leaves Play-now untouched. An already-applied linked move is recognized on reload; a divergent latest version requires review and acknowledgment of both complete lists before Save. New-deck controls wait until its first save.
- **Cards:** the list as rows or pictures at every width (remembered on the device), filtered to All, Missing, On the way or In other decks, each card marked "2 missing", "in Gruul Ramp", or with its on-the-way quantity, order or product and ordered/preordered status; missing copies are greyed. Then the Tokens part (see "Tokens") and the price table (folded; also available when nothing needs buying but cards are still on the way, with the same source labels). Its **Card**, **Missing** and **~AUD missing** header buttons sort locally: names start ascending, copies and extended missing costs start descending, and unknown prices stay last in either direction. The unit estimate sits beneath the card name; price and exchange-rate dates remain visible. When the deck's own owned-vs-needed table is out of date, this tab says so, with **Update the table**. A Commander deck's Cards tab also has **See EDHREC ideas…** (E9-S07): EDHREC's commonly played cards for its commander, grouped by EDHREC's categories with the share of its decks playing each and the date the PC fetched them, filtered to Not in the deck, Free, To buy or All. A viewer who may see the deck's space's collection gets each card marked in the deck, free, owned but all in other decks (never named), or to buy with its AUD estimate; anyone else the list alone. Whoever may change the deck adds a card to its Considering list with **Consider**. EDHREC is asked only when the sheet opens, and only when the PC's copy (in `data/edhrec/`) is a week old; when it can't be reached the sheet says so and an older copy is used if there is one. The sheet's **Page** choice narrows the ideas to EDHREC's Budget or Expensive page, a Commander Brackets page or one of the themes EDHREC lists for the commander (each kept apart in `data/edhrec/`); a page EDHREC hasn't got says so and another can be chosen. The editor's Add panel has the same ideas as its **EDHREC ideas** tick, a new deck's too before its first save (marked in the space it's being made in).
- **Stats:** a verdict strip first, the charts, and the explanations in closed disclosures.
- **Practice:** **Deal a hand** and the practice games (see "Collection and physical play").
- **Matchups:** one row per opponent with the latest result and older ones folded, "Not played yet against: …", Against the field, and Tests of changes (see "Matchups (Forge)"). Its results are read only when the tab opens (`GET /api/deck?omit=matchups` until then), and they refresh while it's visible, every 15 seconds when idle, so runs started on the other device show up. Reading them never starts a Forge matchup.

The Overview's **Usual opponents** links work both ways. **Choose usual opponents**
saves the other decks in the same space that this deck usually faces; only a
viewer who may edit this deck can change its choices. Links chosen on the other
deck are named separately in the picker and changed there. Deleted or unreadable
decks never produce a link. Packing offers the selected decks' usual opponents
first, and a new Forge matchup offers them first among compatible opponents;
an explicit opponent choice and its list version stay selected.

Commander decks start their Overview with **At the Commander table**: a plain
sentence about the declared bracket aim and any detected Game Changers, mass land
denial or extra turns. **What opponents will face** lists those cards with viewer
links, and any two-card combo whose pieces are both in the list (E9-S23, from
Commander Spellbook's public export, which `cards update` downloads and reduces;
the list is matched on the PC, so no decklist is sent anywhere). The data note
gives the card data's dates and Wizards' latest Commander announcement (E9-S24,
from Wizards' sitemap, checked at most once a day), and warns while the card data
or Deck Lab's bracket rules (`constants.BRACKET_RULES_DATE`) are older than it.
After reviewing the rules against a new announcement, set that date to the
announcement's. These checks describe the displayed Planned or Play-now list,
independently of inventory access. They do not certify a bracket: combos of three
or more cards, chained extra turns, speed and intent still need a conversation
with the other players.

The Stats tab's **One card away** panel (E9-S25) lists the two-card combos the
list holds one piece of, from the same downloaded list: the missing piece must
fit the commander's colour identity and be legal in Commander (ban list from the
card data), and a piece that must be the commander is never offered. Each names
the card to add, an AUD estimate (cheapest non-foil printing, the cached daily
rate), and what it would do to the minimum bracket against the deck's aim; a
viewer who sees the space's collection also sees whether a copy is free, on the
way, in another deck or to buy (free first). Whoever may edit the deck can **Add
to Considering** (E2-S23), never straight into the lists. At most 100 are sent,
most serious first, with the total. On the PC, `python -m decklab.lib.combos near
<deck-id> [--owned]` prints the same list, free first, with each card's place in
the deck's own space (the command line reads every space).

Under its role bars, a Commander deck's Stats tab has **Free cards by role**
(E9-S26) for a viewer who sees the space's collection: for each role (ramp,
card draw, removal, board wipes and the rest, from the same Scryfall oracle
tags as the bars) up to 10 cards the space owns with a copy free for the deck
(owned or on the way, less what other built decks and intact products hold),
not in the list yet, inside the commander's colour identity and legal in
Commander, most-printed first. It comes from `GET /api/deck/role-cards?id=&version=`
(403 "That collection isn't public." to anyone else, after the deck's own 404),
names no other deck, and says role tags are unavailable when the card data has
none. It suggests only: a card goes in through the editor.

When the colour check (Karsten's sources) finds a single colour short, the Stats
tab's colour sources panel offers **Free dual lands** for it (E3-S25) to a viewer
who sees the space's collection: free lands (owned or on the way, less what other
built decks and intact products hold) whose produced mana includes that colour and
another of the deck's, each with the basic of the Deck section it would replace and
**Test this swap**, which opens the editor with the swap as its draft. It comes from
`GET /api/deck/dual-lands?id=&version=` and suggests only.

**Commander night** (E9-S20, built 2026-10-16) is one optional household record,
edited in Settings by a home admin. Give it a name; venue, household target
bracket, published range, house rules/table notes and date last checked are
optional. Both ends of a published range must be supplied together; use the same
bracket twice for a single bracket. Blank target/range/date values stay unknown,
and saving does not stamp today or infer a venue policy. Name and venue allow
120 Unicode characters each; house rules allow 1,500. A checked date must be a
calendar date in ISO form and cannot be in the future when saved from the page.

Matt and User1 see these expectations on home Commander deck pages, with the
deck's declared target compared against the household aim or recorded venue
range. The panel works independently of inventory counts and card-data checks.
It shows notes as written for the pregame conversation, with their checked date
or an explicit unknown date; it neither enforces house rules nor certifies
bracket fit. Other spaces and non-home viewers do not receive the record,
including an admin outside home. No saved night adds no extra panel; a storage
failure says the recorded night is unavailable.

Each changed save is audited and checks the loaded revision. A stale form keeps
its edits and requires **Load current saved note** before saving again; an
unchanged save adds no change. **Remove this recorded night** requires a reason
and confirmation. Clearing retains the revision so an older editor cannot
overwrite a clear-and-recreate cycle. Migration `0011_commander_night.sql` adds
the singleton table, included in database exports, checks and backups; no live
migration or venue note was applied during implementation.

Overview and the Stats tab's Commander panel show the loaded Scryfall card-data
date (Game Changers and ban list) and the community effect-tag date. Unknown,
invalid, future or over-seven-day-old dates get a freshness warning; no live
check or download runs on a page read. Missing tags say **not checked**, and
unknown main-deck names make the check incomplete. Community tags are approximate.
The operator still checks current official lists before recommending cards.

### Editing on every device

The editor (`#/edit?id=<deck id>&v=target|owned`, and `#/new` for a new deck) works on every width:

- **From 600 px, any pointer** (the iPad in either orientation, a laptop, the PC): the full editor. From 1,000 px the list sits beside a sticky side panel with three tabs: **Add** (the card finder), **Stats** (the mana curve, lands, colour sources and types) and **Checks** (what's missing and roughly what it costs, problems and warnings); below that width the panel comes before the list and folds to its tabs once the deck has cards.
- **A phone** gets the **Quick edit**: compact rows with steppers, **Add cards** opening a search sheet, a line's ⋯ (printing, move, remove), Status above folded **Deck details**, the **Notes** tab and Save; **Paste a list…** is inside Add cards and offers the same Add/Replace preview. A new deck also has its title, format and "Start from". The picture look and the side panel wait for a bigger screen, and so does **Try a change** (someone else's deck, to test a change against other decks).
- **Adding cards:** type in the finder (`GET /api/deck/find`) and click a result or press Enter to add 1 ("Added ✓ (now 3)"); Shift adds 4, and a typed count ("4 bolt") adds that many. Results show a line of rules text, the A$ price and the copies owned, owned cards first; **Free copies only**, colour, type and mana value filters (under "Filters") narrow them, and **My collection** lists the cards free for this deck in its colours. "/" focuses the search; Alt+Enter opens a result in the viewer.
- **The list** is dense rows with one badge only when a card isn't simply here, or a **Pictures** look of stacked copies. "−" on a line of 1 removes it with Undo, and Ctrl/Cmd+Z takes back any change. **Paste a list…** adds or replaces the list in Arena/MTGO form, showing what changes first, with unknown names (and their "did you mean") first.
- **Notes** (a tab beside Cards) edits the write-up (the Substitutes and Notes prose), and **Mark write-up as current** removes the "Decklist changed" line, saved with the next Save.
- **Saving** saves in place with a toast (and Ctrl/Cmd+S); a review sheet opens only for blocks or a conflict. The split button's other half is **Save & view deck** (**Create & view deck** for a new one).
- **A new deck** asks for its title and format (and whose deck it is, when the visitor may add decks in more than one space: since E10-S30 an admin too adds them only in a space whose decks they see), with no size warning until it has cards, and can start from a pasted list, a precon or another deck.
- Both lists have availability checks, with row counts for free copies, incoming cards, copies used in other decks and missing copies. The deck's saved table still describes the Planned list.

Unsaved drafts stay on the device where they were made (see "Saving" under "Editing and saving decks"), unless you keep one for later on the PC.

**Drafts kept for later** (E2-S16, first slice, 2026-10-29): in the full editor of a saved deck you may save, the Save button's ▾ menu has **Save draft for later** once something has changed. It keeps the edit on the PC for your profile (this device keeps its own copy as before); opening the same deck and list as yourself on another device shows **A draft kept for later** with the device and time it was kept, the deck's saved revision it started from, and whether it or that device's own unsaved changes are newer, and offers **Resume it** (put on top of the latest version when the deck was saved since, as a device's own draft is) or **Discard it** (from every device). Saving the deck clears the kept draft that editor resumed or kept, even after the editor was closed and reopened on that device. Each write carries the draft's revision, so a device that read an older one is told and asked before replacing it. `GET /api/deck/draft?id=&version=` and `POST /api/deck/draft` (`{"profile", "id", "version", "expect", "draft" (null to discard), "device"?}`, `lib/api/deck_drafts.py`) answer only the named viewer's own draft (no admin or script reads another's), check the deck's visibility first (a hidden deck's 404) and need the right to save the deck to keep one. Drafts are not audited, in the general export or shown on Activity; removing a member fingerprints and deletes theirs with the rest of their data. They need migration `0018_deck_drafts.sql`; until `python -m decklab.db migrate` applies it, the read answers `{"available": false}` and the editor works as before, with drafts on each device only. This coding session has not applied it live. The phone's Quick edit has the same **Save draft for later** in a ▾ beside Save, shown only while there's a draft to keep (second slice, 2026-10-29). A new deck not yet created can be kept too, one per space and deck it copies: starting a new deck there on another device offers **A new deck kept for later**, and **Create** clears it from every device. `GET /api/deck/new-draft?space=&source=` and `POST /api/deck/new-draft` (`{"profile", "space", "source"?, "expect", "draft", "device"?}`) answer only the viewer's own, and only for a space whose decks they can see and may add decks to (no admin override), with a copied deck they can see. They need migration `0019_new_deck_drafts.sql`, also not applied live; until then a new deck's draft stays on its device.

### Pictures, symbols and the page's light reads

- **Card pictures:** `GET /img/<set>/<number>/<small|normal|large|art_crop>` (and `-back` for a double-faced card's back), JPEG, fetched from Scryfall on first use with its rate limit, kept in `decklab/data/images/` and cached by browsers for a week. `large` (672 px) is offered to big screens and the viewer, `art_crop` is the art the library tiles and list thumbnails use; both come from the stored `normal` address. Scryfall's 404 is answered with 404 (and remembered for six hours), its other errors with 503.
- **Symbols:** `GET /sym/<code>.svg` (`lib/api/symbols.py`) serves Scryfall's symbol pictures (`{W/U}` is `WU.svg`, `{T}` is `T.svg`), for mana costs, rules text and the play guide. The list (`/symbology`) is fetched once into `decklab/data/symbols/symbology.json` and each SVG on first use, only from `svgs.scryfall.io`; an unknown code asks for the list again at most once a week. Offline it answers 503 (for five minutes before trying again) and the page draws lettered circles instead. The answer carries a sandboxing `Content-Security-Policy`.
- **Light reads** the redesign added: `GET /api/deck?id=&version=&omit=matchups` leaves out the deck's matchups (its slowest part) until the Matchups tab opens; `GET /api/deck/cards?id=` is the picture picker's (each card of the Planned list once, the automatic cover, the cover and revision now); `GET /api/deck/find?q=&scope=all|owned&colors=&type=&mv=&id=|space=&limit=&page=` is the editor's finder (owned counts only for a space the visitor may see inventory of; `scope=owned`, "My collection", 403 otherwise); `GET /api/deck/swaps?id=&version=target|owned&card=` and `POST /api/deck/swaps` (`{"profile", "id", "list", "card"?}`, the editor's Play-now draft; a dry run) list owned stand-ins for each missing card (E2-S07: the same primary type, a shared colour, mana value within 1, free for the deck; `lib/decks/swaps.py` has the rules), only for a viewer who sees the deck's space's collection (403 otherwise, after the deck's own 404); `GET /api/deck/replacements?id=&version=target|owned&card=` ranks the same way up to 5 free pool cards that could replace a card of the list's Deck section (E3-S25, for a card Forge marks drawn and never cast), each priced in AUD with the answer's `rate`, `rate_date` and `price_date` as the stand-ins', with the same reading rule; `GET /api/deck/dual-lands?id=&version=target|owned` gives up to 5 free lands that make a colour the list's colour check finds short and another of the deck's colours, each with the basic of its Deck section it would replace (E3-S25, the Stats tab's colour sources), with the same reading rule; `GET /api/matchups?running=1` gives only the runs waiting or playing, for the top bar's pill (asked every 4 seconds while a run plays and every 45 when none does, only while the page is visible); `GET /api/activity` takes `kind=` and `actor=`.
- **Answers that grew:** `GET /api/decks` and `GET /api/deck` give each deck's `cover` (`{name, set, number, auto, img, img_small, art}`), colours and revision (the library's also an `edited` time, for Recently changed); `/api/cards/printings` gives each printing's `set_name` and picture; `GET /api/receipt` gives `today`, each row's picture and the decks that use it (beside the rows, never in them), a product's card list and the token face names; `GET /api/shopping` gives the deliveries' and the queue's cards with pictures, the home decks whose Planned list still misses cards, canonical playable-card shortfalls across those decks with explicit calculation errors, and each received delivery's open checks; `GET /api/deck/history` gives each revision's change against the one before it; `GET /api/deck` gives `played`, when the deck was last played at home, its games (the Game log's games the viewer may see) and `since`, what its list changed after the last game (from its own revisions; null when that list can't be found); `GET /api/profiles/<id>/wishlist` names a deck source's title (`source_deck`).
- **New writes:** `POST /api/deck/cover` (`{"profile", "id", "expect", "cover": {"name", "set"?, "number"?} | null}`: the Cover card line set or removed, one change, checked as a save of the deck's text; 409 when the deck changed since `expect`, its revision or sha256) and `POST /api/shopping/check` (`{"profile", "order", "component", "check"}`: one open check of a received delivery marked done, the inventory's `order.checks` resolve as `order checks --resolve`, one change; an admin's who sees home's inventory; 400 for a pending or cancelled component, 409 when it changed meanwhile). The Wishlist's POST also takes `"action": "set"` and, on an add, `notes`, `source` and `at` (its Undo).

Shopping's `POST /api/shopping/queue` takes `{"profile", "row", "state", "expect"}`: move one
existing queue row between purchase categories. `row` is the one-based `queue_row` from the
Shopping answer and `expect` its exact `queue_revision`. It requires an admin who can see home's
inventory, saves through `watchlist.set` as one audited change, and returns 409 if that snapshot
has changed. Quantity, printing, purpose, reference prices and notes stay as they were.

A home deck's **Queue missing cards…** (E5-S25, `lib/api/shopping_queue_missing.py`) first asks
`POST /api/shopping/queue/missing` (`{"profile", "deck"}`, nothing written) for each missing
Planned card with the copies already queued for that deck (source or `for`, any state; token rows
never count), the copies to add and `joins` (the state of the identical request those copies
would raise, else null), plus the `revision` it read. `POST /api/shopping/queue` with
`{"profile", "action": "add_many", "expect", "deck", "state": "ready"|"long_term", "cards": [{"name",
"copies", "joins"}]}` saves them as one audited `watchlist.add_many` change (any nonfoil printing, the
deck as source and its title as `for`; an identical request's quantity is raised instead of a second
row, keeping that row's state, which the sheet names and warns about). The cards are worked out again in the change: a stale revision or any difference answers
409 and asks for a new review. Both need a home admin who sees home's records.

`POST /api/shopping/order/change/preview` takes `profile`, Shopping's exact
`expect` revision, `order`, and either `action: "record"` with the changed
`values` (`seller`, `ordered_on`, `notes`, `sources`), or `action: "checks"`
with `component` and one `add: [text]` or `withdraw: [number]`. An admin who sees
home can confirm its opaque, thirty-minute token at
`POST /api/shopping/order/change/apply` with `profile` and `preview`. The token
belongs to that writer and listener; its revision is checked in the write
transaction. These corrections use `order.record` and `order.checks`, with no
card-data dependency or deck-table refresh.

### Remembered on the device

Per-viewer conveniences only, in the browser's `localStorage` under keys starting `decklab.` (every read and write is wrapped, so a page works without storage, as in a private window): `myDevice` (This is my device), `lastProfile`, `theme.<profile>`, the library's `library.products.open`, the deck page's `deck.cardsView` (List or Pictures), the editor's drafts (`draft.<profile>.<deck id>.<version>`, and `draft.<profile>.new...` for a new deck) and its `editLook`, `editSide`, `editFilters` and `editAddTip`, the Receive delivery board's `receiptLayout` and its check in progress (`receipt:<profile>:<order>:<inventory revision>`), `packing-order.<profile>` (Name or Storage order), `collection.rowsSort`, `tokens.filter`, `tokens.search`, `accessories.filter`, and the Matchups home's `matchups.format`, `matchups.deck` and `matchups.engineNoteSeen`. The profile chosen for this visit and when the page went into the background are in `sessionStorage` (`decklab.profile`, `decklab.hiddenAt`). Nothing that has to last or be shared is kept there.

## Collection and physical play

- **Collection** (`#/collection`) has two views of a space's cards. **Find cards** is a grid of card tiles of what's owned and on the way, two a row on a phone, with filters that apply as you type (name or rules text, colour, type, role, mana value, availability) and pagers at the top and bottom; each tile says how many are owned and free ("3 owned · 2 free"), and its viewer words say which decks hold copies, with **Edit copies**. **Card list** (`&view=rows`) is a dense, sortable, paged table of the rows themselves, with a filter for rows whose condition or language isn't recorded and **Set condition & language…**, which sets one condition and/or language on every row the search and filters show (only blanks unless told otherwise) in one change; tapping a row opens its sheet, with Remove at the bottom. More holds **Import cards…**, **Add a precon…**, **Precons we could build…**, **Download collection (CSV)** (anyone who sees the collection: the space's rows in the collection's columns, sorted by set and collector number, saved as `<space>-collection-<date>.csv`, which Import cards reads back) and Build decks. Availability separates free physical copies, incoming copies and cards held by built decks or intact products. Special basic lands are listed, but their individual deck allocations are not tracked. Import previews warn when the exact file content was already imported into this space, with the recorded date and importer (or explicitly unknown provenance). Repeating still adds the copies and records that choice. Reducing or removing copies offers an optional reason with Sold/Traded quick picks. If the physical copies left would be fewer than built decks or intact products hold, a warning names them before an explicit override; incoming copies do not cover the shortage. Uncheckable demand is also a warning, with the option to proceed.
- **Build decks** (`#/assembly`, home's pool, so Matt's and User1's only; also a deck page's More) puts up to twelve lists together. Choose the decks from a checklist grouped by status (ideas and products folded), with a **Built and being built** preset and each deck's list as a choice; the plan is worked out as soon as the choice changes (`POST /api/assembly/preview`, which writes nothing). It counts each physical copy once, and each deck's plan comes in steps: sleeves (its kit: the sleeves' picture and "Sleeve with X: 75 needed, 100 owned", any sleeve or deck-box warnings, a **Choose** for a built deck with none recorded), pull from storage, move from other decks, basic lands, tokens (a tick "Grab Zombie / Zombie Knight ×8 (Zombie side) for Zombie" for each owned card that fits, "Stand-in for Insect: ..." when only a different one is owned, and untickable lines for tokens with none owned, on the way, or that may need checking by hand), put back, pack, and what's still waiting, folded. A deck from a product kept intact shows the whole product's sleeve count. Decks chosen together that are in the same sleeves get a note saying so ("A and B are both in X sleeves: ... keep each deck's cards together"), never a block; an intact product counts once, so its own decks chosen together get no note. Cards are picture tiles with a bottom-left tick, all in one viewer group; a sticky bar says "Pulled 12 of 31 cards". **Shared tokens** lists cards two selected decks would both grab; at home keep them in one pile on the table. Token rows that can't be read are listed rather than stopping the plan. Ticks are saved on the server and shared between Matt and User1 across devices. Open plans refresh shared checks every three seconds and when the device returns from the background. Adding or removing decks keeps unchanged tasks; a changed quantity, source deck, list version or finish needs a fresh check. Each save patches individual ticks, so simultaneous checks on different cards are kept. Each deck has **Tick all card checks**, with its displayed list, card-action/copy counts and selected physical recipe's scope. It checks that deck's unchecked card actions, including returns, while kit/token checks and other decks stay unchanged. Its Undo preserves previously checked cards and later individual changes on this device, and stays usable after changing card order. Bulk checking waits for loaded, saved progress and is unavailable while previewing, reviewing a build or handling a save error. It does not resolve missing cards or finish a build. Clear and Undo affect only the displayed checklist. Failed saves keep visible work and offer Retry; Mark as built waits for progress to load and save. Older browser-only ticks are not copied over shared progress. Checking a card alone does not change a deck. After every card task is checked, **Mark as built** (or **Mark N decks built**) in the bottom bar saves the assembled lists together, including the chosen Planned or Play-now version, and keeps the checked cards visible. Sleeves and token ticks are optional. A changed list or inventory needs a fresh plan; errors keep the checklist and offer **Refresh plan**. Products stay read-only, and only decks the viewer may edit can be marked built. Shared checks are stored in `packing_tick` (migration `0009_packing_ticks.sql`), included in database backups and exports; task descriptions are hashed before storage and audit. **Card order** switches between Name and Storage order: creatures by white, blue, black, red, green and multicolour, then artifact creatures; spells in those colours, then artifacts; lands (including basics) by white, blue, black, red, green, multicolour and colourless; tokens last. Lands use the colours of mana they produce, falling back to colour identity when they produce no coloured mana. Colourless non-artifacts follow multicolour. Each group runs from lowest to highest mana value, then alphabetically for ties; unknown mana values come last. Each card step and storage group shows its total number of copies for checking the physical pile. Foil and etched finishes in the selected deck list have visible labels; mixed finishes show the list's quantities (the plan still allocates copies by card name). This choice is remembered for each person in this browser, and changing it keeps the ticks and progress.

- **Which printing?** on each Build decks pull tile records which printing of that card went in the box (the deck's Printings in box line, AGENTS.md has the format). It lists the collection's printings of the card whose copies aren't all recorded in other boxes; when storage can hold only one printing it's filled in ("only printing in storage"). Skipping is fine: Finish building never waits on it, and writes the choices in the same save. Fix it later on the deck page's Cards tab, **Printings in box…**. Collection then names the recorded copies' deck ("Recorded in the box") and counts them exactly; the rest keep their saved-list hints. A record a later collection edit makes impossible is kept but ignored, and the deck page shows **Printings in box out of date**.

- **Take-apart checklist** on Build decks is offered for built ordinary decks. It uses the recorded physical assembly, including all sections, basics, installed stand-ins and packed tokens, with visible sleeves/box details. These local checks write nothing. After checking every item, **Mark deck taken apart** uses the ordinary conflict-checked save to set Building and free its reservations and kit; intended lists remain. Done removes only that deck from the selected plan and refreshes the others. Missing or malformed physical evidence stays explicit; a lost save response requires Refresh before another attempt.

- **Check box** on Build decks reviews an ordinary home built deck's saved physical assembly in every section, including basics and installed stand-in markers. Counts start blank; a picture tick fills the recorded quantity, while 0 explicitly records none found. Enter extra cards by section and exact card name, then review the missing and extra cards before **Save check date**. Only the optional `- **Box checked:** YYYY-MM-DD` header is saved; observations and differences remain in the local review until Done. The private deck page says **Last box check recorded**, a historical date rather than proof of current contents. Art is representative by name and certifies no printing or finish. The intended lists, collection, kit, reservations and shared packing ticks stay as recorded. A stale or uncertain save requires Reload plan; member/product checks remain future work.

- **Review collection copies** beside a named box difference closes the local box review and discards its counts/extras, carrying only that difference as temporary context into Collection. It saves no check date and makes no collection change by itself. Check every storage location first: missing from one box does not mean fewer owned, and an extra does not establish a printing. A fresh source-deck check, collection rows and exact-name printings precede the copies chooser. Select an existing printing and enter its **total owned copies** in the blank quantity field, or use **Add another printing** and explicitly choose its printing, finish and total. A printing already listed must be reviewed through its existing row. Collection saves remain separate audited changes with the normal current-list SHA, reduction reasons and in-use acknowledgement. A changed-list conflict requires **Review listed copies** and a fresh total; this path does not replay an additive import or recreate a removed row. Named stand-ins use the physical card's name, while an unspecified stand-in must be identified first. Plain basic lands remain untracked; only special printings belong here. The handoff uses one-shot profile-scoped memory and a plain Collection address, with no observation saved in URLs or browser storage. Deck text, physical/intended recipes, kit, packed tokens and shared packing ticks stay as recorded.

- **Review a deck list** beside a named box difference first checks the saved deck and your editing permission, then offers **Open Planned list** and **Open Play-now list** only for lists that already exist. Choose explicitly; the physical build's version does not choose for you. Opening the Editor closes the local box review and discards its counts/extras without saving a date. The ordinary Editor restores or rebases your existing draft, including its earlier-address draft choices, before showing the observation as a dismissible memory-only note. The handoff applies no observed quantity, printing or list edit and makes no Built version change. Make any changes yourself and use the normal reviewed save. A source mismatch during loading/checking drops the observation and requires a fresh box check; route/profile changes or dismissal also retire the context. Intended-list edits keep the saved Assembled contents, generation, installed markers and packing state as recorded.
- **Correct the recorded box**, at the end of the difference review when you may edit the deck, records what the box really holds as the deck's physical build. **Preview corrected box** writes nothing: it lists the corrected cards by section, the cards freed for other decks and those the deck now holds (warning when the collection records too few copies, which you then fix with Review collection copies), and the packed token cards, which stay as written (with the tokens the corrected cards no longer make, or now also make). **Save corrected box** saves the corrected Assembled snapshot, installed stand-ins and the check date as one conflict-checked change, bound to the preview, and lists other decks whose tables are now out of date. Recorded printings are kept up to their copies; further copies are recorded without a printing. The Planned and Play-now lists, the collection, the kit and the Token cards line are unchanged. A stand-in counted in a section other than its card's, or an extra card that is also an installed stand-in, is refused rather than guessed.

- The Library's **Box check date** filter offers **Any check date**, **No check date recorded**, and **Checked before.** for ordinary built home decks whose inventory the viewer may read. Choose the cutoff date explicitly; only earlier dates match, so a check on that date is excluded. There is no automatic age or due-date policy. Missing, malformed or duplicate saved dates count as no reliable date recorded; decks outside this scope or without check-date information are excluded rather than labelled unchecked. The selection appears in the address, combines with the other Library filters, and is retained through the phone's filter sheet and Back. The selected deck shows its historical date, which does not establish its current contents. Filtering changes no deck or collection data.

- **Finish building** reviews the assembled list, sleeves and deck box before the final save. Changing Planned / Play-now returns to the plan for fresh checks. Kit choices, built version, installed stand-ins and the affected availability tables save together in one change; cancellation writes nothing. The picker shows sleeves needed, owned and spare or short, plus deck-box capacity. Only the kit's owner may choose it. Other built decks and intact products keep their reserved cards: add a donor deck with its revised saved list to plan a transfer.
- **Main deck and sideboard**: a selected ordinary deck offers **Main deck only**, **Main deck + whole sideboard**, or **Choose sideboard cards**, with each intended card's quantity as the limit. The full main is always included; Commander and Companion sections are retained too. A missing sideboard copy omitted from this recipe does not block the main build. This is the final physical recipe: reducing an already packed sideboard adds required **Put back** actions, including basics and anonymous spare stand-ins, and the finish review names the returned cards. Adding sideboard copies later keeps unchanged main cards in place. Products keep their complete lists.
- **Physical build and remaining intent**: packing stores the chosen logical card recipe in a protected `Assembled` header in the deck's database text, alongside an `Assembly generation` counter. Installed stand-ins determine the actual named physical copies. Both intended lists remain unchanged: **Still intended for this deck** shows unassembled real cards, intended quantities, missing and incoming copies separately. Owned-but-omitted cards do not become purchases, and no wishlist or queue row changes automatically. The library and deck Overview show actual main/sideboard counts, with the existing inventory permissions. Reservations, kit counts and built token summaries follow the snapshot. An ordinary intended-list edit keeps physical cards in place; a legacy built deck freezes its former physical list on the first such edit. Change a snapshot deck's built list through packing. Taking it apart clears installed assembly/markers, preserves intended lists and saved marker choices, and advances the generation so rebuilding needs fresh checks. Keep these protected headers when pulling/pushing text; stale raw saves cannot remove or replace them while the deck stays built. No database migration is needed.
- **Choose stand-ins** in a packing plan saves physical markers for missing cards, separately for Planned and Play-now lists. A named marker consumes a free owned physical copy; **Any spare card** uses an untracked spare basic. Suggestions do nothing until saved, and saving choices does not install or reserve them. Marking built installs the checked physical recipe. The logical decklist, card rules, shopping shortages, Forge lists and game records still describe the represented card. Overview and **Print play sheet** show the mapping only to someone who may see the deck's inventory. A real card's arrival does not silently free a still-sleeved marker: the next plan uses the real copy and records the return only when explicitly finished.
- The library's **Planned list availability** filter offers all cards here, cards on the way, cards to get and availability needs checking. A zero shortage is not a readiness claim when inventory identities or counts need checking.
- **Game log** (`#/play`, also a deck page's More) records actual 1v1 games. **Record a game** is two deck pickers (each player's last deck to start with; from a deck page, that deck on its player's side) and big "Matt won / User1 won / Draw" buttons; the date, names, mulligans, sideboard plans and notes are under **More details**. A tap asks the server for the record's review at once, shows it in a toast with **Undo** for 8 seconds, then saves it with that review (at once if the page is hidden); each game has **Correct this game** afterwards. Results read "<name> won". Each game keeps snapshots of both lists. **Sideboard plans** record equal quantities in and out for a particular opponent and list; a game can record the resulting sideboarded list. Changed lists make old plans visibly stale. Correcting a game and sideboard plans keep their preview-and-confirm step, and concurrent changes refuse the save. Each record is a row of the database's `play_record` table, and each save ("Save game A vs B", "Save sideboard plan A vs B") is a change set in the audit trail, shown on the Activity page. While the database can't be reached the Game log and its saves answer 503 (before any deck is read). Each viewer sees only the games and plans with a deck of their own space (see "People's own collections").
- **Tonight's pairs** (E1-S28, above Record a game, for Matt and User1 only) suggests up to three ready pairs of home's built casual decks, one for each player: evenest first (the two decks' real record once they've met 10 times, else Forge's saved result for their built lists, else unknown), then the pair met longest ago, each with its reasons. A deck is ready when its built list has every card here. **Use this pair** puts both lists in the quick record's pickers; nothing is saved (`GET /api/play/pairs`, `lib/play_pairs.py`).
- A deck's **History** (`#/history?id=`, the deck page's More) lists its saved revisions, newest first (numbered from 1, with who saved each, when and its message; those imported from git in phase 4 also show their commit), each with what it changed against the revision before it, worked out by the server: "+2 Rabid Gnaw, −1 Shock", "1 Second Breakfast → sideboard", with the cards' pictures, and the header fields. Saves that changed neither the cards nor the header (the write-up, the table) are folded into one line. Tapping a revision opens a sheet with all of it, a comparison with the deck now, and, for someone who may save the deck, **Open … as a draft**, which opens its list in the editor (the Quick edit on a phone). It preserves current metadata and written notes; saving uses the usual checks and saves a new revision. An existing local draft must be explicitly replaced. The latest 100 revisions are shown. An old link naming a git commit still opens the revision imported from it. A retired deck's History page stays readable, with its last title, saved lists and deletion record. An authorised editor can restore its last saved text under the same id; the restoration adds a revision and rejects a stale deletion record or an id already in use. Historical lists stay read-only while the deck is retired; list-as-draft restoration remains for current decks. A revision that changed the deck's Sleeves or Deck box shows its message only to whoever saved it.
- **Rename deck…** in a saved deck's More changes its title and derived address within the same space and format. Preview shows both titles and ids before confirmation. Cards, build status and kit stay unchanged, including on a built deck. One audited rename adds a revision; old revisions, captured games/results and purchase-source strings stay unchanged. Former addresses stay reserved and resolve to the current page/history. Forms still naming a former address must reopen before saving; old-address drafts on this device are offered for explicit recovery. Packing checks need confirming again after rename. Migration `0010_deck_aliases.sql` enables rename (`python -m decklab.db migrate`); without it existing reads and saves still work. Exports, nightly checks and backups include aliases.
- **Retire deck…** in a saved deck's More requires a reason and confirmation. It is offered for editable unbuilt decks; the server also refuses built decks and held sleeves/boxes. A current SHA and revision guard against edits or id reuse after confirmation opened. Success links to retained History, where **Restore deck** can recover the last saved lists and notes under the same id. Retirement and restoration are each one audited database change. Collection cards, purchase intent and captured matchup results stay in place.
- **Deal a hand** (the deck page's Practice tab) deals seven from the list shown ("Opening seven. Keep or mulligan?"), with London mulligans, bottom-card selection and later draws, the hand sorted, with its land and spell counts and card pictures. Commander, companion and sideboard cards stay outside the library. For a Commander deck, **First mulligan is free (multiplayer)** does what it says. It's local to the page and never changes cards. See [Wizards' London mulligan explanation](https://magic.wizards.com/en/news/announcements/london-mulligan-2019-06-03). Under it, **Practice games** shows how the mana holds up over 100,000 simulated games (see "Start it").
- **Copy decklist**, **Download decklist** and **Print play sheet** (the deck page's More) use the list shown, Planned or Play-now. Print includes written guidance and any stale-guide warning, and for a Commander deck an **At the table** part (E9-S27): the Overview's bracket sentence, the Game Changers, mass land denial and extra turns found, the two-card combos as text, the checks' limits and the data dates, all from the facts the page already loaded (or a note that the Commander checks weren't loaded).

- **Life counter** in Game log starts a new two-player counter for the chosen lists and names: 20 life, or 40 with a Commander. Use life taps/holds or ±5, optional poison, separate commander sources, Concede and Undo. Partners and damage from your own commander are counted independently. Terminal taps/concessions open the ordinary result form; a held terminal count waits for its matching foreground release. Cancelled gestures leave **Record result** available. The form still needs explicit **Review game** and **Save game**. **Resume life counter** keeps a local counter for the same profile/collection for up to two days, even if a list has changed or disappeared. Recording then requires explicit current list replacements; changed selected sideboard plans need acknowledgement too. Prior saved aggregate games remain under **Resume legacy life counter**, with their counts unchanged; new counters use separate storage. The clock and visibility changes never save a result.
- **Commander pods** in Game log records three or four players, with at least one saved Commander deck from your collection. Choose a saved list or an external opponent for each seat, enter optional external commander labels, then choose a winner or draw, date and notes. **Review pod game** shows the exact record before **Save pod game**. Closing the form never saves it. **Correct this pod game** keeps unchanged historical lists, and changed records or selected lists require a fresh review. Pods have their own section and count, including on a deck's Game log; they never contribute to 1v1 Head to head, comparison totals or quick-record defaults. Pod form drafts stay only in the open form.
- **Start pod counter** in a new pod form keeps life for three or four seats, starting at 40. Use life ±1/±5, optional poison, Concede and separate commander-damage sources; open a seat's damage disclosure to adjust them. Partner commanders and damage from your own commander stay separate. An external opponent starts with one literal or numbered source; add a second explicitly. One player going out leaves the others playing. The last remaining player or an explicit End game fills the normal pod result form, which still needs **Review pod game** and **Save pod game**. Closing keeps the local counter for **Resume pod counter** in this browser, under the same profile and collection, for up to two days. A changed or missing saved list keeps its counts but requires an explicit current replacement before recording. Failed or uncertain saves keep the counter. The existing two-player counter is separate.
- **Preview post-board list** on a saved Sideboard plan (Game log or the deck Overview) checks that the record and both visible lists are still exact. It shows per-section printing/finish changes and the full proposed list without changing the deck or plan. For known matching formats it also shows fresh paired-game upper bounds; mixed or unconfirmed formats keep the list preview with no numeric game guide. Saved games and simulation setup are not checked, remaining games are unknown, and this action starts no test. Changed or unavailable lists require reviewing a new plan revision.
- **Testing a sideboard plan** (E4-S16): with a proposed game guide, the preview's **Start quick check** or **Start play until ahead** (`POST /api/play/sideboard-test`) checks the plan and both lists again, then the simulations setting (its reason shows under a disabled Start) and the variant tests' own checks, and plays the post-board main list on the base list's games against the opponent as a paired test of a change: its page (`#/variant?test=...`) gives Better, Worse or Makes little difference. Games are best of one, so the sideboard itself isn't played. **Tests of this plan** (`GET /api/play/sideboard-tests`) lists the plan's tests with their verdicts, each marked "For an older list" once either list's cards, or the saved plan's lists, have changed. Only the plan's own space sees them.

- **Review undo** on Activity also restores one deleted token-card row (2026-10-29): the latest standalone deletion in your own space, as a new row. It shows the exact historical row and its physical quantity; **Save Undo** stays disabled until you confirm you still have the whole recorded quantity. Later token changes, possible duplicate identities, uncertain pairing or a packed line that could claim the card refuse. The restored row gets a fresh id and earlier packing doesn't reconnect; surviving cards, decks and products stay as they are. A change that deleted 2-50 token-card rows and nothing else restores the same way as a whole: the review lists every row and the whole physical count, one checkbox confirms them all, and nothing is restored unless every row can be; a refusal says how many rows can't and why (more than 50 rows refuse too).

## People's own collections (spaces)

Each profile in `decklab/config.json` has a `space` (`lib/spaces.py`). Matt and User1 share `home`: the shared collection, token cards and decks, with the products, orders, receipts, accessories and watchlist, which only home has. User2, User3 and User4 each have their own space: a collection, token cards (with their raw imports) and decks, all in the database. Nothing is made in advance: a space with no rows reads as empty.

**Members** in Settings is private to a named home admin. To replace an email, choose an existing member with their own space and the exact address to replace, enter the new address, then **Review email change** and **Save email change**. Other aliases, the member's identity and space, their records and unrelated configuration values are preserved. Addresses are normalized and checked for valid ASCII syntax and duplication across profiles. The panel cannot edit a home profile or change an existing role or space. It refuses legacy configurations without explicit roles, active configuration overrides, invalid profiles and configuration/database mismatches rather than guessing a repair.

**Add member** asks for a display name, a permanent member id and one sign-in email. The id uses lowercase letters, digits and single hyphens, up to 40 characters, and names the member's own space; reserved or previously used identities are refused. **Review new member** shows the exact identity, address, Member role and empty Private space before **Save new member**. The server fixes the role to Member and the space to that id; the browser cannot choose admin or home access. Collection, decks and games start Private, with no inherited cards, records or visibility choices. Existing membership, departure markers, retained private data, audit history and Forge references block reuse rather than being erased or adopted. If those checks are busy or unavailable, creation is refused until they can be checked safely.

Each save binds the complete raw configuration and current database membership reviewed by the panel. One audited database change names the actual signed-in web actor; only its verified outcome authorizes publishing the changed configuration. Creation appends one profile to the raw configuration and inserts exactly its space, profile and email rows; unrelated configuration values remain. A same-address email save confirms a no-op. Stale or unconfirmed outcomes require **Reload member emails** before another review, and creation is never blindly replayed. Email aliases and receipts stay in this panel's lifetime, outside the ordinary roster, page addresses and browser storage. After a confirmed save, the panel names the address to add separately to Cloudflare Access and asks for a sign-in check; Deck Lab has verified neither the Access policy nor sign-in.

If a member update is interrupted, a private pending journal prevents profile/authentication reads from trusting a partly published change. Run `python -m decklab.db sync-profiles` locally to reconcile the exact audited outcome before normal synchronization. Creation recovery verifies its original append recipe and exact three-row INSERT audit, and rechecks that no retained data has occupied the identity. Inventory and cooperative Forge claims protect the normal commit-to-publication interval; they are released when the operation closes. Recovery never overwrites a configuration changed independently after the reviewed edit; an unresolved mismatch keeps the gate closed for local inspection. Do not delete the pending journal to clear the warning. This is process-crash recovery across the configuration file and database, not a hardware-atomic transaction.

- **Deck ids:** a home deck keeps `casual/<slug>` or `commander/<slug>` (and `product/...`, `pairing/...`), so saved results and links keep working. A person's deck is `<id>/<kind>/<slug>`, such as `user2/casual/elves`. Every library summary says its `space`.
- **Owned vs needed** is worked out in the deck's own space: that space's collection, minus the cards its own built decks hold. Nothing is ever on the way in a person's space. Tokens work the same way: a person's deck is matched against their own token cards.
- **A person's deck** has no `Played by` line, since it's theirs by its space, and no `Sleeves` or `Deck box` lines, since accessories are home's. Deck Lab refuses to write them there. A person's decks stay out of home's Build decks plan. Their Forge field uses their own space plus public spaces; matchups and field runs require visible sides, and variant tests require an own-space base.
- **Roles** (`lib/profiles.py`, `lib/permissions.py`): an `admin` edits everything in his own space (every deck there, its collection and tokens, its tables and its games) and, at home, the receipts, orders and products; since E10-S29 (2026-10-18) the role opens nothing in another space, on the page or through the API, so Matt asks Claude for upkeep in a member's space and the command line still writes every space. A `member` edits only their own space, or (at home) the decks Played by them and, since E10-S43, home's collection and tokens as Matt can. A config where no profile names a role is an older one, so every profile is treated as an admin, unless it has an `access` block (then a missing role means member); and while no profile names a role, no one can sign in through the tunnel. On the home network the profile picked on **Who are you?** has the same rights as through the tunnel (since 2026-10-13): User1 picked there can't change Matt's decks. A write names its profile in its body, and when the page's `X-Deck-Lab-Viewer` header names a profile the body must name the same one ("You can only make changes as yourself"). Only a script naming nobody may change everything (see the next point).
- **Only scripts read everything; the chooser offers home profiles only.** A script is code outside a request or an unnamed loopback request on the home listener with `X-Deck-Lab-Script: 1`. The tunnel never honors that header. Other unnamed home readers see Public data only and have no write rights. The home chooser offers Matt/User1; a member profile named on that listener receives 403 "Sign in through decklab.example.com". Members sign in there from home too. `/api/me` follows the picked viewer, is refreshed after a pick/visibility change, and never grants an admin another space's private data.
- **Profiles and spaces an outsider can see** (E10-S38, 2026-10-18; `settings.profiles`): `GET /api/profiles` gives a viewer only their own space's profiles (`id`, `name`, `role`, `space`, `plays_as`: Matt's and User1's for either of them, only himself for User5), then each profile of a space with something public by `id` and `name` only (`settings._public_spaces`: public collection/decks/games or a public kit owner), and `"admins"`, the admins' display names only, for "ask Matt" wording (`adminWords()` in `web/core.js`; empty in an older config where everyone is an admin). The home page before **Who are you?** gets the home profiles it offers, a script naming nobody everyone, a login that isn't set up nobody; the page asks again on every pick at home. No refusal names a space or person the viewer can't see: a collection's or tokens' 403 is "That collection isn't public." for home's too, home's records' "The shopping list, deliveries and packing plan are private.", the accessories' "The sleeves, deck boxes and playmats are private.", Commander-night notes' "Commander-night notes are private."; a new deck in a space whose decks the viewer can't see, or one that doesn't exist, gets the same 403 (`guard.HIDDEN_SPACE`); a deck id in a space that doesn't exist gets the missing deck's 404, "No deck '…'" (the space's 400 only to a script); and another profile's settings or wishlist and a profile that doesn't exist answer alike.
- **The server checks them on every write** (`lib/api/guard.py`), with 403 and the reason in plain words: deck create and save (the editor still opens for anyone, without Save, for "Try a change": `GET /api/deck/edit` says `editable` false with the reason in `why_not`, and checking a draft or pasting a list stays open); table updates (decks the profile can't change are left out and listed as `skipped_not_allowed`); games and sideboard plans (one of the profile's decks must be in it, before and after, an admin's too; in a game with decks of two spaces each space changes only its own side and the date, result and notes only the space that recorded it, and a sideboard plan only its deck's space changes: 403 otherwise; every deck a save names must be one the profile may see, 404 "No deck <id>" otherwise, and a record it may not see answers 404 "No play record", a stale sha256 too: E10-S32); receipts (a home admin only, and a profile that sees home's records); accessories (each home profile its own and the shared ones, admin included; choosing a deck's sleeves or deck box also needs `deck.edit` on that deck and on a move's source deck); tokens and collection edits, imports and Add a precon (only the space's own people: home's Matt and User1, a person's only that person; a write to a space the writer can't see gets the hidden collection's 403, "That collection isn't public.", with only `{"error"}`, before its sha256 is looked at: `guard.require_space_write`); wishlist and settings (their own; an admin also those of his own space's profiles, none of another's). Matchups, field runs and tests of a change can be started by anyone unless an admin has limited them (see "Pausing simulations" under Matchups); a visible run may be stopped by its starter (private profile id), a person with an own-space deck in it, or an admin. Admins can stop hidden runs through anonymous opaque-key controls. Public visibility never grants deck, inventory or kit write rights. A write naming a deck the profile may not see (below) answers 404 "No deck <id>" before any 403 or 409. A new deck goes in the profile's own space unless the request names another, and only in a space whose decks the profile sees (403 before its name is looked up, so a taken name never tells about a hidden deck; the precon preview's `exists` likewise). `GET /api/me`'s `"may"` says what the visitor may change, so the page can hide the rest.
- **The inventory is read by space** (`permissions.sees_inventory`; `"may"`'s `see_inventory`, the spaces the visitor sees or null for all): a space's collection and tokens by its own people or read-only when its collection switch is Public; the admin role opens no other private space. Home's records, its orders, products, watchlist, checks, receipts and packing plan, are `permissions.sees_home_records` (`"may"`'s `see_home_records`): the home profiles only, never anyone else even once home's collection can be made public. So **Shopping**, **Receive delivery** and **Build decks** are left out of User2's, User3's, User4's and User5's navigation (an address opened anyway shows a notice instead), and the server answers 403 to `GET /api/shopping`, `GET /api/receipt` and its preview and apply, and `GET /api/assembly` and its preview. The **Collection** and **Tokens** pages offer only the spaces you may see: `/api/collection`, `/api/collection/rows`, `/api/tokens`, `/api/precons/preview` and `/api/precons/coverage` answer 403 for another, "That collection isn't public.", naming no one, the same words for a space that doesn't exist (only a script naming nobody gets 404 "No space"), and `/api/collection`'s `"spaces"` lists only yours. `/api/precons/preview` also needs `collection.edit` there, so no deck id of a space you can't add to is probed. Inside those answers a deck is named only to a viewer who may see it (else "one of the home decks", with no id, hidden ones merged): the Collection page's holders, the Tokens page's uses and missing decks, and a held space's warnings and unknown cards on the Tables out of date list; pool warnings about a deck (`pool.Pool.warning_decks`) go only to whoever sees that deck, and those about home's orders and products only to whoever sees home's records (`library.visible_warnings`, `visible_unresolved`); the Tokens page's pending token orders go only to home's records' viewers. The printing picker's owned and on-the-way counts (and the copies search shows) are your own space's, never another's (none for a visitor with no profile, home's for a script), and so is the default printing in "Paste a list"; the card finder (`/api/deck/find`) counts its `id` only for a deck you may see, and a `space` named outright answers 403 "That collection isn't public." unless you see its inventory, as a missing one does. Deck pages and the library follow the same rule (since phase 4, the user's decision): whoever may see a deck (see the next point) sees its list, prose, stats, practice hands and matchups, but only a viewer who may see the deck's space's inventory gets its owned-vs-needed part (`/api/deck`'s `owned`, `table` and `tokens` are left out, not null), the deck page's availability banner and card marks, the library's readiness chips and token lines, the Play-now list's availability, the editor's table note (`/api/deck/edit`'s `table`) and the out-of-date tables list (`/api/tables/stale`, its blocked decks, and a save's `stale_tables` list only decks you may see, of the spaces whose inventory you may see; home's pool warnings go only to those who see home). Until E10-S28's switches make a space's decks public, a deck is seen only in its own space, where its inventory is seen too, so this matters once a space's decks are public and its collection isn't. "Try a change" (`/api/deck/check`) leaves out the pool of a space you may not see, and its default printings then don't follow that space's copies. On the home network reads follow the profile chosen (the `X-Deck-Lab-Viewer` header; home profiles only); a script naming nobody sees everything and any other request naming nobody nothing; through the tunnel a login that isn't set up sees nothing. The PC's command line (`python -m decklab.db`, `sql`) isn't bound by this and reads every space.
- **Deck visibility** is own-space or Public (`permissions.sees_deck`). Public means every deck's text as written, including Play-now and prose notes; computed inventory still needs its collection switch. Owned product decks/pairings may be public with home decks; pending products remain home-only. Hidden deck routes answer the same 404 as missing decks before other checks. Saved Forge evidence resolves only through visible aliases or identical current lists, every side is filtered, and fields/ratings use visible opponents only. History subjects and other-space actors are masked on the server, including "Tables refreshed" without order ids.
- **Game log visibility** follows the record's own spaces or a Public games switch. A hidden deck side has no id, list or plan; public records are read-only outside their spaces. Each space edits its own side only, and the recording space controls date/result/notes. Sideboard plans remain owner-only even when games are Public. Activity is always own-space (with system rows for admins), independently of Public switches; web and CLI messages/reasons require every underlying row to be readable.
- **Pod privacy:** every captured deck belongs to the recording collection. Player and external commander labels, notes and the saver stay private to that collection even when its games are Public; other viewers see numbered players and only decks they may read. A Public deck switch alone never publishes games. Activity uses a generic player-count summary and stays within the collection. A departing member's pods are removed whole through the existing guarded removal workflow. Pod recording needs no new migration.
- **The page's code names nobody** (E10-S39, 2026-10-18): every file served from `web/` is read by anyone signed in, so its examples and comments use neutral names (Alex, Sam, Jordan) and decks (Boros Burn, "Krenko, Mob Boss: Goblin Horde"), never a profile, a household deck or a real result. `tests/test_web_no_personal_data.py` reads every served file (`server_http.static_files`) and fails on any profile id, name or email in `config.json` and any of the household's deck titles: the test fixtures' deck texts, the `pre-db-decks` tag's deck files, a list kept in the test (never in a served file), and every deck in an export when `DECKLAB_DECK_EXPORT` names a folder (`python -m decklab.db deck pull --all -o <scratchpad>/decks`, then run the test with `DECKLAB_DECK_EXPORT=<scratchpad>/decks`), which catches a deck made since without editing the test.
- **Accessories** are private by owner unless that owner makes them Public. Public rows group by owner and are read-only; only own/shared rows are offered for picks, writes or image staging, and save hashes cover writable rows only. Hidden holders use generic words without ids/products. Pictures use new versioned addresses, private/no-cache headers and permission checks before 304 responses, so revocation takes effect on the next request. Matt's admin role never grants User1's write rights.
- **Collections are edited on the Collection page** (`lib/api/collection_edit.py`): pick a space, then on **Card list** add a card, or tap a row to change it or remove it (at the bottom of its sheet), or import a CSV with More's **Import cards…**. `GET /api/collection/rows?space=` gives the space's rows and a sha256 (of the rows written out in the collection's columns, so the page can tell when they changed); `GET /api/collection/download?space=` gives them as the collection's CSV text with a file name, for More's Download (403 as the rows); `POST /api/collection/save` changes one row (`add` of a listed printing adds to its quantity); `POST /api/collection/bulk` sets the condition and/or language of the rows it names (`only_blank`, true by default, leaves rows that have one), as one `collection.apply` change (`edit 91 rows in the home collection`), and writes nothing when nothing would change; `POST /api/collection/import/preview` reads an upload and `.../import/apply` merges it. Each change is one change set in the audit trail (shown on the Activity page), such as `add card Llanowar Elves (FDN 227) in User2's collection` by User2, or `import 42 cards into the home collection from manabox.csv` by Matt. A save to rows that changed since the page loaded them answers 409 with the rows as they are now. A save or import doesn't refresh any deck's table: its answer's `stale_tables` lists the space's decks whose tables are now out of date, and the page's message says how many, with **See them on Decks** (the Decks page's Tables out of date list, where Update all refreshes them). Recorded orders and products still arrive through receipts. On the PC, `python -m decklab.db collection merge FILE [--space S] -m MSG` merges a file in the collection's columns the same additive way, warns about exact-content repeats and records them in the audit message; `collection edit SET NUMBER FINISH --expect SHA -m MSG` changes one row's quantity, condition, language or notes (0 removes it, with `--reason`), with the page's row checks and in-use warning (`--allow-in-use`); `collection apply FILE --expect SHA -m MSG` does that for many rows at once, making the collection match an edited copy of `collection list`'s output in one change (rows at quantity 0 removed, with `--reason`; a row left out of the file is refused unless `--remove-missing`; it never adds a row); `collection trade --out GAVE.csv --in GOT.csv [--with T] -m MSG` records a trade as one change, the copies given lowered or removed and the cards got merged in, its message naming both sides (held copies need `--allow-in-use`); `collection list` prints a collection (and its sha on stderr, for edit's and apply's `--expect`) (AGENTS.md, "The inventory"). A changed import history requires a fresh preview. Held-copy overrides are bound to the exact change and both inventory/deck revisions and checked again inside the write transaction. Collection sheets close on navigation, profile changes and the away lock.
- **Where added copies go** (E7-S15, 2026-10-28): after a Collection CSV import or explicit single-card **Add**, **Where these go** groups only its newly added printing copies by waiting deck and storage. An Add into a listed printing uses the increase, not the row's whole quantity. Card list keeps the guide in its message; Find cards uses the existing one-use reload notice. Edits, quantity increases through Edit, swaps, reductions and removals do not gain addition advice, and Add creates no raw import. Page precon adds show the same guide in the new deck's saved box. Suggestions use the exact saved deck lists and stock; a proved new built precon receives its new physical holdings first, then remaining additions share one allocation with existing free copies used first. Every new printing copy appears once, with token cards separate. Suggestions assign no cards and change no deck, packing, status or location. Unknown/incomplete calculations say **Destination unknown** while the addition remains saved. The frozen profile/space-bound page guide shows at most 100 printing lines across groups, with Show more for the remainder. A real CLI `collection merge` prints the same saved-snapshot grouping after its existing counts, retained-import paths and stale-table notes, up to 100 printing lines with explicit omitted counts; zero tracked copies says nothing to file. Advice, formatting or optional output failures keep the saved merge and successful exit, never suggesting it be repeated. Dry-run output and CLI precon output are unchanged. CLI actor attribution does not limit selected-space allocation; when relaying a member's upkeep outside their space, report only counts and completion.
- **Storage locations** (E8-S22, 2026-10-28): a collection row may record where its unsleeved copies are kept, one line of at most 40 characters such as `Row 2, B` or `Binder` (whitespace tidied; no control characters, no `= + - @` start). The card sheet's **Storage location** field sets or clears it (suggesting Row 1 to Row 4 and the space's locations already used), as part of that row's one audited save (`POST /api/collection/save`'s optional `location`; left out, an edit keeps it, and a changed printing or finish takes it along). The Card list shows it after each row's storage words ("In storage · Row 2, B"), and **Build decks** names it on each tile to pull from storage and to put back (`GET /api/assembly`'s `storage_locations`, every recorded location of that card's home rows, since the plan allocates copies by name). A location goes with its row: removing the row removes it. The rows answers carry it apart from the rows (`locations: {ready, sha256, rows}`), so the rows' sha256 and `collection list`'s CSV stay the collection's eight columns, and merges, `collection apply` and the page's import read the same files as before. On the PC, `collection edit SET NUMBER FINISH --location "Row 2, B" --expect SHA -m MSG` sets one (`""` clears it) and `collection locations [--space S]` prints the located rows as CSV (`set,collector_number,finish,name,location`). The database keeps it in `collection_card.location` (migration `0016_collection_locations.sql`); `inventory export` writes it as each space's `locations.csv` beside `collection.csv`. Before that migration is applied the page and commands keep working with every location blank (the card sheet's field says locations aren't available yet, Build decks says the same, and `collection locations` says why), and saving a location is refused with nothing written. Undo never changes a location: a row update that changed only one isn't offered, nor does it block undoing an earlier change to that row (the "changed since" checks skip location-only updates), and a removed row Undo restores (a trade's given-away row) comes back without its location. This coding session has not applied migration 0016 live: run `python -m decklab.db migrate` on the PC (it adds the column with every row blank; no data is written, and no restart is needed for it, though the code that reads it needs the usual restart after its commit).
- **Bulk storage locations** (E8-S23, 2026-10-28): Card list's **Storage location** filter offers All locations, No location recorded and each recorded location, combined with search and the existing filters. A chosen location stays selected even when no rows match. **Set storage location** has separate shown-row and selected-row actions, using the same row checks as condition/language batches. The review lists every printing, its copies and its old/new location; choose Assign one location or explicitly Clear recorded locations. Only those exact printing keys can be saved. The `POST /api/collection/locations/bulk` route checks both `sha256` (collection rows) and `locations_sha256` under the backend write lock, even for a no-op. A conflict refreshes and narrows the reviewed keys, then needs another Save. Each real batch is one audited location-only change, with no changes to card quantities, condition, language, notes, decks or holdings, and no deck-table refresh. An unreadable/invalid location source or missing database capability disables the action. Batches are bounded to 50,000 keys and 4 MiB including the profile field; oversized reviews ask for a narrower scope. This implementation has not applied a household migration or restarted the server.
- **The storage box's count** (E8-S19, 2026-10-28): home's Card list says how full the 4-row storage box is: "Storage box: about 1,234 of 2,400 cards", the copies not held by built decks or intact products (the In storage only counts), with basic lands left out since their copies in decks aren't tracked, and copies whose location isn't one of the box's rows (such as `Binder`; no location, or one starting `Row N`, counts as in the box) left out and named. Over capacity it says so in a warning box. The capacity is `config.json`'s `storage_box_capacity` (a whole number; 2,400 when it isn't set). Rows answers carry it as `storage_box` (`{cards, capacity, over, not_counted, elsewhere}`; null outside home or when the copies in decks can't be worked out).
- **Add a precon** (the Collection page's More, `lib/api/precons.py`): search the paper precons MTGJSON lists (by deck, set or type), see what it adds (its cards as tiles), then add it: its cards go into the space's collection (plain basics left out, condition and language blank) and its list becomes a built deck, both in one change set (`import 66 cards into User4's collection from the Keen Engineering precon; new deck Sai: Keen Engineering` by Matt), so either both are saved or neither is. The new deck's table is worked out with the precon's cards already in the collection. `GET /api/precons?q=`, `GET /api/precons/preview?file=&space=`, `POST /api/precons/add`. The lists and decks are cached in `data/mtgjson/` for a day; when MTGJSON can't be reached the old copy is used, and it isn't asked again for 10 minutes. A precon with a card the local card data can't match can't be added until the data has it (it updates weekly), nor can one whose list breaks a rule every new deck is checked against (the preview says which). A display commander that's a real card (the foil-etched copy in precons from 2022 to mid-2024) goes into the collection but not the deck; an oversized or thick-stock one is only counted. Its token cards can be included with the unchecked **Add its token cards too** choice. Review a physical quantity for every source entry: unknown counts stay blank, and 0 explicitly skips one. Choose one checked front when an entry names two faces. Count a physical card once across paired-face entries, setting the other entry to 0. Each positive entry stays a separate row with printing, finish and reverse face unknown; no pairing or extra card is inferred. Malformed or unchecked names block only the optional token batch. Token and source changes require a fresh preview and a new choice. After an add, the deck page opens with the box a new deck gets (its warnings, such as no sleeves yet, and other decks' tables now out of date). On the PC, `python -m decklab.db collection add-precon CODE [--space S] [--title T] [--played-by P] -m MSG [--dry-run] [--add-tokens] [--token-rows FILE --tokens-source-sha256 SHA] [--actor P]` makes the same change in any space (E10-S36: since E10-S29 the page lets nobody write in another's space, an admin included, so a member's precon is upkeep Claude does when asked): it runs the page's own code (`precons.plan_add`, with no profile's rights asked, as the command line writes every space), so the cards, deck text, table and refusals are the page's; `--dry-run` prints the cards and the deck and saves nothing; `--add-tokens` includes the token batch in that same change and reports token counts separately. For physical confirmation, `--dry-run` prints the public source entries and full source SHA; give `--token-rows FILE --tokens-source-sha256 SHA` with `--add-tokens`, using UTF-8 CSV columns `source_row,front,quantity`. Include every offered entry exactly once, with its checked front and a whole quantity (0 skips). The full SHA binds those entry meanings; the file and MTGJSON cache are kept unchanged. Without a choice file, only the older fully declared, unambiguous batch can be added; a taken deck name is refused naming the deck that has it; the last line gives the counts added and the deck id. CODE is MTGJSON's file name, which `collection precons [WORDS]` lists. Exit codes 0 done, 1 refused, 2 the database can't be reached.
- **Precons we could build** (the Collection page's More, E1-S24, `lib/precon_coverage.py` and `lib/api/precon_coverage.py`): MTGJSON's paper precons ranked by the share of each one's cards (plain basics left out) that have a copy free in the space's pool (owned or on the way, not held by a built deck or an intact product), best first, then the fewest cards to find; filter by format (Commander or 60-card) and kind of deck. Opening one lists its missing cards with estimated AUD costs, stating the rate and the dates, and **Start a deck from it** makes a new idea deck with its list (as **New deck** does: `deck.create` in the space), opening it; nothing is added to the collection. Only those who may see the space's inventory get it (the Collection page's 403 otherwise), and nothing names the decks holding copies. Ranking every precon needs every list, so they're kept in a compact index, `data/mtgjson/coverage.json`, filled in a background thread from MTGJSON's AllDeckFiles archive (one streamed download of about 150 MB, never saved, read again after 30 days) and, for decks listed since or released in the last 120 days, each deck's own file once a day (60 a refresh); while it fills the page shows the precons read so far and asks again every few seconds, and a failed refresh rests for an hour. With no copy of MTGJSON's deck list the page says it couldn't be fetched, as Add a precon does. `GET /api/precons/coverage?space=&format=&type=&limit=`, `GET /api/precons/coverage/deck?file=&space=`, `POST /api/precons/start`. On the PC, `python -m decklab.lib.precons coverage [--space S] [--format commander|casual] [--limit N]` prints the same ranking (read only; it fills the index first, in the foreground, when it's due).
- **Imports** read ManaBox's CSV export, Moxfield's collection export, Deckbox's inventory export, or a CSV in the collection's own columns (AGENTS.md, "Collection cards"), told apart by the header row. Each row is matched to a Scryfall printing (set and number, else name and set, else it's a problem: "printing unknown"), conditions become NM/LP/MP/HP/DMG (ManaBox's Cardmarket scale one step down: Excellent is LP, Good and Light Played MP, Played HP, Poor DMG; anything unknown stays blank), languages Scryfall's codes, ordinary basic lands are dropped by the collection's rules (`lib/inventory/rules.py`: kept when foil, etched, noted as full art or special, or already tracked), and repeated printings are merged. The preview lasts an hour. Applying it keeps the upload as it was sent among the space's raw imports, as `<date>-<file name>.csv` (`-2`, `-3`... when the name is taken), and adds its quantities, in one change. Rows with problems stop the import unless it's told to leave them out.
- **Tokens of a person's space** are edited on the Tokens page with `"space"` (`GET /api/tokens?space=user2`): their own token cards, each change a change set such as `add token Fish (User2's tokens)` by User2.
- **A person's wishlist** (in the database, see "Wishlists") counts the copies in their own collection.

## Wishlists

Choose **Wishlist** (the top bar's More) to see your own cards, as card tiles. Everyone has a separate list,
and can add and remove cards on a phone, iPad or desktop. Search by card name, look at a result in the
card viewer, then add it. Tap a saved card to open its sheet: its picture (tap it to see the whole list
big, swiping between cards), its notes, the printing you'd like and its source (a deck shows as its title,
linked), with **Save**. **Remove** at the bottom of the sheet takes the card off your wishlist at once,
with an **Undo** that puts it back at its old place with its notes, printing and source.

**A wishlist is private:** only its owner sees it, on the Wishlist page or the Activity page. Not
another home profile, not a person with their own space, and not an admin (as with each person's
accessories, Matt's admin role doesn't override it). The page only ever opens the chosen profile's
own list; through the tunnel that's the login's.

User1's list starts with the 55 suggestions in
[`2026-10-01-user1-suggestions.md`](../magic/buylists/2026-10-01-user1-suggestions.md), keeping
the linked artwork and recommendation notes. Matt's starts empty. These are cards to consider;
wishlisting a card does not order it or add it to the shared collection. Owned and on-the-way
counts describe that collection, not copies reserved for the wishlist.

Since phase 2 of the database move (2026-10-12), lists are rows of the database's `wishlist_entry`
table, not files, so every device sees the same saved list. Each add or removal saves immediately,
in one transaction; once the page confirms it, you can close the browser. No Save button is needed,
and nothing is committed to git: each change is a change set in the audit trail ("Add Plains to
User1's wishlist", by whoever made it, at home or away), shown on the Activity page. A list holds
at most 1,000 cards, and a name is listed once, whatever its case. While the database can't be
reached, the page shows an error with **Try again** (503) instead of the list.

`GET /api/profiles/<id>/wishlist` gives `{profile, entries, warnings}`, only to the list's owner
(`permissions.sees_wishlist`): anyone else gets 403 "A wishlist is private", an admin included, and
so does a request at home whose page hasn't named a profile in `X-Deck-Lab-Viewer`, a script's included (the page always
names one once a profile is chosen; through the tunnel the login's profile is the viewer). `POST`
takes `{"profile", "action": "add", "name", "set"?, "number"?, "notes"?, "source"?, "at"?}` (`at`, the
place it goes, and the notes and source are for Undo; the end without `at`), `{"action": "remove", "name"}`
or `{"action": "set", "name", "notes"?, "source"?, "set"?, "number"?}` (both `set` and `number` empty for no
printing), and answers with `saved` and `changed`. Only the list's own person may change it.

Claude (and anyone at the PC) uses the command line: `python -m decklab.db wishlist list <profile>`,
and `add`, `set` (notes, source or printing; `add` never changes a card already listed) and
`remove`, each with `-m "<what>"` and, for a removal, `--reason "<why>"` (AGENTS.md, "Wishlists and
other database data", has the details). A name is checked against the card index like the page's
(`--no-check` skips that when the index isn't built), and a profile not in `config.json` is refused
unless `--allow-orphan`. The command line isn't bound by the page's privacy: it reads and changes
any list, and `sql` reads every list, note, message and reason. On the page, a command line message
or reason about a wishlist shows only to its owner, and only when they may see the command line's
words (an admin: Matt's own list; `--actor user1`: User1's own list). A default Claude
message about User1's list shows to nobody there (see Activity).
The suggestions were initial data only, and the original buylist remains a dated reference.

## Activity

**Activity** (the top bar's More, for everyone; `#/activity`) lists the changes saved in the
database, newest first and grouped by day, each as a plain headline worded by the server from the rows
the viewer may see ("Matt received the Ronin Games order: 16 cards"): who made it (from `config.json`
now, or Claude, System, "someone at home"), when (local time), whether at home or away, or from the
command line, an import or a sync, its message and reason, and its first few rows in plain words
("Added Plains (SLD 1513) to User1's wishlist", "Your theme: system → dark", "Simulations: admins →
everyone") with **Show all**. Filter chips pick a kind of change and a person (the server filters, so
**Load older** keeps to them), and rows link to their decks, receipts and cards (the card viewer, over
the change's cards). The list read is separate from the explicitly confirmed Undo described below.

**Review undo** is an advisory candidate button; its separate server preview decides whether the change can be reversed now. Single-row inventory support requires exactly one audited row globally, in the viewer's own space: an UPDATE of collection quantity/condition/language/notes on the same printing identity, an UPDATE of token quantity/notes on the same stable row, a collection INSERT whose whole nonbasic printing row can safely be removed, a collection DELETE whose exact historical row can be restored, or an unused token INSERT with verified physical pairing and a stable row identity. For updates the review shows the authoritative current row and restored values, including notes only to its authorized editor. **Save Undo** creates one new audited inverse and keeps the original change immutable. It checks the original audit row is still latest, the required current state, and both inventory and deck revisions under the normal write lock. Collisions, unknown holdings, later touches and unsafe held-card reductions refuse; any in-use acknowledgement belongs to the normal editor, not Undo.

**Wishlist preferences:** one complete global UPDATE of printing, notes and/or source can be undone by that exact profile's owner. Another home profile or an admin has no override. Name/position edits and mixed sources remain outside preference Undo. The review shows Set/Collector number differences and literal current/restored notes/source; an unchanged printing partner stays visible. Both printing pairs must follow ordinary forms, with both fields recorded or both empty. Historical sources create no links or card/deck/inventory lookups. It checks the full ordered own wishlist and latest audit evidence again under the same membership/wishlist lock as the ordinary setter, saving one audited inverse or nothing. A saved own-list change after preview requires a fresh review, even after an ABA return to identical values; another profile's writes do not invalidate it. `GET /api/activity/wishlist-undo?id=N` reviews it; POST accepts only `profile`, `id` and `expect`. Its owner-profile protocol and audit-derived revision are separate from inventory Undo, with an exact full-entry and full-list-digest receipt. Uncertain outcomes require Reload Activity.

**Latest wishlist addition or removal:** one global own-profile entry INSERT or DELETE can also be reversed, only while it is the most recent saved change to that entire wishlist. Any later own-list change, including a remove/re-add cycle under another position, blocks these entry inverses. The review shows the complete current entry to remove or historical entry to restore. Restoration must reproduce its former place without shifting other entries; some previously gapped lists require the normal Wishlist page instead. These are wishlist entries, so Save Undo needs no card-ownership confirmation or stock/removal-reason input. The same three request keys and owner-only endpoint apply. `wishlist_add` proves the actual full restored entry; `wishlist_remove` proves exact `removed_name` plus `restored: null`. Both prove the full surviving list and a new owner audit version.

**Accessory recorded details:** one complete global accessory UPDATE changing only brand, name, colour, notes, product link, recorded image-source URL and/or box capacity can be reviewed at `GET /api/activity/accessory-undo?id=N`. POST accepts only `profile`, `id` and `expect`. The normal accessory owner/shared edit rules apply, with no admin or Public-reader override. Both full recorded rows must round-trip ordinary forms exactly; id, owner, kind, stock and image/crop must be unchanged. The review restores these recorded details and retains the **current photo and kit**: image bytes are not audited, so it does not promise to reverse a historical photo replacement under the same filename. A restored image-source URL is only a recorded value, not checked against the retained photo. Both URLs must match ordinary blank/http(s) forms and codepoint limits exactly (product link 500, image source 2,000); reviews render them as wrapping literal text without fetching them or making clickable links. The complete source, latest target audit touch and current owner-scoped list are checked again under the inventory lock. Another owner's private changes do not invalidate the review. One ordinary edit must preserve every other row and current image, with exact actual snapshot/audit verification before commit. The receipt proves the full restored details, owner-scoped list digest and new target audit version, without disclosing global revisions.

Recorded capacity is blank (Not recorded) or a canonical 1-9999 sleeved-card count for a deck box; sleeves and playmats retain blank capacity. Both current/restored entries contain all ten metadata fields, and ordinary exact validation applies to both. A held box can have its recorded capacity corrected through Undo as through normal Edit. Stock, photos and assignments stay as they are; existing fit warnings may change. This does not verify physical fit or require a new ownership checkbox. Full 13-field addition/removal records retain their separate protocols, with capacity present exactly once.

**Recorded accessory count correction:** a single global UPDATE that changes quantity has a distinct `accessory_stock_update` review on the same endpoint. Current/restored entries contain the ten metadata fields plus canonical TEXT quantity 0-9999; quantity must actually differ. The seven supported recorded details may change with it, but id, kind, owner and image/crop must stay exact. Current photos and kit assignments are retained. The same complete source/latest-target/current owner-scoped list and actual ordinary Edit/audit proofs apply, including photographed and held accessories. A correction can change normal sleeve-shortage, box-availability or capacity warnings; it does not move kit or verify physical ownership.

The review replaces the **whole recorded count**, rather than adding to it. Sleeves count individual sleeves, loose ones included; boxes and playmats count items. An initially unchecked confirmation asks whether the entire restored count is still owned; zero instead confirms a zero-stock reference record, which is kept. Cancel and use Sleeves & boxes when the actual count differs. Save sends only `profile`, `id`, `expect` and `confirm_stock: true`; no quantity, metadata, reason or restoration flag is accepted. Metadata-only UPDATE and the ADD/REMOVE protocols reject any stock-confirmation flag. The receipt proves the exact eleven restored fields, scoped digest and new target audit version.

**Unused accessory Mine/Shared correction:** a single global owner-changing UPDATE can be reviewed as `accessory_owner_update`. It must be exactly between Shared and one currently configured home profile, with both recorded owners in the viewer's writable own/shared scope. Even an unnamed script cannot use this inverse for another kind of owner transfer. Id, kind, quantity and image/crop must stay exact; the seven supported recorded details may change with ownership. Current photos and kit are retained. Complete home deck/product/status and kit evidence must prove the record unused, including no stray or wrong-kind references, before preview and again under the write lock. Held or uncertain cases use normal Edit instead.

Current/restored entries contain the same exact eleven fields as count recovery, showing the unchanged quantity in individual sleeves or items. A distinct unchecked owner confirmation explains Mine versus Shared: both home people may see/change Shared, only its owner may change Mine, and read access also follows the destination owner's existing Public/Private kit setting. Undo changes no Public/Private switch. Save sends only `profile`, `id`, `expect` and `confirm_owner: true`; count, restoration and reason flags cannot authorize it, and other actions reject any owner flag. The full source/latest/current/scoped and actual ordinary Edit/audit proofs apply, with exact eleven-field receipts and generic refusals that name no hidden holder. A new reference blocks Save; an unrelated kit edit may pass when the target remains certainly unused.

**Unused accessory kind correction:** a single global kind-changing UPDATE has a distinct `accessory_kind_update` review. It must preserve id, owner, numeric quantity and image/crop; a source that also changes owner or quantity uses the combined review below. The seven supported recorded details may accompany the kind change, including capacity: blank for sleeves/playmats, blank or canonical 1-9999 for a box. Both full historical/current rows must retain ordinary exact validation. Complete unused-kit proof is required before preview and again under the write lock. Normal Edit keeps current pictures and kit, and the expected full list is re-sorted by kind/id while proving every surviving row unchanged.

The exact eleven-field review shows both kind labels and the same number with **each side's units**: individual sleeves versus items, including transitions between boxes and playmats. One initially unchecked kind confirmation covers the recorded classification and whole count still owned; zero instead confirms a zero-stock reference record. Save sends only `profile`, `id`, `expect` and `confirm_kind: true`. Owner, stock, restoration and reason flags cannot authorize this action, and other actions reject any kind flag. The receipt proves the exact eleven restored fields, scoped list digest and new target audit version, with full actual opposite-row/audit verification and no added stock or kit movement. It does not recover an old photograph or verify physical fit.

**Combined accessory correction:** one global UPDATE changing at least two of **kind, owner and quantity** is reviewed as `accessory_record_update`. The seven supported recorded details may change with them; id, image and crop must stay exact. The earlier actions retain their single-category scope. A changed owner must form Shared plus one configured home profile, with both source owners writable even before flag validation; scripts cannot bypass the pair rule. Complete home kit evidence must prove this combined record unused at preview and again under the write lock. Both full rows must retain ordinary exact validation, including counts and box-capacity transitions. One ordinary Edit restores the complete correction, with a sorted full expected list and every survivor, current photo/crop, kit assignment and visibility switch preserved.

The review shows **all eleven current and restored fields**, friendly kind/owner labels and each side's count units. One initially unchecked record confirmation covers the restored classification, total still owned and any sharing change together. Zero instead confirms a reference record; a changed owner also explains Mine/Shared access and the destination owner's existing Public/Private kit setting. No partial selection is offered. Save sends only `profile`, `id`, `expect` and `confirm_record: true`; no proposed row values or owner/kind/count/restoration/removal flags are accepted, and other actions reject any record flag. The exact eleven-field receipt, scoped list digest, latest target/source fences and one actual opposite full-row audit are verified before commit, including an absent audit reason. A different actual correction goes through normal Edit.

**Recorded crop on the current photo:** one global UPDATE changing **only crop** can be reviewed as `accessory_crop_update`. All other twelve raw cells, including the nonblank image filename, must stay exact. Current/restored entries contain all thirteen fields, one crop diff and a pinned `photo` descriptor (`name`, byte `size`, full `sha256`, address-epoch `version`). This restores historical coordinates onto the **photo saved now**, and cannot recover an earlier photograph. A photo replaced under the same filename before preview is the current photo you must review. A different full photo hash after preview blocks Save even without an accessory-row audit; there is no additional image-history guarantee when identical bytes return.

The page fetches the authorized current image without caching or redirects, checks its full strong server ETag, type, declared/actual bounded size, and makes one local blob for both read-only crop views. Both must load/decode successfully before the initially unchecked current-photo acknowledgement is enabled. The views stack on a phone and sit side by side from 600 px. A missing, changed, malformed or undecodable photo blocks Save; closing or changing person aborts that image read and releases its blob, independently of a pending save. No external image-source URL is fetched and no crop editing controls are offered in Undo.

Save sends only `profile`, `id`, `expect` and `confirm_photo: true`; crop values/photo bytes and other action flags are refused. The full current photo descriptor is bound into the review token and checked against actual bytes in the same locked transaction, before and after ordinary Edit. Full byte length/hash, normal format/dimension checks, current photo metadata and one exact opposite audit are proved, including an absent audit reason; the receipt repeats the exact raw thirteen restored cells and the same four photo facts. Stock, kit, photos/crop-independent metadata and visibility stay unchanged, and held accessories may correct their crop. Older actions keep their prior token format and never read photo bytes for this feature.

**Unused added accessory record:** one complete global image-free accessory INSERT can also be reviewed as `accessory_remove` on the same endpoint. Its full current 13-field record, recorded quantity (individual sleeves for sleeves) and box capacity are shown, with `restored: null`, no diff fields and a required reason. Save sends only profile/id/expect/reason and removes the entire record in one new audited change; no stock edit or ownership checkbox is offered. The normalized nonblank reason is limited to 200 characters and shown before saving. Text UPDATE Undo still rejects a reason.

The original full row must still be current/latest and contain no image/crop or target picture orphan. Complete readable home decks, product lists/status and all kit references must establish non-use: any target-id reference, wrong-kind link, unresolved/legacy label, stray reference or incomplete evidence refuses. A canonical missing status sheet is accepted only when there are no products or status rows. Use the normal editor to resolve uncertainty first. These checks run again under the write lock, so a new deck/product reference after preview blocks removal without exposing global revisions. Unrelated kit changes can pass when the target remains certainly unused and are preserved exactly. The ordinary removal must preserve all survivors, kit, photos and other data, including a valid final empty accessories list. Success proves the exact `removed_id`, `restored: null`, scoped survivor digest and a new target audit version; the original audit stays unchanged.

**Image-free deleted accessory record:** one complete global DELETE can be restored as `accessory_add`, with `current: null`, the full historical 13-field record, `confirmation_required: true` and no diff/reason fields. POST accepts only profile/id/expect/confirm_restore, with explicit `true` required. Positive quantities require confirmation that every recorded sleeve/item is still owned **in addition to quantities already recorded**. Quantity zero instead confirms restoration of the reference record, adding no owned items. The checkbox starts unchecked and resets after Cancel; fewer owned items require manual Add in Sleeves & boxes. Other accessory actions reject this confirmation key, and restoration rejects a reason key, including null.

The old id must be absent and retain the latest audit touch, with canonical raw fields and no photo/crop, target picture orphan or target kit reference. The ordinary Add operation must derive exactly the historical id and reproduce the full row and canonical list without changing survivors, photos or kit. Reproducible suffix ids are accepted; ids ordinary Add cannot reproduce or collisions require the normal editor. Other owners' metadata stays outside the review token, but a hidden id collision can still make exact restoration unavailable. Refusals disclose no generated candidate id, hidden namespace or global revision. Complete kit certainty and identity reproduction are checked again under the inventory lock. No photo or kit assignment is restored, and recorded image-source URLs are only text. Success proves exact `added_id`, the actual full historical row, scoped list digest and new audit version. Existing text and removal protocols are retained.

Undo of an added collection row explicitly previews removal of **every recorded copy in that printing row** and requires a nonblank reason of at most 200 characters; the normalized reason is shown before saving and recorded in the new audit. It refuses any physical holder of that card name, even when other printings appear plentiful. Unknown storage or assembly, anonymous or ambiguous installed markers and tracked basic lands require the normal Collection editor instead. All source, revision and physical-use checks run again under the write lock. The confirmed result proves that the printing key is absent (`restored: null`), rather than inventing a zero-quantity row. The normal removal operation creates the new inverse audit. Historical audit stays unchanged, with no ad hoc reverse SQL.

Undo of an added token-card row previews removal of every **physical card** in that row and requires the same explicit removal reason. Each front/back pair counts once. The saved physical pairing must already be verified; a blank reverse needs the existing `single-sided verified` note. Ambiguous duplicate token identities, an in-use target, unknown deck/product packing, row movement or any changed allocation of surviving cards refuses Undo. The check preserves surviving row ids, database positions, facts and physical allocations instead of choosing substitute stock or guessing a reverse face. The result confirms the removed stable `removed_token_row_id` with `restored: null`; earlier collection/UPDATE/metadata protocols remain unchanged. Use Tokens for pairing or packing corrections before another review.

Undo of a deleted collection row previews its complete historical printing, quantity, condition, language and notes. The printing key must still be absent, with no later audit touch. Local card data must verify the exact canonical name, paper printing and finish, and the ordinary Add operation must reproduce every recorded cell without merging, increasing another row or skipping basics. **Save Undo** stays disabled until you explicitly confirm that **all recorded copies are still physically owned**. If fewer copies remain, cancel and enter the copies actually owned through Collection. Cancellation/reopening resets that confirmation. The browser sends only the source id, review receipt and ownership confirmation; the server derives the restored row and printing key from the original audit. A confirmed result includes the actual full restored row and added key.

The same exact restoration can cover one complete change of **2-50 deleted collection rows**. Every global audit row must be an own-space DELETE, with unique original row ids and printing keys. Each key must still be absent and its original deletion the latest touch; canonical paper/finish checks, exact ordinary Add round-trips and both revisions are checked again under the write lock. One unchecked confirmation covers **all recorded copies across every printing in the batch**. Unchecking, cancelling or reopening clears that consent. If any copies are no longer owned, cancel and use Collection; there is no partial selection or smaller-quantity edit here. `batch_add` restores every full historical row in one atomic candidate and audited save, with actual full restored rows confirmed by printing key even if reply order changes. Absence is shown as `current: null`, never an invented zero-quantity row. Mixed UPDATE/DELETE sources, identity/zero changes and general import inverses remain unsupported.

Undo of a deleted token-card row (`token_add`, 2026-10-29) previews the complete historical row with `current: null`, `identity_policy: "fresh_id"`, `packing_restored: false` and `physical_confirmation_required: true`. Only one standalone own-space DELETE that is still the latest audit row for both its id and its space's token list qualifies; the review checks the exact printing and pairing, settled stock order and persisted positions, and that no survivor may be the same physical card and no recorded deck or product packing line could claim it. Its receipt binds the source and latest audit row ids, the facts, the token list's sha, the stock, layout and packing, and both revisions. POST takes profile/id/expect/`confirm_owned: true` (a reason is refused); the whole review runs again inside the write transaction, then ordinary Add saves the row without an id, so the database gives it a new one. Before commit, the same transaction proves exactly one own-space INSERT with a fresh id (never the deleted id or a survivor's) carrying the reviewed facts, every survivor's id, facts and persisted position unchanged, the same packing allocations with the new card unheld, and no other space's token cards changed; anything else rolls the change back. The confirmed result names `added_token_row_id` and the actual restored row. The deleted id is never reused and earlier packing is never reconnected; a replayed receipt refuses. A change of 2-50 own-space token-card DELETEs and nothing else is `token_batch_add` (`lib/inventory/undo_token_batch.py`): the preview has `row_count`, `rows` (each `label` and `restored`), `cards` (the whole physical count) and the same fixed policy fields; every row passes the one-row checks, and before commit the transaction proves exactly that many own-space INSERTs with fresh ids and the reviewed facts, survivors and packing unchanged, or rolls them all back. The saved result names `added_token_row_ids` and `restored_rows` in the preview's order. More than 50 rows, or any ineligible row, refuses the whole change: the review answers `available: false` with a `reason` naming how many rows and why in fixed words (a POST 400 with the same words); a change with any row outside the viewer's space answers 404 as a missing change.

**2-50 added collection rows** can also be removed together as `batch_remove`, with one required reviewed reason. The complete global source must contain only own-space INSERTs, with unique identities, latest audit touches and exact full current rows. Each target must pass the strict single-added-row proof against one complete candidate: basic lands, any physical holder of the same name despite other surplus, unknown packing or uncertain installed Stand-ins refuse. Every target is removed or none, preserving the exact remaining collection and other data. The reply confirms the actual absent `removed_keys` and `restored: null`; it invents no zero row. A batch restoration can produce an eligible source, while imports/receipts with other audit rows remain unavailable. Eligibility depends on the whole audit shape, not an operation label.

Undo also supports a complete change of **2-50 collection UPDATE rows changing positive quantities, condition, language and/or notes**. Every global audit row must be in the viewer's own space; zero quantities, removals, name/printing-key changes and mixed sources refuse the batch. The preview shows every printing's current and restored values, and **Save Undo** restores all of them together in one audited change. There is no partial selection. Each row must still equal its full recorded after-state and retain the latest audit touch; unique identities and both revision receipts are checked again under the write lock. The ordinary collection batch editor must restore exactly those full rows without removals or unrelated changes. The browser sends only the source id and opaque review receipt with its profile; the reply confirms every full restored row by printing key, regardless of reply order. Quantity batches use `batch_update`; metadata-only batches retain `batch_metadata`. Earlier single-row protocols remain unchanged.

Any decrease also requires complete holder and installed Stand-ins certainty against the whole final candidate, using the existing aggregate capacity policy. Uncertain holdings or insufficient capacity refuse Undo. This proves no particular printing physically free and moves no packed cards; use Collection for physical corrections or an in-use acknowledgement.

**A whole import or receipt** (E11-S08, 2026-10-27) can be undone as one change too, on its own endpoint: `GET /api/activity/mixed-undo?id=N` reviews it and `POST /api/activity/mixed-undo` (`{"profile", "id", "expect", "reason"}`) saves it. An import (`import_undo`: a Collection page import, `collection merge` or another `collection.import`, any number of rows up to 2,000) is undone by its space's own people: the rows it added are removed and the rows it added copies to go back to their earlier quantity, condition, language and notes. The upload stays kept as a record. A receipt (`receipt_undo`, home's admins, who may receive) puts its order parts back to pending with their arrival checks to do again, sets a product it received back to ordered or preordered, takes out the cards and token cards it added, and works the deck tables out again. Only a receipt of whole parts qualifies: one that split a part, corrected its rows or confirmed extra copies changed more than this puts back. The review lists every row; there's no partial selection, and a reason is required. Every row the change wrote must still be exactly as it left it and the latest audit row for its key, so a later edit, receipt, kit choice or token packing refuses, naming that row. The inverse must put exactly those rows back and change no other inventory row, checked on the rows the database holds before anything is saved. Cards a built deck or another intact product may hold refuse as for single rows (a product the receipt itself kept intact goes back on order with its cards), as do tracked basic lands and token cards that may be packed. The deck rows a receipt's table refresh wrote aren't restored: Undo refreshes the tables again.

**A whole trade** (E7-S22, 2026-10-28) is undone on the same endpoint (`trade_undo`), by its space's own people, as recording it was: a change `collection trade` or Record a trade saved, told by both its reason (`Traded` or `Traded with T`) and its message ending in the trade's words for that same T (`Trade with T: gave ...; got ...`), whose rows are only that space's collection. The reason alone isn't enough, so a `collection apply` or an Undo saved with a reason like `Traded with T` is never offered as a trade. The review lists both sides, the cards that came in (rows to remove, or to go back to fewer copies) and the cards that left (rows coming back, or going back to more copies), with no partial selection, and a reason is required. Saving is one new change: the cards that came in go out and the cards that left come back exactly as they were. It follows the import's rules: every row the trade wrote must still be as it left it (a row it removed must still be absent) and the latest audit row for its key, a card that came in which a built deck or intact product uses, or a tracked basic land that came in, refuses, and the deck tables are worked out again afterwards. The row Undo never reverses part of a trade.

Historical notes are restored verbatim, preserving whitespace, line breaks, long text, formula-like text and literal markup. The review shows them as wrapping plain text, with no edit inputs. Non-text notes, NUL and text that cannot be represented as UTF-8 refuse before the inverse is attempted. Undo adds no fresh-input trimming, length or formula policy to historical notes; ordinary new-note entry rules are unchanged.

A conflict or uncertain response requires **Reload Activity**, with no blind retry or claim that a previous attempt was already done. Done refreshes the same filter and number of loaded pages, keeping the old rows until all reads succeed and restoring the original anchor where present. The complete global audit shape governs eligibility, without proving which command produced it. Merges outside an import, other removal recovery, identity changes, other multi-row changes, other accessory and broader wishlist inverses remain future work. For inventory, `GET /api/activity/undo?id=` supplies the authoritative review; `POST /api/activity/undo` accepts the source id, opaque review receipt and current profile. Removal of inserted collection/token rows requires a reason, including complete collection batches; restoration of deleted collection rows requires `confirm_owned: true`, including complete batches. No migration is needed.

`GET /api/activity?before=&limit=&kind=&actor=` (`lib/api/activity.py`; `limit`
1-100, 50 by default) applies `permissions.activity_scope`: named viewers see
their own space's changes, with system rows and truly empty changes for admins.
Only an unnamed loopback script sees across spaces. Public switches never widen
Activity. A change with no readable rows is omitted.

Wishlists remain visible only to their owner; kit rows follow their owner's
permissions. Game rows hide other spaces' deck details. Rows expose only their
table's allowed fields, never notes or raw records. Up to 50 inventory rows per
change are listed, with grouped counts for the rest. Messages and reasons require
every underlying row to be readable, including grouped and capped rows, for web
and CLI changes alike. Admins and the change's author follow that rule too.
CLI/import/sync words additionally require an admin or the author; a kit change's
words require its author. Other viewers get the server's row summaries.

Each answer examines at most 2,000 changes, so a page can be empty with **Load
older** offered. An unknown profile header sees no rows. Database failures show
**Try again**.

## Shopping and deliveries

Choose **Shopping** (the top bar, with a count of deliveries waiting; on this PC, [open
Shopping](http://localhost:8642/#/shopping)) for the shared purchase queue, orders and arrival checks.
It's home's, so only Matt and User1 see it (see "People's own collections"). Opening it does not
order cards or receive a parcel.

Matt can use **New order** to record a purchase already placed: its seller, date,
playable cards, token cards and a product, plus the purchase-queue rows it fulfils.
Search for a card and choose its ordered printing, or paste a list; CSV entry
also supports token face pairings and product lists. Leave unknown condition
and language blank. **Preview order** shows arrival checks, queue reductions
and the deck tables it will update. **Save order** records everything as one
change by Matt and refreshes On the way. If Shopping changes after the preview,
refresh it and preview again. User1 sees orders read-only.

**Edit order…** on a delivery or history entry corrects its seller, order date,
delivery notes and sources (one repository path per line). Blank fields clear
unknown details. Each pending part also offers adding a check or withdrawing one
entered by mistake; withdrawing it does not mark it verified. **Preview change**
shows the result before **Save change** records one audited change by Matt.
Another save after the preview requires a refresh and new preview. Received
checks still use Follow-ups.

When adding a check to an existing pending cards or tokens part, **About an
original order row (optional)** can associate it with one explicitly chosen
recorded row. **General check for this whole part** is the default. Preview
shows the selected original row and check before saving. Receive delivery then
shows that context beside the row, including locally edited or split copies.
The check's single label and checkbox move beside the first visible piece of
its proven original row. General or unproved checks, or checks whose target is
hidden or in an unselected part, stay in **To check**. A targeted fallback also
names its original row and printing. Splitting a tile does not create another
verification tick: the check still applies to the whole part. The same control
and checked state survive filtering, Pictures/List, row rebuilds, split/merge,
Undo and the existing explicit **Resume your check** flow. Older unassociated checks, new-order checks and product
checks stay general. Saving a payload correction, shipment split or order merge,
or receiving the part, drops its old row associations. If the saved association
cannot be confirmed, refresh Shopping and inspect the saved checks before making
another change; do not repeat an uncertain save.

Pending card and token parts also offer corrections to their row details. Cards
keep the same names and copies, with printing, finish, condition, language and
notes editable; copies can be divided between printings. Tokens keep the same
physical copy count while their face pairings, printings and details can be
corrected. Unknown fields stay blank. Pending cards and products can be marked
as additional copies only when they really are extra cards, rather than cards
already added to the collection. The mark can also be removed. Each change is
previewed and saved with its affected deck tables in one audited change.

**Split shipment…** on a pending cards or tokens part moves the chosen number
of copies from each recorded row into a new part of the same order. Give the
new part a unique id and leave at least one copy in each part. Each arrival
check can apply to both parts (the default), the original only or the new part
only. The preview shows both resulting lists, their checks and affected deck
tables before one audited save. Printing details, unknown fields and token
pairings stay as recorded. An additional-copies mark stays on the original
part; the new part needs its own confirmation. A split that introduces a
deck-table refresh blocker is refused.

Pending products offer **Correct product…** for their list and recorded details.
**Cancel part** cancels a pending cards, tokens or product part with a one-line reason.
Its queue-restoration checkbox starts checked; the preview shows the recorded quantities
to return, their printing and deck purpose, and affected deck tables. Declining restoration
leaves those quantities off the queue. A cancelled product keeps its reference list and
history, but contributes no incoming cards and disappears from the deck library.

**Remove order** at the bottom of Edit order removes an order recorded by mistake,
including its parts, payloads and products. Give a reason and review before confirming;
any received part blocks removal. Known fulfilled queue quantities always return in the
same change. Older orders without fulfilment records warn for manual queue review; no
quantities are guessed. Product and token corrections preserve the original recorded
purchase intent and warn when it may differ from the corrected contents. Saved results
keep restoration notes and any **Tables out of date** link visible until **Done**. These controls are Matt's; User1 sees orders read-only.

Its parts, linked from a row at the top on a phone or a portrait tablet:

- **On the way:** each delivery a card titled "seller · topic", with a strip of its cards' pictures
  (**+N** opens them all, swipeable in the card viewer), the checks to make when it arrives (folded on a
  phone), and **Receive delivery** as its main action.
- **To buy:** the purchase queue (hidden when it's empty). A card whose purpose or source names a home deck links to that deck's title; its card picture still opens the viewer separately. Matt can **Add card**, choosing its name, copies, category and deck, with any non-foil printing as the default or an optional exact printing. A row's **Details…** opens Copies and Notes; **Remove…** asks for a reason. Its **Move** menu chooses **Ready to buy**, **Waiting for stock**, **Waiting for reprint**, **Deferred** or **Long-term plan**. Each save updates the sections and counts as one change by Matt. A stale page asks for a refresh before another change.
- **Missing cards across decks:** canonical playable-card rows naming every home deck with a shortfall and each matching queue row's quantity, purpose, state, printing and dated reference. The quantity sums the decks' individual shortfalls; it is not a concurrent-build requirement, because shared copies can serve separate comparisons. Known token rows stay separate from same-name playable cards. Queue quantities are annotations, not another deduction from the shortfall. Unavailable or incomplete calculations show errors, with successful partial rows still visible.
- **By shop:** a folded view of all queue states, including the long-term plan, selected by recorded shop (or unknown shop), then grouped by in-stock, out-of-stock or unknown stock. It adds no purchase or edit actions. The selected shop and open fold survive a local queue save; navigation or reload starts a fresh view.
- **Decks still missing cards:** the home decks whose Planned list misses cards (built and being built,
  then ideas), each linking to its deck's missing cards. It's kept apart from the queue, which holds
  only what's been decided.
- **Follow-ups:** checks left open on deliveries that have arrived, such as a product's tokens still in
  the box. An admin marks one done with **Done**, which waits 8 seconds with **Undo** (Dones pressed
  together share one), then `POST /api/shopping/check` resolves it as `order checks ID C --resolve N`
  does, one change set.
- **Long-term plan:** the `long_term` rows, grouped by deck, with the same **Move** menu to bring a card back to **Ready to buy**. User1 sees both lists read-only.
- The order history, folded.

Queue rows and these buying views show the recorded reference price, shop and checked date directly below the row, even without a card picture. A missing legacy date is labelled explicitly. These are historical research references, not live stock or today's lowest price.

**Reprint follow-ups** (E5-S11, built 2026-10-16) show known upcoming paper printings on Shopping's queued and combined missing rows, and missing rows in a deck's inventory-visible price table. Each names the set and ISO release date; **Source and coverage** gives the Scryfall snapshot date, comparison date and limits. Only printings already in that cache are covered, with an earlier released paper printing establishing a reprint. Other announcements may be missing and dates may change.

A **Waiting for reprint** row offers **Check prices again** when a later reprint's listed release date has passed since its recorded price check. A missing, invalid or future check date, or unavailable reprint data, offers a manual review with the uncertainty stated rather than claiming a newly released printing. The sheet retains the exact-printing/finish preference and prior dated reference, links to the relevant Scryfall sources (USD prices), and lets you copy the exact card name to check a shop. A listed release does not confirm lower prices or retailer stock. This review performs no shop research, saves no observation or date, changes no purchase-queue category and schedules no notification; recording new research or moving the row remains an explicit action.

**MTGMate's daily prices** (E5-S08's first slice and E5-S19's highlight, built 2026-10-28): once a day the queue's card names are looked up on MTGMate (mtgmate.com.au), and each queued row shows, under its recorded reference price, what that snapshot found: the shop's own AUD price and how many are in stock (for an exact row, its printing and finish, nonfoil when blank; for any other row, the cheapest nonfoil in stock, else the cheapest in stock, else the cheapest nonfoil out of stock), linking to that printing's page, with the time it was fetched. A shop that couldn't be read shows **price unknown**, never a converted US price; a card MTGMate doesn't sell shows **not listed**, and a row added since the snapshot **not in the last snapshot**. A **Waiting for stock** row the snapshot finds in stock is highlighted **Back in stock**, and any row in stock now but not in the snapshot before is marked **Newly in stock**. The snapshot never changes the queue: recording a price, stock or check date, or moving the row, stays your own change.

**Missing-card checks** use that same saved snapshot on **Missing cards across decks**. Each generic need chooses the cheapest stocked nonfoil printing, with no foil fallback, independently of an exact-printing queue request. The line shows an AUD unit price, stock of that selected printing and the card entry's own fetch time, including its year; it does not promise enough copies for the shortfall or calculate a basket total. No nonfoil listing, no saved check and unconfirmed evidence are distinct. An older carried entry keeps its original date. Nightly lookup includes proven missing names from saved home decks within the same request budget; it may take several nights to reach them all. Opening Shopping performs no shop request.

Home deck **Prices** shows the same saved check beneath each missing card. It is for any nonfoil printing and may differ from the printing or finish in the deck's list; converted estimates, exchange-rate dates and totals stay unchanged. The shop line stays with its card when sorting. Cache coverage is part of home's private buying context: a viewer needs both home inventory and home-record access, so a Public deck or collection alone never exposes these checks. Member-space decks use no home shop cache. Opening a deck performs no retailer request or saved observation.

Nightly captures the queue and saved-home shortfalls from one fresh saved inventory revision. It excludes member decks, Public ones included, wishlists, editor drafts and product/pairing candidates, while retaining home's physical reservations in the calculation. Pool uncertainty leaves queue-only lookup working; individually proven decks may supply a partial scan, with fixed log wording. Existing queue spellings stay intact so saved matches and carried dates still work; canonical identity prevents adding duplicate missing names. An expansion beyond 5,000 names falls back to the complete queue without truncation. An already larger legacy queue keeps its existing lookup behavior; strict missing-price evidence remains unknown for such an oversized cache. Empty home deck lists need no card-index load. Manual snapshot and dry-run remain queue-only.

It's a cache file, `decklab/data/shops/mtgmate.json` (gitignored), and Shopping only reads it, so a page load never reaches the shop. What is particular to a shop (its page of a card name and how to read it) is an adapter in `decklab/lib/shops/` (`base.py`'s interface, `mtgmate.py`'s MTGMate), tested on saved synthetic pages in `decklab/tests/fixtures/shops/`; MTGMate is the only shop so far. It's refreshed by the nightly task's last step (see "Backups"), or by hand:

- `python -m decklab.lib.shops snapshot [--force] [--dry-run]`: one request per distinct card name on the queue (MTGMate's page of every printing with that name; its search is never used, since its robots.txt disallows it), after reading robots.txt, spaced by its Crawl-delay (60 seconds), so 30 names take about half an hour. It does nothing when the snapshot is less than 20 hours old unless `--force`; `--dry-run` lists the names and the time it would take without asking the shop. Three failures in a row stop the run, leaving the rest unknown. Two runs never overlap: a run holds an OS lock on `mtgmate.lock` beside the snapshot, which goes with the process however it ends, so a run stopped partway never blocks the next. Exit codes: 0 done (or not due), 1 refused or every name unknown, 2 the queue can't be read.
- `python -m decklab.lib.shops show`: the queue's rows beside the snapshot, with no network.
- `python -m decklab.lib.shops lookup NAME`: one name's MTGMate listings, printed and not saved.

The view uses the same pool of owned and incoming cards as deck planning, read in one inventory snapshot. The added buying views follow the same home-inventory visibility rule; they do not place an order or change the queue.

Since phase 3 of the database move these are all rows in the database (see "The inventory in the
database" under Database), read and changed on the PC with `python -m decklab.db` (AGENTS.md, "The
inventory", has the rules and commands). Each has its own job:

- The collection and the token cards: the physical playable cards and token/reminder cards already owned.
- The watchlist: intended purchases still to make. A row is `ready`, `waiting_for_stock`, `waiting_for_reprint`, `deferred` or `long_term` (a later plan, bought alongside other orders to share postage); its quantity excludes copies already ordered. `source` links the research or deck behind the decision. A ready row does not certify today's shop stock.
- The order records: stable seller, order date, research links and delivery state for each cards, tokens or product component. Unknown dates remain blank. Components may arrive separately; the order's overall state is derived from them. Optional `audit_notes` keeps migration/provenance evidence (and a cancellation's reason) out of the displayed shipment notes.
- The components' rows: the exact ordered contents, playable cards and token cards apart. Only pending components contribute incoming copies; a received one stays as its order's history, and a cancelled one never counts.
- The products: fixed product contents, and each one's status: availability, whether the product stays intact, and an intact one's sleeves and deck box. A known order can contain products alongside singles and tokens.
- `magic/buylists/` (still files in git): dated research, shop quotes and recommendation rationale. Every file links the current Shopping view; historical "buy" recommendations do not override the current queue or delivery records. Older files also link `../watchlist.csv` and `../orders/records/`, which resolve in the `pre-db-inventory` git tag, and deck files (`../decks/...`), which resolve in `pre-db-decks`. A watchlist row's, wishlist card's or order's `source` naming a deck's old path is still accepted while that deck exists (matched by the path's exact case).
- The wishlists (in the database since phase 2; see "Wishlists"): each person's interests, separate from the purchase queue. A favourite may remain there after it is ordered or owned.

Record an actual order once, with `python -m decklab.db order add`: it saves the record, its
components and any product, reduces the purchase-queue rows it fulfils, and refreshes the saved
deck tables, in one go. Keep shipment facts in the order record and card-specific facts in its
rows. Do not add spending totals. An empty purchase queue means no purchases are currently queued;
it does not mean all orders have arrived or every idea deck is complete. Unresolved physical checks
stay visible even for a received component, such as product tokens still inside an unopened box.

**Receive delivery** (`#/receipt?order=<id>`, from a delivery on Shopping; recording an arrival is an
admin's, and anyone else who sees home sees the same board read only) is a check-off board. Each
pending part of the order is a grid of its cards' pictures (the printing recorded, or the card's
default picture in a dashed frame saying the printing isn't recorded or isn't in the card data), three
a row on a phone and up to about ten on the QHD screen, each with its quantity, set, number and finish,
chips only for what needs a look ("Condition, language ?", Foil, Edited, a note naming the card) and
the decks that use it, and a tick to check it off. An order with one pending part selects it; with
several, tick **This arrived** on each part that did. For cards and tokens, tick only the rows that came; unticked rows stay on the way. Use **Split copies** when only some copies of a tile arrived, then tick the arrived tile. Each part's **To check** list has its own ticks.
Filters (All, Not checked, Needs attention), Pictures or List, **Tick all**, setting a condition and
language on every card that has none, and clearing the "check on arrival" notes of ticked cards work
on the whole part. Tapping a card opens its sheet (a side panel from 1,280 px): **Different printing…**,
the finish, condition, language and notes, and **Split copies** (some copies to a tile of their own,
with **Merge back**); its picture opens the card viewer, and on a phone a sideways swipe moves to the
next card. A token's sheet has its faces, **Swap front/back** and **Back is blank** (which writes
`single-sided verified`). A product shows its cards by deck and section, with two choices above them:
keep it as its own deck(s), or break it up into storage (which clears its sleeves and deck box). The
total quantities can't change, and token fronts and backs stay paired. Products are received whole; their reference cards are not individual receipt selections.

A sticky bar holds the progress ("9/15 ✓"), **Arrived** (Today, Yesterday or another date; never after
today) and **Preview**, which becomes **Confirm: all 15 checked** once every card and check is ticked and
every ticked card has a condition and language (that sends `verified`). A checked subset shows **Confirm: N selected checked**. A partial selection can also be previewed: its received cards/tokens must meet the same inspection rules, while unticked rows do not become owned. Unknown condition or language can still stay blank after the preview warning. A selected cards/tokens part needs at least one ticked row. The check in progress is kept in
this browser per person, order and inventory revision, so a reload or a phone going to sleep loses
nothing ("Resume your check"). Drafts are bound to that inventory revision and cannot resume against a changed one; a successful receipt drops its saved check.
**Preview** runs the receipt on a copy in memory and says the outcome in plain words (the cards going
into the collection, the received and pending component quantities, and the decks whose tables it changes, linked), with anything that blocks it
linked to its card; it refuses when those tables couldn't be refreshed afterwards. Editing after a
preview says "Changed since preview". **What this changes (N)**
lists the parts of the inventory and the decks it touches, in plain words ("Home's collection",
"Order 2026-10-05-ronin", "The products' status", "Deck Gruul Ramp (casual/gruul-ramp)"; until
phase 5 it was "N files will change" with the old files' paths). **Record arrival**
saves it and the refreshed deck tables as one change set ("receive <order>", by whoever recorded
it; the answer's `tables`: written, skipped with why, any error), and **Where these go** follows:
the new cards grouped by the deck and sleeves waiting for them, the rest to storage. A refresh that
fails at that point leaves the receipt saved and the decks as they were: each deck page then says
its table is out of date, with **Update the table**, and the page's note links to the Decks page's
Tables out of date list, where **Update all** refreshes them (or `deck tables --apply` on the PC). A preview lasts 30 minutes and is used once;
any inventory change since it was made (a Tokens or Collection page save too) makes the apply ask
for a new one. A partial cards/tokens receipt keeps the original component pending and creates a received part in that same audited save; selecting every row receives the original component without an extra split. The remainder keeps its checks and recorded fulfilment attribution. Complete edited rows are saved before partitioning, so corrections can also update the pending remainder's metadata. The preview shows **Arriving now and still on the way** with the server-assigned component ids and counts. After saving, the page lists all remaining pending parts and their quantities; **Continue pending delivery** reloads the order so those cards can be checked next. **Where these go** uses the reviewed arrived-row snapshot, so a late response cannot include later board edits. Product token checks stay open
until those physical tokens have been inspected separately. The receipt doesn't rewrite buylist
links to the old payload paths. A temporary database failure keeps the review and offers **Retry recording arrival** with the same opaque preview token; a changed inventory asks for **Reload the delivery**. The board draft remains, but a draft from an old inventory fingerprint cannot be applied to the refreshed delivery. Receipt dialogs close on route, person or away-lock changes; late results do not redraw a different page or person.

## Accessories

Choose **Sleeves & boxes** (`#/accessories`, the top bar's More; home profiles only) for the sleeves,
deck boxes and playmats (in Deck Lab's database since phase 4). It works on phones and the iPad as well
as the PC. Each one shows its picture, how many there are ("100 sleeves", "2 boxes", and for a deck box
how many cards it holds) and which decks or products use it (and how many sleeves or cards each needs),
with a warning when a holder is short or a deck has more cards than its box holds. A filter (All,
Sleeves, Deck boxes, Playmats) is remembered on the device. Tap one to open its sheet, where Remove
sits at the bottom, disabled while a deck or product uses the row; set the quantity to 0 instead to
keep it as history. **Built decks without sleeves (N)** lists the built decks with none chosen, each
with **Choose…**, and **Products kept intact** each product's sleeves and deck box, also with
**Choose…**. Nothing chosen shows as a dashed "None chosen" slot. A visitor who may not change
them gets a details sheet instead (notes, shop link, who uses it).

Each row is Matt's, User1's or shared (**Whose** on the add/edit sheet; new rows are yours unless
you choose Shared, or the deck's owner when added from a deck's picker). You see and change only
yours and the shared ones, marked **Shared**. A deck takes only its player's or shared ones, and an
"either" deck or an intact product only shared ones, so the pickers offer just those. A shared row
used by the other person's deck says "one of User1's decks", without a link or a move.

On a saved built home deck, changing **Played by** with visible editable kit opens
**Review player and kit** (E8-S15 permitted-transition slice). Review the player,
sleeves and deck box together, choose permitted replacements or **None** to clear
each field, then **Use this player and kit** changes one local draft/Undo step.
Normal Save records them together. Shared sleeves retain their usual acknowledgment;
unavailable boxes cannot be chosen. Another owner's kit remains theirs to choose.
Recognized choices survive draft resume and rebase, and a deleted or changed choice
requires another review instead of becoming unchecked older text. Resumed changed-player
pickers load the appropriate choices; loading or failure keeps the draft and hides the
old player's catalog. Existing privacy refusals remain in force; additional guidance
after an actual hidden-kit refusal is still open.

- **Adding:** **Add**, then paste a link to the shop's product page or to the picture itself and
  choose **Find picture**. Deck Lab downloads the page, finds the picture the page shares (its
  `og:image`, or the like) and shows it with guesses for the kind, brand, name and, for sleeves,
  the count ("100 ct"). Check and correct them before **Save**. For sleeves the quantity counts
  every sleeve of the design, loose ones too; +50, +60 and +100 add a pack. A deck box has
  **Holds (sleeved cards)**, such as 80 or 100; leave it blank when not known, and nothing is
  checked.
- **Cropping a picture:** in the add/edit sheet, **Crop…** shows the whole picture with a box to drag,
  or to resize by its corners (with a finger too; on a keyboard, arrow keys move it and Shift with
  the arrow keys resizes it). **Square** makes it square, **Whole picture** resets it, and **Done**
  keeps it for **Save**. Only the part chosen shows everywhere the picture does. The file itself
  isn't changed: the crop is saved in the row's `crop` column, so **Change crop** or **Show the
  whole picture** can undo it at any time. A new picture starts uncropped. **Use a different
  picture**, **Save without a picture** and, when editing, **Replace picture** are there too.
- **When the shop blocks it:** some shops refuse downloads from anything but a browser. Then open
  the picture itself in the browser, copy its address, paste that and try again, or save without a
  picture. **Photo from this device** also accepts a photo or camera picture: JPG, PNG or WebP,
  up to 4 MiB and between 16 and 6,000 pixels a side. It stays in the sheet until **Save**;
  canceling stores nothing. The row and picture save together, and the same crop controls work
  before or after saving. An oversized or damaged picture is refused without changing the row.
- **Fetch limits:** only http and https links of up to 500 characters, on the usual ports and with
  no user name or password. Deck Lab never fetches from the home network (a link to the router or
  this PC is refused, after every redirect too), uses no proxy, gives up after 20 seconds, and
  downloads at most two things per link (the page and its picture). Pages may be up to 2 MB and
  pictures up to 4 MB; only JPEG, PNG and WebP pictures between 16 and 6,000 pixels a side are
  kept, recognised by their contents. A fetched picture waits in `decklab/data/accessories/staged/`
  for up to an hour; saving stores it with the row, in the same change. Pictures are served at
  `/accessory-img/<id>.<ext>?v=<the first 8 hex digits of its sha256>`: `v` is required (a wrong or
  missing one is a 404), and the answer is cached privately for a week (`Cache-Control: private`),
  so no shared cache (Cloudflare's) can answer for the owner check.
- **Choosing a deck's sleeves and box:** a built deck's page (its Overview) shows a Sleeves tile and a Deck box
  tile (picture, name, and "75 needed · 100 owned · 25 spare" or "15 sleeves short"; for the box,
  "Holds 100 · 1 box owned" or "Too small: holds 80, 100 cards here") with
  **Choose…**, on any device. The picker offers None, every design and **+ Add new sleeves**. One
  design may sleeve several built decks and intact products (Matt's decision of 2026-10-13: it's up
  to the players not to play two of them against each other), so a design other decks use says
  "Also used by X" (or "one of User1's decks") and can be chosen as it is: choosing it always warns
  first (Matt, 2026-10-19), asking "Use X here too?", with **Use them here too** (both keep it) or
  **Move them here** (offered only for decks you can see), which takes them off the other deck in the
  same change. Afterwards the Sleeves tile says "Also sleeves X", without a warning colour, and
  `deck push` or `product set-kit` choosing such a design prints a warning naming the other holders. A deck box is
  one box per deck: once every box of a kind is in use it says "In use: X", and only moving one
  makes room. Only the deck's Sleeves or Deck box line changes (two with a move). Choosing,
  clearing or moving a deck's kit is an edit of that deck (E10-S42): `POST /api/accessories/assign`
  needs `deck.edit` on the deck, and on the deck a move takes them from, as an editor save does, so
  User1 is refused an "either" deck's kit with "You can change the home decks played by you."
  (403; checked again inside the write). A product's kit keeps the rights it had: either home
  profile, with the shared kit. A deck that isn't built says "Sleeves are chosen when the deck is built." A
  product kept intact has one sleeve design and one deck box for all its decks: choose them from
  any of its deck pages, or in the Sleeves & boxes page's **Products kept intact** panel (the same picker). They're
  the product status's `sleeves` and `deck_box`, in the database. The library shows
  each deck's (and intact product's) sleeves and box under its card, with "15 sleeves short" when
  there aren't enough.
- **Product storage:** a product deck's Overview shows whether its product is kept intact or
  broken up. An admin can choose **Break up into storage** or **Keep intact**, then review the
  affected tables and confirm. Breaking up clears the product's sleeves, box and packed-token record; keeping intact
  reserves its cards together and requires saved deck lists. This changes the whole product,
  including all its decks. The preview checks both inventory and deck revisions again at Save,
  and preserves the existing kit owner's permissions. Other home viewers see the storage state
  without change controls. The saved result keeps warnings and table follow-up links visible
  until **Done** refreshes the deck page.
- **Product kit on the PC:** `python -m decklab.db product kit STEM [--json]` prints the current
  sleeves, box and products-list SHA. `product set-kit STEM --expect SHA --sleeves ID --deck-box ID
  -m "..."` sets one or both fields; omit a field to keep it, or use `none` to clear it. The
  product must still be owned and intact, and new choices must be shared accessory ids.
  `--dry-run` previews, and `--actor matt` changes attribution as for the other inventory commands.
  The one `kit.set` operation needs no card download or deck-table refresh.
- **Product packed token cards:** an owned intact product's Cards tab offers **Change product packed token cards**
  to a home viewer who may edit products. One record covers the whole box, including every generated deck page;
  it reserves existing physical token cards without adding or removing inventory. Paired faces count as one card.
  Blank means packing is unknown: it reserves nothing explicitly and retains the shared-card warning's
  one-per-used-row assumption. **Clear packed record** restores that state. **Plan packed token cards** on
  Tokens plans built decks and eligible intact products together. Each actual product subdeck has its own
  demand, sharing one physical capacity across all participants, and the result saves once for the box.
  The preview shows both whole-product totals and subdeck shortfalls. Products whose needs cannot be safely
  calculated, or which have no detected needs, retain their existing records. One mixed save requires every
  changed deck/product permission and rechecks inventory, deck, token-list and product-status receipts.
  On the PC, `python -m decklab.db product tokens STEM [--json]` prints the record and both hashes;
  `product set-tokens STEM --expect SHA --tokens-sha256 TOKEN_SHA --tokens "2 Treasure; 1 Beast // Dog" -m "..."`
  records it (`--tokens ""` clears; token SHA `none` only when no token sheet exists). `--dry-run` previews,
  and `--actor matt` follows other writes. Both receipts are checked again under the write lock. Product
  records and status receipts stay private even when home's collection and decks are public.
  Recording product token cards needs migration `0014_product_token_cards.sql`; this coding session has not applied it live. Before that migration, blank packing remains readable as unknown and ordinary blank-record updates still work; saving a recorded value refuses without partial changes.
- **Saving and history:** each add, edit, removal or choice is one change set in the audit trail,
  by whoever made it, such as "add sleeves Dragon Shield Matte (black)" or "set sleeves for Izzet
  Otters" by User1, shown on the Activity page (only to the viewers who see that row's owner: an
  accessory change's message and reason only to whoever made it). A row and its new picture are
  saved together, and every sleeve or deck-box move between decks and products (the inventory's
  `kit.set`) is one change, so nothing is ever half-moved. Nothing is committed to git.
- **Two people at once:** the list's token is worked out over only the rows you see (null when
  you see none), so another owner's change never gets in your way. If your list changed after the
  page loaded it, the save is refused with who changed it and when ("User1 changed the accessories list 7:42 pm today."; for a product's
  choice, the audit trail's last change to the products' status). **Load the latest
  and re-apply my changes** puts your changed fields back on top of the latest list, asking which
  to keep where you both changed the same field; **Discard my changes** drops them.
- **Receipts:** a product's choice changes the inventory, so a receipt previewed before it must be
  previewed again; a row's change or a deck's choice doesn't.
- **On the PC:** prefer the page. `python -m decklab.db accessories list|show|check|add|edit|remove`
  and `image put|remove` make the page's changes with its rules (AGENTS.md, "Accessories", has the
  columns, rules and commands), and a deck's Sleeves and Deck box lines change through `deck push`.
  `accessories check` (or `python -m decklab.lib.accessories --check`) reports broken rules and
  exits 2 when the database can't be reached. A product's kit can also be read with `product kit`
  and changed with `product set-kit`, as described above.

## Tokens

Choose **Tokens** (`#/tokens`, the top bar's More) for the token and reminder cards (in the database
since phase 3; each space has its own, and you see only the spaces you may). It works on phones and the
iPad as well as the PC. Each card is a tile showing its front (with its back overlapping when recorded):
the printing's picture when it's recorded, else example art of a token with that name, always labelled
"Example art" (never taken as its printing), else a letter; its printing and details ("TM11 5 · 2/2
Ooze"), how many there are, and chips for the decks it serves, with one "Details to check" only where
a deck relies on an unchecked card. Tap one for its sheet (details, notes, Remove at the bottom). Search
by face name, and filter by All, In decks, To check or Not used; both are remembered on the device.
**Tokens your decks make that you don't have** lists the tokens built and building decks and intact
products make that no owned card fits, as **Missing** and **On the way**, with the decks. **Token
orders on the way** (folded) lists token cards in orders that haven't arrived; they're received on
Receive delivery, never here.

- **Where the needs come from:** Scryfall links each card to the tokens, emblems and reminders (The
  Monarch, The Ring Tempts You, dungeons) it makes. So the list is approximate: tokens a card makes
  only through its rules text, and most token copies of other cards, aren't listed, and some listed
  ones appear only in certain modes or for the opponent. Deck Lab never says how many a game needs
  from the cards alone (the deck page's suggested counts, below, are estimates from simulated games).
  Every place that shows tokens says so.
- **How a card is matched:** by face name, then by the details recorded for that face: P/T, colour
  and abilities. **Ready** means they agree; **check** means some aren't recorded ("P/T and colour
  not recorded"); **different** means a recorded detail disagrees ("your card says no deathtouch;
  Hornet Queen's Insect has deathtouch"), so it's shown as a stand-in; **on the way** means only an
  order covers it; **none owned** may add "closest: Zombie / Zombie Knight ×8". Notes never change a
  match. None of these is an error: a stand-in is fine at home, so tell your opponent what it is.
- **Details** are `;`-separated parts: `1/1; green; flying, deathtouch`, `no lifelink` for an
  ability the card lacks, `colour unconfirmed` for a part not checked. Other words (a type line,
  rules text, `printed pink`) are kept and shown but never compared.
- **The deck page** has a **Tokens** part on its Cards tab, after the decklist: each token the list makes, which cards
  make it, the cards to grab ("(same card as for X)" when one card serves two tokens), stand-ins and
  what's on the way, tokens only sideboard cards make, and, folded away, cards that make copies or
  may make things Scryfall doesn't link. A token without a recorded printing shows the Tokens page's labelled example art. The Overview
  says when something's wrong ("No Insect tokens") and jumps there. The library shows a token line under a deck only when something's missing, different or on
  the way (not for idea decks). Unreadable token rows show as an info line, never a warning.
  Under **Counters and dice** the part also lists, read-only, the counter kinds and dice the list's cards
  use, each with its cards ("Poison counters (on players)", "d20"), read from their rules text, types and
  keywords (`lib/tokens/counters.py`, E7-S24), so approximate; owned dice and counters aren't recorded yet.
  `python -m decklab.lib.tokens <deck-id>` prints them too.
  **Suggested counts** (E7-S08): when the list's saved Forge matchups were played with the card log's
  token tally (since 2026-10-29), each token gets "Estimate from simulated games: Forge games peaked at
  N; most games at most M (G games of T made one)", the most of it on the battlefield at once in a game,
  and how many more that is than the cards that fit. Forge's names are matched to the tokens by name, so
  tokens sharing a name count together; tokens only the opponent gets, emblems and reminders get none.
  Only matchups whose every side you can see count, and only the deck's Tokens-part viewers see them.
  Without such games the part says why ("Play its matchups again to get them"); older games don't count.
- **Adding and editing:** **Add a token card**, then the front and back face names (suggested from
  Scryfall's names, with "Did you mean …?" for a near miss), each face's details, the quantity of
  physical cards, and optionally the printing (set, collector numbers, finish). **Swap front and
  back** swaps everything of the two faces. **Single-sided (checked)** clears the back and adds
  `single-sided verified` to the notes. Names must be Scryfall token, emblem or reminder names, and a
  printing must be that face's; while the card data is loading, names aren't checked and the page
  says so.
- **The same card twice:** the page never merges rows. Adding a card already listed asks first:
  **Add 2 to that card**, or **Keep it as a separate card** when either row isn't fully known (as
  receipts keep unverified variants apart). An edit that would turn a row into another listed card,
  or make a row fully known while another row names the same card, asks too, but offers only
  **Keep it as a separate card**, and only on the same terms. When both rows are fully known the edit
  is refused; change that card's quantity and remove this one.
- **Removing:** **Remove** (at the bottom of a card's sheet) asks first and takes an optional reason,
  which goes into the change's record. For a partial loss, lower the quantity in the sheet instead.
- **Saving and history:** each add, edit or removal is one change set in the audit trail, such as
  "add token Zombie // Zombie Knight" by Matt, shown on the Activity page. The rows stay in the
  order receipts use.
- **Two people at once:** as on the Sleeves & boxes page, a save to a list that changed since it loaded
  is refused with who changed it, and **Load the latest and re-apply my changes** or **Discard my
  changes** sorts it out.
- **A save between a receipt's preview and its apply** makes the apply ask for a fresh preview.
- **On the PC:** `python -m decklab.db tokens list [--space S]` numbers the rows and prints the list's
  sha; `tokens add`, `tokens edit ROW --expect SHA` and `tokens remove ROW --expect SHA --reason R`
  make the page's changes with its rules (each with `-m`), refusing when the list changed since
  that listing; `tokens check` (or `python -m decklab.lib.tokens --check`) reports rows that break
  the rules. AGENTS.md, "Token cards", has the details.
- **Card data:** tokens need card index format 4, which is built from the Scryfall files already
  downloaded on the next `python -m decklab.lib.cards update` or server restart (about 4 seconds; no
  new download unless the bulk files are over a week old). Until it's rebuilt, the deck pages and the
  library say the card data needs rebuilding, as for any index change; the Tokens page still lists
  and edits rows, with name checks off and without the decks' needs. A deck page opened in the
  moment the new index is being loaded may say "Token data is being rebuilt; refresh in a minute."

## Editing and saving decks

### Checking which version is running

**Settings** (`#/settings`, an admin's page: the avatar menu's Settings or About Deck Lab) shows
**Server** (the commit at startup) and **Checkout** (the latest local commit), plus whether the server
code is current; the footer is one quiet line, the prices' date and the exchange rate. It checks every 30 seconds while the page is visible,
when you return to the page, and when you press **Check for updates**. Checkout checks are cached
for up to five seconds. This compares against the local checkout; it does not fetch from GitHub.

A banner appears when changed server code needs a restart, or when this browser page needs a reload
(a member sees only those; the note about uncommitted code is an admin's).
Changed `decklab/db/*.py` counts as server code; a new migration file doesn't (run `migrate`), and the
same banner then shows "Deck Lab's database" warnings (see "The database warning banner" under Database).
**Reload page**, in the avatar menu for everyone and in the update banner, fetches a fresh page address while keeping the current route and page options. It uses the editor's normal unsaved-changes protection and keeps saved browser drafts, device choices and preferences. JavaScript and CSS addresses include the web revision, so an update gets fresh files without clearing Safari website data. For an older page without the menu action, open the site with a fresh `?v=` value before the `#` (for example `http://homepc.local:8642/?v=20261015`). Restart the server on the PC with
`python -m decklab.lib.homenet restart` when requested, then reload the page if its banner asks for it.
Neither action happens automatically. Deck saves don't change Checkout: they're saved in the
database, never committed. Uncommitted application changes are labelled **+ local changes**; a missing Git
repository or failed check is shown as unverified instead of claiming the server is current.

The commit and source fingerprints are frozen before application modules load. Current runtime/config
and browser-asset fingerprints detect edits, additions and deletions, including changes made without
a commit. Each HTML response also records the page files' fingerprint, so an already-open tab can
detect an update after the server restarts.

### Saving

- **Ways in:** **Edit** on a deck's page (the Planned list or the Play-now list, whichever is shown), **New deck** in the library, **Save as a new deck** on product decks, Beginner Box halves and pairings (those stay as they are; a Commander precon becomes a Commander deck, anything else a casual one), and History's **Open … as a draft**. All of them work on every width (a phone gets the Quick edit; see "Editing on every device" above).
- **Adding cards:** type a name in the finder and add a result (names come from the local Scryfall data, so a misspelled name can't get in), or **Paste a list…** in Arena/MTGO form; names it doesn't know are shown with "did you mean" suggestions and never added. A new line gets the printing the collection has most of, else the cheapest non-foil paper printing; each line's printing can be changed in its printing sheet (a grid of the printings' pictures with the copies owned, and Move and Remove at the bottom).
- **Deck details** sets Status, Played by and Archetype, and for a Commander deck its Target bracket. A built deck also gets **Built version** (when the deck has both lists: which one is put together), **Sleeves** and **Deck box**. Sleeves and Deck box are pickers of tiles from the accessories list (see "Accessories" above): None, then each design with its picture and a live count for the list being edited ("75 needed · 100 owned · 25 spare" or "15 short · 60 owned"). Arrow keys move between tiles. A design another deck or intact product already uses says "Also used by X" and can be picked after a warning, "Use X here too?" (one design may sleeve several decks); a deck box whose every box is in use says "In use: X" and can't be picked. **+ Add new sleeves** and **+ Add a new deck box** open the Sleeves & boxes page's add sheet and pick the new row. On a phone, Status stays visible above folded Deck details. The line stores the row's id; the review shows its name. An older free-text value (such as `red`) appears as a "Keep “red”" tile and can be kept, but new free text can't be typed. Taking a built deck apart (Built to Building or Idea) removes Built version, Sleeves and Deck box, since its cards go back into storage unsleeved. Warnings, never blocks: a built deck with no Sleeves; too few sleeves for every card of the built list (sideboard, companion, commander and basics included; each deck against the row's count on its own, however many decks share it); a deck box used by more decks than its quantity; and an id of the wrong kind.
- **Deck rules are warnings, not blocks** (under 60 cards, more than 4 copies, and the Commander checks), so decks in progress can be saved.
- **Save** (or Ctrl/Cmd+S) saves in place when nothing blocks it and the deck hasn't changed since; the review sheet (what changes, the warnings and what saving does) comes up only for blocks, a conflict or an error. The server works out the new text, changing only Deck Lab's parts (the header fields, the decklists, the owned-vs-needed table and the rate line above it; see "The deck text format" in AGENTS.md), adds the "Decklist changed in Deck Lab on ..." line when a list changed, and saves it in Deck Lab as one change set by the profile ("save <Title>" or "new deck <Title>", shown on the Activity page and as a new revision in the deck's History; a change to Sleeves or Deck box goes in the same change through the inventory's `kit.set`). The page says so in a toast (**Save & view deck** opens the deck page with a box saying what was saved). The write-up from the Notes tab, and **Mark write-up as current** (which takes the "Decklist changed" line off), go with the same save. Nothing is committed to git.
- **Other decks' tables:** a save can change what other decks can use (a built deck's list, for example). The editor (or the deck page after **Save & view deck**) then lists the decks whose owned-vs-needed tables are out of date, and **Update their tables** rewrites just those tables (with today's prices) in one change, all of them or none (decks the profile may not change are left out and listed as `skipped_not_allowed`). A deck's page also says when its own table is out of date (on its Cards tab), with **Update the table**, and the Decks page lists every out-of-date table, with **Update all** (see "Decks (the library)"). On the PC, `python -m decklab.db deck tables [--reprice] --apply` does the same.
- **Two people at once:** if the deck changed after the page loaded it, the save is refused (409) with who changed it and when, from the deck's last saved revision ("User1 saved Gruul Ramp in Deck Lab ..." for a page's save; a change from the command line or an import isn't called a Deck Lab save, and a revision that changed Sleeves or Deck box names its message only to whoever saved it). **Load the latest and re-apply my changes** puts your changes back on top of the latest version to check and save again. Someone who may not edit the deck gets a 403 instead, never who changed it. A deck deleted while **Update their tables** ran is listed as deleted (no who or when).
- **On the PC:** `python -m decklab.db deck pull ID -o FILE` and `deck push ID FILE --expect N -m "..."` read and save a deck's whole text, refusing a push when the deck was saved since the pull; `deck new`, `deck delete`, `deck history` and `deck revision` do the rest. A deck can't be renamed (its id is fixed). AGENTS.md, "Decks", has the rules.
- **Unsaved changes** are kept on the device, per person, deck and list. If browser storage is full or blocked, the editor warns that the changes exist only in the open tab and requires saving or explicitly discarding them before leaving or switching people. Closing the browser can still lose edits that it could not store.
- **Write protection:** the server takes changes only from Deck Lab's own page. Every POST and PUT must be JSON with the header `X-Deck-Lab: 1` (and an `Origin`, if sent, that matches the page's address) and name a profile from `config.json`. Another web page open on a phone can't send that, so it can't change decks.

## Matchups (Forge)

V2 runs checkpoint completed, validated chunks during play (the first chunk,
then every five seconds or 100 games). The saved run is labelled **Checkpoint**
until it finishes; after an interrupted run is picked up, it is labelled
**Recovered**. Already saved game IDs are never counted twice. Ordinary matchups
continue after the reserved range, leaving unfinished game numbers unused;
paired experiments retain their existing matching-number rules. A hard crash
can still lose work since the latest checkpoint. Graceful Stop saves the run.

Two decks play each other in [Forge](https://github.com/Card-Forge/forge), a free Magic rules engine, with its computer players on both sides. Deck Lab runs its own build of Forge, from a fork (see "Deck Lab's own Forge" below), installed outside the repo at `C:\Tools\forge-decklab` (Forge 2.0.15 with Deck Lab's changes, run with the JDK at `C:\Program Files\Java\jdk-26.0.1`). The plain release stays at `C:\Tools\forge` for comparisons. `config.json` can change `forge_dir`, `forge_java`, `forge_workers` (16; use 12 if the PC is busy with other things), `forge_clock_s`, `forge_pool_idle_s` (900: how long warm workers stay up with nothing to play), `forge_pin` (true: pin each warm worker to one core), `forge_field_inflight` (4: how many matchups a field run or a test of a change plays at once) and `forge_variant_margin` and `forge_variant_margin_one` (0.02 and 0.03: what "makes little difference" means for a test of a change against the field and against one deck). `forge_performance_mode` and `forge_game_patches` are for the overnight run's measurements only; leave them true. `forge_decision_log` (`[]`) names cards whose AI decisions Forge prints (see "The decision log" below). `forge_batch_games` is no longer used (since 2026-10-03); it's kept so older `config.json` files still load.

- **The Matchups home** (`#/matchups`, in the top bar) switches between **Matchups** and **Rankings**, remembering the view and format on this device. Matchups is a matrix of every deck against every other: each cell the row deck's latest win rate, with the number printed, on a diverging scale (even in the middle); results of an older list are faded, and an empty cell has a **+** to play that pair (while you may start runs). A tap opens the pair's page. On a phone it's **Show matchups for [deck]** and that deck's results as a sorted list. The runs playing now are listed, and while one plays (or waits) the top bar shows a small turning ring on every page, "Forge is playing: show progress" ("A Forge run is waiting: show progress" while one only waits): tap it for each run's progress ("game 37 of 200", about how long is left), Stop for whoever may stop it, the runs waiting and a link here (a popover on a desktop, a sheet on a phone; E11-S30 slice 6). A result's win rate is a mono figure with its 95% range on a bar that always runs from 20% to 80%, so bars compare from page to page, and says how long ago it was played.
- **Rankings** (2026-10-15, E3-S10) lists every current list of the selected **Constructed** or **Commander** format. Within each connected group, lists sort by their percentage rating and show its 95% range, the likely rank range and decided games. The rating estimates the win rate against an average current field list in that group, balanced for who starts. **Unsettled** and the reasons explain too few games or an uncertain rank. Groups without connecting games have separate ranks and cannot be compared; unrated and excluded lists stay visible with their reasons. Alternate versions outside the field remain visible; target and Play-now aliases with identical cards and pilot share one row. Only current saved evidence counts as current: older lists and earlier engines do not acquire a current rating. This is a read-only view and starts no Forge games. It refreshes while selected and visible, with a clear error if the read fails.
- **Start one** with **Play a matchup** there (a sheet), the **+** of an empty cell, or a deck page's Matchups tab. Pick two lists of the same kind (Commander decks only play Commander decks, as 1v1 Commander), then how long to play, in one vocabulary shared with Play the field and Test this change (since 2026-10-13; the modes since wave 3, 2026-10-03):
  - **Precise** (the default; "How well does this deck do here?" before): 400 games first, then as many as it takes to know the win rate to within ±3 points (usually 700-1,100, at most 3,200).
  - **Settle it** ("Which deck wins?"): checks at 400, 800, 1,600 and 3,200 games, and stops as soon as one deck is clearly ahead or they're about even (within 5 points).
  - **Quick look:** 200 games, a first idea.
  - **A set number of games** (under More options): 200 to 3,200, as before.

  The choice is the profile's, remembered on every device. Each choice shows one rough time. While it plays, the progress bar is marked at the run's planned checks, the result's range bar shows a dashed "live range", which is wider than the final one because the run may stop at any time, and no verdict until it ends. Measured on 2026-10-03 with the warm pool (below) and 16 workers: Izzet Prowess vs Gruul Ramp played about 1,430 games a minute, Selesnya Rabbits vs Orzhov Vampires (a big-board matchup) about 160 and Giada vs Finneas (1v1 Commander) about 230. So once the workers are warm, 800 games of Izzet vs Gruul take about 35 seconds and of Rabbits vs Vampires about 5 minutes. The page's rough time comes from the pair's own saved speed when it has one (see "Time estimates" below).
- **Up to 4 matchups play at once** (since wave 2; it was one), sharing the warm pool's workers, the oldest run first; others wait their turn. Field runs and tests of a change (below) are jobs of their own, 2 at a time, whose games share the same pool. Practice hands don't wait for them. Both phones see the same runs, and either person can **Stop** one. Stopping keeps every game that finished.
- **The warm pool** (since wave 2, 2026-10-03): with the card log on, the server keeps Forge workers running between games instead of starting a Forge process for each batch, and every matchup waiting takes chunks of games (up to 25) from one queue. The pool starts with the server and its workers with the first games.
  - **Memory:** a warm worker is a Java process that keeps its memory while it waits (up to `forge_xmx`, 1 GB, of heap each, plus Java's own), so after a run there can be up to `forge_workers` of them. They quit after 15 minutes with nothing to play (`forge_pool_idle_s`), and the pool never keeps more alive than the slots other Forge runs on the PC leave free.
  - **Seeing it:** `python -m decklab.lib.forge pool` lists the server's workers (state, slot, games played, heap, idle time), and `python -m decklab.lib.forge status` has a "warm pool" line. **Stopping it:** stopping or restarting the server (`homenet stop` or `restart`) ends every worker; otherwise they go by themselves when idle. A change to `forge_pool_idle_s` takes effect at the server's next start.
  - **Cores:** a worker playing games is pinned to one physical core, the V-Cache cores (logical CPUs 0-15) first; `"forge_pin": false` leaves Windows to place them. Each holds a slot of the PC's budget only while it plays, so an idle worker leaves the CPU to other runs.
  - **When a worker goes wrong** (a game hits the clock or the AI's 5 s, or it crashes), the pool replaces it and plays that chunk's later games again in another worker, with the same seeds. A worker also retires after 2,000 games. If the warm workers can't start at all, the run plays the same games in one-shot Forge processes and says so: on the command line, and on the matchup page's progress and its Playing now rows (`job.fallback` and the Running item's `fallback`, a sentence with no worker counts or names; E3-S26).
  - **How it measured** (the overnight run of 3-4 October): warm, it was 1.93x as fast as wave 1's cold batches on Izzet vs Gruul, 1.17x on Rabbits vs Vampires and 3.39x on Giada vs Finneas; a fresh pool, start-up included, 1.41x on Izzet vs Gruul. Warm workers played the same games as fresh processes (0 differences in 490 Constructed games checked over 3.2 hours), Java used about 20 GB at the 99th percentile with 16 workers, and idle workers quit on time.
  - **Runs from the command line** (`play`, `replay`) play in the server's pool when the server is running and plays the same engine; otherwise, or with `--local`, in a pool of their own that closes when the run ends. If the server stops mid-run, the command-line run finishes in a pool of its own.
- **How a run is split:** with the card log on, a run's games are numbered and cut into chunks of at most 25, never across a block of 25 games (the decks swap seats every 25), and the pool's workers take them as they come free. Without the card log (plain Forge), each run starts up to `forge_workers` Forge processes at once, each playing at least 25 games: with 16, 200 games are 8 processes of 25, 400 are 16 of 25, 800 are 16 of 50, 1,600 are 16 of 100 and 3,200 are 16 of 200.
- **Pausing simulations, or using fewer workers** (the Settings page, `#/settings`, admins only; `GET/PUT /api/simulations`): **Simulations** lets only admins start runs (the default), anyone, or nobody (paused), for when the PC is busy. It goes by each profile's role, even on the home network. Practice hands and saved results stay open to whoever sees their decks, stopping a run is an admin's for now (E10-S30), and runs already going carry on. Anyone who can't start one sees why beside each Play or Start, never across the page, in words that name nobody ("Only an admin can start simulations right now."; E10-S34, 2026-10-18). A member's `GET /api/simulations` is only the mode, `may_start`, `why_not` and `may_edit`: who set it, when and the worker counts (`by`, `since`, `workers`, `max_workers`) go only to whoever may change it (an admin, a script). The mode is the database's `simulation_mode` row (with who set it and when; "Set simulations to paused" in the audit trail). While it can't be read (any database error), Deck Lab goes by the last mode it read, else admins only, and says so on the Settings page (and beside the run controls of those who can't start runs); changing it then answers 503 before the worker limit is touched. **Forge workers** lowers how many Forge processes compute at once, for the whole PC (the command line too), from each run's next chunk of games. The limit is `limit.json` in the slots folder below, and `python -m decklab.lib.forge slots` says when it's set. Forge's processes always run below normal priority, so other programs come first anyway.
- **Forge processes share one budget for the whole PC:** `forge_workers` is the most Forge processes computing at once on this PC, from the page and from every command-line run, in every checkout of the repo. A run that finds them all in use waits, and the page and `play` say "Waiting for other Forge runs on this PC to finish." Each process holds a slot, an OS lock on a file in `%LOCALAPPDATA%\DeckLab\forge-slots` (never in `decklab/data`). The lock goes away with the process however it ends, even with `taskkill /F`, so a slot is never left taken. The files stay there and are never deleted, which is fine. A process waiting for a slot holds a `want-...lock` file there the same way, and a busy warm pool that frees a slot while someone waits leaves it free for a moment, so a pool with a long queue doesn't keep every slot until it's done. The environment variable `DECKLAB_FORGE_SLOTS` points Deck Lab at another folder (the tests use their own). `python -m decklab.lib.forge slots` shows who holds them.
- **Forge runs below normal priority,** so the PC stays usable during a run, and the page's practice hands come first. With nothing else busy it shouldn't slow a run: the timings above were taken with it.
- **A pair's page** (`#/matchup?a=&av=&b=&bv=`, or `?key=` for a saved result) leads with the verdict ("Mono-White Angels is a big favourite: wins about 9 in 10") and a bar, at most one caveat line and **Play more**; **Why we're confident** and **Details** start closed, and the pair's earlier results are listed below (it never says "haven't played" when there are some). The Matchups pages and a deck's Matchups tab ask again while they're visible (every 15 seconds when idle, so runs started on the other device show up) and say only when the connection is lost. Reading them never starts a run.
- **Real games** on a pair's matchup page shows the viewer's visible recorded human wins, draws, game count and date range beside Forge's verdict. Matching requires the same pair of deck identities (renames included) and the historical main-deck/commander cards actually played; a sideboard plan's played main must match. Printing choices, unused Sideboard and Companion sections are not compared. The first deck's human percentage is plain wins divided by every matching recorded game, draws included, and is labelled separately from Forge's simulated headline and its going-first/going-second balancing. Fewer than 10 matching games says **Too few real games to confirm or contradict Forge yet**; ten or more remain observations affected by players, choices and chance. An unavailable or unsupported comparison never claims zero games. Only aggregate counts and dates are shown, with no player names, notes or record ids; the panel makes no extra read or write and does not change field ratings. An older API without the summary keeps its existing result view.
- **Results** are saved in `decklab/data/forge/results/` (not in git), one file per pair of lists and engine. **Play more** adds to the same result. Editing a deck gives its list new results; the old ones stay, marked "Older list".
  - **Earlier engines** (since wave 2): each game now has its own seed and a coin flip for who starts, so games played before 2026-10-03, or with plain Forge while the card log was off, are kept apart from today's. Their results stay as they were, marked "Earlier engine" on the page (a tag only while today's engine has results elsewhere; otherwise one line above the list) and in `list`, and never pooled with new games. Playing more of one starts a new result with today's engine. Per-card numbers count only today's engine's games, and say how many were left out.
  - **Replaying them:** `python -m decklab.lib.forge replay --dry-run` lists every saved matchup played with another engine whose two lists are still current, how many games today's engine needs to catch up, and a rough time; `python -m decklab.lib.forge replay` plays them (low priority in the server's pool, so the page's runs go first). Ctrl+C stops and saves, and running it again plays only what's missing. It refuses while the card log is off. Run it when the PC is free for a while. The 22 matchups (26,094 games) played before waves 2 and 3 were replayed by the overnight run and moved in on 2026-10-04 (see "Replaying, and moving staged results" below); the 37 old results stay, marked "Earlier engine".
  - **What starts a new engine:** a Forge upgrade, the card log turning on or off, and (since wave 3) adopting a card-script override set or a pilot. An adoption only re-keys the matchups whose lists it touches, so `replay` then plays just those.
- **Reading them:** the headline is the first deck's win rate, balanced for going first and second, with its 95% range. Forge's computer players are weaker than people and handle some decks better than others, so compare decks with it rather than treating it as real odds. The page lists each deck's cards Forge's AI never plays. It marks results that mean nothing (a deck whose commander the AI never casts; the Gisa decks were, until Deck Lab's Forge learned to play Ghoulcaller Gisa on 2026-10-11).
  - **Who's ahead** (since 2026-10-03): "<deck> is ahead" when the range leaves out 50%; "About even" when the whole range is within 5 points of 50% (45-55%); otherwise "Not settled yet". When the first two both hold, "<deck> is slightly ahead (by under 5 points)".
  - **Starting player:** the starting player's chance of winning, the average of both decks' win rates going first, with its range. (Before 2026-10-03 it was the share of games the starter won, which misled: Forge's loser starts the next game.) Since wave 2 a coin flip decides who starts each game, so each deck goes first in about half; results of earlier engines, and plain Forge's, still have the loser starting the next game.
  - **Engine notes:** "How these games were played" says which engine played them. A deck Forge's AI plays as a slower, non-aggro deck (its name holds "Control", or its nonland cards average 4 mana or more, counting each different card once and rounding down) is noted; since wave 2 that applies in every game.
  - **How far to trust these numbers:** how far two results of this many games can differ by chance alone; a "Forge pilots <deck> poorly" box for each deck whose cards Forge's AI is known to misplay, with those cards and why; a caveat when both decks hold counterspells (Forge likely understates going first in tempo mirrors); and "Commander results are indicative only" on Commander matchups. The deck page's Matchups tab shows the same "Forge pilots this deck poorly" box. The flag comes from the cards' Forge scripts: a deck is flagged when the AI never casts its commander or holds it back, when it has 3 or more cards that pump the whole team (Overrun-style spells, or permanents with such an ability, which Forge's AI judges one creature at a time), or when 4 in 60 of its cards are kinds the AI misplays (counterspells count half). On 2026-10-03 that's Selesnya Rabbits, The Free Peoples, Finneas, Gisa, the Wretched Ranks precon and Hare Raising.
- **How each card played** (Milestone 8): every run keeps Deck Lab's **card log**, which follows each card through Forge's games without changing them. A matchup's page then has **How each deck's cards played** (its card names open the card viewer), and a deck page's Matchups tab has **How its cards played**, pooled over every saved matchup of that list. For each card:
  - **drawn:** the share of games it reached the hand (the opening hand, a draw, a tutor or a card returned to hand);
  - **cast once drawn** (for a land, played): the share of drawn copies that were cast or played;
  - **stuck in hand:** the share of drawn copies still in hand when the game ended. A copy can be both cast and stuck (cast, bounced, held), and a discarded one is neither;
  - **average turn cast:** each player's own turn number, so turn 3 means the same on the play and on the draw;
  - **win rate when drawn and when not,** and the difference with its 95% range, then a **best estimate**: the difference pulled toward 0, the more so the fewer the games, since most cards' real effect is small. A verdict appears only once the card has 30 games each way. Since 2026-10-03, "won more" or "won less" also needs the card to stand out among the deck's cards (a Benjamini-Hochberg test at 10% false discoveries), as well as a range clear of 0; otherwise it's "no clear difference", and a range clear of 0 that could be chance among that many cards says so. These win rates aren't balanced for going first (that moves them about a point).
  - **in hand by turn 3** (since wave 2, 2026-10-03): the verdict is now "won more/less when in hand by turn 3", comparing games where a copy was in the deck's hand by its own turn 3 (the opening hand, or drawn by then) with games where none was. Long games draw more cards, which made "when drawn" lean toward expensive cards with no effect from the card at all; by turn 3 every game has seen about as many cards. Each card's drawn win rates are still shown after it, and the `cards` command has a "by t3" column. A result kept before 2026-10-03 has no turn-3 numbers, so its matchup page still judges on "when drawn", marked "(leans with game length)". Lands get no verdict and always show their win rates when drawn and when not.

  The deck page leads with what stands out: the spells most often stuck in hand, cards drawn but never cast, and the clearest win-rate differences. For a viewer who may see the deck's space's collection, each spell drawn but never cast lists its **Free replacements** (E3-S25, 2026-10-29: up to 5 pool cards no other built deck or intact product holds, of the same type, a shared colour and mana value within 1, from `GET /api/deck/replacements`; nothing for anyone else), each with **Test this swap**, which opens the editor with the swap as its draft (asking first before replacing another unsaved draft) and its **Test this change** sheet open. Its differences are worked out matchup by matchup, so a card isn't credited for which opponents the deck played most (its two win rates are still every game's). Numbers from fewer than 800 games with the card log are marked early (100 before 2026-10-03); when older games are mixed in, that counts the games with turn-3 numbers ("Early numbers"). Games played before the card log have no card data, so the page says "from N of M games"; **Play N more games** fills them in. Games played with an earlier engine don't count either: the page says how many were left out, and `replay` (above) plays them again.
- **The card log needs the full JDK, version 21 or later** (`javac` and `jar` beside `java.exe`; the JDK above, 26, has them). Deck Lab builds the card log's jar itself, into `decklab/data/forge/cardlog/`, at the start of a run, with the newest JDK it finds (or `forge_java`'s); Deck Lab's Forge (below) uses Java's virtual threads, so it needs that JDK too. The card log is also what the warm pool runs, so without it runs play cold plain-Forge batches as before. It's only used with a Forge build it was checked with: each build of Deck Lab's Forge counts as a Forge version of its own (`2.0.15-decklab-<commit>`), and a stock Forge gets no card log at all. Matchups aren't keyed by the build, though, but by its engine release (see "The engine key" below). **After installing a new build, run `python -m decklab.lib.forge cardlog-check` once:** it plays a few Constructed and Commander games (12 and 3; `--games` and `--commander-games`, at most 25 each) four ways: plain Forge one game per process, the card log with Deck Lab's game-changing changes to Forge off and on, and without the card log, then in a warm worker, and compares them game by game. Until a check passes, matchups still play with plain Forge, without card data, and the page says "Per-card stats are off" and why. `python -m decklab.lib.forge serve-check` runs just the warm-worker part (a warm worker plays the same games as fresh processes), and exits 1 when a game differs.
- **Deck Lab's own Forge** (since 2026-10-11): Deck Lab's changes to Forge live in a fork, [matt439/forge](https://github.com/matt439/forge), cloned at `C:\VSProjects\forge`, on its `decklab` branch. Its own `decklab/install.py` builds and installs it: that's the `python decklab/install.py` below, run from the fork's folder, not this repo's (a new install's steps are in [SELF-HOSTING.md](../SELF-HOSTING.md), "Forge simulations"). The branch starts from the release Deck Lab uses (tag `forge-2.0.15`) and carries the changes as commits:
  - `AbstractMulligan` without the 100 ms pause Forge takes on every mulligan. It plays the same games.
  - `AiController` runs each AI decision's evaluation on a Java virtual thread instead of a new thread each time. It plays the same games.
  - `AiAttackController` checks the creatures that must attack one after another, in a fixed order, instead of on a new thread pool for each attack. With two or more must-attack creatures, Forge's own order varies from run to run, so this changes games: it's part of the engine (as `attack-requirements-in-order-1`).
  - `Match` builds each library in the deck file's line order (Forge's own uses hash order), through a hook Deck Lab's `DeckOrder` plugs into, and the decks load from a random-number stream of their own, so a changed version of a deck sees the same shuffles as the original. Tests of a change need it. It changes games, so it's part of the engine too (as `deck-order-1`).
  - AI fixes: Ghoulcaller Gisa and God-Eternal Bontu, which stock Forge's AI never cast, are played. Since AI round 1 (2026-10-13) this is the game patch `gisa-bontu-1`: on by default, and with `-Ddecklab.gamePatches=off` Forge's own code plays and the AI leaves both cards out, as stock Forge does. One gap is left open: Forge's `Deck.UnplayableAICards` (in forge-core, which can't see the switch) and Deck Lab's own readers of Forge's scripts still see the branch's scripts, so with game patches off they don't list Gisa or Bontu as cards the AI never casts.
  - **AI switches** (since AI round 1): fixes to Forge's AI that are off unless a list's pilot names them (see "Pilots" below), each by an id in the fork's `decklab/ai-switches.txt` (forge-ai's resources), checked in Java by `forge.ai.AiSwitches`. They're always off with game patches off. `removal-in-combat-1` (the combat-removal fix: on its own turn the AI removes a blocker that would kill its attacker; Forge's own code only does it on the opponent's turn), `etb-harmless-1` (the optional-target fix: a creature or spell whose optional ETB or trigger has no target is no longer refused) and `prowess-precombat-1` (the prowess-first fix, experimental: cheap card draw and burn are cast before combat when a prowess creature can attack). An id's behaviour never changes once a build with it has been used: a change gets a new id (`-2`).

  Until 2026-10-11 the first four were copies compiled into the card log's jar, used only when Forge's jar held the exact class each was copied from. Forge's jar now lists Deck Lab's changes (`decklab/forge-patches.txt`), and the engine id names the game-changing ones from that list. Plain Forge (when the card log is off) plays them as Forge's own code (`-Ddecklab.gamePatches=off`), as its engine has no game patches. The card log's jar holds only Deck Lab's own classes (the card log, the game loop, pilots and start-up hooks), and they use the fork's hooks, so a stock Forge gets no card log and runs play plain Forge. Deck Lab's start-up plugs its pilots into `AiSwitches` (found by reflection, so Deck Lab's Java still runs on an older build without it).

  **The engine key** (since AI round 1, 2026-10-13; engine id version 3): a matchup's key names Forge's engine release, not its build. Stock Forge's is its release (`2.0.15`). A fork build's is its base release and a hash of the `forge-gui/res` files it changed (`2.0.15+res.<12 hex digits>`, from `decklab-build.txt`'s `base=` and `res_sha256=`); the build's game patches are in the key too. So a new build whose changes are all off by default (AI switches) keeps every saved result current, and needs no replay. A fork build from before AI round 1 (no `res_sha256=`) is keyed by its whole build name. When `decklab-build.txt` can't be read, Deck Lab uses the release it remembered for that build, or refuses to start a run. The rule for the fork from now on: a change that plays differently with every switch off is a listed game patch with a new id, gated so `-Ddecklab.gamePatches=off` plays Forge's own code; a change that's off by default is an AI switch.

  **Changing Deck Lab's Forge:**
  1. In a worktree of `C:\VSProjects\forge`, commit the change with a test in the fork (a scenario or unit test under `forge-gui-desktop/src/test/java/forge/ai/`) that shows it plays Forge's own code with its switch off. A fix meant for Forge itself also gets a branch from upstream's master and a pull request, which the user approves first.
  2. Build it into a scratch folder: `python decklab/install.py --out <scratch folder>` (Maven is at `C:\Tools\maven`; set `JAVA_HOME` first in Git Bash). It builds the jar named after the commit (`2.0.15-decklab-<commit>`), with the branch's card scripts swapped into the release's `cardsfolder.zip`, and never touches `C:\Tools\forge-decklab`.
  3. Check it plays the installed build's games: `python -m decklab.lib.forge engine-check --old C:/Tools/forge-decklab --new <scratch folder> --pair <deck> <deck> ...` (see "engine-check" below). The first time a pair is used, run it with `--old` and `--new` both the installed folder first: that's the noise floor, which shows whether a build repeats its own games for those lists. Accept exit 0, or 3 only where the noise floor gave 3 too (Commander pairs, time limits).
  4. Merge it into `decklab` with `git merge --ff-only` on a clean working tree (a merge commit, or a `-dirty` tree, is another build name than the one checked), then run `python decklab/install.py` there, which installs `C:\Tools\forge-decklab`, and confirm the installed `decklab-build.txt`'s `build=` is the scratch build's.
  5. Run `python -m decklab.lib.forge cardlog-check` here, then put the new version, build and `simjar.source_sha256()` in `simjar.CHECKED`, `CHECKED_BUILDS` and `CHECKED_SOURCE`, so a fresh clone with that build installed has the card log on.
  6. When the new build is the one a new install should download, make its release: in the fork, Actions, **Deck Lab release**, with the build's commit and a draft release (the fork's `decklab/RELEASE.md`), check and publish the draft, then move `simjar.RELEASE` to the build and update the build name and links in [SELF-HOSTING.md](../SELF-HOSTING.md), "Forge simulations". `python -m decklab.lib.forge status` names the build it expects.
  6. A change to what a game patch plays gets a new id in `forge-patches.txt` (forge-game's resources), and a change to an AI switch a new id in `ai-switches.txt`. A new game patch or changed res file re-keys the matchups (engine-check says "Different engine key"); `replay` plays the current matchups again.

  **engine-check** (`python -m decklab.lib.forge engine-check --old DIR [--new DIR] [--games N] [--commander-games N] [--pair DECK DECK]... [--switch ID]... [--game-patches on|off] [--seed N] [--json FILE]`) plays the same seeded games with two installs (`--new` defaults to `config.json`'s `forge_dir`), card log on, and compares them line for line: cardlog-check's lists (25 Constructed and 3 Commander games a pair by default, at most 25) and each `--pair` (deck ids, `@owned` allowed, both of one format). `--switch` turns an AI switch on for both seats (refused with game patches off, or when either build lacks it). It prints both builds, their engine releases and game patches, each pair's identical games and first difference, and "Same engine key" or "Different engine key (what differs)"; games that differ under the same key mean "Don't install this build as it is". A Commander game that differs only in lines (same winner, starter and length) or a game that hit a time limit is "can't tell". Exit 0 all identical, 1 a difference, 2 couldn't run, 3 only "can't tell". It writes no results, and doesn't note either install as Forge's version or engine.

  **Moving to a new Forge release:** rebase the `decklab` branch onto the new release tag (or merge it in), fix any conflicts, update `BASE_TAG` in `decklab/install.py`, then steps 2 and 3 (the scratch build and `engine-check`). A new release is always a different engine key, so step 3's "Accept exit 0, or 3" doesn't hold here: `engine-check` is expected to exit 1 with "Different engine key (...)" and no "Don't install this build as it is" line (0 or 3 if no game changed). Only exit 2 (it couldn't run) or a "Don't install this build as it is" line stops the upgrade. `python -m decklab.lib.forge upgrade-check --plan forge-2.0.16` prints these steps for a tag and runs nothing (with `--dir <scratch folder>` it names that folder). Before step 4's merge and install, run **`python -m decklab.lib.forge upgrade-check --dir <scratch folder>`** (E11-S45): the same three checks below against the scratch build. Forge is set up from that folder without noting its version, `cardlog-check` notes nothing either way (the installed build's checked record never changes, and a pass there doesn't count until the check after the install), the overrides check reads that build's card scripts, and the summary names the folder and leaves the replay part out. A blank or missing folder, or `config.json`'s `forge_dir` itself, is refused. A failed `cardlog-check` or `serve-check` means don't install that build (exit 1). An override that no longer fits the new scripts doesn't stop the install (exit 0 when both game checks passed; the summary says so): `overrides make` reads only the installed build's scripts, so it's made again after the install, as below. Then step 4 (the merge and install), and after it, instead of step 5's checks one by one, run **`python -m decklab.lib.forge upgrade-check`** here (since 2026-10-21, E11-S15). It runs `cardlog-check`, `serve-check` and the card-script overrides' upstream check (`overrides check`, see "AI fixes: card-script overrides and pilots" below), in that order and each with its own defaults, going on past one that fails, and ends with one summary: each step passed, failed (with its first line or error) or was skipped (both game checks when Forge can't be started; `serve-check` when `cardlog-check` couldn't build the card log, which it needs too). When saved matchups were played with another engine than today's, it adds `replay --dry-run`'s matchups, games and rough time. It exits 0 only when all three passed, and 1 otherwise. It writes nothing they don't (`cardlog-check` notes its result, as on its own), never runs `overrides make` and never replays: when an override no longer fits the new scripts, `overrides make` makes it again (review its diff in git), then run `upgrade-check` again. Once it passes, put the new version, build and source in `simjar.CHECKED` as in step 5, make its release as in step 6, and run `replay` on an idle PC. Editing `DeckLabSim.java` (or the other Java files beside it) turns the card log off in the same way until `cardlog-check` passes with it.
- **Stopping the server** (`homenet stop` or `restart`, `--stop`, `taskkill` without `/F`, Ctrl+C, Ctrl+Break or closing its window) stops the playing matchups and saves the games they finished, then the warm workers quit. So does Windows logging off or shutting down. Every Forge process ends with the server, even if it's killed from Task Manager or with `taskkill /F`, but then those runs' games are lost.
- To clear the results, delete the files in `decklab/data/forge/results/`. Some are already there from testing on 2026-10-01, played under the Matt and User1 profiles.

### Against the field

A deck page's **Against the field** part (on its Matchups tab; since wave 3, 2026-10-03) shows how the list does against every current deck of its format, not just one opponent:

- **The headline:** its win rate against an average house deck (each opponent counts the same), its rating and rank ("3rd of 10, likely 2nd-5th"), and how much going first is worth in these games. The rating comes from a Bradley-Terry fit over every saved result of the format, so it also uses games the list never played itself.
- **Strong and weak against:** matchups that come out well above or below what the rating predicts, each linking to that matchup.
- **One row per opponent,** with its win rate, games and who's ahead, and a tick where the rating predicts it. The rows are the real answer; a rating predicts a matchup it hasn't seen only to within about ±8 points.
- **The field** is each deck of the format (a built deck's built version, otherwise its target list) and the products kept intact (their status's `intact` is `yes`). A product's or pairing's list records the product and the inventory revision it was read at as its provenance (`{"product", "revision"}`), and a deck's list its id and saved revision (`{"deck", "revision"}`; none for an unsaved draft or a preview), where both used to be a git commit. On 2026-10-04 that's 10 Constructed lists (the 9 casual decks and Lightning Aggro) and 3 Commander decks (Giada, Finneas and Gisa). The Gisa decks are listed but left out of the average and the rating, since the AI never casts Ghoulcaller Gisa. `decklab/simulation.json`'s `"field"` section can add lists the rules leave out (a product whose `intact` is still blank, say) or take some out, each as `"<deck id>"` or `"<deck id>@target"`/`"@owned"`. Home's field also follows the database's saved field choices (E3-S23, `field_policy`, migration 0017): for a current home deck with a saved choice, its simulation.json names are ignored and the choice (include a list, leave it out, or follow the rules) applies instead. Without the table or any saved choice the field is exactly as above; when the choices can't be read (any failure but the missing table, and the missing table too once the server has read them) the field view says so and shows the file's edits, but no field run or field test starts: **Play the field** is disabled with the reason, `POST /api/field/run` answers 503, `forge field` stops with the same sentence, and Who's in the field says the choices can't be read, so a saved exclusion never lapses. A home admin saves a choice on a home deck's Matchups tab, under **Who's in the field**, **Change the field**: pick a list and Include this list, Leave the deck out (with a reason, kept only in the change history) or Follow the field rules, **Preview change** (it writes nothing), then **Save change**, one audited change that's refused when the policy or that list changed since the preview (`POST /api/field/policy/preview` and `/api/field/policy`, `lib/api/field_choices.py`). Members and pages naming nobody get no controls and are refused. Until migration 0017 is applied the preview works and says so, and a save answers 503 naming `python -m decklab.db migrate`. Saving starts no games.
- **Play the field** plays 200 games against each opponent that has fewer, then spreads more games where they narrow the answer most: **Quick look** (200 a deck), **Settle it** (about 400) or **Precise** (about 800); the profile's `field_budget` keeps them as `quick`, `standard` and `thorough`. Each shows one rough time. With no games yet the part is one empty state saying why. Its games are ordinary matchup results, so they show on each matchup's page too, and games already played count. On 2026-10-03 a Standard run of Mono-White Angels against its 9 opponents played 3,600 games in about 5 minutes. A matchup that a field run is playing says so on its own page, with a link to stop it from the field part.
- From the command line: `python -m decklab.lib.forge field casual/mono-white-angels` (`--budget quick|standard|thorough`, `--owned`, `--show` to print the view and play nothing, `--dry-run` for the plan and its time).

### Testing a change to a deck

The editor's **Test this change** (since wave 3) answers "does swapping these cards make the deck better?" without saving anything:

- It appears while the list's main deck (or Commander section) differs from the saved one and has the same number of cards. A change of size, or of the sideboard only, can't be tested (games are best of one).
- It plays the changed version on the saved version's own games: the same seeds, the same seats and the same shuffles, so only the games where a changed card turned up can differ. That's far fewer games than comparing two separate results: on 2026-10-03 a 1-card change to Gruul Ramp needed 92% fewer games for the same precision against Izzet.
- **Test against** the field (the default) or one deck; **How long:** **Settle it** (until it's clear, with checks at planned points, up to 1,600 games a deck) or **Quick look** (200 a deck). The answer is "Better", "Worse", "Makes little difference" (within 2 points of win rate against the field, 3 against one deck) or "Not settled yet", with each opponent's difference and how many games played out the same.
- The test page has **Play more** and **Save this change**, which opens the editor with the tested list. The deck page's Matchups tab lists its tests under **Tests of changes**, on one scale shared by every bar, coloured by verdict.
- From the command line: `python -m decklab.lib.forge variant casual/gruul-ramp --remove "1 Fiery Annihilation" --add "1 Rabid Gnaw" --field` (or `--against <deck>`; `--list FILE` for a whole changed decklist; `--quick` or `--games N`; `--more <test id>` to play on).
- It needs Deck Lab's Forge, whose engine includes `deck-order-1` (the `Match` change in "Deck Lab's own Forge" above); with a Forge build without it, tests refuse to start.

### AI fixes: card-script overrides and pilots

Forge's computer players misplay some cards, and Deck Lab has two ways to help them (since wave 3). Both change the games, so neither is used until the owner adopts it, from an experiment's numbers.

- **Card-script overrides** are Forge's own card scripts with a small AI edit, kept in `decklab/lib/forge/overrides/<set>/` and listed in `overrides/sets.json` (each set's `status`, why, and each file's card, the SHA-256 of Forge's script it was made from, and the exact edits). Before each run Deck Lab copies the adopted sets' files into its Forge user folder (`decklab/data/forge/user`; `overrides.ensure_deployed`, on every run), which Forge loads over its own scripts. A file isn't used while the installed Forge's script differs from the one it was made from (after an upgrade, say); the Forge box on the page names it.
  - **Adopted:** `fiery` (Fiery Annihilation, 2026-10-03) and `remove` (Devout Decree and Beast Within, 2026-10-04): Forge's AI used to never cast these. **Experiments:** `etb`, `etb-flagged`, `tgt`, `tgt-gift`, `flash` and `hints`; since AI round 1, `etb-tfp` (Fires of Mount Doom, Éowyn, Fearless Knight and Samwise the Stouthearted, for The Free Peoples), `etb-tfp-jailer` (Palace Jailer) and `cmdr-hints` (Primal Might fights; Puca's Mischief was checked and left out).
  - `python -m decklab.lib.forge overrides` lists the sets; `overrides check` says whether every file is Forge's script with its edits; `overrides make [--set S]` makes the files again from the installed Forge (after an upgrade); `overrides deploy` puts the adopted sets in the user folder now and prints their hash (every run does this anyway).
- **Pilots:** each list can be played by its own AI profile (Forge's Default, Cautious, Reckless or Experimental, or Deck Lab's DLAggro, DLTempo and DLControl) with switches: `team-pump-1` (the team-pump fix: Forge's own AI judges an Overrun-style spell one creature at a time, and this judges it as a whole) and `aisim-hybrid-1` (a look-ahead AI, experimental and about 3.6 times slower). Since AI round 1 a pilot may also name the fork's AI switches (see "Deck Lab's own Forge" above): `removal-in-combat-1` (combat-removal fix), `etb-harmless-1` (optional-target fix) and `prowess-precombat-1` (prowess-first fix, experimental). They're set per list in `decklab/simulation.json` (`"pilots": {"lists": {"casual/selesnya-rabbits": {"profile": "Reckless", "switches": ["team-pump-1"]}}}`, keyed `"<deck id>"` or `"<deck id>@<version>"`). A fork switch is adopted for a list the same way, after a paired experiment: only that list's side changes, so only its matchups re-key. A run refuses a switch the installed build doesn't have, and any fork switch with game patches off. Every list plays Forge's Default with no switches today, except The Free Peoples, with `etb-harmless-1` (adopted 2026-10-21 after AI round 1's E4: [forge-trial/ai-round1-results.md](forge-trial/ai-round1-results.md)). `python -m decklab.lib.forge pilots` lists each list's pilot, what's available and which AI switches the installed build has; `pilots --check` exits 1 when the file has a bad entry.
- **Experiments:** `python -m decklab.lib.forge experiment <spec.json>` plays each arm (override sets, pilots, other seeds or config settings) on a control result's own games and seeds, and writes `experiment.json` and `report.md` in `decklab/data/forge/experiments/<name>/` with each named card's cast rate and win rates, the paired matchup difference, speed and AI timeouts, and a recommendation for each override or pilot arm: **adopt**, **don't adopt** or **more games** (`--dry-run` lists the games first). Arm results never mix with matchups. The spec's format is in `forge-trial/sim-wave3-contract.md` §12.1; the overnight run's specs (`inputs/exp-*.json` in its folder) are examples.
  - **Time guide:** `--dry-run` estimates only remaining games, with an additive `estimate` in `--json`. It labels measured control speed, prior-arm/control proxies, format fallback or mixed sources, plus configured/assumed/unknown workers. Positive sub-minute work says under 1 minute; no work says 0. Per-job times are added as a serial budget; overlapping pair jobs can reduce elapsed time. The heuristic range excludes queue wait, cold startup, deployment and changing shared load. Arbitrary configuration arms or unavailable timing leave the complete estimate unknown; row estimates are not a partial total. Optional timing failures leave the game plan usable.
  - **Local worker assumption:** with `--dry-run --local`, an arm changing only `config: {"forge_workers": N}` can use the format fallback at its positive integer requested worker count. Text and JSON keep those arm workers separate from baseline workers. This assumes requested local capacity before worker caps, available chunks, contention and shared PC load; it does not verify actual activity. Saved arm/control throughput is never reused or scaled for this configuration arm. Other configuration combinations, unknown formats or missing local intent keep the complete estimate unavailable.
  - **Dry-run safety:** experiment planning reads the expected existing engine/run-folder identity without deploying overrides, creating folders, remembering metadata or starting games. If that identity cannot be confirmed, it reports the remaining count as unknown before reading cached controls. A plan does not prove an edited arm remains compatible with its existing results folder; real-run validation remains separate.
- **Adopting a fix** (the owner's call):
  1. Set the set's `"status"` to `"adopted"` in `overrides/sets.json` (say why), or add the list's pilot to `decklab/simulation.json`, and commit. Both files are read again when they change, so nothing needs restarting, and a warm worker started with other override files never plays the new engine's games.
  2. That changes the engine of every matchup whose lists hold the set's cards (or that holds the piloted list), and those results show "Earlier engine". `python -m decklab.lib.forge replay --dry-run` lists them; `replay` plays them again, on an idle PC. Adoptions are best decided together, so one replay covers them.
  3. On 2026-10-04 adopting `remove` re-keyed 13 matchups, about 20,000 games to replay.

### The decision log

Since AI round 1 (2026-10-13) Forge can say what its AI weighed for chosen cards, to count the chances it had to cast them and why it passed. For each ability of a named card the AI weighs when it has priority, it prints `DLAI|1|<turn>|<active seat>|<phase>|<seat>|<decision>|<api>|<card>`. These lines change no game, and every reader of Forge's output passes over them.

- Turn it on for one command with a JSON file named by `DECKLAB_CONFIG_EXTRA`, such as `{"forge_decision_log": ["Pearl of Wisdom", "Preordain"]}` (`["*"]` for every card), and `--local` (the server's warm pool doesn't have the setting, and Forge reads the names once per process, so each new list needs a fresh launch). It needs the card log. Experiments tee their logs with it on.
- `python -m decklab.lib.forge decisions <logs>/<arm or control>/<matchup key> [--card NAME]... [--json]` prints, per card, the games with an opportunity, the opportunities, how many the AI took, the decisions it passed with (most common first), and both per phase and per seat.
- An opportunity is one card in one priority window with a decision other than "can't play it", "can't afford it" or "not at this speed". It doesn't mean the AI could pay: a card it can't afford usually shows its ability's own refusal. Instants are weighed in every window, so compare them per phase.
- Limits: a mirror (one list on both sides) can't be split by card name, so judge it on the matchup only; and after an AI timeout a line can land in the next game (rare).

### Replaying, and moving staged results

- `replay` (above) plays again, with today's engine, every saved matchup whose lists are still current and whose result is another engine's: after an adoption, a Forge upgrade or the card log coming back. It plays only what's missing, so it can be stopped and run again.
- **Staged results** are results played somewhere else, such as the overnight run's staging folder, to be moved into the real one only once their checks pass. `python -m decklab.lib.forge staged-move --from <folder> --dry-run` lists what would happen, and without `--dry-run` it moves them:
  - it first puts the adopted overrides in Deck Lab's user folder, then works out each file's key with today's engine;
  - it moves the folder's matchup results of today's engine and its `field/` notes, and never moves results of earlier engines, tests of a change (`paired/`) or experiment results;
  - a file whose key isn't today's (an adoption or a pilot change since it was played, say) is **stale** and stays, naming what differs; `replay` plays it later;
  - a file whose key is already in the real folder is skipped and listed; `--hold <file>` leaves the keys listed in that file behind.
  - Stop the background server while moving. On 2026-10-04 it moved the overnight run's 29 matchup results and 2 field notes; a copy of the folder from before is in `decklab/data/forge/results-backup-2026-10-04/`.

### Time estimates (`rates.json`)

The rough times on the matchup page, Play the field and Test this change come from one estimator. A pair's own saved runs give its speed when it has any; otherwise its lists' speed class does (fast, medium, board-heavy or Commander), at the rates in `decklab/data/forge/rates.json`. Since 2026-10-04 that file holds the overnight run's measured warm rates: 1,426.3 games a minute for Izzet vs Gruul (fast), 157.3 for Rabbits vs Vampires (board-heavy) and 232.6 for Giada vs Finneas (Commander). Without the file, wave 2's defaults stand. To refresh it after another measured run: `python decklab/forge-trial/overnight.py report --out <run folder> --write-rates decklab/data/forge/rates.json`. The times are a guide, not a promise.

### The overnight run (measuring on an idle PC)

Speed, and checks that need many games, are measured by one unattended run on an idle PC, overnight: `decklab/forge-trial/overnight.py`, with its runbook in [forge-trial/sim-combined-run.md](forge-trial/sim-combined-run.md) (§3 the daytime preparation, §4 the start, §10 the morning after). It ran on the night of 3-4 October 2026 to measure waves 2 and 3 before they merged; PLAN.md's wave 3 entry has what it found.

- **Where:** in a git worktree of its own at the commit under test (`C:/VSProjects/TCC-wt/w3-run` that night), with its own data folder: card data copied in, `cardlog-check`, `overrides deploy`, `overrides check` and `pilots --check` run there first. It writes everything under that worktree's `decklab/data/forge/overnight/<date>/`, copies the real results into a staging folder there, and never writes the real ones. Its test servers use 127.0.0.1 ports 8643 and 8644.
- **Steps:** `overnight.py prepare --out <folder> --main <main checkout>` resolves the plan against today's lists into `inputs/` (variants, ladders, experiment specs, estimates) for review; `plan --out <folder> --budget-h H` shows each item's estimate against the budget; `preflight` runs the start-up checks alone; `supervise --out <folder> --budget-h H --deadline HH:MM --main <main checkout>` runs it. A `--smoke` run first plays every item at a tiny size.
- **While it runs:** it waits for the PC to be idle (10 minutes without input; `--no-idle-gate` skips that wait), starts no new step while the PC is in use, and after 5 minutes of use stops the running step, to redo it later. It keeps the PC awake. It stops the background server at the start if it's running, and starts it again at the end. It only ever ends its own processes. A file named `STOP` in its folder stops it gracefully (the running step keeps its games, then it writes the report); closing its window ends it at once, and `overnight.py clean --out <folder>` then ends anything left over.
- **After it:** `overnight.py status --out <folder>`, then `REPORT.md` in the folder: the verdict (PASS, FAIL or INCOMPLETE) and every merge gate first, then the timing, the soak, the replay, the experiments and the next steps. `supervise ... --resume` carries an INCOMPLETE run on another night; `supervise ... --only <items>` re-runs some items into a new folder (the re-check of 2026-10-04 did that with the timing legs, the replay and the soak). `report --out <folder>` writes the report again.

## From outside the home

Since 2026-10-10 Deck Lab can be opened at **https://decklab.example.com** from anywhere, through a Cloudflare Tunnel, behind Cloudflare Access's login. No router port is open: `cloudflared` on this PC connects out to Cloudflare, and Cloudflare sends the visits back through that connection.

- **Who gets in:** Cloudflare Access (Zero Trust team `your-team`, application "Deck Lab", for both hostnames) lets in only the emails in its policy, with a one-time code by email; a login lasts a month. Change who gets in in the Zero Trust dashboard (Access controls, Applications, Deck Lab), not here. Deck Lab has no passwords of its own, so never remove that application while the tunnel runs.
- **Two listeners:** the home network uses port 8642 as before (no login; the page asks **Who are you?**, offering only Matt and User1). User2, User3, User4 and every other member sign in here, from the home Wi-Fi too: the home listener answers a request naming them 403 "Sign in through decklab.example.com" (E10-S35). The tunnel has a listener of its own on `127.0.0.1:8644` (`"access"` in `config.json`: the team, the application's AUD tag and the port), which only this PC can reach. Every request there, pages and pictures included, must carry Cloudflare Access's signed login (the `Cf-Access-Jwt-Assertion` header or the `CF_Authorization` cookie). Deck Lab checks it itself (`lib/access.py`: the signature against the team's published keys, the AUD tag, the team, and the expiry, with a minute's leeway) and looks its email up in the profiles' `"emails"` in `config.json`. A missing or bad login gets 403; an email no profile has gets 403 "This email isn't set up in Deck Lab", so adding someone means both the Access policy and their profile's `"emails"`. A visit through the tunnel is always its login's profile: whatever profile a request names is replaced by it, and another profile's settings and wishlist can't be changed. `GET /api/me` says who is asking and what they may change (`{"profile", "name", "remote", "may"}`; at home for the profile the viewer header names, else no profile and a request naming nobody's `"may"`: everything for a script, nothing otherwise). Only the home listener makes a script (loopback, `X-Deck-Lab-Script: 1`, no viewer): the tunnel's listener is on `127.0.0.1` too, but the header gets nothing there. Every write route checks that profile's role (see "People's own collections").
- **Fails closed:** the home listener refuses (421) any request carrying Cloudflare's headers or naming decklab.example.com, so a tunnel still pointed at port 8642 can't hand out the home network's no-login editing. The server doesn't start `cloudflared` at all while its `config.yml` sends either hostname anywhere but `http://127.0.0.1:8644` (the log says `Tunnel: NOT STARTED` and why), or while the tunnel's listener isn't up.
- **A second lock:** the tunnel's config also requires a valid Access login for that application (`originRequest.access`, with the team name and the application's AUD tag), so `cloudflared` refuses a visit that somehow skipped the login.
- **Starts and stops with Deck Lab:** the server starts `cloudflared` when `"tunnel"` in `config.json` names its config file and the server is on its usual port (`lib/tunnel.py`). It runs with no window in the server's Job Object, so it ends with the server (`stop`, `restart`, logging off, a crash). Its lines go to the server's log, starting `Tunnel:`. If it exits by itself, the server starts it again after 30 seconds. While Deck Lab (or this PC) is off, a signed-in visitor gets the **off page** below (deployed 2026-10-17); if it's rolled back, decklab.example.com shows a Cloudflare error (1033 or 502) after the login.
- **`status`** has Tunnel lines: OK when https://decklab.example.com answers with Access's login; PROBLEM if Deck Lab answers there with no login (stop Deck Lab at once and check the Access application); WARN when the tunnel isn't connected. Then whether `config.yml` sends the hostnames to `http://127.0.0.1:8644` (PROBLEM if not, or if `"access"` is missing), and whether the tunnel's listener refuses a visit without a login (OK), answers one (PROBLEM: something else has the port) or isn't listening (WARN).
- **Files outside the repo**, in `C:\Users\player\.cloudflared\`: `cert.pem` (this PC's login to the Cloudflare account, for managing tunnels), `<tunnel id>.json` (the `decklab` tunnel's credentials; keep both secret) and `config.yml` (the tunnel, its two hostnames, both to `http://127.0.0.1:8644`, the tunnel's listener, and the second lock). `cloudflared` was installed with `winget install Cloudflare.cloudflared` and runs with `--no-autoupdate`, so update it now and then with `winget upgrade Cloudflare.cloudflared` (then restart Deck Lab).
- **The off page** (story E11-S02; `decklab/cloudflare/`): a small Cloudflare Worker, `decklab-off-page`, on the routes `decklab.example.com/*` and `www.decklab.example.com/*`. Access stays in front: it runs before the Worker, so a visitor who isn't signed in still gets Access's login, and the Worker never answers a request without Access's login (header or cookie) itself. It passes every request to the PC unchanged (headers, the login and the body, redirects not followed) and returns Deck Lab's answer as it is. Only when the answer is Cloudflare's own error (502, 503, 504, 520-523 or 530 *without* the `X-Deck-Lab-Origin: 1` header Deck Lab puts on every answer it sends, `server_http.ORIGIN_HEADER`), or the PC can't be reached at all, does it answer 503 itself, never cached: under `/api/` with `{"error": ..., "reason": "off"}` (the page then shows **Deck Lab is off** and tries again every 15 seconds), for a page load with a plain "Deck Lab is off" page that names nobody, checks `/api/status` every 30 seconds while it's on screen and opens Deck Lab by itself when it answers (or has a **Try again** button), and otherwise with a short text. Deck Lab's own 502s and 503s (the database down, the card data loading) and a 524 (Deck Lab slow, not off) always pass through. `https://decklab.example.com/__decklab-off` (behind Access) shows the off page without asking the PC.
  - **Files:** `worker.mjs` (the Worker, no dependencies), `off-page.mjs` (the page), `test/worker.test.mjs`, and `wrangler.toml` (the routes; no `workers.dev` or preview address, no logs, no telemetry). Its tests: `node --test "decklab/cloudflare/**/*.test.mjs"` from the repo root (also run by `decklab/tests/test_cloudflare_worker.py`, skipped without Node). `cd decklab/cloudflare` then `npx wrangler@4.151.1 deploy --dry-run --outdir <scratchpad folder>` builds the bundle without deploying (`.wrangler/` and `dist/` are gitignored).
  - **Deploying** (done 2026-10-17 through Cloudflare's API instead of wrangler: the committed `worker.mjs` and `off-page.mjs`, `main_module` `worker.mjs`, the compatibility date and no logs as in `wrangler.toml`, workers.dev and preview addresses turned off, and both routes with `request_limit_fail_open`; redeploy after a change as below, since wrangler uploads the same; the zone is on the Free plan, which has room: 100,000 requests a day): first make sure the running server sends the header (`curl -sI http://127.0.0.1:8642/api/status` shows `X-Deck-Lab-Origin: 1`, with `/api/status`'s `build.*_dirty` false), since without it the Worker would hide Deck Lab's own 502s and 503s. Then `npx wrangler@4.151.1 login` (a browser login, kept outside the repo; it isn't `cloudflared`'s `cert.pem`) and `npx wrangler@4.151.1 whoami`; from `decklab/cloudflare`, `npx wrangler@4.151.1 deploy`. In the dashboard (the zone, Workers Routes) check that both routes name `decklab-off-page` and set the request-limit failure mode to **Fail open**. Check: a private window still gets Access's login (and `status` still shows its Tunnel OK line); a signed-in phone browses, saves a deck edit and uploads an accessory photo (so the login still passes the second lock); `/__decklab-off` shows the page. `npx wrangler@4.151.1 logout` afterwards if wanted.
  - **Rolling back:** delete the two routes in the dashboard (the zone, Workers Routes), which takes effect at once, or `npx wrangler@4.151.1 delete decklab-off-page` from `decklab/cloudflare`. Visits then go straight to the tunnel again; the server's header is harmless and can stay.
- **To turn it off:** remove `"tunnel"` from `config.json` and restart Deck Lab. `allowed_hosts` lists the two hostnames; with `"access"` set they belong to the tunnel's listener only.
- **Moving to another PC:** install `cloudflared` and copy the `.cloudflared` folder (fixing the credentials path in `config.yml`), or make a new tunnel with `cloudflared tunnel login`, `tunnel create` and `tunnel route dns --overwrite-dns <name> decklab.example.com` (and `www.decklab.example.com`).

## Network setup (once, as administrator)

Phones can't reach the server until Windows lets them in, and changing that needs administrator, so it's a script to run once. Run `python -m decklab.lib.homenet install` first (see "Start it"): the script reads from the "Deck Lab" task which `pythonw.exe` runs Deck Lab. Then open PowerShell **as administrator** (right-click PowerShell in the Start menu, then **Run as administrator**), go to the repo folder and run the script:

```
cd C:\VSProjects\TradingCardCollection
powershell -NoProfile -ExecutionPolicy Bypass -File decklab\network-setup.ps1 -PythonPrivateOnly
```

Only run it at home: it tells Windows to trust the network the PC is on. It prints what it finds and each change it makes, and changes nothing else:

1. **The network:** the home network is the one on the PC's cable or Wi-Fi adapter with the internet route. A VPN or virtual adapter is left alone. If Windows treats the home network as Public, the script names it and asks "Is '<name>' your home network? Type y to set it to Private". Any other answer leaves it Public. Windows blocks phones on Public networks. (It was already Private on 2026-10-01.)
2. **Deck Lab's firewall rules:** it makes sure there are two inbound rules, both for Private networks and for devices on the home network only (`LocalSubnet`):
   - "Deck Lab (TCP 8642)" lets in the page's port (the `"port"` in `config.json`, else 8642);
   - "Deck Lab (pythonw)" lets in the `pythonw.exe` that runs the background server, so Windows doesn't ask about it.

   It adds a missing rule before it removes anything. Then it removes the other allow rules it would have made: ones with those two names, or with its own description ("Added by decklab\network-setup.ps1"). Any other rule whose name starts with "Deck Lab (" is listed and left alone. On 2026-10-01 there were two "Deck Lab (TCP 8642)" rules: the right one, and one open on every kind of network to any address. The script keeps the right one and removes the other.
3. **Block rules for Python:** it removes the block rules Windows' "allow this app" prompt made for that Python's `python.exe` and `pythonw.exe` (block rules beat allow rules). A block rule the prompt didn't make is listed, not removed.
4. **Python's own allow rules:** it lists the ones that also apply to Public networks. On 2026-10-01 `python.exe` and `pythonw.exe` each had two from Windows' prompt (TCP and UDP, every port, on Private and Public networks). They don't stop Deck Lab working, but they let any Python program take connections on Public networks such as cafe or hotel Wi-Fi. `-PythonPrivateOnly` takes Public networks off them and leaves the rest of each rule as it was. A rule that was for Public networks only is turned off.

On 2026-10-01 a dry run of the command above showed 6 changes: add "Deck Lab (pythonw)", remove the wide "Deck Lab (TCP 8642)" rule, and take Public networks off the four Python rules.

- `-DryRun` only shows what it would do, and needs no administrator.
- `-Pythonw <path>` names the `pythonw.exe` when the "Deck Lab" task isn't set up (`status` names the one `install` would use). Without the task or this option, the script skips the "Deck Lab (pythonw)" rule and steps 3 and 4, and says so. It never runs Python to find out, since it runs as administrator.
- `-Yes` sets a Public home network to Private without asking, for a PowerShell that can't ask. Only use it at home.
- Without administrator it changes nothing, and prints the command to run as administrator, with the options you gave.
- It's safe to run again: a second run finds everything right and changes nothing. After upgrading Python, run `homenet install` and then this script again, since the "Deck Lab (pythonw)" rule names that program's exact path.
- Afterwards, check from an ordinary window with `python -m decklab.lib.homenet status`. Its firewall warnings should be gone.

**Never forward port 8642 (or 8644) on the router or open it to the internet.** Port 8642 has no login: anyone who can reach the page can use it, and it saves decks and the inventory. Outside visits go only through the Cloudflare tunnel (see "From outside the home").

## When a phone can't reach it

First check that the phone is on the home Wi-Fi, not mobile data. Then, on the PC, run:

```
python -m decklab.lib.homenet status
```

It checks seven things in about 2 seconds: Server, Start at logon, Restart after a crash, Network, Firewall, Addresses and Sleep. Each line is **OK**, **WARN** (worth fixing, but phones can usually still get in) or **PROBLEM** (phones can't get in until it's fixed), with the fix underneath. It changes nothing and needs no administrator, and it exits with code 1 when anything is a PROBLEM.

What each PROBLEM means:

- **Server:**
  - *Deck Lab isn't running (nothing is listening there):* run `python -m decklab.lib.homenet start` (`install` first, if it isn't set up). If it won't start, its log says why.
  - *A server is recorded but doesn't answer:* it's stuck or still starting. Run `restart`, and read the log if it still doesn't answer.
  - *Something has the port open but doesn't answer:* a Deck Lab server that's stuck, or another program. If it's Deck Lab in a window, press Ctrl+C there. Otherwise end the program in Task Manager (Resource Monitor > Network > Listening Ports shows which one it is), then `start`.
  - *Another program answers on the port:* close it, or change `"port"` in `config.json` (then run the network setup again, since its rule names the port).
  - *It listens on 127.0.0.1 only:* only this PC can open the page. Take `"host"` out of `config.json` (or, if the task was installed with `--host`, run `install` again without it), then `restart`.
- **Start at logon:** the task starts a `pythonw.exe` or `server.py` that isn't there any more (after a Python upgrade, or after moving the repo): run `install` again. A task that isn't set up is only a WARN, though `start` can't start Deck Lab without it. So is a task whose settings were changed in Task Scheduler (how it logs on, running with highest privileges, its priority, or what a second start does): run `install` again to put them back. "Off" on this line is fine: it means Deck Lab starts only with `start`, which is the default.
- **Restart after a crash:** the watchdog gave up after 3 restarts in a row that didn't stay up. Read `decklab/data/logs/watchdog.log` and the server's log, fix the cause, then `start`.
- **Network:** Windows treats the network as Public, which blocks phones: run the network setup, at home (it asks before changing it). No connection, or no address: check the cable and the router. The home network is the cable or Wi-Fi connection with the internet route, never a VPN.
- **Firewall:**
  - *No firewall rule lets phones reach TCP 8642 on Private networks:* run the network setup.
  - *A block rule for Python or the port applies to Private networks:* run the network setup, which removes the ones Windows' prompt made. Any other one has to be deleted by hand in "Windows Defender Firewall with Advanced Security" > Inbound Rules.
  - *"Block all incoming connections" is on for Private networks:* turn it off in Windows Security > Firewall & network protection > Private network.

WARN lines to know about:

- Deck Lab's code changed after the server started: run `restart`.
- Restart after a crash: Deck Lab starts at logon but has no watchdog (a task set up before 2026-10-20), or a watchdog task whose settings don't match what `install` sets: run `python -m decklab.lib.homenet install --at-logon --no-start`. The watchdog restarted Deck Lab in the last 24 hours: its server log around that time may say why it stopped.
- A rule lets the port in on Private networks, but only from some addresses or kinds of connection, so it may not let phones in. The network setup adds Deck Lab's own rules, for the whole home network.
- Firewall rules wider than Deck Lab needs. Python's rules that apply to Public networks: run the network setup with `-PythonPrivateOnly`. Deck Lab's own rules: run the network setup, which replaces them. Any other rule has to be checked by hand, since the network setup doesn't touch rules it didn't make.
- `pythonw.exe` has no firewall rule of its own, and no other rule lets the port in on Private networks either, so Windows may ask about it (see below).
- The PC not answering to `homepc.local`, and the PC going to sleep on mains power (the page stops while it sleeps; it was set to never on 2026-10-01).

On 2026-10-01, with the final Milestone 6 code, `status` showed 0 problems and 5 warnings: the wide "Deck Lab (TCP 8642)" rule, and `python.exe` and `pythonw.exe` (TCP and UDP) open on Public networks. The network setup with `-PythonPrivateOnly` clears all five. After it was run as administrator that day, `status` showed 0 problems and 0 warnings, and a phone on the home Wi-Fi opened the page.

These checks run on the PC itself, so they can't prove a phone gets through. The real test is opening the address on a phone on the home Wi-Fi.

**The firewall prompt for Python.** If Windows asks whether to let Python (`python.exe` or `pythonw.exe`) through the firewall, allow it on **private networks only**. Never press Cancel: that adds a rule that blocks Python, and block rules beat the allow rules above. If it happens, the network setup removes those block rules. On 2026-10-01, with the "Deck Lab (TCP 8642)" rule in place, the background server made Windows ask nothing. A test server listening on every network interface, on a port no rule covered, did make it ask, and that left `pythonw.exe` allowed on Public networks too, which `-PythonPrivateOnly` fixes. That's why test servers use `--host 127.0.0.1`.

## Updating inventory and saved availability

The inventory (collections, token cards, orders, products, the watchlist) is in the database, so it
changes only through Deck Lab's pages or `python -m decklab.db` on the PC (AGENTS.md, "The
inventory", has every command and its rules). Each write is one change set, by Claude by default from the
command line, with a required `-m` message (and `--reason` for a removal or cancellation):

```
python -m decklab.db order add ... --fulfils ... -m "Record the order"     # an order, its product, the queue rows it fulfils
python -m decklab.db order edit|checks|split ...                            # fix a pending order
python -m decklab.db order cancel ID C [--restore-queue] -m "..." --reason "..."
python -m decklab.db order remove ID -m "..." --reason "..."                # mistaken, never received; restores known queue intent
python -m decklab.db order record ID --seller "Shop" -m "Correct seller"   # metadata only; --dry-run previews
python -m decklab.db order extra-copies ID C [--undo] -m "..."              # C is more copies of owned printings
python -m decklab.db product add|edit|set-intact|kit|set-kit ...            # record, storage and kit
python -m decklab.db watchlist list|set|remove|apply ...                    # the purchase queue
python -m decklab.db receive --order <id> [--component C]... [--verified C]... [--intact yes|no] [--date D] [--apply [--expect TOKEN]]
python -m decklab.db collection list|merge|edit ...                         # a space's collection; cards from no recorded order; one row
python -m decklab.db tokens list|check|add|edit|remove ...                  # a space's token cards
```

A recorded receipt (here or on the Receive delivery page) also keeps an
**arrival notice** for each home player whose decks it brought missing cards
for (Played by `either`: both), in that profile's own settings; `receive
--apply` says who will see one. The player sees it above the page on their next
visit, each deck with its count, until they dismiss it (GET /api/arrivals, POST
/api/arrivals/dismiss; E6-S19). A notice that can't be kept never fails the receipt.

`order record` changes only supplied `--seller`, `--ordered-on`, `--notes` and
`--source` fields. Repeat `--source` to replace the whole source list, or use
`--clear-sources` to clear it; an empty string clears a text field. It keeps the
order id, components, card rows and audit notes, works at any receipt status and
does not need card data or refresh deck tables. A corrected order date cannot be
later than an existing receipt. Like other writes it requires `-m` and accepts
`--actor` (omit it for an assistant's change) and `--dry-run`.

`product edit STEM` corrects only supplied `--name`, `--format`, `--status`
(`ordered` or `preordered`) and `--notes`; `--csv FILE` replaces its complete
published card list, including basic lands and optional section/deck columns.
An empty name or format clears its display override. Its stem and order
component, arrival checks and additional-copy acknowledgement stay fixed.
Owned, received or cancelled products are refused. Use `--dry-run` to preview
the result and affected deck tables. On Shopping, **Edit order… > Correct
product…** offers the same correction and shows the full resulting list before
**Save change**. Shopping also splits pending cards or tokens through **Split shipment…**.
`order cancel ID C` now accepts a pending cards, tokens or product component.
Add `--restore-queue` to return its recorded fulfilled quantities; cancellation
keeps the command-line default of no restoration. `order remove ID` removes an
unreceived mistaken order and always restores its known fulfilled quantities.
Both require `-m` and a one-line `--reason`, and accept `--dry-run` and `--actor`.
Any received component refuses removal. A cancelled product retains its list and
history with status `cancelled`, excluded from incoming supply and the library.

New orders record price-free queue intent and physical allocations in a reserved
`audit_notes` ledger, separate from displayed delivery notes. Splits conserve
those allocations. A product-list correction retains the original fulfilled intent
and quantity even when its list shrinks, with a warning. Token-name corrections
preserve the original intent and remap it to remaining physical capacity, with a
warning; later splits conserve it. Card corrections keep each name's total. A
cancellation therefore offers the original recorded purchase request, which may
differ from the corrected contents; it never invents replacement intent. An offer
consumed by cancellation cannot be restored again by removing the order later. Returning copies adds to a matching
current queue row without replacing its metadata. Newly recreated rows have blank
market-reference fields; a missing original source is cleared with a warning.
Historical orders without provenance warn for manual review and never infer queue
rows from their contents. Shopping previews the same operations through opaque
preview/apply tokens bound to both inventory and deck revisions.

Every write that changes what decks count as on the way or in use (order add, edit, split,
cancel, remove and extra-copies, product add, edit and set-intact, a receipt) refreshes the saved deck tables in the same change
(`lib/inventory/refresh.py`'s `in_op`: the operation's kind is registered with `refresh=True`), so
the inventory change and the decks it makes stale are saved together, and a preview or `--dry-run`
lists the decks it would rewrite. A `--dry-run` (under "It would change:") and the `receive`
preview also list what the change touches, in the same plain words as the Receive delivery page ("Home's
collection", "Order 2026-10-12-mtgmate", "Deck Izzet Otters (casual/izzet-otters)" and so on),
not the old files' paths. Only the decks of the spaces the change touches are refreshed: a
home receipt or order never rewrites a person's deck. A deck the operation changed itself, or one
whose Sleeves or Deck box would change, is skipped (`tables.skipped`, with why). Before saving, the
order and product commands (and their `--dry-run`) plan that refresh on the result and refuse a
change after which the tables couldn't be refreshed, such as a product kept intact with no deck
lists or a pending payload whose every card is already in the collection (`--force` saves it
anyway, with the refresh skipped, and says so; for a real order for more copies of printings
already owned, mark it instead, below); a change made while the tables already can't be
refreshed is allowed, since it may be the fix. A refresh that still fails when the change is saved
leaves the decks as they were and the change saved. Previews say when it would fail. Exit codes: 0
done, 1 refused, 2 the database can't be reached, 3 saved but the deck tables couldn't be
refreshed (stderr says why).

**Extra copies of owned printings.** When every printing a pending cards payload or incoming
product lists is already in the collection, the pool (`lib/pool.py`) warns that it may have been
merged without a receipt (its cards would count twice), and like every pool warning that stops
every deck-table refresh and receipt. A real order for a second copy of an owned printing looks
the same, so `order extra-copies ID COMPONENT -m "..."` marks a pending cards or product component
as extra copies (`--undo` takes it off; `order add --extra-copies COMPONENT` marks one as the order
is recorded, instead of `--force`). The mark is one sentence in the order record's `audit_notes`,
`Extra copies of owned printings: cards, other.` (component ids), written and read only by
`lib/inventory/rules.py`'s `with_extra_copies` and `extra_copies` (one strict pattern; the rest of
`audit_notes` is left as it is), so it needed no database migration. The pool doesn't warn about a
marked component whatever the collection holds: the collection keeps no per-copy history from
which it could tell copies merged early from copies owned before, so the mark is the person's
word, kept in the audit trail. It's refused for a received, cancelled or tokens component, and a
receipt or cancellation leaves it in the record, where nothing reads it any more (the guard reads
only pending components). A part split off a marked component is marked too, in the same change,
and the split's preview says so; unmarking either part leaves the other's mark as it is.

`collection merge`, `collection add-precon` and the Collection page don't refresh the tables, and token cards never change
one. `collection merge` and `collection add-precon` then print the space's decks whose tables are now out of date, and `deck
push` and `deck new` print the other decks of the deck's space that are (besides its own table),
each followed by the `deck tables --apply` command, or, when that would refuse, every problem in its
way (`pool.table_blockers()`: an unknown card, a deck with no table or decklist, an incomplete pool).
These notes never change the exit code. On the page, the Decks page's Tables out of date list does
the same with **Update all**. After them, or after a deck's status or Built version changes, refresh
and check:

```
python -m decklab.db deck tables                  # lists the decks whose tables would change
python -m decklab.db deck tables --apply -m "Refresh the tables after the trade"
python -m decklab.db deck tables --check          # exit 1 when a table is out of date
python -m decklab.lib.purchases --check
```

This updates the target lists' owned-vs-needed tables and explains the arrival dependency under each
substitute list. Pick the Play-now list on the deck page for its live availability counts. Incoming cards
count toward purchase planning but cannot be assembled into a deck
until they arrive. Existing `Owned-only version` headings remain readable; refreshed and newly
created lists use `Substitute version (owned and incoming cards)`.

The command uses the local card index and never fetches prices unless `--reprice` (today's prices
and exchange rate, as Deck Lab's **Update the table** and **Update their tables**). Dated estimates remain only where
their quantities still apply; changed quantities clear the old estimates. It preserves both
decklists and hand-written notes, and saves every changed table in one change (all of them, or
none when a deck was saved meanwhile). It refuses while any space's pool is incomplete (an unknown
card or a pool warning), listing every problem, and an inventory change's refresh fails the same way for the spaces it
touches: every deck needs an owned-vs-needed table and only Scryfall card names. `purchases --check` checks the order records, receipt states and queue
fields, and exits 2 when the database can't be used or holds no imported inventory.

**Receiving a delivery from the command line** uses the same inventory operation as the Receive delivery page; partial CLI arrivals still use the explicit split below. Preview first (it
writes nothing), including the same selected components, checks, received rows and actual arrival
date that will be applied. Applying requires `--date` and `--apply`. A valid preview prints
`Preview token: TOKEN`; repeat its options with `--apply --expect TOKEN` to bind the apply to that preview:

```
python -m decklab.db receive --order <order-id> --component cards --verified cards --date YYYY-MM-DD
python -m decklab.db receive --order <order-id> --component cards --verified cards --date YYYY-MM-DD --apply --expect TOKEN
```

Use repeated `--component <component-id>` to receive just the components that arrived. Omit the
selection only when receiving all pending components together. If only some copies within one
component arrived, first split it (`order split ID C --new-id NEW --take ROW[:QTY]`) into
separately identified pending components, preserving the total quantities. Repeated `--verified
<component-id>` acknowledges physical checks once the rows match the received cards: correct them
first with `order edit ID C --csv FILE` (from `order show ID --csv C`), or give them at the receipt
with `--rows C=FILE`. Checks on a pending component can't be resolved before it arrives; `order
checks --withdraw N` drops one added by mistake. Unknown condition and language stay blank unless
confirmed; the receipt does not invent NM or English.

Token receipts always require `--verified` for their component, with physical front/back pairings
recorded. Resolve notes saying a reverse is unconfirmed before receipt; an inspected single-sided
token needs `single-sided verified` in notes when its back field is blank. A product receipt also
requires `--intact yes` or `--intact no`, according to how it will be kept. Product follow-up checks
remain open after its playable cards arrive and do not require `--verified`. Record the actual
physical product tokens separately (`tokens add`) before resolving their inspection checks (`order
checks ID C --resolve N`, or an admin's **Done** under Shopping's Follow-ups); do not add unverified tokens to owned inventory. Cards/tokens checks
completed by a verified receipt move to the order record's `verified_checks`.

Applying validates before writing, adds the owned quantities, marks the components received,
updates the product's status where applicable, refreshes the deck tables, and saves all of it as
one change set. It refuses a second receipt of the same component, and, on the
Receive delivery page, an apply whose inventory changed since its preview. On the command line a valid
preview prints `Preview token: TOKEN`. Pass `--apply --expect TOKEN` with the same receipt options
to require that preview's inventory and intent (order, components, received rows, date and checks).
A changed inventory or receipt option refuses the receipt and asks for another preview, with no write.
Without `--expect`, `--apply` re-checks its blockers against the inventory at that moment as before.
The default audit message names the order and selected components. A receipt that
fails part way is never half-saved, so there's nothing to recover (phase 5 deleted the files
era's `receive --recover`).

## Command-line write previews

Add `--dry-run` to `collection merge`, `tokens add|edit|remove` or `deck push`
to run the normal validation and preview the change without writing. Merge shows
added quantities, skipped basics and retained imports; tokens show before/after;
deck push shows a text diff and its existing checks. Messages, removal reasons
and expected revision/list hashes remain required as for apply. Receipts preview
by default and optionally bind apply with `--expect TOKEN`.

## Member export and departure

`python -m decklab.db space export SPACE DIR` writes a member's collection, tokens,
raw imports and current/retired deck texts, plus `manifest.json`, into a fresh
scratch folder outside this repository. It refuses home and existing destinations.
The v2 manifest verifies artifact integrity, the scoped database and own-only
Forge hashes; raw Forge JSON and other spaces' private contents never enter the
export. Mixed/unknown results and lists another space still uses are preserved.

`space remove SPACE --export DIR --expect SHA -m "..." --reason "..." --dry-run`
prints the exact proposed row/file actions and config/Access reminders without
writing. Without `--dry-run`, the command requires that same complete export and
fresh snapshot, then saves one audited database change. Another space's game side
survives, with the removed side reading "a removed deck"; its own side remains
editable. A removed recorder's notes are cleared and its result becomes read-only.

Apply needs migration `0013_space_departure.sql`, a clean current server that
advertises the lifecycle protocol (or no listener), and no unaccounted Python
process. It refuses an old server or other Python jobs instead of stopping them.
Forge writers hold shared lifecycle claims; removal takes the exclusive claim
before database locks and rechecks all hashes. The minimal departure marker
prevents stale config, queued saves or buffered visits from recreating member
data. Profile sync refuses a still-configured departed id.

Own-only Forge files enter same-volume quarantine under a durable journal before
SQL changes. `space recover UUID` checks the exact audit outcome: an uncommitted
operation restores its files; a committed one finishes cleanup. Unknown outcomes
preserve the journal and quarantine and refuse further Forge writes. Recovery
never overwrites a different file. These are application/process-crash guarantees,
not a hardware or power-loss transaction across the database and filesystem.

After a committed removal, take the member's exact email out of Cloudflare Access
and their profile out of `decklab/config.json`, then sync profiles, as the command
reminds you. Export and removal are deliberate maintenance commands; no real
member was exported or removed while developing this feature.

## Database

Migration `0012_visibility.sql` adds opt-in Public switches and seeds no rows, so
everything stays Private. **Who sees what** in the avatar menu offers only the
viewer's own collection, decks, games and kit controls. Public is read-only to
everyone signed in, members included, never an internet-public page; unnamed
trusted home readers can read Public data too. The deck control explains that the
write-up and Play-now list can hint at owned or ordered cards.

`python -m decklab.db visibility list` reports every switch. The documented
`visibility set OWNER THING on|off -m "..."` changes only home's collection,
decks/games or its kit owners (matt/user1/shared) as Claude/cli; members flip their
own switches on the page. Flip messages are fixed and the supplied rationale is
retained in the audit reason. Missing migration reads fail closed without
interrupting unrelated state operations. Switches are audited, exported, checked
and included in restore digests; profile sync removes dropped-space switches.

This coding update did not apply the live migration, restart the service or flip
any live switch. After authorized activation everything remains Private until an
owner chooses otherwise.

Migration `0013_space_departure.sql` adds minimal departure markers with their
removal operation and audit identity. Normal writers and profile sync consult
them; nightly exports, content digests and the member-departures check retain
them. It starts empty and was not applied to the live database in this run.

Deck Lab's data moved from the repo's CSV, JSON and Markdown files to a **PostgreSQL** database on this PC (the plan and its five phases are in [PLAN.md](PLAN.md), "Moving storage to a database"). **Phases 1 to 4 are built** (2026-10-11 and 2026-10-12), and so are **phase 5a** (2026-10-12: the files era's dead code deleted, messages that name decks by id, and a nightly check of the data; see "The nightly check" under Backups) and **phase 5b** (2026-10-14: the rollback to the files retired; see "No going back to the files" below). The week of side-by-side checks (2026-10-13 to 2026-10-19, the check and a restore check every night) ended clean; its report is [magic/reports/2026-10-19-database-check-week.md](../magic/reports/2026-10-19-database-check-week.md). The database holds the spaces, profiles and their emails (copied from `config.json`), the audit tables, a log of backup runs, since migration 0008 the visits (`ops.visit_day`, `ops.visit_page`: see "Visits" below), since phase 2 (migration `0003_personal_state.sql`) the wishlists (`wishlist_entry`), each profile's settings (`profile_setting`), the simulations mode (`simulation_mode`, one row) and the played games and sideboard plans (`play_record`, one table for both kinds, each record's own fields as jsonb), and since phase 3 the inventory: every space's collection, token cards and raw imports, the orders, the products and the watchlist (see "The inventory in the database" below), and since phase 4 every space's decks with their history and the accessories with their pictures (see "Decks and accessories in the database"). `decklab/simulation.json` (pilots and field edits) and the Forge worker limit stay files.

- **The state store** (`lib/state/`) is the one way the server reaches phase 2's four kinds of data (the inventory has its own, `lib/inventory/`, below): `state.store()` is a `PgStore` (one connection per call, as `decklab_app`) in the server, and an in-memory `MemoryStore` with the same rules in the tests. Every write is one change set naming who made it (a profile id, `home` for "someone at home", `claude` or `system`), from where (`home` or `tunnel`) and how (`web`, `cli`, `migration`), with a message.
- **When the database is down,** a request waits at most 2 seconds to connect (`localhost` is tried as 127.0.0.1 only, so it really is 2), and statements give up on a lock after 2 seconds and after 5 in all. After a failure a circuit breaker answers "not reachable" at once for 30 seconds (or until the once-a-minute check finds the database again), so pages don't each wait. Reads and writes of wishlists, settings and play records then answer 503 with `"reason": "database"` ("Deck Lab's database isn't reachable right now. Try again in a minute."), which the page shows as an error with **Try again**, never as the card-data wait. The matchup and field pages and the simulations mode go on with the last values read, else the defaults. Settings and the mode are cached in the server for a minute, so a change made by another process (a test server, a command line) shows within a minute.

- **The server:** PostgreSQL 18, the Windows service `postgresql-x64-18`, which starts automatically and listens only on `localhost`, port 5432. Its programs (`psql.exe`, `pg_dump.exe`, `pg_restore.exe`) are in `C:\Program Files\PostgreSQL\18\bin`. Without `pg_bin` in `config.json`, Deck Lab looks there, then in the newest other version under `Program Files\PostgreSQL`, then on the PATH (where Linux and macOS installs put them).
- **The database** is `decklab`, owned by the role `decklab_owner`. Deck Lab reaches it as `decklab_app`, and the `sql` command as `decklab_ro`, which can only read. Tables are in three schemas: `public` (Deck Lab's own), `audit` and `ops`.
- **Passwords** are only in `%APPDATA%\postgresql\pgpass.conf`, which PostgreSQL's client library reads by itself. Never print, copy or commit them, or put one on a command line. (`~/.pgpass` off Windows.) `setup` writes the three roles' passwords there. The `postgres` superuser's is there on this PC; when it isn't (a new install), `setup` asks for it at a prompt and uses it for that run only, never saving it.
- **Every write says who and why.** A trigger on each table refuses a write that isn't inside a change set (`decklab.db.conn.change()`), which records who made it (a profile id, `system` or `claude`), from where, a message and an optional reason, plus each row before and after. So even a plain `psql` write has to name itself. The audit function runs with a fixed `search_path`, the app role can't backdate a change set or create temporary objects, and `TRUNCATE` on these tables is refused (migration `0002_audit_hardening.sql`): delete rows inside a change set instead.

### Naming the command-line actor

When you make a data change yourself, add `--actor matt` to the write command, for example:

```
python -m decklab.db watchlist set "Card name" --state ready --actor matt -m "Ready to buy"
```

Activity records Matt as the actor, **from the command line**. Omit `--actor`
for assistant changes, which stay attributed to Claude. The value must be a profile
id in `config.json`; an unknown, blank or reserved id is refused before files or data
are read. This is attribution for local PC commands; it doesn't limit their access.

The option follows the write subcommand: collection merge/add-precon; tokens add/edit/remove;
order add/edit/checks/split/cancel/remove/extra-copies; product add/edit/set-intact/set-kit; watchlist
set/remove/apply; receive; deck push/new/delete/tables; accessories add/edit/remove;
image put/remove; and wishlist add/set/remove. Previews and dry runs accept it too
and save nothing. Setup, migrations and scheduled maintenance keep their system actors.

### The inventory in the database

Since phase 3 (migration `0004_inventory.sql`) the database holds the inventory: `collection_card`
(one row per space and identity key), `collection_import` with its text in
`collection_import_content` (each space's raw imports; the text isn't audited), `token_card`,
`product`, `product_item` (each product's card list, its own columns kept), `product_status`,
`purchase_order`, `order_component`, `order_card_item`, `order_token_item`, `watchlist_item` and
`inventory_revision`, one counter that every inventory write bumps. Blank text is stored as `""`, so
everything comes back as it was written. Migration `0005_gate_runs.sql` let `ops.backup_run`
record the cutover gates' runs (phase 5b retired the gates; their rows stay).

- **One snapshot** (`lib/inventory/`): every reader (the pool, Shopping, the Collection, Tokens,
  Receive delivery and Sleeves & boxes pages, the library and deck pages, the Forge field and lists, the command
  lines) works from an immutable in-memory snapshot of the whole inventory (about 700 collection
  rows, 600 product rows, 30 orders and 65 queue rows), and since phase 4 the decks and accessories. One is pinned per HTTP request and per
  command, so a page's reads all see one revision. The server keeps the last one it loaded, and
  asks the database only for the revision before using it.
- **Every write** is one operation run on a snapshot and saved as the difference, in one
  transaction under the advisory lock `inventory`, checking and bumping `inventory_revision`: a
  page's edit, a receipt, an order command. Pages send the sha256 of what they loaded
  (the rows as the old file would hold them), and a receipt the revision its preview saw, so a
  change in between is refused rather than overwritten. Since phase 4 the deck tables a write
  refreshes are saved in the same transaction (see "Decks and accessories in the database"), so
  nothing is written or committed afterwards.
- **When the database is down**, the pages keep showing the last snapshot the server loaded, and
  an admin's database warning says so ("The collection, decks, orders, products, watchlist and
  accessories are read from the database, which can't be used right now..."); every inventory write answers 503 with
  `"reason": "database"`, and the command lines exit 2. JSON answers carry `"inventory_stale"`
  ("inventory as of <time>: the database isn't reachable") and the command lines print it as a
  `Note:`.
- **Who reads it** on the page: see "People's own collections". On the Activity page each
  inventory row shows to the profiles who may see its space (home's to Matt and User1, a person's
  to them and admins), at most 50 rows per change ("and N more"); the summaries are in plain words
  ("Added 2 × Llanowar Elves (FDN 227) to the home collection").
- **Reading it as files:** the nightly export writes the inventory (and the decks and
  accessories) into the export repo's `magic/` folder, byte for byte as the repo's files were, and
  `python -m decklab.db inventory export DIR` writes the same into `DIR/magic` (a new folder: it
  refuses one holding anything else).
- **`python -m decklab.db status`** prints an "Inventory:" line: what the database holds (its
  revision and import time). An admin's database warning also says when it holds no inventory
  (or migration 0004 is still pending).

**The phase 3 cutover** (done once, after phase 3 was built; phase 5b retired its tools): stop the server; `python -m
decklab.db migrate`; `import-files`, then `import-files --apply`; `gate-inventory --live`; tag the
last commit with the files `pre-db-inventory`; `inventory backend db` and commit `config.json`;
`git rm` the inventory files; start the server; `export`.

**With the files backend** (the tests only), `FileInventory` reads and writes the old files in a
test's own tree, the decks, `accessories.csv` and its pictures included. A write is plain atomic
files under the backend's in-process lock; before writing anything it checks that every file is
still what the load read, and refuses the whole change (a 409 conflict, nothing written) when one
changed meanwhile. Nothing is committed to git. Phase 4 deleted the files backend's Git write mode
(its automatic commits, the "commit them first" refusal and `decklab/data/inventory-pending.json`);
`FileInventory.from_git` and `git_files` still read historical fixtures without changing Git. Phase 5 deleted
its cross-process lock and recovery journal (`decklab/data/receipts/active.json`, the 409s while
one was unfinished, and `receive --recover`), and phase 5b deleted `config.json`'s `"inventory":
{"backend": ...}` switch: Deck Lab reads only the database.

### Decks and accessories in the database

Since phase 4 (migration `0006_decks_accessories.sql`) the database holds every space's decks and
the accessories: `deck` (one row per deck: its id, space, kind, slug, and the title, status and
Played by worked out from its text, plus its revision; never its Sleeves or Deck box values),
`deck_text` (each deck's whole text, LF only), `deck_revision` (every saved revision, append-only:
its number, time, actor, message, op `A`/`M`/`D`, whether it changed the kit, the git commit of
one imported from git, and the text; a deleted deck keeps its revisions), `deck_line` (each list's
lines, worked out from the text when it's saved, for `sql` only: Deck Lab never reads it),
`accessory` (one row per accessory, in the columns AGENTS.md lists), `accessory_image` (each picture's bytes, size and sha256)
and `decks_revision`, the decks part's counter. `deck` and `accessory` are audited, so Activity
shows them; the texts, revisions and pictures aren't (as `collection_import_content`), so the
audit trail stays small. A deck id is unique in its space without case (`casual/x` and
`commander/X` can't both exist).

- **One snapshot, two revisions:** the decks, the accessories and the pictures' sizes and
  sha256s are part of the inventory's snapshot (pictures' bytes are fetched only when served), so a
  page, the pool, the tokens, the Forge lists and the accessories' holders all read one consistent
  view. The snapshot has two revisions: `revision` (the inventory: receipt previews check this
  one) and `decks_revision` (the decks, accessories and pictures). A deck, accessory or
  picture save moves only `decks_revision`, so it never makes a receipt ask for a new preview; an
  inventory change whose refresh rewrote a deck moves both. The server caches the two parts apart,
  re-reading the texts only when `decks_revision` moves.
- **Every write is an operation** (`lib/inventory/ops_decks.py`, `ops_accessories.py`), run under
  the advisory lock `inventory` in one transaction, with the final text worked out first: `deck.save`,
  `deck.create`, `deck.update_tables` (all or nothing), `deck.delete` (a 'D' revision; refused for a
  built deck holding a kit), `kit.set` (every sleeve and deck-box move between decks and products, in
  one change), `precon.add` (the collection's import and the new deck together),
  `accessory.add|edit|remove` and `image.put|remove`. Each checks the sha256 the page or command
  read (the deck text's, or the viewer's accessories list token) and answers 409 with who changed
  it, from the deck's last revision or the audit trail. `deck.save` refuses a change to the Sleeves
  or Deck box lines (that's `kit.set`'s), a person's deck gaining home-only fields, a text over
  1 MiB, a NUL or a carriage return. The page's saves are worded "Saved in Deck Lab"; nothing is
  committed to git (the git era's Commit now, Retry and outside-edit warnings went in phase 4).
  A 409 says whether the deck changed or was deleted, and who changed it, when and with what
  message; since phase 5 it has no `committed`, `commit` or `moved_to` keys, and the editor no longer looks for a deck moved by a commit (a rename keeps the old id as an alias).
  Messages name a deck by its id (`casual/gruul-ramp: unknown cards in target list: ...`,
  `user2/commander/x can't be read: ...`), not by its old file's path.
- **History:** a deck's History page and `python -m decklab.db deck history` read `deck_revision`.
  Revisions are numbered from 1 per deck, one more for each save that changes the text; a deck
  made again after a deletion carries on after its 'D'. The 117 revisions the decks had in git
  (40 commits on main, one deletion: aragorn-heroes) were imported with their commit, time,
  author (as a profile id: "(by User1)" in a subject is User1; a Claude co-author trailer is
  Claude; anything else Matt) and message, and `GET /api/deck/revision` still takes a git commit's
  sha for those. Public readers from another space receive server-written summaries
  and "someone" for other-space profile actors, including retired and imported
  revisions. Table updates read "Tables refreshed". A revision that changed
  Sleeves or Deck box shows its message only to whoever saved it, as on Activity.
- **Who sees what:** deck pages and the library hide a space's counts, token chips, table and
  stale list from viewers who can't see its inventory (see "People's own collections"). On the
  Activity page a `deck` row shows to its space's viewers (id, title, status, Played by), and an
  `accessory` row only to viewers who see that row's owner, admins included (id, kind, name,
  colour, quantity); a change with any accessory row or kit change shows its message and reason
  only to whoever made it.
- **Forge provenance:** a deck's list in a matchup or field result records `{"deck", "revision"}`
  (none for a preview or an unsaved draft), where it used to be a file and a git commit. Results
  saved before keep theirs; nothing reads them.
- **Reading them as files:** `python -m decklab.db deck pull --all -o DIR` writes every deck;
  the nightly export and `python -m decklab.db inventory export DIR` write the decks
  (`decks/<kind>/<slug>.md`, `people/<id>/decks/...`), `accessories.csv` and
  `accessories/images/` into `magic/` with the inventory, byte for byte. The export repo's tables
  gain `deck`, `accessory` and `decks_revision`, and since phase 5 `deck_revision` (every saved
  revision, its text included). `deck_text`, `deck_line` and the pictures (`accessory_image`) aren't
  CSVs: the deck files, `accessories.csv` and its pictures under `magic/` stand for them.
- **`python -m decklab.db status`** prints a "Decks:" line: how many decks and saved revisions
  the database holds, and its decks revision (or that migration 0006 or the import is pending).
- **A database with no decks** (migration 0006 not applied, or a restore gone wrong): the database
  backend serves an empty decks part and refuses every deck, accessory and picture save ("Deck,
  accessory and picture saves can't be made: the database holds no decks. Restore the newest
  backup ..."), and an inventory change's refresh leaves the decks alone with that reason. Until
  phase 5 it served the decks part from the repo's files in that state, for the cutover.

**The phase 4 cutover** (once, after phase 4 was built; the build ran on branch `db-phase4` while
production ran main's code; phase 5b retired its tools): stop the server; `python -m decklab.db migrate` (0006); `import-files`,
then `import-files --apply`, from a checkout where main is the branch the server saved to;
`gate-decks --live` (and `history-gate`); tag the last commit with the deck files `pre-db-decks`;
merge `db-phase4` into main; `git rm` the deck files (home's and every person's),
`accessories.csv` and its pictures, and commit; start the server; `export`; purge Cloudflare's
cache of `decklab.example.com/accessory-img/*` (pictures cached publicly before phase 4 could
otherwise still be answered by the edge without the owner check).

**No going back to the files** (phase 5b, 2026-10-14): the rollback runbook and its tools are
gone: `inventory restore-files`, `inventory backend`, `import-files` (and its decks import),
the gates (`gate-inventory`, `gate-decks` and `python -m decklab.db.gate`), `history-preview`,
`history-gate`, the OS inventory lock (`decklab/db/filelock.py`), `config.json`'s inventory
backend switch and the frozen product names in `files.py` (the tests keep those, in
`tests/pre_db.py`). The last commit that had them is the tag `pre-phase5b`; the old files are in
`pre-db-inventory` and `pre-db-decks`. A lost or broken database comes back from a backup (see
"Backups"). The nightly export still writes the data as the old files in the export repo's
`magic/` folder, and the nightly check still reads them back (Matt's decision: two backup places,
the NAS dumps and the GitHub export).

### The `.venv`

The standard library has no PostgreSQL client, so `decklab.db` needs **psycopg**, pinned in `decklab/requirements.txt`. It lives in a `.venv` at the repo root (gitignored), not in the system Python. To make it, from the repo root:

```
python -m venv .venv
.venv\Scripts\python -m pip install -r decklab/requirements.txt
```

Since phase 2 the system `python` uses it by itself: `decklab/server.py`, `python -m decklab.db` and the test package call `lib/venv.py`'s `activate()` first, which puts `.venv\Lib\site-packages` on `sys.path` (just before the system site-packages, so the pinned psycopg wins) when `.venv` was made from this same Python (its `pyvenv.cfg`'s `home` and major.minor version). So run everything with `python`, as before; `.venv\Scripts\python` works too. The background server's task stays on the system `pythonw.exe`, because the `.venv`'s `python.exe` is a launcher that starts the real interpreter as a second process, which would break the recorded pid, `/F` kills, the Forge slots' pid checks and the firewall rule (which names the program). When `.venv` is missing, or was made from another Python, every module still imports and the database counts as unreachable; an admin sees why in the database warning at the top of the page (paths cut), and `decklab/data/logs/server.log` has the full reason. After upgrading Python, make the `.venv` again.

### Setting it up

```
python -m decklab.db setup
```

It connects as `postgres` and makes whatever is missing: the three roles (each with a new random password, set on the server first and then written to `pgpass.conf`; a role that already has a line there keeps it, and if that password no longer logs in, `setup` sets it on the server again), the `decklab` database, the schema migrations, the grants, and the profiles from `config.json`. On a new database, one holding no inventory and no decks at all, it also starts an empty collection, deck library and shopping list (one change set by system), so the pages work from the first run; a database holding either is left alone, since that's a bad restore, not a new install. When pgpass has no line for `postgres`, it asks for that password once at a prompt (only in a terminal) and doesn't save it. It's safe to run again: a second run changes nothing. Then:

- `python -m decklab.db status`: whether the database answers, which migrations are applied and which are pending, how many profiles, spaces and change sets it holds, a "Personal state" line (wishlist cards and lists, settings, the simulations mode, games and sideboard plans), an "Inventory" line (the revision the database holds), a "Decks" line (how many decks and saved revisions it holds, and its decks revision), and the backups: when the last good dump, export and restore check ran (or, when the newest restore check failed, when and why, and when the last good one ran), the last check of the data ("last check: <date>, passed", "passed (2 warnings)" or "FAILED: <its first failing sub-check> (<what it found>)"; see "The nightly check"), a "Side-by-side checks: until <date>" (or "ended <date>") line while `config.json` sets `side_by_side_until`, a warning when the last good dump is more than 36 hours old, and one when the last check failed.
- `python -m decklab.db migrate`: applies new files from `decklab/db/migrations/` (`NNNN_name.sql`, in order, each in its own transaction). It refuses if a migration already applied has been changed since; add a new one instead.
- `python -m decklab.db sync-profiles`: first recovers any pending Settings member creation/email publication against its exact audited database outcome, then copies the profiles from `config.json` into the database (adding, changing and removing them in one change set). It writes nothing when they already match. `config.json` stays the source of the profiles. Config-backed sync shares the member editor's lock and reads the configuration after claiming it, so an earlier queued sync cannot restore a replaced email.
- `python -m decklab.db sql "select * from profile"`: a read-only query (or the query on standard input), printed as a table, or with `--csv`. It runs as `decklab_ro`, so it can't change anything, and stops after 30 seconds.

- `python -m decklab.db wishlist list|add|set|remove ...`: read or change a wishlist (see "Wishlists" above, and AGENTS.md's "Wishlists and other database data"). Exit codes 0 done (an add of a card already listed included), 1 refused or nothing to do, 2 the database can't be reached.
- The inventory's commands (`collection`, `tokens`, `order`, `product`, `watchlist`, `receive`, `inventory export`) are under "The inventory in the database" below and in AGENTS.md, "The inventory"; the decks' and accessories' (`deck`, `accessories`, `image`) under "Decks and accessories in the database" and in AGENTS.md, "Decks" and "Accessories".
Invalid profile entries are reported locally by `python -m decklab.lib.homenet status`, using an entry position and static error code rather than submitted names or emails. `homenet install`, database `setup` and config-backed `sync-profiles` refuse them before changing tasks or the database, so a skipped entry cannot silently remove a profile. Fix the indicated entry in `decklab/config.json`, check status again, then retry setup or sync. Request readers retain their existing tolerant behavior; these diagnostics are not a new page or public roster.

When an Access block is present, local status also reports known sign-in blockers by position and static code: `access_legacy_roles` for no explicit profile roles, `access_no_email` for no usable ASCII alias, `access_invalid_email` for unsupported declared syntax, and `access_duplicate_email` for an alias shared across usable profiles. Valid Access configurations and local-only configurations add no sign-in warnings. These checks reuse the strict Settings address validator without changing tolerant authentication/profile parsing. They do not contact Cloudflare, inspect its policy or verify sign-in. Add the intended address to the Access policy and check that address separately; the [signed-in household workflow checks](design/stories.md#e11-s02) also remain open and do not establish coverage for every member or address.

`setup`, `migrate`, `status`, `sync-profiles`, `sql` and `wishlist` take `--dbname NAME` to work on another database (the tests use it). Every command exits 0 when it worked, 1 when it failed, and 2 when the database can't be reached or psycopg is missing.

The settings are an optional `"database"` block in `config.json`: `host`, `port`, `name`, `pg_bin`, `backup_dir`, `staging_dir`, `export_repo`, `keep_daily`, `keep_weekly`, `restore_check_days`, `stale_backup_hours` and `side_by_side_until` (a date, `YYYY-MM-DD`: the last day of the week of side-by-side checks, which `status` shows; no default). Leave it out to use the defaults given here. For the week of side-by-side checks (2026-10-13 to 2026-10-19) it set `"restore_check_days": 0.5` (so the restore check ran every night: with 1, a night is skipped whenever the steps before it finish sooner than the night before) and `"side_by_side_until": "2026-10-19"`; since 2026-10-19 only `side_by_side_until` is left (from 2026-10-20 `status` says the checks ended), and `restore_check_days` is back to its default, 28.

### Backups

The PC is the only live copy, so backups are mandatory and checked. They go to two places:

- **The NAS:** `\\NAS\Backups\DeckLab\` (`backup_dir`). Each dump is made first in `decklab/data/backups/` (`staging_dir`), then copied to the NAS. Off Windows, `backup_dir` has no default: without one, `backup` keeps the dumps in `staging_dir` only and says so, and the restore check reads them there. The PC reaches the share with the NAS login saved in Matt's Windows Credential Manager, which is why the backup task runs as Matt.
- **The export repo:** a separate **private** GitHub repo checked out at `C:\VSProjects\DeckLabData` (`export_repo`), holding each table as a CSV in `tables/<schema>.<table>.csv`. It's the copy kept outside the home, as this repo's history is today. It holds `space`, `profile`, `profile_email`, `audit.change_set` and, since phase 2, `wishlist_entry`, `profile_setting`, `simulation_mode` and `play_record`, plus each wishlist as `wishlists/<profile>.json` in the format the repo's old `magic/wishlists/` files had (rebuilt at each export: one file per profile with a card, stale ones deleted). Since phase 3 it also holds the inventory's tables and a `magic/` folder with the inventory as the repo's files were (`collection.csv`, `tokens.csv`, `watchlist.csv`, `products/`, `orders/`, `people/<id>/`, each space's `imports/`), byte for byte, rebuilt at each export, and since phase 4 the tables `deck`, `accessory` and `decks_revision` and, in `magic/`, every deck file (`decks/`, `people/<id>/decks/`), `accessories.csv` and its pictures (`accessories/images/`), as the repo had them. Since phase 5 it also holds `deck_revision` (every deck's saved revisions, texts included), so the copy outside the home has the decks' history too. `deck_text`, `deck_line` and the pictures (`accessory_image`) aren't CSVs: the deck files, `accessories.csv` and its pictures under `magic/` stand for them. `audit.row_change` stays out (it holds every row's before and after, private data included), and so do the visits (`ops.visit_day`, `ops.visit_page`: operational, like `ops.backup_run`). Later phases add their tables.

The commands (all with `python -m decklab.db`):

- `backup`: a `pg_dump` of the database into `decklab-YYYY-MM-DD-HHMMSS.dump`, copied to the NAS. If the copy fails, the dump stays in the staging folder and the command exits 1. `--dest DIR` writes somewhere else instead of the NAS.
- `prune`: keeps the newest dump of each of the last 14 days and of each of the last 8 weeks, in both folders, and deletes other `decklab-*.dump` files. However old they are, the newest dump of each of the 14 newest days that have one is always kept, so if dumps stop working the last good ones never age out. It also deletes `decklab-*.dump.partial` files (a dump that was cut off) more than a day old, and never touches anything else in the share.
- `restore-check`: restores the newest NAS dump into a scratch database, `decklab_restorecheck`, compares every table's row count with the counts recorded when that dump was made (or, for a dump without them, with the live database, leaving out `ops`), and since phase 5 every `public` and `audit` table's contents with the digests recorded with it, then drops the scratch one. It exits 1 if anything differs. A dump made before phase 5 has no digests, so only its counts are compared, and the result says so.
  - **The digests:** `backup` reads, in the same snapshot `pg_dump` reads, an md5 of each `public` and `audit` table's rows (each row as PostgreSQL writes it as text, sorted bytewise, under fixed session settings such as the UTC time zone, so the live database and a restored copy write every value alike; `ops` is left out, since it gains rows after a dump). They're kept in the dump's `ops.backup_run` row, in the `digests` column (migration `0007_check_runs.sql`); its `detail` stays `rows: ` and the counts alone.
- `export`: writes the CSVs (and the wishlists' JSON) into the export repo, and its `README.md` whenever it differs, commits ("Deck Lab export YYYY-MM-DD HH:MM") only if something changed, and pushes if the repo has an `origin`. `--repo DIR` and `--no-push` are for trying it out. Git is never allowed to ask for a sign-in, so a push that needs one fails and is recorded instead of waiting at night. It refuses a folder inside this repo, and an existing repo whose `README.md` isn't the export's, so it can't commit into a working repo. It makes the repo (`git init`) when the folder isn't one yet; adding the private GitHub remote as `origin` is left to you. Before migration 0003 is applied it skips phase 2's tables (keeping any CSV already written for them) and leaves `wishlists/` alone, so the nightly task doesn't fail between a code update and `migrate`.
- `check` (since phase 5): checks the data itself (see "The nightly check" below). `check --history [--limit N]` prints the recent runs instead (14 by default).
- `nightly`: what the scheduled task runs: `backup`, `prune`, the visits' prune (days older than 400 are deleted; before migration 0008 it says there's nothing to prune), `export`, `check`, and `restore-check` when the last good one is at least `restore_check_days` (28) days old, then MTGMate prices for the purchase queue and proven saved-home shortfalls (see "Shopping and deliveries"; manual `shops snapshot` remains queue-only). The shop step skips a snapshot under 20 hours old, checking again under its lock before counting, and gets at most 45 minutes of requests at robots.txt's delay. Names least recently read go first; unreached names keep their prior result and original time. Missing-data failure keeps queue lookups working, and a shop failure is logged without failing the night. The check comes after backup and export, so a problem it finds never stops either. Each step runs even if an earlier one failed, and it exits 1 if any did.

Every run is recorded in the database (`ops.backup_run`, kinds `dump`, `export`, `restore_check`, `gate` (the cutovers' gates, retired in phase 5b) and, since migration 0007, `check`) and in `decklab/data/logs/db.log`, which is where to look when `status` warns.

### The nightly check

`python -m decklab.db check` (a step of the nightly task since phase 5) reads everything in one snapshot: one read-only, repeatable-read connection as `decklab_ro`, with the inventory loaded on it, so every sub-check sees the same revisions. The sub-checks, in order:

- **accessories:** what `accessories check` reports. Deck Lab only warns about these (too few sleeves, a deck box used too often), so a problem here is a warning, not a failure.
- **tokens (<space>):** what `tokens check` reports, for every space in `config.json`. A problem fails; a name check skipped because the card data isn't loaded is a warning.
- **orders and queue:** what `python -m decklab.lib.purchases --check` validates.
- **deck tables:** what `deck tables --check` reports, across every space. Out-of-date tables are a warning only (they're expected after a collection merge or a Collection page edit until the tables are refreshed: `deck tables --apply`, or **Update all** on the Decks page's Tables out of date list), and so is a refresh that can't be worked out (no card data, an incomplete pool, a missing deck), with why.
- **deck revisions, deck texts, deck lines, deck headers:** each deck's revision is its newest `deck_revision`, its `deck_text` is that revision's text, its `deck_line` rows are what the text parses to, and its title, status and Played by are the text's header's.
- **revision rows:** `inventory_revision` and `decks_revision` each hold exactly one row.
- **audit trail:** every `audit.row_change` belongs to an `audit.change_set`.
- **files round trip:** the export's files (the inventory's, the raw imports and the deck parts), read back with the files backend, give the same snapshot the database gives, so the export repo's copy can be read back. The files can't carry the products' names, so those are taken from the database's snapshot before comparing.

Each sub-check writes one line to `db.log` ("Check: deck lines: ok: ... (0.1 s)"), and each run adds one `ops.backup_run` row of kind `check`, `ok` when no sub-check failed, whose `detail` is JSON: the inventory and decks revisions it read, and each sub-check's name, result, warning, detail and seconds. It exits 0 when every sub-check passed (warnings allowed), 1 when one failed or the run couldn't be recorded (before `migrate` applies 0007 it says so), and 2 when the database can't be reached. `check --history` lists each run with its revisions and the sub-checks that failed or warned. `status` shows the last run, and an admin's footer warns when it failed, is older than `stale_backup_hours` or never ran (see "The database warning banner").

**The week of side-by-side checks** (2026-10-13 to 2026-10-19; phase 5b retired the rollback early, on 2026-10-14, at Matt's say-so): the nightly check and a restore check ran every night (`restore_check_days` 0.5 and `side_by_side_until` 2026-10-19 in `config.json`'s `"database"` block), and `check --history` and `status` show each night's. Every night passed; [magic/reports/2026-10-19-database-check-week.md](../magic/reports/2026-10-19-database-check-week.md) records how it went, and the restore check is back to every 28 days.

### The nightly task

```
python -m decklab.db schedule install
python -m decklab.db schedule status
python -m decklab.db schedule remove
```

`install` registers the Task Scheduler task "Deck Lab database backup": every day at 03:30, as Matt's own account and only while he's logged on (it must be, to reach the NAS), running `pythonw.exe -m decklab.db nightly` in the repo folder, with no window. If the PC was off at 03:30 it runs when the PC is next on, and a run still going when the next one is due isn't doubled. A run may take at most two hours. It runs the `pythonw.exe` beside the Python `install` was run from, which must be able to use psycopg (the system Python can, through `lib/venv.py`; otherwise it refuses, saying to install the `.venv`'s packages and run `install` again with the system `python`). Run `install` with the system `python`, not the `.venv`'s: the `.venv`'s `pythonw.exe` is a launcher that starts a second process, which the task's time limit may leave running. `schedule status` warns when the task runs a `pythonw.exe` inside `.venv`. The task registered before phase 5 runs the `.venv`'s, so it's registered again from the system `python` at the phase 5a cutover. After making the `.venv` again, or upgrading Python, run `install` again.

**On Linux** (E11-S33) the same three commands manage a systemd user timer instead: `install` writes `decklab-nightly.service` (a oneshot running `python -m decklab.db nightly` in the repo, with the Python `install` was run from, for at most two hours) and `decklab-nightly.timer` (daily at 03:30, `Persistent=true`, so a night the computer was off runs as soon as it's on) into `~/.config/systemd/user` (`$XDG_CONFIG_HOME/systemd/user`), and enables and starts the timer with `systemctl --user`. It refuses a Python that can't import psycopg, as on Windows. `status` shows the next and last run and whether that run failed, and warns when the timer isn't enabled, when the units differ from what `install` would write now (the repo moved, or Python changed: run `install` again) and when lingering is off, so the timer runs only while the user is logged in (`loginctl enable-linger`). `remove` disables the timer and deletes both units. On other systems the commands say to run `nightly` from cron.

To see the units without installing them, for another computer's paths, `preview-systemd` prints one complete unit to stdout:

```
python -m decklab.db schedule preview-systemd --unit service --python /usr/bin/python3.14 --workdir /srv/DeckLab
python -m decklab.db schedule preview-systemd --unit timer --python /usr/bin/python3.14 --workdir /srv/DeckLab --at 03:30
```

Both target paths are required, absolute POSIX paths; quote shell arguments containing spaces. `--at` is local HH:MM, default 03:30. The preview reads no configuration or database, calls no host manager and writes no files, and other schedule actions reject its options. The timer won't start the service while it's still running, but separate direct `nightly` commands have no shared lock.

### The server and the database

- **At start-up** (after the URL line), the server starts a thread that checks the database once a minute (`lib/dbstatus.py`) with one app-role connection: which migrations are pending, whether phase 2's tables can be read, and when the last good dump finished. The first check logs one "Database: ..." line in the server log, and only the background server then copies `config.json`'s profiles into the database (with the request timeouts, so a lock held elsewhere fails it with one line rather than stalling the checks; it never removes every profile). It never applies migrations itself, never fails the start, and is stopped first when the server stops.
- **The check feeds the breaker:** it opens it when the database stops answering and closes it as soon as it answers again. A check that fails some other way (a statement that timed out, an unexpected error) is "check failed" and leaves the breaker alone. The raw details go only to `decklab/data/logs/db.log`, once per change.
- **`GET /api/status`'s `"database"` block** is answered from that check at once (`{"ok": null, "checking": true}` before the first one). Everyone gets `{"ok"}`: whether wishlists, settings and play records can be used. An admin (by role, or a script naming nobody) gets `ok` (everything in order) and `usable`, `error` (`not reachable`, `psycopg missing`, `migrations pending` or `check failed`), `pending_migrations`, `last_backup`, `backup_stale`, `stale_hours`, `checks_warning` (since phase 5: the footer's words about the nightly checks, or null) and `venv`. The once-a-minute check also reads the newest `check` and `restore_check` runs for `checks_warning`.
- **Code and migrations:** a change to `decklab/db/*.py` counts as server code (the version banner asks for a restart); a new migration doesn't, and the banner asks for `migrate` instead.

### The database warning banner

The version banner (`#build-warning`) gets a "Deck Lab's database" part when something's wrong. Everyone sees "Deck Lab's database isn't reachable, so wishlists, settings and play records can't be read or saved right now" when the stores can't be used. Only admins see the rest: migrations waiting (with "Run python -m decklab.db migrate on the PC", and whether the stores wait on it), "couldn't check its database just now", why the server's Python can't use psycopg, a backup older than `stale_backup_hours` (36 by default) or none yet, and, for the database-backed inventory, that the pages show the inventory as it was when the database was last reached (changes can't be saved meanwhile), or that it holds no inventory ("Deck Lab's database holds no inventory. Restore the newest backup into it on the PC, then check it with python -m decklab.db status.", also shown while migration 0004 is pending; before phase 5 it said to run `import-files --apply` or switch back to the files). `GET /api/status`'s admin block has `"inventory"` for this: the backend, whether the database holds an inventory, its revision and import time, and `stale`. Since phase 5 admins also see the nightly checks' warning (the block's `checks_warning`): "No check of the database's data has run yet", "The database check of <date> found a problem (<sub-check>). On the PC, python -m decklab.db check --history says more.", a last check older than `stale_backup_hours`, or "The restore check of a database backup on <date> failed".

### Visits

Since 2026-10-13 (the user's request, as informal user-testing feedback: whether User1, User2, User3 and User4 actually use Deck Lab and what they look at) the server records who visits and which pages they open. An admin reads it in the Settings page's **Visits** part (`GET /api/visits?days=N&who=<profile>`; 403 for anyone else, and the part isn't drawn for them) or on the PC with `python -m decklab.db visits [--days N] [--profile P]` (read-only, as `decklab_ro`; `--days` from 1 to 366, as the page's API). Each profile in `config.json` is listed, those never seen as "Not seen yet": when it was last seen and from where (at home or from outside), how many of the last 30 days it visited, when it was first seen, and the pages it opened most recently and most often (a deck's pages with the deck's title).

- **Who is recorded:** a profile `config.json` lists, and only the profile a request is from: through the tunnel the Cloudflare Access login's (channel `remote`), on the home network the one the page's "Who are you?" chooser names (`X-Deck-Lab-Viewer`, channel `home`). A request naming nobody (a script, the command line, `homenet status`'s probes, the page before someone is chosen) is never recorded.
- **What:** per profile, day (the PC's date) and channel, the first and last time a page was opened and how many API requests were made (`ops.visit_day`); and the pages opened (`ops.visit_page`): the page's router sends `POST /api/visit` with the route's path (`library`, `deck`, `shopping`...) and, on a deck's pages (deck, edit, history), the deck's id, on each route change (the same page drawn again within two seconds is sent once). Only the pages make a visit: the page's own polling (`/api/status` every 30 seconds, the run activity, a run's progress) adds to the day's request count but never makes a day or moves last seen, so a tab left open (an iPad on a stand) isn't "seen" all day, and requests on a day with no page opened aren't kept. Nothing else of the address is kept: no search text, filters, wishlist notes or card names. A deck's id is kept only for a deck that exists (the library's ids, read at most once a minute, or every 10 seconds for an id not among them), and at most 200 different pages per profile, day and channel (past that only those pages count), so nobody can fill the tables with made-up pages. The beacon isn't a data write: no change set, no Activity row and no permission rule, so a member's visits are recorded like an admin's; it needs the page's write headers like any POST, and records only for the requester (a `profile` in its body must be the requester's own: 403 otherwise).
- **Cheap and never in the way:** the server gathers the counts in memory (`lib/visits.py`, thread-safe) and a timer thread writes them once a minute in one transaction as `decklab_app` (and when the server stops), so a request never waits on the database. A write that fails is logged once in `db.log` and its counts are kept for the next try (up to 5,000 rows in memory). A write connects with the requests' 2-second timeout and has lock and statement timeouts. The Visits part writes what's waiting before it reads, waiting at most a second for a write under way and not at all while writes are failing; the server's stop skips its last write while they are.
- **Kept for about a year:** the nightly task deletes days older than 400 days (`visits` step). The tables are operational, like `ops.backup_run`: not audited, not exported, and outside the dumps' content digests (a restore check still compares their row counts); migration `0008_visits.sql` lets `decklab_app` add and update them but not delete.
- **Privacy:** only admins see it on the page; the PC's `sql` and `visits` commands read all of it. It says who opened which page and when, never what they typed or changed (the Activity page has the changes).

### Tests

Database integration tests need the running PostgreSQL service, its configured roles and psycopg. They are separate from the default fixture checks below: ordinary `python -m unittest` imports may probe the configured server before individual tests install their disposable fixtures. Run that integration workflow only when explicitly authorized for this PC and its database; the fixture runners always disable it before discovery, whether PostgreSQL is available or not.

The integration helper builds a template database for each checkout (`decklab_tmpl_...`) and a throwaway copy for each test class. That workflow reads configured settings and authenticates to PostgreSQL; its intended data writes are confined to those test databases. Its ordinary isolation includes: the test package sets `DECKLAB_DB_NAME` to a database that doesn't exist, makes `state.store()` refuse unless a test installed a store, and (since phase 5) sets `DECKLAB_DB_LOG` to a file in a temporary folder of the run's own, which the test servers and other processes the tests start inherit, so their `db.log` lines never reach the one the nightly task and its checks are read from. Everything else runs on a `MemoryStore`, and on the files backend over a temporary tree for the inventory, decks and accessories (the Sandbox installs a `FileInventory`). Tests that read the real decks take them from the `pre-db-decks` tag (`tests/pre_db.py`'s `decks_inventory()`; a clone without the tag skips them), never the working tree. `test_inventory_contract` runs the same scenarios through both backends and compares every reader's output with kept goldens (`tests/fixtures/inventory_goldens/`), through the reader dump the cutover gates used (`tests/golden_dump.py`, normalised by `tests/golden_p4.py`). A git worktree has no `.venv` of its own; separately authorized database qualification needs an interpreter with psycopg available.

On 2026-10-12, with PostgreSQL up, the whole suite ran 3,210 tests in about 8½ minutes (30 skipped).

## Tests

Safari on iPhone and iPad Simulators has a separate [Mac setup and runner](safari/README.md)
and a [Windows-to-Mac workflow](safari/MAC-WORKFLOW.md) covering SSH, source transfer and results
for E11-S29: `python3 -m decklab.safari` runs the portrait/landscape matrix against
disposable synthetic data and writes per-configuration reports and failure artifacts.
The [accepted Mac report](safari/EVIDENCE.md) records 60/60 checks passing on
Xcode 27.0 and iOS 27.0 across all six configurations. E2-S22 keeps the remaining
physical hardware and touch-usability checks separate from this Simulator coverage.

The [source-length audit](SOURCE_AUDIT.md) records the module boundaries and the
upstream Forge exceptions. The lint workflow runs the guard and its isolated inventory tests alongside Ruff on every push and pull request. To check locally for files growing past the 1,200-line review threshold:

```
python scripts/audit_source_lengths.py --check
```

From the repo root, run the default fixture checks:

```
python scripts/test_fixtures.py
python scripts/test_fixtures.py decklab.tests.test_collection_import_groups
python scripts/test_shard.py 0 4 --hang-after 600
```

The first command discovers the fixture suite, the second selects ordinary unittest module/class/method names, and the third runs one of four module shards (indices 0 to 3). Both entry points install the same guards **before test imports**: private config and PostgreSQL credential files appear absent, configured PostgreSQL connectors fail closed, and inherited configuration overlays and the real-Forge opt-in are removed. Disposable fixture files, local synthetic HTTP servers and explicitly installed fake connectors still work. Saved-script multiprocessing workers install the guards again before importing their targets.

Database integration and named native runtime checks remain in discovery with explicit skip reasons. Ordinary child interpreters do not inherit in-memory patches; the known server, command and process-monitor children that escape fixture isolation are skipped too. This runner prevents accidental configured-server use; it is not a sandbox for malicious code. A green fixture run does not establish PostgreSQL, native process/service, browser/device or real-Forge acceptance.

Tests use a stand-in for Forge (`tests/fixtures/fake_forge.py`) and disposable inventories and stores. Genuine database, native lifecycle and real-Forge checks use a separate explicitly authorized integration workflow. Raw `python -m unittest` does not install fixture protections. `DECKLAB_FORGE_TESTS=1` enables real Forge checks only in that separate workflow; `test_forge_v2loop` then uses the PC's real Forge slots and may wait for one. The separate Linux service CI job is also runtime qualification, rather than fixture coverage.

## Command-line helpers

- `python -m decklab.lib.cards update`: download the card data and build the index without the server (and refresh Scryfall's rulings for the card viewer, the combo list and the official lists' check, each a step whose failure never fails the update).
- `python -m decklab.lib.stats casual/gruul-ramp`: a deck's stats as text.
- `python -m decklab.lib.pool casual/gruul-ramp`: owned vs needed for one deck. A person's deck id (`user2/casual/elves`) is checked against their own collection; with no deck, `--space user2` shows a person's pool.
- `python -m decklab.lib.purchases --check`: check the order records, receipt states and the purchase queue; exits 1 if something's wrong, 2 when the database can't be used.
- `python -m decklab.lib.accessories --check` (or `python -m decklab.db accessories check`): check the accessories, their pictures and the decks' and products' sleeves and deck boxes; prints "Accessories: no problems" when all is well (it said `accessories.csv` before phase 5), and exits 1 if a rule is broken, 2 when the database can't be reached. A problem names a deck by its id ("casual/idea has Sleeves 'red' but isn't built; remove it").
- `python -m decklab.lib.tokens --check`: check home's token cards (readable rows, the standard order, Scryfall face names and printings, `single-sided verified` on a blank back) and the pending token orders; prints "Token cards (home): no problems" when all is well, and exits 1 if a rule is broken. Without the card data it skips the name checks and says so. `--space user2` checks a person's instead.
- The inventory's own commands (`python -m decklab.db collection|tokens|order|product|watchlist|receive|inventory`) are in AGENTS.md, "The inventory", and under Database above; the decks' and accessories' (`python -m decklab.db deck list|show|pull|push|new|delete|history|revision|tables`, `accessories list|show|check|add|edit|remove`, `image put|remove`) in AGENTS.md, "Decks" and "Accessories". `deck tables` replaces `scripts/refresh_deck_tables.py`, deleted in phase 4.
- `python -m decklab.lib.tokens commander/gandalf-and-the-valley`: a deck's tokens as text, each with its state, the cards that make it and the owned cards to grab (`--owned` for the owned-only list). `python -m decklab.lib.cards show <name>` prints a card's "Makes:" line too.
- `python -m decklab.lib.scan PHOTO [PHOTO ...] [--json] [--engine auto|windows|tesseract]`: E7-S32's recognition spike. Reads a photo of one card with Windows' own OCR engine (nothing to install; Tesseract when it's on the PATH instead) and prints the printings it may be, best first, from the card index: the set code and collector number on a modern card's bottom line, checked against the name at the top; only the name on a card older than 2015. `--text FILE` takes lines already read instead of a photo. It changes nothing; the findings are in `design/scanning-spike.md`. On the Collection page, More, **Scan cards…** does the same from a phone's camera (`POST /api/collection/scan`, the space's own people only, nothing written, the photo deleted once read); each pending card's printing (the scan's proposals or **Other printings…**), copies, finish, condition and language (as read, else not recorded) can be changed, and **Review** hands the list to the import preview.
- `python -m decklab.lib.edhrec commander/giada-angels`: EDHREC's commonly played cards for a Commander deck's commander, grouped by EDHREC's categories with the share of decks playing each, marked free, in use or to buy (with the AUD estimate) in the deck's own space; `--all` also lists the cards already in the deck, `--no-prices` skips the estimates and `--refresh` fetches again once the copy in `data/edhrec/` is an hour old (it's fetched anyway after a week). Cards outside the commander's colour identity or not legal in Commander are left out. Exits 1 for a deck that isn't a Commander deck, 2 when the database can't be reached and 3 when EDHREC can't be reached and nothing is cached.
- `python -m decklab.lib.goldfish casual/gruul-ramp`: the practice-hand simulation for one deck (100,000 games on the play and on the draw, about a second); `--all` for every deck (a Commander deck's row is its multiplayer games, the rest on the play). A pairing's halves can come in either order (`pairing/elves+cats`). Results are saved in `data/goldfish/`; Ctrl+C stops a run.

- `python -m decklab.lib.forge play casual/izzet-prowess casual/gruul-ramp --games 800`: a matchup without the page (`--owned-a`/`--owned-b` for the owned-only lists). It plays in the running server's warm pool when there is one that plays the same engine, else in a pool of its own (`--local` always uses its own). It prints the win rates, the starting player's chance of winning, who's ahead in the page's words, and `!` lines for how far to trust them (as the page's "How far to trust these numbers") and about the engine (plain Forge and why; each deck Forge's AI plays as a slower, non-aggro deck). Its "this run" line says where it played and "warm workers", "slowest start-up N s" or "cold processes". `status` says whether Forge is ready, whether runs keep the card log, and about the server's warm pool; `audit <deck>` lists the cards Forge's AI can't play and whether Forge pilots the list poorly, with each card's reason; `list` shows the saved results, marking those of an earlier engine; `cards <deck>` (`--owned`, `--json`) prints how each card of a list played in all its saved matchups (with the best estimates and the "by t3" share); `cardlog-check` checks the card log after a Forge upgrade, and `serve-check` that a warm worker plays the same games as fresh processes; `replay` (`--dry-run`, `--local`, `--matchups N`, `--json`) plays saved matchups of earlier engines again with today's engine (see "Earlier engines" above); `pool` (`--json`) shows the server's warm workers; and `slots` (`--json`) shows the Forge processes running on this PC, from every checkout. Ctrl+C stops a run and saves the games that finished. Several command-line runs at once share the PC's `forge_workers` slots with each other and with the page, so they never have more than `forge_workers` (16) Forge processes computing between them; one that has to wait says so.
- Since wave 3: `play A B --until assess|ahead [--max N]` plays until the win rate is known to ±3 points or until one deck is clearly ahead (printing each check), instead of `--games`; `field <deck>` plays or shows a deck against its format's field; `variant <deck> --remove "N Name" --add "N Name" (--against <deck> | --field)` tests a change on the deck's own games; `experiment <spec.json>` plays an experiment's arms against its control; `pilots` and `overrides` show and check the AI fixes (see "AI fixes" above); and `staged-move` and `soak-probe` are the overnight run's. `play`, `replay`, `field`, `variant` and `experiment` take `--logs-dir <folder>` (and `--log-every N`) to keep Forge's output of the games, gzip-compressed.
- `python -m decklab.lib.homenet install | remove | start | stop | restart | status`: the background server (see above). `install --at-logon` also starts it at every logon and installs the watchdog task, which runs `ensure` every 5 minutes to restart it after a crash. `--port N` and `--task NAME` are for testing with a throwaway task on another port (with `install --host 127.0.0.1`, and `--log FILE` for its log). If `config.json` can't be read, `stop`, `status` and `remove` still work when given `--port`; the others say what's wrong and do nothing.

Each module's docstring in `lib/` explains the rest. A module that's a package (`api`, `decks`, `forge`, `goldfish`, `homenet`, `stats`) keeps it in its `__init__.py`, with a list of its parts.
