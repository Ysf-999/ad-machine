#!/usr/bin/env python3
"""Time a song's lyric lines and plan one shot grid from them.

Inputs
  --lyrics   text file: one sung line per line. Section tags like [Verse] or
             [Beat 3 - Rock bottom] are allowed on their own line and carried through.
  --segments JSON transcript of the song: a list of {"start", "end", "text"}
             (or {"segments": [...]}). Any speech-to-text output in that shape works.
  --duration song length in seconds. Used only when there is no transcript:
             lines are then spaced by syllable count and marked "estimated".
  --script-only  no song at all: the length is estimated from the word count at the
             sung pace measured in the proven ads (~2.5 words/second). Marked "estimated".
  --out      path for the grid JSON (a markdown table is always printed).

Shot rules are measured from five proven singing ads (see references/visual-dna.md):
  - cuts land on line starts only
  - the first line is the hook: one shot holds it whole (split only past 6.5s)
  - short lines group into one shot up to the pace target; long lines split
  - --pace fast (~1.7s, the top-scoring ad) or standard (~2.8s, the rest)
"""
import argparse
import difflib
import json
import math
import re
import sys

TAG = re.compile(r"^\[(.+)\]$")


def norm(w):
    return re.sub(r"[^a-z0-9']", "", w.lower())


def syllables(text):
    n = 0
    for w in text.split():
        groups = re.findall(r"[aeiouy]+", w.lower())
        n += max(1, len(groups) - (1 if w.lower().endswith("e") and len(groups) > 1 else 0))
    return max(n, 1)


def read_lyrics(path):
    lines, section = [], None
    for raw in open(path, encoding="utf-8"):
        t = raw.strip()
        if not t:
            continue
        m = TAG.match(t)
        if m:
            if m.group(1).lower().startswith("beat"):
                section = m.group(1)  # [Verse]/[Chorus] tags are for the singer, not the grid
            continue
        lines.append({"n": len(lines) + 1, "text": t, "section": section})
    return lines


def word_times(segments):
    """Spread each segment's words evenly across its span."""
    words = []
    for s in segments:
        toks = [t for t in s["text"].split() if norm(t)]
        if not toks:
            continue
        span = (s["end"] - s["start"]) / len(toks)
        for i, t in enumerate(toks):
            words.append((norm(t), s["start"] + i * span))
    return words


def align(lines, segments):
    words = word_times(segments)
    seq = [w for w, _ in words]
    lyric_words, owner = [], []
    for i, ln in enumerate(lines):
        for t in ln["text"].split():
            if norm(t):
                lyric_words.append(norm(t))
                owner.append(i)
    sm = difflib.SequenceMatcher(None, lyric_words, seq, autojunk=False)
    first = {}
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            li = owner[a + k]
            first.setdefault(li, words[b + k][1])
    matched = len(first)
    # Fill lines the transcript missed by interpolating between neighbours.
    starts = [first.get(i) for i in range(len(lines))]
    for i in range(len(lines)):
        if starts[i] is None:
            prev = next((starts[j] for j in range(i - 1, -1, -1) if starts[j] is not None), 0.0)
            nxt_i = next((j for j in range(i + 1, len(lines)) if starts[j] is not None), None)
            nxt = starts[nxt_i] if nxt_i is not None else segments[-1]["end"]
            gap = (nxt_i - i + 1) if nxt_i is not None else (len(lines) - i + 1)
            starts[i] = prev + (nxt - prev) / gap
    song_end = segments[-1]["end"]
    for i, ln in enumerate(lines):
        ln["start"] = round(starts[i], 2)
        ln["end"] = round(starts[i + 1] if i + 1 < len(lines) else song_end, 2)
        ln["timing"] = "transcript" if i in first else "interpolated"
    return matched


def estimate(lines, duration):
    total = sum(syllables(l["text"]) for l in lines)
    t = 0.0
    for ln in lines:
        d = duration * syllables(ln["text"]) / total
        ln["start"], ln["end"], ln["timing"] = round(t, 2), round(t + d, 2), "estimated"
        t += d


SUNG_WPS = 2.5  # measured: 2.4-2.7 words/s across the five proven ads (visual-dna.md)
PACE = {"fast": 1.7, "standard": 2.8}  # seconds per shot, measured (visual-dna.md)


def plan_shots(lines, target):
    """Cut only on line starts. Group short lines up to the target shot length,
    split lines that run well past it, and never group across a section tag."""
    groups, cur = [], []
    for i, ln in enumerate(lines):
        d = ln["end"] - ln["start"]
        if i == 0:  # the hook holds its whole first line
            groups.append([ln])
            continue
        if cur and (cur[0]["section"] != ln["section"]
                    or cur[-1]["end"] - cur[0]["start"] >= target * 0.8
                    or d > target * 1.6):
            groups.append(cur)
            cur = []
        cur.append(ln)
    if cur:
        groups.append(cur)

    shots = []
    for g in groups:
        start, end = g[0]["start"], g[-1]["end"]
        d = end - start
        limit = 6.5 if g[0]["n"] == 1 else target * 1.6
        count = 1 if d <= limit else max(2, round(d / target))
        span = d / count
        nums = f"{g[0]['n']}-{g[-1]['n']}" if len(g) > 1 else str(g[0]["n"])
        for k in range(count):
            shots.append({
                "shot": len(shots) + 1,
                "start": round(start + k * span, 2),
                "end": round(start + (k + 1) * span, 2),
                "lines": nums,
                "lyric": " / ".join(l["text"] for l in g),
                "section": g[0]["section"],
                "part": f"{k + 1}/{count}" if count > 1 else "",
            })
    return shots


def tc(s):
    return f"{int(s // 60)}:{s % 60:04.1f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lyrics", required=True)
    ap.add_argument("--segments")
    ap.add_argument("--duration", type=float)
    ap.add_argument("--script-only", action="store_true",
                    help="no song yet: estimate length from words at the measured sung pace")
    ap.add_argument("--pace", choices=sorted(PACE), default="standard",
                    help="fast = ~1.7s shots (top-scoring ad), standard = ~2.8s")
    ap.add_argument("--out")
    a = ap.parse_args()
    lines = read_lyrics(a.lyrics)
    if not lines:
        sys.exit("No lyric lines found.")
    if a.segments:
        seg = json.load(open(a.segments))
        seg = seg.get("segments", seg) if isinstance(seg, dict) else seg
        matched = align(lines, seg)
        note = f"{matched}/{len(lines)} lines matched to the transcript"
    elif a.duration or a.script_only:
        dur = a.duration or sum(len(l["text"].split()) for l in lines) / SUNG_WPS
        estimate(lines, dur)
        src = "song length" if a.duration else f"word count at {SUNG_WPS} words/s"
        note = f"ESTIMATED timing from {src} (no transcript): shots will not land exactly on the music"
    else:
        sys.exit("Give --segments (preferred), --duration, or --script-only.")
    shots = plan_shots(lines, PACE[a.pace])
    print(f"<!-- {note}; {len(lines)} lines -> {len(shots)} shots at {a.pace} pace; song {tc(lines[-1]['end'])} -->")
    print("| Shot | Time | Lines | Lyric | Section |")
    print("|---|---|---|---|---|")
    for s in shots:
        lyric = s["lyric"] + (f" ({s['part']})" if s["part"] else "")
        print(f"| {s['shot']} | {tc(s['start'])}–{tc(s['end'])} | {s['lines']} | {lyric} | {s['section'] or ''} |")
    if a.out:
        json.dump({"note": note, "lines": lines, "shots": shots}, open(a.out, "w"), indent=2)


if __name__ == "__main__":
    main()
