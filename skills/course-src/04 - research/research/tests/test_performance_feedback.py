from __future__ import annotations

import csv
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

from marketing_brain_test_support import load_script_module


performance_feedback = load_script_module("performance_feedback")


class PerformanceFeedbackTest(unittest.TestCase):
    def test_classifies_post_click_failure_modes(self):
        self.assertEqual(
            performance_feedback.classify_row({"outbound_ctr": "0.002", "cpm": "20"})["failure_mode"],
            "hook_or_visual_failure",
        )
        self.assertEqual(
            performance_feedback.classify_row({"outbound_ctr": "0.018", "lpv_rate": "0.85", "quiz_start_rate": "0.08"})["failure_mode"],
            "promise_page_mismatch",
        )
        self.assertEqual(
            performance_feedback.classify_row({"quiz_start_rate": "0.35", "quiz_complete_rate": "0.09"})["failure_mode"],
            "quiz_friction",
        )
        self.assertEqual(
            performance_feedback.classify_row({"checkout_view_rate": "0.18", "purchase_cpa": "700"})["failure_mode"],
            "checkout_offer_trust_or_economics",
        )

    def test_does_not_overreact_to_explicit_tiny_sample(self):
        diagnosis = performance_feedback.classify_row(
            {"spend": "7", "impressions": "300", "outbound_ctr": "0.001", "cpm": "20"}
        )

        self.assertEqual(diagnosis["failure_mode"], "insufficient_signal")
        self.assertEqual(diagnosis["decision"], "collect_more_data")

    def test_analyze_ledger_renders_decisions(self):
        with TemporaryDirectory() as directory:
            ledger = Path(directory) / "creative-ledger.csv"
            with ledger.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "creative_id",
                        "concept",
                        "outbound_ctr",
                        "lpv_rate",
                        "quiz_start_rate",
                        "quiz_complete_rate",
                        "checkout_view_rate",
                        "purchase_cpa",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "creative_id": "a1",
                        "concept": "Trust Checklist",
                        "outbound_ctr": "0.02",
                        "lpv_rate": "0.8",
                        "quiz_start_rate": "0.07",
                    }
                )

            report = performance_feedback.render_feedback(performance_feedback.analyze_ledger(ledger), ledger)

        self.assertIn("Trust Checklist", report)
        self.assertIn("promise_page_mismatch", report)
        self.assertIn("Revise bridge or destination", report)


if __name__ == "__main__":
    unittest.main()
