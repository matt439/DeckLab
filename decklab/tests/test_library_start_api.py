"""GET /api/decks' own_collection_empty (E11-S56): whether the viewer's own space's collection has no cards,
for the library's empty-space start. Sent only to a named profile who may see that collection (its own
people), about their own space only; left out for a script, nobody chosen, an unknown login or an
unreadable collection.

test_api_permissions' sandbox: Matt (admin) and User1 at home (home's collection has cards), User2 with
one deck and an empty collection file, User3 with no collection at all. Run from the repo root:
python scripts/test_fixtures.py decklab.tests.test_library_start_api
"""
from contextlib import ExitStack
from unittest import mock

from decklab.lib import access, api, inventory
from decklab.tests.test_api_permissions import PermissionTestCase, _write
from decklab.tests.test_collection_edit import HEADER

KEY = "own_collection_empty"


class OwnCollectionEmptyTests(PermissionTestCase):

    def index(self, who=None, *, tunnel=True, script=False):
        """decks_index() as who: through the tunnel, or on the home network as the chooser names them."""
        with ExitStack() as stack:
            if tunnel and who:
                stack.enter_context(access.using({"profile": who, "email": "", "remote": True}))
            else:
                stack.enter_context(access.using(None))
                stack.enter_context(access.viewing(who))
                stack.enter_context(access.answering(script))
            return api.decks_index()

    def test_each_profile_learns_only_about_its_own_space(self):
        self.assertIs(self.index("matt")[KEY], False)               # home's collection has cards
        self.assertIs(self.index("user1")[KEY], False)
        self.assertIs(self.index("user2")[KEY], True)               # a deck, but no cards: the flag is the cards'
        self.assertIs(self.index("user3")[KEY], True)               # no collection yet at all
        # Chosen on the home network: the same answer as through the tunnel.
        self.assertIs(self.index("user1", tunnel=False)[KEY], False)

    def test_another_spaces_cards_never_change_the_answer(self):
        _write(self.box.magic / "people" / "user3" / "collection.csv",
               HEADER + "Llanowar Elves,fdn,227,nonfoil,2,NM,en,\n")
        self.assertIs(self.index("user3")[KEY], False)
        self.assertIs(self.index("user2")[KEY], True)
        self.assertIs(self.index("matt")[KEY], False)

    def test_a_script_nobody_or_an_unknown_login_gets_no_flag(self):
        self.assertNotIn(KEY, self.index(None, tunnel=False, script=True))      # a script sees every space
        self.assertNotIn(KEY, self.index(None, tunnel=False, script=False))     # nobody chosen at home
        with access.using({"profile": "stranger", "email": "", "remote": True}):
            try:
                answer = api.decks_index()
            except api.ApiError:
                answer = {}
        self.assertNotIn(KEY, answer)

    def test_a_viewer_who_may_not_see_their_own_collection_or_cant_read_it_gets_no_flag(self):
        with mock.patch("decklab.lib.api.guard.sees_inventory", return_value=False):
            self.assertNotIn(KEY, self.index("user3"))
        real = inventory.current

        class Broken:                       # the snapshot, but its collections can't be read
            def __init__(self, snapshot):
                self.snapshot = snapshot

            def __getattr__(self, name):
                return getattr(self.snapshot, name)

            def collection(self, space=None):
                raise OSError("The database can't be reached")

        def failing():
            return Broken(real())
        with mock.patch("decklab.lib.api.deck_page.inventory.current", side_effect=failing), \
                mock.patch("decklab.lib.api.common._log"):
            self.assertNotIn(KEY, self.index("user3"))
