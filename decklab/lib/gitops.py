"""Read-only git queries about a repo file: its path in the repo and its status.

Deck Lab no longer commits anything (since phase 4 every save goes to the
database). What's left is what decklab/lib/forge/lists.py needs for the
provenance of a .dck file given to the Forge command line ({"file",
"commit", "dirty"}).

Usage:

    from decklab.lib import gitops
    gitops.relative(path)           # "decklab/forge-trial/m7/x.dck"
    gitops.status([path])           # {"decklab/forge-trial/m7/x.dck": " M"}, or {} when clean
    gitops.run(["log", "-1", "--format=%H", "--", rel], check=False)

How git is run: from the repo root (REPO, config.REPO unless a test points
it elsewhere), with paths relative to it, no console prompt
(GIT_TERMINAL_PROMPT=0, stdin closed, and no console window under pythonw),
literal pathspecs, GIT_OPTIONAL_LOCKS=0 (so a status check never takes
.git/index.lock away from someone's own git command), and
GIT_CEILING_DIRECTORIES set so a REPO that isn't a repository is an error
rather than a question to some folder above it. git's output goes to
temporary files rather than pipes.

Each command gets TIMEOUT seconds. When it runs over, git is stopped with
the processes it started (on Windows taskkill /T, elsewhere its process
group), so a stuck git can't hold a page or a Forge request up.

GitError.kind says what went wrong, and str(error) says it in plain words
(repo paths relative to the repo, no final full stop): "missing" (git isn't
installed or on the PATH), "not_repo", "locked" (.git/index.lock exists),
"timeout", "outside" (a path not in the repo) or "failed" (anything else,
with git's own words).
"""
import os
import re
import signal
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

from decklab.lib import config

REPO = config.REPO
TIMEOUT = 30                # seconds for any one git command
KILL_WAIT = 10              # seconds to wait for a stopped git (and taskkill) to finish
_OUTPUT_LIMIT = 400         # characters of git's own output quoted in an error
# git's line-ending warnings and hints: noise in front of the real reason.
_NOISE_RE = re.compile(r"^(?:warning: (?:in the working copy of |(?:CR)?LF will be replaced by )"
                       r"|The file will have its original line endings|hint: )")
_SPAWN = ({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32"
          else {"start_new_session": True})


class GitError(Exception):
    """git couldn't do it. str(error) is a plain sentence; kind is a short code."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def _root(repo):
    return Path(repo if repo is not None else REPO).resolve()


def _env():
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                        "GIT_NAMESPACE", "GIT_PREFIX", "GIT_TRACE2_EVENT", "GIT_TRACE2_PARENT_SID")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_LITERAL_PATHSPECS"] = "1"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _relative_paths(text, root):
    """text with the repo folder taken out of any path in it, in the forms
    git writes it (C:\\..., C:/..., /c/...)."""
    posix = root.as_posix()
    forms = {str(root), posix}
    if re.match(r"^[A-Za-z]:/", posix):
        forms.add(f"/{posix[0].lower()}{posix[2:]}")
    for form in sorted(forms, key=len, reverse=True):
        text = re.sub(re.escape(form) + r"[\\/]+", "", text, flags=re.IGNORECASE)
        text = re.sub(re.escape(form) + r"(?![\w.-])", "the repo folder", text, flags=re.IGNORECASE)
    return text


def _quote(text, root=None):
    """git's output for an error message: the last lines, trimmed, without
    line-ending warnings or hints, repo paths relative, no final full stop."""
    lines = (line.strip() for line in (text or "").strip().splitlines())
    text = " ".join(line for line in lines if line and not _NOISE_RE.match(line))
    if root is not None:
        text = _relative_paths(text, root)
    text = text.rstrip(". ")
    return text if len(text) <= _OUTPUT_LIMIT else "..." + text[-_OUTPUT_LIMIT:]


def _stop(proc):
    """Stop a git that ran over and the processes it started: on Windows
    the real git.exe behind Git for Windows' cmd\\git.exe (taskkill /T),
    elsewhere its process group."""
    if sys.platform == "win32":
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        try:
            subprocess.run([str(taskkill), "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                           stdin=subprocess.DEVNULL, timeout=KILL_WAIT, **_SPAWN)
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        proc.kill()
        proc.wait(timeout=KILL_WAIT)
    except (OSError, subprocess.SubprocessError):
        pass


def run(args, repo=None, check=True):
    """Run a read-only git command with args in the repo root. Returns the
    CompletedProcess (stdout and stderr as text). Raises GitError "missing"
    or "timeout", and, when check is true and git fails, the GitError its
    output describes."""
    root = _root(repo)
    environ = _env()
    environ["GIT_CEILING_DIRECTORIES"] = str(root.parent)
    with ExitStack() as stack:
        out = stack.enter_context(tempfile.TemporaryFile())
        err = stack.enter_context(tempfile.TemporaryFile())
        try:
            proc = subprocess.Popen(["git", *args], cwd=root, env=environ, stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=err, **_SPAWN)
        except NotADirectoryError:
            raise GitError("not_repo", "the repo folder can't be found") from None
        except FileNotFoundError:
            if not root.is_dir():
                raise GitError("not_repo", "the repo folder can't be found") from None
            raise GitError("missing", "git isn't installed on the PC (or isn't on its PATH)") from None
        try:
            code = proc.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            _stop(proc)
            raise GitError("timeout", f"git didn't finish within {TIMEOUT} seconds, so Deck Lab stopped it") \
                from None
        out.seek(0)
        err.seek(0)
        done = subprocess.CompletedProcess(proc.args, code, out.read().decode("utf-8", "replace"),
                                           err.read().decode("utf-8", "replace"))
    if check and done.returncode != 0:
        raise _describe(done, root)
    return done


def _describe(done, root):
    """The GitError for a failed git command, from what it printed."""
    output = (done.stderr or "") + "\n" + (done.stdout or "")
    lower = output.lower()
    if "not a git repository" in lower:
        return GitError("not_repo", "the repo folder isn't a git repository")
    if "index.lock" in lower:
        return GitError("locked", "another git command is using the repo (or one crashed and left "
                                  ".git/index.lock behind; if no git command is running, delete that file)")
    quoted = _quote(output, root)
    return GitError("failed", f"git {done.args[1]} failed" + (f": {quoted}" if quoted else ""))


def relative(path, repo=None):
    """path relative to the repo root, with forward slashes. Raises GitError
    "outside" for a path that isn't in the repo."""
    root = _root(repo)
    path = Path(path)
    path = (path if path.is_absolute() else root / path).resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        raise GitError("outside", f"{path.name} isn't inside the repo") from None


def status(paths, repo=None):
    """{relative path: two-letter status} for the given paths that differ
    from HEAD (git status --porcelain): "??" untracked, " M" modified, "A "
    added, and so on. Clean paths are left out. A file whose only change is
    its line endings may be listed as " M"."""
    rels = [relative(p, repo) for p in paths]
    done = run(["status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *rels], repo)
    out = {}
    entries = done.stdout.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        code, name = entry[:2], entry[3:]
        if code[0] in "RC":
            i += 1                  # a rename's second entry is the old name
        out[name] = code
    return out
