"""Card support audit for Forge (Deck Lab Milestone 0 step 4).

Answers two questions for every card name we use:
  1. Does Forge have a working card script for it (and under which name)?
  2. Does the script tell Forge's AI to stay away from it (AI:RemoveDeck:...) or use an ability type
     the AI has no logic for? Those cards are "supported, but the AI plays them badly".

Usage (from this folder, decklab/forge-trial/)
-----
    python card_audit.py scan  [--json audit/audit.json]
        Collect every card name from every space's decks in the inventory (Deck Lab's database
        since phase 4: target + substitute lists, all sections), the product lists and, as the
        "pool" group, home's collection and the pending and received card orders; check each
        against Forge's card scripts (C:/Tools/forge/res/cardsfolder/cardsfolder.zip); write
        everything to the JSON.

    python card_audit.py decks [--json audit/audit.json] [--out decks/audit] [--chunk 153]
        Write load-test .dck files: every unique name once, in the form to_dck.py writes
        (front face of "A // B"), split into decks of --chunk names ("all-NN.dck"), plus
        "scryfall-dfc.dck" with every "A // B" name exactly as Scryfall spells it (plus 30 Swamp).

    python card_audit.py compare --load RUN.json [RUN.json ...] [--json audit/audit.json]
        Compare run_sim.py JSON outputs of the load test with the static check (the names Forge
        reported as unsupported vs the names the static check expects to fail).

    python card_audit.py report [--json audit/audit.json] [--md audit/lists.md] [--all audit/all-names.md]
        Write the full lists (markdown tables) for the notes, and one row per name to --all.

How Forge names and finds cards (read in forge-core at tag forge-2.0.15, 2026-09-29)
    - CardRules.Reader: "Name:" starts a face; "ALTERNATE" switches to face 2 and "SPECIALIZE:<colour>"
      to faces 3-7; lines that are empty or start with '#' are skipped. "AlternateMode:" is the
      layout (CardSplitType): only Split (split cards, rooms) has FaceSelectionMethod COMBINE, so its
      card name is "A // B"; every other layout (Transform, Modal, Adventure, Flip, Meld, Omen,
      Specialize) is named after its FRONT face.
    - CardDb indexes every face name too (addFaceToDbNames, addCard), case-insensitively, with
      accent-stripped aliases (StringUtils.stripAccents). So a front or back face name resolves,
      but "A // B" resolves only when the card really is Split.
    - Eager loading reads every .txt in cardsfolder.zip, including upcoming/ and rebalanced/
      (CardStorageReader.getZipEntries; the upcoming/ skip applies only to loose folders).
    - "AI:RemoveDeck:All|Random|NonCommander" set CardAiHints flags (CardRules.Reader.parseLine);
      any other "AI:" line is ignored. What they do in a sim game (forge-ai):
        All:  AiController.getSpellAbilityToPlay drops every spell/ability whose host card has it
              ("don't include removedAI cards"), unless the AI uses full simulation, which sim mode
              never turns on (GamePlayerUtil.createAiPlayer passes no AIOption). So the AI never
              casts such a card or activates its abilities through the normal path; lands, static and
              triggered abilities still work. Also scored -10 in ComputerUtilAbility.saEvaluator.
        Random: only deck generation, and ChangeZoneAi won't fetch such cards when choosing freely.
        NonCommander: only deck generation (kept out of non-Commander random decks).
    - SpellApiToAi maps each ability type (ApiType) to its AI class. Types mapped to CannotPlayAi,
      and types with no mapping at all (they fall back to CannotPlayAi and print
      "No AI assigned for API: X" on stderr), are never chosen: a spell or activated ability whose
      chain (SP$/AB$ plus SubAbility$ DB$ ...) contains one is never played
      (SpellAbilityAi.canPlayWithSubs -> chkDrawbackWithSubs), and optional triggers using one are
      declined (doTriggerNoCost). Mandatory triggers still resolve.

The decks (every space's), product lists, collection and orders come from the inventory
(decklab.lib.inventory's current(), the backend config.json names: since phase 3 the database,
and since phase 4 for the decks too, so run it with the repo's .venv Python,
../../.venv/Scripts/python). Otherwise standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))       # decklab.lib.inventory
sys.path.insert(0, str(HERE))
import to_dck  # noqa: E402  (same folder)

DEFAULT_ZIP = Path("C:/Tools/forge/res/cardsfolder/cardsfolder.zip")
DEFAULT_JSON = HERE / "audit" / "audit.json"

# ApiTypes whose AI is CannotPlayAi in forge-ai SpellApiToAi.java (forge-2.0.15), plus ApiTypes
# declared in forge-game ApiType.java with no entry in that map (fallback CannotPlayAi).
CANNOT_PLAY_MAPPED = {"ControlPlayer", "ControlSpell", "ExchangeControlVariant", "GainOwnership",
                      "GameDrawn", "ManaReflected", "MultiplePiles", "PlayLandVariant",
                      "RemoveCounterAll", "InternalIgnoreEffect"}
CANNOT_PLAY_UNMAPPED = {"Block", "ChangeText", "ChangeZoneResolve", "Empower", "ExchangeTextBox",
                        "Incubate", "Intensify", "LookAt", "Recruit", "SwitchBlock"}
CANNOT_PLAY = CANNOT_PLAY_MAPPED | CANNOT_PLAY_UNMAPPED

RE_API = re.compile(r"^\s*(SP|AB|DB)\$\s*([A-Za-z]+)")
RE_SUB = re.compile(r"\bSubAbility\$\s*([\w.]+)")
RE_EXECUTE = re.compile(r"\bExecute\$\s*([\w.]+)")
SPECIALIZE_FACE = {"WHITE": 2, "BLUE": 3, "BLACK": 4, "RED": 5, "GREEN": 6}


def norm(name: str) -> str:
    """Forge's lookup key: accents stripped (StringUtils.stripAccents), case-insensitive."""
    decomposed = unicodedata.normalize("NFD", name)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower().strip()


