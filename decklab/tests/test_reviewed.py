"""E11-S71: the index of hand-maintained reference facts (lib/stats/reviewed.py), its review-due rule,
Settings' "Reference facts to review" answer (lib/api/reference_facts.py) and the page's line.

Constants only: no card data, database or network; the announcement file is a made-up one.
Run: python scripts/test_fixtures.py decklab.tests.test_reviewed
"""
import json
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from importlib import import_module
from pathlib import Path
from unittest import mock

from decklab.lib import edhrec, feature_routes, official_lists
from decklab.lib.api import guard, reference_facts
from decklab.lib.api.common import ApiError
from decklab.lib.gauntlet import edhrec_source
from decklab.lib.stats import constants, reviewed, role_targets
from decklab.tests.test_shell_ui import SETUP as SHELL
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

# A day on which every group is inside its interval, worked out from the constants so that
# recording a review never breaks these tests.
NEWEST = max(record["reviewed"] for record in reviewed.records())
QUIET = NEWEST + timedelta(days=1)
REVIEWED_ALL = {"KARSTEN_CHECKED": "2026-06-01", "BRACKET_RULES_CHECKED": "2026-06-01"}


class IndexTests(unittest.TestCase):
    def test_every_named_group_is_indexed_with_its_source_dates_and_interval(self):
        found = {record["id"]: record for record in reviewed.records()}
        self.assertEqual(list(found), ["bracket-rules", "tutor-wording", "karsten", "role-targets",
                                       "edhrec-page", "edhrec-average-decks"])
        for record in found.values():
            self.assertTrue(record["label"] and record["source"] and record["where"], record["id"])
            self.assertIsInstance(record["reviewed"], date)
            self.assertGreater(record["interval_days"], 0)
            self.assertEqual(record["due_on"], record["reviewed"] + timedelta(days=record["interval_days"]))

    def test_the_dates_are_the_existing_constants(self):
        found = {record["id"]: record for record in reviewed.records()}
        iso = date.fromisoformat
        self.assertEqual(found["bracket-rules"]["reviewed"], iso(constants.BRACKET_RULES_CHECKED))
        self.assertEqual(found["bracket-rules"]["reviewed_through"], iso(constants.BRACKET_RULES_DATE))
        self.assertEqual(found["tutor-wording"]["reviewed"], iso(constants.BRACKET_TUTORS["read_on"]))
        self.assertEqual(found["tutor-wording"]["reviewed_through"],
                         iso(constants.BRACKET_TUTORS["reviewed_through"]))
        self.assertEqual(found["karsten"]["reviewed"], iso(constants.KARSTEN_CHECKED))
        self.assertEqual(found["role-targets"]["reviewed"], iso(role_targets.CHECKED))
        self.assertEqual(found["edhrec-page"]["reviewed"], iso(edhrec.SHAPE_CHECKED))
        self.assertEqual(found["edhrec-average-decks"]["reviewed"], iso(edhrec_source.SHAPE_CHECKED))
        for key in ("karsten", "role-targets", "edhrec-page", "edhrec-average-decks"):
            self.assertIsNone(found[key]["reviewed_through"])

    def test_every_pointer_names_something_that_exists(self):
        for fact in reviewed.FACTS:
            for dotted in fact["where"]:
                module, name = dotted.rsplit(".", 1)
                self.assertTrue(hasattr(import_module(module), name), dotted)

    def test_a_changed_constant_is_read_without_a_restart_of_the_index(self):
        with mock.patch.object(role_targets, "CHECKED", "2020-01-02"):
            found = {record["id"]: record for record in reviewed.records()}
        self.assertEqual(found["role-targets"]["reviewed"], date(2020, 1, 2))

    def test_the_edhrec_shape_date_is_a_constant_not_a_docstring_date(self):
        self.assertEqual(date.fromisoformat(edhrec.SHAPE_CHECKED).isoformat(), edhrec.SHAPE_CHECKED)
        self.assertNotIn("checked 20", edhrec.__doc__)
        self.assertIn("SHAPE_CHECKED", edhrec.__doc__)


