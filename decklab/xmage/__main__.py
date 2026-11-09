"""Explicit bridge setup: python -m decklab.xmage build --home RELEASE_FOLDER."""
import argparse
import json

from .build import build, describe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "describe"))
    parser.add_argument("--home", required=True)
    parser.add_argument("--output")
    parser.add_argument("--java")
    args = parser.parse_args()
    try:
        function = build if args.action == "build" else describe
        result = function(args.home, build_dir=args.output, java=args.java)
    except (ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result, indent=2))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
