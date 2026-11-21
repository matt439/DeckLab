"""Storage setup priorities, using disposable fixture answers only."""
import unittest
from decklab.tests import test_storage_setup_ui as storage_tests
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class StorageHierarchyUiTests(unittest.TestCase):
    run_js = storage_tests.StorageSetupUiTests.run_js

    def test_impact_precedes_paired_counts_and_keeps_unknown_counts_explicit(self):
        self.run_js("""
          const cv = draw(); api = async () => VIEW;
          const ctx = await openStorageSetup(cv); await flush();
          ctx.review = {storage: VIEW.storage, now: setupOf([counted(BOX, 2200)]),
            after: setupOf([counted(BOX, 2500)], {unplaced: 4, elsewhere: 9}),
            moves: [{from: null, to: 'Storage box', locations: 2}], counts_error: null};
          drawStorageReview(ctx);
          const text = ctx.reviewBox.textContent;
          assert(text.indexOf('100 cards over capacity') < text.indexOf('Container counts:'), text);
          assert(text.includes('nowhere to go: about 4 cards'), text);
          assert(text.includes('outside the setup: about 9 cards'), text);
          assert(text.includes('2 recorded locations would be assigned'), text);
          assert.equal(ctx.reviewBox.querySelector('.storage-comparison').querySelectorAll('li').length, 1);
          ctx.review.counts_error = 'Collection could not be read';
          drawStorageReview(ctx);
          assert(ctx.reviewBox.textContent.includes('counts are unavailable'));
          assert(!ctx.reviewBox.textContent.includes('No counted container'));
          assert(!ctx.reviewBox.textContent.includes('No recorded location changes'));
          assert(ctx.reviewBox.textContent.includes('reassignments could not be checked'));
          assert(!ctx.reviewBox.querySelector('.storage-comparison'));
        """)

    def test_optional_fields_and_rename_refresh_without_losing_focus_or_default(self):
        self.run_js("""
          const cv = draw(); api = async () => VIEW;
          const ctx = await openStorageSetup(cv); await flush();
          const row = ctx.edit.querySelector('.storage-container');
          const name = row.querySelector('.storage-name'); name.focus();
          type(name, 'Card shelf');
          assert.equal(document.activeElement, name);
          assert.equal(row.querySelector('legend').textContent, 'Card shelf');
          const option = ctx.edit.querySelector(`option[value="${ctx.defaultKey}"]`);
          assert.equal(option.textContent, 'Card shelf');
          assert.equal(storageRecord(ctx).default, 'box');
          const filing = row.querySelectorAll('select').find(s => s.id.includes('-order-'));
          assert.equal(filing.closest('details'), null);
          assert(filing.closest('label').textContent.includes('Filing order'));
          assert(filing.closest('label').textContent.includes('Card list and Build decks'));
          assert(!row.querySelector('.storage-options').open);
          assert.equal(row.querySelector('[data-move="up"]').getAttribute('aria-label'), 'Move Card shelf up');
          assert.equal(row.querySelectorAll('input')[1].value, '2400');
        """)

    def test_comparison_keeps_renamed_and_removed_containers_identifiable(self):
        self.run_js("""
          const other = {...BOX, id: 'other', name: 'Old binder'};
          const compared = storageComparison(setupOf([counted(BOX, 3), counted(other, 8)]),
            setupOf([counted({...BOX, name: 'Renamed box'}, 11)]));
          assert.equal(compared.querySelectorAll('li').length, 2);
          assert(compared.textContent.includes('Renamed box'));
          assert(compared.textContent.includes('Now — Storage box'));
          assert(compared.textContent.includes('removed from the setup'));
        """)


if __name__ == "__main__":
    unittest.main()
