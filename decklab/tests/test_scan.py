"""Proposing printings from text read off a card (E7-S32's spike); no network.

The card index is built from the trimmed Scryfall fixture. The OCR engines are
faked, except one end-to-end test that runs Windows' own engine on a synthetic
bottom line (tests/scan_image.py) and skips wherever that engine isn't there.
"""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from decklab.lib import cards, scan
from decklab.tests import scan_image

FIXTURES = Path(__file__).parent / "fixtures"


def setUpModule():
    global _patch
    built = cards.build_index(FIXTURES / "default_cards.jsonl", FIXTURES / "oracle_tags.jsonl",
                              {"default_cards": "2026-10-02T09:05:45+00:00"}, log=lambda _: None)
    _patch = mock.patch.object(cards, "_index", cards._prepare(built))
    _patch.start()


def tearDownModule():
    _patch.stop()


def top(lines):
    answer = scan.propose(lines)
    first = answer["proposals"][0] if answer["proposals"] else None
    return answer, first and (first["set"], first["collector_number"], first["how"])


class ReadLinesTests(unittest.TestCase):
    def test_each_bottom_line_layout_gives_its_number(self):
        for line, number in [("R 0107", "107"), ("c 0012", "12"), ("0227 C", "227"),
                             ("002/274 c", "2"), ("153/259 M", "153"), ("O227 C", "227"), ("u 0l35", "135")]:
            with self.subTest(line=line):
                self.assertEqual(scan.read_lines([line])["numbers"], [number])

    def test_power_toughness_and_names_are_not_numbers(self):
        read = scan.read_lines(["2/4", "1/1", "Old Man of the Sea", "Island"])
        self.assertEqual(read["numbers"], [])
        self.assertEqual(read["names"], ["Old Man of the Sea", "Island"])

    def test_set_line_gives_code_language_and_a_foil_star(self):
        read = scan.read_lines(["FDN • EN Artist Name"])
        self.assertEqual((read["sets"], read["language"], read["foil"]), (["FDN"], "en", False))
        read = scan.read_lines(["DSK ★ JP Someone"])
        self.assertEqual((read["sets"], read["language"], read["foil"]), (["DSK"], "ja", True))
        self.assertEqual(scan.read_lines(["FDN EN"])["sets"], ["FDN"])   # the dot often goes unread

    def test_rules_text_in_capitals_is_not_a_set_line(self):
        read = scan.read_lines(["LORD OF THE PIT", "Mentor (Whenever t • creature attacks"])
        self.assertEqual(read["sets"], [])


