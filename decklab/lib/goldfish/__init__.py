"""Practice-hand simulation (PLAN.md part 5): deal a deck's opening hand about
100,000 times and play the first turns out alone, with no opponent
("goldfishing"), by simple fixed rules. Counting what happens says how often
the deck mulligans, misses land drops, gets stuck or floods, lacks a colour,
uses its mana, and when its first 4-drop comes down.

Usage (from the repo root):
    python -m decklab.lib.goldfish casual/gruul-ramp       a summary of one deck
        [--owned]          the deck file's owned-only list instead of the target list
        [--games N] [--turns N] [--seed N] [--workers N]
        [--json]           the whole result as JSON
        [--no-cache]       simulate again even when a saved result exists
    python -m decklab.lib.goldfish --all [--halves] [--pairings]
                           headline numbers for every deck (and the Beginner Box)

From code:

    from decklab.lib import decks, goldfish
    sections = decks.load_deck("casual/gruul-ramp")
    result = goldfish.get_or_simulate(sections, "constructed")   # saved in data/goldfish/
    result = goldfish.simulate(sections, "commander", games=20_000, seed=7, workers=1)
    key = goldfish.cache_key(sections, "constructed")
    goldfish.saved_result(key)      # the saved result, or None: never simulates
    goldfish.headline(result)       # the few numbers a deck list shows

sections is {section: [decks.DeckLine]}, as decks.load_deck() returns it, and
kind is "commander" or "constructed", as for stats.deck_stats(). The deck is
the Commander and Deck sections; the sideboard and companions aren't used.
Cards are read through stats' helpers in lib/stats/cardtext.py (lands, mana
creatures and rocks, land searches, spell // land cards, which lands enter
untapped), so the page's stats and this simulation read a card the same way.
The result holds only dicts, lists, strings, numbers, booleans and None, so it
goes straight to JSON.

Setups (who goes first, and the Comprehensive Rules that differ)
    "play"   a two-player game where you go first: no draw on turn 1 (CR 103.8a).
    "draw"   a two-player game where you go second: you draw on turn 1.
    "multiplayer"  Commander decks only: a game of 3 or more players, like the
             shop's Commander nights. The first mulligan is free (CR 103.5c,
             800.6) and nobody skips the turn-1 draw (CR 103.8c, 800.7).
    A 1v1 Commander game is a two-player game (CR 100.1a, 903.2), so it gets
    neither: a Commander deck's "play" and "draw" results are 1v1 games.

Rules the simulated player follows (RULES has the same in plain words)
    Mulligans: the London mulligan (CR 103.5). Every hand is 7 cards; after
    your k-th mulligan you put k of them on the bottom. Keep rules are Frank
    Karsten's (his 2022 simulation code; its 7-card rule is PLAN.md's "keep
    2-5 lands"): keep 7 cards with 2-5 lands, 6 or 5 cards (after bottoming)
    with 2-4 lands, and always keep 4. A free first 7 in multiplayer is kept
    only with 3-5 lands, since throwing it back costs nothing (his Commander
    rule). Spell // land cards count as lands here. Bottoming is his too:
    put lands on the bottom while you have more than 3, then spells, most
    expensive first. The land that goes is the one that helps least: one
    whose colours your other lands in hand make too (so the hand's only
    source of a colour your spells need stays, then its only source of a
    colour the deck needs, like a splash), then one making none of the
    colours your spells need, then one that enters tapped.
    We use his 3-land target rather than the deck's land share (2.4 of 6
    cards for 24 lands in 60) so the numbers can be checked against his.

    Each turn: untap, draw (not on turn 1 on the play), play a land, then
    cast spells.
    - Land: if you have one, play the land that lets you spend the most mana
      this turn; on a tie, the one adding a colour your spells need and your
      permanents don't make yet; then one that enters tapped (saving
      untapped ones for later turns); then one that makes mana this turn
      (Temple of the False God makes none until you have 5 lands); then one
      adding a colour the deck needs that your permanents don't make yet
      (so a second Forest doesn't go down while a first Mountain waits);
      then the one making more colours. A spell // land card is played as
      a land only when there's no other land in hand; otherwise it's a
      spell.
    - Tapped lands: stats.untapped_on_turn_one() decides which lands can
      enter untapped (a shock land pays 2 life). For lands whose condition
      depends on the game, the condition is checked when the land is played:
      check lands (you control a Mountain or a Forest), battle lands (two or
      more basic lands), reveal lands (a matching card in hand), fast lands
      (two or fewer other lands), slow lands (two or more other lands), and
      "three or more other Swamps". In multiplayer, "two or more opponents"
      lands enter untapped. Every other land stats says can't enter
      untapped on turn 1 always enters tapped.
    - A land with a free search is sacrificed at once for the land it finds
      (the one that helps most, as for a chosen colour below), which
      enters as its text says (stats.land_search()): tapped for
      Evolving Wilds, untapped for Prismatic Vista and Polluted Delta, and
      for Fabled Passage untapped once you control 4 or more lands; but a
      land whose own text says it enters tapped (a Triome) enters tapped.
      A land whose search costs mana (Myriad Landscape) doesn't search:
      it's a tapped land making {C}.
    - A bounce land (Azorius Chancery) returns a land you control to your
      hand as it enters, and Lotus Field sacrifices two: it's played only
      when you have those lands, and they're your least useful ones, taken
      after their mana is used that turn; one that must return an untapped
      land (Coral Atoll) can't use that land's mana first. A returned land
      is played again later.
    - A land or mana rock whose colour is chosen as it enters (Uncharted
      Haven, Heraldic Banner), and a land with a land on both faces (a
      Pathway, played as either face), makes the colour that helps most
      then. For an untapped land, that's first the one that lets you spend
      the most mana this turn. Then: the colour most of your spells need
      that neither your permanents nor the other lands in your hand make
      (those come down later), then one the deck needs that they don't
      make, then the same with your permanents alone (_best_colour); an
      exact tie goes at random, so no colour is favoured. In a Commander
      deck it's one of the commander's colours.
    - A land with a basic land type makes that type's colour too (CR
      305.6; Murmuring Bosk, a Forest). River of Tears ({B} on a turn
      you've played a land, else {U}) counts as either colour.
    - Spells: cast the most expensive spell (by mana value) you can pay for,
      then the most expensive that still fits, and so on until nothing else
      fits (Karsten's rule in his mana curve code). On a tie, a card that
      makes mana this turn goes first, then another mana producer or ramp.
      The commander starts in the command zone and is cast like a spell in
      hand whenever it fits, at most once (commander tax is ignored).
    - Paying: an exact check that each coloured symbol gets its own source
      that makes that colour, with generic mana paid by anything left
      (matching, via Hall's theorem). All the spells cast in a turn are
      checked together, so paying for one never strands another. When a
      rock cast this turn makes mana for later spells, what's been cast so
      far is paid for then, in whichever way lets the most be cast after it
      by the same rule (the most expensive first, as above; that rule
      itself is greedy, so very rarely a turn with several rocks casts a
      little less than it could). Hybrid
      symbols take either colour; {2/W} takes {W} or two generic; Phyrexian
      symbols are paid with 2 life; {C} needs colourless mana; {S} is paid
      as generic. X is 0, unless X = 0 would do nothing ("deals X damage",
      "loses X life", "draw X cards", "X +1/+1 counters" and the like): then
      1. Extra mana is never put into X.
    - Mana creatures make mana from the turn after they're cast (summoning
      sickness), or at once with haste; mana rocks from the turn they're
      cast (artifacts have no summoning sickness) unless they enter tapped.
      A mana ability that costs mana too (a Signet's "{1}, {T}: Add {W}{B}")
      counts as the mana it adds beyond that cost (one more mana, of either
      colour), and on the turn it's cast only when there's mana left to pay
      for it. A rock that doesn't untap by itself (Basalt Monolith) and
      mana from charge counters (Everflowing Chalice, cast for {0}) aren't
      counted, nor is a mana ability whose cost asks for more than {T},
      mana and life (Lotus Petal's sacrifice, Springleaf Drum's other
      creature, Sphere of the Suns' counters), or one a card gives other
      permanents (Goldspan Dragon's Treasures). "Add one mana ... for each
      ..." and "Add X mana ..., where X is ..." count as one mana (X is at
      least the creature's own power for "the greatest power among
      creatures you control"); limits on what the mana can be spent on
      (Giada) are ignored; "your commander's colour identity" means no mana
      in a deck without a commander. An aura that makes its land tap for
      more (New Horizons) is one extra mana of any colour from the next
      turn.
    - Land-search ramp (Rampant Growth, Cultivate, Sakura-Tribe Elder):
      puts a basic land (or the land its text allows) onto the battlefield
      tapped, choosing the one that helps most as for a chosen colour
      (above), then shuffles. "Up to two" gets two; Cultivate's second land
      goes to your hand. This is a simplification: a land put in untapped
      (Grow from the Ashes) is tapped here too, and kickers are ignored. A
      search that's an activated ability is used as soon as it can be: at
      once when it costs no mana (the Elder is sacrificed straight away),
      otherwise with mana left over after spells (Wayfarer's Bauble). A
      search that sacrifices a land (Springbloom Druid) sacrifices your
      least useful land. A search that depends on an opponent (Claim Jumper)
      or that another trigger starts (Ordeal of Nylea's, when it's
      sacrificed) never happens.
    - Not modelled: card draw and card selection (the cards are cast but
      draw nothing; searches for cards that aren't lands, cycling),
      Treasure, cost reductions (convoke, affinity, improvise, delve and
      emerge too: the full mana cost is paid), other activated abilities,
      combat and life totals. A name that isn't a Scryfall card takes a
      place in the library but is never played.

Metrics (for each setup; DEFINITIONS has the page's wording). "After the
land drop" is the start of the main phase, before any spell is cast.
    mulligans   rate: share of games with at least one mulligan (the free
                one included); free_rate: share that took the free one
                (multiplayer only); kept: share of kept hands of 7, 6, 5, 4.
    land_drops  on_time: chance you've played a land from your hand on each
                of turns 1..N, i.e. your Nth land by turn N (a spell // land
                card played as a land counts; lands put in by ramp don't).
                mana: chance of at least N mana on turn N after the land
                drop, and the average: every land (one that entered tapped
                this turn too, so playing a tapped land when nothing needs
                the mana isn't counted against you), plus mana creatures,
                rocks and aura mana that can make mana this turn.
    stuck       games: share of games that, on turn 2, 3 or 4, had no land
                to play and held a spell that one more untapped land of any
                colour would have paid for; missed_drops: average number of
                turns among 1-6 with no land drop.
    flood       turns: share of turns 4-8 where, after the land drop, your
                hand held no spell at all (only lands, or nothing) and no
                commander was waiting; games: share of games with 3 or more.
    colours     by_turn: for each colour the deck's costs need, the chance
                of a source of it on turns 1-5, counted like mana. A hybrid
                symbol (or a split card's halves) needs its colours only
                when no other card needs one of them; {2/W} needs white
                only when the deck makes white (paying {W} is then the
                cheapest way), and Phyrexian symbols need none.
                screw_turns: share of all turns where, after the land
                drop, a spell in hand (or the
                waiting commander) cost no more mana than you could make
                (its cheapest cost in colours the deck makes: {2/W} in a
                deck with no white is 2) but its colours couldn't be paid
                (you may have cast something else); screw_wasted_turns:
                those turns where you also left mana unspent.
    mana_used   mana spent / mana you could make (usable lands and sources
                after the land drop, plus mana from rocks cast this turn),
                per turn and over all turns; all_used: share of turns with
                any mana where you spent all of it.
    first_big   the turn the first spell of mana value 4 or more is cast
                (including the commander, X at its minimum), the share of
                games never casting one, its average turn over the games
                that cast one, and the chance it's on turn 4 or earlier. A
                deck with none gets in_deck 0, a note and None for the rest.

Checked against Frank Karsten's rules (2026-09-29)
    For decks of lands and blank spells, the chances of hitting land drops
    on turns 2-6, the mulligan rate and the expected hand size match an exact
    (not simulated) calculation of Karsten's 2022 rules to within 0.3
    percentage points at 100,000 games: 40 cards with 17 lands, 60 with 20,
    24 and 26, and 99 with 36-41, multiplayer and 1v1. The Milestone 3
    research built that calculator and checked it against his published 2017
    land-drop table (karsten-land-drops) and his 2022 colour tables.

Speed and repeatability
    The games are split into fixed chunks of CHUNK_GAMES games, each with its
    own random generator seeded from (seed, setup, chunk number), and the
    chunks' integer counts are added up. So the same deck, settings and seed
    always give identical results, whatever the number of worker processes
    (config "goldfish_workers", default one per core up to 16). Without a
    seed, the seed comes from a hash of the decklist, so reloading the page
    gives the same numbers. Workers are spawned processes (safe on Windows);
    workers=1 runs everything in this process. Workers ignore Ctrl+C (on
    Windows from the moment they start, in a process group of their own:
    _NewProcessGroups): the server stops the run instead (its progress
    callback raises), and a run that fails or is stopped drops the chunks it
    hasn't started. A worker ends by itself if the process that started it
    is killed. On this PC (16 cores),
    100,000 games per setup of 8 turns take about 1 second for a 60-card
    deck and 1.5 seconds for a Commander deck (three setups).
    get_or_simulate() saves each result in decklab/data/goldfish/, keyed by
    a hash of the main deck and commander, the cards as the simulation reads
    them, the kind, games, turns, seed, the mulligan switch and
    GOLDFISH_VERSION.

Result (every key is always there; None where it doesn't apply)
    version, kind, games (per setup), turns, seed, seed_source ("given" or
    "decklist"), mulligans (bool), workers, seconds, chunks
    deck        {"cards", "lands", "spell_lands", "commanders": [name]}
    setups      [{"id", "label", "text"}] in the order results are shown
    results     {setup id: {"id", "label", "mulligans", "land_drops",
                "stuck", "flood", "colours", "mana_used", "first_big"}},
                each as above; chances are fractions from 0 to 1, to 6
                places (one that isn't exactly 0 or 1 is never rounded to
                0 or 1)
    cards       {"special": [{"name", "qty", "rule"}], "not_modelled":
                [{"name", "qty", "what"}], "unresolved": [{"name", "qty",
                "section"}]}; sorted by name
    rules       [str]: RULES, the rules above in plain words for the page
    definitions {metric: str}: DEFINITIONS
    warnings    [str]; sources {source id: {"title", "date", "url"}}
    cache_key, cached (bool: it came from the saved results) and saved
    (bool: it's in them) are added by get_or_simulate(), and cached and
    saved by saved_result(). A result that can't be saved (the data folder
    can't be written) is still returned, with saved False and a warning.
"""
# Where things are (each module's docstring says more):
#   common.py   the shared rules and constants: setups, keep rules, colour
#               masks, how a land enters, SOURCES, RULES and DEFINITIONS
#   model.py    card reading: compile_deck() turns a deck into plain data
#   engine.py   the game loop: _Engine and _play_games()
#   workers.py  worker processes: _run_chunk() and _start_worker()
#   results.py  a run's counts as the result, and headline()
#   runs.py     simulate(), get_or_simulate(), cache_key(), saved_result()
#               and the saved results in decklab/data/goldfish/
#   cli.py      the command line, main() (__main__.py runs it)
# Every name goldfish.py had can still be read here as goldfish.<name>. The
# names in _PATCHED, which tests patch, are defined only in the module whose
# code reads them: goldfish.<name> passes reads on to it, but setting one here
# raises, since it wouldn't reach that code. Patch goldfish.runs.<name> (or
# goldfish.cli._main) instead.
import sys
import types

