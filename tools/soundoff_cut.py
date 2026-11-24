"""Sound-off placement cut: a second version of a finished master for muted Stories/Reels viewing (Andromeda read, 11/7:
the same ad scores differently with sound on vs off, so ship one version per viewing context).

Usage (PY = .venv/bin/python, from the repo root):
  soundoff_cut.py <project-dir> [--hook "FIRST-FRAME LINE"] [--secs 3.5] [--file MASTER.mp4]
  soundoff_cut.py <any.mp4> --hook "FIRST-FRAME LINE"            (a master outside a project: no caption-coverage check)

What it does, and only this (the master is never touched; works for ad.py and rawedit.py projects):
  1. Hook on screen from frame one. If the plan already burns one (hook_card / hook_text, or a Hook line in
     EDIT_KIT/captions.ass) nothing is added. Otherwise --hook is required: a 3-7 word first-frame card from hook-lab,
     drawn as the C009 hook box (same look as the masters) for 3-5 s. Without --hook it stops and prints the first spoken
     line as a starting point; it never invents the hook itself.
  2. Caption coverage: every spoken word (Whisper on VO/vo.mp3, else the master) must sit under a caption card or the
     hook. Uncovered stretches are listed with times: on mute those words do not exist.
  3. First second: no black head, hook visible by t=1.0 s.
Writes <project>/MASTER-soundoff.mp4 (audio kept, for viewers who unmute) and <project>/QC/soundoff_checks.md.
If the master already passes every check, no copy is written: the master itself is the sound-off cut.
"""
import json, pathlib, re, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rawedit as RE

WHISPER = "mlx-community/whisper-large-v3-turbo"


def secs(ts):
    h, m, s = ts.split(":"); return int(h) * 3600 + int(m) * 60 + float(s)


def ass_events(ass):
    """[(start, end, style, text)] from an ASS file."""
    ev = []
    for l in ass.read_text().splitlines():
        if l.startswith("Dialogue:"):
            f = l.split(",", 9); ev.append((secs(f[1]), secs(f[2]), f[3], f[9]))
    return ev


def words_of(audio):
    import mlx_whisper
    r = mlx_whisper.transcribe(str(audio), path_or_hf_repo=WHISPER, language="en", word_timestamps=True)
    return [(w["word"].strip(), w["start"], w["end"]) for s in r["segments"] for w in s.get("words", []) if w["word"].strip()]


def first_line(words, max_words=8):
    out = []
    for w, _, _ in words:
        out.append(w)
        if w[-1] in ".!?" or len(out) >= max_words: break
    return " ".join(out).rstrip(".,!?")


