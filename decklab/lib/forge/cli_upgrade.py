"""Forge CLI: upgrade-check, the checks after a new build of Deck Lab's Forge is installed (E11-S15).

It runs cardlog-check, serve-check and the card-script overrides' upstream check (overrides
check), in that order and each as its own command does, going on past one that fails, then
prints one summary: each step passed, failed (and why) or was skipped (and why). When saved
matchups were played with another engine than today's, it also prints what replay --dry-run
would (each matchup's games and a rough time). It writes nothing its steps don't: cardlog-check
notes its result (simjar.record_checked or record_failed) as it does on its own, and the
overrides check only reads (overrides make, which writes the files again, stays a step of its
own). It never replays anything. --plan TAG prints the manual steps that come before it (rebase,
build, install) and runs nothing."""
import argparse
import contextlib

from . import cli_checks as checks
from . import cli_commands as commands
from . import cli_results as results
from . import cli_shared as shared


UPGRADE_STEPS = ("cardlog-check", "serve-check", "overrides check")
PASSED, FAILED, SKIPPED = "passed", "failed", "skipped"


class _Tee:
    """sys.stdout's stand-in while a step runs: everything is printed as usual and kept, so the
    summary can quote the step's first line."""

    def __init__(self, target):
        self.target = target
        self.parts = []

    def write(self, text):
        self.parts.append(text)
        return self.target.write(text)

    def flush(self):
        self.target.flush()

    def lines(self):
        return [line for line in "".join(self.parts).splitlines() if line.strip()]


def _first_line(lines, code):
    """Why a step failed: the first line it printed (cardlog-check and serve-check print the
    problem first), or its exit code when it printed nothing."""
    return lines[0] if lines else f"it ended with exit code {code}"


def _overrides_reason(lines, code):
    """Why the overrides check failed: its first problem (each is a "! " line), and how many more."""
    problems = [line[2:] for line in lines if line.startswith("! ")]
    if not problems:
        return _first_line(lines, code)
    return problems[0] + (f" ({len(problems) - 1} more above)" if len(problems) > 1 else "")


def _run_step(name, command, args, reason):
    """Run one step's command, printing as it goes: (state, why, no card log): (PASSED, None,
    False); (FAILED, why, False) for an exit code other than 0, a _CliError, a ForgeError or
    any other error (a bug, a full disk: its traceback logged, so the other steps still run);
    (FAILED, the error, True) when cardlog-check stopped because the card log can't be built
    (cli_checks._CardLogUnavailable). Ctrl+C isn't caught."""
    print(f"\n== {name} ==", flush=True)
    tee = _Tee(shared.sys.stdout)
    try:
        with contextlib.redirect_stdout(tee):
            code = command(args)
    except checks._CardLogUnavailable as e:
        print(e, file=shared.sys.stderr)
        return FAILED, str(e), True
    except shared._CliError as e:
        print(e, file=shared.sys.stderr)
        return FAILED, str(e), False
    except shared.ForgeError as e:
        print(f"Error: {e}", file=shared.sys.stderr)
        return FAILED, str(e), False
    except Exception as e:      # a bug or the OS: logged, and the other steps go on
        shared.common._log(f"{name} failed:\n{shared.traceback.format_exc()}")
        return FAILED, f"{type(e).__name__}: {e}", False
    if code == 0:
        return PASSED, None, False
    return FAILED, reason(tee.lines(), code), False


def _steps():
    """The steps as (name, the command's function, its args, the reason for a failure), read
    from their modules when called, so a test's patch of a command reaches them."""
    from . import servecheck
    return [
        ("cardlog-check", checks._cmd_cardlog_check,
         argparse.Namespace(games=checks.CHECK_GAMES, commander_games=checks.CHECK_COMMANDER_GAMES), _first_line),
        ("serve-check", checks._cmd_serve_check,
         argparse.Namespace(games=servecheck.GAMES, commander_games=servecheck.COMMANDER_GAMES, v1=False),
         _first_line),
        ("overrides check", commands._cmd_overrides,
         argparse.Namespace(action="check", set_name=None, user_dir=None, sets=None, json=False), _overrides_reason),
    ]


def upgrade_check():
    """Run the steps (UPGRADE_STEPS) and return [(name, state, why)]. cardlog-check and
    serve-check are skipped when Forge can't be set up (install._setup), and serve-check when
    cardlog-check couldn't build the card log (which serve-check needs too), but not when it
    failed after building it; the overrides check always runs."""
    try:
        shared._setup()
        setup_problem = None
    except shared.ForgeError as e:
        setup_problem = f"Forge can't be started: {e}"
    found = []
    card_log_problem = None
    for name, command, args, reason in _steps():
        if name in ("cardlog-check", "serve-check") and setup_problem:
            found.append((name, SKIPPED, setup_problem))
            continue
        if name == "serve-check" and card_log_problem:
            found.append((name, SKIPPED, f"cardlog-check couldn't build the card log, which it needs too: "
                                         f"{card_log_problem}"))
            continue
        state, why, error = _run_step(name, command, args, reason)
        if name == "cardlog-check" and error:
            card_log_problem = why
        found.append((name, state, why))
    return found


