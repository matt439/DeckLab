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
        self.assertEqual({row["token"]["back_collector_number"] for row in detail["rows"]}, {"8", "9"})
        self.assertNotIn("For testing", str(detail))
        original = [{key: value for key, value in row.items() if key not in ("manualLabel", "token")}
                    for row in detail["rows"]]
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
          api = async () => detail({rows: [...rows, token], scan: {available:false}, excluded_names: ['Forest'],
            ready:false, editable:false, expect:null});
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
          assert(action('Look up cards') && !action('Count by hand'));
          same(writes, []);
        """)

    def test_complete_scan_saves_the_same_audit_and_retains_unlisted_printings(self):
        self.run_js("""
          const view = render();
          const token = {name: 'Goblin / Treasure', key: 'token-aa', set: 'tfdn', collector_number: '4',
            quantity: 1, finish: 'foil', manualLabel: 'Goblin / Treasure · TFDN · foil'};
          const gold = {name:'Golden Pig', canonical_name:'Golden Pig', set:'fdn', collector_number:'88', finish:'nonfoil'};
          const wrongFinish = {...rows[1], finish:'etched'};
          const differences = [
            {...rows[1], expected:2, observed:0},
            {...wrongFinish, key:'fdn|1|etched', expected:0, observed:1},
            {...gold, key:'fdn|88|nonfoil', expected:0, observed:1},
          ];
          const recorded = {...white, audit: {current:true, needs_review:true, expected:6, observed:6, mismatch_rows:3,
            extra:2, missing:2, unidentified_extra:0, differences}};
          api = async () => detail({rows:[...rows, token], section:{...white, quantity:6}, excluded_names:['Forest'],
            scan:{available:false}});
          let capture, writes = [];
          const start = startCardAudit;
          globalThis.startCardAudit = target => { capture = start(target); return capture; };
          apiWrite = async (path, body) => { writes.push([path, body]); return {section:recorded, expect:'fresh'}; };
          chooseSection('white').click(); await flush();
          action('Look up cards').click();
          addScanCard(capture, {...rows[0], canonical_name:'Alpha'});
          addScanCard(capture, {...rows[0], canonical_name:'Alpha'});
          addScanCard(capture, {...rows[0], canonical_name:'Alpha'});
          addScanCard(capture, wrongFinish);
          addScanCard(capture, gold);
          addScanCard(capture, {name:'Forest', set:'fdn', collector_number:'99', finish:'nonfoil'});
          countInput('Counted for ' + token.manualLabel).value = '1';
          action('Finish audit').click();
          assert(openDialog().textContent.includes('Review your count'));
          assert(openDialog().textContent.includes('2 expected (estimate) · 0 counted'));
          assert(openDialog().textContent.includes('2 cards unlisted'));
          assert(openDialog().textContent.includes('Outside this audit') && openDialog().textContent.includes('1 × Forest'));
          assert.equal(writes.length, 0);
          action('Save audit').click(); await flush();
          same(writes, [['/api/collection/storage-map', {space:'home', section:'white', expect:'proof',
            counts:{'fdn|1|nonfoil':3, 'fdn|1|foil':0, 'token-aa':1}, extra:0, unlisted:[
              {set:'fdn', collector_number:'1', finish:'etched', quantity:1},
              {set:'fdn', collector_number:'88', finish:'nonfoil', quantity:1},
            ]}]]);
          assert(capture.sheet.closed);
          assert(openDialog().textContent.includes('Audit saved.'));
          assert(action('Keep for later') && action('Review collection copies'));
          assert(view.mapSections.find(section => section.id === 'white').audit.needs_review);
        """)

    def test_skipped_photos_cannot_replace_the_saved_audit(self):
        self.run_js("""
          render();
          api = async () => detail({section:empty, rows:[], scan:{available:false}, excluded_names:[]});
          let capture;
          const start = startCardAudit;
          globalThis.startCardAudit = target => { capture = start(target); return capture; };
          apiWrite = () => { throw new Error('unexpected write'); };
          chooseSection('green').click(); await flush();
          action('Look up cards').click();
          drawScanResult(capture, {proposals:[], message:'Unreadable'});
          action('Skip this photo').click();
          action('Finish audit').click();
          assert(openDialog().textContent.includes('1 photo skipped'));
          assert(!action('Save audit'));
          action('Done').click();
          assert(action('Count by hand'));
        """)

    def test_section_scan_offers_only_a_printings_known_finishes(self):
        self.run_js("""
          render();
          api = async () => detail({scan:{available:false}, excluded_names:[]});
          let capture;
          const start = startCardAudit;
          globalThis.startCardAudit = target => { capture = start(target); return capture; };
          chooseSection('white').click(); await flush();
          action('Look up cards').click();
          addScanCard(capture, {name:'Alpha', set:'fdn', collector_number:'9', finish:'nonfoil', finishes:['nonfoil']});
          const select = openDialog().querySelector('[aria-label="Finish of Alpha"]');
          same(select.querySelectorAll('option').map(option => option.value), ['nonfoil']);
          select.value = 'foil'; select.fire('change');
          assert.equal(capture.pending[0].finish, 'nonfoil');
        """)

    def test_stale_scan_reloads_its_section_and_requires_a_new_count(self):
        self.run_js("""
          render();
          let reads = 0, writes = 0;
          api = async () => detail({section:empty, rows:[], scan:{available:false}, excluded_names:[],
            expect:'proof-' + ++reads});
          apiWrite = async (path, body) => {
            writes++;
            assert.equal(body.expect, 'proof-1');
            throw new ApiError(409, 'Someone else saved a count.');
          };
          chooseSection('green').click(); await flush();
          action('Look up cards').click(); action('Finish audit').click();
          const oldSave = action('Save audit');
          oldSave.click(); await flush();
          assert(openDialog().textContent.includes('Someone else saved a count.'));
          action('Reload section').click(); await flush();
          assert(action('Count by hand') && action('Look up cards'));
          assert.equal(reads, 2);
          oldSave.click(); assert.equal(writes, 1);
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