class DueTests(unittest.TestCase):
    def test_nothing_is_due_inside_every_interval(self):
        self.assertEqual(reviewed.due(QUIET), [])
        self.assertEqual(reviewed.line([]), "")

    def test_a_group_is_due_only_after_its_interval(self):
        with mock.patch.object(role_targets, "CHECKED", "2025-01-01"):
            last_day = date(2025, 1, 1) + timedelta(days=reviewed.YEAR)
            with mock.patch.multiple(constants, **REVIEWED_ALL), \
                    mock.patch.dict(constants.BRACKET_TUTORS, {"read_on": "2026-06-01"}), \
                    mock.patch.object(edhrec, "SHAPE_CHECKED", "2026-06-01"), \
                    mock.patch.object(edhrec_source, "SHAPE_CHECKED", "2026-06-01"):
                self.assertEqual(reviewed.due(last_day), [])
                found = reviewed.due(last_day + timedelta(days=3))
        self.assertEqual([(r["id"], r["days_overdue"], r["overdue"], r["announced"]) for r in found],
                         [("role-targets", 3, True, None)])
        self.assertEqual(reviewed.line(found), "Reference facts to review: Command Zone role targets "
                                               "(last reviewed 2025-01-01; due every 365 days).")

    def test_the_most_overdue_comes_first(self):
        found = reviewed.due(NEWEST + timedelta(days=3 * reviewed.YEAR))
        self.assertEqual(len(found), len(reviewed.FACTS))
        late = [record["days_overdue"] for record in found]
        self.assertEqual(late, sorted(late, reverse=True))

    def test_a_newer_announcement_makes_the_bracket_groups_due_and_no_other(self):
        through = date.fromisoformat(constants.BRACKET_RULES_DATE)
        announced = max(through, date.fromisoformat(constants.BRACKET_TUTORS["reviewed_through"])) \
            + timedelta(days=1)
        with mock.patch.multiple(constants, BRACKET_RULES_CHECKED=NEWEST.isoformat()), \
                mock.patch.dict(constants.BRACKET_TUTORS, {"read_on": NEWEST.isoformat()}):
            found = reviewed.due(QUIET, announced)
            same_day = reviewed.due(QUIET, through)
        self.assertEqual([(r["id"], r["overdue"], r["announced"]) for r in found],
                         [("bracket-rules", False, announced), ("tutor-wording", False, announced)])
        self.assertEqual([r["id"] for r in same_day if r["id"] == "bracket-rules"], [])
        words = reviewed.words(found[0])
        self.assertIn(f"Wizards made a Commander announcement on {announced.isoformat()}", words)
        self.assertIn(constants.BRACKET_RULES_DATE, words)
        self.assertNotIn("due every", words)

    def test_a_review_dated_after_today_is_not_due(self):
        self.assertEqual(reviewed.due(date(2000, 1, 1)), [])


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.viewer = self.enterContext(mock.patch.object(guard, "viewer",
                                                          return_value={"id": "matt", "role": "admin"}))
        self.enterContext(mock.patch.object(guard, "script", return_value=False))
        self.today = self.enterContext(mock.patch.object(reference_facts, "_day", return_value=QUIET))
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.file = folder / "official_lists.json"
        self.enterContext(mock.patch.object(reference_facts, "OFFICIAL_FILE", self.file))

    def announce(self, day):
        self.file.write_text(json.dumps({
            "format": official_lists.FORMAT, "checked_at": "2026-11-09T03:00:00+00:00",
            "last_success_at": "2026-11-09T03:00:00+00:00", "error": None,
            "announcement": {"date": day, "url": "https://magic.wizards.com/en/news/announcements/x"}}),
            encoding="utf-8")

    def test_an_admin_with_nothing_due_gets_an_empty_line(self):
        answer = reference_facts.reference_facts_view()
        self.assertEqual(answer, {"today": QUIET.isoformat(), "groups": len(reviewed.FACTS),
                                  "announcement": None, "due": [], "line": ""})
        json.dumps(answer)

    def test_an_overdue_group_is_named_in_one_line(self):
        self.today.return_value = date.fromisoformat(edhrec.SHAPE_CHECKED) + timedelta(days=reviewed.HALF_YEAR + 1)
        with mock.patch.multiple(constants, **{key: self.today.return_value.isoformat() for key in REVIEWED_ALL}), \
                mock.patch.dict(constants.BRACKET_TUTORS, {"read_on": self.today.return_value.isoformat()}), \
                mock.patch.object(role_targets, "CHECKED", self.today.return_value.isoformat()), \
                mock.patch.object(edhrec_source, "SHAPE_CHECKED", self.today.return_value.isoformat()):
            answer = reference_facts.reference_facts_view()
        self.assertEqual([row["id"] for row in answer["due"]], ["edhrec-page"])
        self.assertEqual(answer["due"][0]["days_overdue"], 1)
        self.assertTrue(answer["line"].startswith("Reference facts to review: EDHREC's commander page layout ("))
        self.assertEqual(answer["line"].count("\n"), 0)
        json.dumps(answer)

    def test_bracket_rules_older_than_the_newest_announcement_are_said_without_a_deck(self):
        newer = (date.fromisoformat(constants.BRACKET_RULES_DATE) + timedelta(days=30)).isoformat()
        self.announce(newer)
        with mock.patch.multiple(constants, BRACKET_RULES_CHECKED=NEWEST.isoformat()), \
                mock.patch.dict(constants.BRACKET_TUTORS, {"read_on": NEWEST.isoformat()}):
            answer = reference_facts.reference_facts_view()
        self.assertEqual(answer["announcement"], newer)
        self.assertIn("bracket-rules", [row["id"] for row in answer["due"]])
        rules = next(row for row in answer["due"] if row["id"] == "bracket-rules")
        self.assertEqual((rules["announced"], rules["overdue"]), (newer, False))
        self.assertIn(f"Commander bracket rules (last reviewed {NEWEST.isoformat()}; "
                      f"Wizards made a Commander announcement on {newer}", answer["line"])

    def test_the_announcement_the_rules_already_match_makes_nothing_due(self):
        self.announce(min(constants.BRACKET_RULES_DATE, constants.BRACKET_TUTORS["reviewed_through"]))
        self.assertEqual(reference_facts.reference_facts_view()["due"], [])

    def test_a_missing_or_damaged_announcement_file_counts_only_the_dates(self):
        self.assertIsNone(reference_facts.reference_facts_view()["announcement"])
        self.file.write_text("{not json", encoding="utf-8")
        self.assertEqual(reference_facts.reference_facts_view()["due"], [])
        with mock.patch.object(official_lists, "read", side_effect=OSError("C:/private/path")):
            self.assertEqual(reference_facts.reference_facts_view()["due"], [])

    def test_only_an_admin_or_a_script_naming_nobody_reads_it(self):
        for profile in ({"id": "user1", "role": "member"}, {"id": "user5", "role": "member"}, None):
            self.viewer.return_value = profile
            with self.assertRaises(ApiError) as refused:
                reference_facts.reference_facts_view()
            self.assertEqual(refused.exception.status, 403)
            self.assertEqual(str(refused.exception), reference_facts.ADMINS_ONLY)
        with mock.patch.object(guard, "script", return_value=True):
            self.assertEqual(reference_facts.reference_facts_view()["due"], [])

    def test_the_route_is_registered(self):
        gets, posts = feature_routes.route_tables()
        self.assertEqual(gets[("settings", "reference-facts")], (reference_facts.reference_facts_view, ()))
        self.assertNotIn(("settings", "reference-facts"), posts)


