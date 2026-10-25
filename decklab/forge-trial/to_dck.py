"""Convert one of our decklists to a Forge .dck file.

A Milestone 0 tool. Since phase 4 of Deck Lab's move to a database there are no deck .md or
product .csv files in magic/ (the paths below resolve only in the pre-db-decks and
pre-db-inventory tags). To convert a deck now, write a copy with
`python -m decklab.db deck pull DECK-ID -o <scratchpad>/DECK-ID.md` and give that path; for a
product, its list from `python -m decklab.db order show ORDER-ID --csv <product stem>` or
`inventory export`. Deck Lab
plays decks by id itself (`python -m decklab.lib.forge play`), with its own .dck writer.

Usage
-----
  From a deck file (magic/decks/<casual|commander>/<slug>.md):

    python to_dck.py magic/decks/casual/gruul-ramp.md --list owned -o gruul-owned.dck
    python to_dck.py magic/decks/casual/gruul-ramp.md --list target            # prints to stdout

      --list target   the first fenced block under the "## Decklist" heading (default)
      --list owned    the fenced block under the "### Owned-only version" heading
                      (falls back to target, with a warning on stderr, if the file has none)

  From a product card list (magic/products/*.csv):

    python to_dck.py magic/products/fdn-beginner-box.csv --deck Cats --deck Vampires -o cats-vampires.dck
    python to_dck.py magic/products/fdc-calling-all-angels.csv -o giada-precon.dck
    python to_dck.py magic/products/challenger-2019-lightning-aggro.csv --section deck -o lightning.dck

      --deck NAME     products with a "deck" column (Beginner Box halves, BLB Starter Kit):
                      pick one or more decks; repeat --deck to shuffle several into one Main
                      (e.g. a 40-card Beginner Box pairing). Required for those files.
      --section S     products with a "section" column (commander / deck / sideboard): keep only
                      these sections (repeatable). Default: all of them.

  Common options:
    -o, --out PATH    write the .dck here (default: stdout)
    --name NAME       deck name written to [metadata] Name= (default: the deck's "# " title, or
                      the product/deck names). Forge shows players as "Ai(<n>)-<Name>".
    --form FORM       how each card line is written (default: name):
                        name      "4 Llanowar Elves"                 (recommended, see below)
                        set       "4 Llanowar Elves|FDN"
                        set-art   "4 Llanowar Elves|FDN|1"           (the 3rd field is an ART INDEX)
                        set-num   "4 Llanowar Elves|FDN|[227]"       (collector number in brackets)
    --no-sideboard    leave out the [Sideboard] section

Why name-only (checked against Forge 2.0.15 source and by test, 2026-09-29)
----------------------------------------------------------------------------
- Printing does not matter to the simulation, and Forge resolves a bare name through its
  card-art preference. A set code Forge doesn't know (e.g. "|ZZZ") silently falls back to any
  printing (CardDb.tryGetCard), so set codes add nothing but risk.
- The same card on several lines (different printings, foil and non-foil) is merged into one
  line with the summed count.
- Double-faced cards: our files use Scryfall's "Front // Back". Forge accepts that full form ONLY
  for split cards (e.g. "Fire // Ice"); adventure, transform, MDFC and flip cards written that
  way are "unsupported" and silently dropped from the deck. Forge indexes every face name
  (CardDb.addCard), so this script always writes the FRONT face ("Murderous Rider"), which
  resolves for every layout, split cards included ("Fire" -> Fire // Ice).
- Foil markers (*F*) and collector numbers are dropped.

Card lines that Forge still can't find are reported by Forge on stderr as
  An unsupported card was requested: "<name>" from "<set>".
and are REMOVED from the deck before play (Deck.getValid), so always check for that line
(run_sim.py does).

Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import OrderedDict
from pathlib import Path

# "4 Card Name (SET) 123 *F*"; set, number and flag are optional ("9 Forest").
LINE_RE = re.compile(
    r"^(?P<qty>\d+)x?\s+(?P<name>.+?)"
    r"(?:\s+\((?P<set>[A-Za-z0-9]+)\)(?:\s+(?P<num>\S+))?)?"
    r"(?:\s+\*(?P<flag>[A-Za-z]+)\*)?\s*$"
)
SECTION_HEADERS = {"deck": "Main", "main": "Main", "sideboard": "Sideboard", "commander": "Commander"}
PRODUCT_SECTIONS = {"deck": "Main", "sideboard": "Sideboard", "commander": "Commander"}
SECTION_ORDER = ("Commander", "Main", "Sideboard")


class Card:
    __slots__ = ("qty", "name", "set", "num")

    def __init__(self, qty: int, name: str, set_code: str | None, num: str | None):
        self.qty, self.name, self.set, self.num = qty, name, set_code, num


def forge_name(name: str) -> str:
    """Scryfall name -> the name Forge resolves for every layout (front face of 'A // B')."""
    return name.split(" // ", 1)[0].strip() if " // " in name else name.strip()


def fenced_block_after(lines: list[str], heading_pred) -> list[str] | None:
    """Lines of the first fenced block after the first heading matching heading_pred."""
    i = 0
    while i < len(lines) and not (lines[i].startswith("#") and heading_pred(lines[i])):
        i += 1
    if i == len(lines):
        return None
    level = len(lines[i]) - len(lines[i].lstrip("#"))
    i += 1
    while i < len(lines):
        s = lines[i]
        if s.startswith("#") and (len(s) - len(s.lstrip("#"))) <= level:
            return None  # next section at the same or higher level: no block under this heading
        if s.strip().startswith("```"):
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            return block
        i += 1
    return None


def parse_decklist(block: list[str]) -> dict[str, list[Card]]:
    sections: dict[str, list[Card]] = {}
    current = "Main"
    for raw in block:
        s = raw.strip()
        if not s or s.startswith("//"):
            continue
        if s.lower() in SECTION_HEADERS:
            current = SECTION_HEADERS[s.lower()]
            continue
        m = LINE_RE.match(s)
        if not m:
            raise ValueError(f"can't parse decklist line: {raw!r}")
        sections.setdefault(current, []).append(
            Card(int(m["qty"]), m["name"], m["set"], m["num"]))
    return sections


def from_markdown(path: Path, which: str) -> tuple[str, dict[str, list[Card]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    title = next((l[2:].strip() for l in lines if l.startswith("# ")), path.stem)
    target = fenced_block_after(lines, lambda h: h.strip().lower() == "## decklist")
    if which == "owned":
        block = fenced_block_after(lines, lambda h: h.lstrip("#").strip().lower().startswith("owned-only version"))
        if block is None:
            print(f"warning: {path.name} has no '### Owned-only version' block; using the target list",
                  file=sys.stderr)
            block = target
        name = f"{title} (owned)"
    else:
        block = target
        name = title
    if block is None:
        raise SystemExit(f"error: no fenced decklist under '## Decklist' in {path}")
    return name, parse_decklist(block)


def from_product(path: Path, decks: list[str], keep_sections: list[str]) -> tuple[str, dict[str, list[Card]]]:
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit(f"error: {path} is empty")
    cols = rows[0].keys()
    sections: dict[str, list[Card]] = {}
    if "deck" in cols:
        available = list(OrderedDict.fromkeys(r["deck"] for r in rows))
        if not decks:
            raise SystemExit(f"error: {path.name} holds several decks; pick with --deck. Available: "
                             + ", ".join(available))
        lower = {d.lower(): d for d in available}
        missing = [d for d in decks if d.lower() not in lower]
        if missing:
            raise SystemExit(f"error: no deck {missing} in {path.name}. Available: " + ", ".join(available))
        chosen = {lower[d.lower()] for d in decks}
        for r in rows:
            if r["deck"] in chosen:
                sections.setdefault("Main", []).append(
                    Card(int(r["quantity"]), r["name"], r["set"], r["collector_number"]))
        name = " + ".join(lower[d.lower()] for d in decks)
    elif "section" in cols:
        keep = {s.lower() for s in keep_sections} if keep_sections else set(PRODUCT_SECTIONS)
        for r in rows:
            sec = r["section"].strip().lower()
            if sec not in PRODUCT_SECTIONS:
                raise SystemExit(f"error: unknown section {r['section']!r} in {path.name}")
            if sec in keep:
                sections.setdefault(PRODUCT_SECTIONS[sec], []).append(
                    Card(int(r["quantity"]), r["name"], r["set"], r["collector_number"]))
        name = path.stem
    else:
        raise SystemExit(f"error: {path.name} has no 'deck' or 'section' column, so it isn't a deck list")
    return name, sections


def render(name: str, sections: dict[str, list[Card]], form: str, sideboard: bool) -> str:
    out = ["[metadata]", f"Name={name.replace(chr(10), ' ')}"]
    for sec in SECTION_ORDER:
        if sec not in sections or (sec == "Sideboard" and not sideboard):
            continue
        merged: "OrderedDict[str, int]" = OrderedDict()
        for c in sections[sec]:
            fname = forge_name(c.name)
            if form == "name" or not c.set:
                key = fname
            elif form == "set":
                key = f"{fname}|{c.set.upper()}"
            elif form == "set-art":
                key = f"{fname}|{c.set.upper()}|1"
            else:  # set-num
                key = f"{fname}|{c.set.upper()}|[{c.num}]" if c.num else f"{fname}|{c.set.upper()}"
            merged[key] = merged.get(key, 0) + c.qty
        if not merged:
            continue
        out.append(f"[{sec}]")
        out.extend(f"{n} {k}" for k, n in merged.items())
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source", type=Path, help="deck .md file or product .csv file")
    ap.add_argument("--list", choices=("target", "owned"), default="target")
    ap.add_argument("--deck", action="append", default=[])
    ap.add_argument("--section", action="append", default=[])
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--name")
    ap.add_argument("--form", choices=("name", "set", "set-art", "set-num"), default="name")
    ap.add_argument("--no-sideboard", action="store_true")
    a = ap.parse_args(argv)

    if a.source.suffix.lower() == ".md":
        name, sections = from_markdown(a.source, a.list)
    elif a.source.suffix.lower() == ".csv":
        name, sections = from_product(a.source, a.deck, a.section)
    else:
        raise SystemExit("error: source must be a .md deck file or a .csv product list")
    text = render(a.name or name, sections, a.form, not a.no_sideboard)
    counts = {s: sum(c.qty for c in cs) for s, cs in sections.items()}
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {a.out} ({', '.join(f'{s} {n}' for s, n in counts.items())})", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
