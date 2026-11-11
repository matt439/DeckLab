"""Starter-private run recovery; all launches re-enter the ordinary validated handlers."""
from contextlib import contextmanager
from contextvars import ContextVar
import copy
import hashlib
import importlib
import json
import re
from urllib.parse import quote

from decklab.lib import decks, inventory, jobs, permissions, state, visibility
from . import guard
from .common import ApiError, _keys, _parse_body

_capture = ContextVar("decklab_run_recovery_capture", default=False)
_expected = ContextVar("decklab_run_recovery_expected", default=None)
SHA = re.compile(r"[0-9a-f]{64}\Z")
UNVERIFIED = "Unfinished-run recovery cannot be verified on the PC. No new run was started."
MAX_BODY = 2048
MISSING = "That unfinished run isn't available."
LABELS = {"field": "field run", "group": "group run", "gauntlet": "gauntlet run", "variant": "test of a change",
          "variant_more": "extended test of a change"}


class Prepared(Exception):
    def __init__(self, value):
        self.value = value


def _journal():
    return importlib.import_module("decklab.lib.forge.run_journal")


def _hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _refs(entries, forge, engine):
    out = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) \
                or not isinstance(entry.get("card_sha"), str) or not SHA.fullmatch(entry["card_sha"]):
            raise ValueError("A run reference is unavailable")
        side = forge.engine.entry_side_id(entry, eng=engine)
        if not isinstance(side, str) or not SHA.fullmatch(side):
            raise ValueError("A run side identity is unavailable")
        out.append({**{key: entry.get(key) for key in ("id", "version", "card_sha", "kind")},
                    "pilot": forge.engine.played_pilot(entry, engine), "side": side})
    return sorted(out, key=lambda item: (item["id"], str(item["version"])))


def _is_sparring(deck_id):
    from decklab.lib.gauntlet import is_gauntlet_id
    return is_gauntlet_id(deck_id)


@contextmanager
def _fresh_visibility():
    try:
        fresh = state.store().visibility()
    except Exception:
        raise ApiError(503, UNVERIFIED) from None
    with visibility.pinned():
        visibility.replace(fresh)
        yield


def _visible(refs, profile):
    return all(_is_sparring(ref["id"]) or guard.sees_deck(ref["id"], profile) for ref in refs)


def _engine(forge, *, read_only=False):
    source = forge.engine.read_only_today if read_only else forge.engine.today
    value = source()
    if not isinstance(value, dict) or value.get("complete") is not True:
        raise ValueError("The engine identity is unverified")
    if not isinstance(value.get("ai_sha"), dict):
        raise ValueError("The AI profile identity is unverified")
    return value


def _canonical(kind, request, run, profile):
    data = copy.deepcopy(request)
    data["profile"] = profile["id"]
    if kind in ("field", "group", "gauntlet"):
        data.update(id=run.entry["id"], version=run.entry["version"], budget=run.budget,
                    expected_card_sha=run.entry["card_sha"])
        if kind == "gauntlet":
            data = {key: data[key] for key in ("profile", "id", "version", "budget", "expected_card_sha")}
            data["sample"] = run.full["id"]
        elif kind == "group":
            data["opponents"] = [entry["id"] + "@" + entry["version"] for entry in run.chosen]
    elif kind == "variant":
        data.update(id=run.base["id"], version=run.version, mode=run.mode)
        if isinstance(run.against, str) and run.against.startswith("gauntlet:"):
            data["against"] = run.against   # retain the exact saved sample, never redraw the standard one
    return data


def _variant_work(run, opponents, summary, looks, complete):
    """A numeric upper bound, refined from verified saved session work only at submission."""
    games = max(looks) * len(opponents) * 2
    v = run.forge.variants
    try:
        if summary is not None and v._keys_today(summary, run.base, opponents):
            if complete:
                return {"games": 0, "approximate": True}
            from . import variant_page
            variant = v.variant_entry(run.base, run.cards)
            games = v._planned(run.base, variant, opponents, summary, max(looks),
                               variant_page._results_of(run.forge, run.test))
    except Exception:
        pass        # saved data cannot reduce an unverified upper bound
    return {"games": games, "approximate": True}


