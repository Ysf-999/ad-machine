#!/usr/bin/env python3
"""Maintain the product-level creative ledger.

The ledger is the bridge between strategy, generated assets, validation,
scoring, and spend feedback. Each row is one tested or queued creative, with
the hypothesis and variable under test kept next to the launch metrics.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


LEDGER_FILENAME = "creative-ledger.csv"

LEDGER_FIELDS = [
    "creative_id",
    "concept",
    "asset_file",
    "format",
    "platform",
    "traffic_temperature",
    "archetype",
    "awareness_stage",
    "hypothesis",
    "variable_tested",
    "belief_shift",
    "mechanism",
    "proof_used",
    "control_patterns",
    "destination_url",
    "validation_spec",
    "validation_status",
    "validation_report",
    "score",
    "score_report",
    "launch_date",
    "spend",
    "impressions",
    "cpm",
    "thumbstop_rate",
    "hold_rate",
    "outbound_ctr",
    "cpc",
    "lpv_rate",
    "quiz_start_rate",
    "quiz_complete_rate",
    "checkout_view_rate",
    "purchase_cpa",
    "roas",
    "aov",
    "comment_sentiment",
    "failure_mode",
    "decision",
    "next_action",
    "notes",
]


def ledger_path(product_dir: Path) -> Path:
    return product_dir / LEDGER_FILENAME


def init_ledger(product_dir: Path) -> Path:
    product_dir.mkdir(parents=True, exist_ok=True)
    path = ledger_path(product_dir)
    if not path.exists():
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS)
            writer.writeheader()
    return path


def append_row(product_dir: Path, row: dict[str, object]) -> Path:
    path = init_ledger(product_dir)
    normalized = {field: str(row.get(field, "")).strip() for field in LEDGER_FIELDS}
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS)
        writer.writerow(normalized)
    return path


def key_value_pairs(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Expected key=value, got: {value}")
        key, raw = value.split("=", 1)
        key = key.strip()
        if key not in LEDGER_FIELDS:
            raise SystemExit(f"Unknown ledger field: {key}")
        parsed[key] = raw.strip()
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or append to a Marketing Brain creative ledger.")
    parser.add_argument("--product-dir", required=True, type=Path)
    parser.add_argument("--init", action="store_true", help="Create the ledger if missing.")
    parser.add_argument("--set", action="append", default=[], help="Append a row value as key=value. Can be repeated.")
    args = parser.parse_args()

    if args.set:
        path = append_row(args.product_dir, key_value_pairs(args.set))
        print(f"Appended row to {path}")
    else:
        path = init_ledger(args.product_dir)
        print(f"Ledger ready at {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
