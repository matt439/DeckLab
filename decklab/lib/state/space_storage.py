"""A space's storage as a setting (E8-S25, decklab/design/storage-setting.md): where its loose cards
are kept. One record per space, saved whole with a revision, as the shops' postage is (migration
0028's space_storage table):

    {"v": 1, "default": "box",
     "containers": [{"id": "box", "name": "Storage box", "kind": "box", "capacity": 2400,
                     "sections": ["Row 1", "Row 2", "Row 3", "Row 4"], "order": "colour-type",
                     "sleeved": false, "holds": {"Row 1": "creatures", "Row 2": "spells",
                     "Row 3": "lands", "Row 4": "tokens"}}]}

- containers: 0 to MAX_CONTAINERS, in the space's order. id is a slug made once from the name (as
  accessory ids are) and kept through a rename; name 1-40 characters, one line, unique in the space
  ignoring case; kind box, binder, shelf or other (words only); capacity a whole number of cards
  1-100,000, or None when not known; sections 0 to MAX_SECTIONS short names (a recorded location
  starting with one belongs to the container); order one of ORDERS; sleeved whether its cards are
  kept sleeved (a binder's pockets), so pages stop saying "unsleeved" there; holds (E8-S25 slice 7,
  "sections from the rule") which group of cards each section holds, {section: group}, for a
  colour-type container only: groups GROUPS (creatures, spells, lands, token cards), each at most
  once, each section one of the container's own. Another order's holds are dropped. A record
  saved before slice 7 has no holds and reads as none ({}): the version stays 1.
- default: the id of the container loose cards go to when no location is recorded, or None.

No saved record: home uses BUILTIN_HOME's box (today's behaviour, its capacity config.json's
storage_box_capacity or 2,400), any other space has no containers (effective()). A saved record
always wins, an empty one included: that's how a self-hosted install's home opts out of the box.

match() is the one location rule: a location belongs to the container one of whose sections (or
whose name) it starts with, ignoring case, followed by the end, a space or a comma; the longest
match wins. A location matching nothing is "somewhere else".
"""
import re

from . import Invalid

VERSION = 1
MAX_CONTAINERS = 20
MAX_SECTIONS = 50
MAX_NAME = 40
MAX_CAPACITY = 100_000
KINDS = ("box", "binder", "shelf", "other")
ORDERS = ("colour-type", "set", "name", "none")     # Matt, 2026-11-13 (Q4): no type-colour
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
FIELDS = ("id", "name", "kind", "capacity", "sections", "order", "sleeved", "holds")
# What a colour-type section may hold (slice 7), and how the pages word each group.
GROUPS = ("creatures", "spells", "lands", "tokens")
GROUP_WORDS = {"creatures": "Creatures", "spells": "Spells", "lands": "Lands", "tokens": "Token cards"}
EMPTY = {"v": VERSION, "default": None, "containers": []}
BUILTIN_CAPACITY = 2400
HOME_ROWS = ("Row 1", "Row 2", "Row 3", "Row 4")
# How the household's rows are used (Q2): one group each, the built-in box's holds (slice 7).
HOME_ROW_GROUPS = {"Row 1": "creatures", "Row 2": "spells", "Row 3": "lands", "Row 4": "tokens"}
CHANGED = "The storage setup changed. Reload it before saving."
MIGRATE = ("The storage setup needs the database's migration 0028 (python -m decklab.db migrate on "
           "the PC). Deck Lab's database needs updating on the PC.")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def space_id(value):
    """A space id as the store takes it (Invalid otherwise)."""
    if not isinstance(value, str) or len(value) > MAX_NAME or not ID.fullmatch(value):
        raise Invalid("space must be home or a person's space id")
    return value


def expectation(value):
    """The complete record's optimistic revision (0 before anything was saved)."""
    if type(value) is not int or value < 0:
        raise Invalid("expect must be a whole-number revision of 0 or above")
    return value


def builtin_home(capacity=None):
    """Home's built-in default: today's 4-row storage box, the default for loose cards."""
    size = capacity if type(capacity) is int and 1 <= capacity <= MAX_CAPACITY else BUILTIN_CAPACITY
    return {"v": VERSION, "default": "box",
            "containers": [{"id": "box", "name": "Storage box", "kind": "box", "capacity": size,
                            "sections": list(HOME_ROWS), "order": "colour-type", "sleeved": False,
                            "holds": dict(HOME_ROW_GROUPS)}]}


