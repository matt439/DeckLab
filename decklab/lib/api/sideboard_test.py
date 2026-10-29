"""Tests of a saved sideboard plan (E4-S16): Forge plays the plan's post-board main list on the base
list's games against the plan's opponent, as a paired variant test (api/variant_page.py,
forge.variants.run_test), and gives the variant tests' verdict.

    start_sideboard_test(body)  POST /api/play/sideboard-test {"profile", "id", "sha256", "mode"?}:
                                {"version", "plan", "test", "link", "status", "verdict", "words"}
    sideboard_tests(id, sha256) GET /api/play/sideboard-tests?id=&sha256=: {"version", "plan",
                                "current", "tests": [variant_page._test_item's, with "older_list"
                                and "link"]}, newest first, running ones first

A start goes through the preview's checks first (sideboard_preview.preview_sideboard: the record's
own-space visibility, both lists still visible and exactly as saved, one verified format), so a
hidden plan or opponent answers as the preview does before any 403. Then the simulations setting
(guard.require_start), the base's own space and the variant tests' own checks (Forge ready with
deck-order-1, a free place in the coordinator's queue). The played lists are bound to the plan:
Forge's entries read today must have the cards of the record's verified snapshots. Games stay best
of one, so only the post-board main list is tested; the sideboard isn't played.

A plan's tests are its deck's variant tests against the same opponent list whose changes are the
plan's moves (an editor test of the same swap is the same experiment). One is for an older list
when a list's played cards changed since it was played, or the saved plan no longer matches today's
lists; the plan is "current" while it still does. Only the plan's own space reads them, and each
test also follows the variant tests' visibility (variant_page._sees_test).
"""
import contextlib

from decklab.lib import inventory, jobs, state
from decklab.lib.state import rules

from . import forge_runs, guard, play_records as play, sideboard_preview as preview, variant_page
from .common import MAX_BODY, ApiError, _SHA_RE, _keys, _parse_body
from .settings import _writer

FORMAT = "These lists can't be tested against each other: their simulation formats differ or aren't verified."
CHANGED = "A selected decklist changed. Review a new plan revision before testing it."
BAD_MODE = 'mode must be "ahead" or "quick"'


def _plan_cards(sections):
    """The played cards of a snapshot's sections: {"Commander", "Main"} as forge.lists._section_cards."""
    return {"Commander": [[line["qty"], line["name"]] for line in sections.get("Commander", [])],
            "Main": [[line["qty"], line["name"]] for line in sections.get("Deck", [])]}


def _card_sha(forge, sections, kind):
    return forge.lists._list_text(_plan_cards(sections), kind)[1]


class _PlanRun(variant_page._VariantRun):
    """A variant test's job started from a sideboard plan: the same run, its own title."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = f"Test of a sideboard plan for {self.base['title']}"


def _verified_record(ident, sha256):
    """The saved plan when the preview just accepted it, the same record version read again (its
    opponent's sections are the snapshot the preview's hash covers)."""
    try:
        record = state.store().play_get("sideboards", ident)
        actual = play._checked("sideboards", ident, record) if isinstance(record, dict) else None
    except Exception:
        actual = None
    if actual != sha256:
        raise ApiError(409, preview.PLAN_CHANGED)
    return record


def start_sideboard_test(body):
    """POST /api/play/sideboard-test {"profile", "id", "sha256", "mode"?}: start (or join) the test
    of a saved plan, mode "ahead" (the default) or "quick". ApiError as the preview (400, 404, 409,
    503), 409 FORMAT for lists without one verified format, 403 while the simulations setting
    refuses or for another space's deck, 400 for a plan that plays the same cards or another size,
    503 when Forge isn't ready or too many tests wait."""
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    _keys(data, ("profile", "id", "sha256"), ("mode",))
    mode = data.get("mode", "ahead")
    if mode not in ("ahead", "quick"):
        raise ApiError(400, BAD_MODE)
    seen = preview.preview_sideboard(data["id"], data["sha256"])
    if seen["game_plan"]["status"] != "proposed":
        raise ApiError(409, FORMAT)
    guard.require_start(profile)        # the simulations setting (api/simulations.py)
    forge = variant_page._forge()
    record = _verified_record(data["id"], data["sha256"])
    base_ref, opponent_ref = seen["base"], seen["opponent"]
    try:
        base, against = variant_page._base_and_against(forge, base_ref["id"], base_ref["version"],
                                                       opponent_ref["id"], opponent_ref["version"])
    except ApiError as error:
        raise ApiError(409, CHANGED if error.status == 404 else error.message) from None
    variant_page._require_owner(base, profile)
    if base["card_sha"] != _card_sha(forge, base_ref["sections"], base["kind"]) or \
            against["card_sha"] != _card_sha(forge, record["opponent"]["sections"], against["kind"]):
        raise ApiError(409, CHANGED)        # a list saved between the preview's pin and Forge's read
    cards = _plan_cards(seen["post_board"]["sections"])
    _, card_sha, count = forge.lists._list_text(cards, base["kind"])
    if card_sha == base["card_sha"]:
        raise ApiError(400, "This plan plays the same cards in the main list, so there's no change to test.")
    if count != base["card_count"]:
        raise ApiError(400, f"{variant_page.SIZE_WORDS}: the saved list has {base['card_count']} and this "
                            f"plan's {count}.")
    try:
        variant = forge.variants.variant_entry(base, cards)
    except ValueError as error:
        raise ApiError(400, str(error)) from None
    variant_page._ready(forge)
    test = forge.variants.test_id(base, variant, against, mode)
    variant_page._submit(_PlanRun(forge, test, base, cards, against, mode, profile["name"], by_id=profile["id"]),
                         rerun=True)
    view = variant_page._view(forge, test, forge_runs._Seen(profile))
    return {"version": 1, "plan": {"id": data["id"], "sha256": data["sha256"]}, "test": test,
            "link": f"#/variant?test={test}", "status": view["status"], "verdict": view["verdict"],
            "words": view["words"]}


