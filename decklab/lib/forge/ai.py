"""AI limits: the cards Forge's AI can't play in a list (their script leaves them out, or
it never cast them in enough games), whether a Commander deck's commander is one, the
team pump flag, and (2026-10-03, the simulation report's R19) whether Forge pilots the
list poorly: the cards its scripts put in the kinds Forge's AI is known to misplay. The
Scryfall card lookups (_card_fields, _is_land), _merged_cards and _side_cards moved down
to cardstats.py and saved.py in Milestone 8 (the per-card stats need them, and come
before this part); ai._is_land and the rest still work."""
import re
import threading
import zipfile
from pathlib import Path

from decklab.lib import cards

from . import common, install, overrides
from .cardstats import _card_fields, _is_land, _merged_cards
from .common import ForgeError, forge_name, norm
from .lists import _list_text, _section_cards
from .saved import _counted, _pooled, _pooled_cards, _side_cards, _stored

MIN_GAMES_NEVER_CAST = 100

TEAM_PUMP_TAGS = ("power-boost-to-all", "overrun")
TEAM_PUMP_MIN = 3               # copies in the main deck that flag it
TAG_FILE = None                 # None: cards' downloaded oracle_tags file; the tests point it at a fixture

# How well Forge pilots a list (R19). The kinds of card Forge 2.0.15's AI was shown to misplay by
# reading its source (decklab/forge-trial/sim-investigation/r4-ai/notes.md section 2), each found in
# a card's script; the order is the order a card's reasons are given in.
#   remove_all      AI:RemoveDeck:All: the AI never uses it (AiController.java:1568).
#   etb             a "when this enters" ability the AI must use, and won't when it does nothing
#                   useful, stops it casting the card (AiController.checkETBEffects, :296-362, and
#                   :992-994). Only the patterns confirmed there: a creature whose ability shrinks the
#                   opponent's team ("curse", Massacre Wurm), destroys all of something ("destroy_all",
#                   Sunblast Angel; also a permanent whose ability ends that way, Fires of Mount Doom),
#                   targets "up to" one card ("up_to", Samwise the Stouthearted), or must target the
#                   opponent's things ("no_target": held without a target unless the AI is in danger,
#                   Éowyn, Palace Jailer).
#   flash           a flash creature with no enters ability: cast only at the opponent's end step, with
#                   mana left over (PermanentCreatureAi.java:67-186).
#   team_pump       a spell ("spell") or a permanent's ability ("ability") that pumps the whole team:
#                   judged one creature at a time (PumpAllAi.java:131-133).
#   strict_targets  a removal spell whose AITgts the AI follows strictly (DestroyAi.java:153), such as
#                   only permanents of mana value 4 or more.
#   counterspell    the AI never keeps mana open for it (r4 section 2.8).
WEAK_KINDS = ("remove_all", "etb", "flash", "team_pump", "strict_targets", "counterspell")
CAST_KINDS = ("remove_all", "etb", "flash")     # kinds that stop or put off casting the card itself
HALF_KINDS = ("counterspell",)  # counted as half a copy: still cast 52-74% of the time (r4 section 3)
TEAM_PUMP_FIX = "team-pump-1"   # the pilot switch that fixes team pumps (wave 3, decklab/TeamPumpAi)
PILOT_SHARE = 4 / 60            # copies in the weak kinds (per card in the list) that flag it: 4 in 60
# A creature held for a target ("etb" "no_target": Ravenous Chupacabra, Éowyn, Palace Jailer) counts as a
# whole copy, unlike a counterspell, though r4 calls holding either one reasonable or partly so (sections
# 2.5 and 2.8). The Free Peoples' flag depends on it (3 of its 5 copies), and 2 of Mono-Black Midrange's 3
# (of 4 needed) are Chupacabras, so a retune of HALF_KINDS or PILOT_SHARE should look at both decks.


