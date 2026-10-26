"""Read-only Mac prerequisite checks and explicit six-configuration matrix."""

import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
APPIUM = HERE / "node_modules" / ".bin" / "appium"


def run(*argv, timeout=30):
    completed = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout,
                               stdin=subprocess.DEVNULL)
    if completed.returncode:
        raise RuntimeError(f"{' '.join(map(str, argv))}: {completed.stderr.strip() or completed.stdout.strip()}")
    return completed.stdout.strip()


def source():
    return {"revision": run("git", "-C", str(ROOT), "rev-parse", "HEAD"),
            "dirty": bool(run("git", "-C", str(ROOT), "status", "--porcelain"))}


def _version(value):
    return tuple(int(n) for n in re.findall(r"\d+", value))


def _runtime_number(version):
    parts = (_version(version) + (0, 0, 0))[:3]
    return (parts[0] << 16) | (parts[1] << 8) | parts[2]


def _compatible(device_type, runtime):
    """Use CoreSimulator's compatibility metadata before creating a fresh device."""
    version = _runtime_number(runtime.get("version", ""))
    if not device_type.get("minRuntimeVersion", 0) <= version <= device_type.get("maxRuntimeVersion", 2**32 - 1):
        return False
    supported = runtime.get("supportedDeviceTypes")
    if supported is not None:
        identifiers = {entry.get("identifier") if isinstance(entry, dict) else entry for entry in supported}
        if device_type["identifier"] not in identifiers:
            return False
    return True


def _choices(devices, runtimes, wanted, runtime, device_types):
    candidates = []
    for info in runtimes:
        runtime_id = info["identifier"]
        if info.get("name") and not info["name"].startswith("iOS "):
            continue  # tvOS/watchOS runtimes cannot host these iPhone/iPad types.
        if not info.get("isAvailable") or (runtime and runtime not in (runtime_id, info.get("version"), info.get("name"))):
            continue
        entries = device_types if device_types is not None else devices.get(runtime_id, [])
        for entry in entries:
            name = entry["name"]
            matches = name == wanted if wanted != "11-inch iPad" else (
                name.startswith("iPad Air") and "11-inch" in name)
            if not matches:
                continue
            if device_types is not None:
                if not _compatible(entry, info):
                    continue
            elif not entry.get("isAvailable"):
                continue
            candidates.append((info, entry))
    # Prefer an M2 Air as the suite default, then a stable exact 11-inch Air. A
    # runtime is selected only after choosing the model, so an installed newer
    # M3 runtime cannot silently displace an available M2 configuration.
    if wanted == "11-inch iPad" and candidates:
        names = sorted({entry["name"] for _, entry in candidates})
        preferred = "iPad Air 11-inch (M2)" if "iPad Air 11-inch (M2)" in names else names[0]
        candidates = [(info, entry) for info, entry in candidates if entry["name"] == preferred]
    candidates.sort(key=lambda pair: (_version(pair[0].get("version", "")), pair[1]["name"],
                                      pair[1].get("identifier", pair[1].get("udid", ""))))
    return candidates


def matrix(devices, runtimes, ipad_model=None, runtime=None, device_types=None):
    """Select creatable models and runtimes without relying on personal devices.

    The legacy devices argument remains useful for callers that only have a
    device listing. The Mac preflight always supplies device type definitions.
    """
    rows = []
    required = ["iPhone 15 Pro", "iPhone 17 Pro", ipad_model or "11-inch iPad"]
    for wanted in required:
        candidates = _choices(devices, runtimes, wanted, runtime, device_types)
        picked = candidates[-1] if candidates else None
        for orientation in ("PORTRAIT", "LANDSCAPE"):
            row = {"requested_model": wanted, "orientation": orientation}
            if picked:
                info, device = picked
                row.update(model=device["name"], runtime=info["identifier"],
                           os_version=info["version"], status="pending")
                if device_types is not None:
                    row["device_type"] = device["identifier"]
                else:
                    row.update(udid=device["udid"], initial_state=device.get("state"))
            else:
                row.update(status="unavailable", reason=f"No available {wanted} Simulator" +
                           (f" on runtime {runtime}" if runtime else "") +
                           ". Install the compatible runtime in Xcode Settings > Components and "
                           "check the model in xcrun simctl list devicetypes.")
            rows.append(row)
    return rows


