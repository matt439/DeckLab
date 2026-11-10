"""Shared typed card searches preserve caller scopes and privacy (E7-S34)."""
import json
from collections import Counter
import unittest
from unittest import mock

from decklab.lib import access, cards, inventory, pool
from decklab.lib.api import card_terms, collection, editor
from decklab.lib.api.common import ApiError
from decklab.tests import test_collection_find_layout_ui as collection_ui
from decklab.tests import test_editor_search_ui as search_ui
from decklab.tests.test_api import _write
from decklab.tests.test_editor import EditorTestCase


def card(value=2):
    return {"name": "Front // Back", "cmc": value, "type_line": "Creature // Land",
            "oracle_text": "Front draws a card. Back adds mana.",
            "faces": [{"name": "Front", "type_line": "Creature — Elf"}, {"name": "Back", "type_line": "Land"}]}


class CardTermTests(unittest.TestCase):
    def test_mana_comparisons_are_numeric_inclusive_and_and_combined(self):
        values = [0, 0.5, 1, 2, 3, 5, 7, 12]
        for query, expected in (("mv<=2", [0, 0.5, 1, 2]), ("mv>=5", [5, 7, 12]), ("mv=3", [3]),
                                ("mv=7", [7]), ("mv>=1 mv<=3", [1, 2, 3]), ("mv<1", [0, 0.5]), ("mv>7", [12])):
            with self.subTest(query=query):
                name, terms = card_terms.parse(query)
                self.assertEqual(name, "")
                self.assertEqual([value for value in values if card_terms.matches(card(value), terms)], expected)

    def test_aliases_quoted_open_phone_quotes_and_empty_terms_retain_editor_behavior(self):
        self.assertEqual(card_terms.parse('front ORACLE:“draws a card” type:creature'),
                         ("front", [("o", "draws a card"), ("t", "creature")]))
        self.assertEqual(card_terms.parse('o:"draws a card'), ("", [("o", "draws a card")]))
        self.assertEqual(card_terms.parse("o: -t: mv<="), ("", []))
        with mock.patch.object(cards, "search_names", return_value=["Circle of Protection: Red"]):
            self.assertEqual(card_terms.parse("circle of protection: red -t:creature"),
                             ("circle of protection: red", [("-t", "creature")]))

    def test_negation_checks_both_faces_and_the_existing_tilde_name_rule(self):
        for query, expected in (("t:land", True), ("-t:land", False), ("-type:artifact", True),
                                ('o:"~ draws"', True), ('-oracle:"~ draws"', False),
                                ("-o:discard t:elf", True), ("o:mana -t:artifact mv=2", True)):
            with self.subTest(query=query):
                self.assertEqual(card_terms.matches(card(), card_terms.parse(query)[1]), expected)
        self.assertFalse(card_terms.matches(None, [("-t", "land")]))

    def test_bad_ranges_and_unknown_terms_have_bounded_shared_diagnostics(self):
        with mock.patch.object(cards, "search_names", return_value=[]):
            for query in ("c:red", "is:free", "loc:box", "pow>=2", "set:fdn"):
                with self.subTest(query=query), self.assertRaises(ApiError) as caught:
                    card_terms.parse(query)
                self.assertEqual(caught.exception.status, 400)
                self.assertIn(card_terms.KNOWN_TERMS, caught.exception.message)
                self.assertEqual(caught.exception.extra, {"reason": "term", "term": query})
            for query in ("mv<=NaN", "mv>=Infinity", "mv=-1", "mv=1001", "mv<=two"):
                with self.subTest(query=query), self.assertRaises(ApiError) as caught:
                    card_terms.parse(query)
                self.assertEqual(caught.exception.status, 400)
                self.assertIn(card_terms.KNOWN_TERMS, caught.exception.message)


