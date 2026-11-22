"""Readiness hierarchy and self-contained publication decisions over the real page scripts."""
import unittest

from decklab.tests import test_commander_lineup_ui as lineup
from decklab.tests import test_visibility_ui as visibility


@unittest.skipUnless(lineup.NODE, "Node.js is not installed")
class ReadinessHierarchyTests(unittest.TestCase):
    run_js = lineup.CommanderLineupUiTests.run_js

    def test_readiness_and_packing_warnings_precede_history(self):
        self.run_js(r"""
          answering(answer); state.profile = matt;
          clear(main); drawPlay(data, ''); await settle(); await show();
          const section = main.querySelector('.commander-lineup');
          assert(section.textContent.includes('The counted minimum covers only what the bracket rules name'));
          assert(section.querySelector('details').querySelector('summary').textContent.includes('What the bracket check covers'));
          const [alpha, beta] = main.querySelectorAll('.commander-lineup-deck');
          assert(alpha.querySelector('.commander-lineup-readiness').textContent.includes('Packed in this box'));
          assert(alpha.querySelector('.commander-lineup-standins').getAttribute('class').includes('note-warn'));
          assert.equal(beta.querySelector('.commander-lineup-standins'), null);
          assert.equal(beta.querySelector('.commander-lineup-box'), null);
          assert(beta.querySelector('.commander-lineup-readiness').textContent.includes('Needs packing'));
          assert(alpha.textContent.indexOf('Physical placeholders:') < alpha.textContent.indexOf('Last played'));
          assert(!beta.textContent.includes('Ready to play'), 'being in Fits is not readiness certification');
        """)


@unittest.skipUnless(visibility.NODE, "Node.js is not installed")
class PublicationHierarchyTests(unittest.TestCase):
    run_js = visibility.VisibilityUiTests.run_js

    def test_confirmation_names_full_audience_and_failed_preview_at_action(self):
        self.run_js(r"""
          await openVisibility(); failPreview=true;
          row('home','decks').querySelector('[data-public=true]').fire('click'); await flush();
          const audience = sheet().textContent;
          assert(audience.includes('read-only access to everyone signed in to Deck Lab'));
          assert(audience.includes('visitors on the home network, even without a chosen profile'));
          assert(audience.includes('Away from home, sign-in is required'));
          const warning = sheet().querySelector('[role=alert]');
          assert(warning.getAttribute('class').includes('note-warn'));
          assert(warning.textContent.includes('Preview unavailable'));
          assert.equal(sheet().querySelector('[data-action=confirm]').textContent, 'Make public without preview');
          assert.equal(sent.length,0);
          await answer('cancel');
          assert.equal(sent.length,0);
          failPreview=false;
          row('home','decks').querySelector('[data-public=true]').fire('click'); await flush();
          assert(!sheet().querySelector('[role=alert]'));
          assert.equal(sheet().querySelector('[data-action=confirm]').textContent, 'Make public');
          await answer('confirm'); assert.equal(sent.length,1);
        """)
