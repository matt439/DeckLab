"""Forge command-line entry point and compatibility facade.

Commands and helpers live in cli_shared, cli_output, cli_checks, cli_commands,
cli_results, cli_evaluate, cli_soak, cli_engine and cli_upgrade. Existing cli.<name> reads and
patches forward to their owner; no function or mutable state is copied into this module."""
import types

from . import cli_shared as _shared
from . import cli_output as _output
from . import cli_checks as _checks
from . import cli_commands as _commands
from . import cli_results as _results
from . import cli_evaluate as _evaluate
from . import cli_soak as _soak
from . import cli_engine as _engine
from . import cli_upgrade as _upgrade


def main(argv=None):
    try:
        return _main(argv)
    except KeyboardInterrupt as e:
        print("\n" + _shared._stopped_message(e), file=_shared.sys.stderr)
        return 130
    except _shared.ForgeError as e:
        print(f"Error: {e}", file=_shared.sys.stderr)
        return 1
    except _shared._CliError as e:
        print(e, file=_shared.sys.stderr)
        return 1


# The commands, in the order --help lists them: name -> (adds its parser, runs it).
COMMANDS = {
    "status": (_commands._status_args, _commands._cmd_status),
    "audit": (_commands._audit_args, _commands._cmd_audit),
    "play": (_commands._play_args, _commands._cmd_play),
    "list": (_commands._list_args, _commands._cmd_list),
    "cards": (_commands._cards_args, _commands._cmd_cards),
    "cardlog-check": (_checks._cardlog_check_args, _checks._cmd_cardlog_check),
    "slots": (_commands._slots_args, _commands._cmd_slots),
    "replay": (_results._replay_args, _results._cmd_replay),
    "pool": (_commands._pool_args, _commands._cmd_pool),
    "serve-check": (_checks._serve_check_args, _checks._cmd_serve_check),
    "field": (_evaluate._field_args, _evaluate._cmd_field),
    "variant": (_evaluate._variant_args, _evaluate._cmd_variant),
    "experiment": (_evaluate._experiment_args, _evaluate._cmd_experiment),
    "pilots": (_commands._pilots_args, _commands._cmd_pilots),
    "overrides": (_commands._overrides_args, _commands._cmd_overrides),
    "staged-move": (_results._staged_move_args, _results._cmd_staged_move),
    "soak-probe": (_soak._soak_probe_args, _soak._cmd_soak_probe),
    "engine-check": (_engine._engine_check_args, _engine._cmd_engine_check),
    "decisions": (_engine._decisions_args, _engine._cmd_decisions),
    "upgrade-check": (_upgrade._upgrade_check_args, _upgrade._cmd_upgrade_check),
}


def _main(argv):
    _shared.sys.stdout.reconfigure(errors="replace")
    parser = _shared.argparse.ArgumentParser(prog="python -m decklab.lib.forge", description="Forge matchups for Deck Lab.")
    sub = parser.add_subparsers(dest="command", required=True)
    for add, _ in COMMANDS.values():
        add(sub)
    args = parser.parse_args(argv)
    return COMMANDS[args.command][1](args)


