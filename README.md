# Deck Lab

Deck Lab is a self-hosted web app for a household's Magic: The Gathering cards. It keeps the collection, decks, orders and deliveries, sleeves and deck boxes, token cards and wishlists in PostgreSQL, and it plays decks against each other thousands of times with [Forge](https://github.com/Card-Forge/forge)'s computer players to show how a deck does against the rest of its format.

It runs on one Windows PC and is used from phones, tablets and the PC's browser on the home network. Members sign in from outside through a Cloudflare Tunnel behind Cloudflare Access, and each person's collection, decks and games stay private to their own space.

## What's in it

- **Decks:** a library, a deck page with stats, an editor that tests a change on the deck's own games before saving, and every saved revision.
- **Collection and buying:** owned vs needed for every deck (counting cards held in other built decks), a purchase queue, orders, and deliveries checked in part by part.
- **Simulations:** matchups and whole-field runs played by a fork of Forge, with ratings and confidence ranges, and practice hands that test a deck's mana over 100,000 simulated draws.
- **Privacy and roles:** spaces, admin and member roles, and an audit trail of every change, checked on the server for every request.

## Where to read more

- [decklab/README.md](decklab/README.md): how to run it, set it up and use every part.
- [decklab/PLAN.md](decklab/PLAN.md) and [TODO.md](TODO.md): what's still to do.
- [decklab/HISTORY.md](decklab/HISTORY.md): what was built, and why.
- [decklab/design/](decklab/design/): personas, journeys, user stories and the gap analysis.
- [AGENTS.md](AGENTS.md): the working rules for AI coding assistants on this repo.

## Setup in short

Deck Lab needs Python 3.14, PostgreSQL, a JDK and a Forge build (decklab/README.md, "Deck Lab's own Forge"). Copy `decklab/config.example.json` to `decklab/config.json` and fill in your own profiles; that file is gitignored, so real names and email addresses never enter the repo. A household's own buylists and reports (`magic/buylists/`, `magic/reports/`, which orders' and the watchlist's `source` fields name) live in a private repo of its own: set `records_repo` to that checkout's folder. The people and decks named in the docs and tests are made up.

## Licence and credits

Deck Lab is licensed under the [GNU General Public License v3.0](LICENSE). Parts of it (the Java in `decklab/lib/forge/java` and the card-script overrides in `decklab/lib/forge/overrides`) are built into Forge, which is GPL-3.0 too.

- Card data and images come from the [Scryfall API](https://scryfall.com/docs/api). Deck Lab is not produced by or endorsed by Scryfall.
- Simulations use [Forge](https://github.com/Card-Forge/forge), a free Magic rules engine.
- Fonts: Figtree and JetBrains Mono, under the SIL Open Font License (`decklab/fonts-licences/`).

Deck Lab is unofficial Fan Content permitted under the Fan Content Policy. Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.