def _prepare(forge, kind, run, profile, request):
    snapshot = inventory.current()
    if snapshot.stale or not snapshot.persisted:
        raise ApiError(503, UNVERIFIED)
    engine = _engine(forge, read_only=_capture.get())
    if kind in ("field", "group", "gauntlet"):
        base = run.entry
        if kind == "gauntlet":
            plan = run.g.plan(run.entry, run.sample, run.budget)
        else:
            options = dict(run.options)
            if kind == "group":
                options["opponent_entries"] = run.chosen
            plan = forge.field.plan(run.entry, run.budget, **options)
        opponents = [pair["opponent"] for pair in plan["pairs"]]
        refs = _refs([run.entry, *opponents], forge, engine)
        keys = sorted(pair["key"] for pair in plan["pairs"])
        target = plan["per_opponent"]
        remaining = plan["new_games"]
        work = {"games": remaining, "approximate": True}
        extras = {"target": target, "pair_keys": keys, "budget": run.budget}
        if kind == "gauntlet":
            extras["sample"] = run.sample["id"]
    else:
        base = run.base
        from . import variant_page
        v = forge.variants
        opponents = v._opponent_entries(run.base, run.against, run.opponents, run.field_options)
        refs = _refs([run.base, *opponents], forge, engine)
        field = isinstance(run.against, str)
        looks = list(v._looks("ahead" if run.extend else run.mode, field))
        summary = variant_page._load_summary(forge, run.test)
        good = max([look["games_per_opponent"] for look in (summary or {}).get("looks", []) if not look.get("stopped")] or [0])
        previous = (_expected.get() or {}).get("manifest", {}).get("prior_look", good)
        terminal = (summary or {}).get("outcome") in v.seqstats.PAIRED_VERDICTS or good >= max(looks)
        complete = terminal and (not run.extend or good > previous)
        remaining = 0 if complete else 1     # the original backend, not this receipt, allocates every saved game
        work = _variant_work(run, opponents, summary, looks, complete)
        extras = {"test": run.test, "looks": looks, "prior_look": previous if run.extend else 0}
    if not _visible(refs, profile):
        raise ApiError(404, "That unfinished run isn't available.")
    engine_hash = _hash({**{key: engine[key] for key in forge.engine.ENGINE_FIELDS}, "ai_sha": engine["ai_sha"]})
    base_ref = _refs([base], forge, engine)[0]
    manifest = {"refs": refs, "base": base_ref, "engine": engine_hash, **extras}
    identities = sorted((permissions._deck_space(ref["id"]) or "reference", str(ref["version"] or ""),
                         ref["card_sha"], str(ref["kind"] or ""), ref["side"], _hash(ref["pilot"])) for ref in refs)
    base_identity = (permissions._deck_space(base["id"]), base.get("version"), base["card_sha"], base.get("kind"),
                     base_ref["side"], _hash(base_ref["pilot"]))
    manifest["signature"] = _hash({"kind": kind, "engine": manifest["engine"], "base": base_identity, "lists": identities, **extras})
    return {"manifest": manifest, "remaining": remaining, "request": _canonical(kind, request, run, profile),
            "planned_work": work}


class Binding:
    def __init__(self, kind, prepared, profile, results_root):
        self.kind, self.prepared = kind, copy.deepcopy(prepared)
        self.starter = profile["id"]
        self.results_root = results_root
        self.journal = _journal().store()
        self.expected = copy.deepcopy(_expected.get())
        self.record_id = None

    @contextmanager
    def scope(self):
        ids = [ref["id"] for ref in self.prepared["manifest"]["refs"]]
        with _journal().lifecycle.writer(self.results_root, deck_ids=ids):
            yield

    def event(self, event, job):
        if event == "queued":
            with self.scope():
                if self.expected is None:
                    record = self.journal.create(self.starter, self.kind, self.prepared["request"], self.prepared["manifest"])
                else:
                    record = self.journal.claim(self.starter, self.expected["id"], self.prepared["manifest"])
                self.record_id = record["id"]
        elif self.record_id is not None:
            if event in ("running", "interrupted"):
                with self.scope():
                    self.journal.transition(self.starter, self.record_id, event)
            else:
                self.journal.transition(self.starter, self.record_id, event)


def submit(forge, kind, run, profile, request, key, *, rerun=True):
    """Called only after ordinary start validation, immediately before COORD_JOBS.submit."""
    from . import forge_runs
    try:
        with _fresh_visibility():
            prepared = _prepare(forge, kind, run, profile, request)
        if _capture.get():
            raise Prepared(prepared)
        binding = Binding(kind, prepared, profile, forge.common._results_dir())
        run._journal_event, run._journal_scope, run._journal_binding = binding.event, binding.scope, binding
        job = forge_runs.COORD_JOBS.submit(key, run, rerun=rerun, planned_work=prepared["planned_work"])
        if binding.expected is not None and job.fn is not run:
            raise ApiError(409, "This saved list is already running. Finish or stop that run before resuming.")
        return job
    except (Prepared, ApiError, jobs.Busy):
        raise
    except ValueError as error:
        if _expected.get() is not None:
            raise ApiError(409, str(error)) from None
        raise ApiError(503, UNVERIFIED) from None
    except Exception:
        raise ApiError(503, UNVERIFIED) from None


def _dispatch(kind, request):
    from . import field_group, field_page, gauntlet_page, variant_page
    functions = {"field": field_page.run_field, "group": field_group.run_group, "gauntlet": gauntlet_page.run_gauntlet,
                 "variant": variant_page.run_variant, "variant_more": variant_page.more_variant}
    return functions[kind](json.dumps(request).encode("utf-8"))


