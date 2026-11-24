from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

from marketing_brain_test_support import PROJECT_ROOT, load_script_module


score_creative = load_script_module("score_creative")


class ScoreCreativeUpgradeTest(unittest.TestCase):
    def test_scorecard_splits_ugc_scripts_as_separate_creatives(self):
        spec = score_creative.load_scorecard("creative-scorecard")
        text = """## UGC Video Script 1: First

body

## UGC Video Script 2: Second

body
"""

        blocks = score_creative.split_blocks(text, spec["block_heading_regex"])

        self.assertEqual([heading for heading, _block, _line in blocks], ["UGC Video Script 1: First", "UGC Video Script 2: Second"])

    def test_infers_ugc_validation_spec_from_script_pack(self):
        text = """## UGC Video Script: Example

**Delivery Mode:** creator_brief
**Target Length:** 60s
"""

        self.assertEqual(score_creative.infer_validation_spec(text), "ugc-video-script")

    def test_score_command_blocks_when_validation_fails(self):
        with TemporaryDirectory() as directory:
            product_dir = Path(directory) / "product"
            product_dir.mkdir()
            (product_dir / "offer.md").write_text("Product name: TestProduct\n", encoding="utf-8")
            creative = Path(directory) / "bad-script.md"
            creative.write_text(
                """## UGC Video Script: TestProduct

**Format:** `fake_vs_real_psa`
**Delivery Mode:** `ai_talking_head`
**Platform:** `meta`
**Target Length:** `60s`
**Audience:** Buyers
**Awareness Level:** Solution-aware
**Creator Profile:** Creator
**Offer:** TestProduct

### Script

| Beat | Timing | Line | B-Roll / Visual |
|---|---|---|---|
| Hook | 0-3s | Hi | Face |
""",
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(PROJECT_ROOT / "marketing-brain" / "scripts" / "score_creative.py"),
                "--file",
                str(creative),
                "--product-dir",
                str(product_dir),
                "--quiet",
            ]

            result = subprocess.run(command, cwd=PROJECT_ROOT, text=True, capture_output=True)

        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("VALIDATION GATE FAILED", combined)
        self.assertIn("ugc-video-script", combined)


if __name__ == "__main__":
    unittest.main()
