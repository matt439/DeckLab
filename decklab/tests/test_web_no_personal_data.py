"""The page's code holds no household names, deck titles or results (E10-S39).

Every file Deck Lab serves from web/ (server_http.static_files: the scripts, stylesheets, the page,
the manifest and the icons) is read by anyone signed in, a member such as User5 too, so its examples
and comments use neutral names ("Alex", "Sam", "Jordan") and decks ("Boros Burn", "Krenko, Mob
Boss: Goblin Horde"). This test fails on any configured profile's id, name or email, and on any of
the household's real deck titles, matched case-insensitively as whole words, except the stand-in
names (NEUTRAL_NAMES): a config.json made from config.example.json names "Alex", and one with the
docs' stand-ins names "User1", which the page's examples use on purpose, so a local config.json never
fails the test on them. The titles come from the
test fixtures' deck files, the decks as the git tag pre-db-decks holds them, a database export when
one is named (DECKLAB_DECK_EXPORT: a `deck pull --all -o DIR` or `inventory export DIR` folder, read
for every deck text's `# ` title), and the list below, which keeps titles none of those hold (a deck
made since the move, a deleted one). No database, no server, no network beyond reading git.
"""
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from decklab.lib.config import CONFIG_FILE
from decklab.lib.server_http import WEB_DIR, static_files

# The household's deck titles, every one the decks' history has held (2026-10-18), and the parts a
# page would show of them on their own: a Commander deck's commander and its theme. The fixtures, the
# pre-db-decks tag and an export add theirs (deck_titles_found()); this list is the floor for titles
# none of them holds. This file is a test: it is never served.
DECK_TITLES = (
    "Alela, Cunning Conqueror: Faeries on Your Turn",
    "Aragorn's Heroes",
    "Finneas, Ace Archer: Rabbits, Tokens and Counters",
    "Gandalf and the Valley",
    "Ghalta: Tramplesaurus Rex",
    "Ghoulcaller Gisa: Wretched Ranks (upgraded)",
    "Giada, Font of Hope: Calling All Angels (upgraded)",
    "Gruul Ramp",
    "Izzet Otters",
    "Izzet Prowess",
    "Lathliss: Reign of Dragons",
    "Mono-Black Midrange",
    "Mono-Black Zombies",
    "Mono-White Angels",
    "Orzhov Removal Midrange",
    "Orzhov Vampires",
    "Sai: Keen Engineering",
    "Selesnya Rabbits",
    "The Free Peoples",
    "Vader and Ani",
    "Yoshimaru, Ever Faithful: Vader and Ani",
)

# Other examples taken from the household's records: real order ids' topics and the commanders'
# short names, which the page shows on their own ("Giada" for a Commander deck's chip).
OTHER_TERMS = ("Giada", "Gisa", "Ghalta", "Lathliss", "Alela", "Finneas", "Yoshimaru", "Krobus", "roningames",
               "a-flicker-in-the-deep", "Hare Raising")

# The made-up names the page's examples use (the docstring's) and the repo's stand-ins for the household
# (AGENTS.md: user1 to user5). A profile may carry one (config.example.json's "alex"), but none is
# anyone's personal data, so profile_terms() leaves them out.
NEUTRAL_NAMES = ("Alex", "Sam", "Jordan", "User1", "User2", "User3", "User4", "User5")

# (served path, term) pairs that may stay, each with its reason. Keep it small.
ALLOWED = {
    # "user" and "wife" are plays_as values, not names, so nothing needs listing for them; nothing else is
    # allowed today.
}


REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXPORT_ENV = "DECKLAB_DECK_EXPORT"
_TITLE = re.compile(r"^# (.+?)\s*$", re.MULTILINE)


def title_of(text):
    """A deck text's title: its first `# ` line, only for a text with a `## Decklist` heading."""
    if not re.search(r"^## Decklist\s*$", text, re.MULTILINE):
        return None
    match = _TITLE.search(text)
    return match.group(1) if match else None


