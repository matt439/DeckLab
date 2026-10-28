"""Paired variant tests' API (simulation wave 3's R15, forge-trial/sim-wave3-contract.md
section 11.5): a test of an editor draft against its saved list, played as a coordinator job in
api.forge_runs.COORD_JOBS (key "variant:<test id>") through forge.variants.run_test.

    variant_view(test)  GET /api/variant?test=<id>: the test view (section 15); the server
                        answers 202 while its "status" is "queued" or "running"
    variant_estimate(deck_id, version, against, against_version=None)
                        GET /api/variant/estimate?id=&version=&against=<deck id or "field">[&av=]:
                        {"quick": [low, high], "ahead": [low, high]} minutes (None while there's no
                        estimator), with "max" (the games a deck each plays to at most), "opponents",
                        "available" and "problem" (the field when it can't be tested against) and
                        "default" (the mode the sheet offers first)
    variant_tests(deck_id, version)
                        GET /api/variants?id=&version=: {"tests": [...]}, newest first
    run_variant(body)   POST /api/variant/run {"profile", "id", "version", "list", "against",
                        "mode"?}: the test view
    stop_variant(body)  POST /api/variant/stop {"profile", "test"}
    more_variant(body)  POST /api/variant/more {"profile", "test"}: "Play more"

A test needs a visible base and explicit deck opponent; field opponent rows follow visibility.
Hidden-field verdicts and job errors are discarded while visible per-opponent numbers remain.
Starting or extending a test also requires the base's own space. Field estimates and runs use
that space's visible field. Names from other spaces are "someone". The starter, an owner space
or an admin may stop a visible test; an admin can stop a hidden anonymous item (E10-S31).

The job's function (_VariantRun) carries what the matchup pages and the running lists show of it:
kind "variant", title, by, link ("#/variant?test=<id>"), test, deck_id, version and started (the
wall-clock time it started playing), next to the progress detail run_test reports (section 10.3's
"pairs" record with "stage", "next_look" and "games_per_opponent").
"""
from decklab.lib import decks, inventory, jobs, permissions

from . import common, drafts, forge_runs
from .commits import _deck_file
from .common import MAX_BODY, _SHA_RE, ApiError, _keys, _parse_body, _public
from .editor import _snapshot_deck
from .forge_runs import _forge_module, _matchup_lists
from . import guard
from .settings import _writer

NOT_BUILT = "Tests of changes aren't built yet."
WAITING = (jobs.QUEUED, jobs.RUNNING)
TEST_BAD = "That link isn't a test's address."
TEST_NONE = "There's no test of a change at that link."
COORD_BUSY = "4 field runs or tests are already waiting to be played. Try again when one of them has finished."
COORD_STOPPING = "Deck Lab is stopping on the PC, so no test can start."
SIZE_WORDS = "Keep the same number of cards to test a change"
FIELD_HIDDEN = "The field has decks you can't see, so this list can't be tested against it."
QUICK_DEFAULT_MINUTES = 30      # past this worst case, the sheet offers "Quick look" first (section 11.6)


def _forge():
    """decklab.lib.forge (forge_runs._forge_module), or ApiError 501 when it has no variant tests (a
    stand-in for it, as test_api's FakeForge is)."""
    forge = _forge_module()
    if not hasattr(getattr(forge, "variants", None), "run_test"):
        raise ApiError(501, NOT_BUILT)
    return forge


def _test_id(value):
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise ApiError(400, TEST_BAD)
    return value


def _job_key(test):
    return f"variant:{test}"


class _VariantRun:
    """What a variant test's job runs in COORD_JOBS (forge.variants.run_test), and what the answers
    need to know about it while it waits or plays."""

    kind = "variant"

    def __init__(self, forge, test, base, cards, against, mode, by, extend=None, opponents=None, field_options=None,
                 by_id=None):
        self.forge, self.test, self.base, self.cards = forge, test, base, cards
        self.against, self.mode, self.by, self.extend, self.opponents = against, mode, by, extend, opponents
        self.deck_id, self.version = base["id"], base["version"]
        self.field_options = field_options
        self.by_id = by_id
        self.title = f"Test of a change to {base['title']}"
        self.link = f"#/variant?test={test}"
        self.started = None
        variant = forge.variants.variant_entry(base, cards)
        self.changes = variant["changes"]

    def __call__(self, progress):
        self.started = self.forge.common._now()
        summary = self.forge.variants.run_test(self.base, self.cards, self.against, self.mode, by=self.by,
                                               progress=progress, extend=self.extend, opponents=self.opponents,
                                               field_options=self.field_options)
        return {"test": summary.get("test") if isinstance(summary, dict) else self.test}