def _types(card):
    """Every type line of a card: its own and each face's."""
    lines = [card.get("type_line") or ""] + [f.get("type_line") or "" for f in card.get("faces", [])]
    return " ".join(lines)


# ============================================================ AI limits

def _index_or_problem(problems):
    """script_index(), or None with the reason added to problems."""
    try:
        return install.script_index()
    except ForgeError as e:
        problems.append(f"{e.args[0].rstrip('.')}, so the cards its AI can't play aren't known.")
        return None


def _cannot_play(rows, index, casts=None, lands=None, games=0, card_data=None):
    """(cannot_play, unknown) of rows (_merged_cards): the cards whose script Forge's AI
    leaves out (with index, and Deck Lab's deployed overrides in place of Forge's scripts:
    overrides.overlay_index, so an adopted "remove" set clears Devout Decree's flag), then,
    once games reaches MIN_GAMES_NEVER_CAST, the
    nonland ones never cast or played. When card_data (saved._pooled_cards of the same
    sides) covers every one of the games, a never_cast card of the Main deck also says
    how many of them it was drawn in ("drawn_games", so "drawn in N of its games"); it's
    listed by the same rule either way."""
    cannot, unknown = [], []
    index = overrides.overlay_index(index) if index is not None else None
    for name, dck_name, qty, section in rows if index is not None else ():
        card = index["names"].get(norm(dck_name))
        if card is None:
            unknown.append({"name": name, "qty": qty})
        elif card in index["remove_all_set"]:
            cannot.append({"name": name, "qty": qty, "why": "script"})
    if casts is not None and games >= MIN_GAMES_NEVER_CAST:
        listed_already = {c["name"] for c in cannot}
        # Only when every game has a card log: games played before it (or without it) would
        # leave N short of what the page's "never cast in its games" counts. The games whose
        # card log failed its checks ("bad", normally none) are covered but not in N.
        covered = card_data and card_data["games"] and card_data["games"] + card_data["bad"] == games
        drawn = card_data["rows"] if covered else None
        for name, dck_name, qty, section in rows:
            if name in listed_already or casts.get(dck_name, [0, 0])[0] or (lands or {}).get(dck_name):
                continue
            if _is_land(name):
                continue
            never = {"name": name, "qty": qty, "why": "never_cast"}
            if drawn is not None and section == "Main":
                never["drawn_games"] = drawn.get(dck_name, [0])[0]
            cannot.append(never)
    return cannot, unknown


def _limits(listed, kind, casts=None, lands=None, games=0, card_data=None, pilot=None):
    """AiLimits for a list ({"Commander": [[qty, name]], "Main": [...]}); "pilot" is _pilot()'s
    (None, with the reason in "problem", when Forge's card scripts can't be read). pilot (wave
    3) is the list's AI pilot ({"profile", "switches"}, None: the default one): with the
    team-pump fix, its team pumps aren't held against it."""
    problems = []
    index = _index_or_problem(problems)
    rows = _merged_cards(listed or {}, kind)
    cannot, unknown = _cannot_play(rows, index, casts, lands, games, card_data)
    commanders = {forge_name(n) for _, n in (listed or {}).get("Commander", [])}
    unplayable = kind == "commander" and any(forge_name(c["name"]) in commanders for c in cannot)
    team_pump = None
    try:
        tags = cards.tag_members(TEAM_PUMP_TAGS, TAG_FILE)
        pump_ids = frozenset().union(*tags.values())
        pump = []
        for name, dck_name, qty, section in rows:
            if section != "Main":
                continue
            card = _card_fields(name)
            if card and card["oracle_id"] in pump_ids and re.search(r"\b(Instant|Sorcery)\b", _types(card)):
                pump.append({"name": name, "qty": qty})
        copies = sum(c["qty"] for c in pump)
        if copies >= TEAM_PUMP_MIN:
            team_pump = {"copies": copies, "cards": pump}
    except (OSError, KeyError, ValueError) + cards.INDEX_ERRORS:
        problems.append("Scryfall's oracle tags couldn't be read, so team pump spells weren't counted.")
    played_by, pilot = pilot, None
    if index is not None:
        try:
            pilot = _pilot(rows, index, weak_cards(), kind, unplayable, played_by)
        except ForgeError as e:
            problems.append(f"{e.args[0].rstrip('.')}, so how well Forge pilots it isn't known.")
    return {"cannot_play": cannot, "commander_unplayable": unplayable, "team_pump": team_pump,
            "pilot": pilot, "unknown": unknown, "problem": " ".join(problems) or None, "games": games}


