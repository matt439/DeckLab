"""Configuration syntax diagnostics use temporary files, with no server or database started."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from decklab import doctor, server
from decklab.db import __main__ as db_cli
from decklab.lib import config, preflight, preflight_local, server_http, server_run
from decklab.lib.config_errors import ConfigSyntaxError, InvalidConfig
from decklab.tests.test_doctor import Codes, READY


class ConfigDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="decklab-config-diagnostics-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "decklab" / "config.json"
        self.path.parent.mkdir()
        self.enterContext(mock.patch.object(config, "CONFIG_FILE", self.path))
        self.enterContext(mock.patch.dict("os.environ", {config.EXTRA_ENV: ""}))

    def test_bom_is_accepted_by_the_loader_and_doctor(self):
        settings = {"port": 8765, "profiles": [{"id": "matt", "name": "Matt", "space": "home",
                    "role": "admin", "plays_as": "user", "emails": ["matt@example.com"]}]}
        self.path.write_text(json.dumps(settings), encoding="utf-8-sig")
        self.assertEqual(config.load(), {**config.DEFAULTS, **settings})
        adapter = preflight_local.Local(root=self.root, environ={})
        self.assertEqual(adapter.probe("config"), "config_ready")
        self.assertEqual(adapter.settings["port"], 8765)

    def test_syntax_errors_report_the_same_safe_location_everywhere(self):
        cases = ('{\n  "private": "PRIVATE_VALUE",\n}', r'{"private": "C:\PRIVATE_VALUE"}')
        for source in cases:
            with self.subTest(source=source):
                self.path.write_text(source, encoding="utf-8-sig")
                try:
                    json.loads(source)
                except json.JSONDecodeError as error:
                    expected = f"decklab/config.json isn't valid JSON: line {error.lineno}, column {error.colno}"
                with self.assertRaises(ConfigSyntaxError) as caught:
                    config.load()
                self.assertEqual(str(caught.exception), expected)
                self.assertFalse(hasattr(caught.exception, "doc"))

                logs = []
                with mock.patch.object(server_http, "log", logs.append), \
                        mock.patch.object(server_run, "_serve") as serve:
                    self.assertEqual(server.main(["--no-update"]), 1)
                serve.assert_not_called()
                self.assertEqual(logs, [expected])

                args = SimpleNamespace(func=lambda _: config.load())
                parser = SimpleNamespace(parse_args=lambda _: args)
                with mock.patch.object(db_cli, "parser", return_value=parser), \
                        redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(db_cli.main([]), 1)
                self.assertEqual(err.getvalue(), expected + "\n")

                adapter = preflight_local.Local(root=self.root, environ={})
                def probe(ident):
                    return adapter.probe(ident) if ident == "config" else READY[ident]
                probe.config_location = lambda: adapter.config_location
                for argv in ([], ["--json"]):
                    with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
                        self.assertEqual(doctor.main(argv, provider_factory=lambda: probe), 1)
                    rendered = out.getvalue()
                    if argv:
                        result = json.loads(rendered)
                        row = next(row for row in result["checks"] if row["id"] == "config")
                        self.assertEqual(row["message"], expected)
                        self.assertEqual(row["code"], "config_invalid")
                    else:
                        self.assertIn(expected, rendered)
                    self.assertEqual(err.getvalue(), "")
                    self.assertNotIn("PRIVATE_VALUE", rendered)
                    self.assertNotIn("Traceback", rendered)

    def test_non_objects_and_invalid_encoding_are_safe_configuration_errors(self):
        for raw in (b"[]", b'"PRIVATE_VALUE"', b"\xffPRIVATE_VALUE"):
            self.path.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(InvalidConfig) as caught:
                config.load()
            self.assertNotIn("PRIVATE_VALUE", str(caught.exception))

    def test_only_valid_config_location_integers_can_enter_doctor_output(self):
        for line, column in ((True, 1), (1, "PRIVATE_VALUE"), (0, 1), (1, -1), (2 ** 32, 1)):
            with self.subTest(line=line, column=column), self.assertRaises(ValueError):
                ConfigSyntaxError(line, column)
        result = preflight.report(Codes({"config": "config_invalid"}), config_location=lambda: (2, 3))
        self.assertNotIn("PRIVATE_VALUE", json.dumps(result))
        self.assertIn("line 2, column 3", result["checks"][1]["message"])
        for location in (("PRIVATE_VALUE", 1), (1, True), (1, 0), (1, 2 ** 32), [2, 3], {"line": 2}):
            with self.subTest(kind=type(location).__name__):
                result = preflight.report(Codes({"config": "config_invalid"}), config_location=lambda: location)
                self.assertNotIn("PRIVATE_VALUE", json.dumps(result))
                self.assertEqual(result["checks"][1]["message"], preflight.OUTCOMES["config_invalid"][1])
        callback = mock.Mock(side_effect=RuntimeError("PRIVATE_VALUE"))
        result = preflight.report(Codes({"config": "config_invalid"}), config_location=callback)
        self.assertNotIn("PRIVATE_VALUE", json.dumps(result))
        result = preflight.report(Codes(), config_location=callback)
        self.assertTrue(result["core_ready"])
        callback.assert_called_once_with()
