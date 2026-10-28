"""Deck Lab's web server: the page, its JSON API and the card images.

Usage (from the repo root):
    python decklab/server.py [--host 0.0.0.0] [--port 8642] [--no-update] [--log FILE]
    python decklab/server.py [--port 8642] --stop

The host and port default to "host" and "port" in decklab/config.json (all
network interfaces, port 8642), so phones on the home network can reach it at
http://<PC's IP>:8642. Stop it with Ctrl+C (or Ctrl+Break), which stops a
practice run or the Forge matchups in progress too: each matchup stops within
about a second and saves every game it finished, and the server waits up to
FORGE_STOP_WAIT seconds for that. Closing the server's window does the same,
but Windows ends the process about 5 seconds after the window closes, so it
waits CLOSE_WAIT seconds at most (ctrl_handler).

In the background: python -m decklab.lib.homenet start has Task Scheduler
start the server with pythonw.exe, which has no window (homenet install sets
the task up, off at logon unless --at-logon; homenet stop, restart and
status run it too). Without a window:
- The log goes to decklab/data/logs/server.log (control.LOG_FILE), rotated
  at 2 MB with 3 old files kept (server.log.1 to .3). --log FILE sends it to
  FILE instead, with or without a window (a window then shows nothing).
  Crashes go there too: at start-up, in main() and in any thread.
- --stop (or python -m decklab.lib.homenet stop) stops the server on --port
  the way Ctrl+C does: it sets the server's stop event (control.listen_for_stop),
  then waits up to control.STOP_WAIT seconds for the process to end, and
  exits 0 when it has stopped or wasn't running, 1 otherwise. It first
  writes the stop marker (control.mark_stopped), so homenet's watchdog task
  leaves the server off (E11-S26); a server stopped on request (--stop,
  taskkill without /F, Ctrl+C) writes one too as it exits, and a server
  clears it once it's listening. With --port
  it doesn't read decklab/config.json at all; without, a config.json that
  can't be read gets a plain message saying to pass --port.
- When Windows logs off or shuts down, a hidden window hears of it
  (control.watch_session_end) and the server stops as when its window
  closes: it waits CLOSE_WAIT seconds at most for a matchup to save.
- taskkill /PID <pid> (or /IM) without /F asks that hidden window to close,
  and the server stops the way --stop stops it ("Asked to close (taskkill):
  stopping." in the log). taskkill /F still ends it at once, and a matchup
  that's playing loses the games it hadn't saved.
Servers in a window listen for --stop, taskkill and the session's end too.

While a server runs, decklab/data/server.json (control.STATE_FILE) says so:
its process id, host, port, start time, Python, log file, and whether it
started without a window. It's written once the server is listening and can
be stopped (by --stop or taskkill), and removed when it exits cleanly (only
if it still names that process); a server never replaces the file while it
names another server that's running (say, a second one on another port).
homenet status reads it, and so does a server whose port is taken: then it
says which server is running and how to stop it. On Windows a server takes
its port for exclusive use, so a second server can't share it even on
another address (127.0.0.1 beside 0.0.0.0, say). (The DECKLAB_STATE_FILE
environment variable moves the file; only the tests use it, so the servers
they start never touch the real one.)

On start, a background thread runs cards.update() (downloading Scryfall's bulk
files when they're over a week old) and checks again once a day; --no-update
skips that and only loads the index there is. Until the card index exists,
the deck endpoints answer 503 and /api/status says "updating".

URLs (JSON unless noted; errors are {"error": "..."}, plus "blocks" or
"conflict" where noted; the lib/api package builds each answer). Routes that
read or write the database (wishlists, settings, simulations mode, play
records, Activity) answer 503 with "reason": "database" while it can't be
reached (api.common.state_errors), except GET /api/simulations, which answers
with "unavailable": true. The inventory (collections, token cards, orders,
products, the watchlist: lib/inventory/, from the database) is read from one
snapshot per request (inventory.pinned); while the database can't be reached,
reads get the last snapshot the server loaded and a JSON object answer gains
"inventory_stale" ("inventory as of <time>: the database isn't reachable"), and
inventory writes answer 503 with "reason": "database":
    GET  /api/status                     card data ready?, updating?, cached USD->AUD rate, and
                                         "database" (lib/dbstatus.py, from its once-a-minute check):
                                         {"ok"} for most (can wishlists, settings and play records be
                                         used?); an admin's also has usable, error, pending_migrations,
                                         last_backup, backup_stale, stale_hours, checks_warning (the
                                         nightly checks), venv and "inventory"
                                         (the backend, the database's revision and import time, stale)
    GET  /api/profiles                   the people in config.json
    GET  /api/me                         who is asking: {"profile": <id> or null, "name", "remote",
                                         "may": what they may change and see (permissions.summary,
                                         with "see_inventory": the spaces whose inventory, null for all)}
                                         (access.me; at home for the profile the viewer header names,
                                         else null, and "may" an admin's only for a script)
    GET  /api/simulations                who may start Forge runs now and the PC's worker limit, for the
                                         viewer (lib/api/simulations.py); "unavailable": true when the
                                         mode couldn't be read (the last one read, else "admins", applies)
    PUT  /api/simulations                body {"profile", "mode"?: "everyone"|"admins"|"paused",
                                         "workers"?: 1..forge_workers or null}: an admin's
    GET  /api/commander-night            home's optional dated venue/table notes and saved revision
    PUT  /api/commander-night            {"profile", "expect", "night", "reason"?}: a home admin's;
                                         null clears with a reason, one audited optimistic save
    GET  /api/profiles/<id>/settings     that person's settings (defaults for any not saved)
    GET  /api/profiles/<id>/wishlist     that person's wishlist: {"profile", "entries", "warnings"};
                                         403 unless the viewer is that person (a wishlist is private,
                                         even from an admin and from a script naming nobody)
    POST /api/profiles/<id>/wishlist     body {"profile", "action": "add"|"remove", "name", "set"?, "number"?}:
                                         the answer adds "saved" and "changed" (the person's own list only)
    PUT  /api/profiles/<id>/settings     body {"theme": "system"|"light"|"dark",
                                         "matchup_games": "800"|"200"|"400"|"1600"|"3200",
                                         "matchup_mode": "assess"|"ahead"|"fixed",
                                         "field_budget": "standard"|"quick"|"thorough"}, any of them
    GET  /api/decks                      the library, with missing-card counts and each deck's cover card
                                         (only the decks the viewer may see: its own space's, E10-S30)
    GET  /api/shopping                   shared purchases, deliveries and arrival checks (home's:
                                         403 outside the home, see Security)
    POST /api/shopping/check             body {"profile", "order", "component", "check"}: a received
                                         delivery's open check marked done (order.checks resolve, one
                                         change); an admin's, who sees home (lib/api/shopping.py)
    GET  /api/receipt?order=<id>         a recorded delivery for the Receipts page, with the inventory's
                                         revision as "fingerprint" (lib/api/receipts.py; home's)
    POST /api/receipt/preview            body {"profile", "order", "fingerprint", "received_on",
                                         "components"}: what the receipt would change, run in memory
                                         (409 when the inventory moved on; 400 when the deck tables
                                         couldn't be refreshed after it); kept 30 minutes, used once
    POST /api/receipt/apply              body {"profile", "preview"}: save it, with the deck tables it
                                         refreshes ("tables"), as one change; an admin's, who sees home
    GET  /api/arrivals                   the viewer's arrival notices (E6-S19, lib/api/arrivals.py): the
                                         decks a receipt brought cards for, a home player's own only
    POST /api/arrivals/dismiss           body {"profile", "ids"}: dismiss the writer's own notices
    GET  /api/assembly[?deck=<id>&version=], POST /api/assembly/preview   the packing plan
                                         (lib/api/assembly.py; home's pool, so home's)
    POST /api/decks                      create a deck, one change (201; 409 + "conflict" if its
                                         name is taken in the space); "space" defaults to the
                                         profile's own
    GET  /api/deck?id=<deck id>&version=target|owned   (without "owned", "table" and "tokens" for a
                                         visitor who may not see the deck's space's inventory)
    GET  /api/compare/shared?a=<deck id>&av=&b=<deck id>&bv=   the cards both lists use (E1-S13,
                                         lib/api/compare.py), with the copies the pool can cover for
                                         both only for a visitor who may see the space's inventory
    GET  /api/deck/history?id=<deck id>  its saved revisions, newest first (lib/api/history.py)
    GET  /api/deck/revision?id=&revision=<n or an imported git commit>&version=   one revision's list
    GET  /api/deck/edit?id=<deck id>     a deck as the editor loads it (lists, fields, sha256)
    POST /api/deck/check                 what a save would do: blocks, warnings, preview
    POST /api/deck/save                  save a deck in Deck Lab as one change (400 + "blocks",
                                         409 + "conflict" when the deck was saved since it was read)
    GET  /api/deck/cards?id=<deck id>    the picture picker's cards: its Planned list's cards once
                                         each, the automatic cover, the summary's cover and revision
    GET  /api/deck/find?q=&scope=all|owned&colors=&type=&mv=&id=|space=&limit=&page=
                                         the editor's card finder (lib/api/editor.py find_cards;
                                         owned counts only of a space the visitor may see)
    GET  /api/deck/swaps?id=&version=target|owned&card=   owned stand-ins for each missing card
    POST /api/deck/swaps                 the same for the Play-now list being edited (a dry run;
                                         lib/api/swaps.py; 403 for a space whose inventory the
                                         visitor may not see)
    POST /api/deck/cover                 body {"profile", "id", "expect", "cover"}: set or clear the
                                         deck's Cover card line, one change (lib/api/cover.py)
    POST /api/deck/token-cards           body {"profile", "id", "expect", "tokens_sha256", "cards"}: set a
                                         built deck's Token cards line, one change (lib/api/token_cards.py)
    GET  /api/tokens/plan[?space=]       every built deck's Token cards line as planned (lib/api/token_plan.py)
    POST /api/tokens/plan                body {"profile", "space", "sha256"}: save that plan, one change
    POST /api/decklist/parse             "Paste a list": known lines, unknown names, errors
    GET  /api/tables/stale               decks whose owned-vs-needed table is out of date (of the
                                         spaces the visitor may see)
    POST /api/tables/update              rewrite those tables, in one change (only decks the profile
                                         may change: the rest are "skipped_not_allowed")
    GET  /api/goldfish?id=<deck id>&version=target|owned[&retry=1]
                                         practice hands: a saved result (200), or the run
                                         started or joined (202: ask again in a second)
    GET  /api/matchups                   Forge matchups: saved results, runs waiting or playing
    GET  /api/rankings?format=Constructed|Commander
                                         read-only field rankings, uncertainty and excluded lists
    GET  /api/library/forge              each visible casual list's field average and when it was
                                         tested (the library's Forge line; cached)
    GET  /api/matchup?a=<deck id>&av=target|owned&b=<deck id>&bv=target|owned[&profile=<id>]
    GET  /api/matchup?key=<64 hex>[&profile=<id>]
                                         one matchup: 202 while its run waits or plays, else 200
    POST /api/matchup/run                body {"profile", "a", "av", "b", "bv", "games"}: play it
                                         (or join the run already going); 202 while it waits or plays
    POST /api/matchup/stop               body {"profile", "key"} (+ "a", "av", "b", "bv" for the
                                         answer's point of view): Stop; a no-op when nothing plays
    GET  /api/field?id=<deck id>&version=target|owned[&profile=<id>]
                                         the deck against the field (wave 3); 202 while a field run
                                         of it waits or plays
    POST /api/field/run, /api/field/stop body {"profile", "id", "version", "budget"}: play the field
                                         (or join the run going), or Stop it
    GET  /api/variant?test=<id>          a test of a change (wave 3); 202 while it waits or plays
    GET  /api/variant/estimate?id=&version=&against=<deck id>|field[&av=]   its rough time
    GET  /api/variants?id=&version=      the tests of a deck's list
    POST /api/variant/run, /api/variant/stop, /api/variant/more
                                         body {"profile", ...}: start a test, Stop it, play more
    GET  /api/cards/search?q=<text>&limit=<n>[&detail=1]
                                         names for autocomplete (detail: type, cost, printing)
    GET  /api/cards/printings?name=<name>   the printing picker: owned counts, prices
    GET  /api/cards/rulings?name=<name>    the card viewer's: {"name", "available", "updated", "rulings":
                                         [{"date", "source", "text"}]} (lib/api/card_rulings.py)
    GET  /api/printings?name=<exact name>   the Add card sheet's: {"name", "printings": [{"set", "set_name",
                                         "collector_number", "finishes", "released"}]}, newest first
    GET  /api/collection?space=<id>&q=&color=&type=&role=&mv=&availability=&page=&limit=
                                         a space's cards (home by default), with "space", "spaces"
                                         and "editable" (403 for a space the viewer may not see)
    GET  /api/collection/rows?space=<id>   that space's collection.csv rows as written, and sha256
                                         (403 as /api/collection)
    GET  /api/collection/download?space=<id>   {space, filename, csv}: that collection as collection.csv's
                                         text, to save (403 as /api/collection)
    POST /api/collection/save            body {"profile", "space", "sha256", "action": "add"|"edit"|"remove",
                                         "row"?, "original"?, "reason"?}: change one row, one change set
                                         (409 + "sha256" and "rows" when the rows changed)
    POST /api/collection/bulk            body {"profile", "space", "sha256", "keys": [{"set", "collector_number",
                                         "finish"}], "condition"?, "language"?, "only_blank"?}: set those rows'
                                         condition and language, one change set (409 as save)
    POST /api/collection/import/preview  body {"profile", "space", "filename", "text"} (up to 4 MB, 20,000 rows): read
                                         a ManaBox, Moxfield, Deckbox or collection-columns export
    POST /api/collection/import/apply    body {"profile", "space", "token", "sha256", "skip_problems"?}:
                                         merge it and keep the upload as a raw import, in one change
    POST /api/collection/trade/preview   body {"profile", "space", "sha256", "gave": [{"set", "collector_number",
                                         "finish", "quantity"}], "got": [rows], "with"?, "message"?}: what a
                                         trade would do (E7-S22: held copies, tables left out of date)
    POST /api/collection/trade           the same body and "confirm_in_use"?: the trade as one change set
    GET  /api/precons?q=<words>          paper precons MTGJSON lists, newest first (lib/api/precons.py)
    GET  /api/precons/preview?file=<f>&space=<id>   what adding one would do: its cards, list and tokens
    POST /api/precons/add                body {"profile", "space", "file", "title", "sha256", "fields"?}: add
                                         its cards to the collection and make its built deck, as one
                                         change
    GET  /api/precons/coverage?space=<id>&format=<f>&type=<t>   precons ranked by how much of each the space's
                                         free pool covers (E1-S24, lib/api/precon_coverage.py), best first
    GET  /api/precons/coverage/deck?file=<f>&space=<id>   one precon's missing cards, with estimated AUD costs
    POST /api/precons/start              body {"profile", "space", "file", "title"}: a new idea deck from
                                         its list, as POST /api/decks makes one (nothing is added)
    GET  /api/play[?id=<deck id>]        list snapshots, and the played games and sideboard plans the
                                         viewer may see (permissions.sees_play_record: those with a deck
                                         of their own space; an admin or a script every one)
                                         (each {"record", "sha256"}), with "warnings" and "today"
    POST /api/play/game, /api/play/sideboard   body {"profile", "id", "sha256", <the record's fields>,
                                         "preview", "review_sha256"?}: preview, then save a game or a
                                         sideboard plan (409 when it changed since it was read)
    GET  /api/activity?before=<id>&limit=<1-100>&kind=<kind>&actor=<profile id>   the Activity page: the
                                         database's change sets this viewer may see, newest first, each
                                         with a plain headline, and "next" (lib/api/activity.py)
    POST /api/visit                      body {"route", "deck"?}: the page's beacon, the page the
                                         requester opened (its own profile only; not a data write:
                                         no change set, no permission rule; lib/api/visits.py)
    GET  /api/visits?days=<1-366>&who=<profile id>   who has visited and what they opened, for an
                                         admin (403 otherwise; the Settings page's Visits part)
    GET  /img/<set>/<number>/<small|normal|large|art_crop>[-back]   a card image (JPEG), cached for a week
    GET  /sym/<code>.svg                 a card symbol ({W/U} is WU.svg, {T} is T.svg): Scryfall's SVG,
                                         cached in decklab/data/symbols/ (lib/api/symbols.py)
    GET  /api/accessories                the sleeves, deck boxes and playmats (the inventory's),
                                         who uses each, and the products kept intact (403 for a
                                         visitor who may not see them: see Security)
    POST /api/accessories/fetch          body {"profile", "url"}: download and stage a product's picture
    POST /api/accessories/save           body {"profile", "sha256", "action": "add"|"edit"|"remove", ...}:
                                         change one row, with its picture (409 + "conflict" and
                                         "latest", or + "blocks" for a row a deck uses)
    POST /api/accessories/assign         body {"profile", "holder", "field", "id", "holder_sha256",
                                         "move_from"?}: a built deck's or intact product's sleeves or
                                         deck box (409 + "taken_by" when they're in use)
    GET  /accessory-img/<id>.<jpg|png|webp>?v=<hash>[&viewer=<id>]   an accessory's picture (v
                                         required: the first 8 hex digits of its sha256), cached
                                         for a week, privately
    GET  /accessory-img/staged/<token>.<ext>[?viewer=<id>]   a fetched picture not saved yet (no-store)
                                         (both 403 for a visitor who may not see the accessories;
                                         viewer names the profile on the home network, since an
                                         <img> sends no X-Deck-Lab-Viewer header: the header wins
                                         when sent, and through the tunnel the login decides)
    GET  /api/tokens[?space=<id>]        a space's token and reminder cards (home's by default),
                                         which deck uses each, the tokens decks need that nobody owns,
                                         and (home's) token cards on order (403 for a space the
                                         viewer may not see)
    POST /api/tokens/save                body {"profile", "space"?, "sha256", "action": "add"|"edit"|"remove",
                                         "base"?, "row"?, "separate"?, "reason"?}: change one row, one
                                         change set (409 + "conflict" and "latest", or + "same_row"
                                         for a card that's already listed)
    GET  /, /app.js, /style.css, ...     the page: only files that exist in decklab/web/
                                         (/?profile=<id>&theme=light|dark preselects, for screenshots)
HEAD works wherever GET does.

Security (PLAN.md part 8 and "Accounts and member collections"): the home
listener has no login, by design, so it must stay on the home network; never
forward its port. Visits from outside come only through the Cloudflare
tunnel (lib/tunnel.py), to a second listener: when config.json has "access"
and the server is on its usual port, it also listens on 127.0.0.1:<access
port> (loopback only, the same exclusive port binding). There, every request
(page, file or API) needs a Cloudflare Access login (the header
Cf-Access-Jwt-Assertion or the cookie CF_Authorization) that lib/access.py
verifies itself (RS256 against the team's keys, aud, iss, exp, nbf) for an
email that belongs to exactly one profile; anything else is 403, and only the
tunnel's host names are accepted. That request then acts as that profile:
Handler.identity (and access.current(), for the code it calls) is
{"profile", "email", "remote": True}, a "profile" in a JSON body or the
query is replaced by the login's, and changing another profile's settings or
wishlist is 403. What that profile may change is checked on every write
route (lib/api/guard.py over lib/permissions.py: 403 with the reason in plain
words otherwise): an admin everything; a member their own space's decks,
collection and tokens (or, for a home member, the home decks Played by them),
their wishlist and settings, and play records with one of their decks;
anyone may run and stop matchups, field runs and tests. Four rules are about
reading: a wishlist is its owner's only (permissions.sees_wishlist), so
GET /api/profiles/<id>/wishlist is 403 for anyone else, an admin included,
and on the home listener too (the viewer the page's chooser names; none
named is 403); the sleeves, deck boxes and playmats are the home's, so a visitor
with their own person space (permissions.sees_accessories) gets 403 from
/api/accessories and /accessory-img/, and every other answer leaves them out
(Sleeves and Deck box lines, kits, the packing plan's sleeves: guard.py lists
where); the inventory is read by space (permissions.sees_inventory): home's
collection and tokens, and the shopping list, orders, checks and receipts that
are home's alone, only by the home profiles, and a person's own collection and
tokens only by that person and an admin, so /api/shopping, /api/receipt (and
its preview and apply), /api/assembly (and its preview), and /api/collection,
/api/collection/rows, /api/tokens, /api/precons/preview and /api/precons/coverage for such a space
answer 403 to anyone else, the collection's "spaces" lists only the ones the
viewer sees, and the printing picker's copy counts (/api/cards/printings,
/api/cards/search with detail) are home's only for the home profiles and a
person's own otherwise; a deck page and the library show a deck's
owned-vs-needed, counts, token chips and table only to those who may see its
space's inventory (the rest of the deck to anyone); and /api/activity shows each viewer only the audit rows its scope
allows (permissions.activity_scope and lib/api/activity.py: an admin, or a
script naming nobody, everything but email addresses and other
people's wishlists; anyone else their own wishlist, their own space's
settings, inventory, deck and play-record rows and the simulations setting;
an accessory row only to whoever sees its owner's, admins too; a wishlist row
only ever to its owner, with a change set's message and reason hidden from
anyone who misses one of its rows), each through its table's allow-list of fields; /api/visits
answers only an admin (or a script naming nobody). Visits are recorded (lib/visits.py) for
the profile a request is from, the login's or the one the chooser names, never for one naming
nobody: its API requests per day, and the pages its page's beacon reports (the route's path and a
deck's id, nothing else). On the home listener identity is None and the page's
chooser names the profile, as before, and that profile has the same rights
there as through the tunnel: a write acts as the body's "profile" with its
own rights (User1 picked at home can't change the home collection or
Matt's decks), and when the X-Deck-Lab-Viewer
header names a profile the body must name the same one (403 "You can only
make changes as yourself"); the three reading rules about accessories,
wishlists and the inventory follow the header's profile (and an accessory
picture's ?viewer=, for an <img> that sends no header). The chooser
offers only home profiles, and a home-listener request naming a profile
outside the home (header, ?profile=, ?viewer= or body "profile") gets 403
"Sign in through decklab.example.com" on every route: members come in
through the tunnel's login, from the home Wi-Fi too. Only a script naming
nobody (code outside any request, or a home-listener request from
loopback, 127.0.0.1 or ::1, that sends X-Deck-Lab-Script: 1; never the
tunnel's listener, though it's on 127.0.0.1 too) may change everything and
sees all the accessories and the inventory; any other request naming
nobody (a phone on the Wi-Fi, the PC's browser before a profile is picked)
sees only what's open to everyone and may change nothing. The page hides what the rules hide and
refuse. The home listener refuses (421) any
request that came through Cloudflare (its Cf-Access-Jwt-Assertion, Cf-Ray or
Cf-Connecting-Ip headers) or names a tunnel host name (even when "access" is
missing or wrong: access.home_refused_hosts), so a tunnel pointed
back at it fails closed instead of handing out its no-login editing. Still,
every path part and
query value is checked, static files come only from an allow-list of what is
in decklab/web/ (so no path can reach another folder, and nothing is listed),
decks are only read through decks.load_deck() and saved through the inventory's
deck operations (slugs only, home's or a person's space), request bodies are
limited (4 KB for settings and wishlist operations, 8 KB for Commander-night notes,
256 KB for the editor, 8 MB for a
collection import's preview; one Content-Length, digits only), a connection whose request body wasn't read is closed after the answer
(so the body can't pass for a second request; up to 1 MB of it is read and
dropped first, for at most 2 seconds, so the client gets the answer rather
than a reset connection), HTTP/0.9 is refused, errors
never include a traceback or a local path (the log gets them), the log writes
control characters as escapes, and a Host header that isn't an IP address,
localhost or this PC's name is refused, so a web page elsewhere can't reach
the server through DNS rebinding. "allowed_hosts" in config.json adds more
names.

Accessory pictures (/accessory-img/) are served only for a file name that
the accessories list names (an id and .jpg, .png or .webp; never SVG), of a row
the viewer may see, from the inventory, whose first bytes match its extension
and whose sha256 starts with the address's v (Cache-Control private, so no
shared cache answers for the owner check), or for a staged picture under
decklab/data/ named by a 32-digit
token that's under an hour old. "Find picture" (POST /api/accessories/fetch)
is the one place the server reaches out to a link a person typed: only
http(s) on the usual ports, only to internet addresses (never the home
network, after every redirect too), no proxies, with time and size limits
(lib/accessory_fetch.py has the rules and the DNS-rebinding risk it accepts).

Writes (every POST and PUT) are also protected against other web pages open
on the same phone (check_write): the body must be sent as application/json
(415 otherwise) with the header "X-Deck-Lab: 1" (403 otherwise). A page on
another site can't send either without a CORS preflight, and the server never
approves one (OPTIONS gets 405 or 404, with no Access-Control headers). An
Origin header, when the browser sends one, must be this server's own
(http://<Host>), and Sec-Fetch-Site, when sent, same-origin (403 otherwise).
Every write also names a profile from config.json (api checks it; through
the tunnel it's always the login's).

The server writes inside decklab/data/ (the image cache, saved practice-hand
and matchup results, and collection import previews for an hour in
decklab/data/collection-imports/), into the database (wishlists, profile
settings, the simulations mode and play records through lib/state/, and the
inventory through lib/inventory/: every space's collection, token cards and
raw imports, the orders, the products with their status (an intact product's
sleeves and deck box too) and the watchlist; each write one change set in the
audit trail, never a git commit), and through the same inventory the decks
(home's and every person's), the accessories list and its pictures: each deck,
accessory, picture or kit change is one change set too, and the deck-table
refresh that follows an inventory write is part of that write's change
(lib/inventory/refresh.py). With the files backend (the tests only: phase 4
deleted its git mode, so config.json's "files" is refused) the inventory is
plain files in a test's magic/ folder, written without commits.
Simulations run in a background thread, one at a time, with at most 20 waiting
(lib/jobs.py, through api.practice.JOBS), and Forge matchups in a runner of
their own, up to 4 at once with at most 10 waiting (api.forge_runs.FORGE_JOBS),
so several phones can't overload the PC. The matchups playing at once share
the server's warm pool of Forge workers (lib/forge/pool.py), which starts with
the server (its workers with the first games), quits its idle workers after
config.json's forge_pool_idle_s (15 minutes), and also plays the command line's
runs (python -m decklab.lib.forge play) through its pool service. When the
server stops, its matchups stop and save first, then the pool's workers quit
(POOL_STOP_WAIT seconds at most); closing the window or a logoff kills them at
once once the matchups have saved.

Every request is logged to stderr (or the log file): time, client, method,
path, status and ms.
"""
import argparse
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    # Run as a script: put the repo root on sys.path so "decklab" imports.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _log_import_crash():
    """Under pythonw, nothing would see a crash while Deck Lab's modules load
    (a git pull that broke one, say), so append it to the default log by hand."""
    try:
        path = Path(__file__).resolve().parent / "data" / "logs" / "server.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", errors="backslashreplace") as file:
            file.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} Deck Lab couldn't start:\n{traceback.format_exc()}")
    except Exception:
        pass


