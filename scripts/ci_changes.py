"""Skip CI's full suite only for known documentation paths; lint always runs.

Pushes compare the whole pushed range; pull requests compare from the merge base.
Missing history, empty/unknown comparisons, scheduled and manual runs use the full suite.
"""
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath


DOC_DIRECTORIES = ("decklab/design/", "decklab/forge-trial/", "decklab/safari/")
DOC_FILES = {
    "decklab/fonts-licences/README.md",
    "decklab/lib/forge/overrides/README.md",
    "decklab/design/packing-chooser.svg",
}


def is_documentation(name):
    """Use a narrow allowlist: Markdown deck fixtures and Forge text are inputs."""
    path = PurePosixPath(name)
    if "tests" in path.parts or "fixtures" in path.parts:
        return False
    if name in DOC_FILES:
        return True
    return path.suffix in {".md", ".rst"} and (
        path.parent in {PurePosixPath("."), PurePosixPath("decklab")}
        or name.startswith(DOC_DIRECTORIES)
    )


def changed_paths(event_name, event):
    if event_name == "pull_request":
        base = event["pull_request"]["base"]["sha"]
        head = event["pull_request"]["head"]["sha"]
        separator = "..."
    else:
        base, head = event["before"], event["after"]
        separator = ".."
    for revision in (base, head):
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision) or revision == "0" * 40:
            raise ValueError("Missing comparison revision")
    # No rename folding: a fixture moved to a documentation path must still run tests.
    output = subprocess.check_output(
        ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}{separator}{head}", "--"],
        stderr=subprocess.PIPE,
    )
    return [os.fsdecode(name) for name in output.split(b"\0") if name]


def should_run_tests(event_name, event):
    if event_name not in {"push", "pull_request"}:
        return True, "This event always runs the full suite."
    try:
        paths = changed_paths(event_name, event)
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        return True, "Changed files could not be established; running the full suite."
    if paths and all(is_documentation(name) for name in paths):
        return False, f"Only documentation changed ({len(paths)} paths); lint still runs."
    return True, "Code, test inputs or other paths changed (or the diff is empty); running the full suite."


def main():
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    try:
        event = {}
        if event_name in {"push", "pull_request"}:
            event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    except (KeyError, OSError, ValueError):
        run_tests, reason = True, "The event could not be read; running the full suite."
    else:
        run_tests, reason = should_run_tests(event_name, event)
    print(reason)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"run_tests={str(run_tests).lower()}\n")


if __name__ == "__main__":
    main()