# --------------------------------------------------------------------------- collection

def collect(repo: Path) -> dict[str, list[dict]]:
    """Scryfall name -> list of uses (group deck / product / pool), all from the inventory (repo
    is kept for the callers)."""
    uses: dict[str, list[dict]] = defaultdict(list)
    from decklab.lib import inventory
    inv = inventory.current()
    # Every space's decks, from the inventory (the database since phase 4: there are no deck files).
    found = sorted(inv.decks.values(), key=lambda d: d.id)
    if not found:
        print("warning: the inventory has no decks: the audit covers only the products and the pool",
              file=sys.stderr)
    for deck in found:
        if deck.error:
            print(f"warning: deck {deck.id}: {deck.error}", file=sys.stderr)
            continue
        lines = deck.text.splitlines()
        blocks = {
            "target": to_dck.fenced_block_after(lines, lambda h: h.strip().lower() == "## decklist"),
            "owned": to_dck.fenced_block_after(
                lines, lambda h: h.lstrip("#").strip().lower().startswith(("substitute version",
                                                                         "owned-only version"))),
        }
        for which, block in blocks.items():
            if block is None:
                print(f"warning: {deck.id} has no {which} list", file=sys.stderr)
                continue
            for section, cards in to_dck.parse_decklist(block).items():
                for c in cards:
                    uses[c.name].append({"group": "deck", "source": deck.id,
                                         "list": which, "section": section, "qty": c.qty})
    for product in inv.products:
        if product.error:
            print(f"warning: product {product.stem}: {product.error}", file=sys.stderr)
            continue
        cols = product.columns or ()
        for r in product.items:
            if "deck" in cols:
                part, section = r.get("deck"), "Main"
            elif "section" in cols:
                raw = r.get("section") or ""
                part, section = None, to_dck.PRODUCT_SECTIONS.get(raw.strip().lower(), raw)
            else:
                part, section = None, "card list"
            uses[r.name].append({"group": "product", "source": product.stem, "part": part,
                                 "section": section, "qty": r.qty or 0})
    pool = [("collection.csv", inv.collection())]
    card_folders = {"magic/orders", "magic/orders/received"}
    pool += [(rel.removeprefix("magic/"), sheet) for rel, sheet in sorted(inv.payloads.items())
             if rel.rsplit("/", 1)[0] in card_folders]
    for src, sheet in pool:
        for r in sheet.rows:
            uses[r.name].append({"group": "pool", "source": src, "set": r.get("set"), "qty": r.qty or 0})
    return uses


