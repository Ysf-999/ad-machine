"""Re-derive VO/alignment.json from Whisper word timestamps on the real VO/vo.mp3 (fixes maps that drift from the audio).

Usage: realign_vo.py <project-dir> [--check]   (--check only prints the drift, writes nothing)
Keeps the alignment's characters (the script text) so beat lookups still work; each word's characters are spread
over the Whisper word span. Backs up the old map to VO/alignment_before_realign.json and rewrites every beat's
vo_start/vo_end in plan.json. Clip durations are not touched: re-run stitch and read its CAPPED/FREEZE flags.
"""
import json, pathlib, re, sys, difflib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
def realign(proj, check=False):
    """Returns (median_drift, max_abs_drift) of the old map vs the audio; rewrites alignment.json + plan.json unless check."""
    import mlx_whisper
    al = json.loads((proj / "VO" / "alignment.json").read_text())
    chars, st, en = al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]
    words, cur, ws, last = [], "", None, None  # (text, start, end, char_index_start, char_index_end)
    for i, (c, s, e) in enumerate(zip(chars, st, en)):
        if c.isspace():
            if cur: words.append([cur, ws, last, i0, i - 1]); cur = ""
            continue
        if not cur: ws, i0 = s, i
        cur += c; last = e
    if cur: words.append([cur, ws, last, i0, len(chars) - 1])
    r = mlx_whisper.transcribe(str(proj / "VO" / "vo.mp3"), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en", word_timestamps=True)
    ww = [(w["word"].strip(), w["start"], w["end"]) for s in r["segments"] for w in s["words"]]
    norm = lambda t: re.sub(r"[^a-z0-9']", "", t.lower().replace("1", "one").replace("2", "two"))
    sm = difflib.SequenceMatcher(None, [norm(w[0]) for w in words], [norm(w[0]) for w in ww], autojunk=False)
    new = [None] * len(words); drift = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                new[i1 + k] = (ww[j1 + k][1], ww[j1 + k][2]); drift.append(ww[j1 + k][1] - words[i1 + k][1])
        elif op == "replace" and j2 > j1:  # e.g. a brand name heard as two words: spread the eleven words over the whisper span
            a, b = ww[j1][1], ww[j2 - 1][2]; n = i2 - i1
            for k in range(n):
                new[i1 + k] = (a + (b - a) * k / n, a + (b - a) * (k + 1) / n)
        # delete (whisper missed a word): filled by interpolation below
    # phrase onsets: Whisper stretches the previous word across a pause, so the next phrase's start sits inside the
    # silence (captions early) or, with ElevenLabs maps, late. For every word that follows . , ! ? … in the script,
    # find the longest pause near the estimate and snap the start to where the voice actually comes back.
    import vo_onsets
    x, sr = vo_onsets.load(proj / "VO" / "vo.mp3"); db, win = vo_onsets.rms_track(x, sr); sp, qt = vo_onsets.levels(db)
    idx = [i for i, nw in enumerate(new) if nw]
    ws = [[new[i][0], new[i][1], words[i][0]] for i in idx]; before = [w[0] for w in ws]
    vo_onsets.refine_starts(ws, db, win, sp, qt)
    snapped = 0
    for i, w, b0 in zip(idx, ws, before):
        if abs(w[0] - b0) > 0.02: new[i] = (w[0], max(new[i][1], w[0] + 0.08)); snapped += 1
    print(f"  {snapped} sentence onsets snapped to the audio")
    for i, w in enumerate(words):
        if new[i] is None:
            prev = next((new[j][1] for j in range(i - 1, -1, -1) if new[j]), 0.0)
            nxt = next((new[j][0] for j in range(i + 1, len(words)) if new[j]), prev + (w[2] - w[1]))
            new[i] = (prev, max(prev + 0.05, nxt))
            print(f"  ! word {w[0]!r} not heard by Whisper: interpolated {prev:.2f}-{new[i][1]:.2f}")
    med = sorted(drift)[len(drift)//2]; mx = max(abs(d) for d in drift)
    print(f"drift of the old map vs audio: first {drift[0]:+.2f}s, median {sorted(drift)[len(drift)//2]:+.2f}s, last {drift[-1]:+.2f}s, max |{max(abs(d) for d in drift):.2f}|s over {len(drift)} words")
    if check: return med, mx
    nst, nen = list(st), list(en)
    for w, (a, b) in zip(words, new):
        n = w[4] - w[3] + 1
        for k, i in enumerate(range(w[3], w[4] + 1)):
            nst[i] = round(a + (b - a) * k / n, 3); nen[i] = round(a + (b - a) * (k + 1) / n, 3)
    for i, c in enumerate(chars):  # spaces: sit between the neighbouring words
        if c.isspace():
            nst[i] = nen[i - 1] if i else 0.0; nen[i] = nst[i + 1] if i + 1 < len(chars) else nst[i]
    (proj / "VO" / "alignment_before_realign.json").write_text(json.dumps(al))
    (proj / "VO" / "alignment.json").write_text(json.dumps({"characters": chars, "character_start_times_seconds": nst, "character_end_times_seconds": nen}))
    plan = json.loads((proj / "plan.json").read_text()); text = "".join(chars); pos = 0
    for b in plan["beats"]:
        i = text.find(b["vo"], pos)
        if i < 0: sys.exit(f"beat {b['n']} vo text not found in alignment text: {b['vo']!r}")
        j = i + len(b["vo"]) - 1; pos = j
        old = (b.get("vo_start"), b.get("vo_end")); b["vo_start"], b["vo_end"] = round(nst[i], 2), round(nen[j], 2)
        print(f"  beat {b['n']:2d}: {old[0]}-{old[1]} -> {b['vo_start']}-{b['vo_end']}")
    (proj / "plan.json").write_text(json.dumps(plan, indent=2)); print("alignment.json + plan.json rewritten"); return med, mx


if __name__ == "__main__":
    realign(pathlib.Path(sys.argv[1]).resolve(), "--check" in sys.argv)
