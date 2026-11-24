"""Assemble a voiceover-led animated ad (course Stage 5: VO first, speed-map each clip to its line).

Usage: assemble_anim.py <project-dir> [--sfx-db -16] [--max-speed 3.0] [--min-speed 0.8] [--no-captions] [--endcard <image>] [--endcard-sec 2.0] [--music <mp3> --music-db -22]
plan.json "caption": {font,size,colour (ASS &HAABBGGRR),outline_colour,outline,margin_v,words,upper} overrides the caption look.
plan.json "hook_text": "WE MESSED UP\nOUR HALLOWEEN SALE" burns a big top-of-frame hook line for beat 1 (caption.hook_size/hook_colour/hook_end).
Needs plan.json beats[{n, vo_start, vo_end}], VO/vo.mp3, VO/alignment.json (ElevenLabs char alignment) and
CLIPS/clip_XX.mp4 (highest _vN wins). Each clip is sped up so it ends exactly when the next line starts.
Outputs MASTER.mp4, EDIT_KIT/ (numbered retimed clips + vo.mp3 + captions.ass + ORDER.txt + EDIT_CHECKS.md).

Editing-course rules (knowledge/video-editing-course/EDITING_KB.md, C-rules shared with rawedit.py), all from plan.json:
  hook_card "3 reasons my couch still looks bad"   native white hook box from frame one, 3-5 s (C009; hook_text = old big line)
  music bed: EQ notch where the voice sits (C005, rules.music_eq), drop landed on the start of beat hold_beat (C003,
             --music-drop <s>|auto), music_stops [beat, ...] cut the music under the lines that must land (C007)
  sfx_cues [{"beat": n, "off": s, "kind": "pop", "db": -12, "lead": -1.2} | {"at": s, ...}]  library/sfx/ (C011)
  captions default bottom at y 1220 (caption.margin_v 700) inside Meta's safe zone (C010); EDIT_CHECKS.md reports
  safe zone, black head/tail, long single shots (C002 note), music drop landing.
"""
import json, re, subprocess, sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))   # run with -I: shared course helpers live in rawedit.py
import rawedit as RE

AI_RULES = {"music_eq": [1500, 4, -15], "caption_margin_v": 700, "hook_y": 300, "hook_tilt": 0, "hook_px": 58,
            "max_static": 3.5, "hook_margin_v": 290}

FONT = "Arial Black"


def ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)


def dur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)


def latest(d, stem):
    c = [p for p in d.glob(f"{stem}*.mp4") if re.fullmatch(rf"{stem}(_v\d+)?", p.stem)]
    return max(c, key=lambda p: int(p.stem.rsplit("_v", 1)[1]) if "_v" in p.stem else 1) if c else None


def atempo_chain(s):
    parts = []
    while s > 2.0:
        parts.append("atempo=2.0"); s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5"); s /= 0.5
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


