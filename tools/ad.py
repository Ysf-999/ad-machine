"""One-command stage machine for an animated ad. All state lives in <project>/plan.json + jobs.jsonl.

Usage:
  ad.py <project> status                      what is done / missing per beat
  ad.py <project> voice "<description>"       ElevenLabs Voice Design: 3 previews of the script in VO/ (listen)
  ad.py <project> voice-pick <1|2|3>          keep that preview as the ad's voice (sets plan.voice_id)
  ad.py <project> vo                          render the ElevenLabs voiceover, cut pauses, beat timings + clip durations
  ad.py <project> frames [--only 3,7]         keyframes via gen_scenes consistency chain (skips existing)
  ad.py <project> clips  [--only 3,7] [--workers 5]   Kling clips for every beat with a frame (skips existing)
  ad.py <project> qc     [--stage frames|clips|all]   cheap vision QC -> QC/qc_report.md (needs ANTHROPIC_API_KEY)
  ad.py <project> review                      build + open REVIEW.html
  ad.py <project> redo   <beat> frame|clip ["note"] [--fresh]   new version for that beat. A frame redo with a note
                                              EDITS the current frame (only the note changes); --fresh, no note, or a
                                              3rd round re-rolls it from the masters instead
  ad.py <project> notes [file]                log the review notes you copied from REVIEW.html (clipboard, or a file) and print the redo commands
  ad.py <project> redo-failed [--stage frames|clips] [--go]   list (default) or run redo for every item the last QC marked FAIL
  ad.py <project> lock | unlock               mark a launched/approved ad: redo, redo-failed, vo, frames, clips refuse to touch it (use --force to override)
  ad.py <project> rules                       print the learned rules (universal + this ad's skill): read before producing an ad
  ad.py <project> music "<style>" [--seconds N]   Suno instrumental bed -> VO/music.mp3 (plan.music, plan.music_db default -22) COSTS CREDITS
                                     free instead: plan.music_mood "sad" (+ music_kind trendy|popular|library) -> stitch picks from
                                     library/music (tools/music_lib.py list); drop lands on hold_beat, music_stops, sfx_cues, hook_card
  ad.py <project> stitch [--endcard <image>]  assemble MASTER.mp4 (VO-led speed map, captions, music bed, end card)
  ad.py <project> masterqc                    strict Opus (effort medium) review of MASTER.mp4 -> QC/master_qc.md (text only)
  ad.py <project> soundoff ["HOOK LINE"]      muted Stories/Reels cut: hook box from frame one + caption coverage check ->
                                              MASTER-soundoff.mp4 + QC/soundoff_checks.md (never touches MASTER; ok on locked ads)
  ad.py <project> all                         vo -> frames -> clips -> qc -> review
  ad.py <project> promote <beat> clip|frame <lib_id> ["note"] [--force]   save the approved asset to library/
  ad.py <project> realign                     re-time VO/alignment.json + beat windows from Whisper on vo.mp3 (vo does this itself)
  ad.py <project> library                     list the approved-asset library

Beat fields used: n, vo, visual, camera, sfx, refs (master keys), optional voice_id (+voice_settings) for dialogue ads
(each beat rendered with its own voice), optional end_visual (makes a start+end clip),
optional motion (one-sentence action), optional frame_note / clip_note (appended to prompts on redo),
optional vo_take_file (VO/<name>: use that .mp3 + .json alignment as this voice-run's take instead of TTS; set vo_break on it),
optional lib (library id: reuse an approved clip/frame instead of generating), duration (set by `vo` unless
you set it yourself). Plan field vo_max_gap (default 0.15 s single-voice, null for dialogue ads = keep pauses; cutting pauses makes abrupt sentence onsets).
"""
import json, math, os, pathlib, shutil, subprocess, sys, re, datetime
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import kie

def _load_env():
    """Put the repo .env keys (ANTHROPIC_API_KEY, ELEVENLABS_API_KEY, KIE_API_KEY) into os.environ if missing."""
    f = pathlib.Path(__file__).resolve().parent.parent / ".env"
    if f.exists():
        for l in f.read_text().splitlines():
            if "=" in l and not l.startswith("#"):
                k, v = l.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
_load_env()
import os

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
TOOLS = ROOT / "tools"
LIB = ROOT / "library"


def load(proj):
    return json.loads((proj / "plan.json").read_text())


def save(proj, plan):
    (proj / "plan.json").write_text(json.dumps(plan, indent=2))


