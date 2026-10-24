"""Check that blocked refreshes preserve data without hiding other failures."""

import copy
import json
import sys
import unittest
from unittest.mock import Mock, patch

import requests

import update_scholar as scholar


class BlockedRefreshTests(unittest.TestCase):
    def setUp(self):
        self.previous = json.loads(scholar.DATA_FILE.read_text(encoding="utf-8"))

    def run_refresh(self, response, previous, allow_stale=True):
        arguments = ["update_scholar.py"] + (["--allow-stale"] if allow_stale else [])
        with (
            patch.object(sys, "argv", arguments),
            patch("requests.get", return_value=response),
            patch.object(scholar, "load_previous", return_value=previous),
            patch.object(scholar, "save_snapshot") as save,
            patch("builtins.print") as output,
        ):
            try:
                scholar.main()
            finally:
                save.assert_not_called()
        return output

    def test_blocked_refresh_preserves_snapshot_and_reports_original_date(self):
        for status in (403, 429):
            with self.subTest(status=status):
                before = copy.deepcopy(self.previous)
                output = self.run_refresh(Mock(status_code=status), self.previous)
                self.assertEqual(self.previous, before)
                warning = output.call_args.args[0]
                self.assertIn("::warning::", warning)
                self.assertIn(str(status), warning)
                self.assertIn(self.previous["updated_at"], warning)

    def test_manual_refresh_still_fails(self):
        with self.assertRaises(scholar.ScholarAccessBlocked):
            self.run_refresh(Mock(status_code=403), self.previous, allow_stale=False)

    def test_block_without_stored_data_still_fails(self):
        with self.assertRaises(scholar.ScholarAccessBlocked):
            self.run_refresh(Mock(status_code=403), None)

    def test_block_with_invalid_stored_data_still_fails(self):
        for changes in ({"publications": []}, {"total_citations": 0}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                self.run_refresh(Mock(status_code=403), {**self.previous, **changes})

    def test_other_http_errors_still_fail(self):
        for status in (404, 500):
            response = Mock(status_code=status)
            response.raise_for_status.side_effect = requests.HTTPError(str(status))
            with self.subTest(status=status), self.assertRaises(requests.HTTPError):
                self.run_refresh(response, self.previous)

    def test_incomplete_response_preserves_snapshot_and_original_date(self):
        for body in (
            "<html></html>",
            '<table id="gsc_rsb_st"><tbody>' + '<tr></tr>' * 3 + '</tbody></table>',
            '<table><tr class="gsc_a_tr"></tr></table>',
        ):
            with self.subTest(body=body):
                before = copy.deepcopy(self.previous)
                output = self.run_refresh(Mock(status_code=200, text=body), self.previous)
                self.assertEqual(self.previous, before)
                warning = output.call_args.args[0]
                self.assertIn("::warning::", warning)
                self.assertIn("blocked or incomplete", warning)
                self.assertIn(self.previous["updated_at"], warning)

    def test_incomplete_response_without_fallback_still_fails(self):
        for previous, allow_stale in ((self.previous, False), (None, True)):
            with self.subTest(allow_stale=allow_stale), self.assertRaises(scholar.ScholarProfileUnavailable):
                self.run_refresh(Mock(status_code=200, text="<html></html>"), previous, allow_stale)

    def test_incomplete_response_with_invalid_stored_data_still_fails(self):
        response = Mock(status_code=200, text="<html></html>")
        with self.assertRaisesRegex(RuntimeError, "no publications"):
            self.run_refresh(response, {**self.previous, "publications": []})

    def test_programming_errors_still_fail(self):
        with (
            patch.object(scholar, "fetch_snapshot", side_effect=RuntimeError("Unexpected bug")),
            self.assertRaisesRegex(RuntimeError, "Unexpected bug"),
        ):
            self.run_refresh(Mock(), self.previous)

    def test_invalid_fetched_metrics_still_fail_without_saving(self):
        snapshot = {**self.previous, "total_citations": 0}
        with (
            patch.object(scholar, "fetch_snapshot", return_value=snapshot),
            patch.object(scholar, "apply_curated_metadata"),
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid citation total"):
                self.run_refresh(Mock(), self.previous)

    def test_successful_refresh_still_saves_new_data(self):
        snapshot = copy.deepcopy(self.previous)
        snapshot["total_citations"] += 1
        with (
            patch.object(sys, "argv", ["update_scholar.py", "--allow-stale"]),
            patch.object(scholar, "load_previous", return_value=self.previous),
            patch.object(scholar, "fetch_snapshot", return_value=snapshot),
            patch.object(scholar, "apply_curated_metadata"),
            patch.object(scholar, "save_snapshot") as save,
            patch("builtins.print"),
        ):
            scholar.main()
        save.assert_called_once_with(snapshot)


if __name__ == "__main__":
    unittest.main()
