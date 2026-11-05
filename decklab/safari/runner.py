"""One command, six disposable Simulator runs, and reviewable failure artifacts."""

import argparse
import contextlib
import json
import os
import re
import signal
import socket
import subprocess
import time
import traceback
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import environment
from .driver import Driver, DriverError

# Texts Appium returns once the Simulator's web inspector, WebDriverAgent or
# display has gone (2026-11-05: an iPhone 15 Pro landscape Simulator rebooted
# mid-session). They only trigger a liveness probe; text alone never ends a run.
SESSION_LOST_TEXTS = ("Remote debugger is not connected", "ECONNREFUSED 127.0.0.1:8100",
                      "display surface is not available")
SESSION_LOST_REASON = "Simulator session lost (environment)"
RETRY_SUFFIX = "-retry1"


class SessionLost(RuntimeError):
    """The Appium session or its Simulator died; what failed after it says nothing about the page."""


def suggests_lost_session(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, (DriverError, AssertionError)) and any(
                text in str(error) for text in SESSION_LOST_TEXTS):
            return True
        error = error.__cause__ or error.__context__
    return False


def slug(value):
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")


def write_reports(output, report):
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# Safari Simulator regression", "", f"Source: `{report['source'].get('revision', 'unknown')}`"
             + (" (uncommitted changes)" if report["source"].get("dirty") else ""), "",
             "Simulator coverage for E11-S29 / E2-S22. Physical-device acceptance is separate.", "",
             "| Requested model | Actual model | OS | Orientation | Result |", "|---|---|---|---|---|"]
    for row in report["matrix"]:
        status = row["status"] + (" (retried once)" if row.get("retries") else "")
        lines.append(f"| {row['requested_model']} | {row.get('model', 'unavailable')} | "
                     f"{row.get('os_version', '—')} | {row['orientation']} | {status} |")
    for error in report.get("errors", []):
        lines.extend(["", f"Setup: {error}"])
    for row in report["matrix"]:
        lines.extend(["", f"## {row['requested_model']} {row['orientation']}", ""])
        if row.get("reason"):
            lines.append(row["reason"])
        for note in row.get("cleanup_notes", []):
            lines.append("Cleanup: " + note.replace("\n", " "))
        diagnostics = row.get("session_diagnostics", {})
        for artifact in diagnostics.get("artifacts", []):
            lines.append(f"- [{artifact}]({artifact})")
        for error in diagnostics.get("diagnostic_errors", []):
            lines.append("Diagnostic unavailable: " + error.replace("\n", " "))
        for assertion in row.get("assertions", []):
            assertion_lines(lines, assertion, "")
        for number, retry in enumerate(row.get("retries", []), 1):
            lines.extend(["", (f"Attempt {number} lost its Simulator session and was retried once on a new "
                               f"Simulator: {retry['reason']}").replace("\n", " ")])
            for note in retry.get("cleanup_notes", []):
                lines.append(f"Attempt {number} cleanup: " + note.replace("\n", " "))
            for assertion in retry.get("assertions", []):
                assertion_lines(lines, assertion, f"attempt {number} ")
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def assertion_lines(lines, assertion, prefix):
    lines.append(f"- {prefix}{assertion['status']}: {assertion['name']}")
    if assertion.get("error"):
        lines.append("  " + assertion["error"].replace("\n", " "))
    for artifact in assertion.get("artifacts") or []:
        lines.append(f"  - [{artifact}]({artifact})")


