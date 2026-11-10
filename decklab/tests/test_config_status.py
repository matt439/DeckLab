"""Missing config and role warnings remain local diagnostics, without granting access."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from decklab import doctor, server
from decklab.lib import config, preflight, preflight_local, profiles, server_http, server_run
from decklab.lib.api import carddata
from decklab.lib.homenet import profile_config
from decklab.tests.test_doctor import Codes, READY


def settings(role="admin"):
    return {"profiles": [{"id": "user1", "name": "User1", "space": "home", "plays_as": "user",
                          "role": role, "emails": ["user1@example.com"]}]}


class ConfigStatusTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="decklab-config-status-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "decklab" / "config.json"
        self.path.parent.mkdir()
        self.enterContext(mock.patch.object(config, "CONFIG_FILE", self.path))
        self.enterContext(mock.patch.dict("os.environ", {config.EXTRA_ENV: ""}))

    def test_missing_config_keeps_defaults_and_logs_the_setup_step_before_starting(self):
        self.assertEqual(config.load(), config.DEFAULTS)
        self.assertEqual(config.source_status()["state"], "missing")
        logs = []
        with mock.patch.object(server_http, "log", logs.append), \
                mock.patch.object(server_run, "_serve", return_value=0) as serve:
            self.assertEqual(server.main(["--no-update"]), 0)
        serve.assert_called_once()
        self.assertEqual(serve.call_args.args[3], config.DEFAULTS)
        self.assertEqual(len(logs), 1)
        self.assertIn("decklab/config.example.json", logs[0])
        self.assertIn("SELF-HOSTING.md step 4", logs[0])

    def test_status_returns_fixed_missing_unreadable_and_ready_states_without_contents(self):
        with mock.patch.object(carddata, "_index_info", return_value=(None, None)), \
                mock.patch.object(carddata.pricing_setting, "settings", return_value={}), \
                mock.patch.object(carddata, "_cached_rate", return_value=None), \
                mock.patch.object(carddata, "pricing", return_value={}):
            self.assertEqual(carddata.status()["config"]["state"], "missing")
            for raw in (b'{"SECRET_VALUE":', b"\xffSECRET_VALUE", b'["SECRET_VALUE"]'):
                self.path.write_bytes(raw)
                found = carddata.status()["config"]
                self.assertEqual(found["state"], "unreadable")
                self.assertNotIn("SECRET_VALUE", json.dumps(found))
                self.assertNotIn("line", found)
            self.path.write_text('{"SECRET_VALUE": true}', encoding="utf-8-sig")
            self.assertEqual(carddata.status()["config"], {"state": "ready", "message": None})
        with mock.patch.object(Path, "read_text", side_effect=OSError("SECRET_VALUE")):
            self.assertEqual(config.source_status()["state"], "unreadable")

    def test_role_warnings_do_not_change_tolerant_roles_or_doctor_dependency_checks(self):
        for role, warnings in (("PRIVATE_VALUE", ("config_unknown_role", "config_no_admin")),
                               ("member", ("config_no_admin",)), ("admin", ())):
            with self.subTest(role=role):
                raw = settings(role)
                before = json.dumps(raw)
                parsed = profiles.read(raw)
                self.assertEqual(parsed[0]["role"], "admin" if role == "admin" else "member")
                self.assertEqual(profiles.role_warning_codes(raw), warnings)
                self.path.write_text(json.dumps(raw), encoding="utf-8")
                adapter = preflight_local.Local(root=self.root, environ={})
                self.assertEqual(adapter.config_warnings, ())
                def probe(ident):
                    return adapter.probe(ident) if ident == "config" else READY[ident]
                probe.config_warnings = lambda: adapter.config_warnings
                with redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(doctor.main(["--json"], provider_factory=lambda: probe), 0)
                result = json.loads(out.getvalue())
                config_row = result["checks"][1]
                self.assertEqual(config_row["code"], "config_ready")
                self.assertEqual([row["code"] for row in config_row["warnings"]], list(warnings))
                self.assertEqual(result["checks"][3]["code"], "database_ready")
                self.assertNotIn("PRIVATE_VALUE", out.getvalue())
                self.assertNotIn("user1", out.getvalue())
                self.assertEqual(json.dumps(raw), before)
                local = json.dumps(profile_config.check(raw))
                for code in warnings:
                    self.assertIn(code, local)
                self.assertNotIn("PRIVATE_VALUE", local)
                self.assertNotIn("user1", local)

    def test_legacy_roles_remain_admin_without_new_warnings(self):
        raw = settings()
        del raw["profiles"][0]["role"]
        self.assertEqual(profiles.read(raw)[0]["role"], "admin")
        self.assertEqual(profiles.role_warning_codes(raw), ())
        self.assertEqual(profile_config.check(raw), [])
        self.assertEqual(profiles.role_warning_codes({"profiles": []}), ("config_no_admin",))
        self.assertIn("config_no_admin", json.dumps(profile_config.check({"profiles": []})))

    def test_doctor_accepts_only_known_warning_codes_and_prints_them_as_warnings(self):
        callback = lambda: ("config_no_admin",)
        result = preflight.report(Codes(), config_warnings=callback)
        self.assertTrue(result["core_ready"])
        self.assertIn("WARN Configuration: No usable admin profile is configured.", preflight.text(result))
        for invalid in (("SECRET_VALUE",), ["config_no_admin"], (True,), ("config_no_admin",) * 3):
            result = preflight.report(Codes(), config_warnings=lambda: invalid)
            self.assertNotIn("warnings", result["checks"][1])
            self.assertNotIn("SECRET_VALUE", json.dumps(result))
