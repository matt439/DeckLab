"""Building one need from the card index's token entry, the patterns for
what Scryfall doesn't link, and the words for a need's state. Part of
decklab.lib.tokens (see its docstring)."""
import re
import urllib.parse

from decklab.lib import cards

from .matching import _a, _and, _pt
from .rows import label

COPY_WORDS = "Use it for any copy; say what it copies."
# A card's text that makes token copies Scryfall rarely links to "Copy".
_COPY_RE = re.compile(r"token that's a copy|\bcop(?:y|ies) of\b|\b(?:myriad|encore|embalm|eternalize|populate)\b",
                      re.IGNORECASE)
_CREATES_RE = re.compile(r"\bcreates?\b[^.]*\btokens?\b", re.IGNORECASE)


# ------------------------------------------------------------------ a deck's needs

def _image(entry):
    image = entry.get("image") if entry else None
    if not image:
        return None
    set_code, number = image
    if not (re.fullmatch(r"[a-z0-9]{2,8}", set_code) and re.fullmatch(r"[\w★†-]{1,16}", number)):
        return None
    return f"/img/{set_code}/{urllib.parse.quote(number, safe='')}/small"


def _need(entry):
    return {"key": entry["id"], "name": entry["name"], "kind": entry["kind"],
            "type_line": entry["type_line"], "pt": _pt(entry["power"], entry["toughness"]),
            "colors": list(entry["colors"] or []), "keywords": list(entry["keywords"] or []),
            "text": entry["text"], "image": _image(entry), "faces": entry["faces"],
            "face_names": entry["face_names"], "made_by": []}


def _unresolved_need(name):
    return {"key": f"name:{name}", "name": name, "kind": "token", "type_line": None, "pt": None,
            "colors": None, "keywords": [], "text": "", "image": None, "faces": [],
            "face_names": [name], "made_by": []}


def _incoming_groups(incoming_rows):
    """[(order id, row)] from incoming()'s list (or plain rows with an "order")."""
    out = []
    for item in incoming_rows or []:
        if isinstance(item, dict) and "rows" in item:
            out.extend((item.get("order") or "", row) for row in item["rows"])
        elif isinstance(item, dict):
            out.append((item.get("order") or "", item))
    return out


def _covered(made, unresolved, test):
    return any(test(t) for t in made) or (test is _any_token and bool(unresolved))


def _any_token(t):
    return t["kind"] == "token"


def _names_have(text):
    key = cards.fold(text)
    return lambda t: any(key in cards.fold(n) for n in [t["name"], *t.get("face_names", [])])


# (pattern in a card's text, the linked token or reminder that covers it)
_UNLISTED = (
    (_CREATES_RE, _any_token),
    (re.compile(r"\bthe monarch\b", re.I), _names_have("The Monarch")),
    (re.compile(r"\binitiative\b", re.I), _names_have("Initiative")),
    (re.compile(r"\bventure into\b", re.I), lambda t: t["type_line"].startswith("Dungeon")),
    (re.compile(r"\bthe ring tempts you\b", re.I), _names_have("The Ring Tempts You")),
    (re.compile(r"\bemblem\b", re.I), lambda t: t["kind"] == "emblem"),
    (re.compile(r"it becomes (?:day|night)", re.I), _names_have("Day")),
    (re.compile(r"\{E\}"), _names_have("Energy")),
    (re.compile(r"poison counter", re.I), _names_have("Poison")),
    (re.compile(r"experience counter", re.I), _names_have("Experience")),
)


def _plural(n, word="card"):
    return f"{n} {word}{'' if n == 1 else 's'}"



def _made_by(need, name, quantity, section):
    for m in need["made_by"]:
        if m["name"] == name and m["section"] == section:
            m["quantity"] += quantity
            return
    need["made_by"].append({"name": name, "quantity": quantity, "section": section})


def _card_text(card):
    texts = [card.get("oracle_text") or ""]
    texts += [face.get("oracle_text") or "" for face in card.get("faces", [])]
    return "\n".join(texts)


def _need_words(need, missing):
    """The state's words (see the table in HISTORY.md's Tokens entry)."""
    name, state, k = need["name"], need["state"], need["on_the_way"]
    orders = list(dict.fromkeys(i["order"] for i in need["incoming"] if i["order"]))
    if state == "ready":
        words = f"Have it: {_plural(need['usable'])}"
    elif state == "check":
        if need["key"].startswith("name:"):
            words = (f"Have {_plural(need['usable'])} named {name}; "
                     f"Scryfall's link doesn't say which {name}")
        else:
            words = (f"Have {_plural(need['usable'])} with {_a(name)} face; "
                     f"{_and(missing) if missing else 'details'} not recorded")
    elif state == "differs":
        why = need["stand_ins"][0]["why"]
        words = f"Different token: {why[0]}" if why else "Different token"
    elif state == "incoming":
        which = f"order {orders[0]}" if len(orders) == 1 else f"orders {', '.join(orders)}"
        words = f"None owned yet: {k} on the way" + (f" ({which})" if orders else "")
    else:
        words = "None owned"
        close = [s for s in need["stand_ins"] if s["close"]]
        if close:
            best = max(close, key=lambda s: s["quantity"])
            words += f" · closest: {label(best)} ×{best['quantity']}"
    if k and state != "incoming":
        words += f" · {k} on the way"
    if cards.fold(name) == "copy":
        words += f". {COPY_WORDS}"
    return words


def brief(result):
    """{kinds, none, differs, incoming, opponent, reminders} for the library:
    the number of needs, the names of the deck's own (or maybe the
    opponent's) with nothing owned, a different token, or only cards on the
    way, the names of those that land only on the opponent's side (E7-S23,
    sides.py) in one of those states, counted apart, and the names of the
    emblems and reminders among the needs (so the page says "tokens" only of
    tokens)."""
    needs = result.get("needs", [])
    own = [n for n in needs if n.get("side") != "opponent"]
    return {"kinds": len(needs),
            "none": [n["name"] for n in own if n["state"] == "none"],
            "differs": [n["name"] for n in own if n["state"] == "differs"],
            "incoming": [n["name"] for n in own if n["state"] == "incoming"],
            "opponent": [n["name"] for n in needs if n.get("side") == "opponent"
                         and n["state"] in ("none", "differs", "incoming")],
            "reminders": list(dict.fromkeys(n["name"] for n in needs if n.get("kind", "token") != "token"))}
