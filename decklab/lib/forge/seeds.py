"""Per-game seeds for the v2 engine (simulation wave 2, the report's R09): which game a
result's game number g is, worked out the same way here and in Java
(java/decklab/Seeds.java), so any single game of a result can be played again on its own.

A game of the v2 engine is a pure function of three numbers and the two lists:
    base    the result's seed base: SEED_BASE (1), or a run's --seed-base when it made the
            result
    stream  the result's seed stream, 64 bits: stream_of() the two lists' card_shas unless
            a run asks for another (a paired variant test, wave 3's R15, plays a variant on
            its base deck's stream, so both see the same shuffles)
    g       the game's number in the result: 0, 1, 2... over every run of the result
Game g's seed is game_seed(base, stream, g): Forge's random numbers are reseeded with it
(java.util.Random) before the game, and the game is played in a Match of its own (so it
has a coin flip for who starts, and Forge's auto-profile, like any first game). The side
that is Forge's deck 1 in game g is deck1_side(g): 0 (the side with the smaller card_sha)
in even blocks of SEAT_BLOCK games, 1 in odd ones, the other way round with a_first. So
game g is the same game however a run's games are cut into chunks and whichever worker
plays it, as long as a chunk never spans two blocks (block_of()). Plain Forge plays game g
of a Constructed chunk as "sim -d <deck 1> <deck 2> -n 1 -s <game_seed(base, stream, g)>"
(the v2 card-log check compares the two).

The mixing function is SplitMix64's (Steele, Lea and Flood, 2014: the output of its
generator for one step), applied three times:
    x = mix(base); x = mix(x ^ stream); x = mix(x ^ g)
with every number taken as 64 bits unsigned, and the result's top bit cleared, so a seed is
a long of 0 or more: Forge's sim reads "-s -5" as an option called "-5" and fails, so a
negative seed couldn't be given to plain Forge. Java's Random uses only the low 48 bits of a
seed anyway; a chance overlap of two games' low 48 bits is negligible at Deck Lab's sizes.
Consecutive seeds need the mixing: Random's first numbers barely differ for seeds 1, 2, 3
(r5-stats/javarandom-out.txt). A base must be 0 or more too (it goes after -s).

TEST_VECTORS holds (base, stream, g, seed) cases that Seeds.java must give too (the tests
check both). This file imports nothing from Deck Lab: the tests' fake Forge loads it on its
own."""
import hashlib
import re

MASK = (1 << 64) - 1
SEED_MASK = (1 << 63) - 1       # a seed's bits: a long of 0 or more
GOLDEN_GAMMA = 0x9E3779B97F4A7C15
SEED_BASE = 1                   # a new result's base (lists.SEED_BASE is the same number for v1)
SEAT_BLOCK = 25                 # games in a block: each block has one side as Forge's deck 1
STREAM_LABEL = "decklab-seed-stream-1"      # what stream_of() hashes first
STREAM_RE = re.compile(r"[0-9a-f]{16}")     # a stream as results store it
# The seed scheme's name, as the v2 engine id records it: change it only with the scheme.
SCHEME = "splitmix64(base,stream,game);seat-block-25"

# (base, stream, game, seed): game_seed(base, stream, game) == seed, here and in Seeds.java.
# Computed with Seeds.java (JDK 26.0.1) and with this file on 2026-10-03; they agree.
TEST_VECTORS = (
    (0, 0, 0, 2558736989570252433),
    (1, 0, 0, 3569668903477806787),
    (1, 0, 1, 7806873273932414515),
    (1, 0x0123456789ABCDEF, 0, 2291207570733865206),
    (1, 0x0123456789ABCDEF, 799, 751406823689115176),
    (-5, 0xFFFFFFFFFFFFFFFF, 12345, 6576315120302096085),
    (1, 0xFEDCBA9876543210, 1 << 40, 1845434521246174757),
)
# The first output of SplitMix64 started at 0 (a published value): mix(0) is it.
MIX_ZERO = 0xE220A8397B1DCDAF

# Wave 3's deck-order-1 (forge-trial/sim-wave3-contract.md section 3.2): loading game g's decks
# draws its random numbers (the art of each copy of a card with several) from a stream of its
# own, load_seed(base, stream, g), so a variant that changes how many basic lands it holds
# doesn't shift the game's own numbers. LOAD_SALT is "loadseed" in ASCII.
LOAD_SALT = 0x6C6F616473656564
# (base, stream, game, load seed): load_seed(base, stream, game) == seed, here and in
# Seeds.loadSeed. Computed with Seeds.java and with this file on 2026-10-03; they agree.
LOAD_TEST_VECTORS = (
    (0, 0, 0, 5533761014434635113),
    (1, 0, 0, 6424907176330605920),
    (1, 0x0123456789ABCDEF, 799, 8628384799886043349),
    (1, 0xFEDCBA9876543210, 1 << 40, 633029749585525667),
)


def mix(x):
    """SplitMix64's output for state x (unsigned 64 bits in and out)."""
    z = (x + GOLDEN_GAMMA) & MASK
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
    return z ^ (z >> 31)


def game_seed(base, stream, game):
    """Game g's seed (the module docstring): 0 to 2**63 - 1, a long Forge's -s takes.
    base, stream and game may be any ints; each is taken modulo 2**64."""
    x = mix(base & MASK)
    x = mix(x ^ (stream & MASK))
    return mix(x ^ (game & MASK)) & SEED_MASK


def load_seed(base, stream, game):
    """The seed loading game g's decks draws from (deck-order-1, LOAD_SALT's comment):
    game_seed(base, stream ^ LOAD_SALT, game): another stream than the game's own."""
    return game_seed(base, (stream & MASK) ^ LOAD_SALT, game)


def stream_of(card_sha_a, card_sha_b):
    """The default seed stream of a pair of lists (unsigned 64 bits): the first 8 bytes of
    the SHA-256 of STREAM_LABEL and both card_shas, sorted, one per line. The same for
    (a, b) and (b, a), and different for every other pair, so a deck's games against
    two opponents aren't played on the same shuffles (that would correlate a field
    average across them)."""
    text = "\n".join([STREAM_LABEL, *sorted([card_sha_a, card_sha_b])])
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


def stream_hex(stream):
    """A stream as the 16 lower-case hex digits results store and Forge's -dlgame takes."""
    return f"{stream & MASK:016x}"


def parse_stream(text):
    """stream_hex()'s text back to the number; ValueError unless it's 16 hex digits."""
    if not isinstance(text, str) or not STREAM_RE.fullmatch(text):
        raise ValueError(f"a seed stream is 16 hex digits, not {text!r}")
    return int(text, 16)


def block_of(game):
    """The seat block game g is in (a chunk never spans two)."""
    return game // SEAT_BLOCK


def deck1_side(game, flip=False):
    """The side (0 or 1) that is Forge's deck 1 in game g: 0 in even blocks, 1 in odd ones;
    flip swaps them (a run that asked for side 1 as deck 1 in even blocks: --a-first with
    the larger card_sha first)."""
    return (block_of(game) + bool(flip)) % 2


def block_end(game):
    """The first game number after game g's block."""
    return (block_of(game) + 1) * SEAT_BLOCK
