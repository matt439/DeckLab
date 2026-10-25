"""What a row's details text says (parse_details): P/T, colours, keywords,
what it lacks and what isn't known; and the parts it doesn't read that look
like mistakes (details_mistakes). Part of decklab.lib.tokens (see its
docstring). _kw_cache is rebound while running, so it lives only here."""
import re
from dataclasses import dataclass, field

from .names import _index

# The keywords a details segment may list; every keyword of a token in the
# card index is added when the index is ready (see _keywords).
KEYWORDS = frozenset({
    "flying", "first strike", "double strike", "deathtouch", "lifelink", "trample", "haste",
    "vigilance", "reach", "menace", "defender", "decayed", "hexproof", "indestructible", "ward",
    "prowess", "toxic"})
COLOUR_WORDS = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
_COLOUR_ORDER = list(COLOUR_WORDS.values())
# ASCII digits and word edges only, as the page's TOK_PT and TOK_UNKNOWN read them: "４/４" is kept, not read.
_PT_RE = re.compile(r"^([0-9]+|\*|x)/([0-9]+|\*|x)$", re.IGNORECASE)
_UNKNOWN_RE = re.compile(r"\b(?:unconfirmed|unknown|unspecified)\b", re.IGNORECASE | re.ASCII)


@dataclass
class Facts:
    """What a details string says (parse_details). None is "not recorded"."""
    pt: str | None = None
    colors: set | None = None         # colour words; the empty set is colourless
    has: set = field(default_factory=set)
    lacks: set = field(default_factory=set)
    unknown: set = field(default_factory=set)   # "pt", "colors", "keywords"
    extra: list = field(default_factory=list)



# ------------------------------------------------------------------ details

_kw_cache = (None, KEYWORDS)


def _keywords():
    """KEYWORDS plus every keyword of a token in the card index (lower case)."""
    global _kw_cache
    try:
        data = _index().data
    except RuntimeError:
        return KEYWORDS
    if _kw_cache[0] is not data:
        found = {k.lower() for entry in data.get("tokens", {}).values() if entry["kind"] == "token"
                 for k in entry.get("keywords", [])}
        _kw_cache = (data, KEYWORDS | found)
    return _kw_cache[1]


def _keyword(item, words):
    """The keyword an item names ("ward {2}" -> "ward"), or None."""
    item = " ".join(item.split()).lower()
    if item in words:
        return item
    m = re.fullmatch(r"(.+?)\s+(?:[0-9]+|x|\{[^}]*\})+", item)
    return m.group(1) if m and m.group(1) in words else None


def _colours(segment):
    """The set of colour words a segment is made of, or None if it isn't one."""
    words = [w for w in re.split(r"\s*,\s*|\s+and\s+|\s+", segment.lower()) if w]
    if words in (["colourless"], ["colorless"]):
        return set()
    if words and all(w in _COLOUR_ORDER for w in words):
        return set(words)
    return None


def parse_details(text):
    """The Facts a details string records. Segments are split on ";" and
    matched ignoring case: "1/1" (P/T), colour words ("green", "red and
    white", "colourless"), a list of keywords ("flying, deathtouch"), "no
    <keyword>", and anything saying unconfirmed, unknown or unspecified,
    which marks the aspects it names (power/toughness, colour, abilities;
    all three if none) unknown. Anything else (type lines, rules text, a
    printed colour that isn't a Magic one) goes to extra and is never compared."""
    facts = Facts()
    words = _keywords()
    for segment in (s.strip() for s in (text or "").split(";")):
        if not segment:
            continue
        low = segment.lower()
        if _PT_RE.match(segment):
            facts.pt = segment.upper()
            continue
        if _UNKNOWN_RE.search(segment):
            aspects = set()
            if re.search(r"power|toughness|\bp/t\b", low, re.ASCII):
                aspects.add("pt")
            if re.search(r"colou?r", low):
                aspects.add("colors")
            if re.search(r"abilit|keyword", low):
                aspects.add("keywords")
            if not aspects and re.search(r"printing|set|art", low):
                facts.extra.append(segment)
                continue
            facts.unknown |= aspects or {"pt", "colors", "keywords"}
            continue
        colours = _colours(segment)
        if colours is not None:
            facts.colors = colours
            continue
        items = [i.strip() for i in segment.split(",") if i.strip()]
        has, lacks = set(), set()
        for item in items:
            m = re.fullmatch(r"no\s+(.+)", item, re.IGNORECASE)
            keyword = _keyword(m.group(1) if m else item, words)
            if keyword is None:
                break
            (lacks if m else has).add(keyword)
        else:
            if items:
                facts.has |= has
                facts.lacks |= lacks
                continue
        facts.extra.append(segment)
    return facts