def ai_limits(sections, kind, results=None, pilot=None):
    """AiLimits for a list (sections as decks.load_deck gives them, kind "commander" or
    "constructed"). Without results, as before any game ("games" 0). With results
    (stored results, as load() gives them), also the cards it never cast in them: every
    side of them with this list's card_sha (both sides of a mirror, each once) adds its
    casts, land plays and counted games ("games"), and once those reach
    MIN_GAMES_NEVER_CAST, a nonland card cast or played in none of them is never_cast
    (with "drawn_games" from the card log's tallies of those sides, when every one of
    their games was played with it). results are pooled as given: the caller picks them
    (list_ai, today's engine's).
    Never raises for a missing Forge: it then says so in "problem". pilot: the list's AI pilot
    (wave 3; None the default), for _pilot's team-pump fix."""
    listed = _section_cards(sections)
    if results is None:
        return _limits(listed, kind, pilot=pilot)
    sha = _list_text(listed, kind)[1]
    casts, lands, games, card_data = {}, {}, 0, None
    for result in results:
        for side, s in enumerate(result["sides"]):
            if s["card_sha"] == sha:
                _pooled(result, side, casts, lands)
                card_data = _pooled_cards(result, side, card_data)
                games += _counted(result)
    return _limits(listed, kind, casts, lands, games, card_data, pilot)


def list_ai(sections, kind, results_dir=None, pilot=None, *, keep=None):
    """ai_limits() over the saved results this list played with today's engine: what Forge's
    AI can't play in it, judged by all those games (the deck page's). A result counts when
    its side with this list has today's decklab-kind side id (engine.side_ids: the card log's,
    whatever its state now), or today's id of the kind runs play now (the plain kind's while
    the card log is off: its casts count, it has no card data). Results of other engines
    (before wave 2, another Forge version or setting) are left out, as the per-card numbers
    leave them out (cardstats.list_cards), and their sides' counted games are
    "other_engine_games" (so the page can say why the never-cast check waits for games
    when the list has plenty of earlier ones); "other_engine_commander_unplayable" is
    whether its commander was never cast in one of those results (the page says so rather
    than an all-clear while today's engine hasn't played it). pilot (wave 3): the list's AI pilot (None: the
    default one), whose side ids count (engine.side_ids). keep(result), when supplied, excludes
    private evidence before both current-engine and earlier-engine totals are counted."""
    from . import engine        # engine.py comes before this part; only this function uses it
    sha = _list_text(_section_cards(sections), kind)[1]
    with engine.held():
        # The list's names come from its .dck in the decks folder, as cardstats.list_cards' do, so the deck
        # page's two consumers always agree (engine.side_ids).
        ids = engine.side_ids(sha, kind, pilot)
        wanted = {ids[engine.KIND_DECKLAB], ids[engine.today()["kind"]]}
    results, other, other_commander = [], 0, False
    for r in _stored(results_dir):
        if keep is not None and not keep(r):
            continue
        mine = [s for s in r["sides"] if s["card_sha"] == sha]
        if any(s.get("engine_id") in wanted for s in mine):
            results.append(r)
        else:
            other += _counted(r) * len(mine)
            other_commander = other_commander or any(
                _commander_unplayable(r, i) for i, s in enumerate(r["sides"]) if s["card_sha"] == sha)
    limits = ai_limits(sections, kind, results, pilot)
    limits["other_engine_games"] = other
    limits["other_engine_commander_unplayable"] = other_commander
    return limits


