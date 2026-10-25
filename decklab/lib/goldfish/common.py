"""The goldfish package's shared rules and constants: the setups (play, draw,
multiplayer), the keep and bottoming rules, the turns each metric looks at,
colour bit masks, how a land enters, the sources, and RULES and DEFINITIONS
(the page's plain-word texts). Card reading (model.py), the game loop
(engine.py), the results (results.py) and runs (runs.py) all use them.
"""
from decklab.lib import stats

SOURCES = {
    "comp-rules": {
        "title": "Magic: The Gathering Comprehensive Rules: 100.1a-b, 103.5, 103.5c, 103.8a, 103.8c, "
                 "800.6, 800.7, 903.2",
        "date": "effective 2026-09-25; downloaded 2026-09-29",
        "url": "https://media.wizards.com/2026/downloads/MagicCompRules%2020260925.txt"},
    "karsten-sources": dict(stats.SOURCES["karsten-sources"]),
    "karsten-code": {
        "title": "Frank Karsten's simulation code for his 2022 colour tables (HowManySources2022Update.py): "
                 "the keep and bottoming rules",
        "date": "2022; read 2026-09-29",
        "url": "https://github.com/frankkarsten/MTG-Math/blob/master/HowManySources2022Update.py"},
    "karsten-commander": dict(stats.SOURCES["karsten-commander"]),
    "karsten-curve": {
        "title": "Frank Karsten's optimal mana curve code (OptimalManaCurve.py): play a land, then the "
                 "most expensive spell you can afford",
        "date": "2020-05-27; read 2026-09-29",
        "url": "https://github.com/frankkarsten/MTG-Math/blob/master/OptimalManaCurve.py"},
    "karsten-land-drops": {
        "title": "How Many Lands Do You Need to Consistently Hit Your Land Drops? (Frank Karsten)",
        "date": "2017-05-30 (third-party copy of the ChannelFireball article); read 2026-09-29",
        "url": "https://orkerhulen.dk/onewebmedia/How%20Many%20Lands%20Do%20You%20Need%20to%20"
               "Consistently%20Hit%20Your%20Land%20Drops.pdf"},
    "edhrec-mulligans": {
        "title": "The EDHREC Guide to Mulligans in Commander (John Sherwood)",
        "date": "undated; read 2026-09-29",
        "url": "https://edhrec.com/guides/the-edhrec-guide-to-mulligans-in-commander"},
}

# ------------------------------------------------------------------ setups
# CR 103.8a: in a two-player game the starting player skips their first
# draw. CR 103.5c / 800.6: in a multiplayer game (100.1b: one that begins
# with more than two players) the first mulligan is free; CR 103.8c / 800.7:
# nobody skips the turn-1 draw. A Commander game may be either (903.2).
SETUPS = {
    "play": {"label": "On the play", "draw_first": False, "free_mulligan": False,
             "text": "A two-player game where you go first, so you don't draw on turn 1 (CR 103.8a)."},
    "draw": {"label": "On the draw", "draw_first": True, "free_mulligan": False,
             "text": "A two-player game where you go second and draw on turn 1."},
    "multiplayer": {"label": "Multiplayer", "draw_first": True, "free_mulligan": True,
                    "text": "A game of 3 or more players, like the shop's Commander nights: the first "
                            "mulligan is free (CR 103.5c) and nobody skips the turn-1 draw (CR 103.8c), "
                            "so every seat plays the same."},
}
SETUPS_BY_KIND = {"constructed": ("play", "draw"), "commander": ("multiplayer", "play", "draw")}
COMMANDER_1V1_NOTE = ("For a Commander deck, On the play and On the draw are 1v1 games: a two-player "
                      "game has no free mulligan (CR 100.1a, 103.5c, 903.2).")

# ------------------------------------------------------------ keep rules
# karsten-code: keep 7 with 2-5 lands (PLAN.md's rule); 6 or 5 cards, after
# bottoming, with 2-4; always keep 4. The free 7 of multiplayer Commander is
# kept with 3-5 lands (karsten-sources, karsten-commander). Bottoming puts
# lands on the bottom while there are more than 3, then spells.
KEEP_LANDS = {7: (2, 5), 6: (2, 4), 5: (2, 4)}      # hand size -> (fewest, most) lands kept
FREE_KEEP_LANDS = (3, 5)
ALWAYS_KEEP = 4                                     # this many cards or fewer: keep
BOTTOM_LANDS_ABOVE = 3

BIG_SPELL = 4                                       # "first 4-drop": mana value 4 or more
FLOOD_FROM_TURN = 4
FLOOD_GAME_TURNS = 3                                # a flooded game: this many flood turns or more
STUCK_TURNS = (2, 3, 4)
MISSED_DROP_TURNS = 6
COLOUR_TURNS = 5

# ------------------------------------------------------------------ mana
BITS = {"W": 1, "U": 2, "B": 4, "R": 8, "G": 16, "C": 32}
COLOUR_ORDER = "WUBRGC"
ANY_MANA = 63
POP = [bin(m).count("1") for m in range(64)]
LAND_TYPE_BITS = {"plains": 1, "island": 2, "swamp": 4, "mountain": 8, "forest": 16}   # the basic's colour
LAND_TYPE_RE = "(plains|island|swamp|mountain|forest)"

# How a land enters (codes for _Engine.LRULE; the first two need nothing more).
UNTAPPED, TAPPED, IF_TYPE, IF_BASICS, IF_FEW, IF_MANY, IF_MANY_TYPE, IF_REVEAL, IF_EARLY, \
    IF_MULTIPLAYER = range(10)

