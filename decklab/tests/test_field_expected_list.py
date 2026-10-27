"""Guard field submissions against a changed saved list; all Forge/jobs are fixture stubs."""
from unittest import mock

from decklab.lib import api
from decklab.lib.api import field_page, simulations
from decklab.tests.test_api import ApiTestCase
from decklab.tests.test_field_api import ELVES, GRUUL, FakeFieldPart, body


class ExpectedFieldListTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.forge = self.box.forge
        self.forge.field = FakeFieldPart(self.forge)
        self.runner = mock.Mock()
        self.answer = {"status": "queued"}
        self.status = mock.Mock(return_value={"ready": True})
        self.opponents = mock.Mock(wraps=self.forge.field.opponents)
        for target, name, value in (
            (field_page.forge_runs, "COORD_JOBS", self.runner),
            (field_page, "_answer", mock.Mock(return_value=self.answer)),
            (self.forge, "status", self.status),
            (self.forge.field, "opponents", self.opponents),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_field(self, **extra):
        return api.run_field(body(profile="matt", id=ELVES, **extra))

    def refused(self, status, *, contains=None, **extra):
        return self.assertApiError(status, lambda: self.run_field(**extra), contains=contains)

    def no_submission_work(self):
        self.status.assert_not_called()
        self.opponents.assert_not_called()
        self.runner.submit.assert_not_called()
        self.assertEqual(self.forge.field.runs, [])

    def test_matching_identity_submits_the_captured_entry_once(self):
        summary, entry = field_page._field_entry(self.forge, ELVES, "target")
        with mock.patch.object(field_page, "_field_entry", return_value=(summary, entry)) as captured:
            self.assertIs(self.run_field(expected_card_sha=entry["card_sha"]), self.answer)
        captured.assert_called_once_with(self.forge, ELVES, None)
        self.runner.submit.assert_called_once()
        key, job = self.runner.submit.call_args.args
        self.assertEqual(key, field_page.job_key(self.forge, entry))
        self.assertIs(job.entry, entry)
        self.assertEqual(job.budget, "standard")
        self.assertEqual(self.runner.submit.call_args.kwargs, {"rerun": True})
        self.status.assert_called_once()
        self.opponents.assert_called_once()
        self.assertEqual(self.forge.field.runs, [])

    def test_omitting_identity_preserves_existing_submission(self):
        self.assertIs(self.run_field(budget="quick"), self.answer)
        self.runner.submit.assert_called_once()
        self.assertEqual(self.runner.submit.call_args.args[1].budget, "quick")

    def test_mismatch_refuses_before_readiness_opponents_or_submission(self):
        expected = field_page._field_entry(self.forge, GRUUL, "target")[1]["card_sha"]
        self.status.return_value = {"ready": False, "problem": "Fixture unavailable"}
        error = self.refused(409, expected_card_sha=expected, contains="The saved list changed")
        self.assertNotIn(expected, error.message)
        self.no_submission_work()

    def test_identity_must_be_an_explicit_lowercase_full_hash(self):
        for value in (None, False, 12, [], {}, "", "a" * 63, "a" * 65, "A" * 64,
                      "g" * 64, "a" * 64 + "\n", " " + "a" * 64):
            with self.subTest(value=value):
                self.refused(400, expected_card_sha=value, contains="expected_card_sha must be")
        self.no_submission_work()

    def test_hidden_and_missing_decks_remain_indistinguishable_before_identity_check(self):
        with mock.patch.object(field_page.guard, "sees_deck", return_value=False):
            hidden = self.refused(404, expected_card_sha="bad")
        missing = self.assertApiError(404, api.run_field,
            body(profile="matt", id="commander/missing", expected_card_sha="bad"))
        self.assertEqual(hidden.message, f"No deck '{ELVES}'")
        self.assertEqual(missing.message, "No deck 'commander/missing'")
        self.no_submission_work()

    def test_normal_version_validation_precedes_the_expected_identity(self):
        self.refused(400, version="invalid", expected_card_sha="bad", contains="version must be")
        self.refused(404, version="owned", expected_card_sha="bad", contains="has no owned list")
        self.no_submission_work()

    def test_simulations_permission_precedes_expected_identity_and_deck_work(self):
        with mock.patch.object(simulations, "mode", return_value="paused"), \
                mock.patch.object(field_page, "_field_entry") as entry:
            self.refused(403, expected_card_sha="bad", contains="paused")
        entry.assert_not_called()
        self.no_submission_work()
