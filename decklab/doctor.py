"""Read-only self-hosting preflight: python -m decklab.doctor [--json].

0: core preflight ready; 1: known core setup work; 2: core verification failed
or command usage is invalid. Optional file findings do not block the core app.
Actual server, device and simulation execution qualification remains separate.
"""
import argparse
import json
import sys

from decklab.lib import preflight


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's usual error includes submitted arguments; they may be private.
        self.print_usage(sys.stderr)
        self.exit(2, "Invalid preflight arguments. Use --help for supported options.\n")


def _provider():
    """Create fresh, inert adapters only after command-line parsing succeeds."""
    from decklab.lib.preflight_local import Local
    local = Local()
    optional, optional_failed = None, False

    def probe(ident):
        nonlocal optional, optional_failed
        if ident not in ("java", "forge"):
            return local.probe(ident)
        if optional_failed:
            return "probe_unverified"
        if optional is None:
            try:
                from decklab.lib.preflight_forge import ForgeFiles
                optional = ForgeFiles(settings=lambda: local.settings)
                if not callable(getattr(optional, "probe", None)):
                    optional_failed = True
                    return "probe_unverified"
            except Exception:           # noqa: BLE001 - optional adapter faults do not block core checks
                optional_failed = True
                return "probe_unverified"
        return optional.probe(ident)
    return probe


def _say_error(message):
    stream = sys.stderr
    if stream is not None:
        try:
            print(message, file=stream)
        except (OSError, UnicodeError, ValueError):
            pass


def main(argv=None, *, provider_factory=None):
    parser = _Parser(prog="python -m decklab.doctor", description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the same fixed findings as JSON")
    args = parser.parse_args(argv)  # --help must perform no adapter imports, creation or probes
    try:
        try:
            probe = (_provider if provider_factory is None else provider_factory)()
        except Exception:               # noqa: BLE001 - a broken adapter import is a fixed finding
            probe = None
        result = preflight.report(probe)
    except KeyboardInterrupt:
        _say_error("Preflight cancelled.")
        return 130
    except SystemExit as interruption:
        if interruption.code is None or type(interruption.code) is int:
            raise
        _say_error("Preflight stopped before completing.")
        return 2                       # Python would otherwise print a nonnumeric exit payload
    rendered = json.dumps(result, ensure_ascii=True, allow_nan=False, indent=2) if args.json else preflight.text(result)
    try:
        if sys.stdout is None:
            raise OSError("No report stream")
        print(rendered, file=sys.stdout)
    except (OSError, UnicodeError, ValueError):
        _say_error("The preflight report could not be written.")
        return 2
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
