"""Try a precon before buying it (E3-S39): a published precon the space doesn't own, saved as an
idea deck marked as a trial (decks/trial.py's "- **Trial:** precon <FILE>" line) so that it can
be tested in Forge against the space's own decks and popular decks. Imported when first needed,
by feature_routes.dispatch.

    GET  /api/precons/trial?file=<f>&space=<id>   trial_view(): the precon, and whether it can be tried
    POST /api/precons/trial                       start_trial(body): its trial deck
    POST /api/precons/trial/keep                  keep_trial(body): no longer a trial, still an idea

A trial deck is an ordinary private deck of its space: every privacy rule of decks and Forge
results applies unchanged, and starting a run follows the simulations setting
(guard.require_start), as any run does. Making one needs only deck.create on the space, as
"Start a deck from it" (api/precon_coverage.start_deck), whose path it shares. Trial decks are
kept out of other decks' field, Rankings, Shopping, the shop snapshot, arrival notices, Tables
out of date and the physical-play pickers (each reader filters on the summary's "trial");
removing one is the deck page's ordinary retirement. Add a precon names the trials of the precon
it adds (trials()), so they can be retired once it's bought; their games follow the list.
"""
from decklab.lib import decks, inventory, precons

from . import common, deck_aliases, guard, saving
from . import precon_coverage as coverage
from . import precons as add
from .collection import space_param
from .commits import _conflict, _deck_file, _parse_file, _stored
from .common import ApiError, _keys, _parse_body, _public
from .opponents import _visible_summary
from .saving import _deck_refused, apply_op
from .settings import _writer


def trials(file, space, profile=False):
    """[{"id", "title"}] of the trial decks of the precon file in space that this request (or
    profile; None: a script naming nobody, such as the command line) may see, by title."""
    found = [s for s in guard.visible_decks(decks.list_decks(), profile)
             if s.get("space") == space and s.get("trial") == file]
    return [{"id": s["id"], "title": s["title"]} for s in sorted(found, key=lambda s: (s["title"].casefold(), s["id"]))]


def trial_view(file=None, space=None):
    """GET /api/precons/trial?file=<f>&space=<id>: {"deck" (its /api/precons entry), "kind"
    (commander or casual), "title" (a suggested deck title), "cards" (its Commander and Deck
    cards), "trial" ({"id", "title"} of a trial deck of it in the space this viewer sees, or
    None), "owned_deck" (None: not worked out), "may_create" (deck.create in the space),
    "testable", "why_not_testable" (a sentence, or None)}. 403 (saving.HIDDEN_SPACE) for a
    space whose decks the viewer may not see, nobody named included; 404 for a deck MTGJSON
    doesn't list; 502 when its list can't be had."""
    space = space_param(space)
    saving.require_sees_space(space)
    entry = add._entry(file)
    try:
        read = precons.cards_of(precons.deck(entry["file"]))
    except precons.PreconError as e:
        raise ApiError(502, _public(e)) from None
    except LookupError:
        raise ApiError(404, f"MTGJSON lists no paper deck called {entry['file']}") from None
    has_commander = any(line["section"] == "Commander" for line in read["lines"])
    kind = "commander" if entry["type"] == "Commander Deck" and has_commander else "casual"
    sections = coverage._sections(read, kind)
    kind, count = coverage.kind_and_cards(entry, sections)
    commanders = [line.name for line in sections.get("Commander", [])]
    title = f"{' & '.join(add._short(n) for n in commanders)}: {entry['name']}" if commanders else entry["name"]
    why = coverage.why_not_testable(kind, count)
    with common.state_errors():
        found = trials(entry["file"], space)
    return {"deck": entry, "kind": kind, "title": title[:saving.MAX_TITLE], "cards": count,
            "trial": found[0] if found else None, "owned_deck": None, "may_create": coverage._may_start(space),
            "testable": why is None, "why_not_testable": why}


