"""Every figure the deck stats use, with its source and the date it was
looked up (PLAN.md: never from memory), and the patterns card text is read
with. The package docstring (decklab/lib/stats/__init__.py) says how they're
used; "sources" in deck_stats' result lists SOURCES again, so the page can
cite them."""
import re

KINDS = ("constructed", "commander")

# --------------------------------------------------------------- sources
# Everything below was looked up on 2026-09-29 by the Milestone 2 research
# (land counts, colour sources, Commander Brackets), each from these pages.
SOURCES = {
    "karsten-lands": {
        "title": "How Many Lands Do You Need in Your Deck? An Updated Analysis (Frank Karsten)",
        "date": "2022-07-29, page updated 2025-02-13; still his newest land-count study on 2026-09-29",
        "url": "https://www.tcgplayer.com/content/article/How-Many-Lands-Do-You-Need-in-Your-Deck-"
               "An-Updated-Analysis/cd1c1a24-d439-4a8e-b369-b936edb0b38a/"},
    "karsten-sources": {
        "title": "How Many Sources Do You Need to Consistently Cast Your Spells? A 2022 Update "
                 "(Frank Karsten)",
        "date": "2022-08-02, page updated 2025-02-13; still his newest on 2026-09-29",
        "url": "https://www.tcgplayer.com/content/article/How-Many-Sources-Do-You-Need-to-"
               "Consistently-Cast-Your-Spells-A-2022-Update/dc23a7d2-0a16-4c0b-ad36-586fcca03ad8/"},
    "karsten-commander": {
        "title": "What's an Optimal Mana Curve and Land/Ramp Count for Commander? (Frank Karsten)",
        "date": "2022-07-15, updated 2025-08-28",
        "url": "https://www.tcgplayer.com/content/article/What-s-an-Optimal-Mana-Curve-and-Land-"
               "Ramp-Count-for-Commander/e22caad1-b04b-4f8a-951b-a41e9f08da14/"},
    "karsten-verge": {
        "title": "Building Mana Bases with Duskmourn's New Verge Lands (Frank Karsten)",
        "date": "2024-10-18",
        "url": "https://www.tcgplayer.com/content/article/Building-Mana-Bases-with-Duskmourn-s-New-"
               "Verge-Lands/02256252-047e-458a-92b3-bed999bd3364/"},
    "wizards-mana": {
        "title": "The Basics of Mana (Reid Duke, Wizards of the Coast)",
        "date": "2014-08-18",
        "url": "https://magic.wizards.com/en/news/feature/basics-mana-2014-08-18"},
    "wizards-jumpstart": {
        "title": "Foundations Jumpstart Booster Themes (Wizards of the Coast)",
        "date": "2024-10-28",
        "url": "https://magic.wizards.com/en/news/announcements/foundations-jumpstart-booster-themes"},
    "edhrec-lands": {
        "title": "How to Build a Commander Deck (Brian Cain, EDHREC)",
        "date": "2024-11-25",
        "url": "https://edhrec.com/articles/how-to-build-a-commander-deck"},
    "wizards-commander": {
        "title": "Commander format page: Brackets and Game Changers (Wizards of the Coast)",
        "date": "fetched 2026-09-29 (Game Changers last changed 2026-02-09)",
        "url": "https://magic.wizards.com/en/formats/commander"},
    "brackets-2025-02": {
        "title": "Introducing Commander Brackets Beta (Wizards of the Coast)",
        "date": "2025-02-11",
        "url": "https://magic.wizards.com/en/news/announcements/introducing-commander-brackets-beta"},
    "brackets-2025-10": {
        "title": "Commander Brackets Beta Update, October 21, 2025 (Wizards of the Coast)",
        "date": "2025-10-21",
        "url": "https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-"
               "october-21-2025"},
    "brackets-2026-02": {
        "title": "Commander Brackets Beta Update, February 9, 2026 (Wizards of the Coast)",
        "date": "2026-02-09",
        "url": "https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-"
               "february-9-2026"},
    "banned-list": {
        "title": "Banned and Restricted List, Commander entry (Wizards of the Coast)",
        "date": "Commander entry edited 2026-04-03; fetched 2026-09-29",
        "url": "https://magic.wizards.com/en/banned-restricted-list"},
    "comp-rules": {
        "title": "Magic: The Gathering Comprehensive Rules, 903 (Commander)",
        "date": "effective 2026-09-25",
        "url": "https://media.wizards.com/2026/downloads/MagicCompRules%2020260925.txt"},
    "tagger": {
        "title": "Scryfall Tagger oracle tags mass-land-denial and extra-turn",
        "date": "oracle_tags bulk file of 2026-09-28",
        "url": "https://tagger.scryfall.com/tags/card/mass-land-denial"},
    # Its date is the downloaded list's own (bracket.combos.list_date): deck_stats
    # fills it in at runtime, from decklab/data/combos/two_card.json.
    "commander-spellbook": {
        "title": "Commander Spellbook's combo list: two-card combos (commanderspellbook.com, "
                 "with thanks; fan content under Wizards' Fan Content Policy)",
        "date": "the list downloaded with the card data; its date is shown with the checks",
        "url": "https://commanderspellbook.com/"},
}
# The commander-spellbook source's date while the combo list can't be read (the
# checks then say combos weren't checked, so there's no date to point to).
COMBO_LIST_UNREAD = "not downloaded yet or can't be read, so combos weren't checked"