def _preview(record):
    captured, expected = _capture.set(True), _expected.set(record)
    try:
        _dispatch(record["kind"], record["request"])
    except Prepared as prepared:
        return prepared.value
    finally:
        _capture.reset(captured)
        _expected.reset(expected)
    raise ApiError(409, "This saved list is already running. Finish or stop that run before resuming.")


def _profile():
    profile = guard.viewer()
    if profile is None:
        raise ApiError(403, "Choose the person who started this run.")
    return profile


def _owned(profile, record_id):
    if not isinstance(record_id, str) or not _journal().ID.fullmatch(record_id):
        raise ApiError(400, "Choose an unfinished run.")
    record = _journal().store().get(profile["id"], record_id)
    if record is None:
        raise ApiError(404, MISSING)
    refs = record["manifest"].get("refs")
    if not isinstance(refs, list) or not refs:
        raise ApiError(503, UNVERIFIED)
    if not _visible(refs, profile):
        raise ApiError(404, MISSING)
    return record


def _offer(record, profile):
    inactive = _journal().store().inactive(record)
    if inactive is False:
        return None
    if not _visible(record["manifest"]["refs"], profile):
        return None
    may, why = False, None
    try:
        if inactive is None:
            raise ApiError(503, "The original server's ownership cannot be verified. No work will be resumed; check recovery metadata on the PC.")
        prepared = _preview(record)
        if prepared["manifest"]["signature"] != record["manifest"].get("signature"):
            why = "The saved lists, engine or original participants changed. Dismiss this offer and start a new run if intended."
        elif prepared["remaining"] == 0:
            # Operational completion bookkeeping only; no run, inventory or state write.
            _journal().store().transition(profile["id"], record["id"], "done")
            return None
        else:
            may = True
    except ApiError as error:
        why = error.message
    base = record["manifest"].get("base") or {}
    summary = decks.find_summary(base.get("id")) if isinstance(base.get("id"), str) else None
    title = (summary or {}).get("title")
    label = "Unfinished " + LABELS[record["kind"]]
    if isinstance(title, str) and title:
        label += ": " + title[:160]
    return {"id": record["id"], "kind": record["kind"], "title": label, "created": record["created"],
            "may_resume": may, "why_not": why,
            "link": "#/deck?id=" + quote(base["id"], safe="") if isinstance(base.get("id"), str) else None}


def view():
    profile = guard.viewer()
    if profile is None:
        return {}
    try:
        records = _journal().store().records(profile["id"])
        if not records:
            return {"available": True, "unfinished": []}    # no DB/engine work or optional-Forge warning for an empty journal
        with _fresh_visibility():
            offers = [_offer(record, profile) for record in records]
        return {"available": True, "unfinished": sorted((offer for offer in offers if offer is not None),
                                                          key=lambda item: (item["created"], item["id"]), reverse=True)}
    except Exception:
        return {"available": False, "unfinished": [], "message": "Unfinished-run recovery cannot be checked on the PC right now."}


def resume(body):
    profile = _profile()                       # no anonymous or admin override, before reading a journal
    data = _parse_body(body, MAX_BODY)
    _keys(data, ("profile", "id"))
    if data["profile"] != profile["id"]:
        raise ApiError(403, "You can only make changes as yourself.")
    try:
        with _fresh_visibility():
            record = _owned(profile, data["id"])
            inactive = _journal().store().inactive(record)
            if inactive is None:
                raise ApiError(503, UNVERIFIED)
            if inactive is False:
                raise ApiError(409, "This run is still active. Use its normal Stop control.")
            prepared = _preview(record)        # ordinary permissions, simulations, saved lists and engine; no queue
            if prepared["manifest"]["signature"] != record["manifest"].get("signature"):
                raise ApiError(409, "The original saved lists, engine or participants changed. Start a new run instead.")
            if prepared["remaining"] == 0:
                _journal().store().transition(profile["id"], record["id"], "done")
                return {"resumed": False, "complete": True}
            expected = _expected.set(record)
            try:
                _dispatch(record["kind"], record["request"])
            finally:
                _expected.reset(expected)
        return {"resumed": True, "complete": False}
    except ApiError:
        raise
    except Exception:
        raise ApiError(503, UNVERIFIED) from None


def dismiss(body):
    profile = _profile()
    data = _parse_body(body, MAX_BODY)
    _keys(data, ("profile", "id"))
    if data["profile"] != profile["id"]:
        raise ApiError(403, "You can only make changes as yourself.")
    try:
        with _fresh_visibility():
            record = _owned(profile, data["id"])
            if _journal().store().inactive(record) is False:
                raise ApiError(409, "This run is still active. Use its normal Stop control.")
            _journal().store().transition(profile["id"], record["id"], "dismissed")
        return {"dismissed": True}
    except ApiError:
        raise
    except Exception:
        raise ApiError(503, "The recovery offer could not be dismissed on the PC.") from None