def _notes(entry, author):
    return (f"A trial of the {entry['name']} precon ({entry['set_name'] or entry['code'].upper()}, {entry['type']}), "
            f"which this space doesn't own, made on {add._added_on()} by {author} to test it in Forge against our "
            "decks and popular decks before buying it. Remove it on its deck page when you're done; Add a precon "
            "offers to remove it once it's bought. " + coverage.list_source(entry))


def start_trial(body):
    """POST /api/precons/trial {"profile", "file", "space"?, "title"?}: the precon's trial deck in
    the space, an idea deck with its list (as Add a precon makes it) and its Trial line, through
    POST /api/decks's path. title: the suggested one (Add a precon's) when left out. 403 as
    POST /api/decks (a space the viewer may not see, no deck.create); 409 {"existing": id} when
    the viewer already sees a trial of it in the space; 400 when it can't be tested (too few
    cards) or its list can't be a deck ("problems"); a taken title 409 with "conflict". Returns
    POST /api/decks's answer. Nothing goes into the collection."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "file"), ("space", "title"))
    space = space_param(data.get("space"))
    saving.require_sees_space(space, profile)
    guard.require(profile, "deck.create", {"space": space, "player": None})
    entry = add._entry(data["file"])
    with common.state_errors():
        found = trials(entry["file"], space, profile)
    if found:
        raise ApiError(409, f"There's already a trial of {entry['name']}: {found[0]['title']}.",
                       existing=found[0]["id"])
    built = coverage.built_list(entry["file"], space, refusal="A trial can't be made of")
    kind, count = coverage.kind_and_cards(entry, {s: [decks.DeckLine(c["qty"], c["name"]) for c in lines]
                                                  for s, lines in built["sections"].items()})
    why = coverage.why_not_testable(kind, count)
    if why is not None:
        raise ApiError(400, f"{entry['name']} can't be tried: {why[0].lower()}{why[1:]}")
    title = data.get("title")
    if title is None:
        title = built["title"]
    return coverage.create_idea(built, title, space, profile, _notes(entry, profile["name"]), trial=entry["file"])


def keep_trial(body):
    """POST /api/precons/trial/keep {"profile", "id", "expected_sha"}: the trial deck's Trial line
    removed (deck.edit on it), one deck save; it stays an idea deck. 404 as any deck reader for
    a deck the viewer can't see; 409 when the deck was saved since expected_sha; 400 when it
    isn't a trial deck. Returns {"ok", "id", "sha256"}."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "id", "expected_sha"))
    with common.state_errors():
        deck_aliases.reject_alias(data["id"], profile)
        summary = _visible_summary(data["id"])
        kind, slug, path = _deck_file(summary["id"])
        stored = _stored(summary["id"], viewer=profile)
        deck = _parse_file(stored.data, kind, slug, path, summary["id"])
        guard.require(profile, "deck.edit", deck)
        sha = data["expected_sha"]
        if not isinstance(sha, str) or not common._SHA_RE.fullmatch(sha):
            raise ApiError(400, "expected_sha must be the deck's 64-character text hash")
        if sha != stored.sha256:
            raise _conflict(summary["id"], deck.title, viewer=profile)
        if decks.trial_of(deck) is None:
            raise ApiError(400, f"{deck.title} isn't a trial deck.")
        try:
            decks.set_trial(deck, None)
            text = decks.render_deck_file(deck)
        except (decks.DeckFileError, ValueError) as error:
            raise ApiError(400, f"The deck can't be saved: {_public(error)}") from None
        operation = inventory.Op("deck.save", {"deck_id": summary["id"], "text": text, "base_sha256": stored.sha256})
        after, _ = apply_op(operation, profile, f"keep {deck.title} as a deck idea, no longer a trial",
                            _deck_refused(summary["id"], deck.title, profile))
        return {"ok": True, "id": summary["id"], "sha256": after.deck(summary["id"]).sha256}