# Preserve the existing CLI names and mock.patch.object(cli, name) targets without
# shadow copies. Internal callers read the owning module, not this facade.
_OWNERS = {name: part for part, names in (
    (_shared, (
        'argparse', 'json', 're', 'shutil', 'sys', 'tempfile', 'threading', 'time', 'traceback', 'Path',
        'config', 'decks', 'ai', 'cardlog', 'cardstats', 'common', 'engine', 'install', 'lists', 'overrides',
        'pilots', 'pool', 'processes', 'runner', 'saved', 'seeds', 'servecheck', 'simjar', 'slots',
        'ai_limits', 'DEFAULT_GAMES', 'GAME_CHOICES', 'ForgeError', '_os_reason', '_setup', 'status', 'entry',
        'entry_from_dck', 'AI_TIMEOUT', 'RE_HEADER', 'SLOW_STOP', 'LogReader', '_end_process',
        '_prepare_user_dir', 'run', '_perspective', 'results', 'verdict_words', 'view', '_CliError',
        'engine_kind', '_cli_list', '_cli_entry', '_positive', '_games_problem', '_stopped_message',
        '_log_options', 'NOT_BUILT', '_not_built', '_log_args', '_log_kwargs', '_same_folder',
    )),
    (_output, (
        '_pct', 'WEAK_WORDS', 'PILOT_WHY', '_weak_words', '_pump_split', '_print_pilot', '_print_limits',
        'TEMPO_WORDS', 'COMMANDER_WORDS', '_lead_words', '_starter_words', '_noise_words', '_pilot_reason',
        '_trust_lines', '_range', 'VERDICTS', 'EARLY', 'LEANS', '_diff', '_print_cards', '_print_slots',
        '_setup_lines', '_pool_words', '_pool_line', 'LOOK_WORDS', '_look_line', '_until_words',
        '_nothing_played_words', '_print_play', 'AUTO_PROFILE_WORDS', 'AUTO_PROFILE_WHY', '_engine_lines',
        '_engine_mark',
    )),
    (_checks, (
        'CHECK_SEED', 'CHECK_GAMES', 'CHECK_COMMANDER_GAMES', 'CHECK_MAX_GAMES', 'CHECK_PROCESSES',
        'CHECK_REASONS', 'CHECK_DECKS', 'CHECK_COMMANDER_DECKS', 'RE_TIMING', 'RE_ORDINAL', 'RE_FRAME',
        'JVM_WARNING', 'TIME_LIMITS', 'RE_ATTACKERS', 'RE_ATTACKER', 'LINE_FOR_LINE', 'PARITY', 'CARD_LOG_LEG',
        '_check_legs', '_check_sides', '_seated', '_split_games', '_attackers_in_order', '_games_text',
        '_compare', '_first_difference', '_outcomes', '_outcome', '_compare_outcomes', '_with',
        '_time_limit_hit', '_time_limit_game', '_names_both_commanders', '_card_log_problems', '_leg_problem',
        '_said', '_said_lock', '_say_once', '_check_slot', '_CheckProcesses', '_CheckStopped', '_check_run',
        '_check_runs', 'CHECK_STOP_WAIT', '_play_check_runs', '_CardLogUnavailable', '_cardlog_check', '_check_games',
        '_cardlog_check_args', '_cmd_cardlog_check', '_serve_check_args', '_cmd_serve_check',
    )),
    (_commands, (
        '_status_args', '_cmd_status', '_audit_args', '_cmd_audit', '_play_args', '_cmd_play',
        '_cmd_play_until', '_list_args', '_cmd_list', '_cards_args', '_cmd_cards', '_slots_args', '_cmd_slots',
        '_pool_args', 'NO_POOL', '_cmd_pool', '_pilots_args', '_cmd_pilots', 'OVERRIDES_ACTIONS',
        '_overrides_args', '_cmd_overrides', '_overrides_list',
    )),
    (_results, (
        'REPLAY_MATCHUPS', 'REPLAY_BY', 'REPLAY_REPORT_S', 'REPLAY_NOT_READY', 'REPLAY_STILL_STOPPING',
        '_ReplayLists', '_replay_speed', '_replay_plan', '_replay_estimate', '_about', '_replay_name',
        '_replay_json', '_replay_time', '_print_replay_plan', '_replay', '_replay_args', '_cmd_replay',
        'STAGED_SERVER_UP',
        '_staged_move_args', '_staged_held', '_StagedGone', '_staged_today_sides', '_staged_differs',
        '_staged_plan', '_staged_move_file', '_cmd_staged_move',
    )),
    (_evaluate, (
        'FIELD_REPORT_S', '_field_budget', '_field_args', '_field_rate', '_field_verdict', '_print_field',
        '_field_minutes', '_cmd_field', '_variant_args', '_variant_cards', '_cmd_variant', '_print_variant',
        '_experiment_args', '_cmd_experiment', '_print_experiment_plan',
    )),
    (_soak, (
        'SOAK_NO_SERVER', 'SOAK_RECENT_S', 'SOAK_AT_ONCE', 'SOAK_WARM_FEATURES', '_soak_probe_args',
        '_soak_server_live', '_soak_paired', '_soak_logs', '_soak_sample', '_soak_game_text', '_soak_fresh',
        '_soak_lines', 'SOAK_HEADER', '_soak_outcomes', '_soak_same', '_soak_difference', '_soak_warm',
        '_cmd_soak_probe',
    )),
    (_upgrade, (
        'UPGRADE_STEPS', '_Tee', '_first_line', '_overrides_reason', '_run_step', '_steps', 'upgrade_check',
        '_print_replay', '_plan', '_upgrade_check_args', '_cmd_upgrade_check',
    )),
) for name in names}

__all__ = ["main", "COMMANDS", *(name for name in _OWNERS if not name.startswith("_"))]


def __getattr__(name):
    if name in _OWNERS:
        return getattr(_OWNERS[name], name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(_OWNERS))


class _Facade(types.ModuleType):
    def __setattr__(self, name, value):
        if name in _OWNERS:
            setattr(_OWNERS[name], name, value)
        else:
            super().__setattr__(name, value)

    def __delattr__(self, name):
        if name in _OWNERS:
            delattr(_OWNERS[name], name)
        else:
            super().__delattr__(name)


_shared.sys.modules[__name__].__class__ = _Facade
