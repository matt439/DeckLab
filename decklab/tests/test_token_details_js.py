"""The page's details reader (tokReadDetails in decklab/web/tokens.js) reads a token card's details as the
server does (parse_details in lib/tokens/details.py), and its advice (tokDetailsAdvice) warns about likely
mistakes, offers the canonical rewrite, and leaves legitimate extras (type lines, rules text, a printed
colour that isn't a Magic one) as kept but not compared. Runs the real script in Node; no DOM is needed."""
import json
import subprocess
import unittest
from unittest import mock

from decklab.lib.tokens import details
from decklab.tests.test_workspace_ui import NODE, WEB

SAMPLES = [
    "", "4/4; white; flying", "4/4; White; Flying", "4/4 white flying", "white 4/4, flying", "4/4; whte; flyng",
    "1/1; green; flying, deathtouch", "1/1; flying; no deathtouch", "2/2; green and blue; ward {2}",
    "*/*; colourless", "x/1; colorless", "red, white", "toxic 1; menace", "colour unconfirmed",
    "P/T unknown; abilities unspecified", "printing unconfirmed", "single-sided verified",
    "Token Creature — Phyrexian Beast", "1/1; printed pink (not a Magic colour)",
    "When this creature dies, draw a card", "0/1; defender; ;", ", ", "first strike, double strike",
    "frist strike", "no flyng, haste", "4/4 whte flyng", "white, flying", "Token Creature — White Angel 4/4 flying",
    "Card back is blank", "1/1 green-blue trample", "deathtuch", "Clue",
    "blank", "while", "write", "waste", "each", "warm", "no deathtuch", "1/1; no flyng", "no frist strike",
    "flying trample", "4/4.", "frist", "４/４", "Flying ４/４ wite", "white; red flying",
    "4/4; 2/2 green", "2/2; ward {2}; whte", "flying; no flyng", "4/4; 4/4 whte", "Token Creature — Angel; 4/4 wite fying",
    "Changeling", "4/4 changeling",
]
# The keywords the server adds from the card index when it's ready (a few of them), which the page
# is sent as the GET's "keywords".
LIVE_KEYWORDS = sorted(details.KEYWORDS | {"changeling", "islandwalk", "flanking"})

