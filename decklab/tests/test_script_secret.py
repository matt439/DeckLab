"""Optional script secrets never replace loopback/listener/viewer or Linux peer checks."""
import email.message
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from decklab import smoke
from decklab.lib import access, config, script_secret as secret, server_http
from decklab.lib.config_errors import InvalidConfig

KEY = "SyntheticLoopbackSecret0123456789abcdef"


def message(values=()):
    headers = email.message.Message()
    for name, value in values:
        headers[name] = value
    return headers


class ScriptSecretTests(unittest.TestCase):
    def test_preflight_rejects_invalid_secret_settings_without_publishing_them(self):
        from decklab.lib.preflight_local import Local
        with tempfile.TemporaryDirectory(prefix="decklab-script-secret-") as folder:
            path = Path(folder) / "decklab" / "config.json"
            path.parent.mkdir()
            raw = {"profiles": [{"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin"}],
                   "script_secret": "PRIVATE"}
            path.write_text(json.dumps(raw), encoding="utf-8")
            local = Local(root=folder, environ={})
            self.assertEqual(local.probe("config"), "config_invalid")
            self.assertIsNone(local.settings)
            raw["script_secret"] = KEY
            path.write_text(json.dumps(raw), encoding="utf-8")
            self.assertEqual(Local(root=folder, environ={}).probe("config"), "config_ready")

    def test_configured_keys_are_validated_without_echoing_values(self):
        self.assertEqual(secret.validate(KEY), KEY)
        self.assertIsNone(secret.validate(None))
        for value in ("", "PRIVATE", "private value" * 5, "é" * 40, KEY * 10, [], True):
            with self.subTest(kind=type(value).__name__), self.assertRaises(InvalidConfig) as caught:
                secret.validate(value)
            if value:
                self.assertNotIn(str(value), str(caught.exception))

    def test_handler_checks_the_exact_header_only_when_off_linux_and_configured(self):
        def handler(values=(), remote=False, address="127.0.0.1", key=KEY):
            return SimpleNamespace(server=SimpleNamespace(remote=remote, script_secret=key),
                                   headers=message(values), client_address=(address, 1234))
        flag = [(access.SCRIPT_HEADER, "1")]
        proof = (secret.HEADER, KEY)
        with mock.patch.object(server_http, "script_peer_ok", return_value=True) as peer:
            for platform in ("win32", "darwin"):
                with self.subTest(platform=platform), mock.patch.object(secret.sys, "platform", platform):
                    check = lambda values, **kwargs: server_http.Handler._is_script(handler(values, **kwargs), None)
                    self.assertFalse(check(flag))
                    self.assertFalse(check([*flag, (secret.HEADER, "wrong")]))
                    self.assertFalse(check([*flag, proof, proof]))
                    self.assertTrue(check([*flag, proof]))
                    self.assertFalse(check([proof]))
                    self.assertFalse(check([*flag, proof], remote=True))
                    self.assertFalse(check([*flag, proof], address="192.0.2.10"))
                    self.assertFalse(server_http.Handler._is_script(handler([*flag, proof]), "matt"))
                    self.assertTrue(check(flag, key=None))
            with mock.patch.object(secret.sys, "platform", "linux"):
                self.assertTrue(server_http.Handler._is_script(handler(flag), None))
                peer.return_value = False
                self.assertFalse(server_http.Handler._is_script(handler([*flag, proof]), None))

    def test_invalid_setting_is_refused_before_binding_and_a_valid_setting_reaches_the_server(self):
        with mock.patch.object(server_http.ThreadingHTTPServer, "__init__") as bind:
            with self.assertRaises(InvalidConfig):
                server_http.make_server("127.0.0.1", 0, script_secret="invalid")
        bind.assert_not_called()
        server = server_http.make_server("127.0.0.1", 0, script_secret=KEY)
        self.addCleanup(server.server_close)
        self.assertEqual(server.script_secret, KEY)

    def test_trusted_client_headers_preserve_callers_and_do_not_read_settings_on_linux(self):
        base = {access.SCRIPT_HEADER: "1", "Accept": "application/json"}
        headers = secret.local_headers(base, settings={"script_secret": KEY}, platform="win32")
        self.assertEqual(headers, {**base, secret.HEADER: KEY})
        self.assertNotIn(secret.HEADER, base)
        with mock.patch.object(config, "load", side_effect=AssertionError("No config read")):
            self.assertEqual(secret.local_headers(base, platform="linux"), base)
        with mock.patch.object(secret.sys, "platform", "win32"), mock.patch.object(config, "load", return_value={"script_secret": KEY}), \
                mock.patch.object(smoke, "http_get", return_value=(200, {}, b'{}')) as get:
            self.assertEqual(smoke.get_json(18643, "/api/status"), (200, {}))
        self.assertEqual(get.call_args.args[-1], {**base, secret.HEADER: KEY})