def inspect(ipad_model=None, runtime=None):
    found = {"host": platform.platform(), "python": ".".join(map(str, sys.version_info[:3])),
             "python_executable": sys.executable, "errors": [], "matrix": []}
    if platform.system() != "Darwin":
        found["errors"].append("Safari iOS Simulators require macOS. Run this command on the MacBook; see decklab/safari/README.md.")
        # Preserve all six required entries even on an unsupported host.
        found["matrix"] = matrix({}, [], ipad_model, runtime)
        return found
    if sys.version_info < (3, 11):
        found["errors"].append(f"Python 3.11 or later is required; running {found['python']} at "
                               f"{sys.executable}. Run this suite with a newer Python interpreter; "
                               "see decklab/safari/README.md setup.")
    try:
        simulator_ui = subprocess.run(["pgrep", "-x", "Simulator"], capture_output=True, text=True,
                                      timeout=10, stdin=subprocess.DEVNULL)
        if simulator_ui.returncode in (0, 1):
            found["classic_simulator_ui_running"] = simulator_ui.returncode == 0
        if simulator_ui.returncode == 0:
            found["errors"].append("The classic Simulator UI is running. Close Simulator and retry; "
                                   "Appium's headless mode could otherwise close that existing UI.")
        elif simulator_ui.returncode != 1:
            found["errors"].append("Cannot check for the classic Simulator UI: "
                                   f"pgrep exited {simulator_ui.returncode}: {simulator_ui.stderr.strip()}.")
    except (OSError, subprocess.TimeoutExpired) as error:
        found["errors"].append(f"Cannot check for the classic Simulator UI: {error}.")
    checks = {
        "xcode": ("xcodebuild", "-version"),
        "developer_directory": ("xcode-select", "-p"),
        "node": ("node", "--version"),
        "npm": ("npm", "--version"),
        "appium": (str(APPIUM), "--version"),
    }
    for name, argv in checks.items():
        try:
            found[name] = run(*argv)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            found["errors"].append(f"{name}: {error}. Follow decklab/safari/README.md setup.")
    if "node" in found and _version(found["node"]) != (24, 14, 0):
        found["errors"].append("Use pinned Node 24.14.0 (nvm install && nvm use in decklab/safari).")
    for name, wanted in (("npm", "11.9.0"), ("appium", "3.8.0")):
        if name in found and found[name] != wanted:
            found["errors"].append(f"Use pinned {name} {wanted}; run bash decklab/safari/setup.sh.")
    try:
        found["xcuitest"] = json.loads((HERE / "node_modules" / "appium-xcuitest-driver" /
                                       "package.json").read_text(encoding="utf-8"))["version"]
        if found["xcuitest"] != "10.43.1":
            raise ValueError("installed XCUITest does not match 10.43.1")
    except (OSError, ValueError, KeyError) as error:
        found["errors"].append(f"XCUITest: {error}. Run bash decklab/safari/setup.sh.")
    if "xcode" in found and _version(found["xcode"].splitlines()[0]) < (26,):
        found["errors"].append("Xcode 26 or later with iOS 26 runtime is required for iPhone 17 Pro.")
    if shutil.which("xcrun"):
        try:
            found["runtimes"] = json.loads(run("xcrun", "simctl", "list", "runtimes", "--json"))["runtimes"]
            found["devices"] = json.loads(run("xcrun", "simctl", "list", "devices", "--json"))["devices"]
            found["device_types"] = json.loads(run("xcrun", "simctl", "list", "devicetypes", "--json"))["devicetypes"]
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            found["errors"].append(f"simctl: {error}. Select full Xcode with sudo xcode-select -s /Applications/Xcode.app/Contents/Developer and complete its first launch.")
    else:
        found["errors"].append("xcrun is missing. Install full Xcode and its command-line tools.")
    found["matrix"] = matrix(found.get("devices", {}), found.get("runtimes", []), ipad_model, runtime,
                             device_types=found.get("device_types", []))
    return found
