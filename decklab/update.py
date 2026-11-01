"""Update a server PC: python -m decklab.update [--dry-run] [--no-forge] [--no-restart] [--no-smoke].

For a PC that serves Deck Lab and only pulls updates (the code is developed and tested on
another PC). In order, stopping at the first failure:

  1. refuse a checkout with changed tracked files, or a Python the .venv (and, on Linux, the
     background service and nightly timer) wasn't made with; then git fetch and show what's coming
  2. git merge --ff-only with the branch's upstream (never a merge commit or a rebase)
  3. reinstall psycopg into the .venv when requirements.txt changed (or doesn't match); on Windows
     the running server is stopped first, since it keeps psycopg's DLLs locked
  4. with migrations pending: a backup (python -m decklab.db backup), then python -m decklab.db migrate
  5. when this Deck Lab expects another Forge build than forge_dir holds: download the release,
     check its SHA-256, unzip it beside the old one and point config.json's forge_dir at it
  6. restart the background server, if it's running (python -m decklab.lib.homenet restart)
  7. python -m decklab.smoke

Steps 3-7 run in a new process of the pulled code (`--after-pull`), so an update to this
updater or to anything it calls takes effect at once. --dry-run fetches and says what would be
done, changing nothing. On a failure after the pull it prints how to go back: git reset --hard to
the old commit and restart; migrations aren't undone, so a backup made in step 4 is the way back
for the data (python -m decklab.db restore).

Exit codes: 0 updated (or nothing to do) and the smoke test passed, 1 a step failed or was refused.
"""
import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "decklab" / "config.json"
REQUIREMENTS = "decklab/requirements.txt"
MIGRATIONS = "decklab/db/migrations/"
_SPAWN = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
# Windows keeps a running server's psycopg DLLs locked, so it's stopped while pip replaces them;
# Linux and macOS replace a loaded .so file without trouble, so the server keeps running there
# until step 6's restart loads the new one.
PIP_NEEDS_STOP = os.name == "nt"


class Failed(Exception):
    """A step failed; the message says what to do."""


def say(text=""):
    print(text, flush=True)


def git(*args, check=True, timeout=120):
    """git's stdout, stripped. Raises Failed when it exits non-zero (with check)."""
    try:
        done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, **_SPAWN)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Failed(f"git {args[0]} couldn't run: {e}") from None
    if check and done.returncode != 0:
        raise Failed(f"git {' '.join(args)} failed: {(done.stderr or done.stdout).strip()}")
    return done.stdout.strip()


def step(argv, what, timeout=None):
    """Run a Deck Lab command, its output passed straight through. Raises Failed on a non-zero exit."""
    say(f"\n== {what}: {' '.join(Path(a).name if i == 0 else a for i, a in enumerate(argv))}")
    try:
        code = subprocess.run(argv, cwd=ROOT, timeout=timeout, stdin=subprocess.DEVNULL).returncode
    except subprocess.TimeoutExpired:
        raise Failed(f"{what} didn't finish within {timeout} s") from None
    if code != 0:
        raise Failed(f"{what} failed (exit {code})")


def changed_files(old, new):
    return [line for line in git("diff", "--name-only", old, new).splitlines() if line]


def venv_python():
    """The .venv's interpreter (for pip), or None when there's no .venv."""
    for path in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if path.is_file():
            return path
    return None


# ---------------------------------------------------------------- Forge

def expected_release(text):
    """RELEASE in decklab/lib/forge/simjar.py's text (its V = "..." line), or None."""
    match = re.search(r'^V\s*=\s*"([^"]+)"', text, re.M)
    return match.group(1) if match else None


def set_forge_dir(text, folder):
    """config.json's text with "forge_dir" set to folder: the existing value replaced in place
    (keeping the file's layout), or the key added as the object's first. ValueError when the text
    isn't a JSON object, or the result wouldn't parse."""
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("config.json isn't a JSON object")
    value = json.dumps(str(folder))
    pattern = re.compile(r'("forge_dir"\s*:\s*)"(?:[^"\\]|\\.)*"')
    if "forge_dir" in data:
        if len(pattern.findall(text)) != 1:
            raise ValueError('config.json\'s "forge_dir" can\'t be found once in its text')
        out = pattern.sub(lambda m: m.group(1) + value, text, count=1)
    else:
        brace = text.index("{")
        out = text[:brace + 1] + f'\n  "forge_dir": {value},' + text[brace + 1:]
    if json.loads(out).get("forge_dir") != str(folder):
        raise ValueError("config.json's forge_dir couldn't be set")
    return out


