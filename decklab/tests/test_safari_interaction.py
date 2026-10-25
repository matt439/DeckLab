"""Harness safeguards, not evidence that iOS Safari or native UI passed."""
import copy
import json
import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ElementTree
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlsplit

from decklab.safari import flows, interaction


class VisibleBoundsTests(unittest.TestCase):
    def setUp(self):
        self.measured = {"rect": {"left": 20, "top": 200, "right": 200, "bottom": 244,
                                  "width": 180, "height": 44},
                         "visible": {"left": 20, "top": 200, "right": 200, "bottom": 244},
                         "shown": True}

    def test_dom_presence_is_insufficient_when_keyboard_or_ancestor_clips_control(self):
        interaction.fully_visible(self.measured, "Save")
        for side, clipped in (("bottom", 220), ("left", 40), ("top", 215), ("right", 170)):
            value = copy.deepcopy(self.measured)
            value["visible"][side] = clipped
            with self.subTest(side=side), self.assertRaisesRegex(AssertionError, "clipped"):
                interaction.fully_visible(value, "Save")

    def test_hidden_and_missing_controls_fail_even_with_good_rectangles(self):
        hidden = copy.deepcopy(self.measured)
        hidden["shown"] = False
        with self.assertRaisesRegex(AssertionError, "visible size"):
            interaction.fully_visible(hidden, "Swipe hint")
        with self.assertRaisesRegex(AssertionError, "absent"):
            interaction.fully_visible(None, "Swipe hint")


class NativeGestureTests(unittest.TestCase):
    def test_native_home_button_name_is_forwarded_as_argument(self):
        driver = mock.Mock()
        interaction.mobile(driver, "pressButton", name="home")
        driver.execute.assert_called_once_with("mobile: pressButton", [{"name": "home"}])

    def test_transformed_native_finger_is_used_instead_of_javascript_input(self):
        driver = mock.Mock()
        driver.command.return_value = {"x": 0, "y": 0, "width": 393, "height": 852}
        result = interaction.touch(driver,
            {"offsetX": 5, "offsetY": 90, "pixelRatioX": 0.5, "pixelRatioY": 2},
            (200, 150), (80, 150))
        self.assertEqual(result, {"start": {"x": 105, "y": 390}, "end": {"x": 45, "y": 390}})
        driver.switch_context.assert_called_once_with("NATIVE_APP")
        driver.execute.assert_not_called()
        method, path, payload = next(call.args for call in driver.command.call_args_list
                                     if call.args[:2] == ("POST", "/actions"))
        self.assertEqual((method, path), ("POST", "/actions"))
        finger = payload["actions"][0]
        self.assertEqual(finger["parameters"], {"pointerType": "touch"})
        self.assertEqual([item["type"] for item in finger["actions"]],
                         ["pointerMove", "pointerDown", "pause", "pointerMove", "pointerUp"])
        driver.command.assert_called_with("DELETE", "/actions")

    def test_failed_touch_releases_finger_so_later_cases_can_recover(self):
        driver = mock.Mock()
        driver.command.side_effect = [{"x": 0, "y": 0, "width": 393, "height": 852},
                                      RuntimeError("XCTest touch failed"), None]
        with self.assertRaisesRegex(RuntimeError, "XCTest touch failed"):
            interaction.touch(driver,
                {"offsetX": 0, "offsetY": 0, "pixelRatioX": 1, "pixelRatioY": 1}, (30, 50), (130, 50))
        driver.command.assert_called_with("DELETE", "/actions")

    def test_native_save_tap_uses_one_finger_at_verified_keyboard_open_bounds(self):
        driver = mock.Mock()
        driver.command.return_value = {"x": 0, "y": 0, "width": 393, "height": 852}
        result = interaction.tap_native_rect(driver, {"x": 289, "y": 476, "width": 88, "height": 45})
        self.assertEqual(result, {"start": {"x": 333, "y": 498}, "end": {"x": 333, "y": 498}})
        requests = [call for call in driver.command.call_args_list if call.args[:2] == ("POST", "/actions")]
        self.assertEqual(len(requests), 1)
        self.assertEqual([item["type"] for item in requests[0].args[2]["actions"][0]["actions"]],
                         ["pointerMove", "pointerDown", "pause", "pointerUp"])
        driver.click.assert_not_called()
        driver.execute.assert_not_called()

    def test_outside_native_window_endpoints_are_rejected_before_sending_input(self):
        for start, end in (((-139, 100), (100, 100)), ((100, 100), (393, 100)),
                           ((100, -1), None), ((100, 100), (100, 852))):
            driver = mock.Mock()
            driver.command.return_value = {"x": 0, "y": 0, "width": 393, "height": 852}
            with self.subTest(start=start, end=end), self.assertRaisesRegex(AssertionError, "outside the native window"):
                interaction.touch(driver, {"offsetX": 0, "offsetY": 0, "pixelRatioX": 1, "pixelRatioY": 1}, start, end)
            driver.command.assert_called_once_with("GET", "/window/rect")