def side_ai(result, side):
    """AiLimits for side 0 or 1 of a stored result, including the cards it never cast
    once it has MIN_GAMES_NEVER_CAST counted games ("games": the result's), and how many
    games each was drawn in when every batch of the result has card data."""
    s = result["sides"][side]
    casts, lands = _pooled(result, side)
    return _limits(_side_cards(s), s["kind"], casts, lands, _counted(result), _pooled_cards(result, side),
                   s.get("pilot") if isinstance(s.get("pilot"), dict) else None)


def _commander_unplayable(result, side):
    """side_ai(result, side)["commander_unplayable"], looking only at the commander (no
    oracle tags or Scryfall lookups for the rest: list_item() asks it of every result)."""
    s = result["sides"][side]
    if s["kind"] != "commander":
        return False
    rows = [row for row in _merged_cards(_side_cards(s), "commander") if row[3] == "Commander"]
    if not rows:
        return False
    casts, lands = _pooled(result, side)
    return bool(_cannot_play(rows, _index_or_problem([]), casts, lands, _counted(result))[0])


# ============================================================ how well Forge pilots a list

def _script_params(line):
    """{key: value} of a script line's "Key$ value | ..." parts."""
    out = {}
    for part in line.split("|"):
        key, sep, value = part.partition("$")
        if sep:
            out[key.strip()] = value.strip()
    return out


def _script_api(line):
    """The effect of a "SP$ X | ...", "AB$ X | ..." or "DB$ X | ..." line: "X" (None for none)."""
    found = re.match(r"\s*(?:SP|AB|DB)\$\s*(\w+)", line)
    return found.group(1) if found else None


def _opponents_only(valid):
    """Whether a ValidTgts$ can only name the opponent's things ("Creature.OppCtrl+powerGTX")."""
    return all("OppCtrl" in choice for choice in valid.split(","))


def _face_weak(lines):
    """{kind: detail} of one face of a card script (its lines): see WEAK_KINDS."""
    types = next((line[6:] for line in lines if line.startswith("Types:")), "")
    svars = {}
    for line in lines:
        if line.startswith("SVar:"):
            key, _, value = line[5:].partition(":")
            svars[key] = value
    keywords = [line[2:].strip() for line in lines if line.startswith("K:")]

    def chain(name):
        """The effects an Execute$ or SubAbility$ name runs, in order."""
        seen, out = set(), []
        while name and name in svars and name not in seen:
            seen.add(name)
            out.append(svars[name])
            name = _script_params(svars[name]).get("SubAbility")
        return out

    enters = []                 # (trigger's params, its effects) of each "when this enters" trigger
    for line in lines:
        if line.startswith("T:"):
            trigger = _script_params(line[2:])
            if trigger.get("Mode") == "ChangesZone" and trigger.get("Destination") == "Battlefield" \
                    and "Self" in trigger.get("ValidCard", "Self"):
                enters.append((trigger, chain(trigger.get("Execute"))))
    spell = bool(re.search(r"\b(Instant|Sorcery)\b", types))
    creature = bool(re.search(r"\bCreature\b", types))
    found = {}
    for line in lines:
        if not line.startswith("A:"):
            continue
        params, api = _script_params(line[2:]), _script_api(line[2:])
        own_team = "YouCtrl" in params.get("ValidCards", "") and params.get("IsCurse") != "True"
        if api == "PumpAll" and own_team and (spell or line.startswith("A:AB$")):
            found["team_pump"] = "spell" if spell else "ability"
        if spell and api == "Counter":
            found["counterspell"] = ""
        if spell and api == "Destroy" and "AITgts" in params:
            found["strict_targets"] = params["AITgts"]
    if "AI:RemoveDeck:All" in lines:
        found["remove_all"] = ""
    if spell or re.search(r"\bLand\b", types):
        return found
    for trigger, effects in enters:
        if "OptionalDecider" in trigger:            # the AI may decline it, so it never stops the card
            continue
        for i, effect in enumerate(effects):
            params, api = _script_params(effect), _script_api(effect)
            if params.get("AILogic") == "Always":   # the script tells the AI to use it anyway
                continue
            if creature and api == "PumpAll" and params.get("IsCurse") == "True":
                found["etb"] = "curse"
            elif api == "DestroyAll" and (creature or i > 0):
                found["etb"] = "destroy_all"
            elif creature and api == "ChangeZone" and "ValidTgts" in params and params.get("TargetMin") == "0":
                found["etb"] = "up_to"
            elif creature and i == 0 and "ValidTgts" in params and "TargetMin" not in params \
                    and _opponents_only(params["ValidTgts"]) and trigger.get("AILogic") != "BadETB":
                found["etb"] = "no_target"
    if creature and "Flash" in keywords and not enters and "AmbushAI" not in svars and "PlayMain1" not in svars:
        found["flash"] = ""
    return found