# ------------------------------------------------------------ deck sizes
CONSTRUCTED_SIZES = (20, 40, 60)    # Beginner Box halves, pairings, casual decks
COMMANDER_SIZE = 100                # CR 903.5a: exactly 100 cards, commander included
COMMANDER_LIBRARY = 99              # what Karsten's Commander formula and table are for

# ------------------------------------------------------------ land count
# karsten-lands. His 60-card regression over 95,143 decks with more wins than
# losses (MTG Melee and MTGO, 2020-07-01 to 2022-07-01; R^2 0.395, RMSE 2.75):
#   lands = 19.59 + 1.90 * AMV - 0.28 * cheap + 0.27 * companions
# His 80-card version multiplies every term except the cheap one by 80/60; the
# 20- and 40-card formulas use that same scaling. He never published those:
# they're our extrapolation, which fits all 10 Foundations Beginner Box halves
# within +/-0.97 lands, all 45 pairings within -0.86..+1.19 and 118 of 119
# Foundations Jumpstart lists within +/-1.
LAND_INTERCEPT = 19.59
LAND_PER_AMV = 1.90
LAND_PER_COMPANION = 0.27
LAND_PER_CHEAP = 0.28       # a land for every 3-4 cheap spells; not scaled by deck size
# His published 99-card port (the commander counts as a companion; -1.35 for
# the free mulligan and the turn-1 draw):
#   lands = 99/60 * (19.59 + 1.90 * AMV + 0.27) - 0.28 * cheap - 1.35
#         = 31.42 + 3.13 * AMV - 0.28 * cheap
COMMANDER_LAND_INTERCEPT = 31.42
COMMANDER_LAND_PER_AMV = 3.13
LAND_FORMULAS = {
    20: {"published": False,
         "status": "Not published by Karsten: his 60-card formula scaled by 20/60, the way he scales "
                   "his 80-card one (our extrapolation). It fits all 10 Foundations Beginner Box "
                   "halves within 0.97 lands and 118 of 119 Foundations Jumpstart lists within 1."},
    40: {"published": False,
         "status": "Not published by Karsten: his 60-card formula scaled by 40/60, the way he scales "
                   "his 80-card one (our extrapolation). It fits all 45 Beginner Box pairings within "
                   "-0.86 to +1.19 lands; the curve model in his 2022 Commander article gives 17 "
                   "lands for 40 cards."},
    60: {"published": True,
         "status": "Published regression over 95,143 winning 60-card decks (2020-2022); it explains "
                   "about 40% of the variation, with a typical error of 2.75 lands."},
    100: {"published": True,
          "status": "Published, but Karsten calls it an 'imprecise back-of-the-envelope estimate': "
                    "the commander counts as a companion, and 1.35 lands come off for the free "
                    "mulligan and turn-1 draw."},
}
# Land // spell modal cards: 0.38 of a land when the land always enters tapped
# (his non-mythic Zendikar Rising examples), 0.74 when it can enter untapped
# (his mythic ones; he gives entering untapped as the reason).
MDFC_LAND_WEIGHTS = {"tapped": 0.38, "untapped": 0.74}
# The verdict band b = max(1, N/60): our choice built on the research's
# suggested +/-1 (no source sets a tolerance).
LAND_BAND_MIN = 1.0
# karsten-commander: "for medium-power midrange Commander decks, try not to go
# below 37 lands."
COMMANDER_LAND_FLOOR = 37
# Each figure is from the sources listed with it: wizards-mana says 17-18 and
# 24-25; karsten-commander says his model gives 17 for 40 cards, 24-25 for
# 60-card aggro and 26 for midrange, and 42 plus Sol Ring, trying not to go below
# 37 for medium-power midrange, for Commander; edhrec-lands says 36-38.
LAND_RULES_OF_THUMB = {
    20: {"text": "8 lands (7 basics + 1 nonbasic); 9 in top-heavy or land-matters halves",
         "sources": ["wizards-jumpstart"]},
    40: {"text": "17 lands (Wizards 2014: 17-18; Karsten 2022: his curve model gives 17)",
         "sources": ["wizards-mana", "karsten-commander"]},
    60: {"text": "24-25 lands (Wizards 2014); Karsten 2022: 24-25 for aggro, 26 for midrange",
         "sources": ["wizards-mana", "karsten-commander"]},
    100: {"text": "36-38 lands (EDHREC 2024); Karsten: start from 42 lands plus Sol Ring, cut one "
                  "per 2-3 extra rocks, and for medium-power midrange try not to go below 37",
          "sources": ["edhrec-lands", "karsten-commander"]},
}