try:
    from decklab.lib import venv
    venv.activate()               # .venv's psycopg on sys.path before anything imports it (never raises)
    from decklab.lib import build
    build.start()                 # freeze provenance before loading the application modules
    from decklab.lib import config, control, server_http, server_run
    # decklab.server.X keeps working for these. The names tests patch (log, make_server,
    # CLOSE_WAIT and the underscore helpers) live only in the module that reads them.
    from decklab.lib.server_http import (  # noqa: F401 (re-exported)
        COORD_WAITING, DRAIN_BYTES, DRAIN_SECONDS, GET, HOME_SUFFIXES, IMAGE_MAX_AGE, JSON_TYPE,
        PAGE_PARAMS, STATIC_FOLDERS, STATIC_NAME_RE, STATIC_TYPES, TUNNEL_ONLY, WEB_DIR, WRITE_HEADER,
        WRITE_SITES, Handler, NotAllowed, Refused, Server, host_allowed, host_name, static_files)
    from decklab.lib.server_run import (  # noqa: F401 (re-exported)
        CTRL_BREAK, CTRL_C, CTRL_CLOSE, CTRL_SHUTDOWN, FORGE_STOP_WAIT, POOL_STOP_WAIT, RETRY_AFTER,
        UPDATE_EVERY, ctrl_handler)
