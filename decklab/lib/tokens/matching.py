"""One owned row against one token need (match_face and its verdicts), and
the words that describe a token. Part of decklab.lib.tokens (see its
docstring). _faces_at is read as names._faces_at, where tests patch it."""
import re

from decklab.lib import cards

from . import names
from .details import COLOUR_WORDS, _COLOUR_ORDER, parse_details

_VERDICT_RANK = {"exact": 0, "agrees": 1, "check": 2, "differs": 3}


# ------------------------------------------------------------------ matching

def _colour_names(letters):
    return [COLOUR_WORDS[c] for c in "WUBRG" if c in (letters or [])]


def _colour_text(names):
    names = [n for n in _COLOUR_ORDER if n in names]
    return _and(names) if names else "colourless"


def _pt(power, toughness):
    return None if power is None else f"{power}/{toughness}"


def _traits(pt, colors, keywords):
    """"2/2 green with deathtouch, flying": P/T, colours and keywords, as known."""
    words = [w for w in (pt, None if colors is None else _colour_text(_colour_names(colors))) if w]
    kws = [k.lower() for k in keywords or []]
    return " ".join(words) + (f" with {', '.join(kws)}" if kws else "")


def _describe(name, kind, pt, colors, keywords):
    """"1/1 blue Fish", "1/1 green Insect with deathtouch, flying"; a reminder is its name."""
    if kind not in (None, "token"):
        return name
    words = [w for w in (pt, None if colors is None else _colour_text(_colour_names(colors)), name) if w]
    kws = [k.lower() for k in keywords or []]
    return " ".join(words) + (f" with {', '.join(kws)}" if kws else "")


def _a(text):
    if text.startswith("The "):
        return text
    return ("an " if text[:1].lower() in "aeiou" else "a ") + text


def _side_traits(need, side_name):
    """(pt, colours, keywords) of the need's face called side_name: its
    front's (the need's own) unless side_name is another face."""
    faces = need.get("faces") or []
    key = cards.fold(side_name)
    for i, face in enumerate(faces):
        if i and cards.fold(face.get("name", "")) == key and key != cards.fold(faces[0].get("name", "")):
            text = face.get("text") or ""
            kws = [k for k in need.get("keywords") or [] if re.search(rf"\b{re.escape(k)}\b", text, re.I)]
            return _pt(face.get("power"), face.get("toughness")), face.get("colors"), kws
    return need.get("pt"), need.get("colors"), need.get("keywords")


def _printed_face(entry, side_name):
    """The face called side_name of a printing that carries two different
    tokens (a Guild Kit "Goblin // Soldier", f17 "Vampire // Treasure"), or
    None when the printing is a single token or has no such face."""
    faces = entry.get("faces") or []
    if len({cards.fold(f.get("name", "")) for f in faces}) < 2:
        return None
    key = cards.fold(side_name)
    return next((f for f in faces if cards.fold(f.get("name", "")) == key), None)


def _face_match(need, side_name, entry, face, where):
    """(verdict, why, aspects not recorded) for a row whose printing carries
    the need's face beside another token: "agrees" when that face has the
    need's P/T, colours and keywords, else "differs" saying how."""
    text = face.get("text") or ""
    kws = [k for k in entry.get("keywords") or [] if re.search(rf"\b{re.escape(k)}\b", text, re.I)]
    theirs = (_pt(face.get("power"), face.get("toughness")), set(face.get("colors") or []),
              {k.lower() for k in kws})
    pt, colors, need_kws = _side_traits(need, side_name)
    mine = (pt, set(colors or []), {k.lower() for k in need_kws or []})
    if need.get("kind") != "token" or entry.get("kind") != "token" or theirs == mine:
        return "agrees", [], []
    shown = _describe(face.get("name", side_name), entry.get("kind"), theirs[0], face.get("colors"), kws)
    return "differs", [f"the {face.get('name', side_name)} on {where} is {_a(shown)}; "
                       f"this {need['name']} is {_traits(pt, colors, need_kws)}"], []


def _who(need):
    made = need.get("made_by") or []
    return f"{made[0]['name']}'s {need['name']}" if made else f"this {need['name']}"