class AnchorTransformTests(unittest.TestCase):
    def setUp(self):
        self.dom = {"rect": {"left": 36.5, "top": 223.5, "right": 356.5, "bottom": 669.4,
                             "width": 320, "height": 445.9},
                    "visible": {"left": 36.5, "top": 223.5, "right": 356.5, "bottom": 574.5},
                    "viewport": {"left": 0, "top": 0, "width": 393, "height": 695}, "shown": True}
        self.native = {"x": 36.5, "y": 283.5, "width": 320, "height": 351}
        self.window = {"x": 0, "y": 0, "width": 393, "height": 852}
        self.webview = {"x": 0, "y": 60, "width": 393, "height": 695}

    def test_current_control_width_maps_responsive_coordinates_despite_vertical_clipping(self):
        transform = interaction.measured_transform(self.dom, self.native, self.window, "Show Llanowar Elves larger")
        driver = mock.Mock()
        driver.command.return_value = self.window
        gesture = interaction.touch(driver, transform, (276.5, 399), (141.5, 399))
        self.assertEqual(gesture, {"start": {"x": 276, "y": 459}, "end": {"x": 142, "y": 459}})
        self.assertEqual(transform["pixelRatioY"], 1)
        self.assertEqual(transform["anchor"]["native"]["height"], 351)

    def test_absent_zero_hidden_or_horizontally_clipped_anchor_is_rejected(self):
        variants = [None]
        for key, value in (("hidden", False), ("zero", 0), ("clipped", 60), ("top_clipped", 240)):
            dom = copy.deepcopy(self.dom)
            if key == "hidden":
                dom["shown"] = value
            elif key == "zero":
                dom["rect"]["width"] = value
            else:
                dom["visible"]["left" if key == "clipped" else "top"] = value
            variants.append(dom)
        for dom in variants:
            with self.subTest(dom=dom), self.assertRaises(AssertionError):
                interaction.measured_transform(dom, self.native, self.window, "Receipt picture")

    def test_native_clipping_and_implausible_scale_include_measurements_in_error(self):
        for native in ({**self.native, "x": -4}, {**self.native, "width": 0},
                       {**self.native, "width": 64}, {**self.native, "width": float("nan")}):
            with self.subTest(native=native), self.assertRaisesRegex(AssertionError, "native.*dom|dom.*native"):
                interaction.measured_transform(self.dom, native, self.window, "Receipt picture")

    def test_control_matching_uses_exact_accessible_label(self):
        driver = mock.Mock()
        driver.execute.return_value = "Show Llanowar Elves larger, with its rules text"
        driver.command.return_value = self.window
        fixture = SimpleNamespace(base_url="http://127.0.0.1:9234")
        with mock.patch.object(interaction, "bounds", return_value=self.dom), \
                mock.patch.object(interaction, "native_element", return_value="exact-image") as find, \
                mock.patch.object(interaction, "native_rect", side_effect=[self.native, self.webview]), \
                mock.patch.object(interaction, "web"):
            transform = interaction.anchor_transform(driver, fixture, ".rcpt-sheet-pic")
        find.assert_called_once_with(driver, "Show Llanowar Elves larger, with its rules text", webview_only=True)
        self.assertEqual(transform["offsetY"], 60)

    def test_moving_anchor_cannot_silently_supply_stale_coordinates(self):
        driver = mock.Mock()
        driver.execute.return_value = "Close"
        driver.command.return_value = self.window
        moved = copy.deepcopy(self.dom)
        moved["rect"]["top"] += 30
        with mock.patch.object(interaction, "bounds", side_effect=[self.dom, moved]), \
                mock.patch.object(interaction, "native_element", return_value="close"), \
                mock.patch.object(interaction, "native_rect", side_effect=[self.native, self.webview]), \
                mock.patch.object(interaction, "web"), self.assertRaisesRegex(AssertionError, "moved"):
            interaction.anchor_transform(driver, SimpleNamespace(base_url="http://127.0.0.1:9234"), ".viewer-close")

    def test_duplicate_safari_and_hidden_sheet_close_cannot_anchor_visible_viewer(self):
        tree = ElementTree.fromstring('''<AppiumAUT><XCUIElementTypeApplication>
          <XCUIElementTypeButton id="safari-tab" name="Close" visible="true"/>
          <XCUIElementTypeWebView id="webview">
            <XCUIElementTypeButton id="inert-sheet" name="Close" visible="false"/>
            <XCUIElementTypeButton id="viewer-close" name="Close" visible="true"/>
          </XCUIElementTypeWebView></XCUIElementTypeApplication></AppiumAUT>''')
        driver = mock.Mock()
        driver.execute.return_value = "Close"
        window = {"x": 0, "y": 0, "width": 834, "height": 1194}
        rectangles = {"safari-tab": {"x": 411, "y": 88, "width": 33, "height": 32},
                      "inert-sheet": {"x": 500, "y": 300, "width": 44, "height": 44},
                      "viewer-close": {"x": 768, "y": 108, "width": 44, "height": 44},
                      "webview": {"x": 0, "y": 100, "width": 834, "height": 1094}}

        def find(using, selector):
            if "type == 'XCUIElementTypeWebView'" in selector:
                return "webview"
            scoped = using == "-ios class chain" and selector.startswith("**/XCUIElementTypeWebView/**/")
            candidates = tree.findall(".//XCUIElementTypeWebView//XCUIElementTypeButton" if scoped
                                      else ".//XCUIElementTypeButton")
            return next(element.get("id") for element in candidates if element.get("name") == "Close"
                        and ("visible == 1" not in selector or element.get("visible") == "true"))

        def command(method, path, body=None):
            if path == "/window/rect":
                return window
            if path.startswith("/element/"):
                return rectangles[path.split("/")[2]]

        driver.find.side_effect, driver.command.side_effect = find, command
        measured = {"rect": {"left": 768, "top": 8, "right": 812, "bottom": 52, "width": 44, "height": 44},
                    "visible": {"left": 768, "top": 8, "right": 812, "bottom": 52}, "shown": True,
                    "viewport": {"left": 0, "top": 0, "width": 834, "height": 1094}}
        with mock.patch.object(interaction, "bounds", return_value=measured), mock.patch.object(interaction, "web"):
            transform = interaction.anchor_transform(driver, SimpleNamespace(base_url="http://127.0.0.1:9234"), ".viewer-close")
        self.assertEqual(transform["anchor"]["native"], rectangles["viewer-close"])
        self.assertEqual((transform["offsetX"], transform["offsetY"], transform["pixelRatioX"]), (0, 100, 1))
        gesture = interaction.touch(driver, transform, (800, 300), (30, 300))
        self.assertEqual(gesture, {"start": {"x": 800, "y": 400}, "end": {"x": 30, "y": 400}})

    def test_safari_chrome_rectangle_cannot_map_the_complete_page_viewport(self):
        measured = {"rect": {"left": 768, "top": 8, "right": 812, "bottom": 52, "width": 44, "height": 44},
                    "visible": {"left": 768, "top": 8, "right": 812, "bottom": 52}, "shown": True,
                    "viewport": {"left": 0, "top": 0, "width": 834, "height": 1094}}
        with self.assertRaisesRegex(AssertionError, "disagrees with its native WebView"):
            interaction.measured_transform(measured, {"x": 411, "y": 88, "width": 33, "height": 32},
                {"x": 0, "y": 0, "width": 834, "height": 1194}, "Close",
                {"x": 0, "y": 100, "width": 834, "height": 1094})

    def test_rounding_small_native_tile_does_not_distort_full_landscape_viewport(self):
        measured = {"rect": {"left": 59.165, "top": 216, "right": 233.665, "bottom": 460.5,
                              "width": 174.5, "height": 244.5},
                    "visible": {"left": 59.165, "top": 216, "right": 233.665, "bottom": 393}, "shown": True,
                    "viewport": {"left": 0, "top": 0, "width": 852, "height": 393}}
        window = {"x": 0, "y": 0, "width": 852, "height": 393}
        transform = interaction.measured_transform(measured,
            {"x": 59, "y": 216, "width": 175, "height": 245}, window, "Receipt tile", window)
        self.assertEqual(transform["pixelRatioX"], 1)
        self.assertEqual(transform["anchor"]["mapped_viewport"], {"left": 0, "top": 0, "right": 852, "bottom": 393})