except BaseException:
    if __name__ == "__main__" and sys.stderr is None:
        _log_import_crash()
    raise


def _stop_message(result, port):
    """--stop's answer in plain words (control.request_stop's result)."""
    if result == "stopped":
        return f"Deck Lab (port {port}) has stopped."
    if result == "not running":
        return f"Deck Lab isn't running on port {port}."
    if result == "timeout":
        return (f"Deck Lab (port {port}) was asked to stop, but it's still running after {control.STOP_WAIT} "
                f"seconds. Try again in a minute, or end its pythonw.exe (or python.exe) in Task Manager.")
    if sys.platform.startswith("linux"):
        return (f"Deck Lab on port {port} can't be signalled from here, perhaps because it runs as another user: "
                "stop it as that user, or press Ctrl+C in its terminal.")
    if sys.platform != "win32":
        return "Stopping the server from another window only works on Windows and Linux: press Ctrl+C in its window."
    return (f"Deck Lab on port {port} can't be stopped from here, perhaps because it runs as administrator: "
            f"stop it from an administrator prompt, or end it in Task Manager.")


def _stop(port):
    """--stop: ask the server on port (None: "port" in config.json) to stop
    and wait for it. 0 when it has stopped or wasn't running, else 1. With
    --port, config.json isn't read at all, so a typo in it can't keep the
    running server from being stopped (to fix the typo, say)."""
    if port is None:
        try:
            port = config.load().get("port", 8642)
        except (OSError, ValueError, TypeError) as e:     # JSONDecodeError is a ValueError
            server_http.log(f"decklab/config.json can't be read ({type(e).__name__}: {e}), so the port to stop isn't "
                f"known. Pass it with --port: python decklab/server.py --port 8642 --stop (8642 unless "
                f"config.json sets another)")
            return 1
    # Before the stop, and whether or not one is running: the watchdog then
    # leaves it off even if this stop times out and it's ended another way.
    try:
        control.mark_stopped(port, "server.py --stop")
    except OSError as e:
        server_http.log(f"Can't record the stop in {control.stop_marker_path(port)} ({e}): the watchdog "
                        f"may start Deck Lab again.")
    result = control.request_stop(port)
    print(_stop_message(result, port))
    return 0 if result in ("stopped", "not running") else 1


