"""Own the fixture/browser lifecycle without importing application configuration.

Only the dedicated child installs fixture guards and imports application modules.
Normal runs never install software, attach a browser, or accept an existing URL.
"""
import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
FIXTURE_TYPE = "decklab-ui-review-v1"
SUITES = ("capture", "editor", "composition", "variant-layout", "shell-layout", "task-layout",
          "receipt-layout", "families", "zoom", "crosscheck", "assembly-counters", "precon-bonus", "life-counters", "compare-baselines", "first-use")


class ReviewError(RuntimeError):
    """A failed prerequisite, isolation check, capture, or cleanup."""


def _linked(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def prepare_output(path=None):
    """Create a fresh evidence directory; never overwrite or delete a prior run."""
    if path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = ROOT / "decklab/data/ui-review" / f"{stamp}-{uuid.uuid4().hex[:8]}"
    path = Path(path).expanduser().absolute()
    if any(_linked(p) for p in (path, *path.parents)):
        raise ReviewError("The output directory and its parents must not be links or junctions")
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ReviewError("Choose a new or empty output directory; existing evidence is never overwritten")
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def validate_ready(data, runtime, run_id, worker_pid):
    """Accept only this run's owned worker and runtime-contained control files."""
    runtime = Path(runtime).resolve()
    if (not isinstance(data, dict) or data.get("fixture_type") != FIXTURE_TYPE or data.get("run_id") != run_id
            or type(data.get("pid")) is not int or data["pid"] != worker_pid):
        raise ReviewError("The fixture readiness identity does not match the owned worker")
    try:
        url = urlsplit(data["base_url"])
        valid = (url.scheme == "http" and url.hostname == "127.0.0.1" and url.port
                 and url.port != 8642 and not url.username and not url.password
                 and url.path in {"", "/"} and not url.query and not url.fragment)
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ReviewError("The fixture did not supply an isolated loopback origin")
    for key, filename in (("profile_control", "profile.txt"), ("case_control", "case.txt"),
                          ("stop_file", "stop")):
        try:
            control = Path(data[key])
            if not control.is_absolute() or _linked(control) or control.resolve() != runtime / filename:
                raise ValueError(key)
        except (KeyError, TypeError, ValueError, OSError):
            raise ReviewError("The fixture supplied a control outside its owned runtime") from None
    return data


def discover_browser(explicit=None):
    if explicit:
        browser = Path(explicit).expanduser().resolve()
        if not browser.is_file():
            raise ReviewError("The --browser executable does not exist")
        return str(browser)
    candidates = []
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"),
                 os.environ.get("LOCALAPPDATA")):
        if base:
            candidates.extend(Path(base) / tail for tail in (
                "Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe"))
    candidates.extend((Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                       Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")))
    for browser in candidates:
        if browser.is_file():
            return str(browser.resolve())
    raise ReviewError("Install Chrome/Chromium/Edge, or provide its executable with --browser")


def _process_options():
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _requirements(browser=None):
    node = shutil.which("node")
    if not node:
        raise ReviewError("Node.js 20.19, 22.13 or 24 and later is required")
    try:
        version = subprocess.check_output([node, "--version"], timeout=10, text=True).strip()
        major, minor = (int(part) for part in version.lstrip("v").split(".")[:2])
        if not (major >= 24 or major == 22 and minor >= 13 or major == 20 and minor >= 19):
            raise ReviewError("Node.js 20.19, 22.13 or 24 and later is required")
        expected = json.loads((TOOL / "package.json").read_text(encoding="utf-8"))["dependencies"]
        for name, wanted in expected.items():
            installed = TOOL / "node_modules" / name / "package.json"
            actual = json.loads(installed.read_text(encoding="utf-8"))["version"]
            if actual != wanted:
                raise ReviewError("Development dependencies differ from the pinned version; run --setup")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        raise ReviewError("Development dependencies are unavailable; run python scripts/ui_review.py --setup") from None
    return {"node": node, "node_version": version, "browser": discover_browser(browser),
            "playwright_core": expected["playwright-core"], "javascript_parser": expected["acorn"],
            "javascript_scopes": expected["eslint-scope"]}


def setup():
    """Explicit local dependency installation, with package scripts disabled."""
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise ReviewError("Install Node.js and npm before running --setup")
    command = [npm]
    if os.name == "nt":
        node = shutil.which("node")
        cli = Path(npm).parent / "node_modules/npm/bin/npm-cli.js"
        if not node or not cli.is_file():
            raise ReviewError("The Node.js installation does not expose npm-cli.js")
        command = [node, str(cli)]
    result = subprocess.run([*command, "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
                            cwd=TOOL, timeout=120, **_process_options())
    if result.returncode:
        raise ReviewError("npm ci failed; browser setup did not complete")


def _source_state():
    files = {}
    for base in (ROOT / "decklab/web", ROOT / "decklab/lib", ROOT / "decklab/db", TOOL):
        for directory, children, names in os.walk(base):
            children[:] = [n for n in children if n not in {"node_modules", "__pycache__", ".git"}]
            for name in names:
                path = Path(directory) / name
                if path.suffix in {".py", ".js", ".json", ".css", ".html", ".woff2", ".sql"}:
                    files[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("scripts/ui_review.py", "scripts/fixture_runtime.py", "decklab/server.py",
                 "decklab/safari/fixture.py", "decklab/safari/fixture_data.py", "decklab/safari/card.jpg",
                 "decklab/tests/__init__.py", "decklab/tests/db_support.py"):
        files[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                         timeout=5, text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal", "--",
                                             "decklab/web", "decklab/lib", "decklab/db", "decklab/ui_review",
                                             "decklab/server.py", "decklab/safari/fixture.py",
                                             "decklab/safari/fixture_data.py", "scripts/fixture_runtime.py",
                                             "scripts/ui_review.py"],
                                            cwd=ROOT, timeout=5, stderr=subprocess.DEVNULL))
    except (OSError, subprocess.SubprocessError):
        commit, dirty = None, None
    return {"commit": commit, "dirty": dirty, "digest": digest, "files": files}


def _spawn(command, runtime, label):
    env = os.environ.copy()
    env.update({name: str(runtime) for name in ("TMPDIR", "TEMP", "TMP")})
    env["PYTHONUTF8"] = "1"
    if label in SUITES:
        (runtime / f"browser-{label}.started").touch()
    with (runtime / f"{label}.log").open("wb") as log:
        return subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, **_process_options())


def _probe(ready, run_id):
    url = urlsplit(ready["base_url"])
    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=3)
    try:
        connection.request("GET", "/_ui_review/ready", headers={"X-DeckLab-Review-Run": run_id})
        response = connection.getresponse()
        answer = json.loads(response.read(4097))
        valid = (response.status == 200 and isinstance(answer, dict)
                 and answer.get("fixture_type") == FIXTURE_TYPE and answer.get("run_id") == run_id
                 and answer.get("isolated") is True)
    except Exception:
        valid = False
    finally:
        connection.close()
    if not valid:
        raise ReviewError("The dedicated fixture failed its isolation challenge")


