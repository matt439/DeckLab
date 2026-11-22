"""Section scan uses the private loose-printing snapshot and counts printed tokens by physical card."""
import json
import subprocess
import unittest
from unittest import mock

from decklab.lib import decks, tokens
from decklab.lib.api import collection_storage_map as storage_map
from decklab.tests import test_collection_edit as fixtures
from decklab.tests.test_api import _write
from decklab.tests.test_collection_storage_map_ui import FIXTURE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


class SectionScanApiTests(fixtures.CollectionEditTestCase):
    def test_only_private_section_details_offer_the_readers_scanner_status(self):
        with mock.patch.object(storage_map, "scan_flag", return_value={"available": False}) as engine:
            index = storage_map.view()
            self.assertNotIn("scan", index)
            engine.assert_not_called()
            section = next(item for item in index["sections"] if item["auditable"])
            detail = storage_map.view(section=section["id"])
            self.assertEqual(detail["scan"], {"available": False})
            self.assertEqual(detail["excluded_names"], sorted(decks.BASIC_LANDS))
            engine.assert_called_once_with()
            with self.as_("user2"):
                self.assertApiError(403, storage_map.view, "home", section["id"])
            engine.assert_called_once_with()

    def test_scan_can_compare_fresh_counts_before_audit_history_migration(self):
        self.box.state.collection_audits_ready = False
        section = next(item for item in storage_map.view()["sections"] if item["auditable"])
        with mock.patch.object(storage_map, "scan_flag", return_value={"available": True}):
            detail = storage_map.view(section=section["id"])
        self.assertTrue(detail["scan"]["available"])
        self.assertFalse(detail["editable"])
        self.assertIsNone(detail["expect"])
        self.assertIsInstance(detail["rows"], list)

    def test_token_tally_distinguishes_reverse_printings_and_omits_notes(self):
        token = dict.fromkeys(tokens.FIELDS, "")
        token.update(front="Goblin", back="Treasure", set="tfdn", finish="foil", front_collector_number="4",
                     quantity="1", front_details="1/1 red", back_details="Artifact", notes="For testing")
        content = [",".join(tokens.FIELDS)]
        for number in ("8", "9"):
            token["back_collector_number"] = number
            content.append(",".join(token[field] for field in tokens.FIELDS))
        _write(self.box.magic / "tokens.csv", "\n".join(content) + "\n")
        section = next(s for s in storage_map.view()["sections"] if s["label"] == "Token cards")
        with mock.patch.object(storage_map, "scan_flag", return_value={"available": True}):
            detail = storage_map.view(section=section["id"])
        self.assertEqual(detail["scan"], {"available": True})
        self.assertEqual({row["manualLabel"] for row in detail["rows"]},
                         {f"Goblin · #4 · 1/1 red / Treasure · #{number} · Artifact · TFDN · foil" for number in ("8", "9")})
        self.assertNotIn("For testing", str(detail))
        original = [{key: value for key, value in row.items() if key != "manualLabel"} for row in detail["rows"]]
        self.assertEqual(storage_map._digest("home", {**detail["section"], "rows": detail["rows"]}),
                         storage_map.sections.digest([1, "home", section["id"], section["container"], section["place"], original]))


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SectionScanUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_finish_reports_missing_printings_and_hand_counted_tokens_without_saving(self):
        self.run_js("""
          render();
          const label = 'Goblin #4 / Treasure #9 · TFDN · foil';
          const token = {name: 'Goblin / Treasure', key: 'token-aa', set: 'tfdn', collector_number: '4',
            quantity: 1, finish: 'foil', manualLabel: label};
          api = async () => detail({rows: [...rows, token], scan: {available:false}, excluded_names: ['Forest']});
          const writes = [];
          apiWrite = async (...args) => { writes.push(args); };
          chooseSection('white').click(); await flush();
          const lookup = action('Look up cards');
          assert(document.getElementById(lookup.getAttribute('aria-describedby')).textContent.includes('temporary difference report'));
          lookup.click();
          assert(openDialog().textContent.includes('Closing clears the counted cards'));
          action('Finish audit').click();
          assert.equal(document.activeElement, countInput('Counted for ' + label));
          countInput('Counted for ' + label).value = '2';
          action('Finish audit').click();
          assert(openDialog().textContent.includes('2 counted · 6 expected'));
          assert(openDialog().textContent.includes('Missing (5)'));
          assert(openDialog().textContent.includes('Extra (1)'));
          assert(openDialog().textContent.includes(label));
          assert(openDialog().textContent.includes('Closing clears the counted cards'));
          action('Back to scanning').click();
          assert.equal(countInput('Counted for ' + label).value, '2');
          action('Finish audit').click(); action('Done').click();
          assert(action('Count by hand'));
          same(writes, []);
        """)

    def test_scan_captures_the_open_section_and_owns_child_sheets(self):
        self.run_js("""
          const view = render();
          const token = {name: 'Goblin / Treasure', key: 'token-aa', set: 'tfdn', collector_number: '4',
            quantity: 1, finish: 'foil', manualLabel: 'Goblin #4 / Treasure #9 · TFDN · foil'};
          const details = detail({rows: [...rows, token], scan: {available: true}, excluded_names: ['Forest', 'Wastes']});
          api = async () => details;
          apiWrite = () => { throw new Error('unexpected write'); };
          const starts = [];
          globalThis.startCardAudit = spec => { starts.push(spec); };
          chooseSection('white').click(); await flush();
          const trigger = action('Scan');
          const manual = action('Count by hand');
          trigger.click();
          const [spec] = starts;
          assert.equal(spec.title, 'Storage box · Row 1 · White creatures');
          assert.equal(spec.mode, 'section'); assert.equal(spec.space, 'home');
          same(spec.scan, {available:true}); same(spec.rows.map(row => row.quantity), [3, 2, 1]);
          same(spec.excludedNames, ['Forest', 'Wastes']); assert(spec.instructions.includes('Set basic lands aside'));
          same(spec.rows.map(row => row.manual), [false, false, true]);
          assert.equal(spec.rows[2].manualLabel, token.manualLabel);
          assert(spec.instructions.includes('both faces') && spec.instructions.includes('estimates'));
          const child = colOpenSheet('Read cards');
          assert(spec.current()); trigger.click(); manual.click(); assert.equal(starts.length, 1);
          child.close(); assert(spec.current());
          manual.click(); assert(!spec.current()); trigger.click(); assert.equal(starts.length, 1);
          action('Close').click();
          chooseSection('black').click(); await flush(); assert(!spec.current());
        """)

    def test_empty_sections_can_scan_before_history_migration_and_unfiled_sections_cannot_scan(self):
        self.run_js("""
          render();
          api = async path => path.endsWith('green') ? detail({section: empty, rows: [], scan: {available:false},
            excluded_names: ['Island'], ready:false, editable:false, expect:null}) :
            detail({section: unknown, editable:false, expect:null});
          let spec;
          globalThis.startCardAudit = value => {spec = value;};
          chooseSection('unfiled').click(); await flush(); assert(!action('Look up cards') && !action('Scan'));
          action('Close').click(); chooseSection('green').click(); await flush();
          assert(!action('Count by hand')); action('Look up cards').click();
          same(spec.rows, []); same(spec.scan, {available:false}); assert(spec.current());
          location.hash = '#/library'; assert(!spec.current());
          location.hash = '#/collection?view=map'; assert(spec.current());
          as('user1', MAY.user1); assert(!spec.current());
        """)