def run(*cmd, **kw):
    print("$", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def latest(d, stem, ext):
    c = [p for p in d.glob(f"{stem}*{ext}") if re.fullmatch(rf"{stem}(_v\d+)?", p.stem)]
    return max(c, key=lambda p: int(p.stem.rsplit("_v", 1)[1]) if "_v" in p.stem else 1) if c else None


def next_version(d, stem, ext):
    cur = latest(d, stem, ext)
    if not cur:
        return stem
    v = int(cur.stem.rsplit("_v", 1)[1]) if "_v" in cur.stem else 1
    return f"{stem}_v{v + 1}"


def parse_only(a):
    return {int(x) for x in a[a.index("--only") + 1].split(",")} if "--only" in a else None


# ---------- approved-asset library (reuse proven clips/frames across ads instead of regenerating) ----------
def lib_index():
    f = LIB / "index.json"
    return json.loads(f.read_text()) if f.exists() else {}


def style_group(s):
    """claymation / pixar-3d / cartoon-2d / diorama / ai-realistic from a plan.style or library style string (owner 2026-11-09: animated b-roll is reused only inside its own style)."""
    s = (s or "").lower()
    for key, g in (("clay", "claymation"), ("aardman", "claymation"), ("pixar", "pixar-3d"), ("flat 2d", "cartoon-2d"),
                   ("cartoon-2d", "cartoon-2d"), ("diorama", "diorama"), ("ai-realistic", "ai-realistic")):
        if key in s:
            return g
    return None


def lib_style_check(plan, e, beat):
    pg, eg = style_group(plan.get("style")), style_group(e.get("style"))
    if pg and eg and pg != eg:
        sys.exit(f"beat {beat['n']}: library clip {beat['lib']!r} is {eg} but this ad is {pg}. Animated b-roll is reused only inside its own style (owner rule).")


def lib_entry(b):
    if not b.get("lib"):
        return None
    e = lib_index().get(b["lib"])
    if not e:
        sys.exit(f"beat {b['n']}: library id {b['lib']!r} not found (see: ad.py <project> library)")
    return e


# ---------- stages ----------
def status(proj, plan):
    print(f"{plan.get('ad')}  style={plan.get('style')}  vo={'yes' if (proj/'VO'/'vo.mp3').exists() else 'no'}")
    for b in plan["beats"]:
        n = b["n"]
        fr = latest(proj / "FRAMES", f"scene_{n:02d}", ".png")
        cl = latest(proj / "CLIPS", f"clip_{n:02d}", ".mp4")
        lib = f"  lib={b['lib']}" if b.get("lib") else ""
        print(f"  beat {n:2d}  frame={fr.name if fr else '-':22s} clip={cl.name if cl else '-':18s} vo={b.get('vo_start','?')}-{b.get('vo_end','?')}  dur={b.get('duration', 5)}s{lib}")
    if (proj / "MASTER.mp4").exists():
        print("  MASTER.mp4 present")


def _tts(key, voice, text, settings, prev=None, nxt=None):
    import base64, httpx
    body = {"text": text, "model_id": "eleven_multilingual_v2", "voice_settings": settings}
    if prev: body["previous_text"] = prev[-300:]
    if nxt: body["next_text"] = nxt[:300]
    r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps", params={"output_format": "mp3_44100_128"},
                   headers={"xi-api-key": key}, json=body, timeout=120)
    r.raise_for_status(); j = r.json()
    return base64.b64decode(j["audio_base64"]), j["alignment"]


def _edges(f, thresh="-45dB"):
    """(first_sound, last_sound) seconds of an audio file via silencedetect; (0, duration) if nothing detected."""
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)], capture_output=True, text=True).stdout)
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(f), "-af", f"silencedetect=n={thresh}:d=0.04", "-f", "null", "-"], capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r)]
    first = ends[0] if starts and starts[0] < 0.02 and ends else 0.0
    last = starts[-1] if starts and (not ends or starts[-1] > ends[-1]) else d
    return first, last, d


