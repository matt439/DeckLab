"""Home's saved field choices that can't be read fail closed (E3-S23).

Run: python scripts/test_fixtures.py decklab.tests.test_field_policy_closed

A missing 0017 table is today's field. Any other failed read, and a missing table
after the same store has read that format's policy, keeps legacy selection for the
views but refuses every field run and field test, in words naming nobody. Fixture
trees and stub stores only: no live database, configured connector or Forge game.
"""
import json
import subprocess
import unittest
from unittest import mock

from decklab.lib import decks, state
from decklab.lib.forge import ForgeError, field, field_exclusions as counts, field_membership, variants
from decklab.lib.forge import field_policy_overlay as overlay
from decklab.lib.state import field_policy, pg_field_policy
from decklab.lib.state.memory import MemoryStore
from decklab.tests import test_forge_field as fixtures
from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

NAMES = ("Matt", "matt", "User1", "user1", "Alpha", "Beta", "Gamma", "casual/")


def _missing():
    return pg_field_policy._MissingSchema(pg_field_policy.MIGRATE)


class Store:
    """field_policy(fmt) answers each read from self.answers in turn (the last one repeats): a
    policy dict, or an exception to raise."""

    def __init__(self, *answers):
        self.answers = list(answers) or [None]
        self.reads = []

    def field_policy(self, fmt):
        self.reads.append(fmt)
        answer = self.answers[min(len(self.reads), len(self.answers)) - 1]
        if isinstance(answer, BaseException):
            raise answer
        return answer if answer is not None else field_policy.empty(fmt)


class ClosedTests(fixtures.FieldTestCase):
    def setUp(self):
        super().setUp()
        original = decks.list_decks
        patcher = mock.patch.object(decks, "list_decks", side_effect=lambda: [
            summary for summary in original() if not summary.get("error")])
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(field, "_side_id", side_effect=lambda entry, eng: "side-" + entry["card_sha"])
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(overlay, "_epochs", side_effect=lambda ids: {
            deck_id: ("creation", deck_id, 1) for deck_id in ids})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(overlay.clear_cache)

    def refused(self, store, fmt="Constructed", **options):
        """(entries, notes, refused, manual count) of one selection pass."""
        found, observer = [], counts.Observation(options.get("visible"))
        with state.use(store):
            entries, notes = field._field(fmt, exclusions=observer, refused=found, **options)
        return entries, notes, found, counts.count(observer)

    def assertNamesNobody(self, sentence):
        for name in NAMES:
            self.assertNotIn(name, sentence)

    # ---------------------------------------------------------------- legacy states stay open

    def test_no_store_missing_table_and_empty_policy_never_refuse(self):
        found = []
        field._field("Constructed", refused=found)      # no store installed
        self.assertEqual(found, [])
        for store in (Store(_missing()), MemoryStore(), Store()):
            with self.subTest(store=type(store).__name__):
                entries, notes, refused, _ = self.refused(store)
                self.assertEqual(refused, [])
                self.assertNotIn(overlay.UNREADABLE, notes)
                with state.use(store):
                    self.assertTrue(field.opponents(self.entry("casual/alpha"), fail_closed=True))
                    self.assertIsNone(field.view(self.entry("casual/alpha"), self.results)["run_refused"])

    def test_member_fields_never_read_or_refuse_on_homes_choices(self):
        store = Store(state.Unavailable("down"))
        _entries, _notes, refused, _ = self.refused(store, space="user2", public=lambda owner: owner == "home")
        self.assertEqual((refused, store.reads), ([], []))

    def test_an_unproved_deck_is_noted_but_not_refused(self):
        rule = {"epoch": {"kind": "creation", "deck_id": "casual/alpha", "revision": 1}, "mode": "exclude"}
        store = Store(field_policy.normalize({"v": 1, "format": "Constructed", "revision": 1, "rules": [rule]}))
        with mock.patch.object(overlay, "_epochs", return_value={}):
            _entries, notes, refused, number = self.refused(store)
        self.assertEqual(refused, [])
        self.assertIn(overlay.UNPROVED, notes)
        self.assertIsNone(number)

    # ---------------------------------------------------------------- a failed read refuses runs

    def test_a_failed_read_keeps_legacy_views_but_refuses_every_start(self):
        with state.use(MemoryStore()):
            before, before_notes = field._field("Constructed")
        for error in (state.Unavailable("private database words"), state.Invalid("corrupt"),
                      RuntimeError("private"), ValueError("private")):
            with self.subTest(error=type(error).__name__):
                overlay.clear_cache()
                store = Store(error)
                entries, notes, refused, number = self.refused(store)
                self.assertEqual(entries, before)
                self.assertEqual(notes, [*before_notes, overlay.UNREADABLE])
                self.assertEqual(refused, [overlay.REFUSED])
                self.assertIsNone(number)
                with state.use(store):
                    alpha = self.entry("casual/alpha")
                    self.assertTrue(field.opponents(alpha))      # a view's reader still gets the legacy field
                    with self.assertRaises(ForgeError) as caught:
                        field.opponents(alpha, fail_closed=True)
                    self.assertEqual(str(caught.exception), overlay.REFUSED)
                    self.assertEqual(field.view(alpha, self.results)["run_refused"], overlay.REFUSED)
                    with self.assertRaises(ForgeError) as caught:
                        self.play("casual/alpha")
                    self.assertEqual(str(caught.exception), overlay.REFUSED)
                    with self.assertRaises(ForgeError) as caught:
                        variants._opponent_entries(alpha, "field", None)
                    self.assertEqual(str(caught.exception), overlay.REFUSED)
                self.assertEqual(self.fake.calls, [])
        for sentence in (overlay.REFUSED, overlay.UNREADABLE, field_membership.CHOICES_UNREADABLE):
            self.assertNamesNobody(sentence)
            self.assertNotIn("private", sentence)

    def test_a_missing_table_after_this_store_read_the_policy_refuses(self):
        store = Store(None, _missing())
        self.assertEqual(self.refused(store)[2], [])         # read: the table exists
        _entries, notes, refused, number = self.refused(store)
        self.assertEqual(refused, [overlay.REFUSED])
        self.assertIn(overlay.UNREADABLE, notes)
        self.assertIsNone(number)
        # Another store, and another format of the same store, still go by their own reads.
        self.assertEqual(self.refused(Store(_missing()))[2], [])
        self.assertEqual(self.refused(store, "Commander")[2], [])

    def test_the_read_memory_is_cleared_with_the_cache(self):
        store = Store(None, _missing())
        self.refused(store)
        overlay.clear_cache()
        self.assertEqual(self.refused(store)[2], [])

    def test_a_readable_policy_again_opens_the_field(self):
        store = Store(state.Unavailable("down"), None)
        self.assertEqual(self.refused(store)[2], [overlay.REFUSED])
        self.assertEqual(self.refused(store)[2], [])

    def test_membership_says_the_choices_cant_be_read_without_rows_or_counts(self):
        store = Store(state.Unavailable("private database words"))
        with state.use(store):
            answer = field_membership.view(self.entry("casual/beta"))
        self.assertEqual((answer["complete"], answer["rows"], answer["counts"]), (False, [], None))
        self.assertEqual(answer["error"], field_membership.CHOICES_UNREADABLE)
        self.assertIs(answer["choices_unreadable"], True)
        with state.use(MemoryStore()):
            answer = field_membership.view(self.entry("casual/beta"))
        self.assertIs(answer["choices_unreadable"], False)
        self.assertTrue(answer["complete"])
        self.assertIs(field_membership.unavailable(self.entry("casual/beta"))["choices_unreadable"], False)


