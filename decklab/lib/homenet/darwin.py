"""Honest foreground-mode management on macOS; no native task/service commands."""


def command(args, port, say, config_error=None):
    if config_error:
        say("WARN Configuration: run python -m decklab.doctor to fix the local config before starting.")
    if args.command == "status":
        say(f"INFO macOS foreground mode (configured port {port}). Start with python decklab/server.py.")
        say("WARN Background control, automatic startup, network inspection and nightly scheduling are not "
            "installed or verified here. Use your own launchd/cron setup if wanted (SELF-HOSTING.md).")
        return 0
    say("macOS uses foreground mode: run python decklab/server.py to start and Ctrl+C in that terminal "
        "to stop. For an operator-managed LaunchAgent use launchctl bootstrap/bootout/kickstart; "
        "Deck Lab does not install or control that job. See SELF-HOSTING.md's macOS instructions.")
    return 1
