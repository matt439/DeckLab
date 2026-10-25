"""The simulations setting: who may start Forge runs, and how many Forge workers the PC uses
at once, so an admin can keep the PC free while it's busy (a game, a build).

    GET /api/simulations    {"mode", "may_start", "why_not", "may_edit"}, plus "by", "since",
                             "workers" and "max_workers" only when may_edit (an admin, a
                             script: E10-S34, decision F), and "unavailable": true when
                             the database couldn't be read
    PUT /api/simulations    {"profile", "mode"?, "workers"?}: an admin's (simulations.edit)

- mode (permissions.RUN_MODES): "admins" (the default: only admins may start a run),
  "everyone" or "paused" (nobody may). It's kept in the state store (decklab.lib.state's
  simulation_mode table) with who set it and when. Starting a run is permissions'
  "run.start": a matchup, a field run, a variant test and its "Play more"
  (guard.require_start). Practice hands and the assembly plan stay open to everyone, and runs
  already waiting or playing go on; stopping one is "run.stop", only an admin's for now (E10-S30).
- While the database can't be read, the mode is the last one this server read or wrote (so a
  pause holds), else the default; the answer says "unavailable". A change needs the database.
- workers: the PC's worker limit (forge/slots.py's limit(), None: none), at most max_workers
  (config.json's forge_workers). It's a file every Forge process reads, not the database's. It
  holds for every Forge run on the PC, the command line's too, from each run's next chunk or
  batch.
- may_start and why_not are for the viewer (guard.viewer(): the login's profile, or the one
  the page's chooser names at home), may_edit whether it may change the setting. why_not
  names nobody ("Only an admin can start simulations right now. ..."), so a member doesn't
  learn who the admins are (E10-S34, decision F).
"""
import threading

from decklab.lib import config, permissions, state

from . import common
from .common import MAX_BODY, ApiError, _keys, _parse_body, _public, state_errors

DEFAULT_MODE = "admins"         # the owner's choice of 2026-10-11

_lock = threading.Lock()
_log_lock = threading.Lock()     # guards _fell_back
_fell_back = False              # logged that the mode couldn't be read (once until it can again)


def _read():
    """{"mode", "by", "since"} as saved, and whether the database couldn't be read: then the
    last mode this server read or wrote, else the default (admins), as when none was ever set.
    Any error falls back so, the store's own and a raw database error it doesn't name alike:
    starting a run and the footer must never fail over it."""
    global _fell_back
    store = state.store()
    unavailable = False
    try:
        saved = store.simulation_mode()
        with _log_lock:
            _fell_back = False
    except Exception as e:
        unavailable = True
        try:
            saved = store.simulation_mode_cached()
        except Exception:
            saved = None
        with _log_lock:
            first, _fell_back = not _fell_back, True
        if first:
            common._log(f"The simulations setting couldn't be read ({_public(e)}); using "
                        f"{saved['mode'] if saved else DEFAULT_MODE} until it can")
    if not saved or saved.get("mode") not in permissions.RUN_MODES:
        return {"mode": DEFAULT_MODE, "by": None, "since": None}, unavailable
    return {"mode": saved["mode"], "by": saved.get("by"), "since": saved.get("since")}, unavailable


def mode():
    """The simulations mode now: "everyone", "admins" or "paused" (never raises: see _read)."""
    return _read()[0]["mode"]


def _slots():
    from decklab.lib.forge import slots
    return slots


def _max_workers():
    try:
        return _slots()._budget(None)
    except (ValueError, TypeError):
        return config.DEFAULTS["forge_workers"]


def view(profile=False):
    """GET /api/simulations (the module docstring), for profile (the viewer when it's left out)."""
    from . import guard
    if profile is False:
        profile = guard.viewer()
    saved, unavailable = _read()
    why = permissions.reason(profile, "run.start", saved["mode"], script=guard.script())
    may_edit = permissions.can(profile, "simulations.edit", script=guard.script())
    answer = {"mode": saved["mode"], "may_start": why is None, "why_not": why, "may_edit": may_edit}
    if may_edit:
        # Who set it, when, and the PC's workers: only to whoever may change it (an admin, a
        # script), never a member (E10-S34, decision F). why_not names nobody either.
        answer.update(by=saved.get("by"), since=saved.get("since"), workers=_slots().limit(),
                      max_workers=_max_workers())
    if unavailable:
        answer["unavailable"] = True
    return answer


def change(body):
    """PUT /api/simulations {"profile", "mode"?, "workers"?}: workers a whole number from 1 to
    max_workers, or None for no limit. The mode is saved first, so when the database can't be
    used (ApiError 503) the limit isn't changed either. Returns view() for the profile.
    ApiError 400 for a bad value, 403 for someone who isn't an admin, 500 when the limit
    can't be saved."""
    from . import guard
    from .settings import _web_actor
    data = _parse_body(body, MAX_BODY)
    _keys(data, ("profile",), ("mode", "workers"))
    profile = guard.writer(data, "simulations.edit")
    if "mode" in data and data["mode"] not in permissions.RUN_MODES:
        raise ApiError(400, f"mode must be one of: {', '.join(permissions.RUN_MODES)}")
    top = _max_workers()
    workers = data.get("workers")
    if "workers" in data and workers is not None and not (type(workers) is int and 1 <= workers <= top):
        raise ApiError(400, f"workers must be a whole number from 1 to {top}, or null for no limit")
    with _lock:
        if "mode" in data:
            with state_errors():
                state.store().simulation_mode_set(data["mode"], _web_actor(profile),
                                                  f"Set simulations to {data['mode']}")
        if "workers" in data:
            try:
                _slots().set_limit(None if workers is None or workers >= top else workers)
            except OSError as e:
                raise ApiError(500, f"The simulations setting couldn't be saved: {_public(e)}") from None
    return view(profile)
