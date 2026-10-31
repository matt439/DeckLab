"""What every shop adapter shares (E5-S08): the interface, robots.txt and one polite page fetch.

An adapter (mtgmate.py so far) says who a shop is, where its page of a card name is and how
to read that page into listings; it never fetches anything itself, so its parsing is tested on
saved pages (decklab/tests/fixtures/shops/<key>/). The package (__init__.py) asks the shop
through its Session, keeps the snapshot file and matches queue rows, the same for every shop.

A listing is {"set", "number", "finish", "price", "stock", "condition", "url"} (LISTING_FIELDS):
the lowercase set code, the collector number, a FINISHES value (else the shop's own word, or
"unknown"), the shop's own AUD price as "4.50" or None when it showed none, a whole number in
stock (0 when it showed none), the shop's condition words and the listing's page.
"""
import urllib.error
import urllib.request

from decklab.lib import config

USER_AGENT = config.USER_AGENT + " purchase-queue price check"
TIMEOUT = 30
MAX_PAGE = 5 * 1024 * 1024
FINISHES = {"nonfoil", "foil", "etched"}
LISTING_FIELDS = ("set", "number", "finish", "price", "stock", "condition", "url")


class ShopError(Exception):
    """A request or page that couldn't be read; its words are safe to show."""


class Disallowed(ShopError):
    """robots.txt disallows the path: nothing is fetched."""


class Adapter:
    """One shop. A subclass sets key (the snapshot file's stem, decklab/data/shops/<key>.json,
    and its lock's), name (shown on Shopping), site (https://..., no trailing slash) and
    robots_path, and gives name_url and parse_name_page. Both are pure: no network here."""

    key = ""
    name = ""
    site = ""
    robots_path = "/robots.txt"
    counts_stock = True                     # False: its pages say only available or not (stock 1 or 0)

    def robots_url(self):
        return self.site + self.robots_path

    def name_url(self, name):
        """The shop's page of every printing with this card name."""
        raise NotImplementedError

    def parse_name_page(self, text, name):
        """That page's listings of name (and its variants), sorted: [] when the shop has none,
        ShopError when the page isn't the one expected (the shop changed its pages)."""
        raise NotImplementedError


# --- robots.txt --------------------------------------------------------------------------

def robots_rules(text, agent="decklab"):
    """(disallowed path prefixes, allowed prefixes, crawl delay or None) for agent: every group
    naming "*" or the agent, merged (MTGMate's file has two "*" groups, and Python's
    urllib.robotparser keeps only the first, which would miss its Disallow and Crawl-delay)."""
    disallow, allow, delays = [], [], []
    agents, in_rules, applies = [], False, False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if in_rules:
                agents, in_rules = [], False
            agents.append(value.lower())
            applies = any(name == "*" or (name and name in agent.lower()) for name in agents)
            continue
        in_rules = True
        if not applies:
            continue
        if key == "disallow" and value:
            disallow.append(value)
        elif key == "allow" and value:
            allow.append(value)
        elif key == "crawl-delay":
            try:
                delays.append(float(value))
            except ValueError:
                pass
    return disallow, allow, (max(delays) if delays else None)


def allowed(path, rules):
    """True when robots.txt lets path be fetched: the longest matching rule wins, a Disallow on a tie."""
    disallow, allow, _ = rules
    longest_no = max((len(rule) for rule in disallow if path.startswith(rule)), default=-1)
    longest_yes = max((len(rule) for rule in allow if path.startswith(rule)), default=-1)
    return longest_no < 0 or longest_yes > longest_no


# --- fetching ----------------------------------------------------------------------------

def fetch_page(url, shop):
    """The page's text. ShopError, naming shop, for anything that isn't a page."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read(MAX_PAGE + 1)
    except urllib.error.HTTPError as error:
        raise ShopError(f"{shop} answered {error.code}") from None
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        reason = getattr(error, "reason", error)
        raise ShopError(f"{shop} couldn't be reached ({type(reason).__name__})") from None
    if len(body) > MAX_PAGE:
        raise ShopError(f"{shop}'s page was too big to read")
    return body.decode("utf-8", errors="replace")