SETUP = PAGE + """
  clear(main);editor=null;state.profile={id:'matt',name:'Matt'};state.may=null;
  routeToken=9;
  const calls=[],writes=[];
  apiWrite=async(...args)=>{writes.push(args);throw new Error('Unexpected write');};
  const settle=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
  const refusal="Home's saved field choices can't be read now, so the field can't be played.";
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ClosedUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_play_the_field_waits_and_says_why_while_the_choices_cant_be_read(self):
        self.run_js("""
          const ctx={id:'casual/test',version:'target',budget:'standard',token:routeToken};
          const base={status:'none',forge:{ready:true},budgets:{}};
          for(const [answer,blocked] of [[{...base,run_refused:refusal},true],[{...base,run_refused:null},false],
              [base,false],[{...base,run_refused:''},false]]){
            const box=fvPlayBox(ctx,answer);
            const button=box.querySelector('[data-run]');
            assert.equal(button.disabled,blocked);
            assert.equal(box.textContent.includes(refusal),blocked);
          }
          const box=fvPlayBox(ctx,{...base,run_refused:refusal});
          box.querySelector('[data-run]').click();await settle();
          assert.equal(writes.length,0);
        """)

    def test_membership_shows_fixed_words_when_the_choices_cant_be_read(self):
        self.run_js("""
          const data=makePage();clear(main);location.hash=deckHref(data.summary.id,data.version)+'&tab=matchups';
          deckScreen={data,view:{tab:'matchups'}};
          api=async path=>{calls.push(path);return {deck:{id:data.summary.id,version:data.version,card_sha:'x'},
            format:'Constructed',rows:[],counts:null,complete:false,error:'SECRET words',choices_unreadable:true};};
          const details=fieldMembership(data);main.append(details);
          details.open=true;details.fire('toggle');await settle();
          assert(details.textContent.includes("Home's saved field choices can't be read now"));
          assert(details.textContent.includes('field runs wait until they can be read'));
          assert(!details.textContent.includes('SECRET'));assert(!details.textContent.includes('lists included'));
          const button=details.querySelector('[data-field-membership-refresh]');
          assert.equal(button.textContent,'Try again');assert.equal(button.disabled,false);
          assert.equal(writes.length,0);
        """)


if __name__ == "__main__":
    unittest.main()