def _script_weak(text):
    """{kind: detail} of a Forge card script, over all its faces (empty when Forge's AI plays it
    as well as any card): see WEAK_KINDS for the kinds and the detail each one has."""
    faces = [[]]
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if line.strip() == "ALTERNATE":
            faces.append([])
        else:
            faces[-1].append(line)
    found = {}
    for lines in faces:
        for kind, detail in _face_weak(lines).items():
            found.setdefault(kind, detail)
    return found


def _build_weak(zip_path):
    """{key (norm of a Forge card name): {kind: detail}} of every card script in
    cardsfolder.zip with a weak kind. Two scripts with one name: the one in fewer folders
    wins, as in install._build_index. About a second for Forge 2.0.15's 34,000 scripts."""
    best = {}
    with zipfile.ZipFile(zip_path) as z:
        for entry in z.namelist():
            if not entry.endswith(".txt"):
                continue
            text = z.read(entry).decode("utf-8", "replace")
            name = install._read_script(text)[0]
            if not name:
                continue
            depth, key = entry.count("/"), norm(name)
            if key not in best or depth < best[key][0]:
                best[key] = (depth, _script_weak(text))
    return {key: weak for key, (_, weak) in best.items() if weak}


_weak = {}
_weak_lock = threading.Lock()


def weak_cards():
    """_build_weak() of the installed Forge's card scripts, worked out once per Forge version
    (and again when its cardsfolder.zip changes), with Deck Lab's deployed overrides (the real
    user folder's, overrides.deployed_scripts) in place of Forge's scripts for their cards (wave
    3: an adopted override that fixes a card clears its weak kind). Raises ForgeError as
    install.script_index()."""
    index = install.script_index()
    stamp = (index["version"], index["zip"]["size"], index["zip"]["mtime_ns"])
    with _weak_lock:
        if stamp not in _weak:
            zip_path = Path(common._settings()["forge_dir"]) / install.SCRIPTS_ZIP
            try:
                built = _build_weak(zip_path)
            except (OSError, zipfile.BadZipFile) as e:
                raise ForgeError(f"Forge's card scripts can't be read ({type(e).__name__}).") from None
            _weak.clear()
            _weak[stamp] = built
        found = _weak[stamp]
    deployed = overrides.deployed_scripts(common._user_dir())
    if not deployed:
        return found
    found = dict(found)
    for name, text in deployed.items():
        card = index["names"].get(norm(name), name)
        weak = _script_weak(text)
        if weak:
            found[norm(card)] = weak
        else:
            found.pop(norm(card), None)
    return found


