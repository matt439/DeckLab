"""Draft a Deck Lab release's notes from decklab/HISTORY.md (E11-S84's changelog).

    python scripts/release_notes.py VERSION [--ref REF] [--since TAG] [--repo OWNER/REPO] [--out FILE]

The notes are the download instructions the release workflow always gave, then every HISTORY.md
entry (a "## " section) added since the previous release: the entries whose heading is in
HISTORY.md at REF (HEAD by default) but not in HISTORY.md at the previous release's tag. The
previous release is --since, else the newest version tag REF holds that is older than VERSION
(for a stable VERSION, only stable tags count, so v1.3.0's notes cover everything since v1.2.0,
its release candidates included). With no earlier release the notes say it's the first.

Entries keep HISTORY.md's order (newest first) and words. Their headings move down a level, and
with --repo their links relative to decklab/ point at the files on GitHub at REF's commit, so they
still work on the release page. GitHub limits a release's text, so past LIMIT characters the
entries' bodies are left out (their headings stay) and, past it again, the last headings too,
saying so; HISTORY.md always has the whole text.

.github/workflows/release.yml runs this for the draft release's text; Matt reads the draft before
publishing it. Exit codes: 0 written, 1 refused.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from decklab.lib import release_check  # noqa: E402

HISTORY = "decklab/HISTORY.md"
LIMIT = 100_000                 # GitHub refuses a release body over 125,000 characters
_LINK = re.compile(r"\]\((?!https?:|mailto:|#|/)([^)\s]+)\)")


def _git(*args, check=True):
    done = subprocess.run(["git", *args], cwd=REPO, capture_output=True)
    if check and done.returncode:
        raise ValueError(f"git {' '.join(args)} failed: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout.decode("utf-8", "replace") if done.returncode == 0 else None


def entries(text):
    """[(heading, body)] of HISTORY.md's "## " sections, in the file's order (fenced code skipped)."""
    out, heading, body, fenced = [], None, [], False
    for line in (text or "").splitlines():
        if line.startswith("```"):
            fenced = not fenced
        if not fenced and line.startswith("## "):
            if heading is not None:
                out.append((heading, "\n".join(body).strip()))
            heading, body = line[3:].strip(), []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        out.append((heading, "\n".join(body).strip()))
    return out


def added(old_text, new_text):
    """The entries of new_text whose heading old_text hasn't, in new_text's order."""
    before = {heading for heading, _ in entries(old_text)}
    return [(heading, body) for heading, body in entries(new_text) if heading not in before]


def previous_tag(version, tags):
    """The newest version tag among tags older than version (stable ones only for a stable version), or None."""
    key = release_check.version_key(version)
    stable = key is not None and key[3] == (1,)
    older = [tag for tag in tags if (found := release_check.version_key(tag)) is not None and found < key
             and (not stable or found[3] == (1,))]
    return max(older, key=release_check.version_key) if older else None


def _demote(body):
    fenced, lines = False, []
    for line in body.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        lines.append("#" + line if not fenced and re.match(r"#{1,5} ", line) else line)
    return "\n".join(lines)


def _links(body, base):
    """Relative links (written from decklab/, where HISTORY.md is) as absolute links under base."""
    def absolute(match):
        parts = ["decklab"]
        for part in match.group(1).split("/"):
            if part == "..":
                parts = parts[:-1]
            elif part not in ("", "."):
                parts.append(part)
        return f"]({base}/{'/'.join(parts)})"
    return _LINK.sub(absolute, body)


def header(version, repo):
    verify = f" --repo {repo}" if repo else ""
    return (f"Deck Lab {version}. Download decklab-{version}.zip and check it against decklab-{version}.zip.sha256. "
            f"decklab-{version}.json lists its commit and database migrations. Optionally, gh attestation verify "
            f"decklab-{version}.zip{verify} confirms this repository's release workflow built it. See SELF-HOSTING.md.")


def notes(version, new, since, repo=None, commit=None, limit=LIMIT):
    """The release's text: header(), then the entries new added since the tag since (None: the first release)."""
    top = header(version, repo)
    if since is None:
        return f"{top}\n\nThe first release: decklab/HISTORY.md records everything built so far.\n"
    if not new:
        return f"{top}\n\nNo new entries in decklab/HISTORY.md since {since}.\n"
    base = f"https://github.com/{repo}/blob/{commit}" if repo and commit else None
    title = f"\n\n## What's new since {since}\n\nFrom decklab/HISTORY.md, newest first.\n"
    full = [f"\n### {heading}\n\n{_links(_demote(body), base) if base else _demote(body)}\n" for heading, body in new]
    text = top + title + "".join(full)
    if len(text) <= limit:
        return text
    short = top + title + "\nThe entries are too long for a release page, so only their headings are here; " \
                          "decklab/HISTORY.md has the whole text.\n\n"
    shown = []
    for heading, _ in new:
        line = f"- {heading}\n"
        if len(short) + sum(map(len, shown)) + len(line) > limit - 200:
            shown.append(f"- and {len(new) - len(shown)} more entries in decklab/HISTORY.md\n")
            break
        shown.append(line)
    return short + "".join(shown)


def draft(version, ref="HEAD", since=None, repo=None):
    version = version[1:] if version.startswith("v") else version
    if release_check.version_key(version) is None:
        raise ValueError(f"{version!r} isn't a release version like 1.2.0")
    commit = _git("rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    if since is None:
        since = previous_tag(version, _git("tag", "--list", "v*", "--merged", commit).split())
    elif release_check.version_key(since) is None:
        raise ValueError(f"--since {since!r} isn't a version tag")
    else:
        _git("rev-parse", "--verify", f"refs/tags/{since}^{{commit}}")      # a tag that isn't here is refused
    new_text = _git("show", f"{commit}:{HISTORY}")
    old_text = _git("show", f"{since}:{HISTORY}", check=False) if since else None
    return notes(version, added(old_text or "", new_text) if since else [], since, repo, commit)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Draft a Deck Lab release's notes from decklab/HISTORY.md.")
    parser.add_argument("version", help="the release version, such as 1.2.0 (a leading v is dropped)")
    parser.add_argument("--ref", default="HEAD", help="the commit or tag released (default HEAD)")
    parser.add_argument("--since", help="the previous release's tag (default: the newest older one REF holds)")
    parser.add_argument("--repo", help="OWNER/REPO, for absolute links and the attestation command")
    parser.add_argument("--out", help="write the notes here (default: print them)")
    args = parser.parse_args(argv)
    try:
        text = draft(args.version, args.ref, args.since, args.repo)
    except ValueError as error:
        print(f"Refused: {error}", file=sys.stderr)
        return 1
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
        print(args.out)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