def _log_to(path, announce):
    """Send stdout and stderr to a rotating log file (control.open_log),
    first saying where on the console when announce."""
    stream = control.open_log(path)
    if announce and sys.stderr is not None:
        sys.stderr.write(f"Deck Lab's log: {path}\n")
        sys.stderr.flush()
    sys.stdout = sys.stderr = stream
    return stream


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="python decklab/server.py", description="Deck Lab's web server.")
    parser.add_argument("--host", help='address to listen on (default: "host" in decklab/config.json, '
                                       'else all interfaces)')
    parser.add_argument("--port", type=int, help='port to listen on, or to stop (default: "port" in '
                                                 'decklab/config.json, else 8642)')
    parser.add_argument("--no-update", action="store_true",
                        help="don't download or rebuild the card data; use the index there is")
    parser.add_argument("--log", metavar="FILE",
                        help="write the log to FILE (rotated at 2 MB, 3 old files kept). Without "
                             "--log, a server with no window (pythonw) logs to decklab/data/logs/server.log")
    parser.add_argument("--background", action="store_true",
                        help="run as the background server, as with no window: log to "
                             "decklab/data/logs/server.log (or --log). The systemd service homenet installs "
                             "on Linux gives it")
    parser.add_argument("--stop", action="store_true",
                        help="stop the Deck Lab server running on the port (as Ctrl+C would), then exit")
    return parser.parse_args(argv)


