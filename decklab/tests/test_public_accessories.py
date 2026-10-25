"""E10-S33: public kit is readable, never writable; tests use only disposable stores."""
import json
import subprocess
import unittest
from unittest import mock

from decklab.lib import access, accessories, permissions, state
from decklab.lib.api import accessories as api_acc, guard
from decklab.lib.state import Actor
from decklab.lib.state.memory import MemoryStore
from decklab.tests.test_api_accessories import AccessoriesApiTestCase, SLEEVES, BLACK, image_version, sha
from decklab.tests.test_accessory_fetch import png
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


class PublicAccessoryTests(AccessoriesApiTestCase):
    def setUp(self):
        super().setUp()
        self.store = MemoryStore()
        self.addCleanup(state.use(self.store))
        self.hers = self.add({**SLEEVES, "owner": "user1", "colour": "pink"},
                             image=self.staged(png()), profile="user1")["changed_id"]
        self.add()
        self.assign("casual/hers", self.hers, profile="user1")
        self.assign("product/test-product", BLACK)
        self.public("user1", True)

    def public(self, owner, on):
        self.store.visibility_set(owner, "accessories", on, Actor(owner, owner, "home"), "Fixture kit visibility")

    def test_reader_rows_are_public_but_token_and_choices_cover_only_writable_rows(self):
        view = self.view("matt")
        hers = next(i for i in view["items"] if i["id"] == self.hers)
        shared = next(i for i in view["items"] if i["id"] == BLACK)
        self.assertFalse(hers["editable"])
        self.assertEqual(hers["owner_name"], "User1")
        self.assertTrue(shared["editable"])
        self.assertNotIn("casual/hers", [h["id"] for h in view["holders_options"]])
        self.assertEqual({o["id"] for o in view["owners"]}, {"matt", "shared"})
        token = view["sha256"]
        self.save(profile="user1", sha256=self.view("user1")["sha256"], action="edit", id=self.hers,
                  row={"quantity": 101})
        self.assertEqual(self.view("matt")["sha256"], token)
        self.save(sha256=token, action="edit", id=BLACK, row={"quantity": 102})

    def test_read_only_rows_cannot_be_saved_assigned_or_have_pictures_staged(self):
        with mock.patch.object(api_acc.accessory_fetch, "fetch", side_effect=AssertionError("downloaded")):
            for function, fields in (
                (api_acc.save_accessory, {"sha256": self.view()["sha256"], "action": "edit",
                                          "id": self.hers, "row": {"quantity": 1}}),
                (api_acc.save_accessory, {"sha256": "0" * 64, "action": "remove", "id": self.hers}),
                (api_acc.fetch_picture, {"id": self.hers, "url": "https://example.test/image.png"}),
                (api_acc.assign_accessory, {"holder": "casual/hers", "field": "sleeves", "id": BLACK,
                                            "holder_sha256": self.deck_sha("hers")})):
                with self.subTest(function=function.__name__, fields=fields):
                    self.assertEqual(self.error(function, **fields).status, 403)

    def test_outside_readers_get_hidden_holder_words_and_no_writer_lists(self):
        self.public("shared", True)
        view = self.view("user2")
        self.assertEqual((view["sha256"], view["exists"], view["owners"], view["products"], view["holders_options"]),
                         (None, False, [], [], []))
        self.assertTrue(all(not i["editable"] for i in view["items"]))
        for item in view["items"]:
            for user in item["used_by"]:
                self.assertEqual((user["holder"], user["title"]), (None, "a home deck"))
        encoded = json.dumps(view)
        for hidden in ("casual/hers", "Her Deck", "test-product", "Lightning"):
            self.assertNotIn(hidden, encoded)
        with access.viewing("user2"), mock.patch.object(guard, "public_deck_spaces", return_value={"home"}):
            published = api_acc.accessories_view()
        hers = next(i for i in published["items"] if i["id"] == self.hers)
        self.assertEqual(hers["used_by"][0]["holder"], "casual/hers")
        self.assertEqual(next(i for i in published["items"] if i["id"] == BLACK)["used_by"][0]["holder"], None)

    def test_pictures_revoke_immediately_and_old_cache_addresses_no_longer_work(self):
        name, version = f"{self.hers}.png", image_version(png())
        self.assertNotEqual(version, sha(png())[:8])
        with access.viewing("matt"):
            self.assertEqual(api_acc.image_file(name, version), (png(), "image/png"))
            with self.assertRaises(api_acc.ApiError):
                api_acc.image_file(name, sha(png())[:8])
        self.public("user1", False)
        with access.viewing("matt"), self.assertRaises(api_acc.ApiError) as caught:
            api_acc.image_file(name, version)
        self.assertEqual(caught.exception.status, 404)

    def test_public_reader_stays_out_of_save_fetch_and_staged_endpoints(self):
        with access.viewing("user2"):
            for function, body in ((api_acc.save_accessory, {"profile": "user2"}),
                                   (api_acc.fetch_picture, {"profile": "user2", "url": "https://example.test/a"})):
                # The fixture's writer resolver includes User2, as the real one would.
                with self.subTest(function=function.__name__), self.assertRaises(api_acc.ApiError) as caught:
                    function(json.dumps(body).encode())
                self.assertEqual(caught.exception.status, 403)
            with self.assertRaises(api_acc.ApiError) as caught:
                api_acc.staged_image("0" * 32 + ".png")
            self.assertEqual(caught.exception.status, 403)

    def test_reader_helpers_do_not_widen_write_helpers_even_for_an_admin(self):
        matt = {"id": "matt", "space": "home", "role": "admin"}
        member = {"id": "user2", "space": "user2", "role": "member"}
        self.assertEqual(permissions.accessory_owners(matt), {"matt", "shared"})
        self.assertEqual(permissions.accessory_readers(matt, public={"user1"}), {"matt", "shared", "user1"})
        self.assertEqual(permissions.accessory_readers(member, public={"user1"}), {"user1"})
        self.assertEqual(permissions.accessory_readers(None, public={"user1"}), {"user1"})
        self.assertFalse(permissions.can(member, "accessories.edit"))
        with access.viewing("matt"):
            self.assertTrue(guard.sees_kit("casual/hers"))
            self.assertFalse(guard.sees_kit("casual/hers", guard.accessory_owners()))


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PublicAccessoryUiTests(unittest.TestCase):
    def test_rows_group_by_owner_and_public_rows_never_become_picker_options(self):
        scenario = r"""
          clear(main); state.profile={id:'alex', space:'home'};
          state.may={accessories:true, see_accessories:true};
          const row={kind:'sleeves', owner:'alex', owner_name:'Alex', id:'mine', name:'Own', quantity:100, editable:true};
          const hers={...row, owner:'sam', owner_name:'Sam', id:'hers', name:'Public', editable:false};
          const data={items:[row,hers], owners:[], holders_options:[], products:[], problems:[]};
          const view=drawAccessories(data,routeToken);
          same(view.root.querySelectorAll('.acc-owner-title').map(h=>h.textContent), ['Alex','Sam']);
          assert(view.root.querySelector('[data-id="mine"]').querySelector('.acc-mutate'));
          assert.equal(view.root.querySelector('[data-id="hers"]').querySelector('.acc-mutate'),null);
          assert.equal(kitRowsOf([row,hers],'sam').sleeves.length,0);
          const route=ROUTES.find(r=>r.path==='accessories');
          assert.equal(route.visible({space:'other'},{see_accessories:true}),true);
          assert.equal(route.visible({space:'other'},{see_accessories:false}),false);
        """
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