class Recorder:
    def __init__(self, driver, directory, output, row):
        self.driver, self.directory, self.output, self.row = driver, directory, output, row
        row["assertions"] = []

    def __call__(self, name, action):
        result = {"name": name, "status": "running", "artifacts": []}
        self.row["assertions"].append(result)
        started = time.monotonic()
        try:
            result["evidence"] = action()
            result["status"] = "passed"
        except KeyboardInterrupt as error:
            result.update(status="interrupted", error="KeyboardInterrupt: run interrupted",
                          traceback=traceback.format_exc())
            self.capture(result, f"{len(self.row['assertions']):02}-{slug(name)}")
            raise
        except Exception as error:
            result.update(status="failed", error=f"{type(error).__name__}: {error}",
                          traceback=traceback.format_exc())
            lost = suggests_lost_session(error) and not self.session_alive()
            self.capture(result, f"{len(self.row['assertions']):02}-{slug(name)}")
            if lost:
                # The flows after this one would only fail against a dead driver.
                result["session_lost"] = True
                raise SessionLost(result["error"]) from error
        finally:
            result["seconds"] = round(time.monotonic() - started, 2)
            print(f"  {result['status']}: {name}", flush=True)
            if result.get("error"):
                print("    " + result["error"].splitlines()[0][:500], flush=True)
        return result["status"] == "passed"

    def session_alive(self, attempts=2, pause=2):
        """A native WebDriverAgent round trip, which a dead session or Simulator fails every time."""
        for attempt in range(attempts):
            if attempt:
                time.sleep(pause)
            try:
                self.driver.command("GET", "/orientation")
                return True
            except Exception:
                continue
        return False

    def capture(self, result, name):
        errors = result.setdefault("diagnostic_errors", [])
        contexts = result["diagnostic_context"] = {"original": None, "capture": None}
        try:
            contexts["original"] = self.driver.command("GET", "/context")
        except Exception as error:
            errors.append(f"Original context: {error}")
        try:
            # A failed case may leave a detached/background webview selected.
            # Native capture avoids remote-debugger source/execute timeouts and
            # leaves the next flow's visit() to select its own Safari page.
            self.driver.switch_context("NATIVE_APP")
            contexts["capture"] = "NATIVE_APP"
        except Exception as error:
            errors.append(f"Native capture context: {error}")
        errors.append("browser.json: unavailable; web execution is skipped because the failed webview may be detached.")
        actions = []
        if contexts["capture"] == "NATIVE_APP":
            actions.extend([
                ("png", self.driver.screenshot),
                ("source.txt", lambda: str(self.driver.command("GET", "/source")).encode()),
            ])
        else:
            errors.extend(["png: unavailable without a confirmed native context.",
                           "source.txt: unavailable without a confirmed native context."])
        actions.append(("contexts.json", lambda: json.dumps(self.driver.contexts(), indent=2).encode()))
        for extension, action in actions:
            try:
                path = self.directory / f"{name}.{extension}"
                path.write_bytes(action())
                result["artifacts"].append(path.relative_to(self.output).as_posix())
            except Exception as error:
                errors.append(f"{extension}: {error}")


@contextlib.contextmanager
def appium(output):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ)
    env.pop("APPIUM_HOME", None)  # driver auto-discovery from this project's pinned dependencies
    with (output / "appium.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(environment.APPIUM), "--address", "127.0.0.1", "--port", str(port),
                                    "--log-timestamp", "--use-drivers", "xcuitest"],
                                   cwd=environment.HERE, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            url, deadline = f"http://127.0.0.1:{port}", time.monotonic() + 60
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Appium exited during startup. See appium.log and rerun setup.sh.")
                try:
                    with urllib.request.urlopen(url + "/status", timeout=1) as response:
                        if json.load(response).get("value", {}).get("ready"):
                            break
                except (OSError, ValueError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("Appium did not become ready within 60 seconds. See appium.log.")
                time.sleep(0.25)
            yield url
        finally:
            # Appium/Xcode helpers inherit this run's new process group. Killing
            # that owned group cannot target an independently started server.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
            finally:
                # The parent can exit before an unresponsive xcodebuild child.
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)


@contextlib.contextmanager
def simulator(row):
    # A new device leaves Home Screen icons, website data and keyboard preferences
    # on the user's existing simulators untouched. Only this returned UUID is removed.
    if not row.get("device_type"):
        # Compatibility for a caller holding an older matrix; new preflight rows
        # already contain the exact type selected independently of personal names.
        device_types = json.loads(environment.run("xcrun", "simctl", "list", "devicetypes", "--json"))["devicetypes"]
        matching = [entry for entry in device_types if entry["name"] == row["model"]]
        if len(matching) != 1:
            raise RuntimeError(f"Cannot uniquely resolve Simulator device type for {row['model']}.")
        row["device_type"] = matching[0]["identifier"]
    name = "DeckLabSafari-" + uuid.uuid4().hex[:12]
    udid = environment.run("xcrun", "simctl", "create", name, row["device_type"], row["runtime"])
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", udid):
        raise RuntimeError(f"simctl create returned an invalid UUID: {udid!r}")
    row["test_udid"], row["test_name"] = udid, name
    try:
        environment.run("xcrun", "simctl", "boot", udid)
        environment.run("xcrun", "simctl", "bootstatus", udid, "-b", timeout=180)
        # Test native accessibility names deterministically on every host locale.
        environment.run("xcrun", "simctl", "spawn", udid, "defaults", "write", "NSGlobalDomain",
                        "AppleLanguages", "-array", "en")
        yield udid
    finally:
        try:
            try:
                environment.run("xcrun", "simctl", "shutdown", udid)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                if not already_shutdown(udid, error):
                    cleanup_failed(row, f"Simulator shutdown: {error}")
        finally:
            # Even shutdown timeout/interruption must attempt deletion of only
            # this created UUID, never 'all' or an existing personal device.
            try:
                environment.run("xcrun", "simctl", "delete", udid)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                cleanup_failed(row, f"Simulator deletion: {error}")


