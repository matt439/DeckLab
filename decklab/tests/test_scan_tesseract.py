"""Photo scanning off Windows (E7-S32): Tesseract's TSV regrouped into lines in reading order, its
command, its failures in plain words, the engines "auto" tries on each platform, engine_status and
the doctor's optional check. Tesseract is never run: subprocess.run is a stand-in answering
recorded TSV, so these pass on Windows and Linux alike. The one live check skips where Tesseract
isn't installed and is qualified separately on the Linux server PC (scripts/fixture_runtime.py).
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from decklab.lib import cards, preflight, preflight_local, scan
from decklab.lib.api import collection_scan as cs
from decklab.lib import scan_image

FIXTURES = Path(__file__).parent / "fixtures"
HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def setUpModule():
    global _patch
    built = cards.build_index(FIXTURES / "default_cards.jsonl", FIXTURES / "oracle_tags.jsonl",
                              {"default_cards": "2026-10-02T09:05:45+00:00"}, log=lambda _: None)
    _patch = mock.patch.object(cards, "_index", cards._prepare(built))
    _patch.start()


def tearDownModule():
    _patch.stop()


def tsv(*words):
    """Tesseract 5's TSV for words (block, par, line, left, top, width, height, conf, text), with the
    page, block, paragraph and line rows (conf -1, no text) it writes before them."""
    rows = [HEADER, "1\t1\t0\t0\t0\t0\t0\t0\t1500\t2100\t-1\t"]
    seen = set()
    for block, par, line, left, top, width, height, conf, text in words:
        for level, key in ((2, (block,)), (3, (block, par)), (4, (block, par, line))):
            if key not in seen:
                seen.add(key)
                ids = list(key) + [0] * (3 - len(key))
                rows.append(f"{level}\t1\t{ids[0]}\t{ids[1]}\t{ids[2]}\t0\t{left}\t{top}\t{width}\t{height}\t-1\t")
        rows.append(f"5\t1\t{block}\t{par}\t{line}\t1\t{left}\t{top}\t{width}\t{height}\t{conf}\t{text}")
    return "\n".join(rows) + "\n"


# A photo of Llanowar Elves (FDN 227) as sparse mode reads it: the bottom line's block comes first,
# "R" and "0227" are separate blocks, the set line's dot is its own word, and art reads as noise.
ELVES_TSV = tsv(
    (1, 1, 1, 90, 1930, 28, 34, 91.5, "R"),
    (2, 1, 1, 130, 1930, 92, 34, 88.0, "0227"),
    (3, 1, 1, 90, 1975, 70, 34, 90.1, "FDN"),
    (3, 1, 1, 168, 1980, 12, 22, 47.0, "•"),
    (3, 1, 1, 188, 1975, 40, 34, 89.7, "EN"),
    (3, 1, 1, 260, 1975, 150, 34, 85.2, "Artist"),
    (4, 1, 1, 400, 900, 60, 40, 12.0, "Wwm"),            # art, low confidence
    (5, 1, 1, 700, 1100, 30, 30, 95.0, "~"),              # art, no letter or digit
    (6, 1, 1, 110, 1240, 120, 44, 93.0, "Creature"),
    (6, 1, 1, 250, 1240, 40, 44, 90.0, "—"),
    (6, 1, 1, 310, 1240, 60, 44, 92.0, "Elf"),
    (6, 1, 1, 390, 1240, 110, 44, 92.0, "Druid"),
    (7, 1, 1, 100, 90, 220, 56, 96.0, "Llanowar"),
    (7, 1, 1, 340, 90, 150, 56, 96.3, "Elves"),
)


def completed(code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], code, stdout=stdout.encode("utf-8"), stderr=stderr.encode("utf-8"))


class TsvLinesTests(unittest.TestCase):
    def test_words_become_lines_in_reading_order(self):
        # Art and the type line's dash (no letter or digit) are dropped; the dot on the set line is kept.
        self.assertEqual(scan._tsv_lines(ELVES_TSV),
                         ["Llanowar Elves", "Creature Elf Druid", "R 0227", "FDN • EN Artist"])

    def test_the_regrouped_lines_propose_the_printing(self):
        answer = scan.propose(scan._tsv_lines(ELVES_TSV))
        first = answer["proposals"][0]
        self.assertEqual((first["name"], first["set"], first["collector_number"], first["how"], first["language"]),
                         ("Llanowar Elves", "fdn", "227", "name and number", "en"))

    def test_lines_far_apart_on_one_row_stay_apart(self):
        lines = scan._tsv_lines(tsv((1, 1, 1, 90, 1930, 28, 34, 90, "R"), (1, 1, 1, 130, 1930, 92, 34, 90, "0227"),
                                    (2, 1, 1, 1200, 1932, 200, 34, 90, "Wizards")))
        self.assertEqual(lines, ["R 0227", "Wizards"])

    def test_a_foil_star_is_kept_but_other_marks_are_not(self):
        lines = scan._tsv_lines(tsv((1, 1, 1, 90, 1975, 70, 34, 90, "DSK"), (1, 1, 1, 168, 1975, 20, 30, 60, "★"),
                                    (1, 1, 1, 196, 1975, 40, 34, 90, "JP"), (2, 1, 1, 500, 500, 20, 20, 99, "|")))
        self.assertEqual(lines, ["DSK ★ JP"])
        self.assertTrue(scan.read_lines(lines)["foil"])

    def test_empty_output_is_no_lines_and_other_output_is_a_plain_failure(self):
        self.assertEqual(scan._tsv_lines(""), [])
        self.assertEqual(scan._tsv_lines(HEADER + "\n"), [])
        with self.assertRaisesRegex(scan.OcrUnavailable, r"^The OCR engine couldn't read the photo\.$"):
            scan._tsv_lines("Llanowar Elves\nR 0227\n")
        with self.assertRaises(scan.OcrUnavailable):
            scan._tsv_lines("level\tleft\ttext\n5\t1\tElves\n")      # a header without the columns needed

    def test_a_faint_set_line_is_kept_but_faint_art_is_not(self):
        # Tesseract 5.5 gave a drawn card's "FDN • EN" as one word "FDN-EN" with confidence 0 (WSL, 2026-11-02).
        lines = scan._tsv_lines(tsv((1, 1, 1, 90, 1930, 28, 34, 91.0, "C"), (1, 1, 1, 130, 1930, 92, 34, 90.0, "0227"),
                                    (2, 1, 1, 90, 1975, 130, 34, 0.0, "FDN-EN"),
                                    (3, 1, 1, 400, 900, 60, 40, 12.0, "Wwm"),
                                    (4, 1, 1, 400, 1000, 60, 40, 5.0, "Llanowar")))
        self.assertEqual(lines, ["C 0227", "FDN-EN"])
        read = scan.read_lines(lines)
        self.assertEqual((read["numbers"], read["sets"], read["language"]), (["227"], ["FDN"], "en"))
        answer = scan.propose(lines)
        self.assertEqual((answer["proposals"][0]["name"], answer["proposals"][0]["collector_number"]),
                         ("Llanowar Elves", "227"))

    def test_broken_rows_are_skipped(self):
        text = ELVES_TSV + "5\t1\t9\t1\t1\t1\tx\t10\t10\t10\t90\tBroken\n5\t1\t9\n"
        self.assertNotIn("Broken", " ".join(scan._tsv_lines(text)))


class SetLineSeparatorTests(unittest.TestCase):
    def test_misread_dots_still_give_the_set_and_language(self):
        for line in ("FDN e EN", "FDN - EN", "FDN + EN", "FDN ° EN", "FDN » EN", "FDN o EN", "FDN • EN"):
            with self.subTest(line=line):
                read = scan.read_lines([line])
                self.assertEqual((read["sets"], read["language"], read["foil"]), (["FDN"], "en", False))

    def test_only_a_star_makes_it_foil(self):
        self.assertTrue(scan.read_lines(["FDN * EN"])["foil"])
        self.assertFalse(scan.read_lines(["FDN e EN"])["foil"])

    def test_a_lone_letter_needs_spaces_and_a_language(self):
        self.assertEqual(scan.read_lines(["FDNe EN"])["sets"], [])
        self.assertEqual(scan.read_lines(["FDN e XX"])["sets"], [])


class TesseractEngineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.photo = Path(self.folder.name) / "card.png"
        self.photo.write_bytes(scan_image.png(["R 0227", "FDN EN"]))

    def run_with(self, done):
        with mock.patch.object(scan, "_tesseract", return_value="/usr/bin/tesseract"), \
                mock.patch.object(scan.subprocess, "run", return_value=done) as run:
            return scan.tesseract_ocr(self.photo), run

    def test_its_command_environment_and_time_limit(self):
        lines, run = self.run_with(completed(stdout=ELVES_TSV))
        self.assertEqual(lines[0], "Llanowar Elves")
        command, kwargs = run.call_args
        expected = ["/usr/bin/tesseract", str(self.photo), "stdout", "-l", "eng", "--psm", "11", "tsv"]
        self.assertEqual(command[0][-len(expected):], expected)
        prefix = command[0][:-len(expected)]
        self.assertEqual(prefix, [shutil.which("prlimit"), f"--as={scan.TESSERACT_MEMORY}", "--"]
                         if scan.sys.platform.startswith("linux") else [])
        self.assertEqual(kwargs["env"]["OMP_THREAD_LIMIT"], "1")
        self.assertEqual(kwargs["timeout"], scan.OCR_TIMEOUT)
        self.assertTrue(kwargs["capture_output"])

    def test_a_second_pass_when_the_first_misses_the_printing(self):
        sparse = tsv((1, 1, 1, 100, 1240, 120, 44, 93.0, "ture"), (1, 1, 1, 230, 1240, 60, 44, 92.0, "Elf"))
        blocks = tsv((1, 1, 1, 100, 90, 220, 56, 96.0, "Llanowar"), (1, 1, 1, 340, 90, 150, 56, 96.3, "Elves"),
                     (2, 1, 1, 90, 1930, 28, 34, 91.0, "C"), (2, 1, 1, 130, 1930, 92, 34, 90.0, "0227"),
                     (3, 1, 1, 90, 1975, 70, 34, 90.1, "FDN"), (3, 1, 1, 188, 1975, 40, 34, 89.7, "EN"))
        with mock.patch.object(scan, "_tesseract", return_value="/usr/bin/tesseract"), \
                mock.patch.object(scan.subprocess, "run",
                                  side_effect=[completed(stdout=sparse), completed(stdout=blocks)]) as run:
            lines = scan.tesseract_ocr(self.photo)
        self.assertEqual(lines, ["Llanowar Elves", "C 0227", "FDN EN"])
        self.assertEqual([call.args[0][-3:-1] for call in run.call_args_list], [["--psm", "11"], ["--psm", "6"]])
        # A second pass that reads no more of the printing leaves the first pass's lines.
        with mock.patch.object(scan, "_tesseract", return_value="/usr/bin/tesseract"), \
                mock.patch.object(scan.subprocess, "run",
                                  side_effect=[completed(stdout=sparse), completed(stdout=HEADER + "\n")]):
            self.assertEqual(scan.tesseract_ocr(self.photo), ["ture Elf"])
        # One pass is enough when it reads both the number and the set line.
        lines, run = self.run_with(completed(stdout=ELVES_TSV))
        self.assertEqual(run.call_count, 1)

    def test_the_synthetic_card_is_softened(self):
        hard, soft = scan_image.png(["FDN EN"], soften=0), scan_image.png(["FDN EN"])
        self.assertNotEqual(hard, soft)
        self.assertEqual(hard[:8], b"\x89PNG\r\n\x1a\n")

    def test_failures_are_told_in_plain_words(self):
        for stderr, expected in (
                ("Error opening data file /usr/share/tesseract-ocr/5/tessdata/eng.traineddata\n"
                 "Failed loading language 'eng'\nTesseract couldn't load any languages!\n",
                 "The OCR engine couldn't read the photo: Tesseract has no English language data "
                 "(install tesseract-ocr-eng)."),
                ("Error in pixReadStream: Unknown format: no pix returned\nError in pixRead: pix not read\n"
                 "Error during processing.\n",
                 "The OCR engine couldn't read the photo: it isn't a picture Tesseract can open (JPEG or PNG)."),
                ("Segmentation fault at 0x7f00 /home/someone/private\n", "The OCR engine couldn't read the photo."),
                ("", "The OCR engine couldn't read the photo.")):
            with self.subTest(stderr=stderr[:20]):
                with self.assertRaises(scan.OcrUnavailable) as caught:
                    self.run_with(completed(1, stderr=stderr))
                self.assertEqual(str(caught.exception), expected)
                self.assertNotIn("..", str(caught.exception))

    def test_a_slow_or_unstartable_tesseract_is_plain_too(self):
        with mock.patch.object(scan, "_tesseract", return_value="/usr/bin/tesseract"), \
                mock.patch.object(scan.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            with self.assertRaisesRegex(scan.OcrUnavailable, "too long"):
                scan.tesseract_ocr(self.photo)
        with mock.patch.object(scan, "_tesseract", return_value=None):
            with self.assertRaises(scan.OcrMissing):
                scan.tesseract_ocr(self.photo)

    @unittest.skipUnless(shutil.which("tesseract"), "Tesseract isn't installed")
    def test_tesseract_reads_a_synthetic_bottom_line(self):
        try:
            lines = scan.tesseract_ocr(self.photo)
        except scan.OcrUnavailable as e:
            self.skipTest(f"Tesseract isn't usable here: {e}")
        read = scan.read_lines(lines)
        self.assertIn("227", read["numbers"], lines)
        self.assertIn("FDN", read["sets"], lines)


class AutoEngineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.photo = Path(self.folder.name) / "card.png"
        self.photo.write_bytes(b"photo")

    def on(self, platform):
        return mock.patch.object(scan, "sys", SimpleNamespace(platform=platform))

    def test_each_platform_tries_its_own_engines(self):
        self.assertEqual(scan.platform_engines("win32"), ("windows", "tesseract"))
        self.assertEqual(scan.platform_engines("linux"), ("tesseract",))
        self.assertEqual(scan.platform_engines("darwin"), ("tesseract",))

    def test_linux_never_tries_windows_engine(self):
        windows = mock.Mock(side_effect=AssertionError("Windows' engine tried on Linux"))
        with self.on("linux"), mock.patch.dict(scan.ENGINES, {"windows": windows, "tesseract": lambda path: ["R 0227"]}):
            self.assertEqual(scan.ocr(self.photo), ["R 0227"])
        windows.assert_not_called()

    def test_windows_tries_its_own_engine_then_tesseract(self):
        calls = []

        def windows(path):
            calls.append("windows")
            raise scan.OcrMissing("Windows' OCR engine is only on Windows.")
        with self.on("win32"), mock.patch.dict(scan.ENGINES, {"windows": windows,
                                                              "tesseract": lambda path: calls.append("t") or ["x"]}):
            self.assertEqual(scan.ocr(self.photo), ["x"])
        self.assertEqual(calls, ["windows", "t"])

    def test_an_engine_that_failed_says_why_and_windows_wording_is_unchanged(self):
        def failed(path):
            raise scan.OcrUnavailable("The OCR engine couldn't read the photo: it isn't a picture Windows can open (JPEG or PNG).")

        def missing(path):
            raise scan.OcrMissing("Tesseract isn't installed.")
        with self.on("win32"), mock.patch.dict(scan.ENGINES, {"windows": failed, "tesseract": missing}):
            with self.assertRaises(scan.OcrUnavailable) as caught:
                scan.ocr(self.photo)
        self.assertNotIsInstance(caught.exception, scan.OcrMissing)
        self.assertEqual(str(caught.exception), "The OCR engine couldn't read the photo: it isn't a picture Windows can "
                                                "open (JPEG or PNG). Tesseract isn't installed. Type the card's name instead.")
        with self.on("linux"), mock.patch.dict(scan.ENGINES, {"tesseract": lambda path: scan.tesseract_ocr(path)}), \
                mock.patch.object(scan, "_tesseract", return_value="/usr/bin/tesseract"), \
                mock.patch.object(scan.shutil, "which", return_value="/usr/bin/prlimit"), \
                mock.patch.object(scan.subprocess, "run", return_value=completed(1, stderr="Error in pixRead: x\n")):
            with self.assertRaises(scan.OcrUnavailable) as caught:
                scan.ocr(self.photo)
        self.assertEqual(str(caught.exception), "The OCR engine couldn't read the photo: it isn't a picture Tesseract "
                                                "can open (JPEG or PNG). Type the card's name instead.")
        self.assertNotIn("Windows", str(caught.exception))


class EngineStatusTests(unittest.TestCase):
    def setUp(self):
        scan._status.update(at=None, value=None)
        self.addCleanup(scan._status.update, at=None, value=None)

    def status(self, platform, powershell=None, tesseract=None, run=None):
        with mock.patch.object(scan, "sys", SimpleNamespace(platform=platform)), \
                mock.patch.object(scan, "_powershell", return_value=powershell), \
                mock.patch.object(scan, "_tesseract", return_value=tesseract), \
                mock.patch.object(scan.subprocess, "run", **({"return_value": run} if not isinstance(run, BaseException)
                                                            else {"side_effect": run})) as ran:
            return scan.engine_status(refresh=True), ran

    def test_windows_own_engine_needs_no_process(self):
        found, ran = self.status("win32", powershell="powershell.exe")
        self.assertEqual((found["engine"], found["available"], found["reason"], found["detail"]),
                         ("windows", True, "ready", None))
        ran.assert_not_called()

    def test_tesseract_with_english(self):
        found, ran = self.status("linux", powershell="powershell.exe", tesseract="/usr/bin/tesseract",
                                 run=completed(stdout="List of available languages in \"/usr/share/tessdata/\" (2):\neng\nosd\n"))
        self.assertEqual((found["engine"], found["available"]), ("tesseract", True))
        command, kwargs = ran.call_args
        self.assertEqual(command[0], ["/usr/bin/tesseract", "--list-langs"])
        self.assertEqual(kwargs["timeout"], scan.LIST_TIMEOUT)
        # Tesseract before 4.1 lists them on stderr.
        found, _ = self.status("linux", tesseract="/usr/bin/tesseract",
                               run=completed(stderr="List of available languages (1):\neng\n"))
        self.assertTrue(found["available"])

    def test_what_is_missing_is_named_for_the_pc_only(self):
        found, _ = self.status("linux")
        self.assertEqual((found["engine"], found["available"], found["reason"]), (None, False, "missing"))
        self.assertIn("tesseract-ocr", found["detail"])
        self.assertNotIn("Windows", found["detail"])
        found, _ = self.status("linux", tesseract="/usr/bin/tesseract", run=completed(stdout="List (1):\nosd\n"))
        self.assertEqual((found["available"], found["reason"]), (False, "no_language"))
        self.assertIn("tesseract-ocr-eng", found["detail"])
        for run in (completed(1), subprocess.TimeoutExpired("x", 5), OSError("no")):
            with self.subTest(run=type(run).__name__):
                found, _ = self.status("linux", tesseract="/usr/bin/tesseract", run=run)
                self.assertEqual((found["available"], found["reason"]), (False, "unusable"))
        found, _ = self.status("win32")
        self.assertEqual(found["reason"], "missing")
        self.assertIn("Windows PowerShell", found["detail"])

    def test_it_is_kept_a_minute(self):
        clock = [1000.0]
        with mock.patch.object(scan.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(scan, "_probe", side_effect=[{"engine": None, "available": False, "reason": "missing"},
                                                               {"engine": "tesseract", "available": True, "reason": "ready"}]) as probe:
            self.assertFalse(scan.engine_status()["available"])
            clock[0] += scan.STATUS_TTL - 1
            self.assertFalse(scan.engine_status()["available"])
            clock[0] += 2
            self.assertTrue(scan.engine_status()["available"])
        self.assertEqual(probe.call_count, 2)

    def test_a_broken_check_is_cant_scan(self):
        with mock.patch.object(scan, "_probe", side_effect=RuntimeError("private /home/x")):
            found = scan.engine_status(refresh=True)
        self.assertEqual((found["available"], found["reason"]), (False, "unusable"))
        self.assertNotIn("private", str(found))


class CutLinesTests(unittest.TestCase):
    def test_a_long_read_keeps_the_name_and_the_bottom_line(self):
        lines = ["Llanowar Elves"] + [f"art noise {i}" for i in range(98)] + ["R 0227", "FDN • EN"]
        cut = cs.cut_lines(lines)
        self.assertEqual(len(cut), cs.MAX_LINES)
        self.assertEqual(cut[0], "Llanowar Elves")
        self.assertEqual(cut[-2:], ["R 0227", "FDN • EN"])
        self.assertEqual(cut[:cs.HEAD_LINES], lines[:cs.HEAD_LINES])
        first = scan.propose(cut)["proposals"][0]
        self.assertEqual((first["set"], first["collector_number"], first["how"]), ("fdn", "227", "name and number"))

    def test_a_short_read_is_kept_whole_and_long_lines_are_cut(self):
        self.assertEqual(cs.cut_lines(["a", "b"]), ["a", "b"])
        self.assertEqual(cs.cut_lines(["x" * 500]), ["x" * cs.MAX_LINE])
        self.assertEqual(len(cs.cut_lines([str(i) for i in range(cs.MAX_LINES)])), cs.MAX_LINES)


class DoctorScanCheckTests(unittest.TestCase):
    def test_each_status_is_a_fixed_optional_finding(self):
        for reason, code, status in (("ready", "ocr_ready", "ready"), ("missing", "ocr_missing", "needs_setup"),
                                     ("no_language", "ocr_no_language", "needs_setup"),
                                     ("unusable", "ocr_unusable", "unverified"), ("odd", "probe_unverified", "unverified")):
            with self.subTest(reason=reason):
                local = preflight_local.Local(scan_status=lambda: {"reason": reason, "detail": "/private/path"})
                self.assertEqual(local.probe("ocr"), code)
                self.assertEqual(preflight.OUTCOMES[code][0], status)

    def test_scanning_never_blocks_the_core_or_the_simulation_files(self):
        ready = {"runtime": "runtime_ready", "config": "config_ready", "driver": "driver_ready",
                 "database": "database_ready", "cards": "cards_ready", "java": "java_files_ready",
                 "forge": "forge_files_ready"}
        result = preflight.report(lambda ident: ready.get(ident, "ocr_missing"))
        row = next(row for row in result["checks"] if row["id"] == "ocr")
        self.assertEqual((row["scope"], row["status"], row["label"]), ("optional", "needs_setup", "Photo scanning engine"))
        self.assertIn("tesseract-ocr", row["next_step"])
        self.assertEqual((result["core_ready"], result["exit_code"], result["optional_files_status"]), (True, 0, "present"))
        self.assertIn("Photo scanning engine (optional)", preflight.text(result))


if __name__ == "__main__":
    unittest.main()