# Karsten's cheap card draw and cheap mana ramp (karsten-lands), matched in the
# lowercased Oracle text, reminder text included. Cheap draw: a nonland card
# of mana value 2 or less whose text has one of CHEAP_DRAW_WORDS and none of
# CHEAP_DRAW_NOT (a creature also needs "when" and "enters"); or a noncreature
# one with all of CHEAP_LOOK_WORDS and none of CHEAP_LOOK_NOT; or "any spell
# that cycles for one mana" (at any mana value, as he words it). Cheap ramp:
# a nonland card of mana value 2 or less, not already cheap draw, with "add "
# (none of CHEAP_RAMP_NOT, and a creature must not have "dies"), or "search"
# + "your library" + ("land" or "basic") without "sacrifice", or both
# CHEAP_RAMP_AURA phrases, or both CHEAP_RAMP_CHEAT phrases.
CHEAP_MAX_MV = 2
CHEAP_DRAW_WORDS = ("draw a card", "draw two cards", "draw three cards",
                    "draws cards", "draws two cards", "draws three cards")
CHEAP_DRAW_NOT = ("{4}", "blood token", "investigate")
CHEAP_DRAW_CREATURE_WORDS = ("when", "enters")
CHEAP_LOOK_WORDS = ("look", "library", "put", "your hand")
CHEAP_LOOK_NOT = ("pay ", "pays")
CHEAP_RAMP_NOT = ("add its ability", "add a lore counter")
CHEAP_RAMP_CREATURE_NOT = ("dies",)
CHEAP_RAMP_AURA = ("enchanted land is tapped", "adds an additional")
CHEAP_RAMP_CHEAT = ("put a creature card with", "from your hand onto the battlefield")