def vo(proj, plan):
    if plan.get("song"):
        sys.exit("song ad: VO/vo.mp3 is the song. Timing comes from tools/song_plan.py, never from vo.")
    key = os.environ.get("ELEVENLABS_API_KEY") or next((l.split("=", 1)[1].strip() for l in (ROOT / ".env").read_text().splitlines() if l.startswith("ELEVENLABS_API_KEY=")), None)
    voice = plan.get("voice_id")
    if not voice:  # Camilo: a designed voice beats any stock voice. `voice` needs a paid ElevenLabs plan (API voice creation)
        voice = "cgSgspJ2msm6clMCkdW9"
        print(f'  ! no voice_id in plan.json: using stock voice {voice}. Better: ad.py <project> voice "<description>" '
              f'then voice-pick <n>, or set voice_id to a shared-library voice that fits the avatar')
    settings = plan.get("voice_settings") or {"stability": 0.45, "similarity_boost": 0.75, "style": 0.3, "use_speaker_boost": True}
    (proj / "VO").mkdir(exist_ok=True)
    multi = any(b.get("voice_id") for b in plan["beats"])
    if not multi:
        script = plan["script"] if "script" in plan else " ".join(b["vo"] for b in plan["beats"])
        audio, al = _tts(key, voice, script, settings)
        (proj / "VO" / "vo_raw.mp3").write_bytes(audio)
    else:
        # dialogue ads: each beat may name its own voice_id (+voice_settings). Consecutive beats in the same voice are
        # rendered as ONE take (natural flow, one prosody; the per-beat timings come from the character alignment),
        # takes are trimmed of leading/trailing silence, joined on WAV with a short gap, and the alignment is shifted
        # onto the joined timeline. Takes are cached in VO/grp_XX.* by voice + text (re-render: delete the files).
        groups = []
        in_take = False  # a supplied take (vo_take_file, e.g. a hook variant's untouched body) covers ALL following beats, whatever their voices
        for b in plan["beats"]:
            v = b.get("voice_id") or voice
            if b.get("vo_take_file"):
                groups.append((v, [b])); in_take = True
            elif in_take or (groups and groups[-1][0] == v and not b.get("vo_break")):
                groups[-1][1].append(b)
            else:
                groups.append((v, [b]))
        texts = [" ".join(b["vo"] for b in bs) for _, bs in groups]
        chars, st, en, t, takes = [], [], [], 0.0, []
        gap = plan.get("vo_segment_gap", 0.3)
        for gi, (v, bs) in enumerate(groups):
            text = texts[gi]
            f = proj / "VO" / f"grp_{bs[0]['n']:02d}.mp3"; meta = f.with_suffix(".json")
            if bs[0].get("vo_take_file"):  # a take supplied as audio + alignment (e.g. the untouched body of a hook variant)
                f = proj / (bs[0]["vo_take_file"] + ".mp3"); meta = f.with_suffix(".json")
            cached = json.loads(meta.read_text()) if meta.exists() else {}
            if bs[0].get("vo_take_file"):
                a = cached["alignment"]
                assert cached.get("text") == text, f"take file {f.name} text differs from the beats' vo (did a body beat change?)"
            elif f.exists() and cached.get("voice") == v and cached.get("text") == text:
                a = cached["alignment"]  # unchanged take: reuse (saves ElevenLabs characters)
            else:
                a_prev = texts[gi - 1] if gi else None; a_next = texts[gi + 1] if gi + 1 < len(groups) else None
                audio, a = _tts(key, v, text, bs[0].get("voice_settings") or settings, a_prev, a_next)
                f.write_bytes(audio); meta.write_text(json.dumps({"voice": v, "text": text, "alignment": a}))
                print(f"  take grp_{bs[0]['n']:02d}: {len(text)} chars, voice {v[:6]}", flush=True)
            first, last, d = _edges(f)
            # silence detection at -45 dB counts breaths/room noise after the last word as "sound": cap the end at the
            # aligned end of the last character (+0.12 s) so hook-to-body joins don't carry a ~1 s gap (Oct 28)
            if not bs[0].get("vo_take_file") and a.get("character_end_times_seconds"):
                last = min(last, a["character_end_times_seconds"][-1] + 0.12)
            # smooth joins (owner note 10/27: "sharp cut at the start of a sentence"): keep room tone before the first
            # sound and after the last, fade it in/out over tens of ms, and leave a real gap between takes
            lead, tail = plan.get("vo_take_lead", 0.15), plan.get("vo_take_tail", 0.18)
            s0, e0 = max(0.0, first - lead), min(d, last + tail)
            # a take that starts speaking at once has no room tone to fade: pad silence in front instead, so the fade
            # never lands on the first word (hw6-h2: the fade-in was eating the first syllable)
            pad = max(0.0, lead - (first - s0))
            fade_in = min(0.08, max(0.0, first - s0 - 0.01)) if pad == 0 else 0.0
            wav = f.with_name(f.stem + "_trim.wav")
            af = f"atrim={s0:.3f}:{e0:.3f},asetpts=N/SR/TB" + (f",afade=t=in:d={fade_in:.3f}" if fade_in > 0.005 else "") + \
                 f",afade=t=out:st={max(0.0, e0 - s0 - 0.12):.3f}:d=0.12" + (f",adelay={int(pad * 1000)}:all=1" if pad > 0.005 else "")
            run("ffmpeg", "-v", "error", "-y", "-i", f, "-af", af, "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", wav)
            s0 -= pad  # alignment: audio now starts `pad` before s0
            if chars:
                chars.append(" "); st.append(round(t - gap / 2, 3)); en.append(round(t - gap / 2, 3))
            clamp = lambda x: round(min(max(x - s0, 0.0), e0 - s0) + t, 3)
            chars += a["characters"]; st += [clamp(x) for x in a["character_start_times_seconds"]]; en += [clamp(x) for x in a["character_end_times_seconds"]]
            takes.append((wav, e0 - s0)); t += (e0 - s0) + gap
        lst = proj / "VO" / "_segs.txt"
        padded = []
        for k, (wav, d) in enumerate(takes):
            pf = wav.with_name(wav.stem.replace("_trim", "") + "_pad.wav")
            g2 = gap if k < len(takes) - 1 else 0.0  # no silence after the LAST take (it made the closing shot hold too long)
            run("ffmpeg", "-v", "error", "-y", "-i", wav, "-af", f"apad=pad_dur={g2}", "-t", f"{d + g2:.3f}", "-c:a", "pcm_s16le", pf); padded.append(pf)
        lst.write_text("".join(f"file '{pf.name}'\n" for pf in padded))
        run("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c:a", "pcm_s16le", proj / "VO" / "vo_raw.wav")
        run("ffmpeg", "-v", "error", "-y", "-i", proj / "VO" / "vo_raw.wav", "-c:a", "libmp3lame", "-b:a", "128k", proj / "VO" / "vo_raw.mp3")
        al = {"characters": chars, "character_start_times_seconds": st, "character_end_times_seconds": en}
        print(f"  multi-voice VO: {len(groups)} takes from {len(plan['beats'])} beats, {len({v for v, _ in groups})} voices")
    (proj / "VO" / "alignment_raw.json").write_text(json.dumps(al))
    al, cut = tighten_vo(proj, al, plan.get("vo_max_gap", None if multi else 0.15))
    (proj / "VO" / "alignment.json").write_text(json.dumps(al))
    text, st, en = "".join(al["characters"]), al["character_start_times_seconds"], al["character_end_times_seconds"]
    pos = 0
    for b in plan["beats"]:
        i = text.find(b["vo"], pos)
        if i < 0:
            sys.exit(f"beat {b['n']} vo text not found in script: {b['vo']!r}")
        j2 = i + len(b["vo"]) - 1; pos = j2
        b["vo_start"], b["vo_end"] = round(st[i], 2), round(en[j2], 2)
    set_durations(plan, en[-1])
    save(proj, plan); print(f"VO {en[-1]:.2f}s ({cut:.2f}s of pauses cut), timings + clip durations saved")
    # ElevenLabs timestamps drift from the real audio (0.3-1.0 s late by the end of a 50 s read): re-time the map
    # from Whisper on the finished vo.mp3 so captions and cuts land on the words. Never skip this.
    realign(proj, plan)