class NativeFieldAndHomeScreenTests(unittest.TestCase):
    def test_partly_visible_receipt_tile_gets_one_raw_native_tap_with_exact_label(self):
        driver = mock.Mock()
        driver.execute.return_value = "Llanowar Elves: check and edit"
        native = {"x": 16, "y": 260, "width": 180, "height": 250}
        window = {"x": 0, "y": 0, "width": 393, "height": 852}
        driver.command.side_effect = [True, native, window, {"x": 0, "y": 60, "width": 393, "height": 695}]
        measured = {"rect": {"left": 16, "right": 196, "top": 200, "bottom": 450, "width": 180, "height": 250},
                    "visible": {"left": 16, "right": 196, "top": 200, "bottom": 293},
                    "viewport": {"left": 0, "top": 0, "width": 393, "height": 695}, "shown": True, "disabled": False}
        fixture = SimpleNamespace(base_url="http://127.0.0.1:9234")
        with mock.patch.object(interaction, "bounds", return_value=measured), \
                mock.patch.object(interaction, "visible_button_hit_point", return_value={"point": {"x": 106, "y": 246.5}}), \
                mock.patch.object(interaction, "native_element", return_value="tile") as find, \
                mock.patch.object(interaction, "touch", return_value={"start": {"x": 106, "y": 306}}) as touch, \
                mock.patch.object(interaction, "web"):
            opened = interaction.tap_native_visible_part(driver, fixture, ".card-tile-open")
        find.assert_called_once_with(driver, "Llanowar Elves: check and edit", require_visible=False, webview_only=True)
        touch.assert_called_once()
        self.assertEqual(touch.call_args.args[2], (106, 246.5))
        self.assertEqual(opened["coordinate_transform"]["offsetY"], 60)
        driver.click.assert_not_called()

    def test_offscreen_receipt_tile_is_revealed_before_single_native_tap(self):
        driver = mock.Mock()
        driver.execute.return_value = "Llanowar Elves: check and edit"
        driver.command.side_effect = [True, {"x": 16, "y": 260, "width": 180, "height": 250},
                                      {"x": 0, "y": 0, "width": 393, "height": 852},
                                      {"x": 0, "y": 60, "width": 393, "height": 695}]
        measured = {"rect": {"left": 16, "right": 196, "top": 200, "bottom": 450, "width": 180, "height": 250},
                    "visible": {"left": 16, "right": 196, "top": 200, "bottom": 293},
                    "viewport": {"left": 0, "top": 0, "width": 393, "height": 695}, "shown": True, "disabled": False}
        below = copy.deepcopy(measured)
        below["rect"].update(top=900, bottom=1150)
        below["visible"].update(top=900, bottom=695)
        fixture = SimpleNamespace(base_url="http://127.0.0.1:9234")
        with mock.patch.object(interaction, "bounds", side_effect=[below, measured]), \
                mock.patch.object(interaction, "visible_button_hit_point", return_value={"point": {"x": 106, "y": 246.5}}), \
                mock.patch.object(interaction, "native_element", return_value="tile"), \
                mock.patch.object(interaction, "native_scroll_towards", return_value={}) as scroll, \
                mock.patch.object(interaction, "touch") as touch, mock.patch.object(interaction, "web"):
            interaction.tap_native_visible_part(driver, fixture, ".card-tile-open")
        scroll.assert_called_once_with(driver, fixture, below, upwards=True, standalone=False)
        touch.assert_called_once()

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the observed hit-test check")
    def test_fixed_footer_over_tile_center_uses_actual_uncovered_descendant_hit(self):
        driver = mock.Mock()
        driver.find.return_value = "webview"
        window = {"x": 0, "y": 0, "width": 852, "height": 393}
        measured = {"rect": {"left": 59.165, "top": 216, "right": 233.665, "bottom": 460.5,
                              "width": 174.5, "height": 244.5},
                    "visible": {"left": 59.165, "top": 216, "right": 233.665, "bottom": 393},
                    "viewport": {"left": 0, "top": 0, "width": 852, "height": 393}, "shown": True, "disabled": False}

        def execute(script, args=None):
            if "elementFromPoint" not in script:
                return "Llanowar Elves: check and edit"
            # Execute the production observation script against a descendant
            # image and a fixed footer covering the tile's geometric center.
            completed = subprocess.run([shutil.which("node"), "-e", """
              const fs=require('fs'), input=JSON.parse(fs.readFileSync(0,'utf8'));
              const image={tagName:'IMG',getAttribute:()=>null};
              const footer={tagName:'FOOTER',getAttribute:n=>n==='class'?'receipt-footer':null};
              const button={contains:node=>node===image};
              global.document={querySelector:()=>button,elementFromPoint:(x,y)=>y>=300?footer:image};
              process.stdout.write(JSON.stringify(Function(input.script).apply(null,input.args)));
            """], input=json.dumps({"script": script, "args": args}), text=True,
                capture_output=True, check=True)
            return json.loads(completed.stdout)

        def command(method, path, body=None):
            if path.endswith("/enabled"):
                return True
            if path == "/element/tile/rect":
                return {"x": 59, "y": 216, "width": 175, "height": 245}
            if path.endswith("/rect"):
                return window

        driver.execute.side_effect, driver.command.side_effect = execute, command
        with mock.patch.object(interaction, "bounds", return_value=measured), \
                mock.patch.object(interaction, "native_element", return_value="tile"), \
                mock.patch.object(interaction, "web"), mock.patch.object(interaction, "native_scroll_towards") as scroll:
            opened = interaction.tap_native_visible_part(driver,
                SimpleNamespace(base_url="http://127.0.0.1:9234"), ".card-tile-open")
        hit = opened["hit_test"]
        self.assertEqual(len(hit["samples"]), 9)
        self.assertFalse(hit["samples"][0]["on_target"])
        self.assertEqual(hit["samples"][0]["hit"]["tag"], "FOOTER")
        self.assertLess(hit["point"]["y"], 300)
        actions = [call for call in driver.command.call_args_list if call.args[:2] == ("POST", "/actions")]
        self.assertEqual(len(actions), 1)
        self.assertLess(actions[0].args[2]["actions"][0]["actions"][0]["y"], 300)
        scroll.assert_not_called()
        driver.click.assert_not_called()

    def test_fully_occluded_tile_scrolls_before_one_observed_native_tap(self):
        driver = mock.Mock()
        driver.execute.return_value = "Llanowar Elves: check and edit"
        window = {"x": 0, "y": 0, "width": 393, "height": 852}
        driver.command.side_effect = [True, {"x": 16, "y": 260, "width": 180, "height": 250}, window,
                                      {"x": 0, "y": 60, "width": 393, "height": 695}]
        measured = {"rect": {"left": 16, "right": 196, "top": 200, "bottom": 450, "width": 180, "height": 250},
                    "visible": {"left": 16, "right": 196, "top": 200, "bottom": 293},
                    "viewport": {"left": 0, "top": 0, "width": 393, "height": 695}, "shown": True, "disabled": False}
        blocked = {"point": None, "samples": [{"on_target": False}]}
        fixture = SimpleNamespace(base_url="http://127.0.0.1:9234")
        with mock.patch.object(interaction, "bounds", return_value=measured), \
                mock.patch.object(interaction, "visible_button_hit_point", side_effect=[blocked, {"point": {"x": 106, "y": 246.5}}]), \
                mock.patch.object(interaction, "native_element", return_value="tile"), \
                mock.patch.object(interaction, "native_scroll_towards", return_value={}) as scroll, \
                mock.patch.object(interaction, "touch") as touch, mock.patch.object(interaction, "web"):
            opened = interaction.tap_native_visible_part(driver, fixture, ".card-tile-open")
        scroll.assert_called_once_with(driver, fixture, measured, upwards=True, standalone=False)
        self.assertEqual(opened["native_preparation"][0]["hit_test"], blocked)
        touch.assert_called_once()

    def test_quantity_focus_uses_native_field_bounds_after_native_scroll(self):
        driver = mock.Mock()
        driver.execute.return_value = "Copies of Forest"
        driver.find.return_value = "native-forest-field"
        field_rect = {"x": 60, "y": 400, "width": 44, "height": 44}
        window = {"x": 0, "y": 0, "width": 393, "height": 852}
        view_rect = {"x": 0, "y": 60, "width": 393, "height": 695}
        driver.command.side_effect = [view_rect, window, field_rect, window]
        dom = {"rect": {"left": 60, "right": 104, "top": 340, "bottom": 384, "width": 44, "height": 44},
               "visible": {"left": 60, "right": 104, "top": 340, "bottom": 384}, "shown": True,
               "viewport": {"left": 0, "width": 393}}
        fixture = SimpleNamespace(base_url="http://127.0.0.1:9234")
        clipped = copy.deepcopy(dom)
        clipped["rect"].update(top=800, bottom=844)
        clipped["visible"].update(top=800, bottom=695)
        with mock.patch.object(interaction, "mobile") as mobile, \
                mock.patch.object(interaction, "web"), mock.patch.object(interaction, "bounds", side_effect=[clipped, dom, dom]), \
                mock.patch.object(interaction, "raw_swipe", return_value={"start": {"x": 255, "y": 602}}) as swipe, \
                mock.patch.object(interaction, "tap_native_rect", return_value={"start": {"x": 82, "y": 422}}) as tap:
            result = interaction.focus_native_field(driver, fixture, ".qty-input")
        mobile.assert_not_called()  # Xcode 27's private scroll-to-element selector is not used.
        swipe.assert_called_once()
        tap.assert_called_once_with(driver, field_rect)
        self.assertEqual(result["label"], "Copies of Forest")
        self.assertIn("XCUIElementTypeTextField", driver.find.call_args.args[1])
        driver.click.assert_not_called()

    def test_wide_editor_scroll_stays_in_target_column_away_from_add_panel(self):
        driver = mock.Mock()
        driver.execute.return_value = "Copies of Forest"
        driver.find.return_value = "native-forest-field"
        window = {"x": 0, "y": 0, "width": 1194, "height": 834}
        field = {"x": 72, "y": 400, "width": 44, "height": 44}
        driver.command.side_effect = [window, window, field, window]
        shown = {"rect": {"left": 72, "right": 116, "top": 400, "bottom": 444, "width": 44, "height": 44},
                 "visible": {"left": 72, "right": 116, "top": 400, "bottom": 444}, "shown": True,
                 "viewport": {"left": 0, "width": 1194}}
        below = copy.deepcopy(shown)
        below["rect"].update(top=1000, bottom=1044)
        below["visible"].update(top=1000, bottom=834)
        with mock.patch.object(interaction, "web"), \
                mock.patch.object(interaction, "bounds", side_effect=[below, shown, shown]), \
                mock.patch.object(interaction, "raw_swipe", return_value={}) as swipe, \
                mock.patch.object(interaction, "tap_native_rect"):
            interaction.focus_native_field(driver, SimpleNamespace(base_url="http://127.0.0.1:9234"), ".qty-input")
        start, end = swipe.call_args.args[1:]
        self.assertEqual(start[0], 94)
        self.assertEqual(end[0], 94)
        self.assertLess(start[0], 720)  # the separate Add panel starts in the right column

    def test_standalone_profile_uses_observed_full_native_label_and_center(self):
        driver = mock.Mock()
        driver.execute.return_value = "Matt Tap to continue"
        rect = {"x": 166, "y": 300, "width": 520, "height": 94}
        driver.command.return_value = {"x": 0, "y": 0, "width": 852, "height": 393}
        fixture = SimpleNamespace(base_url="http://127.0.0.1:9234", profile_name="Matt")
        with mock.patch.object(interaction, "native_element", return_value="matt-button") as find, \
                mock.patch.object(interaction, "native_rect", return_value=rect), \
                mock.patch.object(interaction, "tap_native_rect", return_value={"start": {"x": 426, "y": 347}}) as tap, \
                mock.patch.object(interaction, "web") as reconnect:
            result = interaction.choose_native_profile(driver, fixture)
        find.assert_called_once_with(driver, "Matt Tap to continue", webview_only=True)
        tap.assert_called_once_with(driver, rect)
        reconnect.assert_called_once_with(driver, fixture.base_url, standalone=True)
        self.assertEqual(result["observed_label"], "Matt Tap to continue")
        driver.click.assert_not_called()

    def test_reload_button_uses_observed_enabled_native_control(self):
        driver = mock.Mock()
        driver.execute.return_value = "Reload page"
        driver.command.return_value = True
        rect = {"x": 100, "y": 150, "width": 100, "height": 44}
        measured = {"rect": {"left": 100, "right": 200, "top": 90, "bottom": 134, "width": 100, "height": 44},
                    "visible": {"left": 100, "right": 200, "top": 90, "bottom": 134}, "shown": True, "disabled": False}
        fixture = SimpleNamespace(base_url="http://127.0.0.1:9234")
        with mock.patch.object(interaction, "bounds", return_value=measured), \
                mock.patch.object(interaction, "native_element", return_value="reload") as find, \
                mock.patch.object(interaction, "native_rect", return_value=rect), \
                mock.patch.object(interaction, "tap_native_rect") as tap, mock.patch.object(interaction, "web"):
            result = interaction.tap_native_button(driver, fixture, "#build-warning button")
        find.assert_called_once_with(driver, "Reload page", webview_only=True)
        tap.assert_called_once_with(driver, rect)
        self.assertEqual(result["dom"], measured)
        driver.click.assert_not_called()

    def test_add_home_waits_for_both_native_metadata_and_enabled_control(self):
        driver = mock.Mock()
        driver.find.return_value = "native-add"
        enabled = iter([False, True])
        iteration = 0

        def command(method, path, body=None):
            nonlocal iteration
            if path.endswith("/enabled"):
                iteration += 1
                return next(enabled)
            if path == "/elements":
                return [{"element-6066-11e4-a52e-4f735466cecf": "native-name"}]
            if path.endswith("/attribute/value"):
                return "" if iteration == 1 else "Deck Lab"
            return {"x": 310, "y": 78, "width": 64, "height": 44}

        driver.command.side_effect = command
        ready = interaction.native_home_screen_ready(driver, timeout=2)
        self.assertEqual(ready["icon_name"], "Deck Lab")
        self.assertEqual(iteration, 2)
        driver.click.assert_not_called()

    def test_populated_name_does_not_make_disabled_add_ready(self):
        driver = mock.Mock()
        driver.find.return_value = "native-add"
        driver.command.side_effect = [False, [{"ELEMENT": "native-name"}], "Deck Lab"]

        def one_attempt(predicate, timeout, message):
            self.assertIsNone(predicate())
            raise AssertionError(message)

        with mock.patch.object(interaction, "wait", side_effect=one_attempt), \
                self.assertRaisesRegex(AssertionError, "add_enabled.*False"):
            interaction.native_home_screen_ready(driver)
        driver.click.assert_not_called()

    def test_home_is_not_pressed_until_native_add_sheet_dismisses(self):
        driver = mock.Mock()
        driver.command.side_effect = [[{"ELEMENT": "still-open-add"}], []]
        interaction.wait_native_add_dismissed(driver)
        self.assertEqual(driver.command.call_count, 2)
        driver.execute.assert_not_called()