# ------------------------------------------------------------------ likely mistakes

# Words that are never a typo for a colour or keyword: they're the words of type
# lines and notes ("Card" is one letter from ward, "blank" from black). Every word
# of a token face's name is added when the index is ready (see _plain_words):
# "Clue" isn't blue.
_PLAIN_WORDS = frozenset({
    "card", "token", "emblem", "creature", "artifact", "enchantment", "land", "legendary", "equipment",
    "vehicle", "printed", "side", "front", "back", "word", "words", "hard", "glue", "clue", "blank", "while",
    "write", "waste", "each", "warm"})
_WORD_RE = re.compile(r"[^\s,]+")
_PUNCT = ".:;()\"'"
_face_cache = (None, frozenset())


@dataclass
class Mistake:
    """A details part parse_details doesn't read that looks like a mistake
    (details_mistakes). rewrite is what the part was most likely meant to
    say ("4/4; white; flying"), or None when some of it isn't understood."""
    part: str
    message: str
    rewrite: str | None = None


def _plain_words():
    """_PLAIN_WORDS plus every word of a token face name in the card index."""
    global _face_cache
    try:
        data = _index().data
    except RuntimeError:
        return _PLAIN_WORDS
    if _face_cache[0] is not data:
        found = {w.strip(_PUNCT).lower() for entry in data.get("tokens", {}).values()
                 for name in entry.get("face_names", []) for w in name.split()}
        _face_cache = (data, _PLAIN_WORDS | found)
    return _face_cache[1]


def _distance(a, b):
    """The edits (insert, delete, change, swap two neighbours) that turn a into b."""
    rows = [list(range(len(b) + 1))]
    for i, ca in enumerate(a, 1):
        row = [i]
        for j, cb in enumerate(b, 1):
            row.append(min(rows[-1][j] + 1, row[j - 1] + 1, rows[-1][j - 1] + (ca != cb)))
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                row[j] = min(row[j], rows[-2][j - 2] + 1)
        rows.append(row)
    return rows[-1][-1]


_KEYWORD_WORDS = sorted({w for k in KEYWORDS for w in k.split()})   # "first", "strike", ...


def _near(word, plain):
    """The colour or keyword word a word is a likely typo of ("whte" -> "white"),
    or None: one edit for words of 4-5 letters, two for longer ones."""
    if len(word) < 4 or word in plain or not word.isalpha():
        return None
    limit = 1 if len(word) <= 5 else 2
    best = min(_COLOUR_ORDER + ["colourless"] + _KEYWORD_WORDS, key=lambda t: _distance(word, t))
    return best if 0 < _distance(word, best) <= limit else None


def _read_words(words, keywords):
    """What a run of words says, read one item at a time: [(kind, text)] with
    kind "pt", "colour", "keyword", "lacks" or None (not understood)."""
    out, i = [], 0
    while i < len(words):
        word = words[i]
        if _PT_RE.match(word):
            out.append(("pt", word.upper()))
            i += 1
            continue
        if word in ("colourless", "colorless"):
            out.append(("colour", "colourless"))
            i += 1
            continue
        if all(w in _COLOUR_ORDER for w in word.split("-")):     # "white-blue"
            out.extend(("colour", w) for w in word.split("-"))
            i += 1
            continue
        lacks = word == "no" and i + 1 < len(words)
        start = i + 1 if lacks else i
        for size in (3, 2, 1):      # the longest keyword first: "first strike", "ward {2}"
            keyword = _keyword(" ".join(words[start:start + size]), keywords) if start + size <= len(words) else None
            if keyword:
                out.append(("lacks" if lacks else "keyword", " ".join(words[start:start + size])))
                i = start + size
                break
        else:
            out.append((None, word))
            i += 1
    return out