def _pending(run):
    """A test's summary before run_test has written one: what the job knows."""
    fmt = run.forge.lists.fmt_for(run.base["kind"])
    space = (getattr(run, "field_options", None) or {}).get("space")
    field_name = f"field:{space}:{fmt}" if space is not None else f"field:{fmt}"
    against = (field_name if run.against == "field" else
               {"id": run.against["id"], "version": run.against["version"], "card_sha": run.against["card_sha"],
                "title": run.against.get("title")})
    return {"test": run.test, "version": 1,
            "base": {"id": run.base["id"], "version": run.base["version"], "card_sha": run.base["card_sha"],
                     "title": run.base["title"], "kind": run.base["kind"]},
            "variant": {"changes": run.changes}, "against": against, "mode": run.mode, "opponents": [],
            "looks": [], "starter_mismatch": {"games": 0, "of": 0}, "outcome": None, "by": run.by,
            "created": None, "updated": None}


def _job_json(run, snap, found):
    detail = snap["detail"] if isinstance(snap["detail"], dict) else {}
    live = None
    if found is not None:
        live = found.get("field")
        if live is None and len(found.get("opponents") or []) == 1:
            paired = found["opponents"][0].get("paired") or {}
            if paired.get("delta") is not None:
                live = {"delta": paired.get("delta"), "low": paired.get("low"), "high": paired.get("high")}
    return {"status": snap["status"], "ahead": snap["ahead"], "done": snap["progress"]["done"],
            "total": snap["progress"]["total"], "stage": detail.get("stage"), "next_look": detail.get("next_look"),
            "games_per_opponent": detail.get("games_per_opponent"), "pairs": detail.get("pairs") or {},
            "by": run.by, "started": run.started, "seconds": snap["seconds"], "range": live}


def _current_reference(record):
    """A response-only current link/title; captured test records stay byte-for-byte saved."""
    out = dict(record)
    if str(record.get("id")).startswith("pairing/"):
        return out                  # its saved half order determines its displayed name
    try:
        summary = decks.find_summary(record.get("id")) if record.get("id") else None
    except (inventory.StateError, OSError, ValueError, RuntimeError):
        summary = None
    if summary is not None:
        out["id"] = summary["id"]
        if summary.get("title"):
            out["title"] = summary["title"]
    return out


def _current_test(found):
    summary = dict(found["test"])
    summary["base"] = _current_reference(summary["base"])
    if isinstance(summary.get("against"), dict):
        summary["against"] = _current_reference(summary["against"])
    summary["opponents"] = [_current_reference(row) for row in summary.get("opponents") or []]
    return dict(found, test=summary, opponents=[_current_reference(row) for row in found.get("opponents") or []])


def _sees_test(summary, seen, opponents=()):
    """Whether the base and explicit deck opponent are visible; field rows are filtered later."""
    against = summary.get("against")
    named = [summary.get("base")]
    if isinstance(against, dict):
        named.append(against)
    return seen.sides([row for row in named if row is not None]) and all(isinstance(row, dict) for row in named)