# ---------------------------------------------------------- colour check
# karsten-sources, first table: coloured sources needed to cast a spell on
# the turn equal to its mana value, on the play, with (89 + MV)% probability,
# by {turn: {coloured symbols: sources}}. Copied from the article's text
# table; 80 cards is left out (no guidance size uses it).
COLOUR_SOURCES_NEEDED = {
    40: {1: {1: 9}, 2: {1: 9, 2: 14}, 3: {1: 8, 2: 12, 3: 16}, 4: {1: 7, 2: 11, 3: 14, 4: 17},
         5: {1: 6, 2: 10, 3: 13, 4: 15}, 6: {1: 6, 2: 9, 3: 11}, 7: {2: 8, 3: 10}},
    60: {1: {1: 14}, 2: {1: 13, 2: 21}, 3: {1: 12, 2: 18, 3: 23}, 4: {1: 10, 2: 16, 3: 21, 4: 24},
         5: {1: 9, 2: 15, 3: 19, 4: 22}, 6: {1: 9, 2: 13, 3: 17}, 7: {2: 12, 3: 16}},
    99: {1: {1: 19}, 2: {1: 19, 2: 30}, 3: {1: 18, 2: 28, 3: 36}, 4: {1: 16, 2: 26, 3: 33, 4: 39},
         5: {1: 15, 2: 23, 3: 30, 4: 36}, 6: {1: 14, 2: 22, 3: 28}, 7: {2: 20, 3: 26}},
}
# Costs his tables skip, {(turn, symbols): sources}. NOT published by Karsten:
# computed on 2026-09-29 by our research with an exact re-implementation of his
# 2022 simulation code (github.com/frankkarsten/MTG-Math,
# HowManySources2022Update.py), which reproduces all 1,805 of his published
# probability cells within 0.25 percentage points. Checks using them say so.
COLOUR_SOURCES_COMPUTED = {
    40: {(5, 5): 17, (6, 4): 14, (6, 5): 16, (7, 1): 5, (7, 4): 13, (7, 5): 14},
    60: {(5, 5): 25, (6, 4): 20, (6, 5): 23, (7, 1): 8, (7, 4): 19, (7, 5): 21},
    99: {(5, 5): 40, (6, 4): 33, (6, 5): 37, (7, 1): 14, (7, 4): 31, (7, 5): 35},
}
COLOUR_TABLES = {40: 40, 60: 60, 100: 99}      # guidance size -> table (none below 40)
COLOUR_ASSUMED_LANDS = {40: 17, 60: 25, 99: 41}
# He says the 60-card table holds for 22-28 lands; outside that he suggests
# scaling by (your lands / assumed lands). We use the same +/-3 for every table.
COLOUR_LAND_TOLERANCE = 3
COLOUR_MAX_TURN = 7                 # his tables stop at mana value 7
COLOUR_X_VALUE = 1                  # our choice: X is paid as 1
GOLD_EXTRA = 1                      # gold cards: +1 per colour and for the colours together
# Partial sources and when they count (karsten-sources, "How to count
# sources"): weight per copy, and the earliest turn they help with.
LAND_SOURCE = 1.0
MDFC_SOURCE_WEIGHTS = {"tapped": 0.8, "untapped": 1.0}   # his non-mythic 0.8, mythic 1
MULTICOLOUR_FETCH_WEIGHT = 2 / 3    # Fabled Passage, Pathways: decks needing 3+ colours
DORK_WEIGHT, DORK_FIRST_TURN = 0.5, 2          # mana creatures: spells of MV 2+
ROCK_WEIGHT, ROCK_FIRST_TURN = 0.75, 3         # mana rocks: spells of MV 3+
RAMP2_WEIGHT, RAMP2_FIRST_TURN = 0.75, 3       # 2-mana land ramp (Rampant Growth, Farseek)
RAMP3_WEIGHT, RAMP3_FIRST_TURN = 0.5, 5        # 3-mana land ramp (Cultivate): MV 5+ only
CANTRIP_MAX_MV = 2                  # "card draw costing 2 or less"
CANTRIP_MAX_COUNTED = 10            # "count at most the first 10 card-draw effects"
CANTRIP_ROUNDING = 4                # (sources / deck size) rounded down to a quarter
SPECIAL_SOURCE_WEIGHTS = {"Exotic Orchard": 0.75, "Fellwar Stone": 0.5}   # unknown opponents
COLOUR_SOURCE_RULES = (
    "A land that makes the colour is 1 source. On turn 1 only lands that can enter untapped count "
    "(a shock land or fast land can, and in Commander a bond land; a check land, gain land or "
    "basic-land fetch can't).",
    "A land that searches for a basic land is a source of each colour of the basics in the deck "
    "(2/3 of one in decks needing 3 or more colours); one that searches for a land type, of each "
    "colour the deck's lands of that type make. Pathways: 2/3 each in decks needing 3+ colours.",
    "A land whose search costs mana (Myriad Landscape's {2}) is a source only of the colours it "
    "makes itself until it can be used: paying {2} takes two other lands, so the lands it finds "
    "count from turn 4 (Karsten's full source is for searches that cost no mana, like Evolving "
    "Wilds).",
    "A spell // land modal card is 0.8 of a source (1 if its land can enter untapped).",
    "Mana creatures: 0.5 of a source from the turn after they're cast (turn 2 at the earliest). "
    "Mana rocks: 0.75 from the turn after they're cast (turn 3 at the earliest). 2-mana land "
    "ramp: 0.75 from turn 3; 3-mana land ramp: 0.5 from turn 5. Each only when the deck can "
    "cast the card itself consistently.",
    "Cheap card draw (mana value 2 or less): each digs for lands, worth (sources of the colour / "
    "deck size) rounded down to a quarter, for spells cast after it; the first 10 only.",
    "Exotic Orchard 0.75 and Fellwar Stone 0.5 of any colour (opponents unknown).",
    "Not counted: Treasure, scry, and a Verge land's condition (it counts fully for both colours).",
)

