#!/usr/bin/env python3
"""Diagnose creative performance from a Marketing Brain creative ledger."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def as_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace("%", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if "%" in str(value):
        return number / 100
    return number


def classify_row(row: dict[str, object]) -> dict[str, str]:
    spend = as_float(row.get("spend"))
    impressions = as_float(row.get("impressions"))
    ctr = as_float(row.get("outbound_ctr"))
    cpm = as_float(row.get("cpm"))
    lpv = as_float(row.get("lpv_rate"))
    quiz_start = as_float(row.get("quiz_start_rate"))
    quiz_complete = as_float(row.get("quiz_complete_rate"))
    checkout = as_float(row.get("checkout_view_rate"))
    cpa = as_float(row.get("purchase_cpa"))
    thumbstop = as_float(row.get("thumbstop_rate"))

    if (spend is not None and 0 < spend < 20) or (impressions is not None and 0 < impressions < 1000):
        return {
            "failure_mode": "insufficient_signal",
            "decision": "collect_more_data",
            "next_action": "Do not kill or scale yet; get enough spend/impressions for a reliable read.",
        }
    if thumbstop is not None and thumbstop < 0.18:
        return {
            "failure_mode": "first_frame_failure",
            "decision": "rebuild_visual",
            "next_action": "Make 10 new first frames before changing the angle.",
        }
    if ctr is not None and ctr < 0.006 and (cpm is None or cpm < 45):
        return {
            "failure_mode": "hook_or_visual_failure",
            "decision": "kill_or_rebuild",
            "next_action": "Rebuild first frame, hook, or visual pressure before making body-copy variants.",
        }
    if ctr is not None and ctr >= 0.012 and (quiz_start is not None and quiz_start < 0.12):
        return {
            "failure_mode": "promise_page_mismatch",
            "decision": "revise_bridge",
            "next_action": "Revise bridge or destination: align ad promise with LP/quiz expectation.",
        }
    if lpv is not None and lpv < 0.55:
        return {
            "failure_mode": "click_quality_or_page_load",
            "decision": "audit_destination",
            "next_action": "Check placement quality, load speed, and click-to-LPV tracking before judging creative.",
        }
    if quiz_start is not None and quiz_start >= 0.25 and quiz_complete is not None and quiz_complete < 0.15:
        return {
            "failure_mode": "quiz_friction",
            "decision": "fix_funnel",
            "next_action": "Fix quiz friction, question order, or trust copy before writing more ads.",
        }
    if checkout is not None and checkout >= 0.12 and (cpa is None or cpa >= 250):
        return {
            "failure_mode": "checkout_offer_trust_or_economics",
            "decision": "fix_offer_or_economics",
            "next_action": "Inspect price, guarantee, approval path, payout, refund risk, and checkout trust.",
        }
    if cpa is not None and cpa > 0 and cpa < 150:
        return {
            "failure_mode": "none_detected",
            "decision": "scale_or_mutate",
            "next_action": "Preserve belief shift and mutate one variable at a time.",
        }
    return {
        "failure_mode": "insufficient_signal",
        "decision": "collect_more_data",
        "next_action": "Wait for meaningful spend or add missing funnel metrics.",
    }


def analyze_ledger(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    analyzed: list[dict[str, str]] = []
    for row in rows:
        diagnosis = classify_row(row)
        analyzed.append({**{key: str(value or "") for key, value in row.items()}, **diagnosis})
    return analyzed


def render_feedback(rows: list[dict[str, str]], ledger: Path) -> str:
    lines = [
        "# Performance Feedback",
        "",
        f"- Ledger: `{ledger}`",
        f"- Creatives analyzed: `{len(rows)}`",
        "",
        "| Creative ID | Concept | Failure Mode | Decision | Next Action |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.get("creative_id", "").replace("|", "\\|"),
                    row.get("concept", "").replace("|", "\\|"),
                    row.get("failure_mode", "").replace("|", "\\|"),
                    row.get("decision", "").replace("|", "\\|"),
                    row.get("next_action", "").replace("|", "\\|"),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze Marketing Brain creative-ledger performance.")
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    report = render_feedback(analyze_ledger(args.ledger), args.ledger)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report + "\n", encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