class HomeScreenPageTests(unittest.TestCase):
    @staticmethod
    def source(page, icon_page=2, total=2):
        shown = page == icon_page
        return f'''<AppiumAUT><XCUIElementTypeApplication bundleId="com.apple.springboard">
          <XCUIElementTypePageIndicator visible="true" value="Page {page} of {total}"/>
          <XCUIElementTypeIcon name="Safari" label="Safari" visible="true" accessible="true"
            x="120" y="751" width="69" height="69"/>
          <XCUIElementTypeIcon name="Deck Lab" label="Deck Lab" visible="{str(shown).lower()}"
            accessible="{str(shown).lower()}" x="{299 if shown else 0}" y="{275 if shown else 0}"
            width="{68 if shown else 0}" height="{91 if shown else 0}"/>
        </XCUIElementTypeApplication></AppiumAUT>'''

    def test_zero_bounds_icon_on_another_page_is_not_treated_as_visible(self):
        state = interaction.home_screen_state(self.source(1))
        self.assertEqual((state["page"], state["total"]), (1, 2))
        self.assertEqual([icon["name"] for icon in state["icons"]], ["Safari"])
        self.assertEqual(interaction.home_screen_state(self.source(2))["icons"][-1]["name"], "Deck Lab")

    def test_observed_second_page_is_reached_by_native_swipe_before_icon_tap(self):
        driver = mock.Mock()
        driver.find.return_value = "installed-icon"
        pages = iter([self.source(1), self.source(2)])

        def command(method, path, body=None):
            if path == "/source":
                return next(pages)
            if path == "/window/rect":
                return {"x": 0, "y": 0, "width": 393, "height": 852}
            if path.endswith("/rect"):
                return {"x": 299, "y": 275, "width": 68, "height": 91}

        driver.command.side_effect = command
        launch = interaction.launch_home_screen_icon(driver, "Deck Lab")
        self.assertEqual([entry["page"] for entry in launch["pages_seen"]], [1, 2])
        self.assertEqual((launch["native_swipes"][0]["from"], launch["native_swipes"][0]["to"]), (1, 2))
        actions = [call for call in driver.command.call_args_list if call.args[:2] == ("POST", "/actions")]
        self.assertEqual(len(actions), 1)  # one genuine Home Screen swipe
        driver.execute.assert_not_called()
        driver.click.assert_called_once_with("installed-icon")
        self.assertEqual(launch["native_icon_click"], {"element": "installed-icon", "observed_name": "Deck Lab"})

    def test_landscape_springboard_with_portrait_child_coordinates_uses_native_icon_click(self):
        driver = mock.Mock()
        driver.current_app = "com.apple.springboard"
        driver.find.return_value = "decklab-icon"
        source = '''<AppiumAUT><XCUIElementTypeApplication bundleId="com.apple.springboard"
          x="0" y="0" width="1180" height="820">
          <XCUIElementTypeWindow x="0" y="0" width="820" height="1180">
            <XCUIElementTypePageIndicator visible="true" value="Page 2 of 2"/>
            <XCUIElementTypeIcon name="Deck Lab" label="Deck Lab" visible="true" accessible="true"
              x="529" y="471" width="96" height="74"/>
          </XCUIElementTypeWindow></XCUIElementTypeApplication></AppiumAUT>'''
        portrait_rect = {"x": 529, "y": 471, "width": 96, "height": 74}

        def command(method, path, body=None):
            if path == "/source":
                return source
            if path == "/window/rect":
                return {"x": 0, "y": 0, "width": 1180, "height": 820}
            if path == "/element/decklab-icon/rect":
                return portrait_rect

        def click(element):
            self.assertEqual(element, "decklab-icon")
            driver.current_app = "Deck Lab standalone"

        driver.command.side_effect, driver.click.side_effect = command, click
        launch = interaction.launch_home_screen_icon(driver, "Deck Lab")
        self.assertEqual(driver.current_app, "Deck Lab standalone")
        driver.click.assert_called_once_with("decklab-icon")
        self.assertEqual(launch["icon_rect"], portrait_rect)
        self.assertEqual(launch["native_icon_click"]["observed_name"], "Deck Lab")
        self.assertNotIn("native_launch_tap", launch)
        self.assertFalse(any(call.args[:2] == ("POST", "/actions") for call in driver.command.call_args_list))
        driver.execute.assert_not_called()  # No alternate launchApp or guessed rotation input.

    def test_missing_icon_stops_after_all_observed_pages_without_add_retry(self):
        driver = mock.Mock()
        pages = iter([self.source(2, icon_page=3), self.source(1, icon_page=3)])

        def command(method, path, body=None):
            if path == "/source":
                return next(pages)
            if path == "/window/rect":
                return {"x": 0, "y": 0, "width": 393, "height": 852}

        driver.command.side_effect = command
        with self.assertRaisesRegex(AssertionError, "absent on all observed pages"):
            interaction.launch_home_screen_icon(driver, "Deck Lab")
        actions = [call for call in driver.command.call_args_list if call.args[:2] == ("POST", "/actions")]
        self.assertEqual(len(actions), 1)
        driver.find.assert_not_called()

    def test_unrelated_app_or_unbounded_page_indicator_fails_before_gestures(self):
        for source in ("<AppiumAUT><XCUIElementTypeApplication bundleId='com.apple.mobilesafari'/></AppiumAUT>",
                       self.source(1, total=99)):
            with self.subTest(source=source), self.assertRaises(AssertionError):
                interaction.home_screen_state(source)