def titles_in_folder(folder):
    """Every deck text's title under folder (any depth), such as the fixtures or an export."""
    titles = set()
    for path in sorted(Path(folder).rglob("*.md")):
        try:
            title = title_of(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError):
            continue
        if title:
            titles.add(title)
    return titles


def titles_in_tag(tag="pre-db-decks", repo=REPO):
    """Every deck file's title as git's tag holds it (empty when git or the tag isn't there)."""
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout
    try:
        names = git("ls-tree", "-r", "--name-only", tag, "--", "magic").decode("utf-8").splitlines()
    except (OSError, subprocess.CalledProcessError):
        return set()
    titles = set()
    for name in names:
        if name.endswith(".md") and "/decks/" in name:
            try:
                title = title_of(git("show", f"{tag}:{name}").decode("utf-8-sig"))
            except (OSError, subprocess.CalledProcessError, UnicodeDecodeError):
                continue
            if title:
                titles.add(title)
    return titles


def deck_titles_found(environ=os.environ):
    """The list above, the fixtures' deck titles, pre-db-decks' and, when named, an export's."""
    titles = set(DECK_TITLES) | titles_in_folder(FIXTURES) | titles_in_tag()
    export = environ.get(EXPORT_ENV)
    if export and Path(export).is_dir():
        titles |= titles_in_folder(export)
    return titles


def deck_title_terms(titles=DECK_TITLES):
    """Each title, and for "Commander, Epithet: Theme (upgraded)" its commander part and its theme too."""
    terms = set()
    for title in titles:
        terms.add(title)
        bare = re.sub(r"\s*\([^)]*\)\s*$", "", title)
        terms.add(bare)
        if ":" in bare:
            head, theme = (part.strip() for part in bare.split(":", 1))
            terms.update((head, theme))
    return terms


def profile_terms(config_file=CONFIG_FILE, neutral=NEUTRAL_NAMES):
    """Every configured profile's id, name, display name and emails (decklab/config.json, not the
    DECKLAB_CONFIG_EXTRA overlay), but for the stand-in names (NEUTRAL_NAMES)."""
    try:
        config = json.loads(Path(config_file).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    terms = set()
    for profile in config.get("profiles") or []:
        for key in ("id", "name", "display_name", "space"):
            if isinstance(profile.get(key), str) and profile[key] != "home":
                terms.add(profile[key])
        terms.update(e for e in profile.get("emails") or () if isinstance(e, str))
    neutral = {name.lower() for name in neutral}
    return {t.strip() for t in terms if t and t.strip() and t.strip().lower() not in neutral}


def _pattern(term):
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.IGNORECASE)


def hits(files, terms, allowed=ALLOWED):
    """[(served path, line number, term)] for each term found in each served file's text (binary files are
    read as Latin-1, so a name in a PNG's text chunk shows too)."""
    patterns = [(term, _pattern(term)) for term in sorted(terms, key=str.lower)]
    found = []
    for url, path in sorted(files.items()):
        if url == "/":                                   # the same file as /index.html
            continue
        data = Path(path).read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        for number, line in enumerate(text.splitlines(), 1):
            for term, pattern in patterns:
                if pattern.search(line) and (url, term) not in allowed:
                    found.append((url, number, term))
    return found