def _view(forge, test, seen=None):
    """The test view (section 15): forge.variants.view's, with status, job and error; TEST_NONE's
    404 for a test seen (a forge_runs._Seen, this request's when None) may not see."""
    seen = forge_runs._Seen() if seen is None else seen
    job = forge_runs.COORD_JOBS.get(_job_key(test))
    if job is not None and not seen.coordinator(job):
        job = None
    found = forge.variants.view(test, visible=seen.deck)
    snap = forge_runs.COORD_JOBS.snapshot(job) if job is not None else None
    if found is None and job is None:
        raise ApiError(404, TEST_NONE)
    if found is None:
        found = {"test": _pending(job.fn), "opponents": [], "field": None, "margin": None, "verdict": None,
                 "words": None}
    if not _sees_test(found["test"], seen, found.get("opponents") or []):
        raise ApiError(404, TEST_NONE)
    status, error = "done", None
    if snap is not None and snap["status"] in WAITING:
        status = snap["status"]
    elif snap is not None and snap["status"] == jobs.ERROR and snap["error"] != jobs.STOPPED:
        error = snap["error"]
        if not found["test"].get("looks"):
            status = "error"
    elif not found["test"].get("looks") and found["test"].get("outcome") is None:
        status = "none"
    out = dict(_current_test(found), status=status, error=error,
               job=_job_json(job.fn, snap, found) if snap is not None and snap["status"] in WAITING else None)
    if out["job"] is not None:
        out["job"]["may_stop"] = seen.can_stop(job, seen.coordinator(job))
        pairs = out["job"]["pairs"]
        shown = {key: pair for key, pair in pairs.items() if seen.deck((pair.get("opponent") or {}).get("id"))}
        if len(shown) != len(pairs):
            out["job"].update(pairs=shown, done=sum(p.get("done") or 0 for p in shown.values()),
                              total=sum(p.get("total") or 0 for p in shown.values()))
    if status in WAITING:
        out["words"] = None             # no verdict words while it plays (section 11.6)
    base_id = (out["test"].get("base") or {}).get("id")
    if status == "done" and isinstance(base_id, str) and base_id.startswith(("casual/", "commander/")) \
            and guard.sees_home_records():
        from . import variant_buying
        try:
            out["buying"] = variant_buying.build(out["test"])
        except Exception as error:
            common._log(f"Variant buying evidence unavailable: {type(error).__name__}")
            out["buying"] = variant_buying.unavailable("Current buying information could not be read.")
    return seen.mask(out)


def variant_view(test):
    """GET /api/variant?test=<id> (section 11.5): the test view. ApiError 400 for a bad id, 404 for
    a test with no summary and no job."""
    forge = _forge()
    return _view(forge, _test_id(test))


def _base_and_against(forge, deck_id, version, against, against_version=None):
    """(base entry, against: an entry or "field") as the lists are today."""
    version = "target" if version is None else version
    if against in (None, "field"):
        ((_, _, _, base),) = _matchup_lists(forge, [(deck_id, version)])
        return base, "field"
    (_, _, _, base), (_, _, _, other) = _matchup_lists(forge, [(deck_id, version), (against, against_version)])
    return base, other


def _opponents(forge, base, against, seen=None):
    """The opponents of a test, or (None, the reason) for a field that can't be tested against,
    a field with a deck seen (a forge_runs._Seen, this request's when None) may not see included
    (FIELD_HIDDEN)."""
    if against != "field":
        return [against], None
    seen = forge_runs._Seen() if seen is None else seen
    try:
        found = forge.variants._opponent_entries(base, "field", None, _field_options(forge, base, seen))
    except forge.ForgeError as e:
        return None, _public(e)
    if not all(seen.deck(o.get("id")) for o in found or []):
        return None, FIELD_HIDDEN
    return found, None


def _field_options(forge, base, seen):
    from .field_page import _field_options as options
    return options(forge, base, seen)


def _require_owner(base, profile):
    """A changed list is published only by its own space, regardless of edit/player rights."""
    if permissions._deck_space(base.get("id")) != (profile.get("space") or permissions.HOME):
        raise ApiError(403, "You can only test changes to decks in your own collection.")


