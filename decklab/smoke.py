"""Post-install smoke test: python -m decklab.smoke [--json] [--offline] [--no-forge] [--no-server].

Run it on a PC that serves Deck Lab after setting it up (SELF-HOSTING.md) and after
each update (git pull, migrate, restart). Where `python -m decklab.doctor` only
reads files, this exercises the install: the database's three roles, the backup
programs, card lookups, the network sites Deck Lab uses, a throwaway server on a
spare 127.0.0.1 port answering the page and its read-only API, the background
server and nightly task, the tunnel, whether this PC lets Deck Lab hold it awake (a
trial let go at once), config.json's "timezone" against this PC's clock, photo
scanning's OCR engine (one drawn test picture) and one real Forge engine check.

It never writes to the database or the inventory and never touches the server on
the configured port beyond reading its status. It writes only temporary files and
Forge's own caches under decklab/data/forge (the card log jar). Unlike the fixture
test suite, it reads the real config.json and connects to the real PostgreSQL.

Exit codes: 0 no failures (warnings allowed), 1 at least one failure, 2 bad usage.
"""
import argparse
import http.client
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PASS, WARN, FAIL, SKIP = "pass", "warn", "fail", "skip"
WORDS = {PASS: "PASS", WARN: "WARN", FAIL: "FAIL", SKIP: "SKIP"}
SCRIPT_HEADERS = {"X-Deck-Lab-Script": "1", "Accept": "application/json"}
SERVER_START_S = 90          # the throwaway server's start, card index load included
FORGE_CHECK_S = 420          # one engine check: two plays of one game, a card log build
NET_TIMEOUT_S = 15
DB_OPTIONS = "-c default_transaction_read_only=on -c lock_timeout=2000 -c statement_timeout=10000"
_SPAWN = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


@dataclass
class Result:
    id: str
    label: str
    status: str = PASS
    lines: list = field(default_factory=list)
    seconds: float = 0.0

    def note(self, status, text):
        """Add one line; the result keeps its worst status (fail > warn > pass)."""
        self.lines.append((status, text))
        rank = {SKIP: 0, PASS: 1, WARN: 2, FAIL: 3}
        if self.status == SKIP or rank[status] > rank[self.status]:
            self.status = status

    def as_json(self):
        return {"id": self.id, "label": self.label, "status": self.status, "seconds": round(self.seconds, 1),
                "lines": [{"status": s, "text": t} for s, t in self.lines]}


class Skip(Exception):
    """The step can't run here; its message says why."""


# ---------------------------------------------------------------- helpers

def _run(argv, timeout, env=None):
    """(exit code, combined output) of a child process, never raising for its failure."""
    try:
        proc = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, **_SPAWN)
    except subprocess.TimeoutExpired:
        return None, f"(gave up after {timeout} s)"
    except OSError as e:
        return None, f"(couldn't start: {e})"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _run_group(argv, timeout, env=None):
    """_run for a child that starts children of its own (Forge's JVMs). On a timeout or Ctrl+C it's
    interrupted first (SIGINT to its group on Linux, so its own handlers stop the JVMs; on Windows its
    Job Object does that when it dies), then killed after a grace period."""
    extra = dict(_SPAWN) if os.name == "nt" else {"start_new_session": True}
    try:
        proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **extra)
    except OSError as e:
        return None, f"(couldn't start: {e})"

    def stop():
        try:
            if proc.poll() is None and os.name != "nt":
                os.killpg(proc.pid, signal.SIGINT)
                try:
                    proc.wait(30)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        finally:
            if proc.poll() is None:
                proc.kill()
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        stop()
        return None, (proc.communicate()[0] or "") + f"\n(gave up after {timeout} s)"
    except BaseException:
        stop()
        raise
    return proc.returncode, out or ""


def _tail(text, lines=6):
    kept = [line for line in (text or "").strip().splitlines() if line.strip()]
    return "\n".join("    " + line for line in kept[-lines:])


def _first_line(error):
    return (str(error).strip().splitlines() or [type(error).__name__])[-1]


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_get(port, path, timeout=10, headers=None):
    """(status, headers dict lower-cased, body bytes) of GET path on 127.0.0.1:port."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        conn.close()


def get_json(port, path, timeout=10):
    from decklab.lib.script_secret import local_headers
    status, _, body = http_get(port, path, timeout, local_headers(SCRIPT_HEADERS))
    try:
        data = json.loads(body.decode("utf-8")) if body else None
    except ValueError:
        data = None
    return status, data


ASSET_RE = re.compile(r"""(?:src|href)\s*=\s*["'](/?[^"'#?]+\.(?:js|css|svg|png|webmanifest|woff2)(?:\?[^"']*)?)["']""",
                      re.I)


