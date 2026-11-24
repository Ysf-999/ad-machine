# Control Library Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert uploaded high-performing ad batch analyses into a reusable Marketing Brain control-pattern library that improves UGC scripts without copying winning ads.

**Architecture:** Add a deterministic Python ingestion script that parses batch markdown into normalized controls, aggregate patterns, and an index report. Update Marketing Brain skills so script creation retrieves matching control patterns before writing, adapts structure rather than wording, and scores control-pattern fit.

**Tech Stack:** Python 3 standard library, markdown skill files, JSON-compatible scorecard specs.

---

### Task 1: Control Library Ingestion Script

**Files:**
- Create: `marketing-brain/scripts/build_control_library.py`
- Test: `tests/test_build_control_library.py`

- [ ] **Step 1: Write the failing parser tests**

```python
from pathlib import Path

from marketing_brain_test_support import load_script_module


build_control_library = load_script_module("build_control_library")


def test_parse_batch_extracts_video_controls(tmp_path: Path):
    batch = tmp_path / "batch_001.md"
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

    assert len(controls) == 1
    control = controls[0]
    assert control.asset_name == "Winning Podcast Ad.mp4"
    assert control.framework == "Educational Authority / Myth-Busting."
    assert control.pattern_id == "podcast-myth-bust"
    assert control.hook_type == "curiosity-gap"
    assert control.raw_transcript.startswith("Can adults really")
    assert control.visual_variables == ["Podcast Aesthetics", "Counter-Intuitive Logic"]


def test_build_library_groups_patterns_and_blocks_copying(tmp_path: Path):
    first = tmp_path / "batch_001.md"
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
    second = tmp_path / "batch_002.md"
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

    assert patterns[0]["pattern_id"] == "psa-warning"
    assert patterns[0]["control_count"] == 2
    assert "copy the transcript" in patterns[0]["do_not_copy"].lower()
    assert "warning" in patterns[0]["transferable_pattern"].lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests/test_build_control_library.py -v`

Expected: FAIL because `build_control_library.py` does not exist yet.

- [ ] **Step 3: Create minimal test support and implementation**

Create `tests/marketing_brain_test_support.py` to import scripts by path because the project folder uses a hyphen. Create `build_control_library.py` with dataclasses, batch parsing, pattern classification, JSON/report writers, and a CLI.

- [ ] **Step 4: Run parser tests**

Run: `python3 -m unittest tests/test_build_control_library.py -v`

Expected: PASS.

### Task 2: Generate The Initial Control Library From Uploaded Batches

**Files:**
- Create: `marketing-brain/references/control-library/controls.json`
- Create: `marketing-brain/references/control-library/patterns.json`
- Create: `marketing-brain/references/control-library/index.md`

- [ ] **Step 1: Run ingestion on uploaded analyses**

Run:

```bash
python3 marketing-brain/scripts/build_control_library.py \
  --input-dir "<path to analysis_output>" \
  --output-dir marketing-brain/references/control-library
```

Expected: generated JSON and Markdown files that include controls from every `batch_*.md`.

- [ ] **Step 2: Inspect generated index**

Run: `sed -n '1,220p' marketing-brain/references/control-library/index.md`

Expected: top patterns include dialogue/skeptic, podcast myth-bust, PSA warning, listicle signs, authority expert, POV skit, and timeline reveal when present in the supplied batches.

### Task 3: Wire Control Patterns Into Skills

**Files:**
- Modify: `marketing-brain/skills/control-intelligence/SKILL.md`
- Modify: `marketing-brain/skills/ugc-video-script/SKILL.md`
- Modify: `marketing-brain/skills/dtc-research-orchestrator/SKILL.md`
- Modify: `marketing-brain/templates/winning-asset/deconstruction.md`

- [ ] **Step 1: Add control-library operating rules**

Update `control-intelligence` with ingestion, taxonomy, matching, and anti-copy rules.

- [ ] **Step 2: Add reference-control selection to UGC scripts**

Update `ugc-video-script` so every script pack chooses 1-3 matching patterns, states why they fit, adapts their belief movement, and lists what must not be copied.

- [ ] **Step 3: Update orchestration**

Update `dtc-research-orchestrator` so uploaded winning ads trigger control-library ingestion before script generation.

- [ ] **Step 4: Expand the deconstruction template**

Add first-three-seconds, retention device, visual grammar, native believability, pattern ID, adaptation rules, and compliance transfer fields.

### Task 4: Add Scorecard Fit For Non-Slop Copy

**Files:**
- Modify: `marketing-brain/specs/creative-scorecard.yml`

- [ ] **Step 1: Inspect current scorecard JSON**

Run: `sed -n '1,260p' marketing-brain/specs/creative-scorecard.yml`

Expected: score dimensions are JSON-compatible.

- [ ] **Step 2: Add control pattern signals**

Add signal terms and, if the script supports it, a score dimension for control-pattern fit and native believability. If the scorer is fixed to known dimension names, add these terms under existing dimensions rather than breaking the scorer.

### Task 5: Verify The Brain Upgrade

**Files:**
- All changed files.

- [ ] **Step 1: Run unit tests**

Run: `python3 -m unittest tests/test_build_control_library.py -v`

Expected: PASS.

- [ ] **Step 2: Run ingestion against real batches**

Run:

```bash
python3 marketing-brain/scripts/build_control_library.py \
  --input-dir "<path to analysis_output>" \
  --output-dir marketing-brain/references/control-library
```

Expected: successful report with total controls and total patterns.

- [ ] **Step 3: Check generated files**

Run:

```bash
python3 -m json.tool marketing-brain/references/control-library/controls.json >/tmp/controls-json-ok
python3 -m json.tool marketing-brain/references/control-library/patterns.json >/tmp/patterns-json-ok
sed -n '1,160p' marketing-brain/references/control-library/index.md
```

Expected: both JSON files parse and the index is human-readable.

- [ ] **Step 4: Check git diff**

Run: `git diff --stat && git diff -- marketing-brain/skills/ugc-video-script/SKILL.md marketing-brain/skills/control-intelligence/SKILL.md`

Expected: changes are scoped to control-library ingestion and Marketing Brain skill wiring.