class ProposeTests(unittest.TestCase):
    def test_name_and_bottom_line_agree(self):
        answer, first = top(["Llanowar Elves", "Creature — Elf Druid", "{T}: Add {G}.", "0227 c",
                             "FDN • EN Artist", "1/1"])
        self.assertEqual(first, ("fdn", "227", "name and number"))
        self.assertEqual(answer["proposals"][0]["finish"], "nonfoil")
        self.assertEqual(answer["proposals"][0]["language"], "en")
        self.assertEqual(len(answer["proposals"]), 1)
        self.assertIn("Llanowar Elves, FDN 227", answer["message"])

    def test_a_foil_star_suggests_foil_only_where_the_printing_has_one(self):
        answer, _ = top(["Llanowar Elves", "R 0227", "FDN ★ EN"])
        self.assertEqual(answer["proposals"][0]["finish"], "foil")
        answer, _ = top(["Llanowar Elves", "314/280 C", "M19 ★ EN"])
        self.assertEqual(answer["proposals"][0]["finish"], "nonfoil")    # m19 314 is non-foil only

    def test_ocr_confusions_in_the_set_code_are_tried(self):
        self.assertEqual(top(["R 0227", "FON EN"])[1], ("fdn", "227", "number"))
        self.assertEqual(top(["Llanowar Elves", "314/280 C", "MI9 • EN"])[1], ("m19", "314", "name and number"))

    def test_a_misread_name_is_matched_closely(self):
        self.assertEqual(top(["Llanowar Elvcs", "0227 C", "FDN • EN"])[1], ("fdn", "227", "name and number"))

    def test_a_number_naming_another_card_is_flagged(self):
        answer, first = top(["Elvish Mystic", "0227 C", "FDN • EN"])
        self.assertEqual(first, ("fdn", "227", "number"))
        self.assertIn(("cmm", "648", "name"),
                      [(p["set"], p["collector_number"], p["how"]) for p in answer["proposals"]])
        self.assertIn("check it's this card", answer["message"])

    def test_without_a_set_code_the_name_and_number_still_pick_a_printing(self):
        self.assertEqual(top(["Llanowar Elves", "314/280 C"])[1], ("m19", "314", "name and number"))

    def test_an_old_card_gives_its_name_and_every_paper_printing(self):
        answer, first = top(["Llanowar Elves", "Creature — Elf Druid", "Illus. Someone"])
        self.assertEqual(first[2], "name")
        found = {(p["set"], p["collector_number"]) for p in answer["proposals"]}
        self.assertIn(("fdn", "227"), found)
        self.assertNotIn(("ttsr", "12"), found)        # the token printing isn't the card
        self.assertIn("choose the printing", answer["message"])

    def test_a_keyword_lower_down_is_not_taken_for_the_name(self):
        answer, _ = top(["Legendary Creaturg — Cat Warlock", "Vigilance", "Wrath of God"])
        self.assertIsNone(answer["read"]["name"])

    def test_nothing_readable_says_to_type_the_name(self):
        answer, first = top(["", "& 2024 Wizards of the Coast"])
        self.assertIsNone(first)
        self.assertIn("type the card's name", answer["message"])
        answer, _ = top(["R 0999", "FDN • EN"])
        self.assertIn("names no printing", answer["message"])


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.photo = Path(self.folder.name) / "card.png"
        self.photo.write_bytes(scan_image.png(["R 0227", "FDN EN"]))

    def test_windows_engine_gets_the_path_in_its_environment(self):
        done = subprocess.CompletedProcess([], 0, stdout="﻿R 0227\r\nFDN • EN\r\n\r\n".encode("utf-8"),
                                           stderr=b"")
        with mock.patch.object(scan, "_powershell", return_value="powershell.exe"), \
                mock.patch.object(scan.subprocess, "run", return_value=done) as run:
            self.assertEqual(scan.windows_ocr(self.photo), ["R 0227", "FDN • EN"])
        command, kwargs = run.call_args
        self.assertIn("-EncodedCommand", command[0])
        self.assertEqual(kwargs["env"]["DECKLAB_SCAN_IMAGE"], str(self.photo.resolve()))
        self.assertEqual(kwargs["timeout"], scan.OCR_TIMEOUT)

    def test_failures_are_plain_messages(self):
        with mock.patch.object(scan, "_powershell", return_value="powershell.exe"), \
                mock.patch.object(scan.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            with self.assertRaisesRegex(scan.OcrUnavailable, "too long"):
                scan.windows_ocr(self.photo)
        failed = subprocess.CompletedProcess([], 3, stdout=b"", stderr=b"no OCR language installed\n")
        with mock.patch.object(scan, "_powershell", return_value="powershell.exe"), \
                mock.patch.object(scan.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(scan.OcrUnavailable, "no OCR language installed"):
                scan.windows_ocr(self.photo)

    def test_auto_names_every_engine_missing(self):
        with mock.patch.object(scan, "_powershell", return_value=None), \
                mock.patch.object(scan.shutil, "which", return_value=None):
            with self.assertRaises(scan.OcrUnavailable) as caught:
                scan.ocr(self.photo)
        self.assertIn("only on Windows", str(caught.exception))
        self.assertIn("Tesseract isn't installed", str(caught.exception))
        self.assertIn("Type the card's name", str(caught.exception))
        with self.assertRaisesRegex(scan.OcrUnavailable, "No photo"):
            scan.ocr(Path(self.folder.name) / "missing.jpg")

    def test_command_prints_proposals_from_text_and_reports_a_failed_photo(self):
        text = Path(self.folder.name) / "lines.txt"
        text.write_text("Llanowar Elves\nR 0227\nFDN • EN\n", encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(scan.main(["--text", str(text), "--json"]), 0)
        answer = json.loads(out.getvalue())[0]
        self.assertEqual(answer["proposals"][0]["set"], "fdn")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(scan, "ocr", side_effect=scan.OcrUnavailable("Tesseract isn't installed.")), \
                redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(scan.main([str(self.photo)]), 1)
        self.assertIn("Tesseract isn't installed.", out.getvalue())

    @unittest.skipUnless(sys.platform == "win32", "Windows' OCR engine is only on Windows")
    def test_windows_engine_reads_a_synthetic_bottom_line(self):
        try:
            lines = scan.windows_ocr(self.photo)
        except scan.OcrUnavailable as e:
            self.skipTest(f"Windows OCR isn't usable here: {e}")
        self.assertEqual(top(lines)[1][:2], ("fdn", "227"))


if __name__ == "__main__":
    unittest.main()