def _pilot(rows, index, weak, kind, unplayable=False, pilot=None):
    """Whether Forge pilots a list poorly, from its cards' scripts (R19): {"poor", "why",
    "cards", "copies", "needed", "team_pumps", "team_pump_spells", "counterspells",
    "team_pump_fix"}.

    Wave 3: pilot is the list's AI pilot ({"profile", "switches"}); with the team-pump fix
    (switch team-pump-1, decklab/TeamPumpAi) its team pumps aren't a weak kind, so they're
    neither listed nor counted, and "team_pump_fix" is True (the flag's words say so).

    rows are _merged_cards' (Main, and a Commander deck's Commander), index install's
    script_index(), weak weak_cards(). "cards" is every card of a weak kind, [{"name", "qty",
    "commander", "why": [its kinds, in WEAK_KINDS' order], "detail": {kind: detail} for the
    kinds that have one}]. "copies" counts their copies, a card of only HALF_KINDS as half a
    copy; "needed" is PILOT_SHARE of the list's cards (4 in 60, 6.67 in 100); "team_pumps"
    and "counterspells" are those kinds' copies, and "team_pump_spells" the team pumps that are
    spells (the rest are permanents with a team pump ability, such as Warren Elder).

    It's poor ("why" names the first rule that holds, else None) when:
    - "commander": the commander is one Forge's AI never casts (unplayable: by its script, or
      never cast in the list's games) or holds back (a CAST_KINDS kind): it starts every game
      in the command zone, so it matters as much as many cards in the library;
    - "team_pumps": TEAM_PUMP_MIN or more copies pump the whole team, spells or permanents'
      abilities: both go through the same one-creature-at-a-time test (PumpAllAi.checkApiLogic).
      The spells are the ones measured: holding them back put Selesnya Rabbits 12 to 15 points
      too low in Milestone 0;
    - "share": "copies" reaches "needed".
    The rules keep a single minor card (one Devout Decree, one Lathliss) from flagging a list.
    On the decks of 2026-10-03 the flagged ones are Selesnya Rabbits (6-7 team pump copies),
    The Free Peoples (5 weak copies in 60), Finneas (4-5 team pumps) and Gisa (its commander);
    the others have at most 3 weak copies in 60 cards (Mono-Black Midrange) or 6 in 100
    (Giada's owned-only list)."""
    cards_in, copies, pumps, pump_spells, counters, listed = 0, 0.0, 0, 0, 0, []
    commander_held = unplayable
    fixed = TEAM_PUMP_FIX in ((pilot or {}).get("switches") or [])
    for name, dck_name, qty, section in rows:
        cards_in += qty
        card = index["names"].get(norm(dck_name))
        found = dict(weak.get(norm(card), {})) if card else {}
        commander = kind == "commander" and section == "Commander"
        if commander:
            found.pop("flash", None)        # a commander with flash is cast in Main 1 (PermanentCreatureAi:153)
        if fixed:
            found.pop("team_pump", None)    # TeamPumpAi judges the whole team
        if not found:
            continue
        why = [k for k in WEAK_KINDS if k in found]
        listed.append({"name": name, "qty": qty, "commander": commander, "why": why,
                       "detail": {k: v for k, v in found.items() if v}})
        copies += qty * (0.5 if all(k in HALF_KINDS for k in why) else 1)
        pumps += qty if "team_pump" in found else 0
        pump_spells += qty if found.get("team_pump") == "spell" else 0
        counters += qty if "counterspell" in found else 0
        commander_held = commander_held or (commander and any(k in CAST_KINDS for k in why))
    needed = PILOT_SHARE * cards_in
    why = ("commander" if commander_held else "team_pumps" if pumps >= TEAM_PUMP_MIN
           else "share" if cards_in and copies >= needed - 1e-9 else None)
    return {"poor": why is not None, "why": why, "cards": listed, "copies": copies,
            "needed": round(needed, 2), "team_pumps": pumps, "team_pump_spells": pump_spells,
            "counterspells": counters, "team_pump_fix": fixed}