def page_assets(html):
    """The page's own script, style and icon links in index.html (no external ones), in order."""
    found = []
    for link in ASSET_RE.findall(html):
        if "://" in link or link.startswith("//"):
            continue
        link = link if link.startswith("/") else "/" + link
        if link not in found:
            found.append(link)
    return found


def pinned(requirements_text, package):
    """The version requirements.txt pins for package (psycopg[binary]==3.3.6 gives 3.3.6), or None."""
    for line in requirements_text.splitlines():
        match = re.match(rf"\s*{re.escape(package)}(?:\[[^\]]*\])?\s*==\s*([^\s#;]+)", line, re.I)
        if match:
            return match.group(1)
    return None


def major_version(text):
    """The major version in `pg_dump (PostgreSQL) 18.1` (18), or None."""
    match = re.search(r"\)\s*(\d+)", text or "") or re.search(r"(\d+)\.\d+", text or "")
    return int(match.group(1)) if match else None


# ---------------------------------------------------------------- steps

def step_doctor(r, ctx):
    from decklab import doctor
    from decklab.lib import preflight
    result = preflight.report(doctor._provider())
    ctx["doctor"] = {row["id"]: row["status"] for row in result["checks"]}
    for row in result["checks"]:
        if row["scope"] != "core":
            continue
        if row["status"] == "ready":
            r.note(PASS, f"{row['label']}: ready")
        else:
            r.note(FAIL, f"{row['label']}: {row['message']}" + (f"\n    Next: {row['next_step']}" if row["next_step"] else ""))


def _needs(ctx, *checks):
    blocked = [c for c in checks if ctx.get("doctor", {}).get(c) != "ready"]
    if blocked:
        raise Skip("the doctor's " + ", ".join(blocked) + " check isn't ready")


def step_code(r, ctx):
    code, out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], 15)
    if code != 0:
        r.note(WARN, "git can't read this checkout, so updates (git pull) and the build check won't work.")
        return
    branch = out.strip()
    _, commit = _run(["git", "log", "-1", "--format=%h %cs %s"], 15)
    r.note(PASS, f"On {branch} at {commit.strip()}")
    _, dirty = _run(["git", "status", "--porcelain", "--untracked-files=no"], 30)
    if dirty.strip():
        r.note(WARN, f"{len(dirty.strip().splitlines())} tracked files are changed here: a server PC should run "
                     "committed code only (git status; git stash or git checkout -- .).")
    behind_code, behind = _run(["git", "rev-list", "--count", "HEAD..@{upstream}"], 15)
    if behind_code == 0 and behind.strip().isdigit() and int(behind.strip()):
        r.note(WARN, f"{behind.strip()} commits behind its upstream as last fetched: git pull.")
    from decklab.lib import venv
    reason = venv.activate()
    if reason:
        r.note(FAIL, f"The .venv can't be used: {reason}")
        return
    try:
        import psycopg
    except ImportError as e:
        r.note(FAIL, f"psycopg doesn't import: {_first_line(e)}")
        return
    want = pinned((ROOT / "decklab" / "requirements.txt").read_text(encoding="utf-8"), "psycopg")
    have = getattr(psycopg, "__version__", "?")
    if want and have != want:
        r.note(WARN, f"psycopg {have} is installed, requirements.txt pins {want}: {venv.pip_hint()}")
    else:
        r.note(PASS, f"psycopg {have} from the .venv")


def step_database(r, ctx):
    _needs(ctx, "database")
    from decklab.db import conn as db, migrate
    for role, why in (("app", "the server"), ("ro", "sql and the checks"), ("owner", "backups and migrations")):
        try:
            with db.connect(role, autocommit=True, timeout=5, options=DB_OPTIONS) as c:
                profiles = c.execute("select count(*) from profile").fetchone()[0]
                version = c.execute("select current_setting('server_version_num')::int").fetchone()[0]
        except Exception as e:      # noqa: BLE001 - every failure is a finding
            r.note(FAIL, f"{db.role_name(role)} ({why}) can't read the database: {_first_line(e)}")
            continue
        r.note(PASS, f"{db.role_name(role)} ({why}) reads it: {profiles} profiles")
        ctx["server_major"] = version // 10000
    try:
        waiting = migrate.pending(role="app")
    except Exception as e:          # noqa: BLE001
        r.note(FAIL, f"The migrations can't be compared: {_first_line(e)}")
    else:
        if waiting:
            r.note(FAIL, f"{len(waiting)} migrations aren't applied: python -m decklab.db migrate")
        else:
            r.note(PASS, f"Every migration is applied (PostgreSQL {ctx.get('server_major', '?')})")