class NoPersonalDataTests(unittest.TestCase):

    def test_served_files_name_no_profile_or_deck(self):
        files = static_files(WEB_DIR)
        self.assertIn("/core.js", files)                 # the real web/, not an empty folder
        terms = profile_terms() | deck_title_terms(deck_titles_found()) | set(OTHER_TERMS)
        self.assertTrue(profile_terms(neutral=()) or not Path(CONFIG_FILE).exists())    # a config.json is read
        found = hits(files, terms)
        self.assertEqual(found, [], "Use neutral names and decks in web/ (E10-S39): "
                         + "; ".join(f"{url}:{line} {term!r}" for url, line, term in found))

    def test_a_new_real_example_fails(self):
        # The check itself: a comment naming a profile or a deck is found, whole words only, any case.
        with tempfile.TemporaryDirectory() as tmp:
            web = Path(tmp)
            (web / "icons").mkdir()
            (web / "a.js").write_text('/** "user1 changed the list" */\nconst x = 1;\n', encoding="utf-8")
            (web / "b.css").write_text("/* Gruul Ramp's colours */\n.pattern { color: red; }\n", encoding="utf-8")
            (web / "c.js").write_text("// Sai\n", encoding="utf-8")
            (web / "icons" / "i.png").write_bytes(b"\x89PNG\r\n\x1a\ntEXtAuthor\x00Matt\x00")
            terms = {"User1", "User5", "Matt"} | deck_title_terms()
            self.assertEqual(hits(static_files(web), terms), [
                ("/a.js", 1, "User1"), ("/b.css", 1, "Gruul Ramp"), ("/c.js", 1, "Sai"), ("/icons/i.png", 3, "Matt")])
            # "pattern" holds "user5" but not as a word; an allowed pair is skipped.
            self.assertEqual(hits(static_files(web), {"User1"}, allowed={("/a.js", "User1")}), [])

    def test_stand_in_profile_names_are_not_terms(self):
        # A local config.json made from config.example.json (Alex) or with the docs' stand-ins (User1)
        # adds no term; a real name, display name, space and email still do.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"profiles": [
                {"id": "alex", "name": "Alex", "space": "home", "emails": []},
                {"id": "user1", "name": "User1", "space": "home", "emails": ["user1@example.com"]},
                {"id": "robin", "name": "Robin", "display_name": "Rob", "space": "robin",
                 "emails": ["robin@example.com"]},
            ]}), encoding="utf-8")
            self.assertEqual(profile_terms(path),
                             {"user1@example.com", "robin", "Robin", "Rob", "robin@example.com"})
            self.assertIn("Alex", profile_terms(path, neutral=()))
        self.assertEqual(profile_terms(Path(tmp) / "missing.json"), set())

    def test_titles_come_from_fixtures_the_tag_and_an_export(self):
        found = deck_titles_found(environ={})
        fixtures = titles_in_folder(FIXTURES)
        self.assertIn("Gruul Ramp", fixtures)                   # a fixture deck file
        self.assertTrue(fixtures <= found)
        self.assertTrue(titles_in_tag() <= found)
        with tempfile.TemporaryDirectory() as tmp:
            deck = Path(tmp) / "user5" / "commander" / "atraxa.md"
            deck.parent.mkdir(parents=True)
            deck.write_text("# Atraxa Superfriends\n\n- **Status:** idea\n\n## Decklist\n\n```\nDeck\n```\n",
                            encoding="utf-8")
            (Path(tmp) / "notes.md").write_text("# Not a deck\n", encoding="utf-8")
            exported = deck_titles_found(environ={EXPORT_ENV: tmp})
            self.assertIn("Atraxa Superfriends", exported)       # a deck made since, from the export
            self.assertNotIn("Not a deck", exported)             # only deck texts count
            web = Path(tmp) / "web"
            web.mkdir()
            (web / "deck.js").write_text("// e.g. Atraxa Superfriends\n", encoding="utf-8")
            self.assertEqual(hits(static_files(web), deck_title_terms(exported)),
                             [("/deck.js", 1, "Atraxa Superfriends")])

    def test_title_parts(self):
        terms = deck_title_terms(("Giada, Font of Hope: Calling All Angels (upgraded)", "Gruul Ramp"))
        self.assertEqual(terms, {"Giada, Font of Hope: Calling All Angels (upgraded)",
                                 "Giada, Font of Hope: Calling All Angels", "Giada, Font of Hope",
                                 "Calling All Angels", "Gruul Ramp"})


if __name__ == "__main__":
    unittest.main()
