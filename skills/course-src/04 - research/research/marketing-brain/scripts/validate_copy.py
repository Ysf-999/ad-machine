#!/usr/bin/env python3
"""Validate Marketing Brain copy packs against deterministic specs.

Specs live in marketing-brain/specs/*.yml. They are stored as JSON-compatible
YAML so this script has no third-party dependency.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SPECS_DIR = ROOT / "specs"

UNRESTRICTED_MODE = False


@dataclass
class Finding:
    severity: str
    scope: str
    message: str


@dataclass
class Metrics:
    scope: str
    primary_words: int | None = None
    primary_sentences: int | None = None
    headline_chars: int | None = None
    image_prompt_words: int | None = None


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text))


def sentence_count(text: str) -> int:
    pieces = re.split(r"(?<=[.!?])\s+|\n{2,}", text.strip())
    return len([p for p in pieces if word_count(p) > 0])


def first_sentence(text: str) -> str:
    match = re.search(r"(.+?[.!?])(?:\s|$)", text.strip(), flags=re.S)
    if match:
        return match.group(1).strip()
    return text.strip().splitlines()[0].strip() if text.strip() else ""


def load_spec(name_or_path: str) -> dict[str, Any]:
    path = Path(name_or_path)
    if not path.exists():
        path = SPECS_DIR / f"{name_or_path}.yml"
    if not path.exists():
        raise SystemExit(f"Spec not found: {name_or_path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"Could not parse {path}. Specs must be JSON-compatible YAML. {exc}"
        ) from exc


def split_blocks(text: str, heading_regex: str) -> list[tuple[str, str, int]]:
    matches = list(re.finditer(heading_regex, text, flags=re.M))
    blocks: list[tuple[str, str, int]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        next_h2 = re.search(r"^##\s+", text[match.end() : end], flags=re.M)
        if next_h2:
            end = match.end() + next_h2.start()
        line = text.count("\n", 0, start) + 1
        heading = match.group(0).strip("# ").strip()
        blocks.append((heading, text[start:end].strip(), line))
    return blocks


def extract_sections(block: str) -> dict[str, str]:
    matches = list(re.finditer(r"^###\s+(.+?)\s*$", block, flags=re.M))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        sections[norm(name)] = block[start:end].strip()
    return sections


def extract_bold_fields(block: str) -> dict[str, str]:
    matches = list(re.finditer(r"^\*\*(.+?):\*\*\s*(.*?)\s*$", block, flags=re.M))
    fields: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1).strip()
        inline = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        next_heading = re.search(r"^#{1,3}\s+|^---\s*$", block[start:end], flags=re.M)
        if next_heading:
            end = start + next_heading.start()
        tail = block[start:end].strip()
        value = "\n".join(part for part in (inline, tail) if part).strip()
        fields[norm(name)] = value
    return fields


def section(sections: dict[str, str], name: str) -> str:
    return sections.get(norm(name), "")


def field(fields: dict[str, str], name: str) -> str:
    return fields.get(norm(name), "")


def extract_heading_body(text: str, heading: str) -> str:
    pattern = rf"^##+\s+{re.escape(heading)}\s*$"
    match = re.search(pattern, text, flags=re.I | re.M)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^##\s+", text[start:], flags=re.M)
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def validate_strategy_notes(
    text: str,
    spec: dict[str, Any],
    findings: list[Finding],
) -> None:
    rules = spec.get("strategy_notes") or {}
    if not rules:
        return
    heading = rules.get("heading", "Strategy Notes")
    body = extract_heading_body(text, heading)
    if not body:
        severity = "error" if rules.get("required") else "warning"
        findings.append(Finding(severity, "Document", f"Missing required section: ## {heading}."))
        return
    fields = extract_bold_fields(body)
    for required in rules.get("required_fields", []):
        if not field(fields, required) and norm(required) not in norm(body):
            findings.append(Finding("error", "Document", f"Strategy Notes missing required field: {required}."))
    reference_terms = rules.get("reference_terms_any", [])
    if reference_terms and not contains_any(body, reference_terms):
        findings.append(Finding("error", "Document", "Strategy Notes do not reference the required strategy/framework levers."))


def find_prompt_sections(text: str, names: list[str]) -> list[tuple[str, str, int]]:
    matches = list(re.finditer(r"^###\s+(.+?)\s*$", text, flags=re.M))
    wanted = {norm(name) for name in names}
    prompts: list[tuple[str, str, int]] = []
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        if norm(heading) not in wanted:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        next_heading = re.search(r"^#{1,3}\s+", text[start:end], flags=re.M)
        if next_heading:
            end = start + next_heading.start()
        line = text.count("\n", 0, match.start()) + 1
        prompts.append((heading, text[start:end].strip(), line))
    return prompts or [("Document", text.strip(), 1)]


def load_product_names(product_dir: Path | None) -> list[str]:
    if not product_dir:
        return []
    candidates: set[str] = set()
    candidates.add(product_dir.name.replace("-", " "))
    for filename in ("offer.md", "product-info.md"):
        path = product_dir / filename
        if not path.exists():
            continue
        body = path.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"Product name:\s*(.+)", body, flags=re.I):
            raw = match.group(1).strip()
            for piece in re.split(r"/|,|\(|\)|\||;", raw):
                piece = piece.strip()
                if len(piece) >= 3:
                    candidates.add(piece)
        for match in re.finditer(r"^#\s+(.+?)\s+Product Info\s*$", body, flags=re.I | re.M):
            candidates.add(match.group(1).strip())
    expanded: set[str] = set()
    for name in candidates:
        clean = re.sub(r"\s+", " ", name).strip()
        if clean:
            expanded.add(clean)
            words = clean.split()
            if len(words) > 2:
                expanded.add(" ".join(words[:2]))
    return sorted(expanded, key=len, reverse=True)


def load_claim_patterns(product_dir: Path | None) -> list[str]:
    if not product_dir:
        return []
    path = product_dir / "constraints.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    headings = list(re.finditer(r"^(?:#{1,3}\s*(.+?)\s*$|(.+?)\s*:\s*$)", text, flags=re.M))
    patterns: list[str] = []
    for index, heading in enumerate(headings):
        title = norm(heading.group(1) or heading.group(2) or "")
        if not re.search(r"avoid|forbidden|cannot|can't|claims we cannot", title):
            continue
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        body = text[start:end]
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith("-"):
                continue
            phrase = line.lstrip("-").strip()
            phrase = phrase.strip("`'\" ")
            phrase = re.sub(r"\s+unless\b.*$", "", phrase, flags=re.I).strip()
            phrase = re.sub(r"\s+as\s+a\s+guarantee\b.*$", "", phrase, flags=re.I).strip()
            if len(phrase) >= 4:
                patterns.extend(expand_claim_pattern(phrase))

    for match in re.finditer(r"^Forbidden words:\s*(.+?)\s*$", text, flags=re.I | re.M):
        raw_words = re.sub(r"\([^)]*\)", "", match.group(1))
        for piece in re.split(r",|;|\bor\b", raw_words, flags=re.I):
            cleaned = clean_claim_token(piece)
            if cleaned:
                patterns.append(cleaned)

    deduped: list[str] = []
    for pattern in patterns:
        if pattern and pattern not in deduped:
            deduped.append(pattern)
    return deduped


def clean_claim_token(value: str) -> str:
    cleaned = value.strip().strip("-*`'\" “”,.;:").casefold()
    cleaned = re.sub(r"[^a-z0-9 +/&-]", "", cleaned).strip()
    if not cleaned:
        return ""
    stems = {
        "cures": "cure",
        "cured": "cure",
        "curing": "cure",
        "treats": "treat",
        "treated": "treat",
        "treating": "treat",
        "prevents": "prevent",
        "prevented": "prevent",
        "preventing": "prevent",
        "diagnoses": "diagnose",
        "diagnosed": "diagnose",
        "diagnosing": "diagnose",
        "infections": "infection",
        "diseases": "disease",
    }
    return stems.get(cleaned, cleaned)


def expand_claim_pattern(phrase: str) -> list[str]:
    expanded: list[str] = []
    cleaned_phrase = phrase.strip().strip("`'\" ")
    if cleaned_phrase:
        expanded.append(cleaned_phrase)
    for quoted in re.findall(r"['\"]([^'\"]+)['\"]", phrase):
        token = clean_claim_token(quoted)
        if token:
            expanded.append(token)
    for token in re.findall(r"\b(cures?|curing|treats?|treated|treating|prevents?|prevented|preventing|diagnoses?|diagnosed|diagnosing|infections?|diseases?)\b", phrase, flags=re.I):
        cleaned = clean_claim_token(token)
        if cleaned:
            expanded.append(cleaned)
    return expanded


def extract_prices(text: str) -> set[str]:
    found = set()
    for match in re.finditer(r"\$\s?\d[\d,]*(?:\.\d{1,2})?", text):
        found.add(match.group(0).replace(" ", ""))
    return found


def product_packet_prices(product_dir: Path | None) -> set[str]:
    if not product_dir:
        return set()
    prices: set[str] = set()
    for path in product_dir.glob("*.md"):
        prices.update(extract_prices(path.read_text(encoding="utf-8", errors="ignore")))
    return prices


def add_length_checks(
    findings: list[Finding],
    scope: str,
    label: str,
    value: int,
    min_value: int | None = None,
    max_value: int | None = None,
) -> None:
    if UNRESTRICTED_MODE:
        return
    if min_value is not None and value < min_value:
        findings.append(Finding("error", scope, f"{label} is {value}; minimum is {min_value}."))
    if max_value is not None and value > max_value:
        findings.append(Finding("error", scope, f"{label} is {value}; maximum is {max_value}."))


def contains_any(text: str, phrases: list[str]) -> bool:
    lowered = norm(text)
    return any(norm(phrase) in lowered for phrase in phrases)


def claim_pattern_regex(pattern: str) -> str:
    cleaned = norm(pattern)
    if " " in cleaned or not re.fullmatch(r"[a-z0-9-]+", cleaned):
        return re.escape(cleaned)
    if cleaned.endswith("e"):
        stem = re.escape(cleaned[:-1])
        return rf"{re.escape(cleaned)}(?:s|d)?|{stem}ing"
    return rf"{re.escape(cleaned)}(?:s|ed|ing)?"


def scan_forbidden(
    text: str,
    scope: str,
    patterns: list[str],
    findings: list[Finding],
) -> None:
    if UNRESTRICTED_MODE:
        return
    lowered = norm(text)
    for pattern in patterns:
        cleaned = norm(pattern)
        if not cleaned:
            continue
        if " " in cleaned:
            found = lowered.find(cleaned)
            if found == -1:
                continue
        else:
            match = re.search(rf"\b(?:{claim_pattern_regex(cleaned)})\b", lowered)
            if not match:
                continue
            found = match.start()
        context = lowered[max(0, found - 120) : found]
        if re.search(r"\b(no|not|never|without|avoid|do not|does not|is not|not intended to)\b", context):
            findings.append(
                Finding(
                    "warning",
                    scope,
                    f"Forbidden/claim-sensitive term appears in a negated context: '{pattern}'. Review manually.",
                )
            )
        else:
            findings.append(Finding("error", scope, f"Forbidden/claim-sensitive phrase found: '{pattern}'."))


def validate_image_prompt(
    prompt: str,
    scope: str,
    rules: dict[str, Any],
    findings: list[Finding],
) -> int:
    words = word_count(prompt)
    if UNRESTRICTED_MODE:
        return words
    add_length_checks(
        findings,
        scope,
        "Image prompt word count",
        words,
        rules.get("min_words"),
        rules.get("max_words"),
    )
    if rules.get("anchor_any") and not contains_any(prompt, rules["anchor_any"]):
        findings.append(Finding("error", scope, "Image prompt is missing an approved iPhone/UGC realism anchor."))
    for phrase in rules.get("must_include", []):
        if norm(phrase) not in norm(prompt):
            findings.append(Finding("error", scope, f"Image prompt is missing required phrase: '{phrase}'."))
    for group in rules.get("must_include_any", []):
        if not contains_any(prompt, group):
            findings.append(
                Finding("error", scope, "Image prompt is missing one required phrase group: " + " OR ".join(group))
            )
    for phrase in rules.get("forbidden_visuals", []):
        lowered = norm(prompt)
        found = lowered.find(norm(phrase))
        if found == -1:
            continue
        context = lowered[max(0, found - 30) : found]
        if re.search(r"\b(no|not|never|without|avoid|do not|does not|is not)\b", context):
            continue
        if found >= 0:
            findings.append(Finding("error", scope, f"Forbidden visual instruction found: '{phrase}'."))
    return words


def validate_facebook_native(
    text: str,
    spec: dict[str, Any],
    product_dir: Path | None,
    extreme: bool,
) -> tuple[list[Finding], list[Metrics]]:
    findings: list[Finding] = []
    metrics: list[Metrics] = []
    blocks = split_blocks(text, spec["block_heading_regex"])
    if not blocks:
        return [Finding("error", "Document", "No ad blocks found.")], metrics

    product_names = load_product_names(product_dir)
    forbidden = list(spec.get("banned_patterns", [])) + load_claim_patterns(product_dir)

    for heading, block, line in blocks:
        scope = f"{heading} (line {line})"
        sections = extract_sections(block)
        for required in spec.get("required_sections", []):
            if not section(sections, required):
                findings.append(Finding("error", scope, f"Missing required section: {required}."))

        metric = Metrics(scope=scope)

        primary_rules = spec.get("primary_text", {})
        primary = section(sections, primary_rules.get("section", "Facebook Primary Text"))
        if primary:
            p_words = word_count(primary)
            p_sentences = sentence_count(primary)
            metric.primary_words = p_words
            metric.primary_sentences = p_sentences
            add_length_checks(findings, scope, "Primary text word count", p_words, primary_rules.get("min_words"), primary_rules.get("max_words"))
            add_length_checks(findings, scope, "Primary text sentence count", p_sentences, primary_rules.get("min_sentences"), primary_rules.get("max_sentences"))
            first_words = word_count(first_sentence(primary))
            max_first = primary_rules.get("first_sentence_max_words")
            if max_first and first_words > max_first:
                findings.append(Finding("warning", scope, f"First sentence has {first_words} words; hook may be too slow. Target <= {max_first}."))
            if primary_rules.get("require_product_mention"):
                if product_names and not contains_any(primary, product_names):
                    findings.append(Finding("error", scope, f"Primary text does not mention product/brand names: {', '.join(product_names[:5])}."))
                elif not product_names:
                    findings.append(Finding("warning", scope, "No product folder/name supplied, so product mention was not verified."))
            required_disclaimer = primary_rules.get("require_disclaimer_any", [])
            if required_disclaimer and not contains_any(primary, required_disclaimer):
                findings.append(Finding("error", scope, "Primary text is missing a required disclaimer/reminder phrase."))

        headline_rules = spec.get("headline", {})
        headline = section(sections, headline_rules.get("section", "Short Headline CTA"))
        if headline:
            headline_one_line = " ".join(headline.splitlines()).strip()
            chars = len(headline_one_line)
            metric.headline_chars = chars
            add_length_checks(findings, scope, "Headline CTA character count", chars, headline_rules.get("min_chars"), headline_rules.get("max_chars"))
            action_words = headline_rules.get("action_words_any", [])
            if action_words and not re.search(r"\b(" + "|".join(map(re.escape, action_words)) + r")\b", norm(headline_one_line)):
                findings.append(Finding("warning", scope, "Headline CTA may be missing a clear action verb."))

        image_rules = spec.get("image_prompt", {})
        image_prompt = section(sections, image_rules.get("section", "Native Image Prompt"))
        if image_prompt:
            metric.image_prompt_words = validate_image_prompt(image_prompt, scope, image_rules, findings)

        scan_forbidden(block, scope, forbidden, findings)
        metrics.append(metric)

    findings.extend(validate_prices(text, product_dir, spec))
    findings.extend(validate_extreme(text, spec, extreme))
    return findings, metrics


def extract_visible_hook(primary: str) -> str | None:
    match = re.search(r"\|\|(.+?)\|\|", primary, flags=re.S)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def visible_hook_segments(hook: str) -> int:
    parts = re.split(r"\s+\|\s+|(?<=[.!?:])\s+", hook)
    return len([part for part in parts if word_count(part) > 0])


def proof_categories_present(text: str, proof_rules: dict[str, Any]) -> list[str]:
    lowered = norm(text)
    present: list[str] = []
    for category, phrases in proof_rules.get("categories", {}).items():
        found = False
        if category == "number" and re.search(r"(\d+|%|\$)", text):
            found = True
        if not found:
            found = contains_any(lowered, phrases)
        if found:
            present.append(category)
    return present


def normalize_ad_format(value: str) -> str:
    return value.strip().strip("[]").casefold().replace("-", "_").replace(" ", "_")


def count_carousel_cards(value: str) -> int:
    explicit = re.findall(r"\bcard\s+\d+\b", value, flags=re.I)
    if explicit:
        return len(set(match.casefold() for match in explicit))
    bullets = [line for line in value.splitlines() if line.strip().startswith(("-", "*", "1.", "2.", "3.", "4.", "5."))]
    return len(bullets)


def validate_facebook_ad_copy(
    text: str,
    spec: dict[str, Any],
    product_dir: Path | None,
    extreme: bool,
) -> tuple[list[Finding], list[Metrics]]:
    findings: list[Finding] = []
    metrics: list[Metrics] = []
    top_fields = extract_bold_fields(text)
    for required in spec.get("required_top_fields", []):
        if not field(top_fields, required):
            findings.append(Finding("error", "Document", f"Missing required top field: {required}."))

    ad_format = normalize_ad_format(field(top_fields, "Format"))
    allowed_formats = spec.get("allowed_formats", [])
    if ad_format and ad_format not in allowed_formats:
        findings.append(Finding("error", "Document", f"Unknown Format '{field(top_fields, 'Format')}'. Allowed: {', '.join(allowed_formats)}."))

    if spec.get("require_testing_recommendation") and "## Testing Recommendation" not in text:
        findings.append(Finding("error", "Document", "Missing required section: ## Testing Recommendation."))
    validate_strategy_notes(text, spec, findings)

    blocks = split_blocks(text, spec["variation_heading_regex"])
    expected = spec.get("expected_variations")
    if expected and len(blocks) != expected:
        findings.append(Finding("error", "Document", f"Expected {expected} variations; found {len(blocks)}."))
    if not blocks:
        return findings + [Finding("error", "Document", "No variation blocks found.")], metrics

    hook_types: list[str] = []
    product_names = load_product_names(product_dir)
    forbidden = list(spec.get("banned_patterns", [])) + load_claim_patterns(product_dir)

    for heading, block, line in blocks:
        scope = f"{heading} (line {line})"
        fields = extract_bold_fields(block)
        hook_type = heading.split(":", 1)[1].strip() if ":" in heading else heading
        hook_types.append(norm(hook_type))

        for required in spec.get("required_variation_fields", []):
            if not field(fields, required):
                findings.append(Finding("error", scope, f"Missing required field: {required}."))

        metric = Metrics(scope=scope)
        primary = field(fields, "Primary Text")
        if primary:
            primary_clean = primary.replace("||", "")
            p_words = word_count(primary_clean)
            p_chars = len(primary_clean)
            p_sentences = sentence_count(primary_clean)
            metric.primary_words = p_words
            metric.primary_sentences = p_sentences
            primary_rules = spec.get("primary_text", {})
            add_length_checks(findings, scope, "Primary text word count", p_words, primary_rules.get("min_words"), None)
            add_length_checks(findings, scope, "Primary text character count", p_chars, None, primary_rules.get("max_chars"))

            visible = extract_visible_hook(primary)
            if primary_rules.get("require_visible_hook_markers") and not visible:
                findings.append(Finding("error", scope, "Primary Text must mark the first visible hook with ||...||."))
            if visible:
                add_length_checks(
                    findings,
                    scope,
                    "Visible hook character count",
                    len(visible),
                    primary_rules.get("visible_hook_min_chars"),
                    primary_rules.get("visible_hook_max_chars"),
                )
                segments = visible_hook_segments(visible)
                min_segments = primary_rules.get("visible_hook_min_segments", 1)
                if segments < min_segments:
                    findings.append(Finding("error", scope, f"Visible hook has {segments} segment(s); minimum is {min_segments}."))

            if primary_rules.get("require_product_mention"):
                if product_names and not contains_any(primary_clean, product_names):
                    findings.append(Finding("error", scope, f"Primary Text does not mention product/brand names: {', '.join(product_names[:5])}."))
                elif not product_names:
                    findings.append(Finding("warning", scope, "No product folder/name supplied, so product mention was not verified."))

            mechanism_terms = primary_rules.get("mechanism_terms_any", [])
            if mechanism_terms and not contains_any(primary_clean, mechanism_terms):
                findings.append(Finding("error", scope, "Primary Text is missing a mechanism/reason-why cue."))

            journey_terms = primary_rules.get("audience_journey_terms_any", [])
            if journey_terms and not contains_any(primary_clean, journey_terms):
                findings.append(Finding("warning", scope, "Primary Text may be missing the audience journey: what they tried, believe, or currently experience."))

            objection_terms = primary_rules.get("objection_terms_any", [])
            objection_hits = sum(1 for term in objection_terms if contains_any(primary_clean, [term]))
            if objection_terms and objection_hits < 2:
                findings.append(Finding("warning", scope, "Primary Text may not handle at least 2 objections or inhibitions."))

            proof = proof_categories_present(primary_clean, spec.get("proof", {}))
            min_categories = spec.get("proof", {}).get("min_categories", 0)
            if len(proof) < min_categories:
                findings.append(Finding("error", scope, f"Primary Text has {len(proof)} proof type(s); minimum is {min_categories}."))

        headline = field(fields, "Headline")
        if headline:
            headline_one_line = " ".join(headline.splitlines()).strip()
            chars = len(headline_one_line)
            metric.headline_chars = chars
            add_length_checks(findings, scope, "Headline character count", chars, 1, spec.get("headline", {}).get("max_chars"))

        description = field(fields, "Description")
        if description:
            description_chars = len(" ".join(description.splitlines()).strip())
            add_length_checks(findings, scope, "Description character count", description_chars, 1, spec.get("description", {}).get("max_chars"))

        cta = field(fields, "CTA Button")
        if cta:
            allowed_ctas = spec.get("cta_buttons", [])
            if norm(cta) not in {norm(option) for option in allowed_ctas}:
                findings.append(Finding("error", scope, f"CTA Button '{cta}' is not a supported Meta CTA option."))

        if ad_format:
            format_rules = spec.get("format_specific", {}).get(ad_format, {})
            for required in format_rules.get("required_fields", []):
                if not field(fields, required):
                    findings.append(Finding("error", scope, f"Format `{ad_format}` requires field: {required}."))
            if ad_format == "carousel" and field(fields, "Carousel Cards"):
                card_count = count_carousel_cards(field(fields, "Carousel Cards"))
                add_length_checks(findings, scope, "Carousel card count", card_count, format_rules.get("min_cards"), format_rules.get("max_cards"))
            if ad_format == "video" and field(fields, "Video Script"):
                script = norm(field(fields, "Video Script"))
                for timecode in format_rules.get("required_timecodes", []):
                    if norm(timecode) not in script:
                        findings.append(Finding("error", scope, f"Video Script is missing timecode: {timecode}."))

        scan_forbidden(block, scope, forbidden, findings)
        metrics.append(metric)

    if len(hook_types) != len(set(hook_types)):
        findings.append(Finding("error", "Document", "Variation hook types must be unique."))

    findings.extend(validate_prices(text, product_dir, spec))
    findings.extend(validate_extreme(text, spec, extreme))
    return findings, metrics


def validate_image_prompts(text: str, spec: dict[str, Any]) -> tuple[list[Finding], list[Metrics]]:
    findings: list[Finding] = []
    metrics: list[Metrics] = []
    prompts = find_prompt_sections(text, spec.get("prompt_section_names", ["Prompt"]))
    for heading, prompt, line in prompts:
        scope = f"{heading} (line {line})"
        words = validate_image_prompt(prompt, scope, spec, findings)
        metrics.append(Metrics(scope=scope, image_prompt_words=words))
    return findings, metrics


def validate_long_form(
    text: str,
    spec: dict[str, Any],
    product_dir: Path | None,
    extreme: bool,
) -> tuple[list[Finding], list[Metrics]]:
    findings: list[Finding] = []
    metrics: list[Metrics] = []
    blocks = split_blocks(text, spec["block_heading_regex"]) or [("Document", text, 1)]
    forbidden = list(spec.get("banned_patterns", [])) + load_claim_patterns(product_dir)
    for heading, block, line in blocks:
        scope = f"{heading} (line {line})"
        sections = extract_sections(block)
        for required in spec.get("required_sections", []):
            if not section(sections, required):
                findings.append(Finding("error", scope, f"Missing required section: {required}."))
        body_rules = spec.get("body_copy", {})
        body = section(sections, body_rules.get("section", "Body Copy"))
        if body:
            words = word_count(body)
            add_length_checks(findings, scope, "Body copy word count", words, body_rules.get("min_words"), body_rules.get("max_words"))
            metrics.append(Metrics(scope=scope, primary_words=words))
        hook_rules = spec.get("headline", {})
        hook = section(sections, hook_rules.get("section", "Primary Hook"))
        if hook:
            chars = len(" ".join(hook.splitlines()).strip())
            add_length_checks(findings, scope, "Primary hook character count", chars, hook_rules.get("min_chars"), hook_rules.get("max_chars"))
        scan_forbidden(block, scope, forbidden, findings)
    findings.extend(validate_prices(text, product_dir, spec))
    findings.extend(validate_extreme(text, spec, extreme))
    return findings, metrics


def parse_table_rows(table_block: str) -> list[list[str]]:
    """Parse a markdown table into rows of trimmed cell strings, skipping the separator row."""
    rows: list[list[str]] = []
    for raw in table_block.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        if re.match(r"^\|\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)
    return rows


def extract_subsection_body(text: str, heading: str) -> str:
    """Find a level-3 heading and return body until next level-3 or higher heading."""
    pattern = rf"^###\s+{re.escape(heading)}\s*$"
    match = re.search(pattern, text, flags=re.I | re.M)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^#{1,3}\s+", text[start:], flags=re.M)
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def normalize_value(value: str) -> str:
    return (
        value.strip()
        .strip("[]")
        .strip("`'\"")
        .casefold()
        .replace("+", " ")
        .replace("/", " ")
        .replace("-", "_")
        .replace(" ", "_")
    )


def script_beat_jobs(label: str, text: str = "") -> set[str]:
    combined = norm(" ".join([label, text]))
    jobs: set[str] = set()
    checks = {
        "Hook": ("hook",),
        "Pain": ("pain", "problem", "villain", "failed alternative"),
        "Mechanism": ("mechanism", "process", "product bridge", "bridge", "reveal"),
        "Proof": ("proof", "review", "testimonial", "authority", "demo", "demonstration"),
        "Objection": ("objection", "inhibition", "pushback", "risk reversal", "proof + objection"),
        "CTA": ("cta", "offer", "close", "call to action"),
    }
    for job, needles in checks.items():
        if any(needle in combined for needle in needles):
            jobs.add(job)
    return jobs


def validate_ugc_video_script(
    text: str,
    spec: dict[str, Any],
    product_dir: Path | None,
    extreme: bool,
) -> tuple[list[Finding], list[Metrics]]:
    findings: list[Finding] = []
    metrics: list[Metrics] = []

    top_fields = extract_bold_fields(text)
    for required in spec.get("required_top_fields", []):
        if not field(top_fields, required):
            findings.append(Finding("error", "Document", f"Missing required top field: {required}."))

    fmt = normalize_value(field(top_fields, "Format"))
    if fmt and fmt not in spec.get("allowed_formats", []):
        findings.append(Finding("error", "Document", f"Format '{field(top_fields, 'Format')}' is not in allowed list."))

    delivery_mode_raw = field(top_fields, "Delivery Mode")
    delivery_mode = normalize_value(delivery_mode_raw)
    if delivery_mode and delivery_mode not in spec.get("allowed_delivery_modes", []):
        findings.append(Finding("error", "Document", f"Delivery Mode '{delivery_mode_raw}' is not in allowed list."))

    platform = normalize_value(field(top_fields, "Platform"))
    if platform and platform not in spec.get("allowed_platforms", []):
        findings.append(Finding("error", "Document", f"Platform '{field(top_fields, 'Platform')}' is not in allowed list."))

    length_raw = field(top_fields, "Target Length")
    length_match = re.search(r"\b(15s|30s|60s|90s|180s)\b", length_raw)
    target_length = length_match.group(1) if length_match else normalize_value(length_raw)
    if target_length and target_length not in spec.get("allowed_lengths", []):
        findings.append(Finding("error", "Document", f"Target Length '{length_raw}' is not in allowed list."))

    for required in spec.get("required_sections", []):
        if not extract_subsection_body(text, required):
            findings.append(Finding("error", "Document", f"Missing required section: ### {required}."))

    hook_rules = spec.get("hook_options", {})
    hook_block = extract_subsection_body(text, "Hook Options")
    if hook_block:
        hook_lines = [line for line in hook_block.splitlines() if re.match(r"^\s*\d+\.\s+", line)]
        expected = hook_rules.get("expected_count", 3)
        if len(hook_lines) != expected:
            findings.append(Finding("error", "Hook Options", f"Expected {expected} hook options; found {len(hook_lines)}."))
        if hook_rules.get("require_source_tag"):
            for index, line in enumerate(hook_lines, start=1):
                if not re.search(r"\[source:\s*[^\]]+\]", line, flags=re.I):
                    findings.append(Finding("error", "Hook Options", f"Hook #{index} is missing a [source: ...] tag."))

    script_rules = spec.get("script", {})
    script_block = extract_subsection_body(text, "Script")
    spoken_words_computed = 0
    if script_block:
        rows = parse_table_rows(script_block)
        if len(rows) < 2:
            findings.append(Finding("error", "Script", "Script table is empty or malformed."))
        else:
            header = [c.casefold() for c in rows[0]]
            data_rows = rows[1:]
            beat_jobs_present: set[str] = set()
            for row in data_rows:
                if not row or not row[0].strip():
                    continue
                row_text = " ".join(row[1:])
                beat_jobs_present.update(script_beat_jobs(row[0], row_text))
            for beat in script_rules.get("expected_beats", []):
                if beat not in beat_jobs_present:
                    findings.append(Finding("error", "Script", f"Script table is missing beat: {beat}."))

            line_col = next(
                (i for i, h in enumerate(header) if "direction" in h or "line" in h),
                2 if len(header) > 2 else None,
            )
            source_col = next((i for i, h in enumerate(header) if "source" in h), None)
            require_source = script_rules.get("require_source_column", False)
            if require_source and source_col is None:
                findings.append(Finding("error", "Script", "Script table is missing a Source column."))

            for row in data_rows:
                if not row or not row[0].strip():
                    continue
                beat_label = row[0].strip()
                if line_col is not None and line_col < len(row):
                    spoken_words_computed += word_count(row[line_col])
                if require_source and source_col is not None and source_col < len(row):
                    if not row[source_col].strip():
                        findings.append(Finding("error", "Script", f"Beat '{beat_label}' is missing a Source value."))

    budget = (spec.get("spoken_word_budget") or {}).get(target_length, {})
    if budget and delivery_mode in {"full_script", "ai_talking_head"}:
        word_block = extract_subsection_body(text, "Spoken Word Count")
        claimed_total: int | None = None
        if word_block:
            for row in parse_table_rows(word_block):
                if row and "total" in row[0].casefold():
                    nums = [int(c) for c in row[1:] if re.fullmatch(r"\d+", c.strip())]
                    if nums:
                        claimed_total = nums[-1]
                        break
        total = claimed_total if claimed_total is not None else spoken_words_computed
        hard_cap = budget.get("hard_cap")
        target_min = budget.get("target_min")
        target_max = budget.get("target_max")
        metrics.append(Metrics(scope=f"Spoken Words ({target_length}, {delivery_mode})", primary_words=total))
        if hard_cap and total > hard_cap and not UNRESTRICTED_MODE:
            findings.append(Finding("error", "Spoken Word Count", f"Total spoken words is {total}; hard cap for {target_length} is {hard_cap}. Cut adjectives, redundant proof, or a beat — never raise the cap."))
        elif target_max and total > target_max:
            findings.append(Finding("warning", "Spoken Word Count", f"Total spoken words is {total}; target window for {target_length} is {target_min}-{target_max}."))
        elif target_min and total > 0 and total < target_min:
            findings.append(Finding("warning", "Spoken Word Count", f"Total spoken words is {total}; target window for {target_length} is {target_min}-{target_max}. Likely under-using available time."))
        if claimed_total is not None and spoken_words_computed > 0 and claimed_total > 0:
            diff_ratio = abs(claimed_total - spoken_words_computed) / claimed_total
            if diff_ratio > 0.15:
                findings.append(Finding("warning", "Spoken Word Count", f"Claimed total ({claimed_total}) and computed total from Script table ({spoken_words_computed}) disagree by more than 15%. Recount."))

    validate_strategy_notes(text, spec, findings)

    if spec.get("require_testing_recommendation") and "## Testing Recommendation" not in text:
        findings.append(Finding("error", "Document", "Missing required section: ## Testing Recommendation."))

    forbidden = list(spec.get("banned_patterns", [])) + load_claim_patterns(product_dir)
    scan_forbidden(text, "Document", forbidden, findings)

    findings.extend(validate_prices(text, product_dir, spec))
    findings.extend(validate_extreme(text, spec, extreme))
    return findings, metrics


def validate_claims(
    text: str,
    spec: dict[str, Any],
    product_dir: Path | None,
    extreme: bool,
) -> tuple[list[Finding], list[Metrics]]:
    findings: list[Finding] = []
    forbidden = list(spec.get("banned_patterns", [])) + load_claim_patterns(product_dir)
    scan_forbidden(text, "Document", forbidden, findings)
    if spec.get("require_product_mention"):
        product_names = load_product_names(product_dir)
        if product_names and not contains_any(text, product_names):
            findings.append(Finding("error", "Document", f"Copy does not mention product/brand names: {', '.join(product_names[:5])}."))
        elif not product_names:
            findings.append(Finding("warning", "Document", "No product folder/name supplied, so product mention was not verified."))
    findings.extend(validate_prices(text, product_dir, spec))
    findings.extend(validate_extreme(text, spec, extreme))
    return findings, []


def validate_prices(text: str, product_dir: Path | None, spec: dict[str, Any]) -> list[Finding]:
    if UNRESTRICTED_MODE:
        return []
    findings: list[Finding] = []
    ad_prices = extract_prices(text)
    if not ad_prices:
        return findings
    packet_prices = product_packet_prices(product_dir)
    if not packet_prices:
        findings.append(Finding("warning", "Document", f"Prices found {sorted(ad_prices)}, but no product packet prices were available to compare."))
        return findings
    unexpected = sorted(ad_prices - packet_prices)
    if unexpected:
        severity = spec.get("price_mismatch_severity", "warning")
        findings.append(Finding(severity, "Document", f"Price(s) not found in product packet: {', '.join(unexpected)}. Packet prices: {', '.join(sorted(packet_prices))}."))
    return findings


def validate_extreme(text: str, spec: dict[str, Any], extreme: bool) -> list[Finding]:
    if UNRESTRICTED_MODE or not extreme:
        return []
    rules = spec.get("extreme") or {}
    required = rules.get("required_phrases", ["Mode: --extreme", "User confirmed final review responsibility"])
    findings: list[Finding] = []
    for phrase in required:
        if phrase not in text:
            findings.append(Finding("error", "Document", f"--extreme output is missing required mode label phrase: {phrase}."))
    return findings


def render_report(
    spec_name: str,
    file_path: Path,
    findings: list[Finding],
    metrics: list[Metrics],
) -> str:
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    status = "FAIL" if errors else "PASS"
    lines = [
        "# Validation Report",
        "",
        f"- Spec: `{spec_name}`",
        f"- File: `{file_path}`",
        f"- Status: **{status}**",
        f"- Errors: `{len(errors)}`",
        f"- Warnings: `{len(warnings)}`",
        "",
    ]
    if errors:
        lines.extend(["## Errors", ""])
        lines.extend(f"- **{f.scope}**: {f.message}" for f in errors)
        lines.append("")
    if warnings:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- **{f.scope}**: {f.message}" for f in warnings)
        lines.append("")
    if metrics:
        lines.extend(
            [
                "## Metrics",
                "",
                "| Scope | Primary Words | Sentences | Headline Chars | Prompt Words |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for m in metrics:
            lines.append(
                "| "
                + " | ".join(
                    [
                        m.scope.replace("|", "\\|"),
                        "" if m.primary_words is None else str(m.primary_words),
                        "" if m.primary_sentences is None else str(m.primary_sentences),
                        "" if m.headline_chars is None else str(m.headline_chars),
                        "" if m.image_prompt_words is None else str(m.image_prompt_words),
                    ]
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Marketing Brain copy against specs.")
    parser.add_argument("--spec", required=True, help="Spec name from marketing-brain/specs or a path to a JSON-compatible .yml file.")
    parser.add_argument("--file", required=True, type=Path, help="Markdown file to validate.")
    parser.add_argument("--product-dir", type=Path, help="Optional product packet folder for claims, names, and prices.")
    parser.add_argument("--report", type=Path, help="Optional Markdown report output path.")
    parser.add_argument("--extreme", action="store_true", help="Require --extreme mode labeling.")
    parser.add_argument("--unrestricted", action="store_true", help="Bypass constraints, measures, and claim safety checks.")
    parser.add_argument("--quiet", action="store_true", help="Only print PASS/FAIL summary.")
    args = parser.parse_args()

    global UNRESTRICTED_MODE
    UNRESTRICTED_MODE = args.unrestricted

    spec = load_spec(args.spec)
    text = args.file.read_text(encoding="utf-8", errors="ignore")
    spec_name = spec.get("name", args.spec)

    if spec_name == "facebook-native-ad":
        findings, metrics = validate_facebook_native(text, spec, args.product_dir, args.extreme)
    elif spec_name == "facebook-ad-copy":
        findings, metrics = validate_facebook_ad_copy(text, spec, args.product_dir, args.extreme)
    elif spec_name == "image-prompt":
        findings, metrics = validate_image_prompts(text, spec)
    elif spec_name == "long-form-static":
        findings, metrics = validate_long_form(text, spec, args.product_dir, args.extreme)
    elif spec_name == "ugc-video-script":
        findings, metrics = validate_ugc_video_script(text, spec, args.product_dir, args.extreme)
    elif spec_name == "product-claims":
        findings, metrics = validate_claims(text, spec, args.product_dir, args.extreme)
    else:
        raise SystemExit(f"Unknown spec type: {spec_name}")

    report = render_report(spec_name, args.file, findings, metrics)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report + "\n", encoding="utf-8")

    if args.quiet:
        errors = len([f for f in findings if f.severity == "error"])
        warnings = len([f for f in findings if f.severity == "warning"])
        print(f"{'FAIL' if errors else 'PASS'}: {errors} error(s), {warnings} warning(s)")
    else:
        print(report)

    return 1 if any(f.severity == "error" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
