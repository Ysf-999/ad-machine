#!/usr/bin/env python3
"""Score Marketing Brain copy and creative packs for launch quality.

This is intentionally heuristic. It does not replace human judgment or ad
account data. It gives the agent a repeatable pre-launch scorecard so weak
creative does not ship just because it sounds polished.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
SPECS_DIR = ROOT / "specs"
sys.path.insert(0, str(SCRIPT_DIR))

from validate_copy import (  # noqa: E402
    claim_pattern_regex,
    extract_heading_body,
    extract_sections,
    extract_bold_fields,
    load_claim_patterns,
    load_product_names,
    norm,
    section,
    split_blocks,
    word_count,
)


@dataclass
class DimensionScore:
    name: str
    raw: int
    weighted: float
    max_weight: int
    notes: list[str]


@dataclass
class CreativeScore:
    scope: str
    total: float
    grade: str
    dimensions: list[DimensionScore]
    penalties: list[str]
    recommendation: str


def load_scorecard(name_or_path: str) -> dict[str, Any]:
    path = Path(name_or_path)
    if not path.exists():
        path = SPECS_DIR / f"{name_or_path}.yml"
    if not path.exists():
        raise SystemExit(f"Scorecard spec not found: {name_or_path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Could not parse {path}. Scorecard specs must be JSON-compatible YAML. {exc}") from exc


def count_hits(text: str, phrases: list[str]) -> int:
    lowered = norm(text)
    hits = 0
    for phrase in phrases:
        needle = norm(phrase)
        if not needle:
            continue
        if " " in needle:
            if needle in lowered:
                hits += 1
        elif re.search(rf"\b{re.escape(needle)}\b", lowered):
            hits += 1
    return hits


def hit_examples(text: str, phrases: list[str], limit: int = 4) -> list[str]:
    lowered = norm(text)
    examples: list[str] = []
    for phrase in phrases:
        needle = norm(phrase)
        if not needle:
            continue
        found = needle in lowered if " " in needle else bool(re.search(rf"\b{re.escape(needle)}\b", lowered))
        if found:
            examples.append(phrase)
        if len(examples) >= limit:
            break
    return examples


def score_from_hits(hits: int, thresholds: tuple[int, int, int, int]) -> int:
    if hits >= thresholds[3]:
        return 10
    if hits >= thresholds[2]:
        return 8
    if hits >= thresholds[1]:
        return 6
    if hits >= thresholds[0]:
        return 4
    return 2


def has_cta(text: str) -> bool:
    return bool(
        re.search(
            r"\b(see|try|check|get|read|learn|shop|start|claim|watch|discover|find|click|order|support)\b",
            norm(text),
        )
    )


def forbidden_hits(text: str, product_dir: Path | None) -> list[str]:
    patterns = load_claim_patterns(product_dir)
    lowered = norm(text)
    found: list[str] = []
    for pattern in patterns:
        needle = norm(pattern)
        if not needle:
            continue
        if " " in needle:
            index = lowered.find(needle)
            if index == -1:
                continue
        else:
            match = re.search(rf"\b(?:{claim_pattern_regex(needle)})\b", lowered)
            if not match:
                continue
            index = match.start()
        context = lowered[max(0, index - 120) : index]
        if re.search(r"\b(no|not|never|without|avoid|do not|does not|is not|not intended to)\b", context):
            continue
        found.append(pattern)
    return found


def timidity_hits(text: str, spec: dict[str, Any]) -> list[str]:
    rules = spec.get("timidity", {})
    terms = rules.get("terms", [])
    lowered = norm(text)
    hits: list[str] = []
    for term in terms:
        needle = norm(term)
        if not needle:
            continue
        if " " in needle:
            count = lowered.count(needle)
        else:
            count = len(re.findall(rf"\b{re.escape(needle)}\b", lowered))
        hits.extend([term] * count)
    return hits


def grade_for(total: float, thresholds: dict[str, int]) -> str:
    if total >= thresholds["scale_candidate"]:
        return "Scale Candidate"
    if total >= thresholds["testable"]:
        return "Testable"
    if total >= thresholds["needs_sharpening"]:
        return "Needs Sharpening"
    return "Not Ready"


def recommendation_for(grade: str) -> str:
    if grade == "Scale Candidate":
        return "Launch first or build variants immediately."
    if grade == "Testable":
        return "Launch as a test, then expand only if account data confirms."
    if grade == "Needs Sharpening":
        return "Revise before launch; one or two dimensions are probably soft."
    return "Do not launch yet; rebuild the angle or proof structure."


def infer_validation_spec(text: str) -> str:
    lowered = norm(text)
    if "ugc video script" in lowered or ("delivery mode" in lowered and "target length" in lowered):
        return "ugc-video-script"
    if "native image prompt" in lowered or "image prompt" in lowered:
        return "image-prompt"
    if "facebook primary text" in lowered or "primary text:" in lowered:
        return "facebook-ad-copy"
    if "long-form static" in lowered or "primary hook" in lowered and "body copy" in lowered:
        return "long-form-static"
    return "product-claims"


def run_validation_gate(file_path: Path, product_dir: Path | None, spec_name: str) -> tuple[bool, str]:
    command = [
        sys.executable,
        str(SCRIPT_DIR / "validate_copy.py"),
        "--spec",
        spec_name,
        "--file",
        str(file_path),
        "--quiet",
    ]
    if product_dir:
        command.extend(["--product-dir", str(product_dir)])
    result = subprocess.run(command, text=True, capture_output=True)
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return result.returncode == 0, output


def score_dimension(
    name: str,
    weight: int,
    body: str,
    spec: dict[str, Any],
    sections: dict[str, str],
) -> DimensionScore:
    signals = spec["signals"]
    notes: list[str] = []

    if name == "Signal Strength":
        phrases = signals["market_signal"] + signals["trigger_events"]
        hits = count_hits(body, phrases)
        raw = score_from_hits(hits, (1, 3, 5, 8))
        examples = hit_examples(body, phrases)
        notes.append("Hits: " + (", ".join(examples) if examples else "few concrete market signals"))
    elif name == "Pressure Intensity":
        phrases = signals["pressure"]
        hits = count_hits(body, phrases)
        raw = score_from_hits(hits, (1, 2, 4, 6))
        examples = hit_examples(body, phrases)
        notes.append("Pressure cues: " + (", ".join(examples) if examples else "soft or low-stakes"))
    elif name == "Belief Shift Clarity":
        phrases = signals["belief_shift"]
        hits = count_hits(body, phrases)
        has_contrast = bool(re.search(r"\b(not|instead|different|why|because|but|that is why)\b", norm(body)))
        raw = min(10, score_from_hits(hits, (1, 2, 4, 6)) + (2 if has_contrast else 0))
        notes.append("Contrast present" if has_contrast else "Needs clearer old-belief to new-belief movement")
    elif name == "Mechanism Believability":
        phrases = signals["mechanism"]
        hits = count_hits(body, phrases)
        product_detail = bool(re.search(r"\b(with|using|built around|combines|designed to|made to|powered by)\b", norm(body)))
        raw = min(10, score_from_hits(hits, (1, 3, 5, 8)) + (1 if product_detail else 0))
        examples = hit_examples(body, phrases)
        notes.append("Mechanism cues: " + (", ".join(examples) if examples else "needs a more specific reason-why"))
    elif name == "Proof Density":
        phrases = signals["proof"]
        hits = count_hits(body, phrases)
        has_number = bool(re.search(r"(\d+|%|\$)", body))
        has_disclaimer = "individual results vary" in norm(body) or "consult" in norm(body)
        raw = min(10, score_from_hits(hits, (1, 2, 4, 6)) + (1 if has_number else 0) + (1 if has_disclaimer else 0))
        notes.append("Specificity present" if has_number else "Could use more specific proof or reason-why")
    elif name == "Creative Visualizability":
        prompt = (
            section(sections, "Native Image Prompt")
            or section(sections, "Image Prompt")
            or section(sections, "Image Direction")
            or section(sections, "Carousel Cards")
            or section(sections, "Video Script")
        )
        phrases = signals["visual"]
        hits = count_hits(body, phrases)
        raw = score_from_hits(hits, (1, 3, 5, 8))
        if prompt:
            prompt_words = word_count(prompt)
            raw = min(10, raw + 3)
            notes.append(f"Visual asset present ({prompt_words} words)")
        else:
            notes.append("No visual asset found")
    elif name == "Scale Potential":
        phrases = signals["scale"]
        hits = count_hits(body, phrases)
        hook = section(sections, "Facebook Primary Text") or section(sections, "Primary Text") or section(sections, "Primary Hook")
        has_hook = bool(hook)
        raw = min(10, score_from_hits(hits, (1, 2, 4, 6)) + (2 if has_hook else 0))
        notes.append("Angle has expansion handles" if raw >= 7 else "Needs clearer variant paths")
    elif name == "Reference Application":
        phrases = signals["reference_application"]
        hits = count_hits(body, phrases)
        has_strategy_notes = "strategy notes" in norm(body) or any(
            term in norm(body)
            for term in ("schwartz", "halbert", "kennedy", "cialdini", "wundt", "buyer belief shift")
        )
        raw = min(10, score_from_hits(hits, (2, 4, 7, 10)) + (2 if has_strategy_notes else 0))
        examples = hit_examples(body, phrases)
        notes.append("Reference cues: " + (", ".join(examples) if examples else "missing explicit framework application"))
    else:
        raw = 5
        notes.append("Unknown dimension")

    weighted = raw / 10 * weight
    return DimensionScore(name=name, raw=raw, weighted=weighted, max_weight=weight, notes=notes)


def score_block(
    heading: str,
    block: str,
    spec: dict[str, Any],
    product_dir: Path | None,
) -> CreativeScore:
    sections = extract_sections(block)
    sections.update(extract_bold_fields(block))
    body = block
    penalties: list[str] = []
    penalty_points = 0
    penalty_rules = spec.get("penalties", {})

    if not has_cta(block):
        points = penalty_rules.get("missing_cta", 8)
        penalty_points += points
        penalties.append(f"-{points}: missing clear CTA/action language")

    product_names = load_product_names(product_dir)
    if product_names and not any(norm(name) in norm(block) for name in product_names):
        points = penalty_rules.get("missing_product", 8)
        penalty_points += points
        penalties.append(f"-{points}: product or brand name not detected")

    primary = section(sections, "Facebook Primary Text") or section(sections, "Body Copy") or block
    words = word_count(primary)
    if words < 70:
        points = penalty_rules.get("very_short_copy", 8)
        penalty_points += points
        penalties.append(f"-{points}: copy is very short ({words} words)")
    elif words > 500:
        points = penalty_rules.get("very_long_copy", 5)
        penalty_points += points
        penalties.append(f"-{points}: copy is very long ({words} words)")

    visual_asset_present = any(
        phrase in norm(block)
        for phrase in (
            "native image prompt",
            "image prompt",
            "image direction",
            "carousel cards",
            "video script",
        )
    )
    if not visual_asset_present:
        points = penalty_rules.get("no_image_prompt", 12)
        penalty_points += points
        penalties.append(f"-{points}: no image direction, prompt, carousel, or video script detected")

    bad_claims = forbidden_hits(block, product_dir)
    if bad_claims:
        points = penalty_rules.get("forbidden_claim", 20)
        penalty_points += points
        penalties.append(f"-{points}: claim-sensitive phrase detected: {', '.join(bad_claims[:3])}")

    timid_hits = timidity_hits(block, spec)
    timid_limit = spec.get("timidity", {}).get("max_hits_before_penalty", 999)
    if len(timid_hits) > timid_limit:
        points = penalty_rules.get("timid_copy", 8)
        penalty_points += points
        unique_hits = []
        for hit in timid_hits:
            if hit not in unique_hits:
                unique_hits.append(hit)
        penalties.append(f"-{points}: timid/hedged language over limit ({len(timid_hits)} hits): {', '.join(unique_hits[:5])}")

    dimensions: list[DimensionScore] = []
    for dim in spec["dimensions"]:
        dimensions.append(score_dimension(dim["name"], dim["weight"], body, spec, sections))

    weighted_total = sum(d.weighted for d in dimensions)
    total = max(0.0, min(100.0, weighted_total - penalty_points))
    grade = grade_for(total, spec["grade_thresholds"])
    return CreativeScore(
        scope=heading,
        total=total,
        grade=grade,
        dimensions=dimensions,
        penalties=penalties,
        recommendation=recommendation_for(grade),
    )


def render(scores: list[CreativeScore], spec_name: str, file_path: Path) -> str:
    average = sum(s.total for s in scores) / len(scores) if scores else 0
    lines = [
        "# Creative Score Report",
        "",
        f"- Scorecard: `{spec_name}`",
        f"- File: `{file_path}`",
        f"- Creatives scored: `{len(scores)}`",
        f"- Average score: `{average:.1f}/100`",
        "",
        "## Ranking",
        "",
        "| Rank | Creative | Score | Grade | Recommendation |",
        "|---:|---|---:|---|---|",
    ]
    ranked = sorted(scores, key=lambda s: s.total, reverse=True)
    for index, score in enumerate(ranked, 1):
        lines.append(
            f"| {index} | {score.scope.replace('|', '\\|')} | {score.total:.1f} | {score.grade} | {score.recommendation} |"
        )

    for score in ranked:
        lines.extend(["", f"## {score.scope}", "", f"Score: **{score.total:.1f}/100**", f"Grade: **{score.grade}**", ""])
        lines.extend(
            [
                "| Dimension | Raw | Weighted | Notes |",
                "|---|---:|---:|---|",
            ]
        )
        for dim in score.dimensions:
            notes = "; ".join(dim.notes).replace("|", "\\|")
            lines.append(f"| {dim.name} | {dim.raw}/10 | {dim.weighted:.1f}/{dim.max_weight} | {notes} |")
        if score.penalties:
            lines.extend(["", "Penalties:"])
            lines.extend(f"- {penalty}" for penalty in score.penalties)
        else:
            lines.extend(["", "Penalties: none"])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Score Marketing Brain copy and creatives.")
    parser.add_argument("--scorecard", default="creative-scorecard", help="Scorecard name or path.")
    parser.add_argument("--file", required=True, type=Path, help="Markdown file to score.")
    parser.add_argument("--product-dir", type=Path, help="Optional product packet folder.")
    parser.add_argument("--report", type=Path, help="Optional Markdown report output path.")
    parser.add_argument("--validation-spec", help="Validation spec to run before scoring. Defaults to inferred spec.")
    parser.add_argument("--skip-validation-gate", action="store_true", help="Score anyway; report is advisory and should not be used for launch priority.")
    parser.add_argument("--quiet", action="store_true", help="Print only summary.")
    args = parser.parse_args()

    spec = load_scorecard(args.scorecard)
    text = args.file.read_text(encoding="utf-8", errors="ignore")
    validation_spec = args.validation_spec or infer_validation_spec(text)
    if not args.skip_validation_gate:
        passed, validation_output = run_validation_gate(args.file, args.product_dir, validation_spec)
        if not passed:
            message = f"VALIDATION GATE FAILED: `{validation_spec}` did not pass for {args.file}.\n{validation_output}"
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text("# Creative Score Report\n\n" + message + "\n", encoding="utf-8")
            print(message, file=sys.stderr)
            return 2
    blocks = split_blocks(text, spec["block_heading_regex"])
    if not blocks:
        blocks = [("Document", text, 1)]
    strategy_context = extract_heading_body(text, "Strategy Notes")

    scores = [
        score_block(
            heading,
            block + (f"\n\n## Strategy Notes\n\n{strategy_context}" if strategy_context else ""),
            spec,
            args.product_dir,
        )
        for heading, block, _line in blocks
    ]
    report = render(scores, spec.get("name", args.scorecard), args.file)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report + "\n", encoding="utf-8")

    if args.quiet:
        average = sum(s.total for s in scores) / len(scores) if scores else 0
        top = max(scores, key=lambda s: s.total) if scores else None
        if top:
            print(f"SCORED: {len(scores)} creative(s), avg {average:.1f}/100, top '{top.scope}' at {top.total:.1f}/100")
        else:
            print("SCORED: 0 creative(s)")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
