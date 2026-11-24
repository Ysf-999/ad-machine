from __future__ import annotations

import unittest
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

from marketing_brain_test_support import load_script_module


validate_copy = load_script_module("validate_copy")


class ValidateCopyUpgradeTest(unittest.TestCase):
    def test_normalize_value_strips_markdown_code_markup(self):
        self.assertEqual(validate_copy.normalize_value("`meta`"), "meta")
        self.assertEqual(validate_copy.normalize_value(" `ai_talking_head` "), "ai_talking_head")

    def test_load_claim_patterns_reads_plain_constraint_sections_and_forbidden_words(self):
        with TemporaryDirectory() as directory:
            product_dir = Path(directory)
            (product_dir / "constraints.md").write_text(
                """# Constraints

Claims we cannot make:
- "Cures," "treats," or "prevents" BV, yeast infections, or any diagnosed condition
- "Clinically proven to cure vaginal odor"

Forbidden words: cure, treat, prevent, diagnose, infection (in a disease context), disease
""",
                encoding="utf-8",
            )

            patterns = validate_copy.load_claim_patterns(product_dir)

        self.assertIn("cure", patterns)
        self.assertIn("treat", patterns)
        self.assertIn("prevent", patterns)
        self.assertIn("diagnose", patterns)
        self.assertIn("infection", patterns)
        self.assertIn("Clinically proven to cure vaginal odor", patterns)

    def test_product_claims_flags_forbidden_stems_from_plain_constraints(self):
        with TemporaryDirectory() as directory:
            product_dir = Path(directory)
            (product_dir / "offer.md").write_text("Product name: URO\n", encoding="utf-8")
            (product_dir / "constraints.md").write_text(
                """# Constraints

Claims we cannot make:
- "Cures," "treats," or "prevents" BV, yeast infections, or any diagnosed condition

Forbidden words: cure, treat, prevent, diagnose, infection
""",
                encoding="utf-8",
            )
            copy = "URO prevents BV from coming back by rebuilding the microbiome."
            spec = validate_copy.load_spec("product-claims")

            findings, _metrics = validate_copy.validate_claims(copy, spec, product_dir, extreme=False)

        errors = [finding.message for finding in findings if finding.severity == "error"]
        self.assertTrue(any("prevent" in message.casefold() for message in errors))

    def test_ugc_flex_accepts_extra_beat_and_backticked_fields_when_core_jobs_have_sources(self):
        script = """## UGC Video Script: Example

**Format:** `fake_vs_real_psa`
**Delivery Mode:** `ai_talking_head`
**Platform:** `meta`
**Target Length:** `60s`
**Audience:** Skeptical buyers
**Awareness Level:** Solution-aware
**Creator Profile:** Calm creator
**Offer:** Start the assessment

### Reference Control Selection

| Pattern ID | Why It Fits | Belief Movement Borrowed | Visual Grammar Borrowed | Product Proof Needed | Do Not Copy |
|---|---|---|---|---|---|
| psa-warning | Trust fear | fear to evaluation | checklist | page proof | claims |

### Hook Options

1. "Your scam radar is not wrong." — negative warning [source: VOC]
2. "Check this before you pay." — insider secret [source: control-library/psa-warning]
3. "The page should answer this first." — process reveal [source: product-info]

### Script

| Beat | Timing | Line (ai_talking_head) | Source | B-Roll / Visual |
|---|---|---|---|---|
| Hook | 0-3s | "Your scam radar is not wrong." | VOC | Creator close-up |
| Pain | 3-11s | "The ads all sound the same and the buyer worries about wasting money." | VOC | Blurred generic ads |
| Mechanism | 11-31s | "Use a five point checklist before choosing any program." | product-info | Notes checklist |
| Product Bridge | 31-40s | "The assessment starts before the treatment decision." | product-info | Page screen recording |
| Proof + Objection | 40-52s | "Check price, reviews, eligibility, and support before you continue." | product-info | Price and review proof |
| CTA | 52-60s | "Start the assessment and use the checklist as you go." | offer | CTA button |

### Spoken Word Count

| Beat | Words | Cumulative |
|---|---:|---:|
| Hook | 6 | 6 |
| Pain | 12 | 18 |
| Mechanism | 10 | 28 |
| Product Bridge | 9 | 37 |
| Proof + Objection | 9 | 46 |
| CTA | 10 | 56 |
| **Total** | 56 | 56 |

**Target window for 60s:** 180-220
**Status:** within window

### B-Roll Shot List

1. Creator close-up
2. Checklist
3. Page screen recording
4. CTA button

### Do's

- Use real page captures.

### Don'ts

- Do not invent proof.

### Launch Notes

No original lines need review.

## Strategy Notes

**Awareness Stage:** solution-aware
**Market Sophistication:** stage 4
**Buyer Belief Shift:** "this is a scam" -> "I can verify the process"
**Market Signal:** VOC trust fear
**Reference Control Pattern:** psa-warning adapted, not copied
**Schwartz Lever:** mechanism elaboration
**Halbert Lever:** AIDA checklist
**Kennedy Lever:** proof before CTA
**Cialdini Lever:** reciprocity through checklist
**Wundt Inhibition:** removes scam fear
**Copy-Chief Pass:** sharpened the hook and proof order

## Testing Recommendation

| Priority | Hook Option | Format Variant | Why Test First |
|---:|---|---|---|
| 1 | Hook 1 | 60s | Highest trust fit |
"""
        spec = validate_copy.load_spec("ugc-video-script")

        findings, _metrics = validate_copy.validate_ugc_video_script(script, spec, None, extreme=False)

        errors = [finding.message for finding in findings if finding.severity == "error"]
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
