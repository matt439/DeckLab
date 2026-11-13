"""A space's storage setting as Deck Lab uses it (E8-S25): the saved record (state.space_storage)
over the built-in default. state/space_storage.py has the record's rules and match().

    read(space)   -> {space, revision, ready, source, storage}; raises state's errors
    default_place(space) -> {name, kind, sleeved} of the container loose cards go to, or None
                     (slice 6's words: "To Storage box", "unsleeved" only when it isn't sleeved),
                     with "sections" {group: section} when that container's colour-type rule
                     says which section holds each group (slice 7: "Row 1 · Creatures")
    card_groups(names) -> {name: "creatures" | "spells" | "lands"} from the card data (slice 7)
    current(space) -> the same, but never raises: a store that can't be read (the database down,
                     no store installed) answers as "nothing saved", so home keeps its built-in
                     box and the Card list's count still shows (source "default", revision None)

source is "saved" (the space's own record), "default" (home's built-in box, its capacity
config.json's storage_box_capacity or 2,400: Q6, a seed only until home's first save) or "none"
(any other space with nothing saved: no containers).
"""
from decklab.lib import config, state
from decklab.lib.state import space_storage as rules


def capacity_seed():
    """config.json's storage_box_capacity when it's a whole number from 1 to 100,000, else None."""
    try:
        value = config.load().get("storage_box_capacity")
    except (OSError, ValueError):
        return None
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= rules.MAX_CAPACITY:
        return value
    return None


def _view(space, saved, seed=True):
    record, source = rules.effective(space, saved["storage"], capacity_seed() if seed else None)
    return {"space": space, "revision": saved["revision"], "ready": saved["ready"], "source": source,
            "storage": record}


def read(space, *, seed=True):
    """The space's storage as it applies now (the module docstring); state errors propagate.
    seed False leaves config.json unread (the built-in box then holds BUILTIN_CAPACITY), for a
    caller that needs only the containers and their sections."""
    return _view(space, state.store().space_storage(space), seed)


def current(space, *, seed=True):
    """read(space), or the built-in answer when the store can't be read (never raises)."""
    try:
        return read(space, seed=seed)
    except (state.StateError, RuntimeError, OSError):
        return _view(space, {"revision": None, "storage": None, "ready": None}, seed)


def place(record):
    """The record's default container as the pages word it: {name, kind, sleeved}, plus
    "sections" ({group: section}) only when its rule maps groups to sections; or None."""
    found = rules.container(record, (record or {}).get("default"))
    if found is None:
        return None
    answer = {"name": found["name"], "kind": found["kind"], "sleeved": bool(found.get("sleeved"))}
    sections = rules.group_sections(found)
    if sections:
        answer["sections"] = sections
    return answer


def card_groups(names):
    """{name: group} for the names the card data knows (the colour-type rule's group from the
    front face's type line: rules.card_group); {} without the card data. Never raises: the
    section is only a word beside a destination."""
    from decklab.lib import cards
    out = {}
    try:
        for name in sorted(n for n in names if isinstance(n, str) and n):
            card = cards.card(name)
            group = rules.card_group(card.get("type_line")) if isinstance(card, dict) else None
            if group:
                out[name] = group
    except Exception:           # no card data (or a broken index): no sections, the rest stands
        return {}
    return out


def with_groups(answer, names, key="storage_default", *, record=None, places=None):
    """answer with "storage_groups" ({name: group}) for names when answer[key] maps sections;
    the field is left out otherwise (no words to add). With record (the setup answer[key] was
    made from), only names its default container holds get a group: places ({name: [recorded
    locations]}, storage_places.by_name) put a card where space_storage.placed says, as Build decks
    and Shopping do, so a card filed in another container (or somewhere else) gets no section;
    places None (the lookup failed) gives none at all."""
    found = answer.get(key)
    if isinstance(found, dict) and found.get("sections"):
        if record is not None:
            default = record.get("default")
            names = set() if places is None else {
                name for name in names if rules.placed(record, places.get(name)) == default}
        answer["storage_groups"] = card_groups(names)
    return answer


def default_place(space):
    """place() of the space's storage as it applies now (current(): never raises)."""
    return place(current(space, seed=False)["storage"])


def default_record(space):
    """The space's storage record as it applies now (current(), unseeded: never raises)."""
    return current(space, seed=False)["storage"]