def _match(need, side_name, details, row, side="front"):
    """(verdict, why, aspects not recorded) for one face of a row; see match_face."""
    unresolved = need["key"].startswith("name:")
    number = row.get(f"{side}_collector_number") or ""
    if row.get("set") and number and not unresolved:
        try:
            found = names._faces_at(row["set"], number)
        except RuntimeError:
            found = None
        if found is not None:
            oracle_id = found[0]
            if oracle_id == need["key"]:
                return "exact", [], []
            other = cards.token(oracle_id) or {}
            face = _printed_face(other, side_name)
            if face is not None:
                return _face_match(need, side_name, other, face, f"{row['set']} {number}")
            theirs = _describe(other.get("name", side_name), other.get("kind"),
                               _pt(other.get("power"), other.get("toughness")),
                               other.get("colors"), other.get("keywords"))
            pt, colors, kws = _side_traits(need, side_name)
            mine = _traits(pt, colors, kws) if need.get("kind") == "token" else ""
            where = f"{row['set']} {number}"
            if not mine or theirs == _describe(need["name"], need.get("kind"), pt, colors, kws):
                return "differs", [f"{where} is a different {need['name']}"], []
            return "differs", [f"{where} is {_a(theirs)}; this {need['name']} is {mine}"], []
    if unresolved:
        return "check", [f"Scryfall's link doesn't say which {need['name']}"], []
    facts = parse_details(details)
    pt, colors, kws = _side_traits(need, side_name)
    kws = [k.lower() for k in kws or []]
    why, missing = [], []
    if pt is not None:
        if facts.pt is not None and "pt" not in facts.unknown:
            if facts.pt.upper() != pt.upper():
                why.append(f"recorded {facts.pt}; this token is {pt}")
        else:
            missing.append("P/T")
    if colors is not None:
        mine = set(_colour_names(colors))
        if facts.colors is not None and "colors" not in facts.unknown:
            if facts.colors != mine:
                why.append(f"recorded {_colour_text(facts.colors)}; this token is {_colour_text(mine)}")
        else:
            missing.append("colour")
    for keyword in sorted(facts.has - set(kws)):
        rest = ", ".join(kws) if kws else "none"
        why.append(f"recorded {keyword}; {_who(need)} has {rest}")
    for keyword in sorted(facts.lacks & set(kws)):
        why.append(f"your card says no {keyword}; {_who(need)} has {keyword}")
    if why:
        return "differs", why, []
    missing.extend(k for k in kws if k not in facts.has)
    if missing:
        return "check", [f"{_and(missing)} not recorded"], missing
    return "agrees", [], []


def match_face(need, side_name, details, row):
    """(verdict, why) for a row's face that has the need's name.

    need is a need as deck_tokens gives it (key, name, kind, pt, colors,
    keywords, faces, made_by). verdict is "exact" (the row's printing is this
    token), "differs" (its printing is another token, or its details
    contradict this one's P/T, colour or keywords), "agrees" (every aspect the
    token has is recorded and agrees) or "check" (some aren't recorded). why
    gives the reasons as sentences. Notes never change the verdict."""
    side = "front" if cards.fold(row.get("front") or "") == cards.fold(side_name) else "back"
    verdict, why, _ = _match(need, side_name, details, row, side)
    return verdict, why


def _faces_match(need, row):
    """[(side, face name)] of the row's faces that are this need, front first."""
    key = need["key"]
    if key.startswith("name:"):
        names = {cards.fold(key[5:])}
        pair = None
    else:
        face_names = need.get("face_names") or [need["name"]]
        names = {cards.fold(need["name"])}
        distinct = list(dict.fromkeys(cards.fold(f) for f in face_names))
        pair = None
        if len(distinct) > 1:
            pair = set(distinct)
            if need.get("kind") == "token":
                names |= pair
        else:
            names |= set(distinct)
    front, back = cards.fold(row["front"]), cards.fold(row.get("back") or "")
    if pair is not None and {front, back} == pair and front != back:
        return [("front", row["front"])]
    found = []
    if front in names:
        found.append(("front", row["front"]))
    if back and back in names:
        found.append(("back", row["back"]))
    return found


def _best(need, row):
    """(side, face, verdict, why, missing) of the row's best-matching face, or None."""
    best = None
    for side, face in _faces_match(need, row):
        verdict, why, missing = _match(need, face, row[f"{side}_details"], row, side)
        if best is None or _VERDICT_RANK[verdict] < _VERDICT_RANK[best[2]]:
            best = (side, face, verdict, why, missing)
    return best


def _words_of(name):
    return tuple(cards.fold(name).replace("'", "").split())


def _close(a, b):
    """Whole-word containment either way: "Zombie" and "Zombie Rogue"."""
    a, b = _words_of(a), _words_of(b)
    if not a or not b or a == b:
        return False
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return any(long[i:i + len(short)] == short for i in range(len(long) - len(short) + 1))



def _and(words):
    words = list(words)
    if not words:
        return ""
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"
