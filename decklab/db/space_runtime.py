"""Fail-closed deployment checks for member removal and recovery.

Nothing here starts, stops or changes a service. Removal needs a cooperative,
current server (or no listener) and no unrelated Python process which could be
an older Forge coordinator. Checks are repeated under the exclusive claim.
"""
import errno
import http.client
import json
import os
import subprocess
import sys
from pathlib import Path

from decklab.lib import config

TIMEOUT = 2
MAX_STATUS = 128 * 1024


def capability():
    """Private script-status metadata; no filesystem writes or worker launch."""
    from decklab.lib.forge import lifecycle
    return dict(lifecycle.capability(), pid=os.getpid())


def _status():
    """A direct loopback read. Only a refused connection proves no listener."""
    connection = http.client.HTTPConnection("127.0.0.1", config.load()["port"], timeout=TIMEOUT)
    try:
        connection.request("GET", "/api/status", headers={"X-Deck-Lab-Script": "1"})
        response = connection.getresponse()
        payload = response.read(MAX_STATUS + 1)
        if response.status != 200 or len(payload) > MAX_STATUS:
            raise ValueError("The running server's removal capability cannot be verified.")
        found = json.loads(payload)
        if not isinstance(found, dict):
            raise ValueError("The running server's removal capability cannot be verified.")
        return found
    except ConnectionRefusedError:
        return None
    except OSError as error:
        if error.errno == errno.ECONNREFUSED or getattr(error, "winerror", None) == 10061:
            return None
        raise ValueError("The server's state cannot be verified; removal is refused.") from None
    except (http.client.HTTPException, UnicodeError, json.JSONDecodeError):
        raise ValueError("The server's state cannot be verified; removal is refused.") from None
    finally:
        connection.close()


def _processes():
    """Only interpreter ids and parents, never command lines or private arguments."""
    if os.name == "nt":
        script = ("@(Get-CimInstance Win32_Process -ErrorAction Stop | "
                  "Where-Object { $_.Name -match '^(?i)(pythonw?|py)([0-9.]+)?\\.exe$' } | "
                  "Select-Object ProcessId,ParentProcessId) | ConvertTo-Json -Compress")
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        try:
            result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                                    capture_output=True, text=True, timeout=15,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise ValueError("Interpreter processes cannot be checked; removal is refused.")
            rows = json.loads(result.stdout.strip() or "[]")
            rows = rows if isinstance(rows, list) else [rows]
            return {int(row["ProcessId"]): int(row["ParentProcessId"]) for row in rows}
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
            raise ValueError("Interpreter processes cannot be checked; removal is refused.") from None
    if sys.platform.startswith("linux"):
        found = {}
        try:
            for folder in Path("/proc").iterdir():
                if not folder.name.isdigit():
                    continue
                try:
                    name = (folder / "comm").read_text().strip().casefold()
                    if not name.startswith(("python", "pypy")):
                        continue
                    values = (folder / "stat").read_text().rsplit(")", 1)[1].split()
                    found[int(folder.name)] = int(values[1])
                except FileNotFoundError:
                    continue                         # a process that ended during the scan
        except (OSError, ValueError, IndexError):
            raise ValueError("Interpreter processes cannot be checked; removal is refused.") from None
        return found
    raise ValueError("Interpreter process checks are unavailable on this platform; removal is refused.")


def require_ready(results_dir=None):
    """Refuse old/dirty servers or unaccounted interpreter processes; write nothing.

    The exclusive lifecycle claim remains the authority for cooperative workers.
    No other interpreter, including an ancestor, is assumed to be an inert launcher.
    Use the direct interpreter and let other Python projects finish before removal.
    """
    from decklab.lib.forge import lifecycle
    current = lifecycle.capability(results_dir)
    status = _status()
    allowed = {os.getpid()}
    if status is not None:
        adopted, build = status.get("forge_lifecycle"), status.get("build")
        if not isinstance(adopted, dict) or type(adopted.get("version")) is not int \
                or adopted.get("version") != current["version"] \
                or adopted.get("root") != current["root"] or type(adopted.get("pid")) is not int \
                or adopted["pid"] < 1:
            raise ValueError("The running server has not adopted safe member removal. Deploy and restart it first.")
        if not isinstance(build, dict) or any(build.get(key) is not False
                                               for key in ("running_dirty", "latest_dirty", "restart_required")):
            raise ValueError("The running server must use the committed current code before member removal.")
        allowed.add(adopted["pid"])
    processes = _processes()
    if os.getpid() not in processes:
        raise ValueError("Interpreter process inventory is incomplete; removal is refused.")
    if set(processes) - allowed:
        raise ValueError("Other Python processes are running. Wait for them to finish before member removal.")
    return current