def realign(proj, plan):
    subprocess.run([PY, "-I", str(TOOLS / "realign_vo.py"), str(proj)], check=True)
    plan.clear(); plan.update(load(proj))


def voice(proj, plan, description):
    import voice_design
    script = plan["script"] if "script" in plan else " ".join(b["vo"] for b in plan["beats"])
    plan["voice_description"] = description; save(proj, plan)
    voice_design.design(proj / "VO", description, script[:1000] if len(script) >= 100 else None)


def voice_pick(proj, plan, n):
    import voice_design
    plan["voice_id"] = voice_design.pick(proj / "VO", n, f"{proj.name} v{n}")
    save(proj, plan); print("voice_id saved to plan.json; next: ad.py <project> vo")


def tighten_vo(proj, al, max_gap):
    """Cut every pause between words down to max_gap seconds (Camilo: cut even half-second pauses).
    Writes VO/vo.mp3 from VO/vo_raw.wav (or vo_raw.mp3) and returns the alignment shifted to the new timeline.
    Cuts are made on PCM with a 6 ms crossfade so nothing clicks and no word onset is clipped."""
    raw_wav, raw, out = proj / "VO" / "vo_raw.wav", proj / "VO" / "vo_raw.mp3", proj / "VO" / "vo.mp3"
    chars, st, en = al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]
    words, inword = [], False
    for c, s, e in zip(chars, st, en):
        if c.isspace():
            inword = False; continue
        if not inword:
            words.append([s, e]); inword = True
        else:
            words[-1][1] = e
    cuts = [] if max_gap is None else [(round(e0 + max_gap / 2, 3), round(s1 - max_gap / 2, 3))
                                      for (_, e0), (s1, _) in zip(words, words[1:]) if s1 - e0 > max_gap + 0.05]
    if not cuts:
        if raw_wav.exists():
            run("ffmpeg", "-v", "error", "-y", "-i", raw_wav, "-c:a", "libmp3lame", "-b:a", "128k", out)
        else:
            shutil.copyfile(raw, out)
        return al, 0.0
    src = raw_wav if raw_wav.exists() else raw
    try:
        import numpy as np, wave, io
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-ar", "44100", "-ac", "1", "-f", "s16le", "-"], capture_output=True, check=True).stdout
        x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32); sr = 44100; xf = int(0.006 * sr)
        keep, pos = [], 0.0
        for a_, b_ in cuts:
            keep.append((pos, a_)); pos = b_
        keep.append((pos, len(x) / sr))
        outp = np.zeros(0, dtype=np.float32)
        for a_, b_ in keep:
            seg = x[int(a_ * sr):int(b_ * sr)]
            if len(outp) and len(seg) > xf and len(outp) > xf:
                ramp = np.linspace(0, 1, xf, dtype=np.float32)
                outp[-xf:] = outp[-xf:] * (1 - ramp) + seg[:xf] * ramp; seg = seg[xf:]
            outp = np.concatenate([outp, seg])
        tmp = proj / "VO" / "vo_tight.wav"
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(np.clip(outp, -32768, 32767).astype(np.int16).tobytes())
        run("ffmpeg", "-v", "error", "-y", "-i", tmp, "-c:a", "libmp3lame", "-b:a", "128k", out)
    except ImportError:
        expr = "+".join(f"between(t,{a},{b})" for a, b in cuts)
        run("ffmpeg", "-v", "error", "-y", "-i", src, "-af", f"aselect='not({expr})',asetpts=N/SR/TB",
            "-c:a", "libmp3lame", "-b:a", "128k", out)
    shift = lambda t: round(t - sum(min(max(0.0, t - a), b - a) for a, b in cuts), 3)
    return ({"characters": chars, "character_start_times_seconds": [shift(t) for t in st],
             "character_end_times_seconds": [shift(t) for t in en]}, sum(b - a for a, b in cuts))


