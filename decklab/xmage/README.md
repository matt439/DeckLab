# Optional XMage bridge

This bridge runs one game in one disposable, headless JVM. It uses XMage's own MAD AI and
rules implementation. It starts no XMage server or network listener and reads no household
database. Deck Lab owns the run's permissions, cancellation, process watchdog and saved results.

## Install and build explicitly

Use the official [XMage 1.4.63V1 release](https://github.com/magefree/mage/releases/tag/xmage_1.4.63V1),
`mage-full_1.4.63-dev_2026-10-31_09-42.zip`. Its SHA-256 is
`f48e69a2583720800ab6a447458ede73bded5cb21905b0d9658a6052ab43908a`.
Extract it to a separate tools folder. A complete JDK 21 or later must be available; discovery
uses Deck Lab's existing full-JDK finder. Installation, downloading and compilation never happen
from a status read or a game request.

```powershell
python -m decklab.xmage build --home C:\Tools\xmage
python -m decklab.xmage describe --home C:\Tools\xmage
```

`--home` accepts the extracted archive root, its `xmage` directory or `mage-server` itself.
`--output` selects a separate build directory; the default is the gitignored
`decklab/data/xmage/bridge`. `--java` can name the full JDK's Java executable for these setup
commands. Configure `xmage_dir` in the server's private configuration only when enabling it there.
There is no live configuration or service change in building this bridge.

The bridge supports exactly this release's 86 server/plugin jars. Their sorted-path/content
fingerprint is `596c4ca03d3be39230714bf28672543d30109c9c8eb8396d6f0ecdec20a67805`.
An extra, missing or changed jar fails verification. A source change requires an explicit rebuild.
The runtime identity also binds the bridge source and artifact, the JDK executable and release file,
and the fixed AI/rules policy. The running JVM checks those identities again before reading the
request. No upstream sources or binaries are copied into this public repository.

## Game contract

The native command is the private `command` array returned by `describe()`, followed by one
absolute request-file path. Run it with a disposable working directory. Clear inherited JVM option
variables. Its stdout is one JSON object; bounded diagnostics go to stderr. The JVM has a 1 GiB
heap, one advertised processor and one MAD simulation worker. Every game uses MAD skill 6.

The UTF-8 request is strict JSON with no duplicate or unknown keys:

```json
{
  "schema": 1,
  "format": "casual",
  "seed": 42,
  "games": 1,
  "game_number": 1,
  "starting_player": 0,
  "timeout_seconds": 120,
  "decks": [
    {"id": "baseline", "main": [{"name": "Forest", "quantity": 60}], "commander": []},
    {"id": "opponent", "main": [{"name": "Mountain", "quantity": 60}], "commander": []}
  ]
}
```

The subject may be `baseline` or `variant`; the second deck is `opponent`. `game_number` and
`starting_player` are optional; default numbering is 1, and the first starter alternates by game
number. Seed range is 0 through 2,147,483,647, numbering 1 through 10,000 and timeout 1 through
600 seconds. Decks contain at most 2,000 cards. Rows must have a unique exact name and positive
integer quantity. The bridge accepts only main cards and zero to two commanders; it does not
silently discard a sideboard, companion or other unsupported section.

Every exact name is loaded as its real implemented card class, with no mock cards or replacements.
Different printings of a name are interchangeable for these games. Double-faced, split and flip
names are checked with both faces. Missing cards and invalid decks prevent the game entirely.

- `casual`: 1v1, 20 life, at least 60 cards, at most four nonbasic copies, no format or ban-list
  filter. No Standard, Modern or other tournament legality is substituted.
- `commander`: 1v1, 40 life, commander zone, tax and 21 commander damage, regular Commander deck
  validation including color identity and partners. This uses the pinned release's Commander rules
  and ban list, not French Duel Commander or MTGO 1v1 Commander. First player skips their initial
  draw; both formats use London mulligans with no free mulligan. It is not multiplayer Commander.

The response binds SHA-256 of the exact request bytes and the installed/runtime identities, reports
both decks' coverage, then one numbered game with its actual starter, status and winner. Errors,
AI simulation failures, thinking timeouts or a technical winner never count as a completed result.
The internal timeout exits this JVM; the parent also needs its own process watchdog for a blocked
VM or process failure. No winner is inferred for incomplete games. Seeds are passed to XMage's
`RandomUtil`, but **reproducible replay is not established**: every result says `reproducible: false`.

## Explicit native qualification

The fixture suite's build/identity tests start no Java process. Real native qualification is separate:

```powershell
python scripts/xmage_qualify.py --allow-real-xmage --home C:\Tools\xmage --output C:\Scratch\xmage-proof
```

The script runs one JVM at a time with synthetic decks. It checks casual Sol Ring, exact double-faced
names, single and partner commanders, unknown cards, invalid partners and colors, timeout, and strict
protocol refusals. It records exact requests, native responses, stderr and a qualification receipt in
the chosen scratch directory. It neither downloads anything nor reads collection or saved deck data.

The bridge follows the official [AI testing entry point](https://github.com/magefree/mage/issues/10154)
and [game load-test implementation](https://github.com/magefree/mage/blob/master/Mage.Tests/src/test/java/org/mage/test/load/LoadTest.java).
Upstream notes that some card/AI combinations freeze or exhaust memory. Passing synthetic qualification
does not establish complete card coverage, strong play, seeded replay or household-device acceptance.
