#!/usr/bin/env python3
"""Build a reusable control-pattern library from winning-ad batch analyses.

The input files are Markdown exports that contain repeated blocks shaped like:

    ### Video Name: ...
    **1. Complete RAW Transcript**
    **2. Copywriting Framework & Psychology**
    **3. Visual & Directing Breakdown (Scene-by-Scene)**
    **4. Viral / Converting Variables**

The output is deliberately pattern-focused. It stores transcripts for evidence,
but the index teaches agents to adapt the structure, belief movement, visual
grammar, and proof stack instead of copying surface wording.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class Control:
    asset_name: str
    source_file: str
    asset_type: str
    performance_status: str
    raw_transcript: str
    framework: str
    hook: str
    hook_type: str
    cta: str
    pattern_id: str
    pattern_name: str
    transferable_pattern: str
    do_not_copy: str
    adaptation_rules: list[str]
    visual_variables: list[str]
    scene_rows: list[dict[str, str]]


PATTERN_METADATA: dict[str, dict[str, object]] = {
    "dialogue-skeptic": {
        "name": "Skeptical Friend Dialogue",
        "transferable": "One speaker voices the viewer's objection; the second answers with a sharper mechanism, proof, and low-friction next step.",
        "best_for": "Problem-aware or solution-aware buyers with obvious skepticism, category fatigue, or 'is this just another X?' resistance.",
        "do_not_copy": "Do not copy the transcript, jokes, exact objection wording, or brand-specific claims. Rebuild the skeptic's line from the target buyer's real inhibition.",
        "rules": [
            "Open with the objection the buyer is already thinking.",
            "Use the answerer to create a new belief, not to list features.",
            "Let the skeptic ask the next sales objection before the viewer can leave.",
            "End with one direct CTA or one clear curiosity bridge.",
        ],
    },
    "podcast-myth-bust": {
        "name": "Podcast Myth-Bust",
        "transferable": "A casual authority conversation challenges a common belief, explains why the old method fails, then reveals the better mechanism.",
        "best_for": "Categories where education increases conversion: supplements, beauty, language learning, software, financial tools.",
        "do_not_copy": "Do not copy the podcast topic, stat, or authority claim unless substantiated for the product.",
        "rules": [
            "Start with a belief the market recognizes as true.",
            "Use the second speaker to make the contradiction feel obvious.",
            "Name the failed alternative before naming the product.",
            "Make the mechanism visual or metaphorical enough to understand on mute.",
        ],
    },
    "psa-warning": {
        "name": "PSA Warning / Be Careful",
        "transferable": "A friend-style warning alerts the viewer to a hidden buying mistake, shows the tell, contrasts bad options with the real solution, then points to proof.",
        "best_for": "Saturated markets, copycat products, sensitive health categories, and buyers afraid of wasting money or making symptoms worse.",
        "do_not_copy": "Do not copy the transcript, fake-versus-real examples, or safety claims. Only use warnings you can prove with product/category evidence.",
        "rules": [
            "Open with a protective warning, not a sales pitch.",
            "Show the visible tell or failed-alternative pattern.",
            "Create contrast before introducing the product.",
            "Back the recommendation with reviews, numbers, guarantee, or authority.",
        ],
    },
    "listicle-signs": {
        "name": "Three Signs Listicle",
        "transferable": "A fast diagnostic list makes the viewer self-qualify, then connects the signs to a hidden cause and a simple next step.",
        "best_for": "Problem-aware cold traffic where buyers recognize symptoms but do not understand the mechanism.",
        "do_not_copy": "Do not invent symptoms, stats, medical implications, or urgency claims. Use only signs proven by research, reviews, or the landing page.",
        "rules": [
            "Use concrete observable signs, not generic pain labels.",
            "Make each sign visually obvious in one shot.",
            "After the list, reveal the common mechanism behind all signs.",
            "Keep the product step simple and frictionless.",
        ],
    },
    "authority-expert": {
        "name": "Authority Expert Explainer",
        "transferable": "A credible expert or expert-coded creator validates the problem, discredits a common workaround, and explains a specific product mechanism.",
        "best_for": "Health, beauty, finance, and other high-trust categories where proof and safety lower CAC.",
        "do_not_copy": "Do not invent credentials, patient experience, clinical proof, certifications, or 'only brand' claims.",
        "rules": [
            "Open with a real credential or transparent role only if true.",
            "Use the authority to simplify the mechanism, not to bully the viewer.",
            "Contrast the product against a known failed alternative.",
            "Add proof and risk reversal near the CTA.",
        ],
    },
    "pov-skit": {
        "name": "POV Skit / Relatable Moment",
        "transferable": "A recognizable micro-moment dramatizes the buyer's private frustration, then an absolution line shifts blame from the buyer to the method.",
        "best_for": "Cold traffic with shame, frustration, or self-blame, especially TikTok/Reels native formats.",
        "do_not_copy": "Do not copy the exact skit premise. Rebuild the moment from product-specific VOC.",
        "rules": [
            "Use a setting the buyer has actually lived.",
            "Make the first line work without product context.",
            "Add an ego-save: 'it's not you, it's the way you solved it.'",
            "Reveal the product after the belief shift, not before.",
        ],
    },
    "timeline-reveal": {
        "name": "Timeline Reveal",
        "transferable": "The ad turns an invisible process into a sequence: day one, week one, week four, or expected-use milestones.",
        "best_for": "Supplements, skincare, routines, and tools where expectations and consistency drive conversion.",
        "do_not_copy": "Do not invent speed of results. Use the product page, reviews, studies, or guarantee terms for the timeline.",
        "rules": [
            "Use honest milestones and expectation setting.",
            "Show what changes in routine before claiming outcomes.",
            "Make the final milestone a proof or confidence moment.",
            "Handle 'how long does it take?' before the CTA.",
        ],
    },
    "street-interview": {
        "name": "Street Interview / Discovery Clip",
        "transferable": "A curious outsider asks a successful or relevant person what they use, creating social proof and discovery energy.",
        "best_for": "Status-driven products, software, education, and offers where the buyer wants a shortcut from someone ahead of them.",
        "do_not_copy": "Do not fake street proof, income claims, or identity status. Use real creator role-play or clearly staged UGC.",
        "rules": [
            "Open with a compliment or specific result.",
            "Let the answer create mystery before the product reveal.",
            "Keep the conversation short and interrupted-feeling.",
            "Use a cliffhanger only when the landing page resolves it fast.",
        ],
    },
    "comparison-contrast": {
        "name": "Old Way vs. New Way Contrast",
        "transferable": "The control makes the old solution look obviously insufficient, then frames the product as the new category or better method.",
        "best_for": "Commoditized markets, competitor-heavy products, and buyers who have tried multiple alternatives.",
        "do_not_copy": "Do not name or attack competitors unless legal/compliance review allows it.",
        "rules": [
            "Make the old way specific and familiar.",
            "Contrast on mechanism, friction, proof, or outcome.",
            "Avoid generic 'better' language; show the difference.",
            "Use one clear before/after belief shift.",
        ],
    },
    "demo-unboxing": {
        "name": "Demo / Unboxing Proof",
        "transferable": "The creator opens, applies, uses, or demonstrates the product so proof comes through sensory evidence instead of explanation.",
        "best_for": "Visual products, tactile offers, TikTok Shop, beauty, pet, home, apparel, and low-consideration buys.",
        "do_not_copy": "Do not rely on feature dumping. The demo must answer a buying objection.",
        "rules": [
            "Start with motion: open, pour, apply, compare, or use.",
            "Show label, texture, quantity, size, or ease of use.",
            "Turn the demo into a reason-why.",
            "End with a direct product-forward CTA.",
        ],
    },
    "problem-solution-rant": {
        "name": "Problem-Solution Rant",
        "transferable": "A creator vents the exact private frustration, names failed attempts, reveals the hidden cause, and positions the product as the next obvious move.",
        "best_for": "Strong pain, recurring frustration, and buyers who feel unseen or blamed.",
        "do_not_copy": "Do not copy the emotional phrasing unless it comes from the target product's VOC.",
        "rules": [
            "Use the buyer's lived behaviors, not generic pain points.",
            "Name two failed alternatives before the product.",
            "Use one hidden-cause sentence as the belief pivot.",
            "Make the CTA feel like advice from a friend.",
        ],
    },
    "contrarian-reframe": {
        "name": "Contrarian Reframe",
        "transferable": "A familiar belief is challenged fast, then the ad explains why the accepted path is outdated, incomplete, or backwards.",
        "best_for": "Markets with stale conventional wisdom, failed mainstream advice, or buyers who need a new frame before they can want the product.",
        "do_not_copy": "Do not copy the exact contrarian claim. Build the reframe from product-specific market frustration and proof.",
        "rules": [
            "Open by contradicting a belief the buyer recognizes.",
            "Give the viewer a reason the old belief failed them.",
            "Reveal the product mechanism as the practical alternative.",
            "Use proof quickly so the contradiction does not feel like empty hot take bait.",
        ],
    },
    "process-reveal": {
        "name": "Process Reveal / Proof of Work",
        "transferable": "The ad shows the behind-the-scenes process, document, workflow, or screen that produces the outcome, making the value feel tangible.",
        "best_for": "SaaS, services, research-heavy offers, creators, agencies, and products where the buyer distrusts vague claims.",
        "do_not_copy": "Do not fake dashboards, documents, research outputs, or performance data.",
        "rules": [
            "Start with the artifact or workflow, not a promise.",
            "Show the steps that create the result.",
            "Translate each step into a buyer benefit.",
            "Close by making access to the process the CTA.",
        ],
    },
    "internal-monologue": {
        "name": "Internal Monologue / Decision Debate",
        "transferable": "Two sides of the buyer's mind debate cost, risk, desire, and skepticism until the product resolves the stuck decision.",
        "best_for": "High-consideration purchases, diet/beauty/finance offers, and buyers stuck between wanting a result and fearing wasted money.",
        "do_not_copy": "Do not copy the persona split or exact objections. Use the product's actual objection map.",
        "rules": [
            "Open inside the buyer's private argument.",
            "Let the skeptical side say the real objection.",
            "Let proof and risk reversal resolve the debate.",
            "Avoid cartoon acting unless the platform and product can support it.",
        ],
    },
    "redemption-story": {
        "name": "Redemption / Revenge Story",
        "transferable": "A dramatic social reversal creates curiosity, then the product becomes the mechanism behind the transformation.",
        "best_for": "Identity, status, beauty, fitness, dating, and transformation markets with strong before/after emotional stakes.",
        "do_not_copy": "Do not fabricate drama, before/after results, or personal stories.",
        "rules": [
            "Open at the social conflict or reversal.",
            "Make the identity wound concrete.",
            "Reveal the mechanism behind the comeback.",
            "Use only substantiated transformation proof.",
        ],
    },
    "whistleblower-personification": {
        "name": "Whistleblower / Personified Mechanism",
        "transferable": "An ingredient, product, or insider voice exposes why the market ignores the real mechanism, creating a suppressed-truth frame.",
        "best_for": "Ingredient-led beauty, supplements, wellness, and categories where the market has been trained to chase the wrong hero.",
        "do_not_copy": "Do not imply conspiracy, suppression, or industry wrongdoing without evidence.",
        "rules": [
            "Personify the mechanism only when it clarifies the reason-why.",
            "Name the false hero or distraction.",
            "Explain what the overlooked mechanism actually does.",
            "Keep the proof grounded; do not drift into unsupported conspiracy.",
        ],
    },
    "generic-control": {
        "name": "Generic Control Pattern",
        "transferable": "Reusable direct-response structure present, but the source needs human classification before being treated as a reliable pattern.",
        "best_for": "Temporary holding bucket for ambiguous controls.",
        "do_not_copy": "Do not use until a strategist classifies the pattern.",
        "rules": [
            "Review manually before adapting.",
            "Extract belief shift and proof stack before writing variants.",
        ],
    },
}


PERFORMANCE_WEIGHTS = {
    "Pattern-only": 0.25,
    "Unknown": 0.25,
    "Winner": 1.0,
    "Control": 1.25,
    "Scaled control": 2.0,
}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def clean(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", text).strip()
    text = re.sub(r"^\s*[\"']|[\"']\s*$", "", text)
    return text.strip()


def split_video_blocks(text: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"^###\s+Video Name:\s*(.+?)\s*$", text, flags=re.M))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((match.group(1).strip(), text[start:end].strip()))
    return blocks


def numbered_sections(block: str) -> dict[str, str]:
    matches = list(re.finditer(r"^\*\*\d+\.\s+(.+?)\*\*\s*$", block, flags=re.M))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = norm(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        sections[name] = block[start:end].strip()
    return sections


def section(sections: dict[str, str], contains: str) -> str:
    needle = norm(contains)
    for name, body in sections.items():
        if needle in name:
            return body
    return ""


def extract_bullet_field(text: str, label_prefix: str) -> str:
    prefix = norm(label_prefix)
    for match in re.finditer(r"^\s*[*-]\s+\*\*(.+?):\*\*\s*(.+?)\s*$", text, flags=re.M):
        label = norm(match.group(1))
        if label.startswith(prefix):
            return match.group(2).strip()
    return ""


def extract_visual_variables(text: str) -> list[str]:
    variables: list[str] = []
    for match in re.finditer(r"^\s*[*-]\s+\*\*(.+?):\*\*", text, flags=re.M):
        label = match.group(1).strip()
        if label and label not in variables:
            variables.append(label)
    return variables


def extract_scene_rows(text: str, limit: int = 8) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("|") or "---" in line or "Timestamp" in line:
            continue
        cells = [cell.strip().strip("*") for cell in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        rows.append(
            {
                "timestamp": cells[0],
                "spoken_or_audio": cells[1],
                "visual": cells[2],
                "on_screen_text": cells[3],
            }
        )
        if len(rows) >= limit:
            break
    return rows


def classify_pattern(asset_name: str, framework: str, hook: str, transcript: str) -> str:
    text = norm(" ".join([asset_name, framework, hook, transcript]))
    checks: list[tuple[str, tuple[str, ...]]] = [
        ("psa-warning", ("psa", "warning", "be careful", "fake", "scam", "real vs", "loss aversion")),
        ("street-interview", ("street interview", "man on the street", "quick question", "successful", "what industry")),
        ("podcast-myth-bust", ("podcast", "myth-busting")),
        ("dialogue-skeptic", ("dialogue", "q&a", "skeptic", "objection", "interrogation", "is this just another", "what!?", "no dude")),
        ("listicle-signs", ("3 signs", "three signs", "signs your", "listicle", "number one")),
        ("timeline-reveal", ("timeline", "7-day", "day 1", "day one", "day 3", "week", "what happens")),
        ("authority-expert", ("authority", "expert", "dermatologist", "doctor", "veterinary", "vet", "patients", "licensed")),
        ("pov-skit", ("pov", "skit", "relatable", "friend and i", "after using")),
        ("comparison-contrast", ("us vs", "comparison", "old way", "new way", "competitor", "alternative")),
        ("demo-unboxing", ("unboxing", "opening", "watch me", "demonstration", "demo", "package")),
        ("problem-solution-rant", ("pas", "problem-agitate", "rant", "venting", "problem-solution")),
        ("process-reveal", ("proof of concept", "process reveal", "customer research doc", "screen recording", "behind-the-scenes")),
        ("internal-monologue", ("devil and angel", "internal monologue", "decision fatigue")),
        ("redemption-story", ("revenge", "redemption", "younger", "comeback")),
        ("whistleblower-personification", ("whistleblower", "personification", "big skincare", "buries me", "suppressed")),
        ("contrarian-reframe", ("pattern interrupt", "common truth", "traditional", "outdated", "not hard", "sounds like a total scam", "isn't hard", "reframes")),
    ]
    for pattern_id, needles in checks:
        if any(needle in text for needle in needles):
            return pattern_id
    return "generic-control"


def classify_hook(hook: str, transcript: str) -> str:
    text = norm(" ".join([hook, transcript[:300]]))
    checks: list[tuple[str, tuple[str, ...]]] = [
        ("negative-safety", ("be careful", "warning", "scam", "risk", "losing", "loss")),
        ("authority", ("research shows", "dermatologist", "doctor", "vet", "expert", "licensed")),
        ("curiosity-gap", ("how did", "what if", "secret", "curiosity", "impossible", "really", "wonder")),
        ("confrontation", ("stop", "i think you're", "banned", "not the end", "is this just")),
        ("listicle", ("3 signs", "three signs", "number one", "signs your")),
        ("pov", ("pov", "after using")),
        ("status-compliment", ("you look successful", "quick question")),
        ("timeline", ("7-day", "day 1", "in 135 hours", "in two days", "within")),
        ("visual-demo", ("watch me", "opening", "unboxing")),
    ]
    for hook_type, needles in checks:
        if any(needle in text for needle in needles):
            return hook_type
    return "direct-callout"


def control_from_block(source_file: Path, asset_name: str, block: str) -> Control:
    sections = numbered_sections(block)
    transcript = clean(section(sections, "raw transcript"))
    psychology = section(sections, "framework")
    framework = extract_bullet_field(psychology, "Identified Framework")
    hook = extract_bullet_field(psychology, "The Hook")
    cta = extract_bullet_field(psychology, "The CTA")
    viral = section(sections, "viral")
    visual = section(sections, "visual")
    pattern_id = classify_pattern(asset_name, framework, hook, transcript)
    metadata = PATTERN_METADATA[pattern_id]
    return Control(
        asset_name=asset_name,
        source_file=source_file.name,
        asset_type="UGC video analysis",
        performance_status="Pattern-only",
        raw_transcript=transcript,
        framework=framework,
        hook=hook,
        hook_type=classify_hook(hook, transcript),
        cta=cta,
        pattern_id=pattern_id,
        pattern_name=str(metadata["name"]),
        transferable_pattern=str(metadata["transferable"]),
        do_not_copy=str(metadata["do_not_copy"]),
        adaptation_rules=list(metadata["rules"]),
        visual_variables=extract_visual_variables(viral),
        scene_rows=extract_scene_rows(visual),
    )


def parse_batch(path: Path) -> list[Control]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return [control_from_block(path, name, block) for name, block in split_video_blocks(text)]


def parse_batches(paths: Iterable[Path]) -> list[Control]:
    controls: list[Control] = []
    for path in sorted(paths):
        controls.extend(parse_batch(path))
    return controls


def top_items(values: Iterable[str], limit: int = 6) -> list[str]:
    counter = Counter(value for value in values if value)
    return [value for value, _count in counter.most_common(limit)]


def aggregate_patterns(controls: list[Control]) -> list[dict[str, object]]:
    grouped: dict[str, list[Control]] = defaultdict(list)
    for control in controls:
        grouped[control.pattern_id].append(control)

    patterns: list[dict[str, object]] = []
    for pattern_id, items in grouped.items():
        metadata = PATTERN_METADATA[pattern_id]
        examples = [
            {
                "asset_name": item.asset_name,
                "source_file": item.source_file,
                "hook_type": item.hook_type,
                "framework": item.framework,
            }
            for item in items[:8]
        ]
        visual_variables: list[str] = []
        for item in items:
            visual_variables.extend(item.visual_variables)
        status_counts = dict(Counter(item.performance_status for item in items))
        performance_weight = round(
            sum(PERFORMANCE_WEIGHTS.get(item.performance_status, 0.25) for item in items),
            2,
        )
        if any(status in status_counts for status in ("Scaled control", "Control", "Winner")):
            evidence_quality = "performance-backed"
        else:
            evidence_quality = "pattern-only"
        patterns.append(
            {
                "pattern_id": pattern_id,
                "pattern_name": metadata["name"],
                "control_count": len(items),
                "performance_status_counts": status_counts,
                "performance_weight": performance_weight,
                "evidence_quality": evidence_quality,
                "best_for": metadata["best_for"],
                "transferable_pattern": metadata["transferable"],
                "do_not_copy": metadata["do_not_copy"],
                "adaptation_rules": metadata["rules"],
                "common_frameworks": top_items(item.framework for item in items),
                "common_hook_types": top_items(item.hook_type for item in items),
                "common_visual_variables": top_items(visual_variables),
                "examples": examples,
            }
        )
    return sorted(patterns, key=lambda pattern: (-int(pattern["control_count"]), str(pattern["pattern_id"])))


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def render_index(controls: list[Control], patterns: list[dict[str, object]]) -> str:
    lines = [
        "# Control Pattern Library",
        "",
        "Purpose: reusable direct-response patterns extracted from high-performing ad analyses. Use these as structural evidence, not wording to copy.",
        "",
        f"- Controls indexed: {len(controls)}",
        f"- Pattern families: {len(patterns)}",
        "",
        "## Non-Slop Rules",
        "",
        "1. Pick 1-3 patterns because they match the product's buyer pressure, awareness stage, mechanism, and proof stack.",
        "2. Adapt belief movement and visual grammar; never copy transcript wording, claims, jokes, or fake proof.",
        "3. If a pattern requires proof the product does not have, choose another pattern or mark the script as hypothesis-only.",
        "4. Use the target product's reviews, landing page, constraints, and VOC as the factual floor.",
        "",
        "## Pattern Families",
        "",
    ]
    for pattern in patterns:
        lines.extend(
            [
                f"### {pattern['pattern_name']} (`{pattern['pattern_id']}`)",
                "",
                f"- Controls: {pattern['control_count']}",
                f"- Evidence quality: {pattern['evidence_quality']}",
                f"- Performance weight: {pattern['performance_weight']}",
                f"- Best for: {pattern['best_for']}",
                f"- Transferable pattern: {pattern['transferable_pattern']}",
                f"- Do not copy: {pattern['do_not_copy']}",
                f"- Common hook types: {', '.join(pattern['common_hook_types']) or 'none detected'}",
                f"- Common visual variables: {', '.join(pattern['common_visual_variables']) or 'none detected'}",
                "- Adaptation rules:",
            ]
        )
        for rule in pattern["adaptation_rules"]:
            lines.append(f"  - {rule}")
        lines.append("- Example controls:")
        for example in pattern["examples"][:4]:
            lines.append(f"  - {example['asset_name']} ({Path(example['source_file']).name})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_library(input_dir: Path, output_dir: Path) -> tuple[list[Control], list[dict[str, object]]]:
    batch_paths = sorted(input_dir.glob("batch_*.md"))
    if not batch_paths:
        raise SystemExit(f"No batch_*.md files found in {input_dir}")

    controls = parse_batches(batch_paths)
    patterns = aggregate_patterns(controls)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "controls.json", [asdict(control) for control in controls])
    write_json(output_dir / "patterns.json", patterns)
    (output_dir / "index.md").write_text(render_index(controls, patterns), encoding="utf-8")
    return controls, patterns


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path, help="Directory containing batch_*.md analyses.")
    parser.add_argument(
        "--output-dir",
        default=Path("marketing-brain/references/control-library"),
        type=Path,
        help="Directory to write controls.json, patterns.json, and index.md.",
    )
    args = parser.parse_args()

    controls, patterns = build_library(args.input_dir, args.output_dir)
    print(f"Indexed {len(controls)} controls into {len(patterns)} pattern families.")
    print(f"Wrote {args.output_dir / 'controls.json'}")
    print(f"Wrote {args.output_dir / 'patterns.json'}")
    print(f"Wrote {args.output_dir / 'index.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