def step_backups(r, ctx):
    _needs(ctx, "database")
    from decklab.db import conn as db, backup
    for name in ("pg_dump", "pg_restore"):
        try:
            path = db.pg_bin(name)
        except FileNotFoundError as e:
            r.note(FAIL, f"{name}: {e}")
            continue
        code, out = _run([str(path), "--version"], 20)
        major = major_version(out)
        if code != 0 or major is None:
            r.note(FAIL, f"{name} doesn't run: {out.strip()[:200]}")
        elif ctx.get("server_major") and major < ctx["server_major"]:
            r.note(FAIL, f"{name} is version {major}, older than the PostgreSQL {ctx['server_major']} server: "
                         "it refuses to dump it. Install the newer client, or set database.pg_bin.")
        else:
            r.note(PASS, f"{name} {major} at {path}")
    s = db.settings()
    places = {}
    for key in ("staging_dir", "backup_dir"):
        try:
            folder = db.path_setting(key, s)
        except ValueError as e:         # off Windows, a relative or Windows-looking folder
            r.note(FAIL, f"Backups can't use {key}: {e}")
            continue
        if not folder:
            continue
        place = places[key] = Path(folder)
        problem = (backup.same_device_problem(place, places.get("staging_dir") or db.DEFAULTS["staging_dir"], s)
                   if key == "backup_dir" else None)
        if problem:
            r.note(FAIL, f"Backups can't be copied: {problem}")
            continue
        existing = next((p for p in (place, *place.parents) if p.is_dir()), None)
        if key == "backup_dir" and not place.is_dir() and not place.parent.is_dir():
            # A backup makes only backup_dir's last folder, never its parents (backup.copy_to).
            r.note(FAIL, f"Backups can't be copied to backup_dir {place}: its parent folder {place.parent} isn't "
                         "there" + (" (is the NAS share mounted?)" if os.name != "nt" else
                                    " (is the NAS share reachable?)"))
            continue
        try:
            if existing is None:
                raise OSError("no part of it exists")
            # os.access says nothing useful on Windows or a network share: write and remove one temp file.
            with tempfile.NamedTemporaryFile(dir=existing, prefix=".decklab-smoke-"):
                pass
        except OSError as e:
            r.note(FAIL, f"Backups can't be written to {key} {place}: {_first_line(e)}")
        else:
            r.note(PASS, f"{key} {place} is writable" + ("" if place.exists() else " (made on the first backup)"))
    last = backup.last_ok()
    dump = last.get("dump")
    if dump is None:
        r.note(WARN, f"No backup has worked yet: python -m decklab.db backup (then the nightly {_task_word()} "
                     "does it).")
    else:
        from datetime import datetime
        age = (datetime.now().astimezone() - dump).total_seconds() / 3600
        limit = float(s.get("stale_backup_hours") or 36)
        r.note(WARN if age > limit else PASS, f"The last backup that worked is {age:.0f} hours old")


def step_cards(r, ctx):
    _needs(ctx, "cards")
    from decklab.lib import cards, currency
    count = cards.info().get("cards") or 0
    r.note(PASS if count > 20000 else FAIL, f"The card index has {count:,} cards")
    for asked, exact in (("Llanowar Elves", "Llanowar Elves"), ("sol ring", "Sol Ring"), ("fire", "Fire // Ice")):
        got = cards.resolve(asked)
        if got != exact:
            r.note(FAIL, f"Looking up {asked!r} gave {got!r}, not {exact!r}")
    printings = [cards.printing(s, n) for s, n in (cards.card("Sol Ring") or {}).get("printings", [])]
    if not any(p and str(p.get("image_normal") or "").startswith("https://") for p in printings):
        r.note(FAIL, "Sol Ring has no printing with a picture address")
    if cards.cheapest_usd("Sol Ring") is None:
        r.note(WARN, "Sol Ring has no price: prices won't show until the card data is updated")
    date = cards.price_date()
    r.note(PASS if date else WARN, f"Prices as of {date or 'unknown'}")
    if currency.code() != "USD" and not cards.fx_file().exists():
        r.note(WARN, "No exchange rate saved yet: the server fetches one on first use (needs the network)")
    if not cards.bulk_path("oracle_tags").exists():
        r.note(WARN, "Scryfall's oracle tags are missing: python -m decklab.lib.cards update")


NETWORK = (
    # name, url, required: unreachable is a failure, else a warning
    ("Scryfall API", "https://api.scryfall.com/bulk-data", True),
    ("Scryfall pictures", "https://cards.scryfall.io/", False),
    ("Exchange rates (Frankfurter)", "https://api.frankfurter.dev/v1/latest?from=USD&to=AUD", False),
    ("EDHREC", "https://json.edhrec.com/pages/commanders/atraxa-praetors-voice.json", False),
    ("MTGMate", "https://www.mtgmate.com.au/robots.txt", False),
    ("Games Portal", "https://gamesportal.com.au/robots.txt", False),
)