# Runs the page's reader over the samples and prints what it read, as JSON.
SCRIPT = """
const fs = require("fs"), vm = require("vm");
const [web, samples, keywords] = JSON.parse(fs.readFileSync(0, "utf8"));
const context = {};
vm.createContext(context);
vm.runInContext(fs.readFileSync(web + "/tokens.js", "utf8"), context);
const read = vm.runInContext("tokReadDetails", context), advise = vm.runInContext("tokDetailsAdvice", context);
const mistakes = vm.runInContext("tokDetailsMistakes", context);
const words = keywords || undefined;
process.stdout.write(JSON.stringify(samples.map((text) => ({ facts: read(text, words), advice: advise(text, words),
  mistakes: mistakes(text, words) }))));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class TokenDetailsParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = dict(zip(SAMPLES, cls.run_page(None)))
        cls.live = dict(zip(SAMPLES, cls.run_page(LIVE_KEYWORDS)))

    @staticmethod
    def run_page(keywords):
        result = subprocess.run([NODE, "-e", SCRIPT], input=json.dumps([str(WEB), SAMPLES, keywords]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        if result.returncode:
            raise AssertionError(result.stderr)
        return json.loads(result.stdout)

    def test_the_page_reads_details_as_the_server_does(self):
        # The fixed keyword list both sides start from, and the card index's the page is sent when it's ready.
        for keywords, page in ((details.KEYWORDS, self.js), (frozenset(LIVE_KEYWORDS), self.live)):
            with mock.patch.object(details, "_keywords", return_value=keywords):
                self.compare_facts(page)

    def compare_facts(self, page):
        """Each sample read by the page (page) as parse_details reads it."""
        for text in SAMPLES:
            with self.subTest(text=text):
                py, js = details.parse_details(text), page[text]["facts"]
                self.assertEqual(js["pt"], py.pt)
                self.assertEqual(None if js["colours"] is None else set(js["colours"]), py.colors)
                self.assertEqual(set(js["has"]), py.has)
                self.assertEqual(set(js["lacks"]), py.lacks)
                self.assertEqual(set(js["unknown"]), py.unknown)
                self.assertEqual(js["extra"], py.extra)

    def test_the_page_finds_the_mistakes_the_server_finds(self):
        for keywords, page in ((details.KEYWORDS, self.js), (frozenset(LIVE_KEYWORDS), self.live)):
            with mock.patch.object(details, "_keywords", return_value=keywords),                     mock.patch.object(details, "_plain_words", return_value=details._PLAIN_WORDS):
                for text in SAMPLES:
                    with self.subTest(text=text, live=page is self.live):
                        py = [{"part": m.part, "message": m.message, "rewrite": m.rewrite}
                              for m in details.details_mistakes(text)]
                        self.assertEqual(page[text]["mistakes"], py)

    def test_the_index_keywords_the_page_is_sent_are_read(self):
        self.assertEqual(self.js["Changeling"]["facts"]["extra"], ["Changeling"])
        self.assertEqual(self.live["Changeling"]["facts"]["has"], ["changeling"])
        self.assertEqual(self.live["4/4 changeling"]["advice"]["fix"], "4/4; changeling")
        self.assertEqual(self.js["4/4 changeling"]["advice"]["fix"], None)

    def test_the_fix_keeps_what_was_already_read(self):
        # A rewrite's colour or P/T joins the facts already read rather than replacing them.
        self.assertEqual(self.js["white; red flying"]["advice"]["fix"], "white and red; flying")
        self.assertIsNone(self.js["4/4; 2/2 green"]["advice"]["fix"])          # two P/Ts: no fix
        self.assertEqual(self.js["4/4; 4/4 whte"]["advice"]["fix"], "4/4; white")
        self.assertEqual(self.js["2/2; ward {2}; whte"]["advice"]["fix"], "2/2; white; ward {2}")
        self.assertIsNone(self.js["flying; no flyng"]["advice"]["fix"])        # has and lacks flying
        self.assertEqual(self.js["Token Creature — Angel; 4/4 wite fying"]["advice"]["fix"],
                         "Token Creature — Angel; 4/4; white; flying")
        for text in ("white; red flying", "4/4; 4/4 whte", "2/2; ward {2}; whte"):
            with self.subTest(text=text):
                fixed = self.js[text]["advice"]["fix"]
                self.assertEqual(details.details_mistakes(fixed), [])
                self.assertEqual(details.parse_details(fixed).extra, [])

    def test_wording_and_near_misses(self):
        for text in ("blank", "while", "write", "waste", "each", "warm", "frist", "４/４"):
            with self.subTest(text=text):
                self.assertEqual(self.js[text]["mistakes"], [])
                self.assertIsNone(self.js[text]["advice"]["fix"])
        messages = {
            "flying trample": ("list them with commas (flying, trample)", "flying, trample"),
            "4/4.": ("write it as 4/4", "4/4"),
            "no deathtuch": ("did you mean no deathtouch?", "no deathtouch"),
            "1/1; no flyng": ("did you mean no flying?", "no flying"),
            "no frist strike": ("did you mean no first strike?", "no first strike"),
        }
        for text, (message, rewrite) in messages.items():
            with self.subTest(text=text):
                self.assertEqual([(m["message"], m["rewrite"]) for m in self.js[text]["mistakes"]], [(message, rewrite)])
        self.assertEqual(self.js["1/1; no flyng"]["advice"]["fix"], "1/1; no flying")

    def test_likely_mistakes_get_a_warning_and_a_rewrite(self):
        cases = {
            "4/4 white flying": ("'4/4 white flying' isn't read: separate them with ';' (4/4; white; flying).",
                                 "4/4; white; flying"),
            "white 4/4, flying": ("'white 4/4, flying' isn't read: separate them with ';' (4/4; white; flying).",
                                  "4/4; white; flying"),
            "4/4; whte; flyng": ("'whte' isn't read: did you mean white?", "4/4; white; flying"),
            "frist strike": ("'frist strike' isn't read: did you mean first strike?", "first strike"),
            "4/4 whte flyng": ("'4/4 whte flyng' isn't read: did you mean 4/4; white; flying?", "4/4; white; flying"),
        }
        for text, (message, fix) in cases.items():
            with self.subTest(text=text):
                advice = self.js[text]["advice"]
                self.assertTrue(advice["notes"][0]["mistake"])
                self.assertEqual(advice["notes"][0]["message"], message)
                self.assertEqual(advice["fix"], fix)
        self.assertEqual(self.js["4/4; whte; flyng"]["advice"]["read"], ["4/4"])
        self.assertEqual(self.js["4/4; whte; flyng"]["advice"]["notes"][1]["message"],
                         "'flyng' isn't read: did you mean flying?")

    def test_legitimate_extras_are_kept_quietly(self):
        for text in ["Token Creature — Phyrexian Beast", "1/1; printed pink (not a Magic colour)",
                     "printing unconfirmed", "single-sided verified", "When this creature dies, draw a card",
                     "Card back is blank", "Clue"]:
            with self.subTest(text=text):
                advice = self.js[text]["advice"]
                self.assertIsNone(advice["fix"])
                self.assertTrue(advice["notes"])
                self.assertFalse(any(n["mistake"] for n in advice["notes"]))
                self.assertTrue(all(n["message"].endswith("is kept but not compared.") for n in advice["notes"]))

    def test_what_was_read_is_said_in_words(self):
        self.assertIsNone(self.js[""]["advice"])
        self.assertEqual(self.js["2/2; green and blue; ward {2}"]["advice"]["read"], ["2/2", "blue and green", "ward"])
        self.assertEqual(self.js["1/1; flying; no deathtouch"]["advice"]["read"], ["1/1", "flying", "no deathtouch"])
        self.assertEqual(self.js["x/1; colorless"]["advice"]["read"], ["X/1", "colourless"])
        self.assertEqual(self.js["P/T unknown; abilities unspecified"]["advice"]["read"],
                         ["power/toughness unknown", "abilities unknown"])


if __name__ == "__main__":
    unittest.main()