def variant_estimate(deck_id, version="target", against=None, against_version=None):
    """GET /api/variant/estimate (section 11.5): the sheet's times, {"quick": [low, high], "ahead":
    [low, high]} minutes (ahead's high end the worst case: every opponent to the last look, base
    top-ups included), each None when there's no estimate (forge.estimate's), plus "max", "opponents",
    "available", "problem" and "default"."""
    forge = _forge()
    base, against_ = _base_and_against(forge, deck_id, version, against, against_version)
    field_test = against_ == "field"
    opponents, problem = _opponents(forge, base, against_)
    looks = forge.variants._ahead_looks(field_test)
    out = {"against": "field" if field_test else against_["id"], "available": opponents is not None,
           "problem": problem, "opponents": len(opponents or []), "quick": None, "ahead": None,
           "max": {"quick": forge.variants.QUICK_GAMES, "ahead": looks[-1]},
           "default": "quick" if base["kind"] == "commander" else "ahead"}
    if not opponents:
        return out

    def minutes(target):
        pairs = []
        for o in opponents:
            try:
                have = len(forge.views._games(forge.load(forge.matchup_key(base, o)) or {}))
            except forge.ForgeError:
                have = 0
            pairs.append((base, o, max(0, target - have) + target))
        try:
            return forge.estimate.minutes(pairs)
        except Exception as e:      # an estimate is extra: the sheet works without it
            common._log(f"A test's time couldn't be estimated ({type(e).__name__}: {e}).")
            return None

    quick, first, last = minutes(forge.variants.QUICK_GAMES), minutes(looks[0]), minutes(looks[-1])
    out["quick"] = list(quick) if quick else None
    out["ahead"] = [first[0], last[1]] if first and last else None
    if out["ahead"] and out["ahead"][1] > QUICK_DEFAULT_MINUTES:
        out["default"] = "quick"
    return out


def _tests_json(forge, deck_id, version, seen):
    today = None
    try:
        summary = decks.find_summary(deck_id)
        if summary and not summary.get("error") and version in summary["versions"]:
            today = forge.card_sha(decks.load_deck(summary["id"], version), decks.engine_kind(summary))
    except (decks.DeckNotFound, decks.DeckFileError, OSError, ValueError, forge.ForgeError):
        today = None
    running = {}
    for job in forge_runs.COORD_JOBS.active():
        run = job.fn
        if (getattr(run, "kind", None) == "variant" and
                forge_runs._TodaysLists._id(run.deck_id) == forge_runs._TodaysLists._id(deck_id) and
                run.version == version and seen.coordinator(job)):
            running[run.test] = (run, forge_runs.COORD_JOBS.snapshot(job))
    out = []
    for summary in forge.variants.tests_for(deck_id, version):
        live = running.pop(summary["test"], None)
        if _sees_test(summary, seen):
            out.append(_test_item(forge, forge.variants.visible_summary(summary, seen.deck), today, live))
    for run, snap in running.values():
        if _sees_test(_pending(run), seen):
            out.insert(0, _test_item(forge, _pending(run), today, (run, snap)))
    return seen.mask(out)


def _test_item(forge, summary, today, live):
    looks = summary.get("looks") or []
    against = summary.get("against")
    if isinstance(against, dict):
        against = _current_reference(against)
    snap = live[1] if live else None
    return {"test": summary["test"], "changes": (summary.get("variant") or {}).get("changes"),
            "against": "field" if isinstance(against, str) else (against or {}).get("title")
            or (against or {}).get("id"),
            "verdict": summary.get("outcome"), "words": forge.variants.verdict_words(summary) if not live else None,
            "games_per_opponent": looks[-1]["games_per_opponent"] if looks else 0,
            "delta": looks[-1].get("delta") if looks else None,
            "low": looks[-1].get("low") if looks else None, "high": looks[-1].get("high") if looks else None,
            "saved": today is not None and today == (summary.get("variant") or {}).get("card_sha"),
            "running": live is not None,
            "done": snap["progress"]["done"] if snap else None, "total": snap["progress"]["total"] if snap else None,
            "when": summary.get("updated") or summary.get("created")}


def variant_tests(deck_id, version="target"):
    """GET /api/variants (section 11.5): {"tests": [...]} of a deck's list, newest first, running ones
    first: {test, changes, against ("field" or the opponent's title), verdict, words,
    games_per_opponent, delta, low, high (the last look's range), saved (the list today is the tested
    change), running, done, total, when}. ApiError 404 "No deck <id>" for a deck that doesn't exist or
    the viewer may not see (E10-S30), and only the tests it may see (_sees_test)."""
    forge = _forge()
    if version not in ("target", "owned"):
        raise ApiError(400, "version must be target or owned")
    from .library import _find_summary, check_deck_id
    check_deck_id(deck_id)
    guard.require_sees_deck(deck_id)
    with common.state_errors():
        _find_summary(deck_id)
    return {"tests": _tests_json(forge, deck_id, version, forge_runs._Seen())}


