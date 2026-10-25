"""Shared argument handling, deck lookup and dependencies for the Forge CLI.

The compatibility facade in cli.py forwards old patch targets here; callers use
this module directly so a patched dependency has one authoritative binding."""
import argparse
import json
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

from decklab.lib import config, decks

from . import (ai, cardlog, cardstats, common, engine, install, lists, overrides, pilots, pool, processes, runner, saved,
               seeds, servecheck, simjar, slots)
from .ai import ai_limits
from .common import DEFAULT_GAMES, GAME_CHOICES, ForgeError, _os_reason
from .install import _setup, status
from .lists import entry, entry_from_dck
from .logreader import AI_TIMEOUT, RE_HEADER, SLOW_STOP, LogReader
from .processes import _end_process
from .runner import _prepare_user_dir, run
from .views import _perspective, results, verdict_words, view


class _CliError(Exception):
    """A plain sentence for the command line, which then exits with 1."""


# The kind entry() and ai_limits() take for a library summary: "commander" or
# "constructed" (decks.engine_kind, kept here under its old name).
engine_kind = decks.engine_kind


def _cli_list(deck_id, owned):
    """(summary, version, kind, sections) of a deck id's target or owned-only list."""
    summary = decks.find_summary(deck_id)
    if summary is None or summary.get("error"):
        raise _CliError(f"No deck {deck_id!r}")
    version = "owned" if owned else "target"
    if version not in summary["versions"]:
        raise _CliError(f"{deck_id} has no owned-only list")
    try:
        sections = decks.load_deck(summary["id"], version)
    except (decks.DeckNotFound, decks.DeckFileError) as e:
        raise _CliError(f"{deck_id} can't be read: {e}") from None
    return summary, version, engine_kind(summary), sections


def _cli_entry(ref, owned):
    """An entry from a deck id or a .dck file."""
    if ref.lower().endswith(".dck"):
        try:
            found = entry_from_dck(ref)
        except FileNotFoundError:
            raise _CliError(f"There's no deck file called {ref}.") from None
        except OSError as e:
            raise _CliError(f"The deck file {ref} can't be read ({_os_reason(e)}).") from None
        except ValueError:          # not UTF-8
            raise _CliError(f"The deck file {ref} can't be read (it isn't UTF-8 text).") from None
        if not found["card_count"]:
            raise _CliError(f"The deck file {ref} has no cards in [Main] or [Commander].")
        return found
    summary, version, kind, sections = _cli_list(ref, owned)
    return entry(summary["id"], version, summary["title"], kind, sections)


def _positive(text):
    """argparse's type for --workers and --batch: a whole number of 1 or more."""
    try:
        number = int(text)
    except ValueError:
        number = 0
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be a whole number of 1 or more, not {text!r}")
    return number


def _games_problem(games, batch):
    """Why --games doesn't suit (--batch), or None."""
    if batch is None and games not in GAME_CHOICES:
        return f"Games must be one of {', '.join(map(str, GAME_CHOICES[:-1]))} or {GAME_CHOICES[-1]}."
    if batch is not None and (games < 1 or games % batch):
        return f"Games must be a whole number of batches of {batch} (--batch)."
    return None


def _stopped_message(e):
    """What the command line says when Ctrl+C stopped it."""
    saved = getattr(e, "saved_games", None)
    if not saved:
        return "Stopped."
    if saved == 1:
        return "Stopped: the game that finished was saved."
    return f"Stopped: the {saved:,} games that finished were saved."


def _log_options(args):
    """runner.run's log tee keywords from _log_args' options ({} until wave 3's R adds them)."""
    logs = getattr(args, "logs_dir", None)
    return {"log_dir": logs, "log_every": getattr(args, "log_every", None) or 1} if logs else {}


NOT_BUILT = "This command isn't built yet (simulation wave 2)."


def _not_built(command, package):
    print(f"The {command} command isn't built yet (wave 3's package {package}).", file=sys.stderr)
    return 1


def _log_args(parser):
    """Add --logs-dir and --log-every (the log tee, runner.run's log_dir and log_every:
    sim-wave3-contract.md section 8) to a command's parser; _log_kwargs(args) reads them back
    as runner.run's keywords."""
    parser.add_argument("--logs-dir", help="write Forge's output of the games played, gzip-compressed, to "
                                           "<folder>/<matchup key>/<first game>-<last game>.log.gz")
    parser.add_argument("--log-every", type=_positive, default=1,
                        help="with --logs-dir: only the games of every Nth block of 25 game numbers (1: all)")
    return parser


def _log_kwargs(args):
    """runner.run's log_dir and log_every from a command's --logs-dir and --log-every
    (_log_args): {} without --logs-dir (no tee), so a command can pass them on as they are."""
    folder = getattr(args, "logs_dir", None)
    if not folder:
        return {}
    return {"log_dir": folder, "log_every": getattr(args, "log_every", None) or 1}


def _same_folder(a, b):
    """Whether two paths name the same folder (resolved; as given when they can't be)."""
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return Path(a) == Path(b)