# --------------------------------------------------------------------------- Forge scripts

def parse_script(text: str, path: str) -> dict:
    """Mirror of CardRules.Reader for the fields we need."""
    faces: list[dict | None] = [None] * 7
    cur = 0
    alt_mode = None
    ai_lines: list[str] = []
    comments: list[str] = []
    placeholder: dict[int, str] = {}

    def face(i: int) -> dict:
        if faces[i] is None:
            faces[i] = {"name": placeholder.get(i), "A": [], "T": [], "SVar": {}}
        return faces[i]

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line:
            continue
        if line.startswith("#"):
            comments.append(line)
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if key == "Name":
            faces[cur] = {"name": value, "A": [], "T": [], "SVar": {}}
        elif key == "ALTERNATE":
            cur = 1
        elif key.startswith("SPECIALIZE"):
            cur = SPECIALIZE_FACE.get(value, cur)
        elif key == "AlternateMode":
            alt_mode = value
        elif key == "CopyFaceFrom":
            placeholder[cur] = value
            face(cur)["name"] = value
        elif key == "AI":
            ai_lines.append(value)
        elif key == "A":
            face(cur)["A"].append(value)
        elif key == "T":
            face(cur)["T"].append(value)
        elif key == "SVar":
            var, _, sval = value.partition(":")
            face(cur)["SVar"][var] = sval
    names = [f["name"] for f in faces if f and f["name"]]
    main = faces[0]["name"] if faces[0] else None
    if alt_mode and alt_mode.lower() == "split" and faces[1] and faces[1]["name"]:
        canonical = f"{main} // {faces[1]['name']}"
    else:
        canonical = main
    remove = sorted({v.split(":", 1)[1] for v in ai_lines
                     if v.startswith("RemoveDeck:") and v.split(":", 1)[1].lower() in
                     ("all", "random", "noncommander")})
    ignored_ai = [v for v in ai_lines if not (v.startswith("RemoveDeck:") and v.split(":", 1)[1].lower()
                                              in ("all", "random", "noncommander"))]
    return {"path": path, "name": canonical, "faces": names, "alt_mode": alt_mode,
            "remove_deck": remove, "ai_lines_ignored_by_forge": ignored_ai, "comments": comments,
            "cannot_play": cannot_play(faces)}


def _chain_apis(first: str, svars: dict[str, str], seen: set[str] | None = None) -> list[str]:
    """ApiTypes of an ability line and its SubAbility$ chain."""
    seen = seen if seen is not None else set()
    out = []
    m = RE_API.match(first)
    if m:
        out.append(m[2])
    for sub in RE_SUB.findall(first):
        if sub in seen or sub not in svars:
            continue
        seen.add(sub)
        out.extend(_chain_apis(svars[sub], svars, seen))
    return out


def cannot_play(faces: list[dict | None]) -> list[dict]:
    """Abilities whose chain uses an ApiType the AI can't play (see module docstring)."""
    found = []
    for f in faces:
        if not f:
            continue
        for a in f["A"]:
            apis = _chain_apis(a, f["SVar"])
            bad = [x for x in apis if x in CANNOT_PLAY]
            if bad:
                kind = "spell" if a.lstrip().startswith("SP$") else "activated ability"
                found.append({"face": f["name"], "kind": kind, "apis": bad, "line": a[:160]})
        for t in f["T"]:
            for ex in RE_EXECUTE.findall(t):
                if ex in f["SVar"]:
                    apis = _chain_apis(f["SVar"][ex], f["SVar"])
                    bad = [x for x in apis if x in CANNOT_PLAY]
                    if bad:
                        optional = "OptionalDecider$" in t
                        found.append({"face": f["name"], "kind": "optional trigger" if optional else "trigger",
                                      "apis": bad, "line": t[:160]})
    return found


