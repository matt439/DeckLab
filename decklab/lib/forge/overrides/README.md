# Deck Lab's card-script overrides

Each `<set>/<card>.txt` here is **Forge's own card script** (Forge 2.0.15's `res/cardsfolder/cardsfolder.zip`,
GPL-3.0, the Forge project's) with small AI edits applied: exact text replacements, listed in `sets.json`
under the file's `edits`. Forge loads a script in its user folder's `custom/cards` over its own, so Deck Lab
puts the files of the **adopted** sets in its own user folder (`decklab/data/forge/user`) before Forge starts.
Experiment sets play only in folders of their own (`decklab/data/forge/users/exp-*`).

- `sets.json` says, per set, whether it's `adopted` or an `experiment`, why, and per file: the card, the
  SHA-256 of Forge's script it was made from (`upstream_sha256`), the edits, and a cast-rate target.
- `python -m decklab.lib.forge overrides make [--set S]` makes the files again from the installed Forge; it
  fails, naming the card, when an edit's old text isn't in Forge's script exactly once.
- `python -m decklab.lib.forge overrides check` says whether every file is Forge's script with its edits.
- A file whose `upstream_sha256` isn't the installed Forge's script isn't used (a Forge upgrade changed the
  card, perhaps fixing what the override works around): the Forge box on the page names it.

Scoped experiment sets (AI round 1): `etb-tfp` and `etb-tfp-jailer` change only cards in The Free
Peoples (Fires of Mount Doom, Éowyn, Samwise; Palace Jailer on its own). Only The Free Peoples plays
these cards today (2026-10-13), so other decks don't change, but a TFP mirror changes both seats, and
its Play-now list has none of them. `cmdr-hints` is for the Commander decks (Primal Might's Fight
logic, with AILogic$ Always on its fight so the pump counts). None is adopted.

Where they come from: `decklab/forge-trial/sim-investigation/r4-ai` (r4's `make_overrides.py`, notes section
2), r6's AI hints, and the plan's R10 (`decklab/forge-trial/sim-investigation.md`); the wave 3 contract's
section 6 has the rules.
