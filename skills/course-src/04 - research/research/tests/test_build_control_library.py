from __future__ import annotations

import unittest
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

from marketing_brain_test_support import load_script_module


build_control_library = load_script_module("build_control_library")


class BuildControlLibraryTest(unittest.TestCase):
    def test_parse_batch_extracts_video_controls(self):
        with TemporaryDirectory() as directory:
            batch = Path(directory) / "batch_001.md"
            batch.write_text(
                """### Video Name: Winning Podcast Ad.mp4

**1. Complete RAW Transcript**
"Can adults really pick up a new language as fast as kids?"

**2. Copywriting Framework & Psychology**
*   **Identified Framework:** Educational Authority / Myth-Busting.
*   **The Hook (0-3s):** Curiosity Gap & Skepticism. It asks a fundamental question.
*   **The CTA:** Soft Educational CTA.

**3. Visual & Directing Breakdown (Scene-by-Scene)**

| Timestamp | Spoken Script / Audio | Visuals (Actor Actions, B-Roll, Camera Movement) | Text On Screen (Captions/Pop-ups) |
| :--- | :--- | :--- | :--- |
| *0:00-0:03* | "Can adults really pick up a new language as fast as kids?" | Podcast studio. | ADULTS CAN LEARN |

**4. Viral / Converting Variables**
*   **Podcast Aesthetics:** It does not look like an ad.
*   **Counter-Intuitive Logic:** Studying grammar makes you fail.
""",
                encoding="utf-8",
            )

            controls = build_control_library.parse_batches([batch])

        self.assertEqual(len(controls), 1)
        control = controls[0]
        self.assertEqual(control.asset_name, "Winning Podcast Ad.mp4")
        self.assertEqual(control.framework, "Educational Authority / Myth-Busting.")
        self.assertEqual(control.pattern_id, "podcast-myth-bust")
        self.assertEqual(control.hook_type, "curiosity-gap")
        self.assertTrue(control.raw_transcript.startswith("Can adults really"))
        self.assertEqual(control.visual_variables, ["Podcast Aesthetics", "Counter-Intuitive Logic"])

    def test_build_library_groups_patterns_and_blocks_copying(self):
        with TemporaryDirectory() as directory:
            first = Path(directory) / "batch_001.md"
            first.write_text(
                """### Video Name: A.mp4

**1. Complete RAW Transcript**
"Stop buying more scented stuff."

**2. Copywriting Framework & Psychology**
*   **Identified Framework:** Us vs. Them / PSA (Warning).
*   **The Hook (0-3s):** Negative/Safety Hook.
*   **The CTA:** Social Proof / Link.

**4. Viral / Converting Variables**
*   **Fear-Based Hook:** Warning creates loss aversion.
""",
                encoding="utf-8",
            )
            second = Path(directory) / "batch_002.md"
            second.write_text(
                """### Video Name: B.mp4

**1. Complete RAW Transcript**
"Please be careful when buying this."

**2. Copywriting Framework & Psychology**
*   **Identified Framework:** Us vs. Them / PSA (Warning).
*   **The Hook (0-3s):** Negative/Safety Hook.
*   **The CTA:** Social Proof / Link.

**4. Viral / Converting Variables**
*   **Visual Contrast:** Real versus fake is obvious.
""",
                encoding="utf-8",
            )

            controls = build_control_library.parse_batches([first, second])
            patterns = build_control_library.aggregate_patterns(controls)

        self.assertEqual(patterns[0]["pattern_id"], "psa-warning")
        self.assertEqual(patterns[0]["control_count"], 2)
        self.assertIn("copy the transcript", patterns[0]["do_not_copy"].lower())
        self.assertIn("warning", patterns[0]["transferable_pattern"].lower())

    def test_aggregate_patterns_marks_pattern_only_evidence_weight(self):
        with TemporaryDirectory() as directory:
            batch = Path(directory) / "batch_001.md"
            batch.write_text(
                """### Video Name: A.mp4

**1. Complete RAW Transcript**
"Stop buying more scented stuff."

**2. Copywriting Framework & Psychology**
*   **Identified Framework:** Us vs. Them / PSA (Warning).
*   **The Hook (0-3s):** Negative/Safety Hook.
*   **The CTA:** Social Proof / Link.

**4. Viral / Converting Variables**
*   **Fear-Based Hook:** Warning creates loss aversion.

### Video Name: B.mp4

**1. Complete RAW Transcript**
"Please be careful when buying this."

**2. Copywriting Framework & Psychology**
*   **Identified Framework:** Us vs. Them / PSA (Warning).
*   **The Hook (0-3s):** Negative/Safety Hook.
*   **The CTA:** Social Proof / Link.

**4. Viral / Converting Variables**
*   **Visual Contrast:** Real versus fake is obvious.
""",
                encoding="utf-8",
            )

            controls = build_control_library.parse_batches([batch])
            patterns = build_control_library.aggregate_patterns(controls)

        self.assertEqual(patterns[0]["pattern_id"], "psa-warning")
        self.assertEqual(patterns[0]["evidence_quality"], "pattern-only")
        self.assertEqual(patterns[0]["performance_status_counts"], {"Pattern-only": 2})
        self.assertEqual(patterns[0]["performance_weight"], 0.5)


if __name__ == "__main__":
    unittest.main()
