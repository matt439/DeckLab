"""Native Share harness contracts; these do not establish iPad Simulator passes."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from decklab.safari import native_share


def menu(*labels, parent_visible=True):
    rows = "".join(f'<XCUIElementTypeCell name="actionGroupCell" label="{label}" visible="true" '
                   'enabled="true" x="274" y="246" width="83" height="134"/>' for label in labels)
    if "Add to Home Screen" not in labels:
        rows += ('<XCUIElementTypeCell name="actionGroupCell" label="Add to Home Screen" visible="false" '
                 'enabled="true" x="20" y="412" width="335" height="51"/>')
    return ('<AppiumAUT><XCUIElementTypeApplication bundleId="com.apple.mobilesafari">'
            '<XCUIElementTypePopover x="435" y="76" width="375" height="393">'
            '<XCUIElementTypeOther name="ShareSheet.RemoteContainerView" visible="true" '
            'x="435" y="89" width="375" height="380">'
            f'<XCUIElementTypeCollectionView name="activityCollectionView" visible="{str(parent_visible).lower()}" '
            f'x="0" y="0" width="375" height="380">{rows}</XCUIElementTypeCollectionView>'
            '</XCUIElementTypeOther></XCUIElementTypePopover></XCUIElementTypeApplication></AppiumAUT>')


def landscape_menu(add_visible=False, horizontal_x=37, add_y=None):
    if add_y is None:
        add_y = 220 if add_visible else 412
    return f'''<AppiumAUT><XCUIElementTypeApplication bundleId="com.apple.mobilesafari">
      <XCUIElementTypePopover x="85" y="1" width="682" height="392">
      <XCUIElementTypeOther name="ShareSheet.RemoteContainerView" visible="true" x="85" y="1" width="682" height="392">
      <XCUIElementTypeCollectionView name="activityCollectionView" visible="true" x="0" y="0" width="682" height="392">
        <XCUIElementTypeScrollView visible="true" x="{horizontal_x}" y="146" width="608" height="121"/>
        <XCUIElementTypeScrollView visible="true" x="{horizontal_x}" y="268" width="608" height="135">
          <XCUIElementTypeCell name="actionGroupCell" label="Copy" enabled="true" visible="true" x="37" y="268" width="82" height="135"/>
        </XCUIElementTypeScrollView>
        <XCUIElementTypeCell name="actionGroupCell" label="Add to Home Screen" enabled="true" visible="{str(add_visible).lower()}"
          x="20" y="{add_y}" width="642" height="51"/>
      </XCUIElementTypeCollectionView></XCUIElementTypeOther></XCUIElementTypePopover>
    </XCUIElementTypeApplication></AppiumAUT>'''


NORMAL_SAFARI = '<AppiumAUT><XCUIElementTypeApplication bundleId="com.apple.mobilesafari"/></AppiumAUT>'


class NativeShareTests(unittest.TestCase):
    def driver(self, sources, repeat=2):
        driver = mock.Mock()
        sequence = iter(source for source in sources for _ in range(repeat))

        def command(method, path, body=None):
            if path == "/source":
                return next(sequence)
            if path.endswith("/enabled"):
                return True
            if path == "/window/rect":
                return {"x": 0, "y": 0, "width": 820, "height": 1180}
            if path == "/actions":
                return None
            raise AssertionError(f"Unexpected native request {method} {path}")

        def find(using, value):
            if '"View More"' in value:
                return "view-more"
            if '"Add to Home Screen"' in value:
                return "add-home"
            if "activityCollectionView" in value:
                return "activity-list"
            raise AssertionError(f"Unexpected native target {using}: {value}")

        driver.command.side_effect = command
        driver.find.side_effect = find
        driver.screenshot.return_value = b"native screenshot"
        return driver

    def test_compact_popover_expands_native_view_more_and_captures_actual_expansion(self):
        compact = menu("Copy", "Add to Bookmarks", "Add to Reading List", "View More")
        expanded = menu("Copy", "View Less", "Add to Home Screen")
        driver = self.driver([compact, expanded])
        with tempfile.TemporaryDirectory() as directory:
            evidence = native_share.open_add_home_screen(driver, SimpleNamespace(artifacts_dir=Path(directory)))
            self.assertTrue((Path(directory) / "share-expanded.png").is_file())
            self.assertIn("Add to Home Screen", (Path(directory) / "share-expanded.source.txt").read_text())
        self.assertTrue(evidence["expanded"])
        self.assertEqual(driver.click.call_args_list, [mock.call("view-more"), mock.call("add-home")])
        driver.execute.assert_not_called()  # no raw screen-coordinate gesture using local popover frames

    def test_delayed_share_presentation_waits_before_any_native_action(self):
        driver = self.driver([NORMAL_SAFARI, NORMAL_SAFARI, menu("Copy", "Add to Home Screen")])
        evidence = native_share.open_add_home_screen(driver, SimpleNamespace())
        self.assertFalse(evidence["expanded"])
        self.assertEqual(driver.click.call_args_list, [mock.call("add-home")])
        source_requests = [call for call in driver.command.call_args_list if call.args[1] == "/source"]
        self.assertEqual(len(source_requests), 6)

    def test_missing_share_never_swipes_the_browser_or_retries_the_share_button(self):
        driver = self.driver([NORMAL_SAFARI])

        def once(predicate, timeout, message):
            self.assertIsNone(predicate())
            raise AssertionError(message)

        with mock.patch.object(native_share, "wait", side_effect=once), \
                self.assertRaisesRegex(AssertionError, "Share did not settle"):
            native_share.open_add_home_screen(driver, SimpleNamespace())
        driver.find.assert_not_called()
        driver.click.assert_not_called()
        driver.execute.assert_not_called()

    def test_expanded_actions_use_only_the_observed_remote_container_gutter(self):
        driver = self.driver([menu("Copy", "View More"), menu("Copy", "View Less"),
                              menu("Copy", "View Less", "Add to Home Screen")])
        evidence = native_share.open_add_home_screen(driver, SimpleNamespace())
        driver.execute.assert_not_called()
        actions = [call for call in driver.command.call_args_list if call.args[:2] == ("POST", "/actions")]
        self.assertEqual(len(actions), 1)
        self.assertEqual(len(evidence["element_swipes"]), 1)
        self.assertEqual(driver.click.call_args_list, [mock.call("view-more"), mock.call("add-home")])

    def test_missing_action_stops_after_five_element_swipes(self):
        driver = self.driver([menu("Copy", "View Less")] * 6)
        with self.assertRaisesRegex(AssertionError, "after five native swipes"):
            native_share.open_add_home_screen(driver, SimpleNamespace())
        driver.execute.assert_not_called()
        self.assertEqual(len([call for call in driver.command.call_args_list if call.args[:2] == ("POST", "/actions")]), 5)
        driver.click.assert_not_called()

    def test_web_page_action_lookalikes_do_not_satisfy_native_share_readiness(self):
        source = ('<AppiumAUT><XCUIElementTypeWebView>' + menu("Copy", "View More")
                  + '</XCUIElementTypeWebView></AppiumAUT>')
        self.assertFalse(native_share.share_state(source)["ready"])

    def test_ax_invisible_collection_with_visible_enabled_cells_is_ready_and_expandable(self):
        compact = menu("Copy", "Add to Bookmarks", "Add to Reading List", "View More", parent_visible=False)
        expanded = menu("Copy", "View Less", "Add to Home Screen", parent_visible=False)
        state = native_share.share_state(compact)
        self.assertTrue(state["ready"])
        self.assertEqual(state["collection_ax_visibility"], ["false"])
        driver = self.driver([compact, expanded])
        native_share.open_add_home_screen(driver, SimpleNamespace())
        self.assertEqual(driver.click.call_args_list, [mock.call("view-more"), mock.call("add-home")])

    def test_gutter_scroll_accepts_visible_descendants_without_parent_ax_visibility(self):
        driver = self.driver([menu("Copy", "View Less", parent_visible=False),
                              menu("Copy", "View Less", "Add to Home Screen", parent_visible=False)])
        native_share.open_add_home_screen(driver, SimpleNamespace())
        driver.execute.assert_not_called()
        self.assertEqual(len([call for call in driver.command.call_args_list if call.args[:2] == ("POST", "/actions")]), 1)

    def test_unrelated_sibling_action_cells_and_disabled_children_do_not_make_share_ready(self):
        empty = menu()
        sibling = '<XCUIElementTypeCell name="actionGroupCell" label="Copy" visible="true" enabled="true"/>'
        self.assertFalse(native_share.share_state(empty.replace('</AppiumAUT>', sibling + '</AppiumAUT>'))["ready"])
        disabled = menu("Copy").replace('enabled="true"', 'enabled="false"')
        self.assertFalse(native_share.share_state(disabled)["ready"])

    def test_landscape_gutter_uses_hidden_action_inset_and_real_remote_origin(self):
        geometry = native_share.share_scroll_geometry(landscape_menu(), {"x": 0, "y": 0, "width": 852, "height": 393})
        self.assertEqual(geometry["left_inset"], 20)
        self.assertEqual(geometry["direction"], "up")
        self.assertEqual(geometry["duration_ms"], 650)
        self.assertEqual(geometry["start"][0], 95)
        self.assertAlmostEqual(geometry["start"][1], 236.6)
        self.assertAlmostEqual(geometry["end"][1], 157.4)
        self.assertLessEqual(abs(geometry["start"][1] - geometry["end"][1]), (392 - 32) * 0.25)
        self.assertTrue(all(95 < 85 + row["x"] for row in geometry["horizontal_lists"]))

    def test_one_native_gutter_scroll_reveals_real_add_home_action(self):
        driver = self.driver([landscape_menu(), landscape_menu(add_visible=True)])
        evidence = native_share.open_add_home_screen(driver, SimpleNamespace())
        self.assertEqual(driver.click.call_args_list, [mock.call("add-home")])
        self.assertEqual(len(evidence["element_swipes"]), 1)
        gesture = evidence["element_swipes"][0]["native_gesture"]
        self.assertEqual(gesture, {"start": {"x": 95, "y": 237}, "end": {"x": 95, "y": 157}})
        actions = next(call.args[2] for call in driver.command.call_args_list if call.args[:2] == ("POST", "/actions"))
        move = next(action for action in actions["actions"][0]["actions"] if action.get("duration") == 650)
        self.assertEqual(move["type"], "pointerMove")

    def test_overshot_hidden_target_reverses_direction_then_selects_visible_action(self):
        driver = self.driver([landscape_menu(), landscape_menu(add_y=76), landscape_menu(add_visible=True)])
        evidence = native_share.open_add_home_screen(driver, SimpleNamespace())
        self.assertEqual([step["direction"] for step in evidence["element_swipes"]], ["up", "down"])
        down = evidence["element_swipes"][1]["native_gesture"]
        self.assertLess(down["start"]["y"], down["end"]["y"])
        self.assertEqual(driver.click.call_args_list, [mock.call("add-home")])
        self.assertEqual(evidence["initial"]["target"]["reported_bounds"]["y"], 412)
        self.assertFalse(evidence["element_swipes"][0]["after"]["target"]["visible"])

    def test_inconsistent_or_intercepted_native_gutter_fails_before_input(self):
        window = {"x": 0, "y": 0, "width": 852, "height": 393}
        wrong_size = landscape_menu().replace('name="ShareSheet.RemoteContainerView" visible="true" x="85" y="1" width="682"',
                                               'name="ShareSheet.RemoteContainerView" visible="true" x="85" y="1" width="650"')
        for source in (wrong_size, landscape_menu(horizontal_x=0)):
            with self.subTest(source=source), self.assertRaises(AssertionError):
                native_share.share_scroll_geometry(source, window)

    def test_transient_portrait_collection_waits_for_two_matching_landscape_samples_before_input(self):
        settled = landscape_menu(add_visible=True)
        transition = settled.replace('name="activityCollectionView" visible="true" x="0" y="0" width="682" height="392"',
                                     'name="activityCollectionView" visible="true" x="0" y="0" width="375" height="384"')
        self.assertFalse(native_share.share_state(transition)["ready"])
        self.assertTrue(native_share.share_state(settled)["ready"])
        driver = self.driver([transition, settled, settled], repeat=1)
        native_share.open_add_home_screen(driver, SimpleNamespace())
        events = driver.method_calls
        source_positions = [i for i, call in enumerate(events) if call[0] == "command" and call.args[:2] == ("GET", "/source")]
        click_position = next(i for i, call in enumerate(events) if call[0] == "click")
        self.assertEqual(len(source_positions), 3)
        self.assertLess(source_positions[-1], click_position)
        driver.execute.assert_not_called()

    def test_an_interrupted_ready_sample_must_stabilize_again_before_input(self):
        settled = menu("Copy", "Add to Home Screen")
        driver = self.driver([settled, NORMAL_SAFARI, settled, settled], repeat=1)
        result = native_share.open_add_home_screen(driver, SimpleNamespace())
        self.assertEqual(result["initial"]["stable_samples"], 2)
        source_requests = [call for call in driver.command.call_args_list if call.args[:2] == ("GET", "/source")]
        self.assertEqual(len(source_requests), 4)
        self.assertEqual(driver.click.call_args_list, [mock.call("add-home")])


if __name__ == "__main__":
    unittest.main()