def effective(space, saved, capacity=None):
    """(record, source): the saved record when there is one ("saved"); else home's built-in box
    ("default", capacity seeding it) or, for any other space, no containers ("none")."""
    if saved is not None:
        return saved, "saved"
    if space == "home":
        return builtin_home(capacity), "default"
    return dict(EMPTY, containers=[]), "none"


def _line(value, what, *, limit=MAX_NAME):
    if not isinstance(value, str):
        raise Invalid(f"{what} must be text")
    text = " ".join(value.split())
    if not text or len(text) > limit or _CONTROL.search(value.replace("\t", " ").replace("\n", " ")) \
            or "\n" in value or "\r" in value:
        raise Invalid(f"{what} must be one line of 1 to {limit} characters")
    return text


def slug(name, taken):
    """An id made from name (lowercase letters, digits and single hyphens, at most 40), with -2,
    -3... on a clash with taken."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:MAX_NAME].strip("-") or "storage"
    found, n = base, 2
    while found in taken:
        tail = f"-{n}"
        found = base[:MAX_NAME - len(tail)].strip("-") + tail
        n += 1
    return found


def _capacity(value, what):
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise Invalid(f"{what}'s capacity must be a whole number of cards, or blank when not known")
    text = str(value).strip()
    if not text:
        return None
    if not text.isdigit() or not 1 <= int(text) <= MAX_CAPACITY:
        raise Invalid(f"{what}'s capacity must be a whole number of cards from 1 to {MAX_CAPACITY:,}")
    return int(text)


def _sections(value, what):
    if value is None:
        return []
    if not isinstance(value, list):
        raise Invalid(f"{what}'s sections must be a list of names")
    if len(value) > MAX_SECTIONS:
        raise Invalid(f"{what} can have at most {MAX_SECTIONS} sections")
    out, seen = [], set()
    for item in value:
        text = _line(item, f"A section of {what}")
        if text.casefold() in seen:
            raise Invalid(f"{what} lists the section {text!r} twice")
        seen.add(text.casefold())
        out.append(text)
    return out


def _holds(value, sections, order, what):
    """{section: group} in section order (the module docstring); {} for any order but colour-type."""
    if value is None or value == {}:
        return {}
    if not isinstance(value, dict):
        raise Invalid(f"{what}'s holds must map a section to the group of cards it holds")
    if order != "colour-type":
        return {}
    canonical = {section.casefold(): section for section in sections}
    found, groups = {}, set()
    for key, group in value.items():
        if group in (None, ""):
            continue
        section = canonical.get(" ".join(key.split()).casefold()) if isinstance(key, str) else None
        if section is None:
            raise Invalid(f"{what}'s holds name a section it doesn't have: {key!r}")
        if group not in GROUPS:
            raise Invalid(f"A section of {what} holds one of {', '.join(GROUPS)}")
        if group in groups:
            raise Invalid(f"{what} has two sections holding {GROUP_WORDS[group].lower()}")
        if section in found:
            raise Invalid(f"{what}'s holds name the section {section!r} twice")
        groups.add(group)
        found[section] = group
    return {section: found[section] for section in sections if section in found}


def _container(value, taken, reserved):
    if not isinstance(value, dict):
        raise Invalid("Each container must be an object of id, name, kind, capacity, sections, order, sleeved and holds")
    unknown = sorted(set(value) - set(FIELDS))
    if unknown:
        raise Invalid(f"Unknown container field {unknown[0]!r}; a container has {', '.join(FIELDS)}")
    name = _line(value.get("name"), "A container's name")
    given = value.get("id")
    if given in (None, ""):
        ident = slug(name, taken | reserved)
    elif not isinstance(given, str) or len(given) > MAX_NAME or not ID.fullmatch(given):
        raise Invalid(f"{name}'s id must be lowercase letters, digits and single hyphens (at most {MAX_NAME})")
    elif given in taken:
        raise Invalid(f"Two containers have the id {given!r}")
    else:
        ident = given
    kind = value.get("kind", "box")
    if kind not in KINDS:
        raise Invalid(f"{name}'s kind must be one of {', '.join(KINDS)}")
    order = value.get("order", "none")
    if order not in ORDERS:
        raise Invalid(f"{name}'s order must be one of {', '.join(ORDERS)}")
    sleeved = value.get("sleeved", False)
    if type(sleeved) is not bool:
        raise Invalid(f"{name}'s sleeved must be true or false")
    sections = _sections(value.get("sections"), name)
    return {"id": ident, "name": name, "kind": kind, "capacity": _capacity(value.get("capacity"), name),
            "sections": sections, "order": order, "sleeved": sleeved,
            "holds": _holds(value.get("holds"), sections, order, name)}


def normalize(value):
    """The complete record, checked (Invalid with the reason otherwise). value is the record, or
    its containers list alone; a container without an id gets one made from its name, and default
    may name a container by id or by name."""
    if isinstance(value, list):
        value = {"containers": value}
    if not isinstance(value, dict):
        raise Invalid("The storage setup must be an object of default and containers")
    unknown = sorted(set(value) - {"v", "default", "containers"})
    if unknown:
        raise Invalid(f"Unknown storage setup field {unknown[0]!r}; it has default and containers")
    if "v" in value and value["v"] != VERSION:
        raise Invalid("Unknown storage setup record version")
    containers = value.get("containers", [])
    if not isinstance(containers, list):
        raise Invalid("containers must be a list")
    if len(containers) > MAX_CONTAINERS:
        raise Invalid(f"A space can list at most {MAX_CONTAINERS} containers")
    out, taken, names = [], set(), set()
    # Ids given explicitly are reserved first, so a new container's made id never takes one.
    reserved = {c["id"] for c in containers if isinstance(c, dict) and isinstance(c.get("id"), str) and c["id"]}
    for item in containers:
        made = _container(item, taken, reserved)
        if made["name"].casefold() in names:
            raise Invalid(f"Two containers are called {made['name']!r}")
        names.add(made["name"].casefold())
        taken.add(made["id"])
        out.append(made)
    default = value.get("default")
    if default in (None, ""):
        default = None
    elif not isinstance(default, str):
        raise Invalid("default must be a container's id, or blank for none")
    else:
        found = [c["id"] for c in out if c["id"] == default] or \
                [c["id"] for c in out if c["name"].casefold() == " ".join(default.split()).casefold()]
        if not found:
            raise Invalid("default must be one of the containers (or blank for none)")
        default = found[0]
    return {"v": VERSION, "default": default, "containers": out}


def _starts(location, prefix):
    """How much of location prefix matches: its length when location starts with it (ignoring
    case) followed by the end, a space or a comma; else 0."""
    if not prefix or len(location) < len(prefix) or location[:len(prefix)].casefold() != prefix.casefold():
        return 0
    rest = location[len(prefix):]
    return len(prefix) if not rest or rest[0] in " ," else 0


def match(record, location):
    """The id of the container a recorded location belongs to: the record's default for none
    recorded, else the container whose section or name it starts with (the longest wins), else
    None ("somewhere else")."""
    text = (location or "").strip()
    if not text:
        return (record or {}).get("default")
    best, length = None, 0
    for container in (record or {}).get("containers") or ():
        for prefix in (*container.get("sections", ()), container.get("name", "")):
            found = _starts(text, prefix)
            if found > length:
                best, length = container["id"], found
    return best


def suggestions(record):
    """The location suggestions the record gives, in order: each container's sections, or its name
    when it has none."""
    out = []
    for container in (record or {}).get("containers") or ():
        out.extend(container.get("sections") or [container["name"]])
    return out


def container(record, ident):
    """The container with that id, or None."""
    return next((c for c in (record or {}).get("containers") or () if c.get("id") == ident), None)


def group_sections(found):
    """{group: section} of a container's holds (slice 7), {} when it has none or isn't colour-type
    (a record saved before slice 7, or another order)."""
    if not found or found.get("order") != "colour-type" or not isinstance(found.get("holds"), dict):
        return {}
    return {group: section for section, group in found["holds"].items() if group in GROUPS}


def card_group(type_line):
    """The group a playable card is filed with by the colour-type rule, from its front face's type
    line: "lands" (a land creature too, as Build decks' storage order files it), "creatures", else
    "spells"; None when the type line isn't known. Token cards are "tokens" by what they are."""
    front = (type_line or "").split(" // ")[0].split("\u2014")[0].split()
    if not front:
        return None
    return "lands" if "Land" in front else "creatures" if "Creature" in front else "spells"