# --------------------------------------------------------- Commander rules
# comp-rules 903.5b and 101.1: card text can allow more copies, or fewer
# ("A deck can have only one card named Once More with Feeling").
DECK_COPIES_RE = re.compile(r"a deck can have (any number of|up to (\w+)|only one) cards? named"
                            r"|your deck can have (only one) copy of this card")
# comp-rules 702.124: the partner abilities, one per line of a card's text.
PARTNER_WITH_RE = re.compile(r"^partner with (.+)$", re.IGNORECASE)
PARTNER_TEXT_RE = re.compile(r"^partner ?[—–-] ?(.+)$", re.IGNORECASE)      # "Partner—Friends forever"
# comp-rules 903.3: a card that is a creature everywhere but the battlefield
# (Grist, the Hunger Tide) is a creature card in the command zone.
OFF_BATTLEFIELD_CREATURE_RE = re.compile(r"as long as [^.\n]*? isn't on the battlefield, it's an? "
                                         r"[^.\n]*?\bcreature\b")
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
# banned-list: "Lutri, the Spellchaser - only banned as a companion" (Scryfall says legal).
BANNED_AS_COMPANION = {"Lutri, the Spellchaser"}
# wizards-commander, brackets-2025-02, brackets-2025-10 (tutor limits removed),
# brackets-2026-02 (latest change; still "beta" on 2026-09-29).
BRACKETS = (
    {"number": 1, "name": "Exhibition", "min_turns": 9, "game_changers": 0,
     "mass_land_denial": "no", "extra_turns": "no", "two_card_combos": "no",
     "note": "Exceptions can be made for highly thematic cards."},
    {"number": 2, "name": "Core", "min_turns": 8, "game_changers": 0,
     "mass_land_denial": "no", "extra_turns": "only a few, never chained or looped",
     "two_card_combos": "no", "note": None},
    {"number": 3, "name": "Upgraded", "min_turns": 6, "game_changers": 3,
     "mass_land_denial": "no", "extra_turns": "only a few, never chained or looped",
     "two_card_combos": "none before turn 6", "note": None},
    {"number": 4, "name": "Optimized", "min_turns": 4, "game_changers": None,
     "mass_land_denial": "allowed", "extra_turns": "allowed", "two_card_combos": "allowed",
     "note": "No deck restrictions beyond the ban list."},
    {"number": 5, "name": "cEDH", "min_turns": None, "game_changers": None,
     "mass_land_denial": "allowed", "extra_turns": "allowed", "two_card_combos": "allowed",
     "note": "Differs from Bracket 4 only in intent (a cEDH metagame mindset)."},
)
# The date the bracket rules above (BRACKETS, BRACKET_NOT_AUTOMATIC,
# UPGRADED_MAX_GAME_CHANGERS) were last checked against Wizards' announcements:
# brackets-2026-02's. The Commander checks warn while Wizards' latest Commander
# announcement (decklab.lib.official_lists) is newer than this (E9-S24). After
# a new announcement, review the rules, update them and their sources if it
# changed anything, then set this to the announcement's date, even when it
# changed nothing.
BRACKET_RULES_DATE = "2026-02-09"
UPGRADED_MAX_GAME_CHANGERS = 3
BRACKET_LABELS = {1: "Bracket 1 or 2 (theme and intent decide)", 2: "Bracket 2 or higher",
                  3: "Bracket 3 or higher", 4: "Bracket 4 or higher (4 or 5 by intent)"}
