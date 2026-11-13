"""Default-off operator heartbeats. Fixed step names and ok/failed leave the PC, and for a
failed DETAIL_STEPS step (only "shrink", E11-S87) one detail line its caller builds from
whole-table names and counts and a date (shrink.heartbeat_detail): printable ASCII only, at
most MAX_DETAIL characters, sent as {"steps": {...}, "details": {"shrink": "..."}}."""
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

TIMEOUT = 5
MAX_URL = 2048
STEPS = frozenset({"nightly", "watchdog", "backup", "prune", "visits", "export", "check", "restore check",
                   "shop prices", "shop health", "shop_mtgmate", "shop_gamesportal", "card data", "disk space", "shrink"})
DETAIL_STEPS = frozenset({"shrink"})   # the only steps whose failure may carry a detail line
MAX_DETAIL = 400                       # characters of one detail line; longer is cut, ending "..."


def _detail(text):
    """text as one bounded line of printable ASCII, or None when nothing is left."""
    if not isinstance(text, str):
        return None
    clean = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in text).strip()
    if not clean:
        return None
    return clean if len(clean) <= MAX_DETAIL else clean[:MAX_DETAIL - 3].rstrip() + "..."


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def address(settings):
    value = settings.get("alerts")
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > MAX_URL or any(ord(ch) < 33 or ord(ch) == 127 for ch in value):
        raise ValueError("Invalid alerts address")
    try:
        parts = urlsplit(value)
        valid = parts.scheme in ("https", "http") and bool(parts.hostname) and not parts.username and not parts.password and not parts.fragment
        parts.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Invalid alerts address")
    return value


def notify(outcomes, *, details=None, settings=None, opener=None, log=None):
    """None when disabled, True sent, False failed. Never log the target or exception text.
    details ({step: line}) is sent only for a DETAIL_STEPS step sent as failed, bounded."""
    try:
        if settings is None:
            from decklab.lib import config
            settings = config.load()
        target = address(settings)
        if target is None:
            return None
        steps = {key: "ok" if value else "failed" for key, value in outcomes.items()
                 if key in STEPS and type(value) is bool}
        if not steps:
            return None
        payload = {"steps": steps}
        lines = {}
        for key, text in (details.items() if isinstance(details, dict) else ()):
            line = _detail(text) if key in DETAIL_STEPS and steps.get(key) == "failed" else None
            if line:
                lines[key] = line
        if lines:
            payload["details"] = lines
        data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        request = urllib.request.Request(target, data=data, method="POST", headers={"Content-Type": "application/json"})
        selected = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        with selected.open(request, timeout=TIMEOUT) as response:
            if not 200 <= response.status < 300:
                raise ValueError("Heartbeat refused")
        return True
    except Exception:
        if log is not None:
            try:
                log("The optional operator heartbeat could not be sent.")
            except Exception:
                pass
        return False