def load_forge(zip_path: Path) -> tuple[dict, dict, dict, int]:
    """(by canonical name key, by face name key, duplicates, script count)."""
    all_recs: dict[str, list[dict]] = defaultdict(list)
    count = 0
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            if n.endswith("/") or not n.endswith(".txt"):
                continue
            count += 1
            rec = parse_script(z.read(n).decode("utf-8", "replace"), n)
            if rec["name"]:
                all_recs[norm(rec["name"])].append(rec)
    # Two scripts with one name: StaticData puts both into a map keyed by name (one wins). Report
    # them, and use the one in a main a-z folder (fewest path parts) for the checks.
    by_name = {k: min(v, key=lambda r: r["path"].count("/")) for k, v in all_recs.items()}
    dupes = {v[0]["name"]: [r["path"] for r in v] for v in all_recs.values() if len(v) > 1}
    by_face: dict[str, dict] = {}
    for rec in by_name.values():
        for fname in rec["faces"]:
            by_face.setdefault(norm(fname), rec)
    # Non-front faces that share a name with another card (e.g. "Emeritus of Conflict // Lightning
    # Bolt"). CardDb indexes them under that name too, but a name-only request tries exact primary
    # names first (CardDb.tryToGetCardFromEditions -> getAllCardsNoAlt), so "Lightning Bolt" stays
    # Lightning Bolt (tested 2026-09-29, card-audit.md).
    for rec in by_name.values():
        for fname in rec["faces"][1:]:
            other = by_name.get(norm(fname))
            if other is not None and other is not rec:
                other.setdefault("also_face_of", []).append(rec["name"])
    return by_name, by_face, dupes, count


def resolve(name: str, by_name: dict, by_face: dict) -> dict:
    """How Forge resolves a Scryfall name (static)."""
    k = norm(name)
    if k in by_name:
        rec = by_name[k]
        how = "exact" if rec["name"] == name else "case/accent differs"
        return {"status": "supported", "how": how, "forge_name": rec["name"], "rec": rec}
    if " // " in name:
        front, back = (p.strip() for p in name.split(" // ", 1))
        rf = by_name.get(norm(front)) or by_face.get(norm(front))
        rb = by_face.get(norm(back))
        if rf:
            how = "front face (Scryfall 'A // B' is not a Forge card name)"
            if rb is not rf:
                how += "; back face NOT found on the same script"
            return {"status": "supported", "how": how, "forge_name": rf["name"], "rec": rf}
        return {"status": "unsupported", "how": "no script for 'A // B' or its front face", "forge_name": None, "rec": None}
    if k in by_face:
        rec = by_face[k]
        return {"status": "supported", "how": "face of another card", "forge_name": rec["name"], "rec": rec}
    return {"status": "unsupported", "how": "no script with this Name", "forge_name": None, "rec": None}


# --------------------------------------------------------------------------- commands