def set_durations(plan, vo_len):
    """Clip length follows the VO (Camilo: 3-5 s of audio = 1 clip, 6-9 s = 2 clips; Boris: short clips drift less).
    Each beat's on-screen window = its vo_start to the next beat's vo_start (what assemble_anim fills).
    The clip gets ~30% headroom so it plays at ~1.0-1.3x, never shorter than the window (no frozen frame)."""
    beats = plan["beats"]
    for i, b in enumerate(beats):
        start = 0.0 if i == 0 else b["vo_start"]
        end = beats[i + 1]["vo_start"] if i + 1 < len(beats) else vo_len + 0.3
        window = end - start
        if "duration" not in b or b.get("duration_auto"):
            b["duration"] = max(3, min(15, math.ceil(window * 1.3))); b["duration_auto"] = True
        if window > 5.5 and not b.get("lib"):
            print(f"  ! beat {b['n']}: {window:.1f}s on screen in one clip. Consider splitting it into 2 beats "
                  f"(one action per clip drifts less)")


def frames(proj, plan, only=None):
    # gen_scenes handles the master + last-4 chain; --only means we redo specific beats by bumping versions
    if only:
        for n in only:
            redo(proj, plan, n, "frame", None)
        return
    run(PY, "-I", TOOLS / "gen_scenes.py", proj)


def clip_body(proj, plan, b, frame_path, end_path=None):
    cam = b.get("camera", "Static camera, locked-off tripod, completely still")
    if cam.lower().startswith("static"):
        cam = "Static camera, locked-off tripod, completely still"
    act = b.get("motion") or b["visual"]
    sfx = b.get("sfx", "subtle ambient")
    note = (" " + b["clip_note"]) if b.get("clip_note") else ""
    # Camilo's claymation SOP: without this line Kling often holds still for the first second
    style = "The animation starts at the very first frame. " + plan.get("clip_style_tail", "Handmade stop-motion clay animation throughout, non-CGI, non-cinematic.")
    if end_path:
        p = f"Smooth seamless transition between the first frame and the last frame. {act}. Keep every character and the product exactly the same size and shape throughout.{note} Non-verbal background sound effects only ({sfx}), never spoken aloud. No music. No dialogue. No talking. No words in the audio. {style}"
        imgs = [kie.upload(str(frame_path)), kie.upload(str(end_path))]
    else:
        p = f"Keep character facial consistency, no character redesign, no facial feature changes. Keep the product exactly the same size and shape as in the image. {cam}. {act}.{note} Non-verbal background sound effects only ({sfx}), never spoken aloud. No music. No dialogue. No talking. No words in the audio. {style}"
        imgs = [kie.upload(str(frame_path))]
    return {"model": "kling-3.0/video", "input": {"prompt": p, "image_urls": imgs, "sound": True, "duration": str(b.get("duration", 5)), "mode": plan.get("kling_mode", "std"), "multi_shots": False}}