def step_network(r, ctx):
    if ctx["args"].offline:
        raise Skip("--offline")
    import urllib.error
    import urllib.request
    from decklab.lib import config
    for name, url, required in NETWORK:
        request = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(request, timeout=NET_TIMEOUT_S) as response:
                response.read(256)
                code = response.status
        except urllib.error.HTTPError as e:
            code = e.code
        except (OSError, ValueError, http.client.HTTPException) as e:
            r.note(FAIL if required else WARN, f"{name} can't be reached: {_first_line(e)}")
            continue
        # Any HTTP answer proves the route; 4xx from a site root is still reachable.
        r.note(PASS if code < 500 else (FAIL if required else WARN), f"{name} answers ({code})")


def step_server(r, ctx):
    if ctx["args"].no_server:
        raise Skip("--no-server")
    _needs(ctx, "config", "cards")
    folder = Path(tempfile.mkdtemp(prefix="decklab-smoke-"))
    port = free_port()
    env = dict(os.environ, DECKLAB_STATE_FILE=str(folder / "server.json"), DECKLAB_DB_LOG=str(folder / "db.log"))
    env.pop("PYTHONPATH", None)
    # The throwaway server mustn't rewrite Forge's card-script overrides (the real server does that).
    bootstrap = ("from decklab.lib.forge import overrides\n"
                 "overrides.ensure_deployed = lambda user_dir: None\n"
                 "from decklab import server\n"
                 "raise SystemExit(server.main())\n")
    log = folder / "server.log"
    proc = subprocess.Popen([sys.executable, "-c", bootstrap, "--host", "127.0.0.1", "--port", str(port),
                             "--no-update", "--log", str(log)], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, **_SPAWN)
    try:
        _exercise_server(r, ctx, proc, port, log)
    finally:
        try:
            _stop_server(r, proc, port, env)
        finally:
            if proc.poll() is None:     # an interrupted stop: never leave a hidden server behind
                proc.kill()
            shutil.rmtree(folder, ignore_errors=True)


def _stop_server(r, proc, port, env):
    """Stop the throwaway server cleanly. On Windows that's its port's stop event (server.py --stop,
    with the state file in env). Elsewhere it's SIGTERM to the child itself: server.py --stop signals
    only a process whose command line names server.py, and this one runs from -c. Kill it if it hangs."""
    if proc.poll() is not None:
        return
    code, out = 0, ""
    if os.name == "nt":
        code, out = _run([sys.executable, str(ROOT / "decklab" / "server.py"), "--port", str(port), "--stop"],
                         60, env=env)
    else:
        proc.terminate()
    try:
        proc.wait(20)
    except subprocess.TimeoutExpired:
        proc.kill()
        r.note(WARN, "The throwaway server didn't stop when asked, so it was killed")
    else:
        if code != 0:
            r.note(WARN, f"Stopping the throwaway server said:\n{_tail(out)}")


def _exercise_server(r, ctx, proc, port, log):
    deadline, status = time.monotonic() + SERVER_START_S, None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
            r.note(FAIL, f"The server exited ({proc.returncode}) while starting:\n{_tail(text, 12)}")
            return
        try:
            code, status = get_json(port, "/api/status", timeout=5)
        except OSError:
            code = None
        cards = ((status or {}).get("cards") or {}) if code == 200 else {}
        if cards.get("ready") and (status.get("database") or {}).get("checking") is not True:
            break
        if cards.get("error") and not status.get("updating"):
            break           # a --no-update server never retries loading the index
        time.sleep(0.5)
    if not ((status or {}).get("cards") or {}).get("ready"):
        why = ((status or {}).get("cards") or {}).get("error") or f"not ready in {SERVER_START_S} s"
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        r.note(FAIL, f"The server didn't load the card index ({why}):\n{_tail(text, 8)}")
        return
    r.note(PASS, f"A server started on 127.0.0.1:{port} and loaded the card index")
    database = status.get("database") or {}
    if database.get("ok"):
        r.note(PASS, "It reaches the database")
    else:
        r.note(FAIL, f"It can't use the database: {database.get('error') or 'unknown reason'}")
    build = status.get("build") or {}
    if build.get("error"):
        r.note(WARN, f"It can't tell its build: {build['error']}")
    code, headers, body = http_get(port, "/", timeout=10)
    html = body.decode("utf-8", errors="replace")
    if code != 200 or "<html" not in html.lower():
        r.note(FAIL, f"The page doesn't load (HTTP {code})")
        return
    assets = page_assets(html)
    broken = []
    for link in assets:
        try:
            code, _, payload = http_get(port, link, timeout=10)
        except OSError as e:
            broken.append(f"{link} ({_first_line(e)})")
            continue
        if code != 200 or not payload:
            broken.append(f"{link} (HTTP {code})")
    if broken:
        r.note(FAIL, f"{len(broken)} of the page's {len(assets)} files don't load: " + ", ".join(broken[:5]))
    else:
        r.note(PASS, f"The page and its {len(assets)} files load")
    reads = ["/api/profiles", "/api/me", "/api/decks", "/api/collection?space=home&limit=1", "/api/tokens?space=home",
             "/api/accessories", "/api/tables/stale", "/api/simulations", "/api/cards/search?q=Sol%20Ring&limit=1"]
    failed = []
    for path in reads:
        try:
            code, data = get_json(port, path, timeout=30)
        except OSError as e:
            failed.append(f"{path} ({_first_line(e)})")
            continue
        if code != 200 or data is None:
            failed.append(f"{path} (HTTP {code})")
    if failed:
        r.note(FAIL, f"{len(failed)} of {len(reads)} read-only API calls failed: " + ", ".join(failed))
    else:
        r.note(PASS, f"{len(reads)} read-only API calls answered (profiles, decks, collection, tokens, kit, cards...)")


