#!/usr/bin/env python3
# Library v2, 2026-11-09 (reality-drama-engine)
"""Compare what a generated clip says with the approved script line(s).

Usage:
    python3 wordcheck.py "<exact approved line(s)>" <transcript.json | transcript.txt>
    python3 wordcheck.py --script-file lines.txt <transcript.json | transcript.txt>

The transcript can be:
  - plain text (.txt)
  - JSON with "text", or "words" (items with "word", "w" or "text"), or "segments" (items with "text")

Numbers are compared as words ("3" == "three"), case and punctuation are ignored.
Exit code 0 = the words match, 1 = differences found (printed), 2 = usage error.
Standard library only.
"""
import difflib
import json
import re
import sys
from pathlib import Path

ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
        "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def number_words(n):
    """English words for 0-9999 as a list (enough for spoken ad lines)."""
    if n < 20:
        return [ONES[n]]
    if n < 100:
        return [TENS[n // 10]] + ([ONES[n % 10]] if n % 10 else [])
    if n < 1000:
        rest = number_words(n % 100) if n % 100 else []
        return [ONES[n // 100], "hundred"] + rest
    rest = number_words(n % 1000) if n % 1000 else []
    return number_words(n // 1000) + ["thousand"] + rest


def tokens(text):
    out = []
    for raw in re.findall(r"[\w']+|%", text.lower()):
        raw = raw.strip("'")
        if not raw:
            continue
        if raw == "%":
            out.append("percent")
        elif raw.isdigit() and len(raw) <= 4:
            out.extend(number_words(int(raw)))
        else:
            out.append(raw.replace("'", ""))
    return out


def read_transcript(path):
    p = Path(path)
    if not p.exists():
        sys.exit(f"Transcript not found: {path}")
    raw = p.read_text(encoding="utf-8")
    if p.suffix.lower() != ".json":
        return raw
    data = json.loads(raw)
    if isinstance(data, dict) and data.get("result") and isinstance(data["result"], dict):
        data = data["result"]
    if isinstance(data, dict) and isinstance(data.get("text"), str) and data["text"].strip():
        return data["text"]
    items = None
    if isinstance(data, dict):
        items = data.get("words") or data.get("segments")
    elif isinstance(data, list):
        items = data
    if not items:
        sys.exit("No text, words or segments found in the transcript JSON.")
    parts = []
    for it in items:
        if isinstance(it, dict):
            parts.append(str(it.get("word") or it.get("w") or it.get("text") or ""))
        elif isinstance(it, (list, tuple)) and it:
            parts.append(str(it[-1]))
        else:
            parts.append(str(it))
    return " ".join(parts)


def main(argv):
    if len(argv) < 3 or argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if len(argv) > 1 and argv[1] in ("-h", "--help") else 2
    if argv[1] == "--script-file":
        if len(argv) < 4:
            print(__doc__.strip())
            return 2
        script, transcript_path = Path(argv[2]).read_text(encoding="utf-8"), argv[3]
    else:
        script, transcript_path = argv[1], argv[2]
    want, got = tokens(script), tokens(read_transcript(transcript_path))
    problems = []
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(a=want, b=got, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        script_part, clip_part = " ".join(want[a1:a2]) or "-", " ".join(got[b1:b2]) or "-"
        label = {"replace": "CHANGED", "delete": "MISSING", "insert": "ADDED"}[op]
        problems.append(f"{label:8} script: {script_part!r:40} clip: {clip_part!r}")
    print(f"Script words: {len(want)}   Clip words: {len(got)}")
    if not problems:
        print("MATCH: the clip says exactly the approved words.")
        return 0
    for line in problems:
        print(line)
    print(f"{len(problems)} difference(s). Regenerate this clip (or accept if the change is harmless).")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