def clips(proj, plan, only=None, workers=5):
    args = []
    for b in plan["beats"]:
        n = b["n"]
        if only and n not in only:
            continue
        e = lib_entry(b)
        if e: lib_style_check(plan, e, b)
        if e and e["type"] == "clip":
            dest = proj / "CLIPS" / f"clip_{n:02d}.mp4"
            if only:
                print(f"beat {n}: uses library clip {b['lib']!r}; remove 'lib' from the beat to generate a new one")
            elif not latest(proj / "CLIPS", f"clip_{n:02d}", ".mp4"):
                shutil.copyfile(LIB / e["file"], dest); print(f"beat {n}: library clip {b['lib']} -> {dest.name}")
            continue
        key = f"clip_{n:02d}" if not only else next_version(proj / "CLIPS", f"clip_{n:02d}", ".mp4")
        if not only and latest(proj / "CLIPS", key, ".mp4"):
            continue
        fr = latest(proj / "FRAMES", f"scene_{n:02d}", ".png")
        if not fr:
            print(f"beat {n}: no frame yet, skipping"); continue
        end = latest(proj / "FRAMES", f"scene_{n:02d}_end", ".png")
        body = clip_body(proj, plan, b, fr, end)
        req = proj / "CLIPS" / f"{key}_req.json"; req.write_text(json.dumps(body, indent=1)); args.append(f"{key}={req}")
    if not args:
        print("nothing to generate"); return
    run(PY, "-I", TOOLS / "batch.py", proj / "jobs.jsonl", proj / "CLIPS", *args, "--workers", str(workers))


def redo(proj, plan, n, what, note, fresh=False):
    b = next(x for x in plan["beats"] if x["n"] == n)
    if b.get("lib"):
        sys.exit(f"beat {n} uses library asset {b['lib']!r}; remove 'lib' from the beat to generate a new one")
    if note:
        b["frame_note" if what == "frame" else "clip_note"] = note
        save(proj, plan)
    if what == "frame":
        cur = latest(proj / "FRAMES", f"scene_{n:02d}", ".png")
        key = next_version(proj / "FRAMES", f"scene_{n:02d}", ".png")
        masters = plan.get("masters", {})
        refs = [kie.upload(str(proj / masters[m])) for m in b.get("refs", []) if m in masters]
        edits = b.get("frame_edits", 0)
        if cur and note and not fresh and edits < 2:
            # Camilo: fix a frame by editing it, not by re-rolling it. The current frame is image 1; only the note changes.
            prompt = (f"Edit image 1. Keep everything else exactly as it is: framing, camera angle, lighting, background, "
                      f"characters, product, colours and style. Change only this: {note} {plan.get('lock','')}")
            refs = [kie.upload(str(cur))] + refs
            b["frame_edits"] = edits + 1
            print(f"beat {n}: editing {cur.name} (edit round {edits + 1}/2)")
        else:
            if cur and note and not fresh:
                print(f"beat {n}: 2 edit rounds used, re-rolling from the masters instead")
            # keep colour/style continuity: add the two neighbouring frames
            for m in (n - 1, n + 1):
                f = latest(proj / "FRAMES", f"scene_{m:02d}", ".png")
                if f: refs.append(kie.upload(str(f)))
            prompt = f"{b['visual']} {b.get('frame_note','')} {plan.get('style_tail','')} The characters and props must match the reference images exactly. {plan.get('lock','')}"
            b["frame_edits"] = 0
        save(proj, plan)
        body = {"model": "nano-banana-pro", "input": {"prompt": prompt, "image_input": refs[:8], "aspect_ratio": "9:16", "resolution": "2K", "output_format": "png"}}
        kie.run(body, str(proj / "jobs.jsonl"), key, str(proj / "FRAMES"))
        if latest(proj / "FRAMES", f"scene_{n:02d}_end", ".png"):
            print(f"beat {n}: has an end frame made from the old start frame; redo it too if the change affects it")
    else:
        clips(proj, plan, only={n})


def promote(proj, plan, n, what, lib_id, note, force=False):
    """Copy the latest approved clip/frame of a beat into library/ so later ads can reuse it via beat 'lib'."""
    b = next(x for x in plan["beats"] if x["n"] == n)
    src = (latest(proj / "CLIPS", f"clip_{n:02d}", ".mp4") if what == "clip"
           else latest(proj / "FRAMES", f"scene_{n:02d}", ".png"))
    if not src:
        sys.exit(f"beat {n}: no {what} to promote")
    idx = lib_index()
    if lib_id in idx and not force:
        sys.exit(f"library id {lib_id!r} exists (use --force to replace)")
    rel = f"{what}s/{lib_id}{src.suffix}"
    (LIB / f"{what}s").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, LIB / rel)
    idx[lib_id] = {"type": what, "file": rel, "source": f"{proj.name} beat {n} {src.name}", "style": plan.get("style"),
                   "vo": b.get("vo"), "visual": b.get("visual"), "note": note or "",
                   "added": datetime.date.today().isoformat()}
    (LIB / "index.json").write_text(json.dumps(idx, indent=1))
    print(f"library: {lib_id} <- {src.name}")