def step_live(r, ctx):
    _needs(ctx, "config")
    from decklab.lib import config
    port = int(config.load().get("port", 8642))
    try:
        code, status = get_json(port, "/api/status", timeout=5)
    except OSError:
        start_command = "python decklab/server.py" if sys.platform == "darwin" else "python -m decklab.lib.homenet start"
        r.note(WARN, f"Nothing answers on port {port}: start it ({start_command}), "
                     "or ignore this before homenet install")
        return
    if code != 200 or not isinstance(status, dict):
        r.note(FAIL, f"Something on port {port} answers, but not as Deck Lab (HTTP {code})")
        return
    r.note(PASS, f"Deck Lab answers on port {port}")
    build = status.get("build") or {}
    if build.get("restart_required"):
        r.note(WARN, "It runs older code than this checkout: " + ("restart the foreground server or your own LaunchAgent"
               if sys.platform == "darwin" else "python -m decklab.lib.homenet restart"))
    if build.get("running_dirty"):
        r.note(WARN, "It started with uncommitted changes in the checkout")
    database = status.get("database") or {}
    if database.get("ok") is False:
        r.note(FAIL, f"It can't use the database: {database.get('error') or 'unknown reason'}")
    if (status.get("cards") or {}).get("ready") is False:
        r.note(WARN, "Its card data isn't ready yet")


def step_services(r, ctx):
    if sys.platform == "darwin":
        return _darwin_services(r, ctx)
    code, out = _run([sys.executable, "-m", "decklab.lib.homenet", "status"], 120)
    found = homenet_findings(out)
    if code is None:
        r.note(WARN, f"homenet status didn't finish {out}")
    elif found:
        r.note(WARN, "homenet status (run it for the fixes):\n" + "\n".join("    " + f for f in found))
    elif code != 0:
        r.note(WARN, f"homenet status failed (exit {code}):\n{_tail(out)}")
    else:
        r.note(PASS, "homenet status: the background server, " + _start_words() + " and the network look right")
    code, out = _run([sys.executable, "-m", "decklab.db", "schedule", "status"], 60)
    note = schedule_finding(code, out)
    r.note(PASS if note is None else WARN, note or f"The nightly backup {_task_word()} is installed and its last run "
                                                   "worked")


def nightly_receipt_finding(found, now=None, hours=36):
    """Recent whole-job evidence never implies an installed/working future scheduler."""
    from datetime import datetime, timedelta
    now = now or datetime.now().astimezone()
    finished = found.get("finished_at") if isinstance(found, dict) else None
    if (isinstance(found, dict) and found.get("ok") is True and isinstance(finished, datetime)
            and timedelta(0) <= now - finished.astimezone() <= timedelta(hours=hours)):
        return PASS, "A recent whole nightly completed. macOS scheduling remains operator-managed; no installed timer was verified."
    return WARN, ("No recent successful whole nightly was verified. macOS has no built-in backup scheduler; "
                  "add your own launchd/cron job for python -m decklab.db nightly (SELF-HOSTING.md).")


def _darwin_services(r, ctx):
    r.note(WARN, "macOS uses foreground or operator-managed launchd running; built-in background/network checks are unsupported.")
    if ctx.get("doctor", {}).get("database") != "ready":
        r.note(WARN, "The database isn't ready, so a recent manual nightly cannot be verified; no macOS scheduler is installed by Deck Lab.")
        return
    try:
        from decklab.db import backup, conn
        found = backup.latest(("nightly",)).get("nightly")
        hours = float(conn.settings()["stale_backup_hours"])
        if not 0 < hours <= 24 * 366:
            raise ValueError
        level, message = nightly_receipt_finding(found, hours=hours)
    except Exception:
        level, message = WARN, "Whole-nightly history couldn't be checked; configure and verify your own macOS launchd/cron job."
    r.note(level, message)


