"""GET /sym/<code>.svg: Scryfall's card symbols (mana, tap, energy, ...),
cached in decklab/data/symbols/ the first time each one is asked for.

The page draws mana costs, rules text and guide prose with these pictures
(web/symbols.js). <code> is the name of Scryfall's own SVG file: the symbol
without its braces and slashes, in capitals ({W/U} -> WU, {2/W} -> 2W,
{W/P} -> WP, {T} -> T), with HALF for {½} and INFINITY for {∞}.

Scryfall's list of symbols (GET /symbology, one request) is saved as
symbology.json beside the pictures and read from there afterwards. A code
that list doesn't have asks for the list again, at most once every
RELIST_AFTER, so a symbol from a new set turns up without a restart. Every
request goes through cards._open_url, with Deck Lab's User-Agent and an
Accept header, spaced like the card data's, and gives up after FETCH_TIMEOUT.

A failed fetch (no network, Scryfall down) makes every symbol not cached yet
answer 503 at once for NETWORK_PAUSE, without asking Scryfall again: a page
with a dozen symbols never queues a dozen slow failures behind the lock, and
Scryfall isn't asked again on every request while there's no saved list.

Only codes in Scryfall's list are fetched, and only from SVG_PREFIX (the
list's own svg_uri for that code), so the server never fetches an address a
request made up. Offline, a picture not cached yet answers 503 and the page
falls back to its lettered circles.
"""
import json
import re
import threading
import time
import urllib.error

from decklab.lib import cards, config

from . import common
from .common import ApiError, _public

SYMBOLOGY_URL = "https://api.scryfall.com/symbology"
SVG_PREFIX = "https://svgs.scryfall.io/card-symbols/"
CODE_RE = re.compile(r"[A-Z0-9]{1,12}")
SYMBOLS_DIR = config.DATA / "symbols"
LIST_NAME = "symbology.json"
RELIST_AFTER = 7 * 24 * 60 * 60     # seconds: how often an unknown code may ask Scryfall for the list again
MAX_SVG = 64 * 1024                 # bytes: Scryfall's symbols are 1-6 KB
NETWORK_PAUSE = 5 * 60              # seconds after a failed fetch before Scryfall is asked again
FETCH_TIMEOUT = 15                  # seconds a fetch from Scryfall may take

_lock = threading.Lock()
_codes = {}             # SYMBOLS_DIR -> {code: svg url}, read from LIST_NAME once
_asked = {}             # SYMBOLS_DIR -> time.monotonic() of the last fetch of the list this run
_failed = {}            # SYMBOLS_DIR -> time.monotonic() of the last fetch from Scryfall that failed


def _code_of(svg_uri):
    """The code of one of Scryfall's svg_uri addresses ("https://svgs.scryfall.io/card-symbols/WU.svg?..." -> "WU"),
    or None for an address somewhere else or a name that isn't a code."""
    if not isinstance(svg_uri, str) or not svg_uri.startswith(SVG_PREFIX):
        return None
    name = svg_uri[len(SVG_PREFIX):].split("?")[0]
    if not name.endswith(".svg") or not CODE_RE.fullmatch(name[:-4]):
        return None
    return name[:-4]


def _read_list(path):
    """{code: svg url} from a saved list, or None when there isn't a readable one."""
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    out = {}
    for symbol in saved.get("data", []) if isinstance(saved, dict) else []:
        code = _code_of(symbol.get("svg_uri") if isinstance(symbol, dict) else None)
        if code:
            out[code] = symbol["svg_uri"].split("?")[0]
    return out


def _fetch_list(folder):
    """Ask Scryfall for the list, save it, and return {code: svg url}. Network errors propagate."""
    _asked[folder] = time.monotonic()
    answer = cards._get_json(SYMBOLOGY_URL, timeout=FETCH_TIMEOUT)
    if not isinstance(answer, dict) or not isinstance(answer.get("data"), list):
        raise ValueError("Scryfall's symbol list wasn't in the expected shape")
    kept = [{"symbol": s.get("symbol"), "english": s.get("english"), "svg_uri": s.get("svg_uri")}
            for s in answer["data"] if isinstance(s, dict) and _code_of(s.get("svg_uri"))]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / LIST_NAME
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps({"data": kept}, indent=0), encoding="utf-8")
    tmp.replace(path)
    return _read_list(path) or {}


def _known(folder, code):
    """The svg url for code, from the saved list (fetched when there's none, or again when the code isn't in
    it and the list wasn't asked for within RELIST_AFTER). Call with _lock held."""
    if folder not in _codes:
        _codes[folder] = _read_list(folder / LIST_NAME)
    if _codes[folder] is None:
        _codes[folder] = _fetch_list(folder)
    elif code not in _codes[folder]:
        last = _asked.get(folder)
        if last is None or time.monotonic() - last > RELIST_AFTER:
            _codes[folder] = _fetch_list(folder)
    return _codes[folder].get(code)


def _looks_like_svg(data):
    head = data[:512].lstrip().lower()
    return head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:2048].lower())


def symbol_svg(name):
    """GET /sym/<name>: the bytes of a symbol's SVG (name is "<code>.svg"). ApiError 404 for a name that
    isn't a code or a code Scryfall doesn't have, 503 when Scryfall can't be reached and it isn't cached."""
    if not isinstance(name, str) or not name.endswith(".svg") or not CODE_RE.fullmatch(name[:-4]):
        raise ApiError(404, "No such symbol: use /sym/<code>.svg, such as /sym/WU.svg")
    code = name[:-4]
    folder = SYMBOLS_DIR
    path = folder / f"{code}.svg"
    try:
        return path.read_bytes()
    except FileNotFoundError:
        pass
    except OSError as e:
        common._log(f"Can't read the symbol cache's {path.name}: {type(e).__name__}: {e}")
        raise ApiError(500, "The symbol couldn't be read on the PC (the server log says why)") from None
    with _lock:
        try:
            if path.exists():               # another request fetched it meanwhile
                return path.read_bytes()
            failed = _failed.get(folder)
            if failed is not None and time.monotonic() - failed < NETWORK_PAUSE:
                raise ApiError(503, "Couldn't reach Scryfall for card symbols a moment ago; try again in a few minutes")
            url = _known(folder, code)
            if url is None:
                raise ApiError(404, f"Scryfall has no symbol {code}")
            folder.mkdir(parents=True, exist_ok=True)
            cards._download(url, path, accept="image/svg+xml", timeout=FETCH_TIMEOUT)
            data = path.read_bytes()
            if len(data) > MAX_SVG or not _looks_like_svg(data):
                path.unlink(missing_ok=True)
                raise ApiError(503, f"Scryfall's picture of {code} wasn't an SVG")
            return data
        except ApiError:
            raise
        except urllib.error.URLError as e:          # an HTTPError's filename is its URL: still the network
            _failed[folder] = time.monotonic()
            raise ApiError(503, f"Couldn't download the symbol from Scryfall: {_public(e)}") from None
        except OSError as e:
            if e.filename:      # the cache folder on the PC, not the network
                common._log(f"Can't save the symbol {code}: {type(e).__name__}: {e}")
                raise ApiError(500, "The symbol couldn't be saved on the PC (the server log says why)") from None
            _failed[folder] = time.monotonic()
            raise ApiError(503, f"Couldn't download the symbol from Scryfall: {_public(e)}") from None
        except cards.NETWORK_ERRORS as e:
            _failed[folder] = time.monotonic()
            raise ApiError(503, f"Couldn't download the symbol from Scryfall: {_public(e)}") from None