MASS_LAND_DENIAL_TAG = "mass-land-denial"   # its description is Wizards' definition, word for word
EXTRA_TURN_TAG = "extra-turn"
BRACKET_NOT_AUTOMATIC = (
    "Two-card combos (game-enders, lockouts or infinites): none in Brackets 1-2, none before "
    "turn 6 in Bracket 3. Deck Lab looks for Commander Spellbook's two-card combos only: combos "
    "of three or more cards, combos needing a card that isn't named (\"a creature with power 4 or "
    "more\") and your intent aren't checked, how early a combo can win isn't judged, and the "
    "list can miss combos.",
    "Extra turns in Brackets 2-3 must be few and never chained or looped; no number is published.",
    "How fast games are meant to end (at least 9, 8, 6 or 4 turns) and the deck's intent; you can "
    "always play a deck in a higher bracket.",
    "Bracket 1 vs 2, and 4 vs 5, differ only in theme and intent. Bracket 1 may allow a thematic "
    "Game Changer, extra turn or combo if the other players agree.",
    "Scryfall's community tags can miss or over-include cards: mass-land-denial misses Burning of "
    "Xinye and Destructive Force and includes some planeswalkers whose ultimates hit lands.",
)

# -------------------------------------------------------------- card text
COLOURS = "WUBRG"
MANA_COLOURS = "WUBRGC"         # C: the {C} symbol, which Karsten treats as a colour
COLOUR_NAMES = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green",
                "C": "colourless ({C})"}
CARD_TYPES = ("creature", "instant", "sorcery", "artifact", "enchantment", "planeswalker",
              "battle", "land")
LAND_TYPES = ("plains", "island", "swamp", "mountain", "forest")
TRIBAL_TYPES = {"Creature", "Kindred", "Tribal"}
MULTIWORD_SUBTYPES = ("Time Lord",)
# Faces you can cast as spells: both halves of a split card, an adventure's or
# prepare card's spell, and both faces of a modal card (unless one is a land).
CAST_EVERY_FACE = {"split", "adventure", "prepare", "modal_dfc"}
SYMBOL_RE = re.compile(r"\{([^}]*)\}")
REMINDER_RE = re.compile(r"\([^()]*\)")
TAP_ADD_RE = re.compile(r"\{t\}(?:, [^:\n]*)?: (?:for each [^,:\n]*, )?add\b")
# The parts of a mana ability's cost that still let it be used every turn:
# mana symbols ({T}, {1}) and life, which isn't counted. Anything else (a
# sacrifice, removing a counter, tapping another creature, discarding)
# makes it a one-off or conditional source.
MANA_COST_PART_RE = re.compile(r"(?:\{[^}]*\})+|pay (?:\d+|x|one|two|three) life")
ABILITY_WORD_RE = re.compile(r"^[^{:—]*— ")        # "Vivid — " before an ability's cost
SEARCH_RE = re.compile(r"search your library for ([^.]*?)cards?\b")
ENTERS_TAPPED_RE = re.compile(r"enters(?: the battlefield)? tapped")
# Lands that enter tapped only sometimes and can be untapped on turn 1: shock
# lands and modal lands ("you may pay"), fast lands ("two or fewer other
# lands"), "unless it's your first, second, or third turn"; and in multiplayer
# Commander (which Karsten's 99-card table assumes) "two or more opponents".
# Every other "unless" (check lands, "two or more basic lands") is tapped on turn 1.
UNTAPPED_OPTION_RE = re.compile(r"you may pay|unless you control (?:one|two|three) or fewer"
                                r"|unless it's your first")
MULTIPLAYER_UNTAPPED_RE = re.compile(r"unless you have two or more opponents")
CYCLING_RE = re.compile(r"(?<![a-z])cycling ((?:\{[^}]+\})+)")
LAND_KINDS = ("land", "fetch", "special")     # sources that are lands (not modal cards)