def _wait_ready(worker, runtime, run_id, deadline):
    path = runtime / "ready.json"
    until = min(deadline, time.monotonic() + 25)
    while time.monotonic() < until:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                time.sleep(.05)
                continue
            answer = validate_ready(data, runtime, run_id, worker.pid)
            _probe(answer, run_id)
            return answer
        if worker.poll() is not None:
            raise ReviewError("The disposable fixture exited before becoming ready")
        time.sleep(.05)
    raise ReviewError("Timed out waiting for the disposable fixture")


def _force_owned_tree(proc):
    """Only called for a still-running Popen created by this invocation."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        # Playwright's Chrome can have its own process group. Enumerate only
        # descendants of our live Node child before killing that child's group.
        def parents():
            raw = subprocess.check_output(["ps", "-axo", "pid=,ppid="], text=True, timeout=5)
            return {int(pid): int(parent) for pid, parent in (line.split() for line in raw.splitlines())}
        def descendants(snapshot):
            found, seen, frontier = [], {proc.pid}, [proc.pid]
            while frontier:
                parent = frontier.pop()
                children = [pid for pid, ppid in snapshot.items() if ppid == parent and pid not in seen]
                found.extend(children)
                seen.update(children)
                frontier.extend(children)
            return found
        original = parents()
        owned = descendants(original)
        current = parents()
        still_owned = set(descendants(current))
        if proc.poll() is not None:
            return
        for pid in reversed(owned):
            if pid not in still_owned or current.get(pid) != original[pid]:
                continue  # The process exited or changed ownership; never guess.
            if proc.poll() is not None:
                return
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.wait(timeout=10)


def _stop_owned(proc, runtime, role, grace=5):
    if proc is None:
        return True
    if proc.poll() is not None:
        return True
    (runtime / ("stop" if role == "fixture" else "cancel-file")).touch()
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        _force_owned_tree(proc)
        return False
    return True


def _read_browser_summary(path):
    try:
        result = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ReviewError("The browser helper did not produce a valid summary") from None
    if not isinstance(result, dict) or result.get("completed") is not True or result.get("browser_closed") is not True:
        raise ReviewError("Browser capture or browser cleanup did not complete")
    return result


def _run_browser(node, browser, suite, runtime, output, run_id, smoke, deadline, *, strict_console=False):
    command = [node, str(TOOL / f"{suite}.js"), "--runtime", str(runtime), "--output", str(output),
               "--run-id", run_id, "--browser", browser]
    if smoke:
        command.append("--smoke")
    if strict_console:
        command.append("--strict-console")
    proc = _spawn(command, runtime, suite)
    try:
        while proc.poll() is None:
            if time.monotonic() >= deadline:
                raise ReviewError("The headless review exceeded its time limit")
            time.sleep(.1)
        if proc.returncode:
            log = (runtime / f"{suite}.log").read_text(encoding="utf-8", errors="replace")[-2000:]
            raise ReviewError(f"The {suite} helper failed; inspect its retained evidence.\n{log}")
        return _read_browser_summary(output / suite / "summary.json")
    finally:
        _stop_owned(proc, runtime, suite)


def _public_error(error, runtime, run_id=None):
    text = str(error).replace(str(runtime), "<runtime>").replace(str(ROOT), "<repo>")
    if run_id:
        text = text.replace(run_id, "<run>")
    text = re.sub(r"/(?:Users|home)/[^\s\"']+", "<local path>", text)
    return re.sub(r"[A-Za-z]:[\\/][^\r\n\"']+", "<local path>", text)[:1500]


def _write_index(output, report):
    lines = ["# Disposable headless UI review", "", "Screenshots are evidence to inspect, not automatic product passes.", "",
             f"Run completed: {report['completed']}. Cleanup complete: {report['cleanup']['complete']}.", "",
             "See `run.json` for source provenance, guard/adapter limits and suite summaries.", ""]
    for path in sorted(output.rglob("*.png")):
        relative = path.relative_to(output).as_posix()
        lines.append(f"- [{relative}]({relative})")
    (output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_review(output, browser, node, suite="all", smoke=False, timeout=180, *, strict_console=False):
    """Start only owned children; retain evidence and always attempt full cleanup."""
    output = Path(output).resolve()
    source = _source_state()  # No private runtime exists yet if source fingerprinting fails.
    runtime = Path(tempfile.mkdtemp(prefix="decklab-ui-review-")).resolve()
    parent = Path(tempfile.gettempdir()).resolve()
    if runtime.parent != parent or _linked(runtime):
        raise ReviewError("The private runtime is outside its expected temporary parent")
    run_id = uuid.uuid4().hex
    report = {"schema": 1, "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "completed": False, "interrupted": False, "headless": True, "desktop_input": False,
              "source": source, "suite": suite, "smoke": smoke, "strict_console": strict_console, "results": {},
              "limits": ["Synthetic data and renderer adapters; no real Forge results or authentication acceptance",
                         "CSS root-font stress is not OS/browser text zoom", "No physical-device or screen-reader acceptance"],
              "cleanup": {"complete": False}}
    worker = None
    ready = None
    deadline = time.monotonic() + timeout
    try:
        (runtime / "owner.json").write_text(json.dumps({"fixture_type": FIXTURE_TYPE, "run_id": run_id}), encoding="utf-8")
        worker = _spawn([sys.executable, "-m", "decklab.ui_review.fixture", "--runtime", str(runtime),
                         "--run-id", run_id], runtime, "fixture")
        ready = _wait_ready(worker, runtime, run_id, deadline)
        for selected in ("capture", "editor") if suite == "all" else (suite,):
            options = {"strict_console": True} if strict_console else {}
            report["results"][selected] = _run_browser(node, browser, selected, runtime, output, run_id, smoke, deadline, **options)
        report["completed"] = True
    except KeyboardInterrupt:
        report["interrupted"] = True
        report["error"] = "Interrupted; owned fixture/browser cleanup was requested"
    except Exception as error:
        report["error"] = _public_error(error, runtime, run_id)
    finally:
        cooperative = False
        try:
            cooperative = _stop_owned(worker, runtime, "fixture")
            cleanup_path = runtime / "cleanup.json"
            child = json.loads(cleanup_path.read_text(encoding="utf-8")) if cleanup_path.exists() else {}
            report["cleanup"] = {"fixture_exited": worker is None or worker.poll() is not None,
                                  "fixture_exit_code": worker.returncode if worker is not None else None,
                                  "fixture_cooperative": cooperative,
                                  "fixture_temporary_data_removed": child.get("temporary_root_removed") is True,
                                  "runtime_removed": False, "complete": False}
        except Exception as error:
            report["cleanup"]["error"] = _public_error(error, runtime, run_id)
        browser_closed = True
        for selected in SUITES:
            if not (runtime / f"browser-{selected}.started").exists():
                continue
            try:
                summary = json.loads((output / selected / "summary.json").read_text(encoding="utf-8"))
                browser_closed = browser_closed and isinstance(summary, dict) and summary.get("browser_closed") is True
            except (OSError, ValueError):
                browser_closed = False
        report["cleanup"]["browsers_closed"] = browser_closed
        try:
            if runtime.parent != parent or _linked(runtime) or runtime.resolve().parent != parent:
                raise ReviewError("Refusing cleanup of an unexpected runtime path")
            shutil.rmtree(runtime)
            report["cleanup"]["runtime_removed"] = not runtime.exists()
        except Exception as error:
            report["cleanup"]["error"] = _public_error(error, runtime, run_id)
        report["cleanup"]["complete"] = (report["cleanup"].get("fixture_exited", False)
                                              and report["cleanup"].get("runtime_removed", False)
                                              and browser_closed
                                              and cooperative and not report["cleanup"].get("error"))
        try:
            after = _source_state()
            report["source_changed_during_run"] = after["digest"] != report["source"]["digest"]
        except Exception:
            report["source_changed_during_run"] = True
        if report["source_changed_during_run"]:
            report["error"] = "Review source changed during the run; evidence is not one consistent source snapshot"
        report["completed"] = bool(report["completed"] and report["cleanup"]["complete"]
                                   and report["cleanup"].get("fixture_exit_code") == 0
                                   and not report["source_changed_during_run"])
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        (output / "run.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        _write_index(output, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", action="store_true", help="Install pinned browser/static-audit dependencies, then check prerequisites")
    parser.add_argument("--check", action="store_true", help="Check prerequisites without starting a fixture or browser")
    parser.add_argument("--output", type=Path, help="New or empty output folder; default: gitignored decklab/data/ui-review/<run>")
    parser.add_argument("--suite", choices=("all", *SUITES), default="all")
    parser.add_argument("--smoke", action="store_true", help="Use the small capture matrix; editor qualification remains complete")
    parser.add_argument("--strict-console", action="store_true", help="Fail on every browser console error, including resource errors")
    parser.add_argument("--browser", help="Installed Chrome/Chromium/Edge executable; otherwise detected")
    parser.add_argument("--timeout", type=int, default=180, help="Maximum fixture/capture time in seconds (default: 180)")
    args = parser.parse_args(argv)
    try:
        if args.timeout < 5:
            raise ReviewError("--timeout must be at least 5 seconds")
        if args.setup:
            setup()
        requirements = _requirements(args.browser)
        if args.setup or args.check:
            print(f"Ready: {requirements['node_version']}; playwright-core {requirements['playwright_core']}; "
                  f"Acorn {requirements['javascript_parser']}; eslint-scope {requirements['javascript_scopes']}; headless browser available")
            return 0
        output = prepare_output(args.output)
        result = run_review(output, requirements["browser"], requirements["node"], args.suite, args.smoke, args.timeout,
                            strict_console=args.strict_console)
        print(f"Evidence: {output}")
        print(f"Completed: {result['completed']}; cleanup complete: {result['cleanup']['complete']}")
        if result.get("error"):
            print(result["error"], file=sys.stderr)
        return 0 if result["completed"] else 130 if result["interrupted"] else 1
    except (ReviewError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
