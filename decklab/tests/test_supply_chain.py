"""Supply-chain pins (E11-S67): the workflows' actions, the wake gate's images and Dependabot's file.

Read as text, without a YAML library. A release zip leaves .github/ out, so those checks skip there.
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GITHUB = REPO / ".github"
WORKFLOWS = GITHUB / "workflows"
COMPOSE = REPO / "decklab" / "wakegate" / "compose.yaml"

USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$")
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"^\s+# v\d+\.\d+\.\d+$")
IMAGE = re.compile(r"^\s*image:\s*(\S+)")


def uses_lines(path):
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        found = USES.match(line)
        if found:
            yield number, found.group(1), found.group(2)


@unittest.skipUnless(WORKFLOWS.is_dir(), "no .github/workflows here (a release zip leaves it out)")
class WorkflowPinTests(unittest.TestCase):
    def test_the_three_workflows_are_the_ones_checked(self):
        self.assertEqual({"lint.yml", "release.yml", "tests.yml"}, {p.name for p in WORKFLOWS.glob("*.y*ml")})

    def test_every_action_is_pinned_to_a_commit_with_its_version_in_a_comment(self):
        seen = 0
        for path in sorted(WORKFLOWS.glob("*.y*ml")):
            for number, target, rest in uses_lines(path):
                where = f"{path.name}:{number}"
                if target.startswith("./"):
                    continue                    # a local action is this repo's own commit
                seen += 1
                self.assertRegex(target, PINNED, f"{where} isn't pinned to a full commit SHA")
                self.assertRegex(rest, VERSION_COMMENT, f"{where} needs its version as a trailing comment")
        self.assertGreater(seen, 0)

    def test_one_action_has_one_pin_everywhere(self):
        pins = {}
        for path in WORKFLOWS.glob("*.y*ml"):
            for _number, target, rest in uses_lines(path):
                name, _, ref = target.partition("@")
                pins.setdefault(name, set()).add((ref, rest.strip()))
        self.assertEqual({}, {name: refs for name, refs in pins.items() if len(refs) > 1})

    def test_release_attests_the_zip_before_attaching_it(self):
        text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^  id-token: write")
        self.assertRegex(text, r"(?m)^  attestations: write")
        attest = text.index("uses: actions/attest-build-provenance@")
        self.assertLess(text.index('scripts/make_release.py "'), attest)
        self.assertLess(attest, text.index("gh release create"))
        self.assertIn("subject-path: dist/decklab-${{ steps.version.outputs.version }}.zip", text)

    def test_self_hosting_gives_the_attestation_check_beside_the_checksum(self):
        text = (REPO / "SELF-HOSTING.md").read_text(encoding="utf-8")
        line = next(line for line in text.splitlines() if "gh attestation verify" in line)
        self.assertIn(".zip.sha256", line)
        self.assertIn("Optionally", line)


@unittest.skipUnless(GITHUB.is_dir(), "no .github here (a release zip leaves it out)")
class DependabotTests(unittest.TestCase):
    def setUp(self):
        self.text = (GITHUB / "dependabot.yml").read_text(encoding="utf-8")
        self.blocks = self.text.split("  - package-ecosystem: ")[1:]

    def entries(self):
        for block in self.blocks:
            ecosystem = block.splitlines()[0].strip().strip('"')
            directory = re.search(r'^\s+directory:\s*"([^"]+)"', block, re.M).group(1)
            yield ecosystem, directory, block

    def test_it_covers_each_pinned_ecosystem_where_its_manifest_is(self):
        manifests = {"github-actions": ".github/workflows", "pip": "requirements.txt",
                     "npm": "package-lock.json", "docker-compose": "compose.yaml"}
        found = set()
        for ecosystem, directory, _block in self.entries():
            self.assertIn(ecosystem, manifests)
            self.assertTrue((REPO / directory.strip("/") / manifests[ecosystem]).exists(),
                            f"{ecosystem} in {directory} has no {manifests[ecosystem]}")
            found.add((ecosystem, directory))
        self.assertEqual({("github-actions", "/"), ("pip", "/decklab"), ("npm", "/decklab/safari"),
                          ("npm", "/decklab/ui_review"), ("docker-compose", "/decklab/wakegate")}, found)

    def test_everything_is_one_monthly_group(self):
        self.assertEqual(1, self.text.count("interval:"))
        self.assertRegex(self.text, r'(?m)^multi-ecosystem-groups:\n  upkeep:\n    schedule:\n      interval: "monthly"$')
        for ecosystem, directory, block in self.entries():
            self.assertIn('multi-ecosystem-group: "upkeep"', block, f"{ecosystem} {directory}")
            self.assertIn('patterns: ["*"]', block, f"{ecosystem} {directory}")


class WakeGateImageTests(unittest.TestCase):
    def images(self):
        found = {}
        for line in COMPOSE.read_text(encoding="utf-8").splitlines():
            match = IMAGE.match(line)
            if match:
                name, _, tag = match.group(1).partition(":")
                found[name] = tag
        return found

    def test_cloudflared_has_a_dated_tag_and_python_a_patch_tag(self):
        images = self.images()
        self.assertEqual({"python", "cloudflare/cloudflared"}, set(images))
        self.assertRegex(images["cloudflare/cloudflared"], r"^20\d\d\.\d{1,2}\.\d+$")
        self.assertRegex(images["python"], r"^3\.\d+\.\d+-alpine$")

    def test_the_readme_repeats_no_image_tag(self):
        # Dependabot's pull request changes compose.yaml alone, so a tag copied here would go stale.
        readme = (COMPOSE.parent / "README.md").read_text(encoding="utf-8")
        for name in self.images():
            self.assertNotIn(f"{name}:", readme)


if __name__ == "__main__":
    unittest.main()