def _linux(platform=None):
    return (sys.platform if platform is None else platform).startswith("linux")


def _start_words(platform=None):
    """How the background server starts by itself, as this system does it."""
    selected = sys.platform if platform is None else platform
    return "operator-managed foreground/launchd running" if selected == "darwin" else "its systemd service" if _linux(selected) else "its start at logon"


def _task_word(platform=None):
    """What runs the nightly maintenance here: a systemd timer on Linux, else a scheduled task."""
    selected = sys.platform if platform is None else platform
    return "operator-managed job" if selected == "darwin" else "timer" if _linux(selected) else "task"


def homenet_findings(out):
    """The first line of each WARN and PROBLEM entry `homenet status` printed."""
    return [re.sub(r"\s+", " ", line.strip()) for line in (out or "").splitlines()
            if re.match(r"(WARN|PROBLEM)\s", line)]


def schedule_finding(code, out):
    """What's wrong with the nightly task, from `schedule status`'s exit code and output, or None."""
    text = (out or "").lower()
    if code != 0 or "isn't registered" in text or "isn't installed" in text:
        return f"The nightly backup {_task_word()} isn't installed: python -m decklab.db schedule install"
    flagged = [line.strip() for line in (out or "").splitlines()
               if "WARNING" in line or "it failed" in line or line.strip().startswith("Note: systemd runs")]
    return f"The nightly {_task_word()} needs attention:\n" + _tail("\n".join(flagged), 8) if flagged else None


def step_tunnel(r, ctx):
    _needs(ctx, "config")
    from decklab.lib import config, tunnel
    settings = config.load()
    found = tunnel.settings_of(settings)
    if found is None:
        raise Skip("no tunnel in config.json")
    program = tunnel.find_cloudflared(settings)
    r.note(PASS if program else FAIL, f"cloudflared {'at ' + str(program) if program else 'is not installed'}")
    version = tunnel.version_check(settings) if program else None
    if version is not None:     # E11-S88: an old or unknown version is a note, never a failure
        text = version["text"] + (f" {version['fix']}" if version["fix"] else "")
        r.note(PASS if version["state"] == "current" else WARN, text)
    if not found["config"].is_file():
        r.note(FAIL, f"The tunnel's config {found['config']} is missing")
        return
    r.note(PASS, f"The tunnel's config {found['config']} exists")
    # The server starts cloudflared only with a valid "access" listener and an ingress sending the
    # hostname there (tunnel.start): say so here, not when the tunnel is quietly missing.
    from decklab.lib import access
    try:
        listener = access.settings_of(settings)
    except ValueError as e:
        r.note(FAIL, f"The server won't start the tunnel: {e}")
        return
    if listener is None:
        r.note(FAIL, "The server won't start the tunnel: \"access\" is missing from config.json")
        return
    problems = tunnel.ingress_problems(settings, int(settings.get("port", 8642))) or []
    for problem in problems:
        r.note(FAIL, f"The server won't start the tunnel: {problem}")
    if not problems:
        r.note(PASS, f"cloudflared's config sends {found['hostname'] or 'the tunnel'} to the tunnel listener "
                     f"(127.0.0.1:{listener['port']})")


def step_wake(r, ctx):
    """Wake-on-request (config.json's "wake"): the NAS's wake gate answers, and says the PC is awake."""
    _needs(ctx, "config")
    from decklab.lib import config
    wake = config.load().get("wake")
    if not isinstance(wake, dict):
        raise Skip("no wake block in config.json (the PC never sleeps)")
    gate = str(wake.get("gate") or "").rstrip("/")
    if not gate:
        r.note(WARN, 'config.json\'s "wake" names no "gate": phones at home have no address that wakes the PC')
        return
    import urllib.request
    try:
        with urllib.request.urlopen(gate + "/__status", timeout=5) as response:
            status = json.loads(response.read(4096).decode("utf-8"))
    except (OSError, ValueError, http.client.HTTPException) as e:
        r.note(FAIL, f"The wake gate at {gate} doesn't answer: {_first_line(e)} (decklab/wakegate/README.md)")
        return
    if status.get("awake") is True:
        r.note(PASS, f"The wake gate at {gate} answers and sees this PC awake")
    else:
        r.note(FAIL, f"The wake gate at {gate} answers but can't reach this PC: check DECKLAB_PC_HOST and "
                     "DECKLAB_PC_PORT in its settings")