def _draft_cards(forge, deck_id, version, raw):
    """The variant's cards from the editor's list (the editor's own checks apply): {"Commander",
    "Main"}. ApiError 400 with the editor's words when the draft doesn't pass."""
    _deck_file(deck_id)                 # only deck files (and a space that exists), as the editor saves
    space, kind, slug = decks.split_id(deck_id)
    deck = _snapshot_deck(kind, slug, space)    # from the inventory's snapshot, not the file on disk
    if not isinstance(raw, dict):
        raise ApiError(400, 'list must be a JSON object of sections, like {"Deck": [...]}')
    draft = drafts._read_draft({"lists": {version: raw}}, kind, deck)
    if draft.blocks:
        raise ApiError(400, draft.blocks[0]["problem"], blocks=draft.blocks)
    sections = draft.lists[version] or {}
    return forge.lists._section_cards(sections), sections


def _sideboard(sections):
    return sorted((l.quantity, l.name) for l in sections.get("Sideboard", []))


def _submit(run, rerun=False):
    try:
        forge_runs.COORD_JOBS.submit(_job_key(run.test), run, rerun=rerun)
    except jobs.Busy as e:
        raise ApiError(503, COORD_STOPPING if e.stopping else COORD_BUSY) from None


def _ready(forge):
    state = forge.status()
    if not state.get("ready"):
        raise ApiError(503, state.get("problem") or "Forge isn't ready to play games on the PC.")
    if forge.variants.DECK_ORDER not in (forge.engine.today().get("game_patches") or []):
        raise ApiError(503, forge.variants.NO_DECK_ORDER)


def run_variant(body):
    """POST /api/variant/run {"profile", "id", "version", "list", "against", "mode"?} (section
    11.5): test the editor's draft of a list (list: its sections, as the editor sends them to
    /api/deck/check) against one deck ({"id", "version"}) or "field"; mode "ahead" (the default) or
    "quick". Returns the test view. ApiError 400 when the draft doesn't pass the editor's checks,
    its size differs, only the sideboard changed, or nothing did; 403 without a profile or while the simulations setting refuses (api/simulations.py); 503 when
    Forge isn't ready, lacks deck-order-1, or too many tests are waiting."""
    data = _parse_body(body)
    profile = _writer(data)
    guard.require_start(profile)        # the simulations setting (api/simulations.py)
    forge = _forge()
    _keys(data, ("profile", "id", "version", "list", "against"), ("mode",))
    version = data["version"]
    if version not in ("target", "owned"):
        raise ApiError(400, "version must be target or owned")
    mode = data.get("mode", "ahead")
    if mode not in ("ahead", "quick"):
        raise ApiError(400, 'mode must be "ahead" or "quick"')
    against = data["against"]
    if against != "field":
        if not isinstance(against, dict) or not isinstance(against.get("id"), str):
            raise ApiError(400, 'against must be "field" or {"id", "version"} of a deck')
        if set(against) - {"id", "version"}:
            raise ApiError(400, 'against must be "field" or {"id", "version"} of a deck')
    base, against_ = (_base_and_against(forge, data["id"], version, "field") if against == "field" else
                      _base_and_against(forge, data["id"], version, against["id"], against.get("version")))
    _require_owner(base, profile)
    cards, sections = _draft_cards(forge, data["id"], version, data["list"])
    _, card_sha, count = forge.lists._list_text(cards, base["kind"])
    if card_sha == base["card_sha"]:
        if _sideboard(sections) != _sideboard(decks.load_deck(data["id"], version)):
            raise ApiError(400, forge.variants.SIDEBOARD_ONLY)
        raise ApiError(400, forge.variants.NO_CHANGE)
    if count != base["card_count"]:
        raise ApiError(400, f"{SIZE_WORDS}: the saved list has {base['card_count']} and this one {count}.")
    try:
        variant = forge.variants.variant_entry(base, cards)
    except ValueError as e:
        raise ApiError(400, str(e)) from None
    if against_ == "field":
        _, problem = _opponents(forge, base, "field", forge_runs._Seen(profile))
        if problem:
            raise ApiError(400, problem)
    _ready(forge)
    seen = forge_runs._Seen(profile)
    options = _field_options(forge, base, seen) if against_ == "field" else None
    test = forge.variants.test_id(base, variant, against_, mode, field_space=(options or {}).get("space"))
    _submit(_VariantRun(forge, test, base, cards, against_, mode, profile["name"], field_options=options,
                        by_id=profile["id"]), rerun=True)
    return _view(forge, test, forge_runs._Seen(profile))


