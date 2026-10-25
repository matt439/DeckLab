"""List long repository source files, excluding pinned copies of upstream Forge.

Run from any directory: python scripts/audit_source_lengths.py [--check].
Includes tracked and untracked files, but respects .gitignore (caches and downloads).
The 1,200-line review threshold comes from Deck Lab's Milestone 7.
"""
import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = {".py", ".js", ".css", ".html", ".java", ".ps1"}
LIMIT = 1200
# These patched upstream classes are checked against Forge's original source and
# bytecode hashes. Their layout is part of that comparison, not our module design.
UPSTREAM = "decklab/lib/forge/java/forge/"


def inventory():
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    ).decode("utf-8").split("\0")
    owned, upstream = [], []
    for name in sorted(set(paths)):
        path = ROOT / name
        if path.suffix not in EXTENSIONS or not path.is_file():
            continue
        row = (len(path.read_text(encoding="utf-8-sig").splitlines()), name)
        (upstream if name.startswith(UPSTREAM) else owned).append(row)
    return sorted(owned, reverse=True), sorted(upstream, reverse=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if an owned source exceeds 1,200 lines")
    args = parser.parse_args(argv)
    owned, upstream = inventory()
    long = [(lines, name) for lines, name in owned if lines > LIMIT]
    print(f"{len(owned)} owned source files; {len(long)} exceed {LIMIT:,} lines.")
    print("Longest owned files:")
    for lines, name in owned[:20]:
        print(f"{lines:5}  {name}")
    if upstream:
        print("Excluded pinned upstream Forge copies:")
        for lines, name in upstream:
            print(f"{lines:5}  {name}")
    return int(args.check and bool(long))


if __name__ == "__main__":
    raise SystemExit(main())