class ContextSelectionTests(unittest.TestCase):
    class Driver:
        def __init__(self):
            self.context = "NATIVE_APP"
            self.commands = []
            self.pages = {"WEBVIEW_old": ("http://127.0.0.1:9234/?profile=matt#/receipt?order=test", False),
                          "WEBVIEW_edit": ("http://127.0.0.1:9234/?profile=matt#/edit?id=casual/test", False),
                          "WEBVIEW_home": ("http://127.0.0.1:9234/", True)}
            self.documents = {name: {"time_origin": 1000 + i, "dialog_open": False, "draft": None}
                              for i, name in enumerate(self.pages)}
            self.visibility = {name: "visible" for name in self.pages}
            self.viewport_heights = {name: 700 for name in self.pages}
            self.refreshes_document = True
            self.refresh_url = None

        def contexts(self):
            return ["NATIVE_APP", *self.pages]

        def switch_context(self, name):
            self.context = name

        def execute(self, script, args=None):
            if script == "return performance.timeOrigin;":
                return self.documents[self.context]["time_origin"]
            if "performance.timeOrigin !==" in script:
                return (self.documents[self.context]["time_origin"] != args[0]
                        and self.pages[self.context][0] == args[1])
            if "href:location.href" in script:
                href, standalone = self.pages[self.context]
                parsed = urlsplit(href)
                return {"origin": f"{parsed.scheme}://{parsed.netloc}", "href": href, "standalone": standalone,
                        "visibilityState": self.visibility.get(self.context, "visible")}
            if script == "return visualViewport.height;":
                return self.viewport_heights[self.context]
            return True

        def command(self, method, path, body=None):
            self.commands.append((method, path, body))
            if (method, path) == ("GET", "/context"):
                return self.context
            if (method, path) == ("POST", "/refresh") and self.refreshes_document:
                document = self.documents[self.context]
                document.update(time_origin=document["time_origin"] + 10, dialog_open=False, draft=None)
                if self.refresh_url is not None:
                    self.pages[self.context] = (self.refresh_url, self.pages[self.context][1])

    def test_visit_selects_requested_route_among_same_origin_tabs(self):
        driver = self.Driver()
        fixture = SimpleNamespace(base_url="http://127.0.0.1:9234", profile_id="matt")
        interaction.visit(driver, fixture, "/edit?id=casual/test")
        self.assertEqual(driver.context, "WEBVIEW_edit")
        urls = [entry for entry in driver.commands if entry[:2] == ("POST", "/url")]
        self.assertEqual(len(urls), 2)  # native open, then navigate the exact selected tab
        self.assertEqual(sum(entry[:2] == ("POST", "/refresh") for entry in driver.commands), 1)

    def test_same_url_receipt_visit_refreshes_document_and_discards_previous_modal_and_draft(self):
        driver = self.Driver()
        previous = driver.documents["WEBVIEW_old"]
        previous.update(dialog_open=True, draft="unsaved receipt change")
        previous_origin = previous["time_origin"]
        interaction.visit(driver, SimpleNamespace(base_url="http://127.0.0.1:9234", profile_id="matt"),
                          "/receipt?order=test")
        self.assertEqual(driver.context, "WEBVIEW_old")
        self.assertNotEqual(previous["time_origin"], previous_origin)
        self.assertFalse(previous["dialog_open"])
        self.assertIsNone(previous["draft"])
        self.assertEqual(driver.commands[-1], ("POST", "/refresh", {}))

    def test_visit_rejects_unchanged_document_or_refresh_to_wrong_url(self):
        def immediate(predicate, timeout=20, message="Condition unavailable"):
            value = predicate()
            if not value:
                raise AssertionError(message)
            return value

        for reloads, next_url in ((False, None), (True, "http://127.0.0.1:9234/?profile=matt#/library")):
            driver = self.Driver()
            driver.refreshes_document, driver.refresh_url = reloads, next_url
            fixture = SimpleNamespace(base_url="http://127.0.0.1:9234", profile_id="matt")
            with self.subTest(reloads=reloads, next_url=next_url), \
                    mock.patch.object(interaction, "wait", side_effect=immediate), \
                    self.assertRaisesRegex(AssertionError, "fresh document did not load"):
                interaction.visit(driver, fixture, "/receipt?order=test")

    def test_native_switch_returns_to_selected_tab_and_keeps_standalone_separate(self):
        driver = self.Driver()
        base = "http://127.0.0.1:9234"
        interaction.web(driver, base, standalone=False, expected_url=driver.pages["WEBVIEW_edit"][0])
        interaction.native(driver)
        self.assertEqual(interaction.web(driver, base, standalone=False), "WEBVIEW_edit")
        interaction.native(driver)
        self.assertEqual(interaction.web(driver, base, standalone=True), "WEBVIEW_home")
        interaction.native(driver)
        self.assertEqual(interaction.web(driver, base, standalone=False), "WEBVIEW_edit")

    def test_matching_active_tab_is_preferred_over_remembered_duplicate(self):
        driver = self.Driver()
        base = "http://127.0.0.1:9234"
        interaction.web(driver, base, standalone=False, expected_url=driver.pages["WEBVIEW_edit"][0])
        driver.pages["WEBVIEW_new"] = driver.pages["WEBVIEW_edit"]
        driver.context = "WEBVIEW_new"
        self.assertEqual(interaction.web(driver, base, standalone=False), "WEBVIEW_new")

    def test_same_url_background_cache_is_rejected_for_the_visible_foreground_tab(self):
        for active in ("NATIVE_APP", "WEBVIEW_edit"):
            driver = self.Driver()
            base = "http://127.0.0.1:9234"
            expected = driver.pages["WEBVIEW_edit"][0]
            interaction.web(driver, base, standalone=False, expected_url=expected)
            driver.pages["WEBVIEW_foreground"] = driver.pages["WEBVIEW_edit"]
            driver.visibility.update(WEBVIEW_edit="hidden", WEBVIEW_foreground="visible")
            driver.context = active
            driver.contexts = mock.Mock(wraps=driver.contexts)
            with self.subTest(active=active):
                self.assertEqual(interaction.web(driver, base, standalone=False, expected_url=expected),
                                 "WEBVIEW_foreground")
                driver.contexts.assert_called()
                self.assertEqual(driver._decklab_web_contexts[(base, False)], "WEBVIEW_foreground")

    def test_stale_background_keyboard_viewport_is_not_used_for_foreground_page_bounds(self):
        driver = self.Driver()
        base = "http://127.0.0.1:9234"
        expected = base + "/?profile=matt#/library"
        driver.pages["WEBVIEW_edit"] = (expected, False)
        interaction.web(driver, base, standalone=False, expected_url=expected)
        driver.pages["WEBVIEW_foreground"] = (expected, False)
        driver.visibility.update(WEBVIEW_edit="hidden", WEBVIEW_foreground="visible")
        driver.viewport_heights.update(WEBVIEW_edit=103, WEBVIEW_foreground=283)
        driver.context = "NATIVE_APP"
        interaction.web(driver, base, standalone=False, expected_url=expected)
        self.assertEqual(driver.execute("return visualViewport.height;"), 283)

    def test_valid_live_standalone_context_is_reused_without_invalidating_enumeration(self):
        driver = self.Driver()
        driver.context = "WEBVIEW_home"
        driver.contexts = mock.Mock(side_effect=RuntimeError("enumeration would detach the PWA"))
        driver.switch_context = mock.Mock(side_effect=AssertionError("no redundant switch"))
        self.assertEqual(interaction.web(driver, "http://127.0.0.1:9234", standalone=True), "WEBVIEW_home")
        driver.contexts.assert_not_called()
        driver.switch_context.assert_not_called()

    def test_native_return_reuses_cached_standalone_without_enumeration(self):
        driver = self.Driver()
        base = "http://127.0.0.1:9234"
        driver.context = "WEBVIEW_home"
        interaction.web(driver, base, standalone=True)
        interaction.native(driver)
        driver.contexts = mock.Mock(side_effect=RuntimeError("enumeration would detach the PWA"))
        self.assertEqual(interaction.web(driver, base, standalone=True), "WEBVIEW_home")
        driver.contexts.assert_not_called()

    def test_wrong_origin_live_context_falls_back_to_matching_standalone_page(self):
        driver = self.Driver()
        driver.pages["WEBVIEW_other"] = ("https://example.invalid/", True)
        driver.context = "WEBVIEW_other"
        driver.contexts = mock.Mock(wraps=driver.contexts)
        self.assertEqual(interaction.web(driver, "http://127.0.0.1:9234", standalone=True), "WEBVIEW_home")
        driver.contexts.assert_called()


