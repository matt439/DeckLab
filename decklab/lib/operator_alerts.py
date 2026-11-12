"""Default-off operator heartbeats. Only fixed step names and ok/failed leave the PC."""
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

TIMEOUT = 5
MAX_URL = 2048
STEPS = frozenset({"nightly", "watchdog", "backup", "prune", "visits", "export", "check", "restore check",
                   "shop prices", "shop health", "shop_mtgmate", "shop_gamesportal", "card data", "disk space", "shrink"})


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


def notify(outcomes, *, settings=None, opener=None, log=None):
    """None when disabled, True sent, False failed. Never log the target or exception text."""
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
        data = json.dumps({"steps": steps}, sort_keys=True, separators=(",", ":")).encode()
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
