"""Games Portal's adapter (E5-S08): its search page for a card name and how to read it.

Games Portal is a Shopify shop whose robots.txt (checked 2026-10-31) disallows the cart,
checkout, account and sorted or filtered collection pages but not /search, and names no
Crawl-delay, so the Session keeps its own 60 seconds. The page is SEARCH_PATH + the name,
quoted whole, with type=product: the shop's own search results, ten products to a page and
fuzzy (other names come too), of which only the first page is read.

Each product on it is a card (<div class="product-card-list2 product-card-list2__ID">, whose
first /products/ link is its page) followed by a hidden <div id="productCardList2-js-ID">
whose data-product-variants is JSON: one variant a condition and finish, each with "name"
("Sol Ring (0212) [Marvel Super Heroes Commander] - Near Mint"), "public_title" ("Near Mint",
"Near Mint Foil"), "sku" (SET-NUMBER-LANGUAGE-FINISH-CONDITION, "MSC-212-EN-NF-1"),
"available" and "price" in cents, in AUD. The page says only whether a variant is available,
not how many, so a listing's stock is 1 (at least one) or 0. Saved pages:
decklab/tests/fixtures/shops/gamesportal/.
"""
import html.parser
import json
import re
import urllib.parse

from decklab.lib.shops.base import Adapter, ShopError

SHOP = "Games Portal"
SITE = "https://gamesportal.com.au"
SEARCH_PATH = "/search"                     # ?q=<the card name>&type=product
CARD_TYPE = "MTG Single"                    # data-product-type of a single card (sealed products aren't)
_CARD_CLASS = re.compile(r"\bproduct-card-list2__(\d+)\b")
_VARIANTS_ID = "productCardList2-js-"
_NO_RESULTS = re.compile(r"<title>\s*Search:\s*(?:0 results|No results)", re.IGNORECASE)
_SEARCH_PAGE = re.compile(r"<title>\s*Search:", re.IGNORECASE)


def name_url(name):
    return SITE + SEARCH_PATH + "?" + urllib.parse.urlencode({"q": name, "type": "product"}, quote_via=urllib.parse.quote)


class _Results(html.parser.HTMLParser):
    """Each product's page and its variants' JSON, as the search page lists them."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.card, self.pages, self.products = None, {}, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            found = _CARD_CLASS.search(attrs.get("class") or "")
            if found:
                self.card = found.group(1)
            ident = attrs.get("id") or ""
            if ident.startswith(_VARIANTS_ID) and "data-product-variants" in attrs:
                self.products.append((ident[len(_VARIANTS_ID):], attrs.get("data-product-type"),
                                      attrs.get("data-product-variants")))
        elif tag == "a" and self.card and self.card not in self.pages:
            href = attrs.get("href") or ""
            if href.startswith("/products/"):
                self.pages[self.card] = href.split("?", 1)[0]


def _card_name(title):
    """The card name in a product title: "Sol Ring (0212) [Marvel Super Heroes Commander]" is Sol Ring."""
    text = str(title or "").split(" [", 1)[0].strip()
    while text.endswith(")") and " (" in text:
        text = text[:text.rindex(" (")].rstrip()
    return text.casefold()


def _title(variant):
    """The product's title: the variant's name without " - <its public title>"."""
    name = str(variant.get("name") or "")
    suffix = " - " + str(variant.get("public_title") or "")
    return name[:-len(suffix)] if suffix != " - " and name.endswith(suffix) else name


def _sku(value):
    """(set, collector number, language) from a SKU like "NEO-141//141-EN-NF-1", else ("", "", "")."""
    parts = str(value or "").split("-")
    if len(parts) < 5 or not parts[0]:
        return "", "", ""
    head = parts[:-3]
    numbers = [part for part in head[1:] if part[:1].isdigit()]
    number = (numbers[-1] if numbers else head[1] if len(head) > 1 else "").split("//", 1)[0]
    return head[0].lower(), number, parts[-3].upper()


def _finish(words):
    """(finish, condition) from a public title like "Near Mint Foil" or "Near Mint Foil Etched"."""
    text = str(words or "").strip()
    for ending, finish in ((" Foil Etched", "etched"), (" Etched Foil", "etched"), (" Etched", "etched"),
                           (" Foil", "foil")):
        if text.endswith(ending):
            return finish, text[:-len(ending)].strip()
    return "nonfoil", text


def _price(cents):
    if isinstance(cents, bool) or not isinstance(cents, int) or cents < 0:
        return None
    return f"{cents / 100:.2f}"


def parse_name_page(text, name):
    """The listings of name on Games Portal's search page for it: [] when none of its products is
    that card. ShopError when the page isn't the one expected (Games Portal changed its pages)."""
    if _NO_RESULTS.search(text):
        return []
    parser = _Results()
    parser.feed(text)
    if not _SEARCH_PAGE.search(text) or not parser.products:
        raise ShopError(f"{SHOP}'s page for {name} didn't have its usual product data")
    wanted = {name.casefold(), name.split(" // ", 1)[0].casefold()}
    listings = []
    for product, kind, raw in parser.products:
        try:
            variants = json.loads(raw)
            if not isinstance(variants, list):
                raise TypeError
        except (ValueError, TypeError):
            raise ShopError(f"{SHOP}'s product data for {name} couldn't be read") from None
        if kind is not None and kind != CARD_TYPE:
            continue
        page = SITE + parser.pages[product] if product in parser.pages else name_url(name)
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            title = _title(variant)
            if title.split(" [", 1)[0].strip().casefold() not in wanted and _card_name(title) not in wanted:
                continue
            set_code, number, language = _sku(variant.get("sku"))
            finish, condition = _finish(variant.get("public_title"))
            if language and language != "EN":
                condition = f"{condition}, {language}" if condition else language
            ident = variant.get("id")
            listings.append({
                "set": set_code, "number": number, "finish": finish, "price": _price(variant.get("price")),
                "stock": 1 if variant.get("available") is True else 0, "condition": condition,
                "url": f"{page}?variant={ident}" if isinstance(ident, int) and page != name_url(name) else page})
    listings.sort(key=lambda item: (item["set"], item["number"], item["finish"], item["condition"]))
    return listings


class GamesPortal(Adapter):
    key, name, site = "gamesportal", SHOP, SITE

    def name_url(self, name):
        return name_url(name)

    def parse_name_page(self, text, name):
        return parse_name_page(text, name)


ADAPTER = GamesPortal()