def cmd_scan(a) -> int:
    uses = collect(REPO)
    by_name, by_face, dupes, n_scripts = load_forge(a.zip)
    cards = []
    for name in sorted(uses, key=str.lower):
        r = resolve(name, by_name, by_face)
        # what to_dck.py writes, and whether that resolves to the same script
        dck = to_dck.forge_name(name)
        rd = resolve(dck, by_name, by_face)
        rec = r["rec"]
        groups = sorted({u["group"] for u in uses[name]})
        cards.append({
            "name": name, "groups": groups, "uses": uses[name],
            "status": r["status"], "how": r["how"], "forge_name": r["forge_name"],
            "dck_name": dck, "dck_resolves_same": rd["rec"] is rec and rec is not None,
            "script": rec["path"] if rec else None,
            "alt_mode": rec["alt_mode"] if rec else None,
            "faces": rec["faces"] if rec else None,
            "remove_deck": rec["remove_deck"] if rec else [],
            "ai_lines_ignored_by_forge": rec["ai_lines_ignored_by_forge"] if rec else [],
            "cannot_play": rec["cannot_play"] if rec else [],
            "comments": rec["comments"] if rec else [],
            "duplicate_scripts": dupes.get(rec["name"]) if rec else None,
            "also_face_of": rec.get("also_face_of", []) if rec else [],
        })
    out = {"zip": str(a.zip), "scripts": n_scripts, "forge_names": len(by_name),
           "cannot_play_apis": {"mapped": sorted(CANNOT_PLAY_MAPPED), "unmapped": sorted(CANNOT_PLAY_UNMAPPED)},
           "cards": cards}
    a.json.parent.mkdir(parents=True, exist_ok=True)
    a.json.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    def cnt(pred):
        return sum(1 for c in cards if pred(c))
    for grp in ("deck", "product", "pool"):
        g = [c for c in cards if grp in c["groups"]]
        print(f"{grp:8s} names={len(g):4d} unsupported={sum(c['status'] != 'supported' for c in g)} "
              f"RemoveDeck:All={sum('All' in c['remove_deck'] for c in g)} "
              f"RemoveDeck:Random={sum('Random' in c['remove_deck'] for c in g)} "
              f"cannot_play={sum(bool(c['cannot_play']) for c in g)}")
    print(f"total names={len(cards)} unsupported={cnt(lambda c: c['status'] != 'supported')} "
          f"scripts={n_scripts} forge_names={len(by_name)} -> {a.json}")
    return 0


def _load(a) -> dict:
    return json.loads(a.json.read_text(encoding="utf-8"))


def cmd_decks(a) -> int:
    data = _load(a)
    a.out.mkdir(parents=True, exist_ok=True)
    for old in a.out.glob("*.dck"):
        old.unlink()
    names = sorted({c["dck_name"] for c in data["cards"]}, key=str.lower)
    written = []
    for i in range(0, len(names), a.chunk):
        part = names[i:i + a.chunk]
        idx = i // a.chunk + 1
        p = a.out / f"all-{idx:02d}.dck"
        p.write_text("\n".join(["[metadata]", f"Name=Audit {idx:02d}", "[Main]"] + [f"1 {n}" for n in part]) + "\n",
                     encoding="utf-8", newline="\n")
        written.append((p.name, len(part)))
    dfc = sorted({c["name"] for c in data["cards"] if " // " in c["name"]}, key=str.lower)
    p = a.out / "scryfall-dfc.dck"
    # 30 Swamps keep it a playable deck after Forge drops the names it can't find.
    p.write_text("\n".join(["[metadata]", "Name=Audit Scryfall DFC names", "[Main]"] + [f"1 {n}" for n in dfc]
                           + ["30 Swamp"]) + "\n", encoding="utf-8", newline="\n")
    written.append((p.name, len(dfc)))
    for n, k in written:
        print(f"{a.out / n}: {k} names")
    print(f"{len(names)} unique .dck names from {len(data['cards'])} Scryfall names")
    return 0


def cmd_compare(a) -> int:
    data = _load(a)
    reported: set[str] = set()
    no_ai: set[str] = set()
    for f in a.load:
        run = json.loads(Path(f).read_text(encoding="utf-8"))
        reported |= set(run.get("unsupported_cards") or [])
        log = run.get("log")
        if log and Path(log).is_file():
            for line in Path(log).read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("No AI assigned for API:"):
                    no_ai.add(line.strip())
    dck_expected = {c["dck_name"] for c in data["cards"] if not c["dck_resolves_same"]}
    raw_expected = {c["name"] for c in data["cards"] if " // " in c["name"]
                    and not (c["status"] == "supported" and norm(c["forge_name"]) == norm(c["name"]))}
    print("expected unsupported (to_dck form):", sorted(dck_expected))
    print("expected unsupported (Scryfall 'A // B' form):", sorted(raw_expected))
    print("Forge reported unsupported:", sorted(reported))
    print("match (to_dck + Scryfall forms):", reported == (dck_expected | raw_expected))
    print("only in Forge:", sorted(reported - dck_expected - raw_expected))
    print("only static:", sorted((dck_expected | raw_expected) - reported))
    print("No AI assigned lines:", sorted(no_ai))
    return 0