def ass_time(t):
    h, r = divmod(t, 3600); m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def captions(al, out, offset=0.0, cfg=None):
    cfg = cfg or {}
    font = cfg.get("font", FONT); size = cfg.get("size", 78); colour = cfg.get("colour", "&H00FFFFFF")
    outline_c = cfg.get("outline_colour", "&H00000000"); outline = cfg.get("outline", 7); margin_v = cfg.get("margin_v", 520)
    words_per = cfg.get("words", 3); upper = cfg.get("upper", True)
    chars, st, en = al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]
    words, cur, ws = [], "", None
    for c, s, e in zip(chars, st, en):
        if c.isspace():
            if cur: words.append((cur, ws, last)); cur = ""
            continue
        if not cur: ws = s
        cur += c; last = e
    if cur: words.append((cur, ws, last))
    # chunking: split into phrases at punctuation, fold one-word phrases into a neighbour ("No, no, no!" stays
    # one card), then split long phrases evenly into chunks of at most max_words
    max_words = cfg.get("max_words", words_per + 1)
    phrases, g = [], []
    for w in words:
        g.append(w)
        if w[0][-1] in ".,!?…": phrases.append(g); g = []
    if g: phrases.append(g)
    merged = []
    for ph in phrases:
        if merged and len(ph) == 1 and merged[-1][-1][0][-1] not in ".!?" and len(merged[-1]) < max_words:
            merged[-1] += ph
        elif merged and len(merged[-1]) == 1 and merged[-1][-1][0][-1] not in ".!?" and len(ph) < max_words:
            merged[-1] += ph
        else:
            merged.append(ph)
    groups = []
    for ph in merged:
        n = -(-len(ph) // max_words); csz = -(-len(ph) // n)  # csz, not size: `size` is the caption font size used in the Style line below
        groups += [ph[i:i + csz] for i in range(0, len(ph), csz)]
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Cap,{font},{size},{colour},{colour},{outline_c},&H64000000,1,0,0,0,100,100,0,0,1,{outline},2,2,80,80,{margin_v},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lines = []
    if cfg.get("hook_text"):
        ht = cfg["hook_text"].replace("\n", "\\N"); he = cfg.get("hook_end", 3.0)
        hs = cfg.get("hook_size", 92); hc = cfg.get("hook_colour", "&H0000D7FF")
        lines.append(f"Dialogue: 1,{ass_time(0)},{ass_time(he)},Hook,,0,0,0,,{ht}")
        head = head.replace("\n\n[Events]", f"\nStyle: Hook,{font},{hs},{hc},{hc},{outline_c},&H64000000,1,0,0,0,100,100,0,0,1,{outline},2,8,60,60,{cfg.get('hook_margin_v', 290)},1\n\n[Events]")
    hook_end = cfg.get("hook_end", 0.0) if cfg.get("hook_text") else 0.0
    for i, g in enumerate(groups):
        s = g[0][1] + offset
        e = (groups[i + 1][0][1] + offset) if i + 1 < len(groups) else g[-1][2] + offset + 0.4
        if hook_end and s < hook_end - 0.05:
            continue  # the big hook card already carries these words; no duplicate caption under it
        txt = " ".join(w[0] for w in g).rstrip(".,"); txt = txt.upper() if upper else txt
        lines.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Cap,,0,0,0,,{txt}")
    out.write_text(head + "\n".join(lines) + "\n")


def ccfg_margin(plan, R):
    return (plan.get("caption") or {}).get("margin_v", R["caption_margin_v"])


def sfx_cues(plan, win):
    """plan.sfx_cues -> [(t, file, db)] on the master timeline (beat windows start where the beat's picture starts)."""
    ev = []
    for c in plan.get("sfx_cues") or []:
        if "at" in c: t = float(c["at"])
        elif c.get("beat") in win: t = win[c["beat"]][0] + float(c.get("off", 0))
        else: continue
        f = pathlib.Path(c["kind"])
        if not f.exists(): f = next(iter(sorted(RE.SFX_DIR.glob(f"{c['kind']}.*"))), None)
        if not f: print(f"  sfx '{c['kind']}' not in {RE.SFX_DIR} (tools/sfx.py list)"); continue
        ev.append((max(t + float(c.get("lead", 0)), 0.0), f, float(c.get("db", -12))))
    return ev


def main():
    a = sys.argv[1:]
    def opt(n, d, cast=float):
        if n in a:
            i = a.index(n); v = cast(a[i + 1]); del a[i:i + 2]; return v
        return d
    sfx_db = opt("--sfx-db", -16.0); max_speed = opt("--max-speed", 3.0)
    min_speed = opt("--min-speed", 0.8)  # a slightly short clip is slowed (up to 0.8x) rather than frozen
    endcard = opt("--endcard", None, str); end_sec = opt("--endcard-sec", 2.0)
    music = opt("--music", None, str); music_db = opt("--music-db", -22.0); drop = opt("--music-drop", None, str)
    caps = "--no-captions" not in a
    proj = pathlib.Path([x for x in a if not x.startswith("--")][0]).resolve()
    plan = json.loads((proj / "plan.json").read_text())
    R = {**AI_RULES, **plan.get("rules", {})}
    kit = proj / "EDIT_KIT"; kit.mkdir(exist_ok=True)
    vo = proj / "VO" / "vo.mp3"; vo_len = dur(vo)
    beats = plan["beats"]; parts, order, win = [], [], {}
    for i, b in enumerate(beats):
        start = 0.0 if i == 0 else b["vo_start"]
        end = beats[i + 1]["vo_start"] if i + 1 < len(beats) else vo_len + 0.3
        target = end - start; win[b["n"]] = (start, end)
        clip = latest(proj / "CLIPS", f"clip_{b['n']:02d}")
        if not clip: sys.exit(f"missing clip for beat {b['n']}")
        cd = dur(clip); speed = max(min_speed, min(max_speed, cd / target))
        used = min(cd, target * speed)
        flag = ""
        if cd / target > max_speed:  # clip too long even at max speed: its ending is cut off
            flag = f"  !! CAPPED: last {cd - target * max_speed:.1f}s of the clip is cut (split the beat or shorten the clip)"
        elif cd / speed < target - 0.05:  # clip too short even slowed down: last frame is held
            flag = f"  !! FREEZE: last frame held {target - cd / speed:.1f}s (clip {cd:.1f}s for a {target:.1f}s line)"
        if flag: print(f"beat {b['n']}:{flag}")
        out = kit / f"{b['n']:02d}_retimed.mp4"
        ff("-i", str(clip), "-t", f"{used:.3f}",
           "-vf", f"setpts=PTS/{speed:.4f},scale=1080:1920:flags=lanczos,setsar=1,fps=30,tpad=stop_mode=clone:stop_duration=3",
           "-af", f"{atempo_chain(speed)},volume={sfx_db}dB,apad", "-t", f"{target:.3f}",
           "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(out))
        parts.append(out); order.append(f"{out.name} <- {clip.name} speed {speed:.2f}x, {target:.2f}s for: {b.get('vo', '')}{flag}")
    if endcard:
        ec = kit / "99_endcard.mp4"
        ff("-loop", "1", "-i", endcard, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{end_sec}",
           "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:white,fps=30,format=yuv420p",
           "-c:v", "libx264", "-crf", "17", "-c:a", "aac", "-shortest", str(ec))
        parts.append(ec); order.append(f"{ec.name} <- {endcard}")
    lst = kit / "_list.txt"; lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
    picture = kit / "_picture.mp4"
    ff("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(picture))
    ass = kit / "captions.ass"
    if caps:
        ccfg = dict(plan.get("caption") or {})
        ccfg.setdefault("margin_v", R["caption_margin_v"]); ccfg.setdefault("hook_margin_v", R["hook_margin_v"])
        if plan.get("hook_text"):
            ccfg["hook_text"] = plan["hook_text"]; ccfg.setdefault("hook_end", beats[0].get("vo_end", 3.0) + 0.3)
        captions(json.loads((proj / "VO" / "alignment.json").read_text()), ass, cfg=ccfg)
    master = proj / "MASTER.mp4"
    total = dur(picture)
    ins, fa, fv, mix = ["-i", picture.name, "-i", str(vo)], [], [], ["[0:a]", "[v1]"]
    checks = ["## Edit checks (course rules, knowledge/video-editing-course/EDITING_KB.md)"]
    if music:
        # C003 drop on the hold: shift the bed so its drop lands where beat hold_beat starts
        hold_n = plan.get("hold_beat", beats[1]["n"] if len(beats) > 1 else beats[0]["n"]); hold_t = win.get(hold_n, (0, 0))[0]
        drop = drop if drop is not None else plan.get("music_drop_at")
        if drop == "auto": drop = RE.find_drop(music)
        lead = 0.0
        if drop not in (None, "none"):
            st = float(drop) - hold_t
            if st >= 0:
                ins += ["-ss", f"{st:.3f}"]
                checks.append(f"- music drop: track {float(drop):.1f}s lands at {hold_t:.1f}s (start of beat {hold_n}, the hold)")
            else:   # never put silence under the hook: start the track at 0 and say where its drop falls
                checks.append(f"- music drop: track drop {float(drop):.1f}s is earlier than the hold ({hold_t:.1f}s); track starts at 0 (pick a track with a later drop to land it)")
        ins += ["-stream_loop", "-1", "-i", str(music)]
        mf = [f"adelay={int(lead * 1000)}:all=1"] if lead else []
        mf += [f"atrim=0:{total:.3f}", "asetpts=N/SR/TB"]
        if R.get("music_eq"):
            hz, q, g = R["music_eq"]; mf.append(f"equalizer=f={hz}:t=q:w={q}:g={g}")   # C005 notch where speech sits
        stops = [win[n] for n in plan.get("music_stops") or [] if n in win]
        if stops:   # C007 music drops out completely under the line that must land
            mf.append("volume='" + "*".join(f"(clip(({a:.3f}-t)/0.08,0,1)+clip((t-{e:.3f})/0.25,0,1))" for a, e in stops) + "':eval=frame")
            checks.append(f"- music stops under beats {plan['music_stops']}")
        mf += [f"afade=t=in:d={0.3 if drop not in (None, 'none') else 0.8}", f"afade=t=out:st={max(0.0, total - 1.5):.3f}:d=1.5", f"volume={music_db}dB"]
        fa.append(f"[2:a]{','.join(mf)}[m]")
        fa.append("[1:a]asplit=2[v1][v2]"); fa.append("[m][v2]sidechaincompress=threshold=0.03:ratio=4:attack=5:release=400[md]"); mix.append("[md]")
    else:
        mix = ["[0:a]", "[1:a]"]
    nxt = len([x for x in ins if x == "-i"])
    hook = plan.get("hook_card")
    if hook:   # C009 native hook box on screen from frame one, no animation
        png, hw, hh = RE.hook_png(hook, kit / "hook_card.png", R)
        b1 = win[beats[0]["n"]]; hd = min(max(plan.get("hook_secs") or (b1[1] - b1[0]), 3.0), 5.0)
        ins += ["-loop", "1", "-i", str(png)]
        fv.append(f"[0:v][{nxt}:v]overlay=x=(W-w)/2:y={R['hook_y']}:enable='lt(t,{hd:.3f})'[vh]"); nxt += 1
        top, side = RE.SAFE["top"] * 1920, RE.SAFE["side"] * 1080; cap_top = 1920 - ccfg_margin(plan, R) - 2 * 95
        ok = R["hook_y"] >= top and R["hook_y"] + hh <= cap_top and (1080 - hw) / 2 >= side
        checks.append(f"- hook box: {hw}x{hh} at y {R['hook_y']}-{R['hook_y'] + hh}, 0-{hd:.1f}s from frame one -> {'ok' if ok else '!! overlaps the top band, captions or side margin'}")
        if plan.get("hook_text"): checks.append("- !! hook_card and hook_text both set: two hook texts on screen")
    vin = "[vh]" if hook else "[0:v]"
    if caps: fv.append(f"{vin}subtitles={ass.name}[vout]"); vin = "[vout]"
    for k, (t, f, db) in enumerate(sfx_cues(plan, win)):   # C011 one SFX per visible event
        ins += ["-i", str(f)]; fa.append(f"[{nxt}:a]aresample=48000,volume={db}dB,adelay={int(t * 1000)}:all=1[s{k}]"); mix.append(f"[s{k}]"); nxt += 1
        checks.append(f"- sfx {f.stem} at {t:.2f}s")
    fa.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:dropout_transition=0:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    cmd = [*ins, "-filter_complex", ";".join(fv + fa), "-map", vin if vin != "[0:v]" else "0:v", "-map", "[a]", "-t", f"{total:.3f}",
           "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(master)]
    subprocess.run(["ffmpeg", "-v", "error", "-y", *cmd], check=True, cwd=kit)
    # course checks: safe zone, long single shots, black head/tail
    mv = ccfg_margin(plan, R); bot, top = 1920 - mv, 1920 - mv - 2 * 95
    checks.append(f"- captions: y {top}-{bot} vs safe {RE.SAFE['top'] * 1920:.0f}-{(1 - RE.SAFE['bottom']) * 1920:.0f} -> "
                  + ("ok" if bot <= (1 - RE.SAFE["bottom"]) * 1920 else f"!! bottom inside Meta's bottom UI band (caption.margin_v {mv}; 700 = safe)"))
    if plan.get("hook_text"):
        hm = (plan.get("caption") or {}).get("hook_margin_v", R["hook_margin_v"])
        checks.append(f"- hook line top at y {hm} -> {'ok' if hm >= RE.SAFE['top'] * 1920 else '!! inside the top UI band'}")
    long = [(n, e - s0) for n, (s0, e) in win.items() if e - s0 > R["max_static"]]
    checks.append("- shot length: " + ("every beat changes picture within %.1f s" % R["max_static"] if not long else
                  "note (C002, a visual change every 2-3 s): " + ", ".join(f"beat {n} {d:.1f}s" for n, d in long) + " - fine if the clip moves a lot, else split it"))
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(master), "-vf", "blackdetect=d=0.05:pix_th=0.08", "-an", "-f", "null", "-"], capture_output=True, text=True)
    bl = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", r.stderr)]
    md = dur(master); edge = [x for x in bl if x[0] < 0.05 or x[1] > md - 0.1]
    checks.append("- black frames at head/tail: " + ("none" if not edge else "!! " + ", ".join(f"{a:.2f}-{b:.2f}s" for a, b in edge)))
    if plan.get("music_pick"): checks.append(f"- music: {plan['music_pick'].get('title')} ({plan['music_pick'].get('kind')}, mood {plan.get('music_mood')})")
    (kit / "EDIT_CHECKS.md").write_text("\n".join(checks) + "\n"); print("\n".join(checks))
    subprocess.run(["cp", str(vo), str(kit / "vo.mp3")])
    lst.unlink(); picture.unlink()
    (kit / "ORDER.txt").write_text("\n".join(order) + "\n")
    print(f"MASTER {master} {dur(master):.2f}s"); print("\n".join(order))


if __name__ == "__main__":
    main()