# Every module, at import: each binds the real stats module before a test
# swaps it (test_api.py's Sandbox).
from . import cli, common, engine, model, results, runs, workers
from .common import (ALWAYS_KEEP, ANY_MANA, BIG_SPELL, BITS, BOTTOM_LANDS_ABOVE, COLOUR_ORDER, COLOUR_TURNS,
                     COMMANDER_1V1_NOTE, DEFINITIONS, FLOOD_FROM_TURN, FLOOD_GAME_TURNS, FREE_KEEP_LANDS, IF_BASICS,
                     IF_EARLY, IF_FEW, IF_MANY, IF_MANY_TYPE, IF_MULTIPLAYER, IF_REVEAL, IF_TYPE, KEEP_LANDS,
                     LAND_TYPE_BITS, LAND_TYPE_RE, MISSED_DROP_TURNS, POP, RULES, SETUPS, SETUPS_BY_KIND, SOURCES,
                     STUCK_TURNS, TAPPED, UNTAPPED, _colour_bits, _colours_text, _mask)
from .model import (AURA_RAMP_RE, BASICS_RE, CHECK_RE, COST_KEYWORDS, COST_REDUCTION_RE, EARLY_RE, FEW_LANDS_RE,
                    FROM_TOP_RE, KINDS, MANY_LANDS_RE, MANY_TYPE_RE, MIN_LANDS_RE, MIN_LIBRARY, NO_UNTAP_RE,
                    OPPONENT_SEARCH_RE, PAY_LIFE_RE, PLAYED_LAND_INSTEAD_RE, RETURN_LAND_RE, RETURN_OWN_LANDS_RE,
                    REVEAL_RE, SACRIFICE_LANDS_RE, SPEND_LIMIT_RE, TREASURE_RE, TRIGGER_RE, UNTAP_FOUND_RE,
                    X_NEEDS_ONE_RE, _as_it_arrives, _card_model, _chosen_text, _clause_colours, _cost_options,
                    _effect, _either_face, _enter_rule, _enter_text, _found_text, _land_model, _mana_output,
                    _needed_colours, _number, _search_spec, _type_bits, _type_names, _x_minimum, compile_deck)