def stop_variant(body):
    """POST /api/variant/stop {"profile", "test"} (section 11.5): Stop. A waiting test is taken off
    the queue; a playing one stops its pair runs (each saves the games it finished) and makes a look
    at what's there ("Stopped early"). A visible test may be stopped by its starter, a named
    deck's space or an admin. A hidden test answers 404 except to an admin, whose response is
    only {"test", "stopped", "hidden": True}."""
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    forge = _forge()
    _keys(data, ("profile", "test"))
    test = _test_id(data["test"])
    seen = forge_runs._Seen(profile)
    job = forge_runs.COORD_JOBS.get(_job_key(test))
    summary = _pending(job.fn) if job is not None else forge.variants.load_summary(test)
    visible = summary is not None and _sees_test(summary, seen)
    if job is not None:
        seen.require_stop(job, visible, TEST_NONE)
    elif not visible:
        raise ApiError(404, TEST_NONE)
    stopped = job is not None and forge_runs.COORD_JOBS.cancel(_job_key(test), by=profile["name"])
    if stopped:
        job.wait(forge_runs.STOP_WAIT)
    if not visible:
        return {"test": test, "stopped": stopped, "hidden": True}
    return _view(forge, test, seen)


def more_variant(body):
    """POST /api/variant/more {"profile", "test"} (section 11.5): "Play more", to the next look and on
    as "Until it's clear". ApiError 404 for no such test, 409 when the deck's list has changed since
    or the test is already playing to its last look, 503 as run_variant."""
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    guard.require_start(profile)        # the simulations setting (api/simulations.py)
    forge = _forge()
    _keys(data, ("profile", "test"))
    test = _test_id(data["test"])
    seen = forge_runs._Seen(profile)
    job = forge_runs.COORD_JOBS.get(_job_key(test))
    if job is not None and forge_runs.COORD_JOBS.snapshot(job)["status"] in WAITING:
        if not _sees_test(_pending(job.fn), seen):
            raise ApiError(404, TEST_NONE)
        _require_owner(job.fn.base, profile)
        return _view(forge, test, seen)     # already playing: join it
    summary = forge.variants.load_summary(test)
    if summary is None or not _sees_test(summary, seen):
        raise ApiError(404, TEST_NONE)
    base_ = summary["base"]
    _require_owner(base_, profile)
    against = summary["against"]
    try:
        if isinstance(against, str):
            base, against_ = _base_and_against(forge, base_["id"], base_["version"], "field")
        else:
            base, against_ = _base_and_against(forge, base_["id"], base_["version"], against["id"],
                                               against.get("version"))
    except ApiError as e:
        if e.status == 404:
            raise ApiError(409, forge.variants.LIST_CHANGED) from None
        raise
    if base["card_sha"] != base_["card_sha"]:
        raise ApiError(409, forge.variants.LIST_CHANGED)
    if forge.variants._looks("ahead", isinstance(against, str))[-1] <= max(
            [look["games_per_opponent"] for look in summary.get("looks") or [] if not look.get("stopped")] or [0]):
        raise ApiError(409, forge.variants.NO_MORE)
    cards = (summary.get("variant") or {}).get("cards")
    if not cards:
        raise ApiError(409, "This test's changed list wasn't saved with it, so it can't play more: start a new test.")
    _ready(forge)
    options = _field_options(forge, base, seen) if against_ == "field" else None
    _submit(_VariantRun(forge, test, base, cards, against_, summary.get("mode"), profile["name"], extend=test,
                        opponents=summary.get("limited"), field_options=options, by_id=profile["id"]), rerun=True)
    return _view(forge, test, seen)