class SharedSearchTests(EditorTestCase):
    def setUp(self):
        super().setUp()
        _write(self.box.magic / "collection.csv", "name,set,collector_number,finish,quantity,condition,language,notes\n"
               "Llanowar Elves,fdn,227,nonfoil,4,,,\nElvish Mystic,cmm,648,nonfoil,1,,,\n"
               "Aerie Mystics,con,1,nonfoil,1,,,\nRhystic Study,wot,25,nonfoil,1,,,\n"
               '"Ghalta, Primal Hunger",rix,130,nonfoil,1,,,\n')
        # The sandbox also owns unrelated products and decks. Give these search
        # checks an explicit pool, with one free Elf after its own known holds.
        self.supply = pool.Pool(Counter({"Llanowar Elves": 4, "Elvish Mystic": 1, "Aerie Mystics": 1,
                                        "Rhystic Study": 1, "Ghalta, Primal Hunger": 1}), {},
                                [pool.InUse("casual/held", "Held", "built", Counter({"Llanowar Elves": 3}))])
        self.enterContext(mock.patch.object(pool, "load_pool", return_value=self.supply))

    def names(self, query, **filters):
        return {row["name"] for row in collection.collection_view(q=query, limit="100", **filters)["cards"]}

    def test_collection_ranges_negated_types_and_rules_mix_with_old_untyped_rules_search(self):
        self.assertEqual(self.names("mv>=5"), {"Aerie Mystics", "Ghalta, Primal Hunger"})
        self.assertEqual(self.names("mv=3"), {"Rhystic Study"})
        self.assertEqual(self.names('o:"add {g}" -t:artifact mv<=2'), {"Llanowar Elves", "Elvish Mystic"})
        self.assertEqual(self.names("add -t:artifact mv<=2"), {"Llanowar Elves", "Elvish Mystic"})
        self.assertEqual(self.names("mv<=2", mv="3"), set())
        self.assertEqual(self.names("-t:creature mv>=3"), {"Rhystic Study"})

    def test_editor_all_and_owned_ranges_work_and_keep_dropdown_seven_plus(self):
        for scope in ("all", "owned"):
            found = editor.find_cards('o:"add {g}" -t:artifact mv<=2', scope=scope, limit="60")
            names = {row["name"] for row in found["cards"]}
            self.assertTrue({"Llanowar Elves", "Elvish Mystic"} <= names)
            self.assertNotIn("Ghalta, Primal Hunger", names)
        exact = editor.find_cards("mv=7", limit="60")["cards"]
        self.assertTrue(exact)
        self.assertTrue(all(row["cmc"] == 7 for row in exact))
        high = editor.find_cards(mv="7", limit="60")["cards"]
        self.assertTrue(any(row["cmc"] > 7 for row in high))

    def test_both_endpoints_return_the_same_unknown_term_sentence_before_any_pool_read(self):
        for query in ("is:free", "c:red", "mv<=NaN"):
            with self.subTest(query=query), mock.patch.object(editor.pool, "load_pool", side_effect=AssertionError("pool read")):
                messages = []
                for find in (editor.find_cards, collection.collection_view):
                    with self.assertRaises(ApiError) as caught:
                        find(q=query)
                    self.assertEqual(caught.exception.status, 400)
                    messages.append(caught.exception.message)
                self.assertEqual(messages[0], messages[1])

    def test_hidden_collection_refuses_before_parsing_and_does_not_relay_its_counts(self):
        _write(self.box.root / "config.json", json.dumps({"profiles": [
            {"id": "matt", "name": "Matt", "space": "home", "role": "admin", "plays_as": "user"},
            {"id": "user2", "name": "User2", "space": "user2", "role": "member"}]}))
        with access.using({"profile": "user2", "remote": True, "email": ""}), \
                mock.patch.object(card_terms, "parse", side_effect=AssertionError("hidden collection query parsed")):
            with self.assertRaises(ApiError) as caught:
                collection.collection_view(q="mv<=2")
        self.assertEqual(caught.exception.status, 403)

    def test_searches_are_read_only(self):
        before = inventory.current().revision
        self.names("mv<=2 -o:discard")
        editor.find_cards("mv>=5 -t:land")
        self.assertEqual(inventory.current().revision, before)


@unittest.skipUnless(search_ui.workspace_ui.NODE, "Node.js is not installed")
class SearchTermUiTests(unittest.TestCase):
    def test_typed_ranges_and_negative_terms_never_become_close_name_guesses(self):
        search_ui.EditorSearchUiTests.run_js(self, r'''
          for(const query of ['mv<=2','mv>=5','mv=3','-o:discard','-TYPE:land']){
            const reads=[];api=async url=>{reads.push(url);return {cards:[],did_you_mean:['Wrong guess']};};
            apiWrite=async()=>{throw Error('A typed filter must not become a decklist parse');};
            ac.input.value=query;await lookUp(ac,query);assert.equal(reads.length,1);
            assert.equal(new URLSearchParams(reads[0].split('?')[1]).get('q'),query);
            assert(hasFindTerms(query));assert(!ac.list.textContent.includes('Wrong guess'));
          }
          assert(ac.input.getAttribute('title').includes('mv<=2'));
        ''')

    def test_collection_discloses_typed_terms_without_changing_the_chosen_query(self):
        collection_ui.CollectionFindLayoutUiTests.run_js(self, r'''
          const query='mv<=2 -t:land o:"add {g}"';const cv=drawFind({},new URLSearchParams({q:query}).toString());
          assert.equal(cv.filterControls.q.value,query);assert(cv.filterControls.q.getAttribute('title').includes('-o:'));
          assert(main.textContent.includes('mv>=5'));assert(main.textContent.includes('-t:land'));
        ''')