def _uses_short(c: dict, group: str) -> str:
    seen = []
    for u in c["uses"]:
        if u["group"] != group:
            continue
        if group == "deck":
            s = u["source"].split("/", 1)[1]
            lists = sorted({x["list"] for x in c["uses"] if x["group"] == "deck" and x["source"] == u["source"]})
            secs = sorted({x["section"] for x in c["uses"] if x["group"] == "deck" and x["source"] == u["source"]})
            tag = s + (" (" + "+".join(lists) + ("; " + "/".join(secs) if secs != ["Main"] else "") + ")")
        elif group == "product":
            tag = u["source"] + (f": {u['part']}" if u.get("part") else "") + \
                (f" [{u['section']}]" if u["section"] not in ("Main", "card list") else "")
        else:
            tag = u["source"]
        if tag not in seen:
            seen.append(tag)
    return "; ".join(seen)


def cmd_report(a) -> int:
    data = _load(a)
    cards = data["cards"]
    L: list[str] = []

    def table(title: str, rows: list[dict], cols: list[tuple[str, callable]]):
        L.append(f"### {title} ({len(rows)})\n")
        if not rows:
            L.append("None.\n")
            return
        L.append("| " + " | ".join(h for h, _ in cols) + " |")
        L.append("|" + "---|" * len(cols))
        for r in rows:
            L.append("| " + " | ".join(str(f(r)).replace("|", "\\|") for _, f in cols) + " |")
        L.append("")

    def used_in(c):
        parts = []
        for g in ("deck", "product", "pool"):
            s = _uses_short(c, g)
            if s:
                parts.append(s)
        return " / ".join(parts)

    for grp, label in (("deck", "deck files"), ("product", "product lists"), ("pool", "collection + orders")):
        g = [c for c in cards if grp in c["groups"]]
        L.append(f"- {label}: {len(g)} names")
    L.append("")
    main_scope = [c for c in cards if {"deck", "product"} & set(c["groups"])]
    pool_only = [c for c in cards if c["groups"] == ["pool"]]

    table("Unsupported (decks + products)", [c for c in main_scope if c["status"] != "supported"],
          [("Name", lambda c: c["name"]), ("Why", lambda c: c["how"]), ("Used in", used_in)])
    table("Unsupported (collection/orders only)", [c for c in pool_only if c["status"] != "supported"],
          [("Name", lambda c: c["name"]), ("Why", lambda c: c["how"]), ("Used in", used_in)])
    table("Naming differences (Scryfall name is not Forge's card name)",
          [c for c in cards if c["status"] == "supported" and c["how"] != "exact"],
          [("Scryfall name", lambda c: c["name"]), ("Forge name", lambda c: c["forge_name"]),
           ("Layout", lambda c: c["alt_mode"] or "-"), ("How it resolves", lambda c: c["how"]),
           ("to_dck writes", lambda c: c["dck_name"] + ("" if c["dck_resolves_same"] else " (FAILS)")),
           ("Used in", used_in)])
    table("Split cards: full 'A // B' is Forge's name", [c for c in cards if (c["alt_mode"] or "").lower() == "split"],
          [("Name", lambda c: c["name"]), ("Used in", used_in)])
    for flag, title in (("All", "AI:RemoveDeck:All: the AI never casts or activates these"),
                        ("Random", "AI:RemoveDeck:Random: only kept out of random decks"),
                        ("NonCommander", "AI:RemoveDeck:NonCommander")):
        for scope_name, scope in (("decks + products", main_scope), ("collection/orders only", pool_only)):
            table(f"{title} ({scope_name})", [c for c in scope if flag in c["remove_deck"]],
                  [("Name", lambda c: c["name"]), ("Script", lambda c: c["script"]), ("Used in", used_in)])
    # Per deck / product deck: flagged cards with their counts.
    per: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for c in cards:
        for flag in c["remove_deck"]:
            for u in c["uses"]:
                if u["group"] == "deck":
                    key = f"{u['source']} ({u['list']})"
                elif u["group"] == "product":
                    key = f"product {u['source']}" + (f": {u['part']}" if u.get("part") else "")
                else:
                    continue
                sec = "" if u["section"] in ("Main", "card list") else f" [{u['section']}]"
                per[key][flag].append(f"{u['qty']} {c['name']}{sec}")
    rows = [{"key": k, **{f: "; ".join(v.get(f, [])) or "-" for f in ("All", "Random", "NonCommander")}}
            for k, v in sorted(per.items())]
    table("Flagged cards per deck (quantities as listed)", rows,
          [("Deck (list)", lambda r: r["key"]), ("RemoveDeck:All", lambda r: r["All"]),
           ("RemoveDeck:Random", lambda r: r["Random"]), ("RemoveDeck:NonCommander", lambda r: r["NonCommander"])])
    table("Abilities using an ApiType with no AI (CannotPlayAi)", [c for c in cards if c["cannot_play"]],
          [("Name", lambda c: c["name"]),
           ("Ability", lambda c: "; ".join(f"{x['kind']}: {'+'.join(x['apis'])}" for x in c["cannot_play"])),
           ("RemoveDeck", lambda c: ",".join(c["remove_deck"]) or "-"), ("Used in", used_in)])
    table("Other AI: lines (ignored by Forge's parser)", [c for c in cards if c["ai_lines_ignored_by_forge"]],
          [("Name", lambda c: c["name"]), ("Lines", lambda c: "; ".join(c["ai_lines_ignored_by_forge"]))])
    table("Scripts with comment lines", [c for c in cards if c["comments"]],
          [("Name", lambda c: c["name"]), ("Comments", lambda c: " ".join(c["comments"])[:200])])
    table("Names that are also another card's back face (Forge picks the real card; tested)",
          [c for c in cards if c.get("also_face_of")],
          [("Name", lambda c: c["name"]), ("Also a face of", lambda c: ", ".join(c["also_face_of"])),
           ("Used in", used_in)])
    table("Names with more than one script", [c for c in cards if c["duplicate_scripts"]],
          [("Name", lambda c: c["name"]), ("Scripts", lambda c: ", ".join(c["duplicate_scripts"]))])
    table("Scripts outside the main folders (upcoming/, rebalanced/)",
          [c for c in cards if c["script"] and c["script"].count("/") > 1],
          [("Name", lambda c: c["name"]), ("Script", lambda c: c["script"])])
    a.md.parent.mkdir(parents=True, exist_ok=True)
    a.md.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {a.md} ({len(L)} lines)")
    # Appendix: every name, one row each.
    A = ["| # | Scryfall name | Forge script | In | AI flags |", "|---|---|---|---|---|"]
    for i, c in enumerate(cards, 1):
        flags = ", ".join(f"RemoveDeck:{f}" for f in c["remove_deck"]) or ""
        if c["cannot_play"]:
            flags += (", " if flags else "") + "CannotPlayAi"
        script = c["script"] or "NONE"
        if c["how"] != "exact":
            script += f" (as {c['forge_name']})" if c["forge_name"] else ""
        A.append(f"| {i} | {c['name']} | {script} | {'+'.join(c['groups'])} | {flags} |")
    a.all.write_text("\n".join(A) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {a.all} ({len(cards)} names)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Forge card support audit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    s.add_argument("--json", type=Path, default=DEFAULT_JSON)
    s.set_defaults(fn=cmd_scan)
    d = sub.add_parser("decks")
    d.add_argument("--json", type=Path, default=DEFAULT_JSON)
    d.add_argument("--out", type=Path, default=HERE / "decks" / "audit")
    d.add_argument("--chunk", type=int, default=153)
    d.set_defaults(fn=cmd_decks)
    c = sub.add_parser("compare")
    c.add_argument("--json", type=Path, default=DEFAULT_JSON)
    c.add_argument("--load", nargs="+", required=True)
    c.set_defaults(fn=cmd_compare)
    r = sub.add_parser("report")
    r.add_argument("--json", type=Path, default=DEFAULT_JSON)
    r.add_argument("--md", type=Path, default=HERE / "audit" / "lists.md")
    r.add_argument("--all", type=Path, default=HERE / "audit" / "all-names.md")
    r.set_defaults(fn=cmd_report)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