def _print_replay():
    """When saved matchups were played with another engine than today's (replay's plan isn't
    empty), what replay --dry-run would print, with the command that plays them, and whether
    replay would refuse now as the dry run says it: by whether runs can use the card log now
    (install.status), not by this run's cardlog-check, since an earlier pass of this version and
    build still stands after a check that couldn't tell."""
    try:
        eng = shared.engine.today(shared.engine.KIND_DECKLAB)
        plan = results._replay_plan(None, eng)
        log = shared.status()["card_log"]
    except shared.ForgeError as e:
        print(f"What needs replaying couldn't be worked out: {e}")
        return
    if not plan:
        print("No saved matchup needs replaying: every current matchup has as many games with today's engine.")
        return
    release = f" (Forge {eng['forge']})" if eng.get("forge") else ""
    print(f"\nThe engine changed: {len(plan)} saved matchup{' was' if len(plan) == 1 else 's were'} played with "
          f"another engine than today's{release}. replay --dry-run says:")
    results._print_replay_plan(plan, shared.pool._workers_setting())
    if log["ready"]:
        print("python -m decklab.lib.forge replay plays them again, on an idle PC.")
    else:
        print("python -m decklab.lib.forge replay plays them again, on an idle PC, once the card log can be used "
              f"(until then it refuses: {log['problem']})")


def _plan(tag):
    """--plan: the manual steps of README.md's "Deck Lab's own Forge" for a new release, as text."""
    return "\n".join([
        f"Moving Deck Lab's Forge onto {tag} (decklab/README.md, \"Deck Lab's own Forge\"). Nothing here is run "
        "for you:",
        f"  1. In C:\\VSProjects\\forge, rebase the decklab branch onto the tag {tag} (or merge it in) and fix any "
        "conflicts.",
        f"  2. Update BASE_TAG in the fork's decklab/install.py to {tag}.",
        "  3. Build it into a scratch folder: python decklab/install.py --out <scratch folder> (Maven is at "
        "C:\\Tools\\maven; set JAVA_HOME first in Git Bash).",
        "  4. Compare it with the installed build: python -m decklab.lib.forge engine-check --old C:/Tools/forge-decklab "
        "--new <scratch folder> --pair <deck> <deck> ... A new release is always a different engine key, so exit "
        "1 with \"Different engine key\" and no \"Don't install this build as it is\" line is what to expect (0 or 3 "
        "if no game changed); only exit 2 (it couldn't run) or a \"Don't install\" line stops the upgrade.",
        "  5. Merge it into decklab with git merge --ff-only on a clean working tree, run python decklab/install.py "
        "there (it installs C:\\Tools\\forge-decklab), and confirm the installed decklab-build.txt's build= is the "
        "scratch build's.",
        "  6. Here: python -m decklab.lib.forge upgrade-check (cardlog-check, serve-check and the overrides check, "
        "with what needs replaying). If an override no longer fits, overrides make makes it again from the new "
        "scripts: review its diff, then run upgrade-check again.",
        "  7. Put the new version, build and simjar.source_sha256() in simjar.CHECKED, CHECKED_BUILDS and "
        "CHECKED_SOURCE, so a fresh clone with that build installed has the card log on.",
        "  8. On an idle PC: python -m decklab.lib.forge replay.",
    ])


def _upgrade_check_args(sub):
    check = sub.add_parser("upgrade-check", help="after installing a new Forge build: cardlog-check, serve-check "
                                                 "and the overrides check, with one summary")
    check.add_argument("--plan", metavar="TAG",
                       help="print the manual steps before the check for this release tag (forge-2.0.16, say) "
                            "and run nothing")


def _cmd_upgrade_check(args):
    """upgrade-check: exit 0 only when every step passed (upgrade_check), 1 otherwise. --plan
    prints _plan's text and exits 0."""
    if args.plan is not None:
        if not args.plan.strip():
            raise shared._CliError("--plan needs a release tag, such as forge-2.0.16.")
        print(_plan(args.plan.strip()))
        return 0
    found = upgrade_check()
    version = shared.install.forge_version()      # None when Forge was never found; never raises
    print(f"\nUpgrade check{f' of Forge {version}' if version else ''}:")
    for name, state, why in found:
        print(f"  {name}: {state}" + (f": {why}" if why else ""))
    _print_replay()
    missed = sum(state != PASSED for _, state, _ in found)
    print("Every check passed." if not missed else
          f"{missed} of {len(found)} checks didn't pass: fix what's above and run upgrade-check again.")
    return 0 if not missed else 1
