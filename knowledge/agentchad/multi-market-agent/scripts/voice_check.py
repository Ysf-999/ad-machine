#!/usr/bin/env python3
# Library v2, 2026-11-09 (chad-copy). Standard library only.
"""Score an ad script against the chad-copy voice targets.

Usage:
    python3 voice_check.py SCRIPT.txt [--seconds 30] [--lang en] [--wps 2.5] [--strict]

SCRIPT.txt  plain text or one cut copied from a brief. Lines starting with "VO:" are read as speech;
            lines starting with "ON SCREEN:", "#", "|" or "---" are skipped.
--seconds   target length of the cut. The estimate must land within 2 s of it.
--lang      en (all checks) or any other code (length, sentence mix and banned connectors only).
--wps       spoken words per second (default 2.5 for English; try 2.2 for German or French, 2.3 for Swedish,
            Norwegian or Danish).
--strict    exit with code 1 when any check says FIX (useful in a batch).

Prints one PASS / FIX / INFO line per check. Nothing is sent anywhere.
"""
import argparse
import re
import sys
from pathlib import Path

CONJUNCTIONS = {"and", "but", "so", "now", "or", "because", "still", "plus", "then", "yet"}
BANNED_CONNECTORS = ["furthermore", "additionally", "moreover", "consequently", "however,", "in conclusion"]
BANNED_WORDS = ["delve", "elevate", "unlock", "empower", "journey", "game-changer", "game changer", "revolutionary",
                "seamless", "leverage", "transform your", "say goodbye to", "look no further", "in today's world"]
UNCONTRACTED = ["do not", "does not", "did not", "is not", "are not", "was not", "were not", "can not", "cannot",
                "will not", "would not", "should not", "could not", "it is", "that is", "there is", "i am",
                "you are", "we are", "they are", "i will", "you will", "we will", "i have", "you have", "we have",
                "let us", "what is", "here is"]
CONTRACTION_RE = re.compile(r"\b\w+'(s|t|re|ve|ll|d|m)\b", re.I)
MARKERS = ["honestly", "look,", "right?", "okay so", "ok so", "i mean", "actually", "here's the thing", "listen"]


def speech_text(raw):
    keep = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith(("ON SCREEN:", "#", "|", "---", "```")):
            continue
        s = re.sub(r"^(VO|V\.O\.|[A-Z][A-Za-z ]{0,20}):\s*", "", s) if re.match(r"^[A-Z][A-Za-z. ]{0,20}:\s", s) else s
        keep.append(s)
    return " ".join(keep).replace("’", "'")


def sentences(text):
    parts = re.split(r"(?<=[.!?])\s+|\s+[—-]{1,2}\s+(?=[A-Z])|\.\.\.\s*", text)
    return [p.strip(" \"'") for p in parts if re.search(r"\w", p)]


def words(s):
    return re.findall(r"[\w'%-]+", s)


def spoken_count(ws):
    n = 0
    for w in ws:
        n += 2 if re.fullmatch(r"\d{3,}[\d.,]*%?", w) else 1
    return n


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def main():
    ap = argparse.ArgumentParser(description="Score an ad script against the chad-copy voice targets.")
    ap.add_argument("script")
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--lang", default="en")
    ap.add_argument("--wps", type=float, default=2.5)
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    p = Path(a.script)
    if not p.is_file():
        sys.exit(f"File not found: {p}")
    text = speech_text(p.read_text(encoding="utf-8"))
    sents = sentences(text)
    if not sents:
        sys.exit("No spoken text found (lines starting with ON SCREEN:, #, | are skipped).")
    lens = [len(words(s)) for s in sents]
    all_words = [w for s in sents for w in words(s)]
    low = text.lower()
    fixes = 0

    def out(ok, label, detail):
        nonlocal fixes
        tag = "PASS" if ok is True else ("INFO" if ok is None else "FIX ")
        fixes += ok is False
        print(f"{tag}  {label:<22} {detail}")

    n = len(sents)
    print(f"Script: {p.name} | sentences {n} | words {len(all_words)} | language {a.lang}\n")
    short = sum(1 for x in lens if x < 8)
    long_ = sum(1 for x in lens if x > 25)
    out(pct(short, n) >= 25, "Short sentences", f"{pct(short, n):.0f} % under 8 words (target 25 %+)")
    out(long_ >= 1 if n >= 6 else None, "Long sentences",
        f"{long_} over 25 words ({pct(long_, n):.0f} %; target 15 %+ on long scripts, at least one in a 30 s ad)")
    frag = sum(1 for x in lens if x <= 4)
    out(pct(frag, n) >= 8, "Fragments", f"{pct(frag, n):.0f} % of sentences are 4 words or less (target 8-12 %)")
    runs = [i + 1 for i in range(n - 2) if max(lens[i:i + 3]) - min(lens[i:i + 3]) <= 3 and min(lens[i:i + 3]) > 4]
    out(not runs, "Rhythm", "ok" if not runs else f"3 similar-length sentences in a row starting at sentence {runs[0]}")

    found_conn = [c for c in BANNED_CONNECTORS if c in low]
    out(not found_conn, "Essay connectors", "none" if not found_conn else "remove: " + ", ".join(found_conn))
    found_banned = [w for w in BANNED_WORDS if re.search(r"\b" + re.escape(w) + r"\b", low)]
    out(not found_banned, "Delete-on-sight words", "none" if not found_banned else "remove: " + ", ".join(found_banned))

    if a.lang.lower().startswith("en"):
        conj = sum(1 for s in sents if words(s) and words(s)[0].lower() in CONJUNCTIONS)
        out(pct(conj, n) >= 10, "Conjunction starts", f"{pct(conj, n):.0f} % start with And/But/So/Now... (target 10 %+)")
        unc = [u for u in UNCONTRACTED if re.search(r"\b" + u + r"\b", low)]
        con = len(CONTRACTION_RE.findall(text))
        out(len(unc) <= 1, "Contractions", f"{con} contracted; uncontracted pairs: {', '.join(unc) if unc else 'none'}"
            " (one emphatic pair is fine)")
        mk = sum(low.count(m) for m in MARKERS)
        per100 = 100.0 * mk / max(len(all_words), 1)
        out(None, "Discourse markers", f"{mk} ({per100:.1f} per 100 words; aim for about 2-3, spread out)")

    spoken = spoken_count(all_words)
    est = spoken / a.wps
    if a.seconds:
        out(abs(est - a.seconds) <= 2.0, "Length", f"about {est:.1f} s at {a.wps} words/s vs target {a.seconds:.0f} s"
            + ("" if abs(est - a.seconds) <= 2.0 else " -> cut or add whole lines, never change the read speed"))
    else:
        out(None, "Length", f"about {est:.1f} s at {a.wps} words/s (give --seconds to check a target)")

    print(f"\n{fixes} check(s) to fix. Then read it aloud with a timer.")
    if a.strict and fixes:
        sys.exit(1)


if __name__ == "__main__":
    main()