from .engine import (_Engine, _add_counts, _best_colour, _bottom, _can_enter, _cast, _cast_order_key, _choose,
                     _colour_rank, _deal, _enters_untapped, _hall_table, _keeps, _land_enters, _later_colours,
                     _leftover, _leftovers, _new_counts, _payable, _pick, _plan, _play_games, _ramp, _ranked_choices,
                     _search, _source_mask, _takes)
from .workers import (CREATE_NEW_PROCESS_GROUP, _ENGINES, _GroupWinapi, _NewProcessGroups, _SPAWN_LOCK, _exit_with,
                      _run_chunk, _start_worker)
from .results import SHARE_DIGITS, _average, _share, _summary, headline
from .runs import (DEFAULT_GAMES, DEFAULT_TURNS, MAX_GAMES, MAX_TURNS, _check_settings, _chunk_seed, _deck_key,
                   _digest, _prepare, _prune, _save, _setup_text, cache_key, saved_result)
from .cli import _pct, _print_summary, main

_PATCHED = {
    "_main": cli,
    "CACHE_DIR": runs,
    "CACHE_MAX_FILES": runs,
    "CHUNK_GAMES": runs,
    "GOLDFISH_VERSION": runs,
    "_log": runs,
    "default_workers": runs,
    "get_or_simulate": runs,
    "simulate": runs,
}


def __getattr__(name):
    if name in _PATCHED:
        return getattr(_PATCHED[name], name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _Facade(types.ModuleType):
    """This package's module type: setting or deleting a name in _PATCHED
    raises, rather than changing a copy no code reads."""

    def __setattr__(self, name, value):
        if name in _PATCHED:
            raise AttributeError(f"{name} belongs to {_PATCHED[name].__name__}: set or patch it there")
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if name in _PATCHED:
            raise AttributeError(f"{name} belongs to {_PATCHED[name].__name__}: set or patch it there")
        super().__delattr__(name)


sys.modules[__name__].__class__ = _Facade