def already_shutdown(udid, error):
    """Accept Appium's earlier shutdown only after checking our created device."""
    if (not isinstance(error, RuntimeError) or not re.search(r"\bcode=405\b", str(error))
            or not re.search(r"current state:\s*Shutdown\b", str(error))):
        return False
    try:
        devices = json.loads(environment.run("xcrun", "simctl", "list", "devices", "--json"))["devices"]
        return isinstance(devices, dict) and any(
            isinstance(device, dict) and device.get("udid") == udid and device.get("state") == "Shutdown"
            for group in devices.values() if isinstance(group, list) for device in group)
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return False


def cleanup_failed(row, message):
    row.setdefault("cleanup_notes", []).append(message)
    if row.get("status") != "interrupted":
        row["status"] = "failed"


def capabilities(row, udid):
    return {"platformName": "iOS", "browserName": "safari", "appium:automationName": "XCUITest",
            "appium:udid": udid, "appium:deviceName": row["model"],
            "appium:platformVersion": row["os_version"], "appium:orientation": row["orientation"],
            "appium:language": "en", "appium:locale": "en_US", "appium:newCommandTimeout": 180,
            "appium:connectHardwareKeyboard": False, "appium:forceSimulatorSoftwareKeyboardPresence": True,
            "appium:isHeadless": True,
            "appium:nativeWebTap": True, "appium:nativeWebTapStrict": True,
            "appium:webviewConnectTimeout": 60000, "appium:wdaLaunchTimeout": 120000,
            "appium:includeSafariInWebviews": True, "appium:additionalWebviewBundleIds": ["*"],
            "appium:showXcodeLog": True}


def verify_orientation(driver, fixture, expected):
    from .interaction import require, visit

    visit(driver, fixture, "/library")
    actual = driver.command("GET", "/orientation")
    viewport = driver.execute("return {width: innerWidth, height: innerHeight};")
    require(actual == expected, f"Requested {expected} but native orientation is {actual}")
    landscape = viewport["width"] > viewport["height"]
    require(landscape == (expected == "LANDSCAPE"),
            f"Safari viewport does not match {expected}: {viewport}")
    return {"native_orientation": actual, "viewport": viewport}


def run_configuration(url, row, output, suffix=""):
    from .fixture import FixtureServer
    from .flows import run_flows

    directory = output / (slug(row["model"] + "-" + row["orientation"]) + suffix)
    directory.mkdir()
    lost = False
    with simulator(row) as udid, FixtureServer() as fixture, \
            (directory / "commands.jsonl").open("w", encoding="utf-8") as log:
        driver = None
        try:
            row["fixture_url"] = fixture.base_url
            fixture.artifacts_dir = directory
            driver = Driver(url, capabilities(row, udid), log)
            row["capabilities"] = driver.capabilities
            recorder = Recorder(driver, directory, output, row)
            fixture.expected_orientation = row["orientation"]
            recorder("device.native_and_viewport_orientation",
                     lambda: verify_orientation(driver, fixture, row["orientation"]))
            run_flows(driver, fixture, recorder)
            row["status"] = "passed" if row["assertions"] and all(
                item["status"] == "passed" for item in row["assertions"]) else "failed"
        except SessionLost:
            # Propagates only after the driver, fixture and Simulator are torn
            # down, so main() can retry on a new Simulator.
            lost = True
            raise
        except (Exception, KeyboardInterrupt) as error:
            row.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                       reason=f"{type(error).__name__}: {error}",
                       traceback=traceback.format_exc())
            diagnostic = {"artifacts": []}
            if driver:
                Recorder(driver, directory, output, {"assertions": []}).capture(diagnostic, "session-failure")
            else:
                try:
                    path = directory / "session-failure.png"
                    environment.run("xcrun", "simctl", "io", udid, "screenshot", str(path))
                    diagnostic["artifacts"].append(path.relative_to(output).as_posix())
                except Exception as capture_error:
                    diagnostic["diagnostic_errors"] = [str(capture_error)]
            row["session_diagnostics"] = diagnostic
            if isinstance(error, KeyboardInterrupt):
                raise
        finally:
            (directory / "fixture.log").write_text("\n".join(fixture.logs) + "\n", encoding="utf-8")
            if driver:
                try:
                    driver.close()
                except Exception as error:
                    if lost:  # expected: the session is already gone
                        row.setdefault("cleanup_notes", []).append(f"Appium session cleanup: {error}")
                    else:
                        cleanup_failed(row, f"Appium session cleanup: {error}")


def all_check_names():
    from .flows import run_flows

    names = ["device.native_and_viewport_orientation"]
    run_flows(None, None, lambda name, action: names.append(name))
    return names