def safe_extract(archive, target):
    """Unzip archive into target, refusing any member that would land outside it. Returns the
    single top-level folder the release holds. Off Windows each file keeps the permission bits
    the zip recorded for it (_keep_modes), so the release's launchers stay runnable."""
    target = Path(target).resolve()
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        for name in names:
            path = (target / name).resolve()
            if path != target and target not in path.parents:
                raise Failed(f"The Forge download holds a file outside its folder ({name}): not unzipped")
        tops = {name.replace("\\", "/").split("/", 1)[0] for name in names if name.strip("/")}
        if len(tops) != 1:
            raise Failed("The Forge download doesn't hold exactly one folder: not unzipped")
        z.extractall(target)
        if os.name != "nt":
            _keep_modes(z.infolist(), target)
    return target / tops.pop()


def _keep_modes(members, target):
    """chmod each regular file member extracted under target to the rwx bits its zip entry
    records (external_attr's high 16 bits, as the fork's package.py writes them), which zipfile's
    extractall drops. Never
    setuid, setgid or sticky; directories, links (unzipped as plain files) and entries with no
    Unix mode are left as extracted."""
    for info in members:
        mode = info.external_attr >> 16
        if info.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG) or not mode & 0o777:
            continue
        os.chmod(target / info.filename, mode & 0o777)


def file_sha256(path):
    """The SHA-256 of a file, read a MiB at a time (the Forge release is hundreds of MB)."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url, path):
    from decklab.lib import config
    request = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response, open(path, "wb") as out:
        shutil.copyfileobj(response, out, 1024 * 1024)


def update_forge(dry_run=False, release=None):
    """Step 5: install the Forge release this Deck Lab expects (release: another one, for a dry run
    in the code before the pull) when forge_dir holds another build. Any failure is a Failed, and
    leaves forge_dir as it was."""
    try:
        _update_forge(dry_run, release)
    except Failed:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, http.client.HTTPException) as e:
        raise Failed(f"Forge couldn't be updated ({type(e).__name__}: {e}); forge_dir is unchanged") from None


def _update_forge(dry_run, release):
    from decklab.lib import config
    from decklab.lib.forge import install, simjar
    settings = config.load()
    current = Path(settings.get("forge_dir") or "")
    jar, _ = install._find_jar(current) if current.is_dir() else (None, None)
    if jar is None:
        say(f"Forge isn't installed at forge_dir ({current}), so it's left alone (SELF-HOSTING.md step 8).")
        return
    release = release or simjar.RELEASE
    build = simjar.forge_build(current / jar)
    if build == release:
        say(f"Forge is build {build}, the one this Deck Lab expects.")
        return
    check = {"build": build}
    folder = current.parent / f"forge-{release}"
    if dry_run:
        say(f"Would install Forge {release} into {folder} (installed: {check['build']}) and set forge_dir.")
        return
    if folder.exists():
        found, _ = install._find_jar(folder)
        if found is None or simjar.forge_build(folder / found) != release:
            raise Failed(f"{folder} exists but isn't Forge {release}: move it away and update again")
        say(f"Forge {release} is already unzipped at {folder}.")
    else:
        base = f"{simjar.RELEASES}/download/{release}/forge-{release}.zip"
        with tempfile.TemporaryDirectory(prefix="decklab-forge-") as tmp:
            archive = Path(tmp) / f"forge-{release}.zip"
            say(f"Downloading {base}...")
            try:
                download(base, archive)
                download(base + ".sha256", Path(tmp) / "sum")
            except (OSError, http.client.HTTPException) as e:
                raise Failed(f"Forge {release} couldn't be downloaded ({e}): is the release published? "
                             f"{simjar.release_url(release)}") from None
            want = (Path(tmp) / "sum").read_text(encoding="utf-8", errors="replace").split()[:1]
            digest = file_sha256(archive)
            if not want or want[0].lower() != digest:
                raise Failed(f"The Forge download's SHA-256 ({digest}) doesn't match its .sha256 file: not installed")
            say(f"SHA-256 checked: {digest}")
            with tempfile.TemporaryDirectory(prefix="decklab-forge-unzip-", dir=current.parent) as unzip:
                top = safe_extract(archive, unzip)
                found, _ = install._find_jar(top)
                if found is None or simjar.forge_build(top / found) != release:
                    raise Failed(f"The download doesn't hold Forge {release}: not installed")
                os.replace(top, folder)
        say(f"Unzipped Forge {release} into {folder}.")
    text = CONFIG.read_text(encoding="utf-8")
    backup = CONFIG.with_name("config.json.before-forge-update")
    backup.write_text(text, encoding="utf-8")
    CONFIG.write_text(set_forge_dir(text, folder), encoding="utf-8")
    say(f"config.json's forge_dir is now {folder} (the old file is {backup.name}; the old Forge, {current}, "
        "is left in place: delete it once the smoke test passes).")


# ---------------------------------------------------------------- the Python it runs on

def _venv_config(root=None):
    """.venv/pyvenv.cfg's "key = value" lines (lowercase keys), or None when there isn't one."""
    path = Path(root or ROOT) / ".venv" / "pyvenv.cfg"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    out = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip().lower()] = value.strip()
    return out


def venv_base_python(values, windows=None):
    """The Python the .venv was made from, from pyvenv.cfg's values (its home folder and
    version), or None when they don't say."""
    windows = os.name == "nt" if windows is None else windows
    home = (values or {}).get("home")
    if not home:
        return None
    if windows:
        return str(Path(home) / "python.exe")
    version = ".".join(((values or {}).get("version") or (values or {}).get("version_info") or "").split(".")[:2])
    return f"{home.rstrip('/')}/python{version or '3'}"