def _canonical(items):
    """The details a list of understood items is written as: P/T, then the
    colours joined with "and" in WUBRG order, then the keywords comma-joined
    (as tokSplitDescription in web/tokens.js writes them); None when the
    items can't be one row's details (two P/Ts, colourless with a colour)."""
    pts = [text for kind, text in items if kind == "pt"]
    colours = {text for kind, text in items if kind == "colour"}
    if len(pts) > 1 or ("colourless" in colours and len(colours) > 1):
        return None
    keywords = list(dict.fromkeys(("no " if kind == "lacks" else "") + text
                                  for kind, text in items if kind in ("keyword", "lacks")))
    colour_text = " and ".join(c for c in ["colourless"] + _COLOUR_ORDER if c in colours)
    return "; ".join(filter(None, [pts[0] if pts else "", colour_text, ", ".join(keywords)]))


def details_mistakes(text):
    """The parts of a details string that parse_details doesn't read and
    that look like mistakes rather than notes, as Mistakes:
    - a part whose words are mostly a P/T, colours or keywords, missing its
      ";" ("4/4 white flying", "white, flying"): "separate them with ';'";
    - a part whose every word is understood or one or two letters off a
      colour or keyword ("whte", "4/4 flyng"): "did you mean white?".
    Type lines, rules text and notes such as "printed pink" are left alone:
    most of their words are neither. The JS side (web/tokens.js) keeps the
    same rules."""
    keywords, plain = _keywords(), _plain_words()
    found = []
    for part in (s.strip() for s in (text or "").split(";")):
        if not part or _UNKNOWN_RE.search(part) or not parse_details(part).extra:
            continue
        words = [w for w in (m.group().strip(_PUNCT).lower() for m in _WORD_RE.finditer(part))
                 if w and w not in ("and", "—", "-", "–")]
        items = _read_words(words, keywords)
        # Each word not understood: its likely fix, itself when it's part of a
        # keyword ("strike" in "frist strike"), or None.
        fixes = [None if kind else _near(text, plain) or (text if text in _KEYWORD_WORDS else None)
                 for kind, text in items]
        # A "no" before a keyword's typo ("no flyng") is understood: it's "no flying".
        fixes = [text if not kind and text == "no" and k + 1 < len(items) and fixes[k + 1] in _KEYWORD_WORDS
                 else fix for k, ((kind, text), fix) in enumerate(zip(items, fixes))]
        typos = [fix for (kind, text), fix in zip(items, fixes) if fix and fix != text]
        known = sum(1 for kind, _ in items if kind)
        unknown = sum(1 for (kind, _), fix in zip(items, fixes) if not kind and not fix)
        again = _read_words(" ".join(fix or text for (_, text), fix in zip(items, fixes)).split(), keywords)
        if typos and not unknown and all(kind for kind, _ in again):
            # Only when the fixes make colours and keywords ("frist" alone isn't one).
            rewrite = _canonical(again)
            found.append(Mistake(part, f"did you mean {rewrite or ' and '.join(typos)}?", rewrite))
        elif known and known > len(items) - known:
            rewrite = _canonical(items) if known == len(items) else None
            found.append(Mistake(part, _separate(rewrite), rewrite))
    return found


def _separate(rewrite):
    """What a part missing its separators is told: "separate them with ';' (4/4;
    white)", "list them with commas (flying, trample)" or "write it as 4/4"."""
    if rewrite is None or ";" in rewrite:
        return "separate them with ';'" + (f" ({rewrite})" if rewrite else "")
    return f"list them with commas ({rewrite})" if "," in rewrite else f"write it as {rewrite}"