def main(argv=None):
    """Run the server until it's stopped, or with --stop, stop the one
    running; the exit code. With no console (pythonw) everything said,
    tracebacks included, goes to the log file (control.LOG_FILE, or --log),
    which stays sys.stderr until the process ends; with a console and
    --log, the console's streams come back when main() returns."""
    console = sys.stderr is not None
    saved = sys.stdout, sys.stderr
    stream = None
    if not console:
        # Until the arguments say where, anything said goes to the default log.
        stream = _log_to(control.LOG_FILE, announce=False)
    try:
        args = _parse_args(argv)
        if args.stop:
            return _stop(args.port)
        settings = config.load()
        port = settings.get("port", 8642) if args.port is None else args.port
        background = not console or args.background
        log_path = str(control.LOG_FILE) if background else None
        if args.background and console and not args.log:
            stream = _log_to(control.LOG_FILE, announce=False)
        if args.log:
            if stream is not None:
                stream.close()
            log_path = os.path.abspath(args.log)
            stream = _log_to(log_path, announce=console)
        host = settings.get("host", "0.0.0.0") if args.host is None else args.host
        return server_run._serve(host, port, args.no_update, settings, log_path, background=background)
    except Exception:
        server_http.log(f"{server_run._stamp()} Deck Lab stopped with an error:\n{traceback.format_exc()}")
        return 1
    finally:
        if console and stream is not None:
            sys.stdout, sys.stderr = saved
            stream.close()


if __name__ == "__main__":
    sys.exit(main())