def library():
    idx = lib_index()
    if not idx:
        print("library is empty (ad.py <project> promote <beat> clip|frame <id>)"); return
    for k, e in sorted(idx.items()):
        print(f"{k:28s} {e['type']:5s} {e.get('style') or '':10s} {e['source']:40s} {e.get('note','')}")


def qc(proj, plan, stage="all"):
    run(PY, "-I", TOOLS / "vision_qc.py", proj, "--stage", stage)


def review(proj, plan):
    run(PY, "-I", TOOLS / "review_page.py", proj)


def music(proj, plan, style, seconds=None):
    """Suno instrumental bed via tools/music.py -> VO/music.mp3, saved on plan['music']."""
    import music as mu
    secs = seconds or int(math.ceil((plan["beats"][-1].get("vo_end") or 45) + 5))
    files = mu.generate(proj / "VO" / "music.mp3", style, secs, f"{proj.name} bed", str(proj / "jobs.jsonl"), "music")
    plan["music"] = "VO/music.mp3"; plan["music_style"] = style; save(proj, plan)
    print("music saved; alt take in VO/music_alt.mp3. Set plan.music_db (default -22) to taste.")


def masterqc(proj, plan):
    run(PY, "-I", TOOLS / "master_qc.py", proj)


def soundoff(proj, plan, hook=None):
    subprocess.run([PY, "-I", str(TOOLS / "soundoff_cut.py"), str(proj), *(["--hook", hook] if hook else [])])


def stitch(proj, plan, endcard=None):
    if plan.get("build_script"):
        # 2026-11-22: a hand-built ad (own edit chain in tools_local/, e.g. footage swaps, split screens, script cards) names its
        # Python build driver here, so `stitch` (and the cloud's ai-finish / ai-revise) runs that chain instead of a bare
        # assemble. The script must end with its own caption sync check.
        script = (proj / plan["build_script"]).resolve()
        if proj.resolve() not in script.parents or script.suffix != ".py" or not script.is_file():
            sys.exit(f"build_script must be a .py file inside the project: {plan['build_script']}")
        run(PY, "-I", script, proj)
        import feedback as fb
        plan = load(proj); plan["skill"] = fb.skill_of(plan); plan["rules_version"] = fb.version(plan["skill"]); save(proj, plan)
        return
    cmd = [PY, "-I", TOOLS / "assemble_anim.py", proj]
    if "sfx_db" in plan:
        cmd += ["--sfx-db", str(plan["sfx_db"])]
    if endcard:
        cmd += ["--endcard", endcard, "--endcard-sec", "2.0"]
    if plan.get("music") and (proj / plan["music"]).exists():
        cmd += ["--music", str(proj / plan["music"]), "--music-db", str(plan.get("music_db", -22))]
        if plan.get("music_drop_at") is not None: cmd += ["--music-drop", str(plan["music_drop_at"])]
    elif plan.get("music_mood") and not plan.get("song"):   # free local library, no credits (tools/music_lib.py)
        import music_lib as ml
        beats = plan["beats"]; hold_n = plan.get("hold_beat", beats[1]["n"] if len(beats) > 1 else beats[0]["n"])
        hold_t = next((b["vo_start"] for b in beats if b["n"] == hold_n), 0.0)
        pk = ml.pick(plan["music_mood"], plan.get("music_kind", "any"), (beats[-1].get("vo_end") or 30) + 3, proj.name,
                     bool(plan.get("music_vocals")), hold_t)
        if pk:
            plan["music_pick"] = pk; save(proj, plan)
            print(f"music ({plan['music_mood']}): {pk['title']} [{pk['kind']}{', instrumental' if pk['instrumental'] else ''}] drop {pk['drop']}s")
            cmd += ["--music", pk["file"], "--music-db", str(plan.get("music_db", -22)), "--music-drop", str(plan.get("music_drop_at", pk["drop"]))]
    run(*cmd)
    import feedback as fb
    plan["skill"] = fb.skill_of(plan); plan["rules_version"] = fb.version(plan["skill"]); save(proj, plan)  # which rule set made this master
    subprocess.run([PY, "-I", str(TOOLS / "caption_sync_check.py"), str(proj)])  # prints PASS / !! FAIL; fix = realign + stitch


def notes(proj, plan, src=None):
    run(PY, "-I", TOOLS / "feedback.py", "ingest", proj, *([src] if src else []))


def rules(proj, plan):
    import feedback as fb
    fb.cmd_rules(fb.skill_of(plan))