def step_records(r, ctx):
    _needs(ctx, "config")
    from decklab.lib import config
    from decklab.lib import pathsetting
    records = config.load().get("records_repo")
    if not records:
        raise Skip("no records_repo in config.json")
    try:
        place = Path(pathsetting.normalise("records_repo", records) or str(records))
    except pathsetting.PathSettingError as e:
        r.note(FAIL, str(e))
        return
    if (place / ".git").exists():
        r.note(PASS, f"records_repo {place} is a git checkout")
    else:
        r.note(WARN, f"records_repo {place} is missing, so buylist and report links won't open and Shopping "
                     "lists each order and queue row naming one under needs attention: clone it there")


def step_awake(r, ctx, check=None, user=None):
    """Deck Lab may hold this PC awake (while it's in use, a Forge run, the nightly run): one
    trial, let go at once (keepawake.capability). check and user are for tests."""
    from decklab.lib import keepawake
    found = (check or keepawake.capability)()
    if found.get("ok") is None:
        raise Skip(found.get("why") or "keeping the PC awake isn't supported here")
    if found.get("ok"):
        how = "systemd-inhibit" if found.get("kind") == "systemd-inhibit" else "a Windows power request"
        r.note(PASS, f"Deck Lab may hold the PC awake while it's in use ({how}; tried and let go)")
        return
    why = found.get("why") or "it was refused"
    if found.get("kind") == "systemd-inhibit":
        from decklab.lib.homenet import linux_power
        if user is None:
            try:
                import getpass
                user = getpass.getuser()
            except (OSError, KeyError, ImportError):
                user = None
        r.note(WARN, f"Deck Lab isn't allowed to hold the PC awake ({why}), so it may suspend in the middle of a "
                     f"visit, a Forge run or the nightly run (polkit refuses a service with no login session).\n"
                     f"    Fix: {linux_power.polkit_fix(user)}")
    elif found.get("kind") == "none":
        r.note(WARN, f"Deck Lab can't hold the PC awake: {why}, so it may suspend in the middle of a visit, a Forge "
                     "run or the nightly run (systemd-inhibit comes with systemd).")
    else:
        r.note(WARN, f"Deck Lab couldn't hold the PC awake: {why}")


def step_time(r, ctx, mismatch=None, settings=None):
    """config.json's "timezone" (lib/hometime.py) is this PC's own zone. mismatch and settings
    are for tests."""
    from decklab.lib import hometime
    if settings is None:
        _needs(ctx, "config")
        from decklab.lib import config
        settings = config.load()
    name, problem = hometime.setting(settings)
    if problem:
        r.note(WARN, problem)
        return
    if name is None:
        raise Skip("no timezone in config.json: dates and the nightly run follow this PC's own clock")
    try:
        differs = (mismatch or hometime.host_mismatch)(name)
    except LookupError:
        r.note(WARN, f"This PC has no time zone data for {name}, so it can't be compared"
                     + (" (install the tzdata package)" if sys.platform.startswith("linux") else
                        "; Deck Lab's own dates use UTC+10 without it"))
        return
    if differs:
        r.note(WARN, differs)
    else:
        r.note(PASS, f"This PC's clock keeps {name} time, as config.json's \"timezone\" says")


SCAN_LINES = ["R 0227", "FDN EN"]       # a card's bottom line, in scan_image's block letters


def step_scan(r, ctx, status=None, ocr=None, folder=None):
    """Photo scanning (optional): an OCR engine is here, and it reads a drawn bottom line
    ("R 0227 / FDN EN") as collector number 227 of FDN. status, ocr and folder are for tests."""
    from decklab.lib import scan, scan_image
    found = (status or (lambda: scan.engine_status(refresh=True)))()
    if not found.get("available"):
        r.note(WARN, "No photo scanning engine, so Scan cards... asks for typed names"
                     + (f": {found['detail']}" if found.get("detail") else "")
                     + " (optional: Linux needs the tesseract-ocr package)")
        return
    engine = found.get("engine") or "an OCR engine"
    with tempfile.TemporaryDirectory(dir=folder) as place:
        path = Path(place) / "bottom-line.png"
        path.write_bytes(scan_image.png(SCAN_LINES))
        try:
            lines = (ocr or scan.ocr)(str(path))
        except scan.OcrUnavailable as e:
            r.note(FAIL, f"The {engine} engine is here but couldn't read a test picture: {_first_line(e)}")
            return
    read = scan.read_lines(lines)
    # A set code one OCR confusion away ("FON") is what propose() looks up too.
    if "227" in read["numbers"] and any("fdn" in scan._set_variants(str(code)) for code in read["sets"]):
        r.note(PASS, f"The {engine} engine read a test card's bottom line (227, FDN)")
    else:
        r.note(WARN, f"The {engine} engine read a test card's bottom line as {' / '.join(lines) or 'nothing'}, "
                     "not 227 of FDN, so scans may need their printing chosen by hand")


