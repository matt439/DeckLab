"""The public-repo leak guard (E11-S62) against disposable Git repositories, and over this repo.

No real address or domain is written here: the "real" values are made up under real-looking endings,
and the ones a PC's own config.json holds are read only by the audit's child process.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import audit_public_repo as audit


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit_public_repo.py"
# Made up for these tests, and put together here so this file passes its own check.
REAL_HOST = "cards." + "lantern-vale" + ".net"
REAL_EMAIL = "kim" + "@" + "lantern-vale" + ".net"
WRANGLER = """name = "decklab-off-page"
main = "worker.mjs"
routes = [
  { pattern = "HOST/*", zone_name = "ZONE" },
]
"""


class RuleTests(unittest.TestCase):
    def test_example_hosts_are_placeholders(self):
        for host in ("example.com", "decklab.example.com", "WWW.Example.org.", "shop.example", "x.invalid", "a.test", ""):
            self.assertTrue(audit.example_host(host), host)
        for host in (REAL_HOST, "example.com.au", "notexample.com", "myexample.net"):
            self.assertFalse(audit.example_host(host), host)

    def test_route_hosts(self):
        self.assertEqual(audit.route_host("decklab.example.com/*"), "decklab.example.com")
        self.assertEqual(audit.route_host("*.example.com/api/*"), "example.com")
        self.assertEqual(audit.route_host("https://" + REAL_HOST + ":8443/x"), REAL_HOST)

    def test_placeholder_ids(self):
        for value in ("", "<account id>", "${CF_ACCOUNT_ID}", "0" * 32, "your-account-id", "example"):
            self.assertTrue(audit.placeholder_id(value), value)
        self.assertFalse(audit.placeholder_id("0123456789abcdef0123456789abcdef"))

    def test_emails(self):
        text = "\n".join([
            "user1@example.com Matt@Example.COM a+b@shop.example build@example.invalid",
            "npx wrangler@4.151.1 deploy; icon@2x.png; matt@192.168.0.2; @staticmethod; a @ b.c",
            "Co-Authored-By: Someone <noreply@anthropic.com>",
            "write to " + REAL_EMAIL + ", please",
            "<" + REAL_EMAIL.upper() + ">",
        ])
        found = audit.email_findings(text)
        self.assertEqual([number for number, _ in found], [4, 5])
        self.assertIn(REAL_EMAIL, found[0][1])

    def test_config_files_are_recognised(self):
        for name in ("decklab/cloudflare/wrangler.toml", "tools/wrangler.jsonc", "decklab/wakegate/compose.yaml",
                     "decklab/wakegate/.env.example", "decklab/cloudflare/routes.json"):
            self.assertTrue(audit.is_config_file(name), name)
        for name in ("decklab/cloudflare/worker.mjs", "decklab/wakegate/README.md", "decklab/config.example.json",
                     "decklab/lib/tunnel.py"):
            self.assertFalse(audit.is_config_file(name), name)

    def test_wrangler_placeholders_pass_and_a_real_zone_fails(self):
        clean = WRANGLER.replace("HOST", "decklab.example.com").replace("ZONE", "example.com")
        self.assertEqual(audit.config_findings("decklab/cloudflare/wrangler.toml", clean), [])
        real = WRANGLER.replace("HOST", REAL_HOST).replace("ZONE", REAL_HOST.split(".", 1)[1])
        found = audit.config_findings("decklab/cloudflare/wrangler.toml", real)
        self.assertEqual([number for number, _ in found], [4, 4])
        self.assertTrue(any(message.startswith("pattern names") for _, message in found))
        self.assertTrue(any(message.startswith("zone_name names") for _, message in found))

    def test_wrangler_ids_and_plain_routes(self):
        text = ('account_id = "0123456789abcdef0123456789abcdef"\nroute = "' + REAL_HOST + '/*"\n'
                '[env.live]\nroutes = ["a.example.com/*",\n  "www.' + REAL_HOST + '/*"]\nzone_id = "<zone id>"\n')
        found = audit.config_findings("wrangler.toml", text)
        self.assertEqual([(number, message.split(" ")[0]) for number, message in found],
                         [(1, "account_id"), (2, "route"), (5, "routes")])

    def test_yaml_json_and_env_lines(self):
        yaml = ("ingress:\n  - hostname: " + REAL_HOST + "\n    service: http://127.0.0.1:8644\n"
                "  - hostname: decklab.example.com\n# hostname: " + REAL_HOST + "\n")
        self.assertEqual([n for n, _ in audit.config_findings("decklab/wakegate/config.yml", yaml)], [2])
        env = "CLOUDFLARE_ACCOUNT_ID=0123456789abcdef0123456789abcdef\nCF_ZONE_ID=\nGATE_PORT=8650\nZONE_NAME=example.com\n"
        self.assertEqual([n for n, _ in audit.config_findings("decklab/wakegate/.env.example", env)], [1])
        jsonc = '{\n  // routes\n  "routes": ["' + REAL_HOST + '/*"],\n  "zone_id": "abc123def456"\n}\n'
        self.assertEqual([n for n, _ in audit.config_findings("decklab/cloudflare/wrangler.jsonc", jsonc)], [3, 4])
        plain = json.dumps({"env": {"live": {"routes": [{"pattern": REAL_HOST + "/*", "zone_name": "example.com"}]}}})
        self.assertEqual(len(audit.config_findings("wrangler.json", plain)), 1)

    def test_jsonc_is_parsed_past_comments_and_line_breaks(self):
        jsonc = ('{\n  // "routes": ["' + REAL_HOST + '/*"]\n  "routes": [\n    /* the site */\n'
                 '    "' + REAL_HOST + '/*",\n    "decklab.example.com/*",\n  ],\n'
                 '  "main": "https://example.com//x", // trailing\n}\n')
        self.assertEqual(json.loads(audit.strip_jsonc(jsonc))["main"], "https://example.com//x")
        self.assertEqual([n for n, _ in audit.config_findings("wrangler.jsonc", jsonc)], [5])

    def test_zone_names(self):
        self.assertEqual(audit.zone_names("WWW." + REAL_HOST + "."), [REAL_HOST, REAL_HOST.split(".", 1)[1]])
        self.assertEqual(audit.zone_names("cards.lantern-vale.com.au"), ["cards.lantern-vale.com.au", "lantern-vale.com.au"])
        self.assertEqual(audit.zone_names("lantern-vale.co"), ["lantern-vale.co"])

    def test_config_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "local.json"
            path.write_text(json.dumps({
                "profiles": [{"id": "kim", "emails": [REAL_EMAIL.upper(), "kim@example.com"]}, {"id": "sam"}],
                "allowed_hosts": ["www." + REAL_HOST, REAL_HOST, "decklab.example.com", "localhost", "192.168.0.2"],
                "access": {"team": "lantern", "aud": "ab12" * 16, "port": 8644},
            }), encoding="utf-8")
            terms = audit.config_terms(path)
            self.assertEqual(audit.config_terms(Path(tmp) / "absent.json"), {})
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(audit.config_terms(path), {})
        self.assertEqual(terms["a configured profile's email"], {REAL_EMAIL})
        self.assertEqual(terms["the configured domain"], {REAL_HOST, REAL_HOST.split(".", 1)[1]})
        self.assertEqual(terms["the configured Cloudflare Access team"], {"lantern.cloudflareaccess.com"})
        self.assertEqual(terms["the configured Cloudflare Access AUD tag"], {"ab12" * 16})

    def test_term_findings_never_print_the_value(self):
        data = ("one\nsee https://WWW." + REAL_HOST.upper() + "/x\n\x00\xff " + REAL_HOST + "\n").encode("latin-1")
        found = audit.term_findings(data, {"the configured domain": {REAL_HOST}})
        self.assertEqual([number for number, _ in found], [2, 3])
        self.assertTrue(all(REAL_HOST not in message.lower() for _, message in found))


@unittest.skipUnless(shutil.which("git"), "Git is required for the public-repo audit")
class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "core.autocrlf", "false")
        self.local = Path(self.temp.name) / "local.json"       # outside the repo, as a stand-in config.json

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.PIPE)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))

    def found(self):
        return audit.audit(self.root, config_file=self.local)[0]

    def test_a_clean_repo_passes(self):
        self.write("decklab/cloudflare/wrangler.toml",
                   WRANGLER.replace("HOST", "decklab.example.com").replace("ZONE", "decklab.example.com"))
        self.write("docs/a.md", "Mail user1@example.com about https://decklab.example.com\n")
        self.write("icon.png", b"\x89PNG\x00\x01 " + REAL_EMAIL.encode("ascii"))      # binary: emails not read
        self.git("add", "-A")
        self.assertEqual(self.found(), [])

    def test_a_real_email_fails_naming_the_file(self):
        self.write("docs/a.md", "ok\nMail " + REAL_EMAIL + "\n")
        self.write("untracked.txt", REAL_EMAIL + "\n")
        self.write(".gitignore", "ignored/\n")
        self.write("ignored/private.txt", REAL_EMAIL + "\n")
        self.git("add", "docs", ".gitignore")
        self.assertEqual([(name, number) for name, number, _ in self.found()], [("docs/a.md", 2), ("untracked.txt", 1)])

    def test_a_real_route_fails_only_in_a_config_file(self):
        real = WRANGLER.replace("HOST", REAL_HOST).replace("ZONE", REAL_HOST)
        self.write("decklab/cloudflare/wrangler.toml", real)
        self.write("decklab/tests/fixtures/sample.toml", real)
        self.write("decklab/wakegate/.env.example", "TUNNEL_TOKEN=\nCF_ACCOUNT_ID=0123456789abcdef0123456789abcdef\n")
        self.git("add", "-A")
        self.assertEqual(sorted({name for name, _, _ in self.found()}),
                         ["decklab/cloudflare/wrangler.toml", "decklab/wakegate/.env.example"])

    def test_configured_values_are_searched_in_every_file(self):
        self.local.write_text(json.dumps({"profiles": [{"id": "kim", "emails": ["kim@" + REAL_HOST]}],
                                          "allowed_hosts": [REAL_HOST]}), encoding="utf-8")
        self.write("decklab/web/core.js", "// open https://" + REAL_HOST + "/#/decks\n")
        self.write("icon.png", b"\x89PNG\x00\n\n" + REAL_HOST.upper().encode("ascii"))
        self.write("clean.py", "x = 1\n")
        self.git("add", "-A")
        found = self.found()
        self.assertEqual([(name, number) for name, number, _ in found], [("decklab/web/core.js", 1), ("icon.png", 3)])
        self.assertTrue(all("lantern" not in message for _, _, message in found))
        self.local.unlink()
        self.assertEqual(self.found(), [])

    def test_a_configured_zone_is_found_and_never_quoted_by_another_rule(self):
        zone = REAL_HOST.split(".", 1)[1]
        self.local.write_text(json.dumps({"profiles": [{"id": "kim", "emails": [REAL_EMAIL]}],
                                          "allowed_hosts": ["www." + REAL_HOST]}), encoding="utf-8")
        self.write("decklab/cloudflare/wrangler.toml", WRANGLER.replace("HOST", "decklab.example.com").replace("ZONE", zone))
        self.write("docs/a.md", "Mail " + REAL_EMAIL.upper() + "\n")
        self.git("add", "-A")
        found = self.found()
        self.assertEqual(sorted({name for name, _, _ in found}), ["decklab/cloudflare/wrangler.toml", "docs/a.md"])
        self.assertTrue(any(message.startswith("zone_name names") for _, _, message in found))
        self.assertTrue(any(message.startswith("an email address") for _, _, message in found))
        self.assertTrue(all("lantern" not in message.lower() for _, _, message in found), found)

    def test_check_exit_codes(self):
        script = self.root / "scripts" / "audit_public_repo.py"
        script.parent.mkdir()
        shutil.copyfile(SCRIPT, script)
        self.write("a.md", "user1@example.com\n")
        self.git("add", "-A")

        def run(*args):
            return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)

        self.assertEqual(run("--check").returncode, 0)
        self.write("a.md", REAL_EMAIL + "\n")
        result = run("--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("a.md:1:", result.stdout)
        self.assertEqual(run().returncode, 0)             # without --check it only lists


@unittest.skipUnless(shutil.which("git") and (REPO / ".git").exists(), "needs this repo's Git checkout")
class ThisRepoTests(unittest.TestCase):
    def test_this_repo_holds_no_real_address_zone_or_configured_value(self):
        # A child process, so on a PC with a decklab/config.json (which the fixture runner hides from
        # this process) its domain and emails are searched for too. It only reads, and prints files and
        # line numbers, never a configured value. In CI there's no config.json: the other rules run.
        result = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_worker_config_names_only_placeholders(self):
        name = "decklab/cloudflare/wrangler.toml"
        text = (REPO / name).read_text(encoding="utf-8")
        self.assertIn("routes", text)
        self.assertEqual(audit.config_findings(name, text), [])
        ignored = (REPO / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("decklab/cloudflare/wrangler.local.toml", ignored)


if __name__ == "__main__":
    unittest.main()