def redo_failed(proj, plan, stage=None, go=False):
    """Every beat whose LATEST frame/clip QC verdict is FAIL. Skips library assets, beats in plan.approved_beats, and
    items newer than the QC report (stale verdict). Dry run unless --go. Re-run `qc` first so verdicts are current."""
    f = proj / "QC" / "qc_report.json"
    if not f.exists():
        sys.exit("no QC/qc_report.json; run `ad.py <project> qc` first")
    rep = {r["item"]: r for r in json.loads(f.read_text())}
    todo = []
    for b in plan["beats"]:
        n = b["n"]
        if b.get("lib"):
            continue
        for kind, d, ext, st in (("frame", "FRAMES", ".png", "frames"), ("clip", "CLIPS", ".mp4", "clips")):
            if stage and stage != st:
                continue
            cur = latest(proj / d, f"{'scene' if kind == 'frame' else 'clip'}_{n:02d}", ext)
            r = rep.get(cur.name) if cur else None
            if r and cur.stat().st_mtime > f.stat().st_mtime:
                continue  # file is newer than the QC report: the verdict belongs to an older version
            if n in plan.get("approved_beats", []):
                continue  # owner approved this beat; checker flags never override that
            if r and r.get("verdict") == "FAIL":
                todo.append((n, kind, cur.name, "; ".join(str(x)[:90] for x in r.get("defects", []))))
    if not todo:
        print("nothing marked FAIL on the latest versions"); return
    for n, kind, name, why in todo:
        print(f"{'REDO' if go else 'would redo'} beat {n} {kind} ({name}): {why}")
    if not go:
        print(f"\n{len(todo)} item(s). Re-run with --go to regenerate them (costs credits). Beats that use a library asset are skipped.")
        return
    for n, kind, name, why in todo:
        redo(proj, load(proj), n, kind, None)


def main():
    a = sys.argv[1:]
    if len(a) == 1 and a[0] == "library" or len(a) >= 2 and a[1] == "library":
        return library()
    proj = pathlib.Path(a[0]).resolve(); stage = a[1]; rest = a[2:]
    flags = {x for x in rest if x in ("--fresh", "--force", "--go")}
    pos = [x for x in rest if x not in flags]
    for d in ("FRAMES", "CLIPS", "VO", "EDIT_KIT", "QC"):
        (proj / d).mkdir(exist_ok=True)
    plan = load(proj)
    only = parse_only(rest)
    if plan.get("locked") and stage in ("vo", "frames", "clips", "redo", "redo-failed", "all", "stitch", "music", "realign", "promote") and "--force" not in rest:
        sys.exit(f"{proj.name} is LOCKED (launched/approved). Make a copy or a hook variant instead, or pass --force.")
    if stage == "status": status(proj, plan)
    elif stage == "voice": voice(proj, plan, pos[0])
    elif stage == "voice-pick": voice_pick(proj, plan, int(pos[0]))
    elif stage == "vo": vo(proj, plan)
    elif stage == "realign": realign(proj, plan)
    elif stage == "frames": frames(proj, plan, only)
    elif stage == "clips": clips(proj, plan, only, int(rest[rest.index("--workers") + 1]) if "--workers" in rest else 5)
    elif stage == "qc": qc(proj, plan, rest[rest.index("--stage") + 1] if "--stage" in rest else "all")
    elif stage == "review": review(proj, plan)
    elif stage == "redo": redo(proj, plan, int(pos[0]), pos[1], pos[2] if len(pos) > 2 else None, "--fresh" in flags)
    elif stage == "promote": promote(proj, plan, int(pos[0]), pos[1], pos[2], pos[3] if len(pos) > 3 else None, "--force" in flags)
    elif stage == "stitch": stitch(proj, plan, rest[rest.index("--endcard") + 1] if "--endcard" in rest else None)
    elif stage == "music": music(proj, plan, pos[0], int(rest[rest.index("--seconds") + 1]) if "--seconds" in rest else None)
    elif stage == "masterqc": masterqc(proj, plan)
    elif stage == "soundoff": soundoff(proj, plan, pos[0] if pos else None)
    elif stage in ("lock", "unlock"):
        plan["locked"] = stage == "lock"; save(proj, plan); print(f"{proj.name}: locked={plan['locked']}")
    elif stage == "notes": notes(proj, plan, pos[0] if pos else None)
    elif stage == "rules": rules(proj, plan)
    elif stage == "redo-failed": redo_failed(proj, plan, rest[rest.index("--stage") + 1] if "--stage" in rest else None, "--go" in rest)
    elif stage == "all":
        if not (proj / "VO" / "vo.mp3").exists(): vo(proj, plan)
        frames(proj, plan); clips(proj, plan); qc(proj, plan); review(proj, plan)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
