"""Native app-transition contracts, separate from Simulator acceptance."""
import unittest
from types import SimpleNamespace
from unittest import mock

from decklab.safari import flows


class ShareInstallationTransitionTests(unittest.TestCase):
    def test_installation_returning_home_restores_safari_checks_errors_then_launches_real_icon(self):
        active = "Safari"
        events = []
        driver = mock.Mock()
        fixture = SimpleNamespace(base_url="http://127.0.0.1:9234", profile_name="Matt")
        ready = {"icon_name": "Deck Lab", "native_add": {"x": 300, "y": 50, "width": 60, "height": 44}}

        def installed(*args):
            nonlocal active
            active = "SpringBoard"
            events.append("installed_on_home")

        def mobile(driver, command, **arguments):
            nonlocal active
            if command == "activateApp":
                self.assertEqual(arguments, {"bundleId": "com.apple.mobilesafari"})
                active = "Safari"
                events.append("restore_safari")
            elif command == "pressButton":
                self.assertEqual(arguments, {"name": "home"})
                active = "SpringBoard"
                events.append("press_home")
            else:
                self.fail(f"Unexpected native command {command}")

        def web(driver, base_url, standalone=False, **kwargs):
            self.assertEqual(active, "PWA" if standalone else "Safari", "A hidden webview must not satisfy this flow")
            events.append("attach_pwa" if standalone else "attach_safari")

        def errors(driver):
            events.append("check_errors_" + active)

        def launch(driver, name):
            nonlocal active
            self.assertEqual(active, "SpringBoard")
            self.assertEqual(name, "Deck Lab")
            active = "PWA"
            events.append("launch_actual_icon")
            return {"name": name}

        driver.execute.side_effect = lambda script, *args: False if ".who-button" in script else True
        with mock.patch.object(flows, "visit"), mock.patch.object(flows, "browser_button", return_value="share"), \
                mock.patch.object(flows, "native_rect", return_value=ready["native_add"]), \
                mock.patch.object(flows, "tap_native_rect"), mock.patch.object(flows, "native"), \
                mock.patch.object(flows, "open_add_home_screen", return_value={"element_swipes": []}), \
                mock.patch.object(flows, "native_home_screen_ready", return_value=ready), \
                mock.patch.object(flows, "wait_native_add_dismissed", side_effect=installed), \
                mock.patch.object(flows, "mobile", side_effect=mobile), \
                mock.patch.object(flows, "web", side_effect=web), \
                mock.patch.object(flows, "no_page_errors", side_effect=errors), \
                mock.patch.object(flows, "launch_home_screen_icon", side_effect=launch):
            result = flows.share_home_screen(driver, fixture)
        self.assertTrue(result["standalone"])
        self.assertEqual(events, ["installed_on_home", "restore_safari", "attach_safari", "check_errors_Safari",
                                  "press_home", "launch_actual_icon", "attach_pwa", "check_errors_PWA"])


class VersionStartupTransitionTests(unittest.TestCase):
    def test_version_case_resets_safari_and_keeps_the_installed_app_context(self):
        origin = "http://127.0.0.1:9234"
        driver = SimpleNamespace(context="WEBVIEW_home", safari_running=True,
                                 _decklab_web_contexts={(origin, False): "old_safari", (origin, True): "home_app"})

        def switch_context(name):
            driver.context = name

        def execute(script, arguments):
            self.assertEqual(driver.context, "NATIVE_APP")
            self.assertEqual(script, "mobile: terminateApp")
            self.assertEqual(arguments, [{"bundleId": "com.apple.mobilesafari"}])
            driver.safari_running = False

        driver.switch_context, driver.execute = switch_context, execute

        class FreshVisitObserved(Exception):
            pass

        def visit(current, fixture, route):
            self.assertIs(current, driver)
            self.assertEqual(route, "/library")
            self.assertFalse(driver.safari_running)
            self.assertEqual(driver._decklab_web_contexts, {(origin, True): "home_app"})
            raise FreshVisitObserved

        with mock.patch.object(flows, "visit", side_effect=visit), self.assertRaises(FreshVisitObserved):
            flows.stale_reload(driver, SimpleNamespace(base_url=origin))


if __name__ == "__main__":
    unittest.main()
