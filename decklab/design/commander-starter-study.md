# Commander starter picks from public precons

On 2026-11-20 we gave the starter five published commanders and competing pools, then counted chosen spells that directly advance a printed commander ability. The study calls the production builder with one free copy of each eligible candidate, zero locks, the production role categories and denial tags, and no cached EDHREC affinity. This exercises the fallback used when the commander has no cached recommendations.

## Inputs and scoring

Each pool contains the commander's printed main board and roughly half the other four main boards' distinct additional names. The low bit of the first SHA-256 byte of each additional name assigns it to A or B. The two pools therefore share the original deck and have disjoint competing cards. Only Commander-legal cards in the commander's identity qualify. The builder supplies ordinary basics. The evaluator skips prohibited automatic picks and counts only nonlands outside the command zone. Source-deck membership carries zero scoring weight. The five precons provide 78–141 eligible spells per pool for 61 picks.

| Deck and release date | Direct contribution measured |
| --- | --- |
| [Temur Roar, 2025-04-11](https://magic.wizards.com/en/news/announcements/tarkir-dragonstorm-commander-decklists#Temur) | Eshki draws for casting a creature spell with power at least four. Count front-face creatures with a numeric printed power of four or more. Variable power and other enablers are outside this count. |
| [Prismari Artistry, 2026-04-24](https://magic.wizards.com/en/news/announcements/secrets-of-strixhaven-commander-decklists) | Rootha makes a token after a turn in which its controller cast an instant or sorcery before combat. Count front-face instants and sorceries. This measures access to the trigger, without estimating cast timing or token size. |
| [Keen Engineering, 2026-10-02](https://magic.wizards.com/en/news/announcements/foundations-commander-decklists) | Casting an artifact spell triggers Sai. Count front-face artifact spells. Other cards that reward artifacts can also be good support. |
| [Sultai Arisen, 2025-04-11](https://magic.wizards.com/en/news/announcements/tarkir-dragonstorm-commander-decklists#Sultai) | Count a fixed, manually reviewed set of cards that can move cards out of their controller's graveyard. The script's 24 named examples were checked against the cached Scryfall Oracle text. They include a creature returning itself, flashback, delve, and cards returning other cards to hand or the battlefield. Dauthi Voidwalker is in the precon but its replacement effect applies to opponents. Self-mill alone also earns zero credit. This is a sample of positive examples. |
| [Eternal Might, 2025-02-14](https://magic.wizards.com/en/news/announcements/aetherdrift-commander-decklists) | Temmet pumps Zombies when its controller draws. Count front-face Zombie creatures. Spells that make Zombies can contribute equally during play and are reviewed separately below. |

## Results

Each cell gives the A and B results in that order. The first two pick columns count direct contributions among the 61 chosen spells per list. The role deficit sums shortages against the template. An overlapping role card can satisfy two categories.

| Commander | Direct candidates A/B | Baseline picks A/B | Revised picks A/B | Role deficit, both revisions A/B | Mana value 5+ baseline → revised A/B |
| --- | ---: | ---: | ---: | ---: | ---: |
| Eshki | 28 / 33 | 5 / 8 | 20 / 20 | 0 / 1 | 12 / 12 → 13 / 13 |
| Rootha | 40 / 33 | 20 / 19 | 34 / 30 | 0 / 2 | 12 / 12 → 13 / 13 |
| Sai | 52 / 45 | 40 / 40 | 47 / 41 | 2 / 3 | 13 / 13 → 13 / 13 |
| Teval | 24 / 22 | 8 / 9 | 20 / 18 | 1 / 1 | 12 / 15 → 13 / 13 |
| Temmet | 28 / 29 | 28 / 29 | 28 / 26 | 0 / 0 | 14 / 16 → 12 / 13 |

All ten lists reached 100 cards including the commander. With Eshki the baseline passed Thunderbreak Regent in both pools. With Teval it passed Reassembling Skeleton and Meren of Clan Nel Toth in both. The revised lists for Eshki included two and five qualifying creatures drawn from other precons.

Temmet kept every printed Zombie in A. In B it retained Gempalm Polluter, whose two-mana cycling draws a card and triggers the commander, and passed God-Eternal Oketra, Rot Hulk and Twisted Abomination. A secondary review counted six named noncreature cards that can make Zombie tokens or amass Zombies for their controller, including Dread Summons and Dreadhorde Invasion. Of the five available in A and six in B, the baseline chose two in each pool. The revised lists chose all five and all six respectively. These are additional ways for Temmet to build an attacking board. The counts do not estimate the number of tokens made in a game.

A separate focused regression gives Sai a removal-tagged Energy Flux, an artifact spell and plentiful creatures sharing Sai's types. The builder selects the artifact and passes Energy Flux, whose upkeep tax affects its own artifacts. The same check verifies an explicit lock is respected and a sparse pool can still select the card with a tax explanation. Other cases check that a restricted spell trigger gets no blanket claim for a board wipe and that an opponent-only graveyard effect earns no own-graveyard reason. These fixtures exercise specific rules interactions outside the ten-list comparison. Neither evaluation measures win rate or whole-deck power. [Commander starter regressions](../tests/test_commander_draft.py)

## Repeating the study

From the repository root run `python -m scripts.study_commander_starters`, optionally with `--details` to print the passed direct cards and other picks. It reads only five public deck files, the card index and Oracle tags. It needs no server or database. The command does not download anything.

For an empty checkout, the following optional PowerShell commands fetch only the five MTGJSON deck files and Scryfall's two public bulk inputs, then build the local index. The card and tag downloads are large. Skip the second block when the existing index and tags are available.

```powershell
$deckDirectory = 'decklab/data/mtgjson/decks'
New-Item -ItemType Directory -Force -Path $deckDirectory | Out-Null
foreach ($deck in 'TemurRoar_TDC','PrismariArtistry_SOC','KeenEngineering_FDC','SultaiArisen_TDC','EternalMight_DRC') {
    $path = Join-Path $deckDirectory "$deck.json"
    if (-not (Test-Path -LiteralPath $path)) {
        Invoke-WebRequest "https://mtgjson.com/api/v5/decks/$deck.json" -OutFile $path
    }
}
```

```powershell
python -c "from decklab.lib import cards as c; c.download_bulk(); c.write_index(c.build_index(c.bulk_path('default_cards'), c.bulk_path('oracle_tags')))"
```

The fixed baseline was measured with the builder at `9ced571`. The five MTGJSON files were version `5.3.0+20261101`. The indexed Scryfall default cards and Oracle tags were published on 2026-10-26 at 21:05:59 and 21:00:32 UTC respectively. The script fingerprints the deck membership, commander names, Oracle-level card metadata and mass-land-denial membership. Both measured builds used SHA-256 `a271a8bf431fef67f0372b7928646fb7dca9b4289805c534901f74378b0ea4aa`. Newly downloaded inputs can produce different numbers. To repeat the historical baseline, run this same study module in a checkout of that revision with the matching public caches.
