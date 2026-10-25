"""Packing confirmations belong to a deck's rename generation, never an old id alone."""
import dataclasses
import json
import unittest

from decklab.lib import inventory
from decklab.lib.api import assembly
from decklab.tests.test_api import ApiTestCase
from decklab.tests import test_assembly_progress_ui as progress_tests
from decklab.tests.test_workspace_ui import NODE


OLD = "casual/gruul-test"
NEW = "casual/renamed-gruul"
OTHER = "commander/elf-commander"


class AssemblyRenameMetadataTests(ApiTestCase):
    def preview(self, snapshot, *ids):
        with inventory.pinned(snapshot):
            return assembly.assembly_preview(json.dumps({"decks": [{"id": value, "version": "target"}
                                                                  for value in ids]}))

    def test_old_link_uses_current_generation_without_disclosing_other_deck_generations(self):
        before = inventory.current()
        current = before.deck(OLD).replace(slug="renamed-gruul", rename_version=4)
        other = before.deck(OTHER).replace(rename_version=7)
        snapshot = before.without_deck(OLD).with_deck(current).with_deck(other).replace(deck_aliases={OLD: NEW})
        plan = self.preview(snapshot, OLD)
        self.assertEqual(plan["decks"][0]["id"], NEW)
        self.assertEqual(plan["decks"][0]["rename_version"], 4)
        self.assertEqual(plan["rename_versions"], {NEW: 4})
        together = self.preview(snapshot, OLD, OTHER)
        self.assertEqual(together["rename_versions"], {NEW: 4, OTHER: 7})

    def test_ordinary_snapshot_or_text_revisions_do_not_change_generation(self):
        before = inventory.current()
        changed = before.with_deck(before.deck(OLD).replace(rename_version=2, revision=100))
        plan = self.preview(changed, OLD)
        changed = dataclasses.replace(changed, decks_revision="unrelated-newer-revision")
        changed = changed.with_deck(changed.deck(OLD).replace(revision=101, text=changed.deck(OLD).text + "\n"))
        later = self.preview(changed, OLD)
        self.assertEqual(plan["rename_versions"], {OLD: 2})
        self.assertEqual(later["rename_versions"], plan["rename_versions"])
        self.assertNotEqual(later["completion"]["fingerprint"], plan["completion"]["fingerprint"])

    def test_unrenamed_and_synthetic_decks_use_zero(self):
        snapshot = inventory.current()
        for deck_id in (OLD, "pairing/elves+cats"):
            with self.subTest(deck_id=deck_id):
                plan = self.preview(snapshot, deck_id)
                self.assertEqual(plan["decks"][0]["rename_version"], 0)
                self.assertEqual(set(plan["rename_versions"].values()), {0})


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AssemblyRenameProgressUiTests(unittest.TestCase):
    run_js = progress_tests.AssemblyProgressUiTests.run_js

    def test_id_reversal_and_title_only_rename_never_resurrect_an_old_tick(self):
        self.run_js("""
          const make = (id, generation, title=id) => plan([item(id,{title,rename_version:generation})]);
          let root=open(make('casual/a',0)); await settle();
          tiles(root)[0].click(); await settle(); same(checked(root),['true']);
          const original=[...server][0];
          clear(main); root=open(make('casual/b',1)); await settle(); same(checked(root),['false']);
          tiles(root)[0].click(); await settle();
          clear(main); root=open(make('casual/a',2)); await settle(); same(checked(root),['false']);
          assert(server.has(original),'rename never deletes historical opaque ticks');
          tiles(root)[0].click(); await settle();
          clear(main); root=open(make('casual/a',3,'Changed title, same id')); await settle();
          same(checked(root),['false'],'a title-only rename also needs confirmation');
          tiles(root)[0].click(); await settle();
          clear(main); root=open(make('casual/a',3,'Changed title, same id')); await settle();
          same(checked(root),['true'],'a redraw or unchanged rename keeps the generation');
        """)

    def test_unrelated_rename_and_ordinary_save_leave_other_tasks_checked(self):
        self.run_js("""
          const make = (bGeneration, fingerprint) => plan([
            item('casual/a',{rename_version:0}),item('casual/b',{rename_version:bGeneration})],fingerprint);
          let root=open(make(0,'first')); await settle();
          tiles(root).forEach(t => t.click()); await settle(); same(checked(root),['true','true']);
          clear(main); root=open(make(1,'b-renamed')); await settle(); same(checked(root),['true','false']);
          tiles(root)[1].click(); await settle();
          clear(main); root=open(make(1,'ordinary-save')); await settle(); same(checked(root),['true','true']);
          const a=packingProgressView.ticks[0].id;
          assert.equal(JSON.parse(a)[0],'casual/a:target','zero generation preserves the old task namespace');
        """)

    def test_only_a_transfer_from_the_renamed_donor_needs_a_new_check(self):
        self.run_js("""
          const make = (generation, fingerprint='first') => ({...plan([
            item('casual/a',{steps:[
              {name:'Alpha',keep:0,storage:1,transfers:[{from:'casual/b',from_title:'B',quantity:1}],waiting:0,missing:0}
            ]}),item('casual/b',{rename_version:generation,steps:[]})],fingerprint),
            rename_versions:{'casual/a':0,'casual/b':generation}});
          let root=open(make(0)); await settle();
          tiles(root).forEach(t => t.click()); await settle(); same(checked(root),['true','true']);
          clear(main); root=open(make(2,'donor-returned-to-old-id')); await settle();
          same(checked(root),['true','false'],'pulling storage is unchanged; the renamed donor transfer resets');
          tiles(root)[1].click(); await settle();
          clear(main); root=open(make(2,'ordinary-donor-save')); await settle(); same(checked(root),['true','true']);
        """)
