"""Hook variant of a finished VOICEOVER-mode rawedit ad: new spoken hook + new hook shots, identical body.

Usage: .venv/bin/python -I tools/rawedit_variant.py <base> <new> --hook-vo <hook.mp3> --body-from <beat n>
                    [--split-word "<first word of the 2nd hook shot>"] [--shot-a <clip>] [--shot-b <clip>] [--gap 0.28]
Builds projects/<new>: voice = hook line (loudness-matched) + the base VO from beat n on; keep ranges mapped word by word;
body shots/cards/sfx/anims/word_fix/music stops shifted by the new hook length; hook shots A/B placed on the hook words.
Then: rawedit.py <new> render --music ... and verify.
"""
import difflib, json, pathlib, re, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rawedit as R


def lufs(f):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(f), "-af", "loudnorm=I=-16:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    return float(json.loads(re.search(r"\{.*\}", r.stderr, re.S).group(0))["input_i"])


def main():
    a = sys.argv[1:]; opt = lambda n, d=None: a[a.index(n) + 1] if n in a else d
    base_p = R.ROOT / "projects" / a[0]; new_name = a[1]; base = R.load(base_p)
    N = int(opt("--body-from")); hook = pathlib.Path(opt("--hook-vo")).resolve(); gap = float(opt("--gap", 0.28))
    bN = next(b for b in base["beats"] if b["n"] == N); src_in = bN["segs"][0]["in"]
    araw = R.RAW / base["aroll"]["file"]
    work = R.ROOT / "projects" / new_name / "VO"; work.mkdir(parents=True, exist_ok=True)
    body = work / "body.wav"; hk = work / "hook.wav"; joined = work / "voice_joined.wav"
    R.sh("ffmpeg", "-v", "error", "-y", "-ss", f"{src_in:.3f}", "-i", araw, "-vn", "-ac", "1", "-ar", "48000", body)
    gain = lufs(body) - lufs(hook)   # hook at the body's loudness
    R.sh("ffmpeg", "-v", "error", "-y", "-i", hook, "-af", f"highpass=f=70,volume={gain:.2f}dB,apad=pad_dur={gap}", "-ac", "1", "-ar", "48000", hk)
    R.sh("ffmpeg", "-v", "error", "-y", "-i", hk, "-i", body, "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1", "-ac", "1", "-ar", "48000", joined)
    R.new_vo(new_name, str(joined)); proj = R.ROOT / "projects" / new_name; plan = R.load(proj)
    tw, sil = R.transcribe(plan["aroll"]["fid"], R.RAW / plan["aroll"]["file"]); W = tw["words"]
    bw, _ = R.transcribe(base["aroll"]["fid"], R.RAW / base["aroll"]["file"]); BW = bw["words"]
    norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    a0 = bN["words"][0]
    m = difflib.SequenceMatcher(None, [norm(w["w"]) for w in BW[a0:]], [norm(w["w"]) for w in W], autojunk=False)
    mp = {}
    for tag, i1, i2, j1, j2 in m.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1): mp[a0 + i1 + k] = j1 + k
    k_hook = mp[a0]   # words before the body = the hook
    keep = [[0, k_hook - 1]]
    for (x, y) in base["keep"][N - 1:]:
        xs = [mp[i] for i in range(x, y + 1) if i in mp]
        if not xs: sys.exit(f"keep {x}-{y} not found in the new transcript")
        keep.append([min(xs), max(xs)])
    renum = lambda n: n - N + 2   # base beat n -> new beat number
    plan["keep"] = keep
    for kk in ("rules", "hook_card", "hook_style", "music_kind", "music_mood", "music_vocals"):
        if kk in base: plan[kk] = base[kk]
    plan["hold_beat"] = 2
    if base.get("cta_beat"): plan["cta_beat"] = base["cta_beat"] if base["cta_beat"] == "last" else renum(base["cta_beat"])
    plan["music_stops"] = [renum(n) for n in base.get("music_stops") or [] if n >= N]
    plan["tighten_seams"] = [renum(n) for n in base.get("tighten_seams") or [] if n >= N]
    R.save(proj, plan)
    beats, total, warns = R.build_edl(plan, W, sil, R.probe(R.RAW / plan["aroll"]["file"])[0])
    plan["beats"], plan["total"] = beats, total
    t_new2 = beats[1]["t"]; t_baseN = bN["t"]; shift = t_new2 - t_baseN
    H = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(hk)], capture_output=True, text=True).stdout)   # hook + gap length: new source time = base source time - src_in + H
    bsegs = [g for b in base["beats"] for g in b["segs"]]; nsegs = [g for b in beats for g in b["segs"]]
    spd_b = base.get("rules", {}).get("speed", 1.0); spd_n = plan.get("rules", {}).get("speed", 1.0)
    def sh_(t):
        """base output time -> base source -> new source -> new output, through both EDLs (exact, per cut)."""
        g = next((g for g in bsegs if g["t"] - 1e-6 <= t < g["t"] + g["dur"] + 1e-6), bsegs[-1])
        src = g["in"] + (t - g["t"]) * spd_b - src_in + H
        for h in nsegs:
            if h["in"] - 1e-6 <= src < h["out"] + 1e-6: return round(h["t"] + (src - h["in"]) / spd_n, 3)
        nxt = [h for h in nsegs if h["in"] > src]
        return round(nxt[0]["t"], 3) if nxt else round(total, 3)
    absrc = lambda x: str((base_p / x).resolve()) if not pathlib.Path(x).is_absolute() and (base_p / x).exists() else x
    plan["shots"] = [{**s, "at": sh_(s["at"]), "src": absrc(s["src"])} for s in base["shots"] if s["at"] >= t_baseN - 0.01]
    plan["cards"] = [{**c, "at": sh_(c["at"])} for c in base.get("cards") or [] if c["at"] >= t_baseN - 0.01]
    plan["sfx"] = [{**s, "at": sh_(s["at"])} for s in base.get("sfx") or [] if s["at"] >= t_baseN - 0.3]
    plan["anims"] = [{**x, "at": sh_(x["at"])} for x in base.get("anims") or [] if x["at"] >= t_baseN]
    plan["word_fix"] = [{**w, "near": sh_(w["near"]), "start": sh_(w["start"])} for w in base.get("word_fix") or [] if w["near"] >= t_baseN]
    # hook shots on the hook words: A from 0, B from the split word
    hook_words = W[:k_hook]; split = opt("--split-word")
    tb = next((hw["start"] for hw in hook_words if split and norm(hw["w"]) == norm(split)), None)
    hs = []
    if opt("--shot-a"): hs.append({"at": 0.0, "src": opt("--shot-a"), "in": 0.2, "fx": ["flash"], "note": "AI hook shot A"})
    if opt("--shot-b") and tb is not None:
        hs.append({"at": round(max(tb - 0.08, 0.6), 3), "src": opt("--shot-b"), "in": 0.2, "fx": ["punch"], "note": "AI hook shot B"})
    plan["shots"] = hs + plan["shots"]
    plan["sfx"] = ([{"at": hs[1]["at"], "kind": "whoosh", "db": -16, "lead": -0.25}] if len(hs) > 1 else []) + \
                  [{"at": t_new2, "kind": "whoosh", "db": -16, "lead": -0.25}] + [s for s in plan["sfx"] if abs(s["at"] - t_new2) > 0.3]
    plan["variant_of"] = a[0]; R.save(proj, plan)
    print(f"{new_name}: hook {k_hook} words, {beats[0]['dur']:.2f}s; body shift {shift:+.2f}s; total {total:.2f}s; {len(plan['shots'])} shots")
    for w_ in warns: print("  WARN", w_)


if __name__ == "__main__":
    main()