SETUP = SHELL + r'''
  showFooter=()=>{};loadServerRestart=()=>{};settingsSimulations=()=>{};loadCommanderNightSettings=()=>{};
  loadPostageSettings=()=>{};loadPricingSettings=()=>{};loadSettingsMembers=()=>{};loadVisits=()=>{};
  loadSettingsMaintenance=()=>{};
  state.status=null;state.simulations=null;
  let reads=[],writes=0,answer={today:'2026-11-10',groups:6,announcement:null,due:[],line:''},failure=null,hold=null;
  apiWrite=()=>{writes++;throw Error('Writes are forbidden');};
  api=async(path)=>{reads.push(path);if(hold)await hold;if(failure)throw failure;return structuredClone(answer);};
  const due={today:'2026-11-10',groups:6,announcement:null,
    due:[{id:'karsten',label:"Karsten's land and colour-source figures",words:'x'}],
    line:"Reference facts to review: Karsten's land and colour-source figures (last reviewed 2025-01-01; due every 365 days)."};
  const open=async(id='matt')=>{as(id,false);location.hash='#/settings';routeToken++;
    showSettings(new URLSearchParams(),routeToken);await flush();return byId('settings-reference');};
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SettingsLineUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([
            str(WEB), SETUP + scenario + "\nassert.equal(writes,0);", True]),
            capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_an_admin_sees_the_line_when_a_group_is_due(self):
        self.run_js(r'''
          answer=due;const line=await open();
          same(reads,['/api/settings/reference-facts']);
          assert(!line.hidden);assert.equal(line.textContent,due.line);
          assert(byId('settings-about').contains(line));
        ''')

    def test_nothing_shows_when_nothing_is_due(self):
        self.run_js(r'''
          const line=await open();same(reads,['/api/settings/reference-facts']);
          assert(line.hidden);assert.equal(line.textContent,'');
          assert(!main.textContent.includes('Reference facts to review'));
        ''')

    def test_a_failed_or_odd_answer_stays_quiet(self):
        self.run_js(r'''
          failure=Object.assign(Error('C:/private/path'),{status:503});
          let line=await open();assert(line.hidden);assert(!main.textContent.includes('private'));
          failure=null;answer={due:[{}],line:42};
          line=await open();assert(line.hidden);assert.equal(line.textContent,'');
        ''')

    def test_a_member_is_never_asked_and_sees_no_line(self):
        self.run_js(r'''
          answer=due;const line=await open('user1');
          assert.equal(line,null);same(reads,[]);
          assert(!main.textContent.includes('Reference facts to review'));
        ''')

    def test_a_late_answer_does_not_cross_a_route_change(self):
        self.run_js(r'''
          answer=due;let release;hold=new Promise(done=>{release=done;});
          const line=await open();assert(line.hidden);
          routeToken++;release();await flush();
          assert(line.hidden);assert.equal(line.textContent,'');
        ''')


if __name__ == "__main__":
    unittest.main()
