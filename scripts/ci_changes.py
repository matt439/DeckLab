"""Skip CI's full suite only for known documentation paths, or for a push the pull request already tested; lint always runs.

Pushes compare the whole pushed range; pull requests compare from the merge base.
A push that merges a pull request skips the suite when the pull request's own run passed on the
same files: main hadn't moved past the branch (so that run tested exactly the merged files) and the
merge changed nothing else. Any doubt runs it.
Missing history, empty/unknown comparisons, scheduled and manual runs use the full suite.
"""
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath


TESTS_WORKFLOW = ".github/workflows/tests.yml"
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


def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.PIPE).decode().strip()


def github_api(path):
    """GET one GitHub REST path for this repository, with the workflow's token."""
    url = f"{os.environ.get('GITHUB_API_URL', 'https://api.github.com')}/repos/{os.environ['GITHUB_REPOSITORY']}{path}"
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "User-Agent": "decklab-ci-changes",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def tested_pull_request(event, api):
    """The number of the pull request whose passing run already covered this push, else None."""
    before, after = event["before"], event["after"]
    merged = [pull for pull in api(f"/commits/{after}/pulls")
              if pull.get("merged_at") and pull.get("merge_commit_sha") == after]
    if len(merged) != 1:
        return None
    number, head = merged[0]["number"], merged[0]["head"]["sha"]
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        return None
    # With main's old tip inside the branch, the pull request's run tested the branch's own files,
    # and the merge result must be exactly those files too.
    if subprocess.run(["git", "merge-base", "--is-ancestor", before, head],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        return None
    if git("rev-parse", f"{after}^{{tree}}") != git("rev-parse", f"{head}^{{tree}}"):
        return None
    query = urllib.parse.urlencode({"head_sha": head, "event": "pull_request", "status": "success", "per_page": 100})
    runs = api(f"/actions/runs?{query}").get("workflow_runs", [])
    if any(run.get("path") == TESTS_WORKFLOW and run.get("head_sha") == head
           and run.get("conclusion") == "success" for run in runs):
        return number
    return None


def should_run_tests(event_name, event, api=github_api):
    if event_name not in {"push", "pull_request"}:
        return True, "This event always runs the full suite."
    try:
        paths = changed_paths(event_name, event)
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        return True, "Changed files could not be established; running the full suite."
    if paths and all(is_documentation(name) for name in paths):
        return False, f"Only documentation changed ({len(paths)} paths); lint still runs."
    if event_name == "push" and paths:
        try:
            number = tested_pull_request(event, api)
        except Exception:  # the API, the token or Git: never skip on doubt
            number = None
        if number is not None:
            return False, f"Pull request #{number}'s run already passed on these exact files; lint still runs."
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
