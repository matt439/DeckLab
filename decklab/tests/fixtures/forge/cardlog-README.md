# cardlog-s7.log

Real Forge 2.0.15 output of one game played with the card log (DeckLabSim, as Milestone 8 built
it from `decklab/lib/forge/java/`, with Deck Lab's lazy card loading): Gruul Ramp (owned) as deck 1
against Izzet Prowess (owned), Constructed, seed 7, the same game as `full-game-s7.log`. Gruul Ramp
went first and won on turn 13 (round 7).

Logged on 2026-10-01, with one edit: the `Phase:` lines are left out, as in the other logs here
(nothing reads them). Milestone 0's jar logged the same game with the same lines, apart from the
`DL|log|1` line it didn't print yet.

Everything else is as Forge printed it. Card ids are Forge's own: deck 1's
cards are 1-60 and deck 2's 67-126 (not contiguous); id 133 is an effect ("Scorching Dragonfire's
Effect") that the card log leaves out. `test_forge_cardlog.ReaderTests.test_a_real_game` checks a
few cards' tallies, worked out by hand from this log.

# cardlog-opening-s2.log

Real Forge 2.0.15 output of one game with opening-hand actions, played with the card log on
2026-10-01: game 7 of twelve, Constructed, seed 2, between two made-up lists. Deck 1, "leylines",
is 4 Leyline of the Void, 4 Gemstone Caverns, 20 Swamp, and 4 each of Vampire Nighthawk, Gifted
Aetherborn, Bloodghast, Gravecrawler, Dread Shade, Sengir Vampire, Duress and Doom Blade. Deck 2,
"green", is 24 Forest, and 4 each of Llanowar Elves, Grizzly Bears, Centaur Courser, Giant Growth,
Garruk's Companion, Leatherback Baloth, Kalonian Tusker, Rancor and Elvish Mystic.

After both players kept 7, Forge put Leyline of the Void (5) and Gemstone Caverns (52) onto the
battlefield and exiled Dread Shade (48) for the Caverns, all at turn 0 and before `DL|hand|1|start`,
so seat 1's start hand has 4 cards. Green went first; the Leyline list won on turn 14 (round 7).

Edits: the start-up lines are kept, the other eleven games are left out (the header line still
says twelve), and the `Phase:` lines are left out. Everything else is as Forge printed it.
`test_forge_cardlog.ReaderTests.test_a_real_game_with_opening_hand_actions` checks a few cards'
tallies, worked out by hand from this log.

# cardlog-failed-cast-s5.log

Real Forge 2.0.15 output of one game with a failed cast, played with the card log on 2026-10-01:
game 13 of twenty, Constructed, seed 5, between Selesnya Rabbits (deck 1) and Orzhov Vampires
(deck 2), as the casual deck files listed them that day. Deck 2 went first and won on turn 13
(round 7).

Selesnya Rabbits drew Felling Blow (11) on turn 8. On turn 12 Forge's AI began casting it: the
card moved Hand -> Stack (`DL|zone|12|1|MAIN1|Hand|Stack|1|11|Felling Blow`), and then, with no
`Ai(1)-... cast` line, Forge logged `Add To Stack: Felling Blow (11) - [Couldn't add to stack,
failed to target] - ...`. Forge never moves the card again that game, so it's in neither end hand.
The same line without `Add To Stack: ` (Forge's error stream, printed while the game was played)
comes just before the game's `DL|log|1` line.

Edits: the start-up lines are kept, except the "was not assigned to any set" and `WARNING:` lines;
the other nineteen games are left out (the header line still says twenty); and the `Phase:` lines
are left out. Everything else is as Forge printed it.
`test_forge_cardlog.ReaderTests.test_a_real_game_with_a_failed_cast` checks Felling Blow and a few
other cards' tallies, worked out by hand from this log.
