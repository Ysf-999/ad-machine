"""Measure caption-to-audio sync on a finished master: Whisper word timestamps on MASTER.mp4 vs the start of each
caption card in EDIT_KIT/captions.ass. PASS when the median card lead/lag is within 0.08 s and no card is off by more
than 0.2 s (ground truth = Whisper on the clean VO with energy-snapped sentence onsets). Usage: caption_sync_check.py <project-dir>   (also run automatically by ad.py stitch)"""
import json, pathlib, re, sys, difflib
sys.path.insert(0, str(pathlib.Path(__file__).parent))

def check(proj):
    import mlx_whisper
    ass = (proj / "EDIT_KIT" / "captions.ass").read_text().splitlines()
    cards = []
    for l in ass:
        if l.startswith("Dialogue:") and ",Cap," in l:
            f = l.split(",", 9); h, m, s = f[1].split(":"); cards.append((int(h) * 3600 + int(m) * 60 + float(s), re.sub(r"\{[^}]*\}", "", f[9])))   # 11/22: drop ASS override tags ({\pos}, T53 word fades) before matching words
    norm = lambda t: re.sub(r"[^a-z0-9']", "", t.lower().replace("1", "one").replace("2", "two"))
    # ground truth = the clean VO (the master is picture + vo.mp3 at t=0, same timeline): Whisper word starts, with
    # words after a pause snapped to the real voice onset. Whisper on the mix wobbles ±0.3 s on sentence starts.
    import vo_onsets
    r = mlx_whisper.transcribe(str(proj / "VO" / "vo.mp3"), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en", word_timestamps=True)
    ww = [[norm(w["word"]), w["start"], w["end"], w["word"].strip()] for seg in r["segments"] for w in seg["words"] if norm(w["word"])]
    x, sr = vo_onsets.load(proj / "VO" / "vo.mp3"); db, win = vo_onsets.rms_track(x, sr); sp, qt = vo_onsets.levels(db)
    rw = [[w[1], w[2], w[3]] for w in ww]
    vo_onsets.refine_starts(rw, db, win, sp, qt)  # same physics as realign_vo (guards: between neighbours, no 120 ms silence inside a word)
    for w, r2 in zip(ww, rw): w[1] = r2[0]
    ww = [(w[0], w[1]) for w in ww]
    cw = []  # (card index, word)
    for i, (t, txt) in enumerate(cards):
        for k, w in enumerate(txt.replace("\\N", " ").split()):
            if norm(w): cw.append((i, norm(w), k == 0))
    sm = difflib.SequenceMatcher(None, [w for _, w, _ in cw], [w for w, _ in ww], autojunk=False)
    offs = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal": continue
        for k in range(i2 - i1):
            ci, _, first = cw[i1 + k]
            if first: offs.append((cards[ci][0] - ww[j1 + k][1], cards[ci][1]))
    if not offs:
        print("!! CAPTION SYNC: no cards matched to audio"); return False
    d = sorted(x for x, _ in offs); med = d[len(d) // 2]; worst = max(offs, key=lambda x: abs(x[0]))
    ok = abs(med) <= 0.08 and abs(worst[0]) <= 0.2
    print(f"{'CAPTION SYNC PASS' if ok else '!! CAPTION SYNC FAIL'}: {len(offs)}/{len(cards)} cards matched, median {med:+.2f}s "
          f"(+ = caption late), worst {worst[0]:+.2f}s on {worst[1]!r}")
    if not ok:
        for x, t in offs:
            if abs(x) > 0.25: print(f"   {x:+.2f}s  {t}")
        print("   fix: `ad.py <project> realign` (Whisper re-times the map), then stitch again")
    return ok

if __name__ == "__main__":
    sys.exit(0 if check(pathlib.Path(sys.argv[1]).resolve()) else 1)