# One attempt's results, moved into row["retries"] before the retry.
ATTEMPT_KEYS = ("assertions", "cleanup_notes", "session_diagnostics", "reason", "traceback",
                "capabilities", "fixture_url", "test_udid", "test_name")


def run_with_retry(url, row, output):
    """Run one configuration; a lost Simulator session costs one retry on a new Simulator."""
    try:
        run_configuration(url, row, output)
        return
    except SessionLost as error:
        first = {"reason": str(error), "directory": slug(row["model"] + "-" + row["orientation"])}
        for key in ATTEMPT_KEYS:
            if key in row:
                first[key] = row.pop(key)
        row["retries"] = [first]
    row["status"] = "running"
    print("  Simulator session lost; retrying once on a new Simulator", flush=True)
    try:
        run_configuration(url, row, output, RETRY_SUFFIX)
    except SessionLost as error:
        assertions = row.setdefault("assertions", [])
        done = {item["name"] for item in assertions}
        assertions.extend({"name": name, "status": "not_run", "artifacts": [],
                           "error": "Not run: the Simulator session was lost."}
                          for name in all_check_names() if name not in done)
        row.update(status="failed", reason=f"{SESSION_LOST_REASON}, on the retry too: {error}")
        return
    # The retry never hides a failure the page caused before the session was lost.
    earlier = [item["name"] for item in first.get("assertions", [])
               if item["status"] != "passed" and not item.get("session_lost")]
    if earlier:
        note = "Attempt 1 failed before its session was lost: " + ", ".join(earlier) + "."
        row.update(status="failed", reason=(row["reason"] + " " + note) if row.get("reason") else note)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="inspect Mac prerequisites and matrix without running tests")
    parser.add_argument("--output", type=Path, help="new report directory (default: decklab/data/safari/<run>)")
    parser.add_argument("--ipad-model", help="exact installed 11-inch iPad Simulator model name")
    parser.add_argument("--runtime", help="exact installed runtime version, name or identifier")
    args = parser.parse_args(argv)
    if args.ipad_model and (not args.ipad_model.startswith("iPad") or "11-inch" not in args.ipad_model):
        parser.error("--ipad-model must name an 11-inch iPad Simulator")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    output = args.output or environment.ROOT / "decklab" / "data" / "safari" / stamp
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    # Populate all requested rows before any potentially interrupted subprocess.
    initial = environment.matrix({}, [], args.ipad_model, args.runtime)
    for row in initial:
        row.update(status="pending")
        row.pop("reason", None)
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "coverage": "Simulator",
              "physical_device_acceptance": False, "check_only": args.check,
              "source": {"revision": "unknown"}, "errors": [], "matrix": initial}
    exit_code = 0
    try:
        try:
            report["source"] = environment.source()
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            report["source"] = {"error": str(error)}
        report.update(environment.inspect(args.ipad_model, args.runtime))
        if report["source"].get("error"):
            report["errors"].append("Cannot record source revision: " + report["source"]["error"])
        if report["errors"]:
            exit_code = 2
            for row in report["matrix"]:
                if row["status"] == "pending":
                    row.update(status="not_run", reason="Prerequisite checks failed; see setup errors.")
        elif not args.check:
            with appium(output) as url:
                for row in report["matrix"]:
                    if row["status"] != "pending":
                        continue
                    print(f"{row['model']} / {row['os_version']} / {row['orientation']}", flush=True)
                    row["status"] = "running"
                    try:
                        run_with_retry(url, row, output)
                    except KeyboardInterrupt:
                        row.update(status="interrupted", reason="Run interrupted during this configuration.")
                        raise
                    except Exception as error:
                        row.update(status="failed", reason=f"{type(error).__name__}: {error}",
                                   traceback=traceback.format_exc())
                    write_reports(output, report)
        else:
            for row in report["matrix"]:
                if row["status"] == "pending":
                    row["status"] = "ready"
        if any(row["status"] == "unavailable" for row in report["matrix"]):
            exit_code = 2
        elif any(row["status"] == "failed" for row in report["matrix"]):
            exit_code = 1
    except (Exception, KeyboardInterrupt) as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
        exit_code = 130 if isinstance(error, KeyboardInterrupt) else 2
    finally:
        for row in report["matrix"]:
            if row["status"] == "running":
                row.update(status="interrupted", reason="Run interrupted during this configuration.")
            elif row["status"] == "pending":
                row.update(status="not_run", reason="Run interrupted before this configuration started.")
        report["finished_at"], report["exit_code"] = datetime.now(timezone.utc).isoformat(), exit_code
        write_reports(output, report)
    print(f"Report: {output / 'report.md'}", flush=True)
    for error in report["errors"]:
        print(error, flush=True)
    return exit_code
