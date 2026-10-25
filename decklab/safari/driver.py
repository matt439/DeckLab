"""Small W3C/Appium client; no Selenium installation or network service needed."""

import base64
import json
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlparse


class DriverError(RuntimeError):
    pass


class Driver:
    def __init__(self, url, capabilities, log):
        parsed = urlparse(url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
            raise ValueError("The Appium server must be this run's loopback process.")
        self.url, self.log, self.session_id = url.rstrip("/"), log, None
        result = self._request("POST", "/session", {"capabilities": {"alwaysMatch": capabilities}})
        self.session_id = result["sessionId"]
        self.capabilities = result.get("capabilities", {})

    def _request(self, method, path, body=None):
        payload = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.url + path, data=payload, method=method,
                                         headers={"Content-Type": "application/json"})
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            try:
                details = json.load(error).get("value", {})
            except (ValueError, OSError):
                details = {"message": str(error)}
            finally:
                error.close()
            self._log(method, path, body, started, error=details)
            raise DriverError(f"{method} {path}: {details.get('message', details)}") from error
        except (OSError, ValueError) as error:
            self._log(method, path, body, started, error=str(error))
            raise DriverError(f"{method} {path}: {error}") from error
        self._log(method, path, body, started)
        value = result.get("value")
        if isinstance(value, dict) and value.get("error"):
            raise DriverError(str(value))
        return value

    def _log(self, method, path, body, started, error=None):
        # Screenshot/source payloads are kept as separate failure artifacts.
        self.log.write(json.dumps({"method": method, "path": path, "body": body,
                                   "seconds": round(time.monotonic() - started, 3),
                                   "error": error}) + "\n")
        self.log.flush()

    def command(self, method, path, body=None):
        suffix = "/" + path.lstrip("/") if path else ""
        return self._request(method, f"/session/{quote(self.session_id, safe='')}{suffix}", body)

    def execute(self, script, args=None):
        return self.command("POST", "/execute/sync", {"script": script, "args": args or []})

    def find(self, using, value):
        found = self.command("POST", "/element", {"using": using, "value": value})
        return found.get("element-6066-11e4-a52e-4f735466cecf", found.get("ELEMENT"))

    def click(self, element):
        return self.command("POST", f"/element/{quote(element, safe='')}/click", {})

    def send_keys(self, element, text):
        return self.command("POST", f"/element/{quote(element, safe='')}/value", {"text": text})

    def contexts(self):
        return self.command("GET", "/contexts")

    def switch_context(self, name):
        return self.command("POST", "/context", {"name": name})

    def screenshot(self):
        return base64.b64decode(self.command("GET", "/screenshot"), validate=True)

    def close(self):
        if self.session_id:
            try:
                self.command("DELETE", "")
            finally:
                self.session_id = None


def wait(predicate, timeout=25, message="Condition was not met"):
    deadline, last_error = time.monotonic() + timeout, None
    while True:
        try:
            value = predicate()
            if value:
                return value
        except DriverError as error:
            last_error = error
        if time.monotonic() >= deadline:
            raise AssertionError(message + (f": {last_error}" if last_error else ""))
        time.sleep(0.25)