def step_forge(r, ctx):
    if ctx["args"].no_forge:
        raise Skip("--no-forge")
    _needs(ctx, "config")
    if ctx.get("doctor", {}).get("forge") in ("needs_setup", "blocked"):
        raise Skip("Forge isn't installed where config.json's forge_dir says (optional: SELF-HOSTING.md step 8)")
    from decklab.lib.forge import install, simjar
    try:
        setup = install._setup(remember=False)
    except Exception as e:          # noqa: BLE001 - ForgeError and the rest are findings
        r.note(FAIL, f"Forge can't start: {_first_line(e)}")
        return
    r.note(PASS, f"Java {setup['java']}")
    check = simjar.release_check(Path(setup["forge_dir"]) / setup["jar"])
    r.note(PASS if check["matches"] else WARN, check["advice"])
    if not check["matches"]:
        return
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    started = time.monotonic()
    code, out = _run_group([sys.executable, "-m", "decklab.lib.forge", "engine-check", "--old", str(setup["forge_dir"]),
                      "--games", "1", "--commander-games", "0"], FORGE_CHECK_S, env=env)
    took = time.monotonic() - started
    if code == 0:
        r.note(PASS, f"A real game played twice the same way, card log on ({took:.0f} s)")
    elif code == 3:
        r.note(WARN, f"Games played, but a time limit was hit, so they couldn't be compared ({took:.0f} s):\n{_tail(out)}")
    else:
        r.note(FAIL, f"The Forge engine check failed (exit {code}):\n{_tail(out, 10)}")


STEPS = (
    ("doctor", "Doctor (python -m decklab.doctor)", step_doctor),
    ("code", "Code and Python packages", step_code),
    ("database", "Database roles and migrations", step_database),
    ("backups", "Backups", step_backups),
    ("cards", "Card data", step_cards),
    ("network", "Network", step_network),
    ("server", "A throwaway server", step_server),
    ("live", "The background server", step_live),
    ("services", "Starting by itself, and the nightly task", step_services),
    ("tunnel", "From outside the home", step_tunnel),
    ("wake", "Waking on request (the NAS's wake gate)", step_wake),
    ("awake", "Keeping the PC awake", step_awake),
    ("time", "Time zone", step_time),
    ("records", "The records repo", step_records),
    ("scan", "Photo scanning", step_scan),
    ("forge", "Forge", step_forge),
)


def run(args, steps=STEPS, out=None):
    """Run every step in order, printing each as it finishes (unless out is None); return the results."""
    ctx, results = {"args": args}, []
    for ident, label, fn in steps:
        r = Result(ident, label)
        started = time.monotonic()
        try:
            fn(r, ctx)
        except Skip as e:
            r.status, r.lines = SKIP, [(SKIP, str(e))]
        except KeyboardInterrupt:
            raise
        except Exception as e:      # noqa: BLE001 - a broken step is a failure, never a crash
            r.note(FAIL, f"The step stopped: {type(e).__name__}: {_first_line(e)}")
        if not r.lines:
            r.lines = [(r.status, "ok")]
        r.seconds = time.monotonic() - started
        results.append(r)
        if out is not None:
            print(render(r), file=out, flush=True)
    return results


def render(r):
    lines = [f"{WORDS[r.status]} {r.label} ({r.seconds:.1f} s)"]
    marks = {PASS: "ok  ", WARN: "warn", FAIL: "FAIL", SKIP: "skip"}
    lines += [f"  {marks[s]} {t}" for s, t in r.lines]
    return "\n".join(lines)


def exit_code(results):
    return 1 if any(r.status == FAIL for r in results) else 0


def main(argv=None, steps=STEPS):
    parser = argparse.ArgumentParser(prog="python -m decklab.smoke", description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the results as JSON at the end, instead of text")
    parser.add_argument("--offline", action="store_true", help="skip the network checks")
    parser.add_argument("--no-forge", action="store_true", help="skip Forge (Java, the build and one real game)")
    parser.add_argument("--no-server", action="store_true", help="skip starting a throwaway server")
    args = parser.parse_args(argv)
    started = time.monotonic()
    results = run(args, steps, out=None if args.json else sys.stdout)
    code = exit_code(results)
    took = time.monotonic() - started
    if args.json:
        print(json.dumps({"exit_code": code, "seconds": round(took, 1),
                          "results": [r.as_json() for r in results]}, indent=1))
    else:
        counts = {s: sum(r.status == s for r in results) for s in (PASS, WARN, FAIL, SKIP)}
        print(f"\nSmoke test {'passed' if code == 0 else 'FAILED'} in {took:.0f} s: "
              f"{counts[PASS]} passed, {counts[WARN]} with warnings, {counts[FAIL]} failed, {counts[SKIP]} skipped.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