RULES = (
    "Mulligans follow the London rule (CR 103.5): every hand is 7 cards, and after your k-th "
    "mulligan you put k of them on the bottom.",
    "Keep rules are Frank Karsten's: keep 7 cards with 2 to 5 lands, keep 6 or 5 cards (after "
    "bottoming) with 2 to 4 lands, and always keep 4. Spell // land cards count as lands here.",
    "In a multiplayer game the first mulligan is free, so the first 7 is kept only with 3 to 5 lands "
    "(Karsten's Commander rule).",
    "Putting cards on the bottom: lands while you have more than 3, then spells, most expensive "
    "first. The land that goes is the one that helps least: not your hand's only source of a colour your "
    "spells or deck need, then one making none of the colours your spells need, then one that enters "
    "tapped.",
    "Each turn: untap, draw (not on turn 1 on the play), play a land, then cast spells. There's no "
    "opponent, no combat and no life total.",
    "The land played is the one that lets you spend the most mana this turn; on a tie, one adding a "
    "colour you need and don't have yet; then one that enters tapped, saving untapped ones for later.",
    "A spell // land card is played as a land only when there's no other land in hand.",
    "Lands enter tapped as Deck Lab's stats read them. Check lands, battle lands, reveal lands, fast "
    "and slow lands enter untapped when their condition is met at the time; a shock land pays 2 life.",
    "Otherwise the land played is one that makes mana this turn, then one adding a colour the deck needs "
    "and you don't have yet.",
    "Evolving Wilds and similar lands are sacrificed at once for the land they find, which enters tapped "
    "or untapped as the cards say. Myriad Landscape's search, which costs mana, isn't used.",
    "A bounce land (Azorius Chancery) is only played when you have another land for it to return to your "
    "hand, and returns the least useful one after using its mana (Coral Atoll, which needs an untapped "
    "one, can't use it first); Lotus Field likewise sacrifices two.",
    "A land or mana rock whose colour is chosen as it enters (Uncharted Haven, Heraldic Banner), or a land "
    "with a land on both faces (a Pathway), makes the colour you need most at that moment: for an untapped "
    "land, the one that lets you spend the most mana; then the colour most of your spells need that neither "
    "your permanents nor the other lands in your hand make; then one the deck needs that they don't make; "
    "an exact tie goes at random.",
    "Spells: cast the most expensive spell you can pay for, then the most expensive that still fits, "
    "until nothing else fits. The commander starts in the command zone and is cast like a spell in "
    "hand when it fits (commander tax ignored).",
    "Paying checks colours exactly: each coloured symbol needs its own source of that colour; hybrid "
    "symbols take either colour, Phyrexian ones are paid with life. X is 0 unless the card would do "
    "nothing with X = 0 (then 1); spare mana isn't put into X.",
    "Mana creatures make mana from the turn after they're cast (at once with haste); mana rocks from "
    "the turn they're cast, unless they enter tapped. 'For each' mana abilities count as one mana.",
    "A rock whose ability costs mana too (a Signet: pay {1} for {W}{B}) counts as one more mana, and "
    "on the turn it's cast only if there's mana left to pay for it. Rocks that don't untap by themselves "
    "(Basalt Monolith), mana from charge counters (Everflowing Chalice), mana abilities that also need a "
    "sacrifice or another cost besides mana (Lotus Petal), and ones a card gives other permanents "
    "(Goldspan Dragon's Treasures) aren't counted.",
    "Land ramp (Rampant Growth, Cultivate, Sakura-Tribe Elder) puts a basic land of a colour you need "
    "onto the battlefield tapped. A ramp ability that costs mana is used with mana left over after "
    "spells.",
    "Not modelled: card draw and card selection, Treasure, cost reductions (convoke and the like too), "
    "other activated abilities, triggers other than casting or entering (Ordeal of Nylea's search), and "
    "anything that needs an opponent.",
)

DEFINITIONS = {
    "mulligan_rate": "Share of games where you mulliganed at least once (a free multiplayer mulligan "
                     "counts).",
    "kept": "How many cards the kept hand had, after putting cards on the bottom.",
    "on_time": "Chance you'd played your Nth land by turn N: a land from your hand on every turn so "
               "far. Lands put in by ramp spells don't count here.",
    "mana": "Chance of having at least N mana on turn N, after your land drop: lands (one that "
            "entered tapped this turn counts) plus mana creatures, rocks and lands from ramp that "
            "can make mana this turn.",
    "stuck": "Share of games where on turn 2, 3 or 4 you had no land to play while holding a spell "
             "that one more land would have let you cast.",
    "missed_drops": "Average number of turns, of turns 1 to 6, with no land to play.",
    "flood_turns": "Share of turns 4 to 8 where your hand had no spells left (only lands, or "
                   "nothing), so there was nothing to spend mana on.",
    "flood_games": "Share of games with 3 or more such turns.",
    "colour_by_turn": "Chance you have a source of each colour on turns 1 to 5, after your land "
                      "drop (counted the same way as mana).",
    "colour_screw": "Share of turns where you had enough mana in total for a spell in hand (or your "
                    "commander), but not the right colours. You may still have cast something else.",
    "colour_screw_wasted": "Share of turns with colour screw where you also left mana unspent.",
    "mana_used": "Mana spent as a share of the mana you had, and the share of turns (with any "
                 "mana) where you spent all of it.",
    "first_big": "The turn your first spell with mana value 4 or more was cast (the commander "
                 "counts), and the chance it was on turn 4 or earlier.",
}


# ================================================================ colours

def _mask(colours):
    m = 0
    for c in colours or ():
        m |= BITS.get(c, 0)
    return m


def _colours_text(mask):
    return "".join(c for c in COLOUR_ORDER if mask & BITS[c])


def _colour_bits(mask):
    """Each colour bit in mask, in WUBRGC order (hybrid masks split)."""
    return [BITS[c] for c in COLOUR_ORDER if mask & BITS[c]]