def black_head(mp4):
    r = subprocess.run(["ffmpeg", "-v", "info", "-t", "1.5", "-i", str(mp4), "-vf", "blackdetect=d=0.05:pix_th=0.08", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", r.stderr) if float(a) < 0.05]


def main():
    a = sys.argv[1:]
    def opt(n, d, cast=str):
        if n in a:
            i = a.index(n); v = cast(a[i + 1]); del a[i:i + 2]; return v
        return d
    hook = opt("--hook", None); hsecs = opt("--secs", None, float); fname = opt("--file", "MASTER.mp4")
    target = pathlib.Path(a[0]).resolve()
    if target.is_dir():
        proj, master = target, target / fname
        plan = json.loads((proj / "plan.json").read_text()) if (proj / "plan.json").exists() else {}
    else:
        proj, master, plan = target.parent, target, {}
    if not master.exists(): sys.exit(f"no {master}")
    base = RE.DEFAULT_RULES
    if target.is_dir() and any((proj / "CLIPS").glob("clip_*.mp4")):   # ad.py (animated) project: same hook-box look as its stitch
        import assemble_anim as AA; base = {**RE.DEFAULT_RULES, **AA.AI_RULES}
    R = {**base, **plan.get("rules", {})}
    ass = proj / "EDIT_KIT" / "captions.ass" if target.is_dir() else None
    ev = ass_events(ass) if ass and ass.exists() else None
    has_hook = bool(plan.get("hook_card") or plan.get("hook_text") or (ev and any(e[2] == "Hook" for e in ev)))
    vo = proj / "VO" / "vo.mp3"
    words = words_of(vo if target.is_dir() and vo.exists() else master)   # the master is picture + vo.mp3 at t=0

    if not has_hook and not hook:
        print("No hook text on screen in this master, and no --hook given.")
        print(f"First spoken line, as a starting point only: \"{first_line(words).upper()}\"")
        print("Write a 3-7 word first-frame card (hook-lab, format 'first-frame card') and re-run with --hook \"...\".")
        sys.exit(2)

    checks = [f"# Sound-off cut checks: {master.name}", ""]
    add = None
    if has_hook and not hook:
        checks.append("- hook: already burned into the master from frame one -> ok")
    else:
        b1_end = next((e for w, s, e in words if w[-1] in ".!?"), 3.0)
        hd = hsecs or min(max(b1_end + 0.3, 3.0), 5.0)
        add = (hook, hd)
        checks.append(f"- hook: added \"{hook.upper()}\" as the hook box, 0-{hd:.1f}s (y {R['hook_y']})"
                      + ("  !! the master already has a hook: two hook texts on screen" if has_hook else ""))

    # caption coverage: a word is covered when its midpoint sits inside a caption card or the hook window
    if ev is None:
        checks.append("- captions: no EDIT_KIT/captions.ass, coverage not checked (burn captions with ad.py stitch / rawedit.py render)")
        gaps = []
    else:
        spans = [(s, e) for s, e, _, _ in ev] + ([(0.0, add[1])] if add else [])
        bare = [(w, s, e) for w, s, e in words if not any(s0 - 0.05 <= (s + e) / 2 <= e0 + 0.05 for s0, e0 in spans)]
        gaps, cur = [], []
        for w in bare:
            if cur and w[1] - cur[-1][2] > 0.6: gaps.append(cur); cur = []
            cur.append(w)
        if cur: gaps.append(cur)
        checks.append(f"- captions: {len(words) - len(bare)}/{len(words)} spoken words under a card or the hook -> "
                      + ("ok" if not gaps else f"!! {len(gaps)} uncaptioned stretch(es):"))
        for g in gaps:
            checks.append(f"    {g[0][1]:.2f}-{g[-1][2]:.2f}s  \"{' '.join(w for w, _, _ in g)}\"")

    bh = black_head(master)
    checks.append("- first second: " + ("no black head" if not bh else "!! black frames at " + ", ".join(f"{x:.2f}-{y:.2f}s" for x, y in bh)))
    first_word = words[0][1] if words else None
    if not has_hook and not add:
        checks.append("- hook by 1.0 s: !! no hook text")
    else:
        checks.append("- hook by 1.0 s: on screen from frame one -> ok")
    if first_word is not None and first_word > 1.0 and not (has_hook or add):
        checks.append(f"- !! first word at {first_word:.1f}s with nothing on screen to read before it")

    out = proj / "MASTER-soundoff.mp4" if target.is_dir() else master.with_name(master.stem + "-soundoff.mp4")
    if add:
        png, hw, hh = RE.hook_png(add[0].upper(), proj / ("EDIT_KIT" if target.is_dir() else ".") / "hook_card_soundoff.png", R)
        vis = hw - 2 * int(int(R.get("hook_px", 58)) * 0.6)   # the PNG carries a drop-shadow pad on each side
        side_ok = (1080 - vis) / 2 >= RE.SAFE["side"] * 1080 and R["hook_y"] >= RE.SAFE["top"] * 1920
        checks.append(f"- hook box: {vis}px wide visible -> " + ("inside Meta's safe zone" if side_ok else "!! breaks the side/top safe margin: shorten the line"))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(master), "-loop", "1", "-i", str(png), "-filter_complex",
                        f"[0:v][1:v]overlay=x=(W-w)/2:y={R['hook_y']}:shortest=1:enable='lt(t,{add[1]:.3f})'[v]",
                        "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "copy", str(out)], check=True)
        checks.append(f"\nWROTE {out.name}")
    elif not gaps and not bh:
        checks.append(f"\nMASTER already sound-off ready: use {master.name} for Stories/Reels too (no copy written).")
    else:
        checks.append("\nNo copy written: fix the !! items in the master (captions / head), then re-run.")
    fails = [c for c in checks if "!!" in c]
    checks.insert(1, f"VERDICT: {'PASS' if not fails else 'FIX'}")
    rep = (proj / "QC" if target.is_dir() else proj); rep.mkdir(exist_ok=True)
    (rep / "soundoff_checks.md").write_text("\n".join(checks) + "\n")
    print("\n".join(checks))
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
