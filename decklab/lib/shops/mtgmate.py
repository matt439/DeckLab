"""MTGMate's adapter (E5-S08): its page of a card name and how to read it.

The page is NAME_PATH + the name, quoted whole ("Sol%20Ring"), the same page its card links
lead to, never its search (robots.txt disallows /cards/search). Its listings are the props of
a FilterableTable element, JSON whose "uuid" holds one entry a printing, finish and condition;
prices are in cents, in AUD. Saved pages: decklab/tests/fixtures/shops/mtgmate/.
"""
import html.parser
import json
import urllib.parse

from decklab.lib.shops.base import FINISHES, Adapter, ShopError

SHOP = "MTGMate"
SITE = "https://www.mtgmate.com.au"
NAME_PATH = "/cards/"                       # + the card name, quoted whole ("Sol%20Ring")


def name_url(name):
    return SITE + NAME_PATH + urllib.parse.quote(name, safe="")


class _Table(html.parser.HTMLParser):
    """The props of MTGMate's FilterableTable: the listings the name page shows."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.props = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.props is None and attrs.get("data-react-class") == "FilterableTable":
            self.props = attrs.get("data-react-props")


def _number(link_path):
    """The collector number in a link like /cards/Sol_Ring/C16/272 (or .../887:foil)."""
    if not isinstance(link_path, str):
        return ""
    last = link_path.rstrip("/").rsplit("/", 1)[-1]
    return urllib.parse.unquote(last.split(":", 1)[0])


def _price(cents):
    if isinstance(cents, bool) or not isinstance(cents, int) or cents < 0:
        return None
    return f"{cents / 100:.2f}"


def _base_name(value):
    """MTGMate's name without its variant label: "Sol Ring (Borderless 1011)" is Sol Ring."""
    text = str(value or "").strip()
    if text.endswith(")") and " (" in text:
        text = text[:text.rindex(" (")]
    return text.casefold()


def parse_name_page(text, name):
    """The listings on MTGMate's page of a name: [] when the page has none (no such card there).
    ShopError when the page isn't the one expected (MTGMate changed its pages)."""
    if "No matches for" in text and "FilterableTable" not in text:
        return []
    parser = _Table()
    parser.feed(text)
    if parser.props is None:
        raise ShopError(f"{SHOP}'s page for {name} didn't have its usual card table")
    try:
        props = json.loads(parser.props)
        entries = props["uuid"].values()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ShopError(f"{SHOP}'s card table for {name} couldn't be read") from None
    wanted = {name.casefold(), name.split(" // ", 1)[0].casefold()}
    listings = []
    for entry in entries:
        if not isinstance(entry, dict) or (str(entry.get("name", "")).strip().casefold() not in wanted
                                           and _base_name(entry.get("name")) not in wanted):
            continue
        finish = str(entry.get("finish", "")).lower()
        stock = entry.get("quantity")
        link = entry.get("link_path")
        listings.append({
            "set": str(entry.get("set_code", "")).lower(), "number": _number(link),
            "finish": finish if finish in FINISHES else finish or "unknown",
            "price": _price(entry.get("price")),
            "stock": stock if isinstance(stock, int) and not isinstance(stock, bool) and stock >= 0 else 0,
            "condition": str(entry.get("condition") or ""),
            "url": SITE + link if isinstance(link, str) and link.startswith("/cards/") else name_url(name)})
    listings.sort(key=lambda item: (item["set"], item["number"], item["finish"], item["condition"]))
    return listings


class MTGMate(Adapter):
    key, name, site = "mtgmate", SHOP, SITE

    def name_url(self, name):
        return name_url(name)

    def parse_name_page(self, text, name):
        return parse_name_page(text, name)


ADAPTER = MTGMate()