class ReceiptViewportTests(unittest.TestCase):
    def test_opening_receipt_for_layout_does_not_require_native_photo_anchor(self):
        driver = mock.Mock()
        driver.execute.return_value = True
        fixture = SimpleNamespace(order_id="disposable", base_url="http://127.0.0.1:9234", profile_id="matt")
        with mock.patch.object(flows, "visit"), mock.patch.object(flows, "css", return_value="tile"), \
                mock.patch.object(flows, "tap_native_visible_part", return_value={"native_tap": {}}) as tap, \
                mock.patch.object(flows, "text", return_value="1 / 3"), \
                mock.patch.object(flows, "anchor_transform", side_effect=AssertionError("AX image invisible")) as anchor:
            flows.receipt_open(driver, fixture)
        anchor.assert_not_called()
        tap.assert_called_once_with(driver, fixture, ".rcpt-grid .card-tile-open")

    def test_partly_cropped_receipt_close_fails_initial_viewport(self):
        valid = {"rect": {"left": 20, "right": 200, "top": 0, "bottom": 44, "width": 180, "height": 44},
                 "visible": {"left": 20, "right": 200, "top": 0, "bottom": 44}, "shown": True}
        cropped = copy.deepcopy(valid)
        cropped["rect"].update(top=-12, bottom=32)
        cropped["visible"].update(top=0, bottom=32)
        with mock.patch.object(flows, "receipt_open"), mock.patch.object(flows, "bounds", side_effect=[valid, cropped, valid, valid, valid]), \
                self.assertRaisesRegex(AssertionError, "Receipt close.*clipped"):
            flows.receipt_layout(mock.Mock(), mock.Mock())

    def test_same_origin_wrong_route_live_context_does_not_bypass_expected_url(self):
        driver = ContextSelectionTests.Driver()
        driver.context = "WEBVIEW_old"
        driver.contexts = mock.Mock(wraps=driver.contexts)
        expected = driver.pages["WEBVIEW_edit"][0]
        self.assertEqual(interaction.web(driver, "http://127.0.0.1:9234", standalone=False,
                                         expected_url=expected), "WEBVIEW_edit")
        driver.contexts.assert_called()


if __name__ == "__main__":
    unittest.main()
