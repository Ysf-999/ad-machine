from __future__ import annotations

import csv
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

from marketing_brain_test_support import load_script_module


creative_ledger = load_script_module("creative_ledger")


class CreativeLedgerTest(unittest.TestCase):
    def test_init_creates_ledger_header_with_strategy_validation_and_performance_fields(self):
        with TemporaryDirectory() as directory:
            product_dir = Path(directory)

            ledger_path = creative_ledger.init_ledger(product_dir)
            header = ledger_path.read_text(encoding="utf-8").splitlines()[0].split(",")

        for field in (
            "creative_id",
            "concept",
            "hypothesis",
            "variable_tested",
            "belief_shift",
            "validation_spec",
            "validation_status",
            "score",
            "spend",
            "thumbstop_rate",
            "outbound_ctr",
            "lpv_rate",
            "quiz_start_rate",
            "quiz_complete_rate",
            "checkout_view_rate",
            "purchase_cpa",
            "decision",
        ):
            self.assertIn(field, header)

    def test_append_row_preserves_header_and_records_creative(self):
        with TemporaryDirectory() as directory:
            product_dir = Path(directory)
            ledger_path = creative_ledger.init_ledger(product_dir)

            creative_ledger.append_row(
                product_dir,
                {
                    "creative_id": "trimrx-001",
                    "concept": "Scam Radar Checklist",
                    "hypothesis": "Trust inhibition blocks quiz starts",
                    "variable_tested": "first_frame",
                    "validation_spec": "ugc-video-script",
                    "validation_status": "PASS",
                    "score": "80.5",
                    "decision": "queued",
                },
            )

            with ledger_path.open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["creative_id"], "trimrx-001")
        self.assertEqual(rows[0]["concept"], "Scam Radar Checklist")
        self.assertEqual(rows[0]["decision"], "queued")


if __name__ == "__main__":
    unittest.main()