def _plan_changes(forge, record):
    """The plan's moves as a variant test's "changes": {"remove", "add"} [[qty, Forge name]]."""
    order = lambda item: (item[1].casefold(), item[1])      # noqa: E731

    def merged(moves):
        counts = {}
        for move in moves:
            name = forge.common.forge_name(move["name"])
            counts[name] = counts.get(name, 0) + move["qty"]
        return sorted(([qty, name] for name, qty in counts.items()), key=order)
    return {"remove": merged(record["out"]), "add": merged(record["in"])}


def _lists_today(forge, record, reads):
    """(whether the saved plan matches today's lists, today's base entry, today's opponent entry);
    an entry None when it can't be read today."""
    current = False
    try:
        with contextlib.nullcontext() if inventory.is_pinned() else inventory.pinned():
            base, _ = preview._current_snapshot(record["deck"], reads)
            opponent, _ = preview._current_snapshot(record["opponent"], reads)
        current = base["sha256"] == record["deck"]["sha256"] and opponent["sha256"] == record["opponent"]["sha256"]
    except Exception:
        current = False
    try:
        base, against = variant_page._base_and_against(forge, record["deck"]["id"], record["deck"]["version"],
                                                       record["opponent"]["id"], record["opponent"]["version"])
    except Exception:
        base = against = None
    return current, base, against


def _for_plan(forge, summary, record, changes):
    against = summary.get("against")
    return isinstance(against, dict) and isinstance(against.get("id"), str) and \
        forge.deck_identity.same(against["id"], record["opponent"]["id"]) and \
        against.get("version") == record["opponent"]["version"] and \
        (summary.get("variant") or {}).get("changes") == changes


def sideboard_tests(id=None, sha256=None):
    """GET /api/play/sideboard-tests?id=<saved plan id>&sha256=<record hash>: the plan's tests, each
    with its verdict and "older_list". ApiError as the preview for a bad, hidden, changed or
    unavailable plan or pair, 501 without variant tests."""
    if not isinstance(id, str) or not rules.PLAY_ID.fullmatch(id) or not isinstance(sha256, str) \
            or not _SHA_RE.fullmatch(sha256):
        raise ApiError(400, "Choose a saved sideboard plan and its exact record version.")
    profile, script = guard.viewer(), guard.script()
    try:
        record = state.store().play_get("sideboards", id)
    except Exception:
        raise ApiError(503, preview.UNAVAILABLE) from None
    try:
        visible = isinstance(record, dict) and play._sees_record("sideboards", record, profile, script)
    except Exception:
        visible = False
    if not visible:
        raise ApiError(404, preview.NO_PLAN)
    reads = guard.deck_reader(profile)
    try:
        visible_pair = preview._visible_pair(record, reads)
    except Exception:
        visible_pair = False
    if not visible_pair:
        raise ApiError(409, preview.PAIR_UNAVAILABLE)
    try:
        preview._bounded_record(record)
        actual = play._checked("sideboards", id, record)
    except Exception:
        raise ApiError(500, preview.INVALID_PLAN) from None
    if actual != sha256:
        raise ApiError(409, preview.PLAN_CHANGED)
    forge = variant_page._forge()
    changes = _plan_changes(forge, record)
    current, base, against = _lists_today(forge, record, reads)
    seen = forge_runs._Seen(profile)
    deck_id, version = record["deck"]["id"], record["deck"]["version"]
    running = {}
    for job in forge_runs.COORD_JOBS.active():
        run = job.fn
        if getattr(run, "kind", None) == "variant" and forge.deck_identity.same(run.deck_id, deck_id) and \
                run.version == version and seen.coordinator(job):
            running[run.test] = (run, forge_runs.COORD_JOBS.snapshot(job))
    found = []
    for summary in forge.variants.tests_for(deck_id, version):
        live = running.pop(summary["test"], None)
        found.append((forge.variants.visible_summary(summary, seen.deck), live))
    found[:0] = [(variant_page._pending(run), (run, snap)) for run, snap in running.values()
                 if snap["status"] in (jobs.QUEUED, jobs.RUNNING)]
    tests = []
    for summary, live in found:
        if not _for_plan(forge, summary, record, changes) or not variant_page._sees_test(summary, seen):
            continue
        item = variant_page._test_item(forge, summary, None, live)
        item.pop("saved", None)
        tested = (summary["base"].get("card_sha"), summary["against"].get("card_sha"))
        today = (base or {}).get("card_sha"), (against or {}).get("card_sha")
        item.update(older_list=not (current and None not in today and tested == today),
                    link=f"#/variant?test={summary['test']}")
        tests.append(item)
    return seen.mask({"version": 1, "plan": {"id": id, "sha256": actual}, "current": current, "tests": tests})