def _same_python(a, b):
    if os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b)):
        return True
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _installed_units():
    """[(what, its unit's Python, the command that installs it again)] for the Linux systemd
    units that run Deck Lab: the background service and the nightly timer's service."""
    from decklab.lib import systemd
    from decklab.lib.homenet import service
    found = []
    for what, name, again in (("The background service", service.service_name(), "-m decklab.lib.homenet install"),
                              ("The nightly timer", "decklab-nightly.service", "-m decklab.db schedule install")):
        try:
            text = (systemd.unit_dir() / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        parts = service.unit_parts(text)
        if parts and parts.get("program"):
            found.append((what, parts["program"], again))
    return found


def interpreter_problem(executable=None, activate=None, venv=None, units=None, platform=None):
    """Why this update shouldn't run on this Python, or None. Checked before anything is fetched,
    since the pulled code runs on the same Python and would only fail later (the migrations can't
    be checked without the .venv's psycopg), leaving the server unrestarted.

    - .venv was made from another Python (pyvenv.cfg's home and version; lib/venv.py): the
      update must run on that one. No .venv at all is left to the smoke test, as before.
    - on Linux, the background service's or nightly timer's unit runs another Python: after the
      update it would run without the .venv's packages, so it's installed again first.

    executable, activate (venv.activate), venv (pyvenv.cfg's values), units (_installed_units)
    and platform are for tests."""
    executable = executable or sys.executable
    platform = sys.platform if platform is None else platform
    values = _venv_config() if venv is None else venv
    if values:
        if activate is None:
            from decklab.lib import venv as venv_module
            activate = venv_module.activate
        reason = activate()
        if reason:
            base = venv_base_python(values, windows=platform == "win32")
            run_with = (f"run the update with that Python instead: {base} -m decklab.update" if base else
                        "run the update with the Python the .venv was made from")
            return (f"This update runs on {executable}, but {reason}, so the pulled code couldn't use the "
                    f"database. Nothing was fetched: {run_with} (or make the .venv again with this Python: "
                    "SELF-HOSTING.md step 3).")
    if platform.startswith("linux"):
        for what, program, again in (_installed_units() if units is None else units):
            if not _same_python(program, executable):
                return (f"{what} runs {program}, not this Python ({executable}), so after the update it would "
                        "start without the .venv's packages. Nothing was fetched: install it again with this "
                        f"Python first ({executable} {again}, with the options it was installed with), then "
                        "update again.")
    return None


# ---------------------------------------------------------------- the steps

def before_pull(args):
    """Steps 1-2, in the code as it was. Returns the exit code of the rest (or 0 for a dry run)."""
    problem = interpreter_problem()
    if problem:
        raise Failed(problem)
    dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise Failed("Tracked files are changed here, so nothing was pulled (a server PC runs committed code "
                     "only):\n" + "\n".join("  " + line for line in dirty.splitlines()[:20]) +
                     "\nLook with git diff, then git stash or git checkout -- <file>.")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        raise Failed("This checkout isn't on a branch (a detached HEAD), so there's nothing to pull: "
                     "git checkout main (or the branch this server follows), then update again.")
    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", check=False)
    if not upstream:
        raise Failed(f"The branch {branch} has no upstream to pull from: git branch -u origin/main")
    say(f"== Fetching {upstream}")
    git("fetch", "--prune", timeout=300)
    old, new = git("rev-parse", "HEAD"), git("rev-parse", "@{upstream}")
    incoming = git("log", "--oneline", "--no-decorate", f"{old}..{new}")
    ahead = git("rev-list", "--count", f"{new}..{old}")
    if ahead != "0":
        raise Failed(f"{branch} has {ahead} commits that {upstream} hasn't: a server PC shouldn't, so nothing "
                     "was pulled (git log @{upstream}..)")
    new_release = None
    if incoming:
        lines = incoming.splitlines()
        say(f"{len(lines)} new commits:\n" + "\n".join("  " + line for line in lines[:30]) +
            ("\n  ..." if len(lines) > 30 else ""))
        files = changed_files(old, new)
        if REQUIREMENTS in files:
            say("  requirements.txt changed: psycopg will be reinstalled")
        new_migrations = [f for f in files if f.startswith(MIGRATIONS) and f.endswith(".sql")]
        if new_migrations:
            say(f"  {len(new_migrations)} migration files changed: a backup, then migrate")
        old_release = expected_release(git("show", f"{old}:decklab/lib/forge/simjar.py", check=False))
        new_release = expected_release(git("show", f"{new}:decklab/lib/forge/simjar.py", check=False))
        if old_release != new_release:
            say(f"  Forge release: {old_release} -> {new_release}")
    else:
        say("Already up to date with " + upstream + ".")
    if args.dry_run:
        if not args.no_forge:
            update_forge(dry_run=True, release=new_release)
        say("\nDry run: nothing was changed.")
        return 0
    if incoming:
        say(f"\n== Updating {old[:9]} -> {new[:9]}")
        git("merge", "--ff-only", new)
    rest = [sys.executable, "-m", "decklab.update", "--after-pull", old]
    rest += [flag for flag, on in (("--no-forge", args.no_forge), ("--no-restart", args.no_restart),
                                   ("--no-smoke", args.no_smoke)) if on]
    return subprocess.run(rest, cwd=ROOT, stdin=subprocess.DEVNULL).returncode


def after_pull(args):
    """Steps 3-7, in the pulled code."""
    old = args.after_pull
    done = set()        # the steps that changed something, for the way back
    try:
        warnings = _after_pull(args, old, done)
    except Exception as e:      # noqa: BLE001 - every failure gets the way back, a traceback none
        say(f"\nUpdate stopped: {e if isinstance(e, Failed) else f'{type(e).__name__}: {e}'}")
        say(way_back(old, done))
        return 1
    if warnings:
        say("\nUpdate done, but:\n" + "\n".join("  " + w for w in warnings))
        return 1
    say("\nUpdate done.")
    return 0


def way_back(old, done):
    """What to do after a failure, given the steps that already changed something."""
    lines = []
    if "backup-failed" in done:
        lines.append("Nothing was migrated. Fix what stopped the backup (is backup_dir reachable?), then run "
                     "python -m decklab.update again.")
    if "server-stopped" in done:
        lines.append("Deck Lab was stopped to replace psycopg: python -m decklab.lib.homenet start.")
    if old and "pulled" in done:
        back = [f"To go back to the code from before: python -m decklab.lib.homenet stop, git reset --hard {old[:12]}"]
        if "migrated" in done:
            back.append("python -m decklab.db restore <the dump the backup step named> --replace --force "
                        "(after the reset, so the old code's migrations are the ones it checks)")
        if "forge" in done:
            back.append("copy decklab/config.json.before-forge-update back over decklab/config.json")
        back.append("python -m decklab.lib.homenet start")
        lines.append(", then ".join(back) + ".")
    return "\n".join(lines)


def _after_pull(args, old, done):
    """Steps 3-7. Returns warnings that don't stop the update (Forge not updated); raises Failed."""
    files = changed_files(old, "HEAD") if old else []
    if old and old != git("rev-parse", "HEAD", check=False):
        done.add("pulled")
    python = sys.executable
    warnings = []
    running = server_answers()
    if REQUIREMENTS in files or psycopg_mismatch():
        pip = venv_python()
        if pip is None:
            raise Failed("There's no .venv to install psycopg into: SELF-HOSTING.md step 3")
        stop = running and PIP_NEEDS_STOP
        if stop:
            step([python, "-m", "decklab.lib.homenet", "stop"], "Stop Deck Lab to replace psycopg", timeout=120)
            done.add("server-stopped")
        try:
            step([str(pip), "-m", "pip", "install", "-r", str(ROOT / REQUIREMENTS)], "Reinstall psycopg", timeout=900)
        except Failed:
            if stop:
                step([python, "-m", "decklab.lib.homenet", "start"], "Start Deck Lab again", timeout=120)
                done.discard("server-stopped")
            raise
    from decklab.lib import venv
    venv.activate()
    from decklab.db import migrate
    try:
        pending = migrate.pending(role="app")
    except Exception as e:      # noqa: BLE001 - the database being down is reported, not raised
        raise Failed(f"The migrations can't be checked: {e}") from None
    if pending:
        say(f"\n{len(pending)} migrations are pending: " + ", ".join(f["name"] for f in pending))
        try:
            step([python, "-m", "decklab.db", "backup"], "Back up before migrating", timeout=3600)
        except Failed:
            done.add("backup-failed")
            raise
        done.add("migrated")
        step([python, "-m", "decklab.db", "migrate"], "Migrate", timeout=1800)
    else:
        say("\nNo migrations are pending.")
    if args.no_forge:
        say("Forge: skipped (--no-forge).")
    else:
        say("\n== Forge")
        before = CONFIG.read_bytes() if CONFIG.exists() else None
        try:
            update_forge()
        except Failed as e:     # the server must still restart on the pulled code
            say(str(e))
            warnings.append(f"Forge wasn't updated: {e}")
        if CONFIG.exists() and CONFIG.read_bytes() != before:
            done.add("forge")
    if args.no_restart:
        say("Restart: skipped (--no-restart).")
    elif running or server_answers():
        step([python, "-m", "decklab.lib.homenet", "restart"], "Restart the background server", timeout=300)
        done.discard("server-stopped")
    else:
        say("\nThe background server isn't running, so it wasn't started (python -m decklab.lib.homenet start).")
    if args.no_smoke:
        say("Smoke test: skipped (--no-smoke).")
    else:
        step([python, "-m", "decklab.smoke"], "Smoke test", timeout=1200)
    return warnings


def psycopg_mismatch():
    """Whether the .venv's psycopg isn't the version requirements.txt pins. Read from its metadata,
    never imported, so this process doesn't load (and lock) the DLLs pip may have to replace."""
    import importlib.metadata
    from decklab import smoke
    from decklab.lib import venv
    if venv.activate():
        return False            # no usable .venv: the smoke test says so
    want = smoke.pinned((ROOT / REQUIREMENTS).read_text(encoding="utf-8"), "psycopg")
    try:
        have = importlib.metadata.version("psycopg")
    except importlib.metadata.PackageNotFoundError:
        return True
    return bool(want) and have != want


def server_answers():
    """Whether Deck Lab answers on the configured port (so a restart picks up the new code)."""
    from decklab import smoke
    from decklab.lib import config
    try:
        code, status = smoke.get_json(int(config.load().get("port", 8642)), "/api/status", timeout=5)
    except (OSError, ValueError):
        return False
    return code == 200 and isinstance(status, dict)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m decklab.update", description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="fetch and say what would be done; change nothing")
    parser.add_argument("--no-forge", action="store_true", help="leave Forge as it is")
    parser.add_argument("--no-restart", action="store_true", help="don't restart the background server")
    parser.add_argument("--no-smoke", action="store_true", help="don't run the smoke test at the end")
    parser.add_argument("--after-pull", metavar="COMMIT", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.after_pull is not None:
        return after_pull(args)
    try:
        return before_pull(args)
    except Failed as e:
        say(f"\nUpdate stopped: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
