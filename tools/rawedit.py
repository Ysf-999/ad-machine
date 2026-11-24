"""Real-footage UGC editor: one creator take (a-roll) + b-roll from the BRoll / Footage library -> finished 9:16 ad.

The agent never watches video. Audio is the clock: Whisper gives every word a time, ffmpeg silencedetect gives every
pause, and every cut edge sits inside a silence (never on a word onset, never inside a word). Plan first, render second.

Usage (PY = .venv/bin/python, from the repo root):
  rawedit.py new <name> --aroll <fid|file-name-substring>      make projects/<name>, fetch the a-roll from Drive
  rawedit.py new <name> --vo <audio file>                       VOICEOVER mode: the voice is the clock, the picture is a free
                                                                shot timeline (plan.shots) of b-roll from anywhere
  rawedit.py <project> transcribe                               words + silences for the a-roll (cached per Drive id)
  rawedit.py <project> pack                                     TAKES.md: phrase view with word indices and gap sizes (+ mirror check)
  rawedit.py <project> mirror [--on|--off]                      re-run the backwards-text check on the a-roll, or force the a-roll flip
  rawedit.py <project> plan                                     keep ranges (plan.json) -> EDL with silence-anchored edges + audit
  rawedit.py <project> broll [--keywords]                       suggest b-roll per beat (writes beat.intent + beat.suggest): beat intent
                                                                (literal must-show + meaning) -> moment search -> rerank, from
                                                                tools/moments.py; --keywords = old INDEX keyword match
  rawedit.py <project> set-broll <beat> <clip|m:moment> [--in s] [--off s] [--dur s] [--split <clip2> [--split-in s]] [--flip] [--pip]
                                                                split = clip on top, clip2 below; pip = creator stays small on screen
  rawedit.py <project> storyboard                               STORYBOARD.html (one frame per beat + the line) and PLAN.md
  rawedit.py <project> render [--music <file>|mood:<mood> [--music-drop <s>|auto]] [--no-captions]   (or plan.music_mood)
                                                                segments (punch-ins) -> b-roll -> concat -> voice chain, music, sfx -> hook box, captions last
  rawedit.py <project> verify                                   seam re-transcribe, pops, caption sync, audio levels -> VERIFY.md
  rawedit.py <project> fcpxml                                   EDIT_KIT/<name>.fcpxml for Resolve / Premiere (File > Import > Timeline)
  rawedit.py <project> variant <new-name> [--keep "a-b[,c-d]"] [--hook-card "text"]
                                                                hook variant: same body; new opening (visual test) OR new hook text (message test)
  rawedit.py <project> status

plan.json (written by `new`, edited by hand or by the agent):
  keep   [[w0,w1], ...]  inclusive word-index ranges of the a-roll in play order. One range = one beat.
  beats  [{n, vo, broll:{fid,in,off,dur}|null, suggest:[...]}]  built by `plan`; broll chosen by the agent/owner
  hook_card  hook text, drawn as a rounded box from frame one for the hook beat (null = none); hook_style "box"|"ass"; hook_secs
  cta_beat   beat number (or "last") that gets the pre-CTA pause      hold_beat  where the music drop lands (default 2)
  music_stops [beat, ...] music cut out under these lines             sfx  [{"beat": n, "off": s, "kind": "pop", "db": -12, "lead": s}]
  beat keys  zoom (e.g. 1.12 emphasis), zoom_anchor [x, y], punch: false
  shots  (vo mode) [{"at": s, "src": path|INDEX key, "in": s, "speed": 1, "flip": false, "zoom": 1.0, "push": [1.0, 1.08],
          "anchor": [0.5, 0.5], "fit": "fill"|"blur"}]  each shot runs until the next one's "at"; `words` prints word times
  cards  [{"text": "...", "at": s, "dur": s, "style": "box"|"review"|"offer"|"dark", "y": 300}]  overlay cards (review quote,
          offer, guarantee), drawn like the hook box
  rules (captions) caption_font, caption_size, caption_upper, caption_max_words (default 3), caption_hold (s a card may stay
          after its last word; 0.7), caption_outline, caption_shadow   fonts in library/fonts
  rules  {max_pause, pad_in, pad_out, min_piece, caption_late, music_under_db, speed, punch_in, auto_punch, voice_chain,
          music_eq, cta_pause, max_static, caption_margin_v, hook_y, hook_tilt, hook_px}   (C-rules: feedback/RULES_raw-ugc-editor.md)
"""
import csv, html, json, math, os, pathlib, re, shutil, subprocess, sys, xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))   # vo_onsets (run with -I, so the script dir is not on the path)
from brand import BRAND
FOOT = ROOT / "footage"
RAW, TR = FOOT / "raw", FOOT / "transcripts"
INDEX = pathlib.Path(os.environ.get("FOOTAGE_INDEX") or ROOT / "footage" / "INDEX.csv")   # footage library catalogue
PY = sys.executable
SKILL = "raw-ugc-editor"
DEFAULT_RULES = {"max_pause": 0.45, "pad_in": 0.10, "pad_out": 0.15, "min_piece": 1.2, "caption_late": 0.06,
                 "music_under_db": 8, "speed": 1.0,
                 # course pass 2026-11-05 (Video Ads Mastery + Video Editing Breakdowns; knowledge/video-editing-course/)
                 "punch_in": 1.10,          # C001 alternate 100% / 110% on every a-roll jump cut (B06: min visible ~1.03-1.06, abrupt 1.12)
                 "voice_chain": True,       # C004 compressor + de-esser + limiter on the voice before loudness (B06, B09)
                 "music_eq": [1500, 4, -15],  # C005 notch the music where speech sits: centre Hz, Q, gain dB (B04, B05)
                 "cta_pause": 0.35,         # C008 extra beat of silence before the CTA beat (plan.cta_beat) (B03)
                 "max_static": 3.5,
                 "auto_punch": 2.8,         # C001b long a-roll pieces get a mid-line punch-in at a word gap every ~2.8 s (no cut: same take)         # C002 longest stretch with no visual change before plan/verify warn (A12, A06, B05)
                 "caption_margin_v": 640,   # T50: owner 11/22 #1213 "slightly lower but still in the center" (was 700); 640 is the value he then approved on Rug Cleaner v3 (bottom y=1280)
                 "hook_y": 300, "hook_tilt": 0, "hook_px": 58}   # C009 hook box: top inside the 14% top band, STRAIGHT (owner 11/12: never rotate text boxes)
SAFE = {"top": 285 / 1920, "bottom": 0.35, "side": 0.06}   # Meta Reels/Stories UI bands (A03 shows the zone; numbers from Meta's guide).
# top was 0.14 (y 269); raised 2026-11-14 to y 285 because Feed crops 9:16 to 4:5 (1080x1350 centred = y 285-1635), so
# anything above 285 is cut off there. Bottom (y 1248) and side (65 px) are already stricter than the 4:5 crop.
SFX_DIR = ROOT / "library" / "sfx"
FONTS = ROOT / "library" / "fonts"
W, H, FPS = 1080, 1920, 30
ENC = ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


# ---------- helpers ----------
def sh(*cmd, check=True, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, errors="replace", **kw)
    if check and r.returncode:
        sys.exit(f"command failed: {' '.join(str(c) for c in cmd[:6])} ...\n{r.stderr[-1500:]}")
    return r


def probe(f):
    """Duration and DISPLAY size (rotation applied) — phone clips report 1920x1080 for a vertical video."""
    j = json.loads(sh("ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,side_data_list", "-of", "json", f).stdout)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    rot = 0
    for sd in v.get("side_data_list", []):
        if "rotation" in sd: rot = int(sd["rotation"])
    w, h = v["width"], v["height"]
    if rot % 180: w, h = h, w
    return float(j["format"]["duration"]), w, h


def index_rows():
    if not INDEX.exists(): sys.exit(f"missing {INDEX}: put your footage catalogue CSV there or set FOOTAGE_INDEX")
    rows = list(csv.DictReader(open(INDEX)))
    for r in rows:
        r["fid"] = r["Link"].split("/d/")[1].split("/")[0]
        r["ext"] = pathlib.Path(r["New file name"]).suffix.lower() or ".mp4"
    return rows


EXTRA_INDEX = ROOT / "footage/moments/catalog_extra.csv"   # Drive clips `moments.py sync` catalogued that INDEX.csv lacks


def all_rows():
    """INDEX.csv plus the extra catalogue, for looking a clip up by id (set-broll m:<id>, fetch). Listing/search of the
    original library keeps using index_rows()."""
    rows = index_rows()
    if EXTRA_INDEX.exists():
        have = {r["fid"] for r in rows}
        for r in csv.DictReader(open(EXTRA_INDEX)):
            try:
                r["fid"] = r["Link"].split("/d/")[1].split("/")[0]
            except (KeyError, IndexError):
                continue
            r["ext"] = pathlib.Path(r.get("New file name") or "").suffix.lower() or ".mp4"
            if r["fid"] not in have:
                rows.append(r)
    return rows


def moment(key):
    """m:<fid10>@<start> -> the moment card from tools/moments.py (one described stretch of a library clip)."""
    import moments
    return moments.get_moment(key)


def find_row(rows, key):
    if key.startswith("m:"): key = moment(key)["fid"]
    hit = [r for r in rows if r["fid"] == key] or [r for r in rows if key.lower() in r["New file name"].lower()]
    if not hit: sys.exit(f"no INDEX row matches {key!r}")
    if len(hit) > 1 and hit[0]["fid"] != key:
        print("matches:"); [print("  ", r["New file name"]) for r in hit[:12]]; sys.exit("be more specific")
    return hit[0]


def fetch(row):
    RAW.mkdir(parents=True, exist_ok=True)
    f = RAW / f"{row['fid']}{row['ext']}"
    want = int(float(row["MB"]) * 1024 * 1024 * 0.9)
    if f.exists() and f.stat().st_size >= want: return f
    print(f"fetch {row['New file name']} ({row['MB']} MB)")
    for _ in range(3):
        sh("curl", "-sL", "--retry", "3", "-o", f, f"https://drive.usercontent.google.com/download?id={row['fid']}&export=download&confirm=t", check=False)
        if f.exists() and f.stat().st_size >= want: return f
    sys.exit(f"download failed for {row['New file name']}")


def load(proj):
    p = proj / "plan.json"
    if not p.exists(): sys.exit(f"no plan.json in {proj}")
    return json.loads(p.read_text())


def save(proj, plan):
    (proj / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False))


def fmt(t): return f"{t:6.2f}"


# ---------- transcribe ----------
def transcribe(fid, f, force=False):
    TR.mkdir(parents=True, exist_ok=True)
    wf, sf = TR / f"{fid}.words.json", TR / f"{fid}.silences.json"
    if not wf.exists() or force:
        import mlx_whisper
        print(f"whisper {f.name}")
        r = mlx_whisper.transcribe(str(f), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en",
                                   word_timestamps=True, initial_prompt=BRAND["transcribe_hint"],
                                   # skip words Whisper invents inside >1 s silences on long real takes (loops / repeats).
                                   # condition_on_previous_text stays on: turning it off drops the vocab prompt after 30 s.
                                   hallucination_silence_threshold=1.0)
        words = [{"i": 0, "w": w["word"].strip(), "start": round(w["start"], 3), "end": round(w["end"], 3)}
                 for s in r["segments"] for w in s.get("words", []) if w["word"].strip()]
        for i, w in enumerate(words): w["i"] = i
        wf.write_text(json.dumps({"fid": fid, "file": f.name, "text": r["text"].strip(), "words": words}, indent=0))
    if not sf.exists() or force:
        # adaptive threshold: room noise differs per creator. Pick the level whose silences cover the most word gaps >= 0.3 s.
        words = json.loads(wf.read_text())["words"]
        wgaps = [(words[i]["end"], words[i + 1]["start"]) for i in range(len(words) - 1) if words[i + 1]["start"] - words[i]["end"] >= 0.3]
        dur = probe(f)[0]; best = None
        for noise in (-38, -34, -30, -26, -22, -18):
            r = sh("ffmpeg", "-hide_banner", "-nostats", "-i", f, "-af", f"silencedetect=noise={noise}dB:d=0.12", "-f", "null", "-", check=False)
            st = [float(m) for m in re.findall(r"silence_start:\s*(-?[\d.]+)", r.stderr)]
            en = [float(m) for m in re.findall(r"silence_end:\s*(-?[\d.]+)", r.stderr)]
            sil = []
            for i, s in enumerate(st):
                e = en[i] if i < len(en) else dur
                if e > s: sil.append({"start": round(s, 3), "end": round(e, 3), "dur": round(e - s, 3)})
            cov = sum(1 for a, b in wgaps if any(x["start"] < b + 0.05 and x["end"] > a - 0.05 for x in sil))
            speech_lost = sum(1 for w in words if any(x["start"] < w["start"] + 0.05 and x["end"] > w["end"] - 0.05 for x in sil))
            score = cov - 2 * speech_lost
            if best is None or score > best[0]: best = (score, noise, sil, cov, speech_lost)
        print(f"silence threshold {best[1]} dB: {len(best[2])} silences, covers {best[3]}/{len(wgaps)} word gaps, {best[4]} words swallowed")
        sf.write_text(json.dumps({"noise_db": best[1], "silences": best[2]}))
    sil = json.loads(sf.read_text())
    if isinstance(sil, dict): sil = sil["silences"]
    return json.loads(wf.read_text()), sil


# ---------- pack ----------
def phrases(words, gap_break=0.35):
    out, cur = [], []
    for w in words:
        cur.append(w)
        nxt = words[w["i"] + 1] if w["i"] + 1 < len(words) else None
        gap = (nxt["start"] - w["end"]) if nxt else 9.9
        if re.search(r"[.!?,;:]$", w["w"]) or gap >= gap_break or nxt is None:
            out.append({"a": cur[0]["i"], "b": cur[-1]["i"], "start": cur[0]["start"], "end": cur[-1]["end"],
                        "text": " ".join(x["w"] for x in cur), "gap_after": round(gap, 2) if nxt else None})
            cur = []
    return out


def pack(proj, plan):
    tw, sil = transcribe(plan["aroll"]["fid"], RAW / plan["aroll"]["file"])
    ph = phrases(tw["words"])
    L = [f"# TAKES — {plan['ad']}", f"a-roll: {plan['aroll']['name']}  ({plan['aroll']['creator']}, {plan['aroll']['seconds']} s)",
         "", "One line per phrase. [w<first>-w<last>] = word indices for plan.json keep ranges. gap = silence after the phrase",
         "(>= 0.45 s is a clean cut point, 0.15-0.45 usable, < 0.15 mid-thought).", ""]
    for p in ph:
        g = p["gap_after"]
        tag = "" if g is None else ("CLEAN" if g >= 0.45 else "usable" if g >= 0.15 else "tight")
        L.append(f"[w{p['a']}-w{p['b']}] {fmt(p['start'])}-{fmt(p['end'])}  {p['text']}   (gap {g if g is not None else '-'} {tag})")
    L += ["", f"{len(tw['words'])} words, {len(ph)} phrases, {len(sil)} silences >= 0.12 s", "", "Full text:", tw["text"]]
    (proj / "TAKES.md").write_text("\n".join(L))
    print("\n".join(L[:len(L) - 3]))
    mirror_cmd(proj, plan)


# ---------- mirrored selfie takes ----------
def mirror_of(f, n=6, force=False):
    """Backwards-text check (tools/mirror_check.py, Apple Vision OCR as shot vs flipped), cached next to the transcripts."""
    cf = TR / f"{pathlib.Path(f).stem}.mirror.json"
    if cf.exists() and not force: return json.loads(cf.read_text())
    import mirror_check
    r = mirror_check.check(f, n); TR.mkdir(parents=True, exist_ok=True); cf.write_text(json.dumps(r)); return r


def mirror_cmd(proj, plan, force_flip=None):
    """Selfie takes are often mirrored (logo / packaging reads backwards). Flip only the takes that are. Sets aroll.flip
    automatically on a clear 'mirrored' verdict unless the flip was forced with --on/--off."""
    a = plan["aroll"]
    if force_flip is not None:
        a["flip"] = force_flip; a["flip_forced"] = True; save(proj, plan)
        print(f"a-roll flip forced {'ON' if force_flip else 'OFF'}"); return
    if plan.get("mode") == "vo": return
    r = mirror_of(RAW / a["file"]); a["mirror"] = r
    if r["verdict"] == "mirrored" and not a.get("flip_forced"):
        a["flip"] = True
        print(f"!! a-roll is MIRRORED (text reads right only when flipped: {r['words_flipped']}) -> aroll.flip = true, render will hflip it")
    else:
        print(f"mirror check: {r['verdict']} (as shot {r['score_as_shot']}, flipped {r['score_flipped']})"
              + ("" if r["verdict"] != "unclear" else " -> look at one frame or force with `mirror --on|--off`")
              + (f"  | aroll.flip = {a.get('flip', False)}" if a.get("flip") else ""))
    save(proj, plan)


# ---------- plan / EDL ----------
def edges(words, sil, a, b, R, dur):
    ws = words[a]["start"]; prev_end = words[a - 1]["end"] if a > 0 else 0.0
    g = [s for s in sil if prev_end - 0.3 <= s["start"] and s["end"] <= ws + 0.05 and s["end"] >= prev_end - 0.05]
    if g:
        gg = max(g, key=lambda s: s["end"])
        tin = max(gg["start"], gg["end"] - R["pad_in"], prev_end)
    else:
        tin = max(ws - 0.06, prev_end)
    we = words[b]["end"]; nxt = words[b + 1]["start"] if b + 1 < len(words) else dur
    g = [s for s in sil if s["start"] >= we - 0.08 and s["start"] <= nxt + 0.01]
    if g:
        gg = min(g, key=lambda s: s["start"])
        tout = min(max(gg["start"], we) + R["pad_out"], gg["end"] - 0.02, nxt)
        tout = max(tout, we)
    else:
        tout = min(we + R["pad_out"], nxt)
    return round(tin, 3), round(max(tout, tin + 0.1), 3)


def build_edl(plan, words, sil, dur):
    R = {**DEFAULT_RULES, **plan.get("rules", {})}
    beats, t, warns = [], 0.0, []
    for n, (a, b) in enumerate(plan["keep"], 1):
        if not (0 <= a <= b < len(words)): sys.exit(f"keep range {a}-{b} out of bounds (0..{len(words)-1})")
        # split the range at long pauses, but never make a piece shorter than min_piece
        subs, s0 = [], a
        for i in range(a, b):
            gap = words[i + 1]["start"] - words[i]["end"]
            if gap > R["max_pause"]:
                subs.append((s0, i)); s0 = i + 1
        subs.append((s0, b))
        merged = []
        for sa, sb in subs:
            if merged and (words[sb]["end"] - words[sa]["start"]) < R["min_piece"]:
                merged[-1] = (merged[-1][0], sb)
            else:
                merged.append((sa, sb))
        if len(merged) > 1 and (words[merged[0][1]]["end"] - words[merged[0][0]]["start"]) < R["min_piece"]:
            merged[0] = (merged[0][0], merged[1][1]); del merged[1]
        segs = []
        cta = plan.get("cta_beat")
        cta = len(plan["keep"]) if cta == "last" else cta
        for sa, sb in merged:
            tin, tout = edges(words, sil, sa, sb, R, dur)
            if n == cta and sa == a and a > 0:   # C008 let the story finish: a deliberate pause before the CTA (B03)
                tin = round(max(words[a - 1]["end"] + 0.05, tin - R["cta_pause"]), 3)
            d = round((tout - tin) / R["speed"], 3)
            segs.append({"a": sa, "b": sb, "in": tin, "out": tout, "dur": d, "t": round(t, 3),
                         "text": " ".join(w["w"] for w in words[sa:sb + 1]), "punch_at": punch_points(words, sa, sb, tin, d, R)})
            if d < R["min_piece"]: warns.append(f"beat {n}: piece w{sa}-w{sb} is {d:.2f}s (< {R['min_piece']}s)")
            if sa > a and not re.search(r"[.!?,;:]$", words[sa - 1]["w"]): warns.append(f"beat {n}: jump cut before w{sa} ('{words[sa]['w']}') is mid-sentence")
            t += d
        old = next((x for x in plan.get("beats", []) if x.get("n") == n), {})
        nb = {"n": n, "words": [a, b], "vo": " ".join(w["w"] for w in words[a:b + 1]), "segs": segs,
              "t": segs[0]["t"], "dur": round(sum(s["dur"] for s in segs), 3),
              "broll": old.get("broll"), "suggest": old.get("suggest", [])}
        for k in ("zoom", "zoom_anchor", "punch", "role"):   # per-beat edit choices survive a re-plan
            if k in old: nb[k] = old[k]
        beats.append(nb)
    # back-to-back pieces of a continuous take (beat n ends on word k, beat n+1 starts on word k+1) must butt, not overlap:
    # the padding would replay the tail of word k at the start of the next beat (a stutter, and a false caption onset).
    # Cut both at the middle of the gap between the two words. A deliberate pre-CTA pause (overlap inside silence) stays.
    flat = [sg for bt in beats for sg in bt["segs"]]
    fixed = 0
    tight = set(plan.get("tighten_seams") or [])   # beat numbers whose leading seam drops the pause (breath/noise in the gap)
    starts = {bt["segs"][0]["a"]: bt["n"] for bt in beats}
    for p_, q_ in zip(flat, flat[1:]):
        if q_["a"] == p_["b"] + 1 and starts.get(q_["a"]) in tight:
            we, ws = words[p_["b"]]["end"], words[q_["a"]]["start"]
            p_["out"] = round(we + 0.12, 3); q_["in"] = round(max(ws - 0.08, we + 0.12), 3); fixed += 1; continue
        if q_["a"] == p_["b"] + 1 and q_["in"] < p_["out"]:
            we, ws = words[p_["b"]]["end"], words[q_["a"]]["start"]
            if q_["in"] < we + 0.02 or p_["out"] > ws - 0.02:
                mid = round((we + max(ws, we)) / 2, 3); p_["out"] = mid; q_["in"] = mid; fixed += 1
    held = False
    eh = R.get("end_hold")   # seconds kept after the final word (let the last word finish and the ad breathe)
    if eh and flat:
        lg = flat[-1]; want = round(min(dur, words[lg["b"]]["end"] + eh), 3)
        if want > lg["out"]: lg["out"] = want; held = True
    if fixed or held:
        t = 0.0
        for bt in beats:
            for sg in bt["segs"]:
                sg["dur"] = round((sg["out"] - sg["in"]) / R["speed"], 3); sg["t"] = round(t, 3); t += sg["dur"]
            bt["t"] = bt["segs"][0]["t"]; bt["dur"] = round(sum(sg["dur"] for sg in bt["segs"]), 3)
        if fixed: warns.append(f"{fixed} back-to-back seam(s) butted at the word gap (no replayed audio)")
    return beats, round(t, 3), warns


def punch_points(words, sa, sb, tin, d, R):
    """C001b: a long a-roll piece gets punch-in toggles at word gaps (seconds into the piece, output time) so the frame
    changes every ~auto_punch s without cutting the take (B06 emphasis zoom; A12 'never let the eyes get comfortable').
    Prefers gaps after punctuation; never within 0.6 s of the piece edges."""
    step = R.get("auto_punch")
    if not step or d <= R["max_static"]: return []
    gaps = []
    for i in range(sa, sb):
        g = ((words[i]["end"] + words[i + 1]["start"]) / 2 - tin) / R["speed"]
        if 0.6 < g < d - 0.6: gaps.append((g, bool(re.search(r"[.!?,;:]$", words[i]["w"]))))
    out, n = [], math.ceil(d / step)
    for k in range(1, n):
        ideal = d * k / n
        c = [x for x in gaps if abs(x[0] - ideal) < step / 2 and (not out or x[0] - out[-1] > 1.0)]
        if c: out.append(round(min(c, key=lambda x: abs(x[0] - ideal) - (0.4 if x[1] else 0))[0], 3))
    return out


def zooms(plan, R):
    """Scale per a-roll piece, in timeline order. C001: alternate 1.0 / punch_in on every jump cut so a cut on the same
    framing never reads as a glitch (B06). A beat's "zoom" (e.g. 1.12 emphasis on the key line) overrides; "punch": false
    keeps that beat at 1.0."""
    out, k = [], 0
    for b in plan["beats"]:
        for _ in b["segs"]:
            if b.get("zoom"): z = float(b["zoom"])
            elif b.get("punch") is False or not R.get("punch_in"): z = 1.0
            else: z = R["punch_in"] if k % 2 else 1.0
            out.append((b["n"], z)); k += 1
    return out


def cadence(plan, R):
    """C002: something must change on screen every few seconds (A12 'never let the eyes get comfortable', A06 'new visual
    about every 2 s' for punchy ads, B05 a clip every 1-3 s). Older buyers need a calmer pace (A12, B08), so the default
    ceiling is 3.5 s. Events = every a-roll cut (each is also a punch-in change), b-roll in and out. Returns static spans."""
    if plan.get("shots"):
        ev = sorted({0.0, plan.get("total", 0.0)} | {round(x["at"], 2) for x in plan["shots"]} | {round(float(c["at"]), 2) for c in plan.get("cards") or []})
        sh_ = sorted(plan["shots"], key=lambda z: z["at"])   # R002 / owner holds: spans inside a one_take shot may run long
        holds = [(z["at"], sh_[i + 1]["at"] if i + 1 < len(sh_) else plan.get("total", 0)) for i, z in enumerate(sh_) if z.get("one_take")]
        inside = lambda x, y: any(a - 0.01 <= x and y <= e + 0.01 for a, e in holds)
        return [(x, y, next((b["n"] for b in plan["beats"] if b["t"] <= x + 0.01 < b["t"] + b["dur"]), "?")) for x, y in zip(ev, ev[1:])
                if y - x > R["max_static"] and not inside(x, y)]
    ev, cover = {0.0, plan.get("total", 0.0)}, []
    for b in plan["beats"]:
        br = b.get("broll")
        if br:
            t0 = b["t"] + br["off"]; ev.add(round(t0, 2)); ev.add(round(t0 + br["dur"], 2))
            if not br.get("pip"): cover.append((t0, t0 + br["dur"]))   # a full-frame insert hides the a-roll's cuts and punch-ins
    hidden = lambda t: any(x + 0.01 < t < y - 0.01 for x, y in cover)
    for b in plan["beats"]:
        for s in b["segs"]:
            for t in [s["t"]] + [s["t"] + p for p in (s.get("punch_at") or [])]:
                if not hidden(t): ev.add(round(t, 2))
    ev = sorted(ev); spans = []
    for x, y in zip(ev, ev[1:]):
        if y - x > R["max_static"]:
            bn = next((b["n"] for b in plan["beats"] if b["t"] <= x + 0.01 < b["t"] + b["dur"]), "?")
            spans.append((x, y, bn))
    return spans


def plan_cmd(proj, plan):
    tw, sil = transcribe(plan["aroll"]["fid"], RAW / plan["aroll"]["file"])
    dur = probe(RAW / plan["aroll"]["file"])[0]
    if not plan.get("keep"): sys.exit("plan.json has no keep ranges yet — read TAKES.md and fill keep: [[w0,w1], ...]")
    beats, total, warns = build_edl(plan, tw["words"], sil, dur)
    plan["beats"] = beats; plan["total"] = total; save(proj, plan)
    (proj / "EDIT_KIT").mkdir(exist_ok=True)
    (proj / "EDIT_KIT" / "edl.json").write_text(json.dumps({"aroll": plan["aroll"], "beats": beats, "total": total}, indent=1))
    print(f"EDL: {len(beats)} beats, {sum(len(b['segs']) for b in beats)} pieces, {total:.1f}s")
    for b in beats:
        print(f"  beat {b['n']}  @{b['t']:.2f}  {b['dur']:.2f}s  {b['vo'][:90]}")
        for s in b["segs"]:
            print(f"      w{s['a']}-w{s['b']}  src {s['in']:.2f}-{s['out']:.2f}  ({s['dur']:.2f}s)")
    for w in warns: print("  WARN", w)
    R = {**DEFAULT_RULES, **plan.get("rules", {})}
    for x, y, bn in cadence(plan, R):
        print(f"  WARN static {x:.1f}-{y:.1f}s ({y-x:.1f}s, beat {bn}): nothing changes on screen — add b-roll (set-broll), "
              f"an emphasis zoom (beat 'zoom': 1.12) or split the line (C002)")
    if not plan.get("cta_beat"): print("  note: set plan.cta_beat (a beat number or \"last\") to get the pre-CTA pause (C008)")
    src_span = sum(b["dur"] for b in beats)
    print(f"kept {src_span:.1f}s of {dur:.1f}s source")


# ---------- b-roll suggestions ----------
# Optional: footage/KEYS.json maps your INDEX.csv folder codes to search words, e.g. {"01": "couch sofa chair"}.
_KEYS_FILE = pathlib.Path(__file__).resolve().parent.parent / "footage" / "KEYS.json"
KEYS = json.loads(_KEYS_FILE.read_text()) if _KEYS_FILE.exists() else {}


def broll_cmd(proj, plan, keywords=False):
    if not keywords and (FOOT / "moments" / "index.json").exists():
        import moments
        moments.pick(proj, plan); save(proj, plan)
        print("\nchoose with: rawedit.py <ad> set-broll <beat> <m:id>   (in-point and length come from the moment; --in/--dur override)")
        return
    rows = index_rows(); mine = plan["aroll"]["fid"]; pet = (plan["aroll"].get("pet") or "").lower()
    for b in plan["beats"]:
        txt = set(re.findall(r"[a-z]+", b["vo"].lower()))
        sc = []
        for r in rows:
            if r["fid"] == mine or r["Type"] != "B-roll": continue
            f2 = r["Folder"][:2]; s = 0
            s += 3 * len(txt & set(KEYS.get(f2, "").split()))
            s += len(txt & set(re.findall(r"[a-z]+", r["What you see"].lower()))) * 1.5
            s += int(r["Quality (1-3)"] or 1) - 1
            if r["Flags"].strip(): s -= 1
            if pet and r["Pet"].lower() == pet: s += 1
            if r["Creator"] == plan["aroll"]["creator"]: s += 1
            if float(r["Seconds"] or 0) < 2: s -= 2
            if s > 0: sc.append((s, r))
        sc.sort(key=lambda x: -x[0])
        b["suggest"] = [{"fid": r["fid"], "name": r["New file name"], "what": r["What you see"], "sec": r["Seconds"],
                         "q": r["Quality (1-3)"], "score": s} for s, r in sc[:4]]
    save(proj, plan)
    for b in plan["beats"]:
        print(f"beat {b['n']} ({b['dur']:.1f}s): {b['vo'][:70]}")
        for s in b["suggest"]: print(f"    [{s['score']:.0f}] {s['name']}  ({s['sec']}s, q{s['q']})  — {s['what']}")
        if not b["suggest"]: print("    (no match — keep the creator on camera)")


def _ban_guard(r, a, b=None, d=None):
    """Refuse a banned clip / hard-banned window; print a WARN for a scoped ban (only banned for some lines)."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); import banned
    b = a + d if b is None else b
    why = banned.window_banned(r["fid"], a, b, scoped=False, name=r.get("New file name"))
    if why: sys.exit(f"REFUSED T06: {r.get('New file name') or r['fid']} {a:.2f}-{b:.2f}s is banned ({why}). Pick another clip or window.")
    for h in banned.window_hits(r["fid"], a, b):
        if not h.get("hard"): print(f"  WARN T06 {r.get('New file name') or r['fid']} {a:.2f}-{b:.2f}s overlaps a scoped ban: {h.get('reason')}")


def set_broll(proj, plan, n, key, src_in=None, off=0.0, dur=None, split=None, split_in=0.0, flip=False, pip=False):
    """split: a second INDEX clip for the bottom half (before on top, after below: A05, B07 opening split screen).
    flip: mirror the clip so screen direction matches the neighbouring shot (B07 continuity).
    A clip up to 12 % too short is slowed to fill the line (B05: 88-92 % is invisible) instead of leaving a flash."""
    rows = all_rows(); r = find_row(rows, key); b = next(x for x in plan["beats"] if x["n"] == n)
    mom = None
    if key.startswith("m:"):
        mom = moment(key); sug = next((s_ for s_ in b.get("suggest") or [] if s_.get("mid") == mom["id"]), None)
        if src_in is None: src_in = float(sug["in"]) if sug else float((mom.get("take") or {}).get("swipes_from") or mom["start"])
        if (mom.get("take") or {}) and not mom["take"].get("complete"):
            print(f"  WARN T05 {mom['id']} is not a complete demo take (action+show+result): fine for a non-demo line only")
        if mom.get("product_brand") == "other": print("  NOTE a competitor's product is visible in this clip: blur it")
    src_in = float(src_in or 0.0)
    f = fetch(r); clip_dur = probe(f)[0]
    d = dur if dur else round(b["dur"] - off, 3); spd = 1.0
    avail = clip_dur - src_in
    if mom: avail = min(avail, mom["end"] - src_in + 0.3)   # stay inside the moment (no hard cut, no dead tail)
    if avail + 0.05 < d:
        if avail >= 0.88 * d:
            spd = round(avail / d, 3); print(f"  b-roll {avail:.2f}s for a {d:.2f}s line: slowed to {spd*100:.0f}% to fill it (C006)")
        else:
            d = round(avail, 3); print(f"  b-roll shorter than the beat: covers {d:.2f}s of {b['dur']:.2f}s")
    _ban_guard(r, src_in, src_in + d * spd)   # T06: never place a banned clip or banned window (footage/BANNED_CLIPS.json)
    if split: _ban_guard(find_row(rows, split), float(split_in or (moment(split)["start"] if split.startswith("m:") else 0.0)), None, d)
    b["broll"] = {"fid": r["fid"], "file": f.name, "name": r["New file name"], "in": src_in, "off": off, "dur": d, "speed": spd, "flip": bool(flip), "pip": bool(pip)}
    if mom: b["broll"].update({"mid": mom["id"], "what": mom.get("action", "")})
    if split:
        r2 = find_row(rows, split); f2 = fetch(r2)
        if split.startswith("m:") and not split_in: split_in = moment(split)["start"]
        b["broll"]["split"] = {"fid": r2["fid"], "file": f2.name, "name": r2["New file name"], "in": split_in}
    save(proj, plan)
    print(f"beat {n}: b-roll {r['New file name']} src {src_in}+{d:.2f}s at offset {off}" + (f"  | bottom half: {b['broll']['split']['name']}" if split else "") + ("  (flipped)" if flip else "") + ("  (creator PiP on top)" if pip else ""))


# ---------- storyboard ----------
def still(src, t, out, w=270, flip=False):
    out.parent.mkdir(parents=True, exist_ok=True)
    sh("ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1", "-vf", f"scale={w}:-2" + (",hflip" if flip else ""), out)


def storyboard(proj, plan):
    a = RAW / plan["aroll"]["file"]; sb = proj / "STORYBOARD"; cards = []
    for b in plan["beats"]:
        s0 = b["segs"][0]; still(a, s0["in"] + 0.3, sb / f"beat_{b['n']:02d}_a.jpg", flip=bool(plan["aroll"].get("flip")))
        br = ""
        if b.get("broll"):
            still(RAW / b["broll"]["file"], b["broll"]["in"] + 0.2, sb / f"beat_{b['n']:02d}_b.jpg")
            br = f"<img src='STORYBOARD/beat_{b['n']:02d}_b.jpg'><div class='cap'>b-roll: {html.escape(b['broll']['name'])} ({b['broll']['dur']:.1f}s)" + (f"<br>{html.escape(b['broll']['mid'])}" if b['broll'].get('mid') else "") + "</div>"
        it = b.get("intent") or {}
        alts = ""
        for k, s_ in enumerate((b.get("suggest") or [])[:3]):
            if not s_.get("mid") or (b.get("broll") or {}).get("mid") == s_["mid"]: continue
            fp = RAW / f"{s_['fid']}{pathlib.Path(s_['name']).suffix.lower() or '.mp4'}"
            if not fp.exists(): continue
            still(fp, s_["in"] + 0.3, sb / f"beat_{b['n']:02d}_alt{k}.jpg", w=160)
            alts += f"<div><img class='alt' src='STORYBOARD/beat_{b['n']:02d}_alt{k}.jpg'><div class='cap'>{html.escape(s_['mid'])}<br>{html.escape(s_.get('why',''))}</div></div>"
        intent_html = (f"<p class='meta'>must show: {html.escape(str(it.get('literal','')))} · feel: {html.escape(str(it.get('meaning','')))} ({html.escape(str(it.get('emotion','')))})</p>" if it else "")
        if alts: intent_html += f"<div class='row'><span class='meta'>other picks:</span>{alts}</div>"
        pieces = "<br>".join(f"src {s['in']:.2f}-{s['out']:.2f} ({s['dur']:.2f}s)" for s in b["segs"])
        cards.append(f"""<section class="beat" data-n="{b['n']}"><h2>Beat {b['n']} <small>@{b['t']:.2f}s · {b['dur']:.2f}s · {len(b['segs'])} piece(s)</small></h2>
<div class="row"><div><img src="STORYBOARD/beat_{b['n']:02d}_a.jpg"><div class="cap">a-roll {html.escape(plan['aroll']['creator'])}</div></div><div>{br}</div></div>
<p class="line">“{html.escape(b['vo'])}”</p>{intent_html}<p class="meta">{pieces}</p>
<div class="decide"><label><input type="radio" name="d{b['n']}" value="approve"> approve</label> <label><input type="radio" name="d{b['n']}" value="redo"> redo</label>
<input type="text" class="note" placeholder="note (cut, b-roll, pacing...)"> <label title="applies to every future ad"><input type="checkbox" class="rule"> general rule</label></div></section>""")
    master = (proj / "MASTER.mp4").exists()
    mv = f'<section class="beat" id="master"><h2>Whole ad</h2><video id="mv" src="MASTER.mp4" controls playsinline style="max-width:360px;width:100%;border-radius:8px;background:#000"></video><div class="decide"><button onclick="markTime()">Add note at current time</button><span id="mt"></span></div><div id="tnotes"></div><div class="decide"><input type="text" id="adnote" class="note" placeholder="Note about the whole ad"><label><input type="checkbox" id="adrule"> general rule</label></div></section>' if master else ""
    hook = f"<p class='meta'>hook card: {html.escape(plan['hook_card'])}</p>" if plan.get("hook_card") else ""
    doc = f"""<!doctype html><meta charset="utf-8"><title>{html.escape(plan['ad'])} storyboard</title>
<style>body{{font:15px/1.4 -apple-system,sans-serif;margin:20px;background:#111;color:#eee}}.beat{{background:#1c1c1c;border-radius:10px;padding:14px;margin:12px 0;max-width:820px}}
.row{{display:flex;gap:14px;flex-wrap:wrap}}.row img{{width:200px;border-radius:6px;background:#000}}.row img.alt{{width:110px}}.cap{{color:#999;font-size:12px;max-width:200px}}.line{{font-size:17px}}.meta{{color:#888;font-size:12px}}
.note{{width:380px;padding:4px}}small{{color:#888;font-weight:normal}}button{{padding:6px 10px}}h2{{margin:0 0 8px}}</style>
<header><b>{html.escape(plan['ad'])}</b> · {len(plan['beats'])} beats · {plan.get('total',0):.1f}s · a-roll {html.escape(plan['aroll']['name'])} <button onclick="copyNotes()">Copy notes for Claude</button> <span id="msg"></span></header>{hook}
{mv}{''.join(cards)}
<script>
const K='rawedit:{html.escape(plan['ad'])}';let T=JSON.parse(localStorage.getItem(K+':T')||'[]');
function state(){{const s={{}};document.querySelectorAll('.beat[data-n]').forEach(b=>{{const n=b.dataset.n;const d=b.querySelector('input[type=radio]:checked');s[n]={{d:d?d.value:'',note:b.querySelector('.note').value,rule:b.querySelector('.rule').checked}}}});return s}}
function restore(){{const s=JSON.parse(localStorage.getItem(K)||'{{}}');for(const [n,v] of Object.entries(s)){{const b=document.querySelector(`.beat[data-n="${{n}}"]`);if(!b)continue;if(v.d)b.querySelector(`input[value=${{v.d}}]`).checked=true;b.querySelector('.note').value=v.note||'';b.querySelector('.rule').checked=!!v.rule}}drawT()}}
document.addEventListener('input',()=>localStorage.setItem(K,JSON.stringify(state())));document.addEventListener('change',()=>localStorage.setItem(K,JSON.stringify(state())));
function saveT(){{localStorage.setItem(K+':T',JSON.stringify(T))}}
function drawT(){{const el=document.getElementById('tnotes');if(!el)return;el.innerHTML=T.map((t,i)=>`<div class="decide"><b>@${{t.t}}s</b> <input type="text" class="note" value="${{t.note.replace(/"/g,'&quot;')}}" oninput="T[${{i}}].note=this.value;saveT()"><label><input type="checkbox" ${{t.rule?'checked':''}} onchange="T[${{i}}].rule=this.checked;saveT()"> general rule</label><button onclick="T.splice(${{i}},1);saveT();drawT()">x</button></div>`).join('')}}
function markTime(){{const v=document.getElementById('mv');T.push({{t:v.currentTime.toFixed(1),note:'',rule:false}});saveT();drawT()}}
function copyNotes(){{const s=state();let out=`REVIEW {html.escape(plan['ad'])}\\n`;for(const [n,v] of Object.entries(s)){{if(!v.d&&!v.note)continue;out+=`beat ${{n}}: ${{v.d||'(no decision)'}}${{v.note?' — '+v.note:''}}${{v.rule&&v.note?' [RULE]':''}}\\n`}}T.forEach(t=>{{if(t.note)out+=`master @${{t.t}}s: ${{t.note}}${{t.rule?' [RULE]':''}}\\n`}});const an=document.getElementById('adnote');if(an&&an.value)out+=`ad: ${{an.value}}${{document.getElementById('adrule').checked?' [RULE]':''}}\\n`;navigator.clipboard.writeText(out).then(()=>{{document.getElementById('msg').textContent='copied — then run: ad.py {html.escape(plan['ad'])} notes';setTimeout(()=>document.getElementById('msg').textContent='',4000)}})}}
restore();</script>"""
    (proj / "STORYBOARD.html").write_text(doc)
    md = [f"# PLAN — {plan['ad']}", f"a-roll: {plan['aroll']['name']} ({plan['aroll']['creator']})", f"total {plan.get('total',0):.1f}s, {len(plan['beats'])} beats", ""]
    if plan.get("hook_card"): md.append(f"hook card: {plan['hook_card']}\n")
    for b in plan["beats"]:
        md.append(f"## Beat {b['n']} @{b['t']:.2f}s ({b['dur']:.2f}s)\n{b['vo']}\n")
        md.append(f"*[{'b-roll: ' + b['broll']['name'] if b.get('broll') else 'creator on camera'}]*\n")
    (proj / "PLAN.md").write_text("\n".join(md))
    print(f"wrote {proj/'STORYBOARD.html'} and PLAN.md")
    sh("open", proj / "STORYBOARD.html", check=False)


# ---------- render ----------
VF = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1,format=yuv420p"


def zoom_vf(z, anchor=(0.5, 0.4)):
    """Punch-in after the 1080x1920 fill: scale up by z, crop back to the frame around the anchor (faces sit high)."""
    if not z or abs(z - 1.0) < 1e-3: return ""
    zw, zh = int(round(W * z / 2)) * 2, int(round(H * z / 2)) * 2
    ax, ay = anchor
    return f",scale={zw}:{zh},crop={W}:{H}:{int((zw - W) * ax)}:{int((zh - H) * ay)}"


def cut_segment(src, tin, tout, out, speed=1.0, zoom=1.0, anchor=(0.5, 0.4), punch_at=None, alt=1.10, flip=False):
    """punch_at: times (s, output time) where the framing toggles between `zoom` and the alternate scale, same take.
    flip: hflip a mirrored selfie take (aroll.flip, set by the mirror check)."""
    d = tout - tin
    VF_ = VF + (",hflip" if flip else "")
    af = f"afade=t=in:st=0:d=0.03,afade=t=out:st={max(d-0.03,0):.3f}:d=0.03,aresample=48000"
    sp = f",setpts=PTS/{speed}" if speed != 1.0 else ""
    if speed != 1.0: af = f"atempo={speed}," + af
    if punch_at:
        z2 = alt if abs(zoom - 1.0) < 1e-3 else 1.0
        edges_ = list(punch_at) + [99999]
        on = "+".join(f"between(t,{edges_[i]:.3f},{edges_[i+1]:.3f})" for i in range(0, len(punch_at), 2))
        fc = (f"[0:v]{VF_}{sp},split[x][y];[x]null{zoom_vf(zoom, anchor)}[a];[y]null{zoom_vf(z2, anchor)}[b];"
              f"[a][b]overlay=enable='{on}'[v]")
        sh("ffmpeg", "-v", "error", "-y", "-ss", f"{tin:.3f}", "-i", src, "-t", f"{d:.3f}", "-filter_complex", fc, "-map", "[v]",
           "-map", "0:a", "-af", af, *ENC, "-movflags", "+faststart", out)
        return
    vf = VF_ + zoom_vf(zoom, anchor) + sp
    sh("ffmpeg", "-v", "error", "-y", "-ss", f"{tin:.3f}", "-i", src, "-t", f"{d:.3f}", "-vf", vf, "-af", af, *ENC, "-movflags", "+faststart", out)


def concat(files, out):
    lst = out.with_suffix(".txt"); lst.write_text("".join(f"file '{f}'\n" for f in files))
    sh("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out)


def lufs(f):
    r = sh("ffmpeg", "-hide_banner", "-nostats", "-i", f, "-af", "loudnorm=I=-14:TP=-1.5:print_format=json", "-f", "null", "-", check=False)
    m = re.search(r"\{.*\}", r.stderr, re.S)
    return float(json.loads(m.group(0))["input_i"]) if m else None


def voice_af(R, target):
    """C004 voice chain (B06: Multiband 'Broadcast' + Hard Limiter -6 dB; B09 adds a de-esser): rumble cut, gentle
    compression so quiet words come up and loud ones stop jumping out, de-ess, then loudness. Off with rules.voice_chain."""
    ch = "highpass=f=80,acompressor=threshold=-20dB:ratio=3:attack=5:release=80:makeup=2,deesser=i=0.3," if R.get("voice_chain") else ""
    return ch + f"loudnorm=I={target}:TP=-1.5"


def find_drop(music, search=75.0):
    """The music's beat drop: the biggest jump in short-term energy (next 2 s vs previous 2 s) in the first `search` s."""
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(music), "-t", str(search + 3), "-ac", "1", "-ar", "8000", "-f", "f32le", "-"], capture_output=True)
    x = np.frombuffer(r.stdout, dtype=np.float32)
    hop = 2000; n = len(x) // hop
    if n < 20: return 0.0
    db = 20 * np.log10(np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-6)
    best, bt = -99, 0.0
    for i in range(8, n - 8):   # 0.25 s steps, 2 s windows
        s = db[i:i + 8].mean() - db[i - 8:i].mean()
        if s > best and i * 0.25 >= 2.0: best, bt = s, i * 0.25
    return round(bt, 2)


def music_chain(R, plan, total):
    """C005 EQ notch where speech lives (B04/B05: Simple Parametric EQ 1500 Hz, Q 4, -15 dB), C007 music stops on the
    lines that must land (A14: drop the music completely on the key line, bring it back after), end fade."""
    f = []
    if R.get("music_eq"):
        hz, q, g = R["music_eq"]; f.append(f"equalizer=f={hz}:t=q:w={q}:g={g}")
    stops = []
    for n in plan.get("music_stops") or []:
        b = next((x for x in plan["beats"] if x["n"] == n), None)
        if b: stops.append((b["t"], b["t"] + b["dur"]))
    if stops:
        g = "*".join(f"(clip(({a:.3f}-t)/0.08,0,1)+clip((t-{e:.3f})/0.25,0,1))" for a, e in stops)
        f.append(f"volume='{g}':eval=frame")
    f.append(f"afade=t=out:st={max(total-1.5,0):.2f}:d=1.5")
    return ",".join(f), stops


def pretty_card(text, out, style="box", px=56, maxw=860, icon=None, tilt=0):
    """Modern text card (Poppins): *accent* words get a yellow highlighter (light cards) or yellow text (dark cards).
    Styles: box (white), dark (near-black), glass (translucent black), offer (brand yellow). Soft shadow, optional check icon."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    fb = ImageFont.truetype(str(FONTS / "Poppins-SemiBold.ttf"), px); fa = ImageFont.truetype(str(FONTS / "Poppins-Bold.ttf"), px)
    toks = []
    for i, part in enumerate(re.split(r"\*", text)):
        toks += [(w, i % 2 == 1) for w in part.split()]
    d0 = ImageDraw.Draw(Image.new("RGB", (10, 10))); sp = d0.textlength(" ", font=fb)
    wid = lambda w, acc: d0.textlength(w, font=fa if acc else fb)
    ic = int(px * 0.95) if icon else 0
    lines, cur, cw = [], [], 0
    for w, acc in toks:
        ww = wid(w, acc)
        if cur and cw + sp + ww > maxw - ic: lines.append(cur); cur, cw = [], 0
        cur.append((w, acc, ww)); cw += (sp if len(cur) > 1 else 0) + ww
    lines.append(cur)
    lw = [sum(x[2] for x in l) + sp * (len(l) - 1) for l in lines]
    lh = int(px * 1.28); padx, pady = int(px * 0.85), int(px * 0.5)
    bw = int(max(lw) + ic + (int(px * 0.35) if icon else 0) + 2 * padx); bh = lh * len(lines) + 2 * pady
    bg, fg, accent = {"dark": ((14, 14, 16, 242), (255, 255, 255), "text"), "glass": ((10, 10, 12, 165), (255, 255, 255), "text"),
                      "offer": ((255, 212, 0, 255), (12, 12, 12), "bold")}.get(style, ((255, 255, 255, 255), (17, 17, 17), "marker"))
    S = int(px * 0.6); im = Image.new("RGBA", (bw + 2 * S, bh + 2 * S), (0, 0, 0, 0))
    sh_ = Image.new("RGBA", im.size, (0, 0, 0, 0)); ImageDraw.Draw(sh_).rounded_rectangle([S, S + 8, S + bw, S + bh + 8], radius=int(px * 0.62), fill=(0, 0, 0, 80))
    im = Image.alpha_composite(im, sh_.filter(ImageFilter.GaussianBlur(14))); d = ImageDraw.Draw(im)
    d.rounded_rectangle([S, S, S + bw, S + bh], radius=int(px * 0.62), fill=bg)
    x0 = S + padx
    if icon == "check":
        cy = S + bh / 2; d.ellipse([x0, cy - ic / 2, x0 + ic, cy + ic / 2], fill=(22, 163, 74))
        d.line([(x0 + ic * 0.27, cy + ic * 0.02), (x0 + ic * 0.44, cy + ic * 0.19), (x0 + ic * 0.74, cy - ic * 0.17)], fill=(255, 255, 255), width=max(3, int(ic * 0.12)))
        x0 += ic + int(px * 0.35)
    for li, l in enumerate(lines):
        x = x0 + (max(lw) - lw[li]) / 2; y = S + pady + li * lh
        for w, acc, ww in l:
            f = fa if acc else fb
            if acc and accent == "marker":   # highlighter stroke behind the words, lower 60 % of the line
                d.rounded_rectangle([x - px * 0.12, y + lh * 0.38, x + ww + px * 0.12, y + lh * 0.92], radius=int(px * 0.18), fill=(255, 212, 0))
            col = (255, 212, 0) if acc and accent == "text" else fg
            d.text((x, y + (lh - px) * 0.42), w, font=f, fill=col); x += ww + sp
    if tilt: im = im.rotate(tilt, resample=Image.BICUBIC, expand=True)
    im.save(out); return out, im.size[0], im.size[1]


def hook_png(text, out, R):
    """C009 hook box: frame one, readable in half a second; Poppins card (owner 11/5: modern font, no tilt)."""
    return pretty_card(text, out, "box", int(R.get("hook_px", 58)), 880, None, R.get("hook_tilt", 0))


def anim_frames(a, out_dir):
    """plan.anims kind "stopwatch": a quick pop-up stopwatch (overshoot pop-in, hand sweeps a full turn, pop-out), drawn per
    frame as RGBA PNGs. Returns (pattern, frame count, size)."""
    from PIL import Image, ImageDraw, ImageFilter
    import math as m_
    out_dir.mkdir(parents=True, exist_ok=True)
    S = int(a.get("size", 190)); n = max(int(round(float(a.get("dur", 1.2)) * FPS)), 6); C = S + 60
    for i in range(n):
        t = i / (n - 1)
        if t < 0.18: k = t / 0.18; sc = 1.18 * (1 - (1 - k) ** 3)            # pop in with overshoot
        elif t < 0.30: k = (t - 0.18) / 0.12; sc = 1.18 - 0.18 * k              # settle
        elif t > 0.86: k = (t - 0.86) / 0.14; sc = max(1.0 - k, 0.0)            # pop out
        else: sc = 1.0
        im = Image.new("RGBA", (C, C), (0, 0, 0, 0))
        if sc > 0.02:
            r = S / 2 * sc; cx = cy = C / 2 + 8
            sh_ = Image.new("RGBA", (C, C), (0, 0, 0, 0)); ImageDraw.Draw(sh_).ellipse([cx - r, cy - r + 8, cx + r, cy + r + 8], fill=(0, 0, 0, 110))
            im = Image.alpha_composite(im, sh_.filter(ImageFilter.GaussianBlur(8))); d = ImageDraw.Draw(im)
            bw, bh = r * 0.34, r * 0.22                                          # crown button
            d.rounded_rectangle([cx - bw / 2, cy - r - bh * 0.9, cx + bw / 2, cy - r + bh * 0.3], radius=int(bh / 3), fill=(30, 30, 30))
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(24, 24, 24))         # ring
            ri = r * 0.84; d.ellipse([cx - ri, cy - ri, cx + ri, cy + ri], fill=(255, 255, 255))
            for k_ in range(12):                                                    # ticks
                ang = k_ * m_.pi / 6; r1, r2 = ri * (0.78 if k_ % 3 == 0 else 0.86), ri * 0.94
                d.line([(cx + r1 * m_.sin(ang), cy - r1 * m_.cos(ang)), (cx + r2 * m_.sin(ang), cy - r2 * m_.cos(ang))], fill=(40, 40, 40), width=max(2, int(r * 0.05)))
            ang = 2 * m_.pi * min(t / 0.86, 1.0)                                   # sweep hand, one full turn
            d.line([(cx, cy), (cx + ri * 0.72 * m_.sin(ang), cy - ri * 0.72 * m_.cos(ang))], fill=(255, 196, 0), width=max(3, int(r * 0.09)))
            d.ellipse([cx - r * 0.08, cy - r * 0.08, cx + r * 0.08, cy + r * 0.08], fill=(24, 24, 24))
        im.save(out_dir / f"f_{i:03d}.png")
    return str(out_dir / "f_%03d.png"), n, C


def bake_anims(proj, plan, src):
    """Composite plan.anims onto the exact frames by number (PIL), then rebuild before + middle + after. ffmpeg's overlay
    would not show a short sequence shifted 30 s into a long video (11/5), so no timestamp shifting is used here."""
    from PIL import Image
    work = proj / "EDIT_KIT" / "_anim"; shutil.rmtree(work, ignore_errors=True); work.mkdir(parents=True)
    cur = pathlib.Path(src)
    for j, an in enumerate(sorted(plan["anims"], key=lambda z: z["at"])):
        pat, n, C = anim_frames(an, proj / "EDIT_KIT" / f"anim_{j:02d}")
        f0 = int(round(float(an["at"]) * FPS)); fr = work / f"a{j}"; fr.mkdir()
        sh("ffmpeg", "-v", "error", "-y", "-i", cur, "-vf", f"select=between(n\\,{f0}\\,{f0 + n - 1})", "-vsync", "0", "-frames:v", str(n), fr / "v_%03d.png")
        x = int(an.get("x", (W - C) / 2)); y = int(an.get("y", 1250)) - 30
        for i in range(n):
            vf = fr / f"v_{i + 1:03d}.png"
            if not vf.exists(): break
            base = Image.open(vf).convert("RGBA"); ov = Image.open(proj / "EDIT_KIT" / f"anim_{j:02d}" / f"f_{i:03d}.png")
            base.alpha_composite(ov, (x, y)); base.convert("RGB").save(vf)
        enc = ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p", "-r", str(FPS)]
        A, M, Cc = work / f"A{j}.mp4", work / f"M{j}.mp4", work / f"C{j}.mp4"
        sh("ffmpeg", "-v", "error", "-y", "-i", cur, "-an", "-vf", f"select=lt(n\\,{f0}),setpts=N/{FPS}/TB", *enc, A)
        sh("ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", fr / "v_%03d.png", *enc, M)
        sh("ffmpeg", "-v", "error", "-y", "-i", cur, "-an", "-vf", f"select=gte(n\\,{f0 + n}),setpts=N/{FPS}/TB", *enc, Cc)
        joined = work / f"J{j}.mp4"; concat([A, M, Cc], joined)
        out = work / f"S{j}.mp4"
        sh("ffmpeg", "-v", "error", "-y", "-i", joined, "-i", src, "-map", "0:v", "-map", "1:a", "-c", "copy", "-shortest", out)
        cur = out
    return cur


def burn(proj, plan, R, src, dst, captions=True):
    """Hook box (frame one, no animation: A11), overlay cards (plan.cards), then captions LAST (S006)."""
    ass = write_captions(proj, plan, proj / "VO" / "vo.mp3", R) if captions else None
    hook = plan.get("hook_card") if plan.get("hook_style", "box") == "box" else None
    ov = []   # (png, y, start, end)
    if hook:
        png, hw, hh = hook_png(hook, proj / "EDIT_KIT" / "hook_card.png", R); ov.append((png, R["hook_y"], 0.0, hook_secs(plan)))
    for k, c in enumerate(plan.get("cards") or []):
        png, cw, ch = card_png(c, proj / "EDIT_KIT" / f"card_{k:02d}.png", R)
        ov.append((png, c.get("y", R["hook_y"]), float(c["at"]), float(c["at"]) + float(c.get("dur", 2.5))))
    if plan.get("anims"): src = bake_anims(proj, plan, src)
    sub = f"ass={ass}:fontsdir={FONTS}" if ass else None
    if not ov and not sub and not plan.get("anims"): shutil.copy(src, dst); return
    ins, fc, last = ["-i", src], [], "[0:v]"
    for k, (png, y, a, e) in enumerate(ov):
        idx = ins.count("-i"); ins += ["-loop", "1", "-i", png]
        fc.append(f"{last}[{idx}:v]overlay=x=(W-w)/2:y={y}:shortest=1:enable='between(t,{a:.3f},{e:.3f})'[o{k}]"); last = f"[o{k}]"
    fc.append(f"{last}{sub}[v]" if sub else f"{last}null[v]")
    sh("ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "0:a",
       "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p", "-c:a", "copy", dst)


def hook_secs(plan):
    """Hook text stays for the hook beat, at least 3 s (older viewers need 3-5 s to read: B08), at most 5 s."""
    b1 = plan["beats"][0]["dur"] if plan.get("beats") else 3.0
    if plan.get("hook_secs_force"): return float(plan["hook_secs_force"])   # owner: never cover a face (overrides the 3 s floor)
    return min(max(plan.get("hook_secs") or b1, 3.0), 5.0, plan.get("total", 99))


PIP = (360, 640, W - 360 - int(SAFE["side"] * W) - 40, 340)   # w, h, x, y: right side, clear of the caption lines (y 1030-1220) and the like/share column


def pip_mask(out):
    if not out.exists():
        from PIL import Image, ImageDraw
        im = Image.new("L", (PIP[0], PIP[1]), 0); ImageDraw.Draw(im).rounded_rectangle([0, 0, PIP[0] - 1, PIP[1] - 1], radius=28, fill=255); im.save(out)
    return out


def broll_clip(br, out):
    """One b-roll insert: optional split screen (top = clip, bottom = split clip, 1080x960 each), flip, slow-down."""
    rows = None
    def src_of(x):
        nonlocal rows
        if (RAW / x["file"]).exists(): return RAW / x["file"]
        rows = rows or all_rows(); return fetch(find_row(rows, x["fid"]))
    spd = br.get("speed", 1.0) or 1.0; need = br["dur"] * spd
    post = (f",setpts=PTS/{spd}" if spd != 1.0 else "") + (",hflip" if br.get("flip") else "")
    if br.get("split"):
        half = f"scale={W}:{H//2}:force_original_aspect_ratio=increase,crop={W}:{H//2},fps={FPS},setsar=1"
        sp = br["split"]
        sh("ffmpeg", "-v", "error", "-y", "-ss", f"{br['in']:.3f}", "-t", f"{need:.3f}", "-i", src_of(br),
           "-ss", f"{sp['in']:.3f}", "-t", f"{need:.3f}", "-i", src_of(sp), "-an", "-filter_complex",
           f"[0:v]{half}{post}[a];[1:v]{half}{post}[b];[a][b]vstack=inputs=2,format=yuv420p[v]", "-map", "[v]",
           "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p", out)
    else:
        sh("ffmpeg", "-v", "error", "-y", "-ss", f"{br['in']:.3f}", "-t", f"{need:.3f}", "-i", src_of(br), "-an", "-vf", VF + post,
           "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p", out)


def sfx_events(plan):
    """plan.sfx: [{"beat": n, "off": s, "kind": "pop"} | {"at": s, "kind": "whoosh", "db": -14}]. kind = a file stem in
    library/sfx/ (see tools/sfx.py) or a path. Course rule C011: one SFX per on-screen event, minimal in organic/UGC."""
    ev = []
    for s in plan.get("sfx") or []:
        if "at" in s: t = float(s["at"])
        else:
            b = next((x for x in plan["beats"] if x["n"] == s["beat"]), None)
            if not b: continue
            t = b["t"] + float(s.get("off", 0)) + (b["broll"]["off"] if s.get("on") == "broll" and b.get("broll") else 0)
        f = pathlib.Path(s["kind"])
        if not f.exists(): f = next(iter(sorted(SFX_DIR.glob(f"{s['kind']}.*"))), None)
        if not f: print(f"  sfx '{s['kind']}' not found in {SFX_DIR} (run tools/sfx.py build)"); continue
        ev.append((max(t + float(s.get("lead", 0)), 0), f, float(s.get("db", -12))))
    return ev


def render(proj, plan, music=None, captions=True, drop=None):
    if plan.get("locked"): sys.exit(f"{proj.name} is LOCKED. Make a variant instead.")
    if not plan.get("beats"): sys.exit("run plan first")
    R = {**DEFAULT_RULES, **plan.get("rules", {})}
    a = RAW / plan["aroll"]["file"]; seg = proj / "SEGMENTS"; seg.mkdir(exist_ok=True)
    (proj / "EDIT_KIT").mkdir(exist_ok=True); (proj / "VO").mkdir(exist_ok=True)
    beat_files = []; Z = iter(zooms(plan, R))
    for b in plan["beats"]:
        parts = []
        for k, s in enumerate(b["segs"]):
            _, z = next(Z)
            f = seg / f"b{b['n']:02d}_{k}.mp4"
            cut_segment(a, s["in"], s["out"], f, R["speed"], z, tuple(b.get("zoom_anchor") or (0.5, 0.4)),
                        None if b.get("punch") is False else s.get("punch_at"), R.get("punch_in") or 1.10,
                        bool(plan["aroll"].get("flip"))); parts.append(f)
        bf = seg / f"beat_{b['n']:02d}.mp4"
        if len(parts) == 1: shutil.copy(parts[0], bf)
        else: concat(parts, bf)
        if b.get("broll"):
            br = b["broll"]; bc = seg / f"broll_{b['n']:02d}.mp4"; broll_clip(br, bc)
            ov = seg / f"beat_{b['n']:02d}_ov.mp4"; off = br["off"]; en = f"between(t,{off:.3f},{off+br['dur']:.3f})"
            if br.get("pip"):   # C015 creator stays on screen, small, over the b-roll (B02 green-screen reaction layout)
                mask = pip_mask(seg / "pip_mask.png")
                sh("ffmpeg", "-v", "error", "-y", "-i", bf, "-i", bc, "-i", mask, "-filter_complex",
                   f"[0:v]split[base][pp];[pp]scale={PIP[0]}:{PIP[1]},format=rgba[ps];[2:v]format=gray,scale={PIP[0]}:{PIP[1]}[m];[ps][m]alphamerge[pip];"
                   f"[1:v]setpts=PTS-STARTPTS+{off:.3f}/TB[b];[base][b]overlay=eof_action=pass:enable='{en}'[v1];"
                   f"[v1][pip]overlay=x={PIP[2]}:y={PIP[3]}:enable='{en}'[v]", "-map", "[v]", "-map", "0:a", *ENC, ov)
            else:
                sh("ffmpeg", "-v", "error", "-y", "-i", bf, "-i", bc, "-filter_complex",
                   f"[1:v]setpts=PTS-STARTPTS+{off:.3f}/TB[b];[0:v][b]overlay=eof_action=pass:enable='{en}'[v]",
                   "-map", "[v]", "-map", "0:a", *ENC, ov)
            bf = ov
        beat_files.append(bf)
    cut = proj / "CUT_VOICE.mp4"; concat(beat_files, cut)
    # sample-exact voice: AAC segments joined with -c copy each add ~21 ms of encoder priming, so the voice drifts later
    # and later behind the EDL (0.3 s by beat 12 on stairs-h1-remake; lip-sync drift on a-roll). Rebuild the voice in one
    # pass from the source (atrim per piece + 30 ms fades, concatenated as PCM) and put it under the cut's picture.
    pieces = [sg for b in plan["beats"] for sg in b["segs"]]; fcv = []
    for k, sg in enumerate(pieces):
        d_ = sg["out"] - sg["in"]
        fcv.append(f"[0:a]atrim=start={sg['in']:.4f}:end={sg['out']:.4f},asetpts=PTS-STARTPTS,aresample=48000"
                   + (f",atempo={R['speed']}" if R["speed"] != 1.0 else "")
                   + f",afade=t=in:st=0:d=0.03,afade=t=out:st={max(d_ / R['speed'] - 0.03, 0):.4f}:d=0.03[p{k}]")
    fcv.append("".join(f"[p{k}]" for k in range(len(pieces))) + f"concat=n={len(pieces)}:v=0:a=1[a]")
    vwav = proj / "VO" / "voice_exact.wav"
    sh("ffmpeg", "-v", "error", "-y", "-i", a, "-filter_complex", ";".join(fcv), "-map", "[a]", "-ac", "2", "-c:a", "pcm_s16le", vwav)
    cx = proj / "CUT_VOICE_X.mp4"
    sh("ffmpeg", "-v", "error", "-y", "-i", cut, "-i", vwav, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
       "-t", f"{plan['total']:.3f}", cx)
    cut = cx
    if plan.get("shots"):   # voiceover mode: the shot timeline is the picture, the cut keeps only its voice
        pic = build_shots(proj, plan); cv = proj / "CUT_VOICE_SHOTS.mp4"
        sh("ffmpeg", "-v", "error", "-y", "-i", pic, "-i", cut, "-map", "0:v", "-map", "1:a", "-c", "copy", "-t", f"{plan['total']:.3f}", cv)
        cut = cv
    # voice-only reference on the output timeline (captions + checks are timed off this)
    vo = proj / "VO" / "vo.mp3"
    sh("ffmpeg", "-v", "error", "-y", "-i", cut, "-vn", "-af", voice_af(R, -16), "-ar", "48000", "-ac", "2", "-b:a", "192k", vo)
    mixed = proj / "CUT.mp4"; total = plan["total"]
    ins, fc, mix = ["-i", cut], [], ["[v]"]
    sfx = sfx_events(plan) + SHOT_AUDIO
    plan["music"] = None
    mood = music[5:] if music and music.startswith("mood:") else (plan.get("music_mood") if not music else None)
    if mood:   # free local library (tools/music_lib.py): trendy / popular / library tracks tagged by mood
        import music_lib as ml
        hold_t = next((b["t"] for b in plan["beats"] if b["n"] == plan.get("hold_beat", 2)), 0.0)
        pk = ml.pick(mood, plan.get("music_kind", "any"), total, proj.name, bool(plan.get("music_vocals")), hold_t)
        if not pk: sys.exit(f"no '{mood}' music in library/music (music_lib.py list / add / fetch-free)")
        music = pk["file"]; plan["music_mood"] = mood; plan["music_pick"] = pk
        if drop is None: drop = pk["drop"]
        print(f"  music ({mood}): {pk['title']} [{pk['kind']}{', instrumental' if pk['instrumental'] else ''}]")
    if music:
        music = pathlib.Path(music).resolve(); plan["music"] = str(music)
        mv = lufs(music); gain = (-16.0 - R["music_under_db"]) - (mv if mv is not None else -20)
        # C003 the beat drop lands where the hold starts (B04, B07): music is shifted so drop == start of beat hold_beat
        hold_t = next((b["t"] for b in plan["beats"] if b["n"] == plan.get("hold_beat", 2)), 0.0)
        if drop == "auto": drop = find_drop(music); print(f"  music drop detected at {drop:.2f}s")
        lead = 0.0
        if drop is not None:
            st = float(drop) - hold_t
            if st >= 0: ins += ["-ss", f"{st:.3f}"]
            else: print(f"  music drop {float(drop):.1f}s comes before the hold ({hold_t:.1f}s): track starts at 0, no silence under the hook")
            plan["music_drop"] = {"at": float(drop), "lands": hold_t if st >= 0 else float(drop)}
        ins += ["-stream_loop", "-1", "-i", music]
        chain, stops = music_chain(R, plan, total)
        fc.append(f"[1:a]volume={gain:.1f}dB,{chain}" + (f",adelay={int(lead*1000)}:all=1" if lead else "") + "[m]"); mix.append("[m]")
        if stops: print(f"  music stops under beats {plan.get('music_stops')} ({', '.join(f'{x:.1f}-{y:.1f}s' for x, y in stops)})")
    for k, (t, f, db) in enumerate(sfx):
        i = 1 + (1 if music else 0) + k; ins += ["-i", f]
        fc.append(f"[{i}:a]aresample=48000,volume={db}dB,adelay={int(t*1000)}:all=1[s{k}]"); mix.append(f"[s{k}]")
    if len(mix) > 1:
        fc.insert(0, f"[0:a]{voice_af(R, -16)}[v]")
        fc.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5[a]")
    else:
        fc = [f"[0:a]{voice_af(R, -14)}[a]"]
    sh("ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fc), "-map", "0:v", "-map", "[a]", "-t", f"{total:.3f}",
       "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", mixed)
    if sfx: print(f"  sfx: " + ", ".join(f"{f.stem}@{t:.2f}s" for t, f, _ in sfx))
    master = proj / "MASTER.mp4"
    burn(proj, plan, R, mixed, master, captions)
    plan["rendered"] = {"total": plan["total"], "captions": captions, "rules": R}; save(proj, plan)
    d = probe(master)
    print(f"MASTER.mp4  {d[0]:.2f}s  {d[1]}x{d[2]}   (CUT.mp4 = same without captions/hook box, VO/vo.mp3 = voice-only reference)")


def ass_t(x):
    h, r = divmod(x, 3600); m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def write_captions(proj, plan, vo, R):
    """Caption words come from the EDL (the a-roll transcript mapped to the output timeline: out = seg.t + (src - seg.in)/speed),
    not from re-transcribing the cut. Every word after a pause (>= 0.2 s, including every seam) is snapped to the real voice
    onset in the rendered audio, because Whisper hands the first word after a pause the pause itself (R001)."""
    import vo_onsets, mlx_whisper, difflib
    tw, _ = transcribe(plan["aroll"]["fid"], RAW / plan["aroll"]["file"]); Wd = tw["words"]; spd = R["speed"]
    norm = lambda t: re.sub(r"[^a-z0-9']", "", t.lower())
    raw = []; tmp = proj / "VO" / "_beat.wav"
    for b in plan["beats"]:
        # EDL words mapped to the output timeline (text is authoritative, times can drift inside a long take)
        edl = []
        for s in b["segs"]:
            for i in range(s["a"], s["b"] + 1):
                w = Wd[i]; st = s["t"] + (max(w["start"], s["in"]) - s["in"]) / spd; en = s["t"] + (min(w["end"], s["out"]) - s["in"]) / spd
                edl.append([round(st, 3), round(max(en, st + 0.05), 3), w["w"], s["t"]])   # [start, end, text, segment start]
        # Whisper on this beat's rendered audio alone: short windows give tight local timestamps (no drift across a take)
        sh("ffmpeg", "-v", "error", "-y", "-ss", f"{b['t']:.3f}", "-t", f"{b['dur']:.3f}", "-i", vo, "-ac", "1", "-ar", "16000", tmp)
        r = mlx_whisper.transcribe(str(tmp), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en", word_timestamps=True,
                                   initial_prompt=" ".join(w[2] for w in edl))
        loc = [[round(b["t"] + w["start"], 3), round(b["t"] + w["end"], 3), w["word"].strip()] for s_ in r["segments"] for w in s_.get("words", []) if w["word"].strip()]
        m = difflib.SequenceMatcher(None, [norm(w[2]) for w in edl], [norm(w[2]) for w in loc], autojunk=False)
        if m.ratio() >= 0.8:
            for tag, i1, i2, j1, j2 in m.get_opcodes():
                if tag == "equal":
                    for k in range(i2 - i1): edl[i1 + k][0], edl[i1 + k][1] = loc[j1 + k][0], loc[j1 + k][1]
        raw += edl
    tmp.unlink(missing_ok=True)
    for i in range(len(raw) - 1):   # keep the sequence monotonic after the merge
        if raw[i + 1][0] < raw[i][0] + 0.05: raw[i + 1][0] = round(raw[i][0] + 0.05, 3)
        if raw[i + 1][1] < raw[i + 1][0] + 0.05: raw[i + 1][1] = round(raw[i + 1][0] + 0.05, 3)
    x, sr = vo_onsets.load(vo); db, win = vo_onsets.rms_track(x, sr); sp, qt = vo_onsets.levels(db)

    low = (db < sp).astype(float); K = int(0.12 / win)   # 120 ms window; a 10 ms blip must not reset a pause

    def quiet_before(j):   # >= 80 % of the 120 ms before frame j is below speech level
        return j >= K and low[j - K:j].mean() >= 0.8

    def trim_end(w):
        """Whisper stretches a word over the pause that follows it: end the word where a 120 ms (80 %) sub-speech window begins."""
        j0, j1 = int((w[0] + 0.08) / win) + K, int(w[1] / win)
        for j in range(j0, min(j1, len(db))):
            if quiet_before(j):
                w[1] = round(max((j - K) * win, w[0] + 0.05), 3); return

    def onsets(t_from, t_to):
        """Speech onsets in [t_from, t_to]: a frame above the speech level (and the next 30 ms) preceded by a mostly
        sub-speech 120 ms. 'Below speech level' rather than 'silent', because the gap before a word is often breath or noise."""
        i0, i1 = max(K, int(t_from / win)), min(len(db) - 8, int(t_to / win)); out = []
        for j in range(i0, i1):
            # sustained: the next 60 ms average above speech level and 5 of the next 8 frames above it (a 20 ms click is not a word)
            if db[j] > sp and db[j:j + 6].mean() > sp and (db[j:j + 8] > sp).mean() >= 0.6 and quiet_before(j) and (not out or j * win - out[-1] > 0.12):
                out.append(round(j * win, 3))
        return out

    # 1. snap starts (on Whisper's untrimmed spans): a word whose start sits in a pause, or that follows a gap, or that
    #    Whisper stretched, moves to the speech onset nearest its estimate.  2. then trim ends.  3. no overlaps.
    trimmed = [list(w) for w in raw]
    for w in trimmed: trim_end(w)
    for i, w in enumerate(raw):
        prev_end = trimmed[i - 1][1] if i else 0.0      # the previous word's REAL end, not Whisper's stretched one
        j = int(w[0] / win)
        if i == 0 or w[0] - prev_end >= 0.15 or (w[1] - w[0]) > 0.6 or quiet_before(j + K // 2):
            nxt = raw[i + 1][0] if i + 1 < len(raw) else 1e9
            floor = max(prev_end - 0.05, w[0] - 1.0, w[3], (raw[i - 1][0] + 0.05) if i else 0.0)   # never before its own piece starts
            # +1.0: pad + pause + Whisper's early start. An onset nearer the NEXT word's estimate belongs to that word, not this one.
            c = [o for o in onsets(floor, min(w[0] + 1.0, nxt + 0.3)) if o < w[1] and abs(o - w[0]) <= abs(o - nxt)]
            if c:
                o = min(c, key=lambda t: abs(t - w[0]))      # the onset nearest Whisper's estimate, not the last one
                w[0] = o; w[1] = max(w[1], o + 0.05)
            else:
                # a word cannot start in silence: Whisper put it (and maybe the next word) inside the pause. Move it to the
                # first voice onset after an all-quiet lead-in, if that comes before the next word would end.
                lim = raw[i + 1][1] + 0.6 if i + 1 < len(raw) else w[0] + 1.2
                for o in onsets(w[0] - 0.05, min(w[0] + 1.2, lim)):
                    j0, j1 = int(max(w[0], 0) / win), int(o / win)
                    if o > w[0] + 0.15 and j1 > j0 and low[j0:j1].mean() >= 0.85:
                        w[0] = o; w[1] = max(w[1], o + 0.15); break
        if i + 1 < len(raw) and raw[i + 1][0] < w[0] + 0.08:   # keep later words after a word that moved forward
            raw[i + 1][0] = round(w[0] + 0.08, 3); raw[i + 1][1] = max(raw[i + 1][1], raw[i + 1][0] + 0.05)
    for w in raw: trim_end(w)
    for i in range(len(raw) - 1):
        if raw[i][1] > raw[i + 1][0]: raw[i][1] = round(max(raw[i + 1][0] - 0.01, raw[i][0] + 0.05), 3)
    k = 1
    while k < len(raw):   # web addresses: Whisper splits "yourshop" + ".co." -> one token "yourshop.co."
        if raw[k][2][:1] in ".-" and len(raw[k][2].strip(".-")) > 0:   # also "60" + "-day", "money" + "-back"
            raw[k - 1][2] += raw[k][2]; raw[k - 1][1] = raw[k][1]; del raw[k]
        else: k += 1
    for fx in plan.get("word_fix") or []:   # measured onsets that beat Whisper's estimate: {"word": "Right", "near": s, "start": s, "why": ...}
        k = min(range(len(raw)), key=lambda i: abs(raw[i][0] - fx["near"]) + (0 if norm(raw[i][2]) == norm(fx["word"]) else 9))
        if norm(raw[k][2]) == norm(fx["word"]):
            raw[k][0] = fx["start"]; raw[k][1] = max(raw[k][1], fx["start"] + 0.12)
            if k: raw[k - 1][1] = min(raw[k - 1][1], fx["start"] - 0.01)
            for j in range(k + 1, len(raw)):
                if raw[j][0] < raw[j - 1][0] + 0.08: raw[j][0] = round(raw[j - 1][0] + 0.08, 3); raw[j][1] = max(raw[j][1], raw[j][0] + 0.05)
    words = [(w[2], w[0], w[1]) for w in raw]
    cards, cur = [], []
    for i, (w, s, e) in enumerate(words):
        cur.append((w, s, e))
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt[1] - e) if nxt else 9
        url_next = bool(nxt and re.search(r"\w\.\w", nxt[0]))   # a web address gets a card of its own
        if re.search(r"[.!?,;:]$", w) or gap >= 0.35 or len(cur) >= R.get("caption_max_words", 3) or nxt is None or url_next or re.search(r"\w\.\w", w):
            cards.append(cur); cur = []
    # cards too short to read: merge into the previous card only when nothing separates them (no pause, no full stop);
    # otherwise they simply stay on screen longer (the end is the next card's start)
    out = []
    for c in cards:
        if out and (c[-1][2] - c[0][1]) < 0.4 and len(out[-1]) + len(c) <= max(R.get("caption_max_words", 3), 1) \
           and (c[0][1] - out[-1][-1][2]) < 0.2 and not re.search(r"[.!?]$", out[-1][-1][0]):
            out[-1] = out[-1] + c
        else: out.append(c)
    if "--debug" in sys.argv:
        for w in raw: print(f"  {w[0]:6.2f}-{w[1]:6.2f} {w[2]}")
    late = R["caption_late"]
    L = [f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\n", "[V4+ Styles]",
         "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
         f"Style: Cap,{R.get('caption_font', 'Arial Black')},{R.get('caption_size', 78)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,"
         f"{0 if re.search('Bold|Black|Heavy', R.get('caption_font', 'Arial Black')) and R.get('caption_font') != 'Arial Black' else -1},0,0,0,100,100,0,0,1,"
         f"{R.get('caption_outline', 5)},{R.get('caption_shadow', 0)},2,{int(SAFE['side']*W)+10},{int(SAFE['side']*W)+10},{R['caption_margin_v']},1",
         "Style: Hook,Arial Black,70,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,5,0,8,60,60,300,1",
         "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    prev_e = -1.0
    for i, c in enumerate(out):
        s = max(c[0][1] + late, prev_e + 0.01)   # never two cards on screen at once
        e = out[i + 1][0][1] + late - 0.01 if i + 1 < len(out) else c[-1][2] + 0.4
        e = min(e, c[-1][2] + R.get("caption_hold", 0.7))
        txt = " ".join(w for w, _, _ in c); txt = re.sub(r"[.,!;:]+(?=\s|$)", "", txt.upper() if R.get("caption_upper", True) else txt)
        e = max(e, s + 0.3)
        if i + 1 < len(out): e = min(e, out[i + 1][0][1] + late - 0.01) if out[i + 1][0][1] + late - 0.01 > s + 0.15 else e
        L.append(f"Dialogue: 0,{ass_t(s)},{ass_t(e)},Cap,,0,0,0,,{txt}"); prev_e = e
    if plan.get("hook_card") and plan.get("hook_style", "box") == "ass":
        hd = hook_secs(plan)
        L.append(f"Dialogue: 1,{ass_t(0)},{ass_t(hd)},Hook,,0,0,0,,{plan['hook_card'].upper()}")
    ass = proj / "EDIT_KIT" / "captions.ass"; ass.write_text("\n".join(L))
    (proj / "EDIT_KIT" / "captions.srt").write_text("".join(
        f"{i+1}\n{ass_t(c[0][1]+late).replace('.',',')}0 --> {ass_t(c[-1][2]+0.4).replace('.',',')}0\n{' '.join(w for w,_,_ in c)}\n\n" for i, c in enumerate(out)))
    return ass


# ---------- verify ----------
def verify(proj, plan):
    import mlx_whisper
    vo = proj / "VO" / "vo.mp3"; master = proj / "MASTER.mp4"
    if not master.exists(): sys.exit("render first")
    L = [f"# VERIFY — {plan['ad']}", ""]
    seams = []
    for b in plan["beats"]:
        for s in b["segs"]:
            if s["t"] > 0: seams.append((s["t"], f"beat {b['n']} w{s['a']}"))
    L.append(f"## Seams ({len(seams)})  — 3 s window re-transcribed around each cut; repeated words or a chopped attack show here")
    bad = 0
    for t, lab in seams:
        w0 = max(t - 1.5, 0)
        tmp = proj / "VO" / "_seam.wav"
        sh("ffmpeg", "-v", "error", "-y", "-ss", f"{w0:.3f}", "-t", "3", "-i", vo, "-ac", "1", "-ar", "16000", tmp)
        txt = mlx_whisper.transcribe(str(tmp), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en")["text"].strip()
        toks = re.findall(r"[a-z']+", txt.lower()); rep = [x for i, x in enumerate(toks[:-1]) if x == toks[i + 1] and len(x) > 2]
        # pop: peak in 40 ms at the seam vs the 300 ms either side
        def peak(st, d):
            r = sh("ffmpeg", "-v", "info", "-ss", f"{max(st,0):.3f}", "-t", f"{d:.3f}", "-i", vo, "-af", "astats=measure_overall=Peak_level:measure_perchannel=0", "-f", "null", "-", check=False)
            m = re.search(r"Peak level dB:\s*(-?[\d.]+)", r.stderr); return float(m.group(1)) if m else -99
        p = peak(t - 0.02, 0.04); n = max(peak(t - 0.32, 0.3), peak(t + 0.02, 0.3))
        flag = ("REPEAT " + " ".join(rep) if rep else "") + (" POP" if p > n + 3 else "")
        bad += bool(flag)
        L.append(f"- @{t:6.2f}s {lab:14s} {('!! ' + flag) if flag else 'ok '}  “{txt}”")
    tmp.unlink(missing_ok=True)
    L.append("")
    sync_ok = True
    if (proj / "EDIT_KIT" / "captions.ass").exists():
        r = sh(PY, "-I", TOOLS / "caption_sync_check.py", proj, check=False)
        txt = (r.stdout + r.stderr).strip(); sync_ok = "PASS" in txt and "FAIL" not in txt
        L += ["## Caption sync (caption_sync_check.py: Whisper on the mix + onset snapping)", "```", txt[-1200:], "```"]
        if not sync_ok:
            # second opinion from the voice energy itself: is there a sustained speech onset where the card starts?
            import vo_onsets, numpy as np
            x, sr = vo_onsets.load(vo); db, win = vo_onsets.rms_track(x, sr); sp, qt = vo_onsets.levels(db)
            low = (db < sp).astype(float); K = int(0.12 / win)
            ons = [j * win for j in range(K, len(db) - 8) if db[j] > sp and db[j:j + 6].mean() > sp and (db[j:j + 8] > sp).mean() >= 0.6 and low[j - K:j].mean() >= 0.8]
            R = {**DEFAULT_RULES, **plan.get("rules", {})}; agree = 0; rows = []
            for m in re.finditer(r"^\s*([+-][\d.]+)s\s+(.+)$", txt, re.M):
                off, card = float(m.group(1)), m.group(2).strip()
                cs = next((l for l in (proj / "EDIT_KIT" / "captions.ass").read_text().splitlines() if l.endswith("," + card)), None)
                if not cs: continue
                h, mi, s = cs.split(",")[1].split(":"); t0 = int(h) * 3600 + int(mi) * 60 + float(s) - R["caption_late"]
                near = min(ons, key=lambda o: abs(o - t0)) if ons else None
                j0 = int(t0 / win); active = (db[max(j0 - 5, 0):j0 + 15] > sp).mean() >= 0.6   # voice already running through the card start
                ok = (near is not None and abs(near - t0) <= 0.1) or active
                agree += ok; rows.append(f"- {card}: card at {t0:.2f}s, checker says {off:+.2f}s, nearest voice onset {near:.2f}s -> {'energy agrees with the card' if ok else 'CHECK'}")
            L += ["", f"Energy second opinion: {agree}/{len(rows)} flagged cards start on a real voice onset (±0.1 s)."] + rows
            sync_ok = bool(rows) and agree == len(rows)
            L.append("(The checker's ground truth is Whisper on the mixed audio; on real speech with breath and room noise it wobbles. "
                     "The editor's captions are timed from the EDL word map snapped to measured onsets. Owner decides which to trust.)")
        L.append("")
    r = sh(PY, "-I", TOOLS / "audio_check.py", master, "--voice", vo, check=False)
    L += ["## Audio", "```", (r.stdout + r.stderr).strip()[-1500:], "```", ""]
    EC = edit_checks(proj, plan, master); edit_ok = not any("!!" in x for x in EC); L += EC
    r = mlx_whisper.transcribe(str(master), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en")["text"].strip()
    want = " ".join(b["vo"] for b in plan["beats"])
    import difflib
    # word-level, autojunk off: char-level matching with autojunk scored a near-identical transcript 0.31 (2026-11-05)
    ratio = difflib.SequenceMatcher(None, re.findall(r"[a-z']+", want.lower()), re.findall(r"[a-z']+", r.lower()), autojunk=False).ratio()
    L += [f"## Spoken vs planned  (similarity {ratio:.2f}; below 0.9 means a missing or doubled word)", "planned: " + want, "heard:   " + r, ""]
    L.append(f"**{'PASS' if bad == 0 and ratio >= 0.9 and sync_ok and edit_ok else 'CHECK'}** — {bad} flagged seam(s), transcript similarity {ratio:.2f}, captions {'ok' if sync_ok else 'need a look'}, edit checks {'ok' if edit_ok else 'need a look'}")
    (proj / "VERIFY.md").write_text("\n".join(L)); print("\n".join(L))


def edit_checks(proj, plan, master):
    """Course checks (C002, C010, C013): static stretches, safe-zone geometry of the hook box and captions, black frames at
    the head or tail (B06: export ends 2 frames early so no black is exported)."""
    R = {**DEFAULT_RULES, **plan.get("rules", {})}; L = ["## Edit checks (course rules)"]
    sp = cadence(plan, R)
    L.append(f"- cadence: {'ok, nothing static for more than ' + str(R['max_static']) + ' s' if not sp else '!! ' + '; '.join(f'{x:.1f}-{y:.1f}s ({y-x:.1f}s, beat {bn})' for x, y, bn in sp)}")
    top, bot, side = SAFE["top"] * H, (1 - SAFE["bottom"]) * H, SAFE["side"] * W
    cap_bottom = H - R["caption_margin_v"]; cap_top = cap_bottom - 2 * 95   # two lines max at 78 px + outline
    L.append(f"- captions: y {cap_top:.0f}-{cap_bottom:.0f} vs safe {top:.0f}-{bot:.0f} -> {'ok' if cap_bottom <= bot and cap_top >= top else 'ok (owner-approved position T50, up to 32 px below the guide line)' if cap_bottom <= bot + 32 and cap_top >= top else '!! outside the safe zone'}")
    hp = proj / "EDIT_KIT" / "hook_card.png"
    if plan.get("hook_card") and hp.exists():
        from PIL import Image
        w, h = Image.open(hp).size; x0 = (W - w) / 2
        ok = R["hook_y"] >= top and R["hook_y"] + h <= cap_top and x0 >= side
        L.append(f"- hook box: {w}x{h} at y {R['hook_y']}-{R['hook_y']+h}, x {x0:.0f}-{x0+w:.0f}, on screen 0-{hook_secs(plan):.1f}s from frame one -> {'ok' if ok else '!! overlaps the top band, the captions or the side margin'}")
    r = sh("ffmpeg", "-v", "info", "-i", master, "-vf", "blackdetect=d=0.05:pix_th=0.08", "-an", "-f", "null", "-", check=False)
    bl = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", r.stderr)]
    d = probe(master)[0]
    edge = [x for x in bl if x[0] < 0.05 or x[1] > d - 0.1]
    L.append(f"- black frames at head/tail: {'none' if not edge else '!! ' + ', '.join(f'{a:.2f}-{b:.2f}s' for a, b in edge)}")
    # backwards text (2026-11-14): on screen the text reads right when (source mirrored) XOR (we flip it) is false
    def orient(f, flip, label):
        r = mirror_of(f, 6 if label == "a-roll" else 4); v = r["verdict"]
        if v not in ("mirrored", "ok"): return f"- {label}: text check {v}" + (" (flipped)" if flip else "")
        back = (v == "mirrored") != bool(flip)
        return (f"- {label}: {'!! TEXT READS BACKWARDS on screen' if back else 'text reads right'} "
                f"(source {v}, {'flipped' if flip else 'not flipped'})")
    if plan.get("mode") != "vo":
        L.append(orient(RAW / plan["aroll"]["file"], plan["aroll"].get("flip"), "a-roll"))
        for b in plan.get("beats", []):
            br = b.get("broll")
            if br: L.append(orient(RAW / br["file"], br.get("flip"), f"b-roll beat {b['n']} ({br.get('name', '')[:40]})"))
    if plan.get("cta_beat") is None: L.append("- cta_beat not set: no deliberate pause before the CTA (C008)")
    L.append(""); return L


# ---------- FCPXML ----------
def fcpxml(proj, plan):
    R = {**DEFAULT_RULES, **plan.get("rules", {})}
    if R["speed"] != 1.0: print("note: speed != 1 is not written to FCPXML; the timeline is at source speed")
    if plan["aroll"].get("flip"): print("note: aroll.flip is not written to FCPXML; flip the a-roll clips in the NLE (Transform > Flip X)")
    fr = lambda s: f"{int(round(s * FPS))}/{FPS}s"
    a = RAW / plan["aroll"]["file"]; ad = probe(a)[0]
    root = ET.Element("fcpxml", version="1.9"); res = ET.SubElement(root, "resources")
    ET.SubElement(res, "format", id="r1", name=f"FFVideoFormat{H}p{FPS}", frameDuration=f"1/{FPS}s", width=str(W), height=str(H))
    ET.SubElement(res, "asset", id="r2", name=plan["aroll"]["name"], src=a.resolve().as_uri(), start="0s", duration=fr(ad), hasVideo="1", hasAudio="1", format="r1")
    assets = {plan["aroll"]["fid"]: "r2"}; k = 3
    for b in plan["beats"]:
        br = b.get("broll")
        if br and br["fid"] not in assets:
            f = RAW / br["file"]; assets[br["fid"]] = f"r{k}"
            ET.SubElement(res, "asset", id=f"r{k}", name=br["name"], src=f.resolve().as_uri(), start="0s", duration=fr(probe(f)[0]), hasVideo="1", hasAudio="1", format="r1"); k += 1
    lib = ET.SubElement(root, "library"); ev = ET.SubElement(lib, "event", name="ad-machine")
    pr = ET.SubElement(ev, "project", name=plan["ad"]); seq = ET.SubElement(pr, "sequence", format="r1", tcStart="0s", tcFormat="NDF", audioLayout="stereo", audioRate="48k")
    spine = ET.SubElement(seq, "spine")
    for b in plan["beats"]:
        for i, s in enumerate(b["segs"]):
            c = ET.SubElement(spine, "asset-clip", ref="r2", name=f"beat{b['n']}_{i}", offset=fr(s["t"]), start=fr(s["in"]), duration=fr(s["out"] - s["in"]))
            br = b.get("broll")
            if br and i == 0:
                ET.SubElement(c, "asset-clip", ref=assets[br["fid"]], lane="1", name=br["name"], offset=fr(s["in"] + br["off"]), start=fr(br["in"]), duration=fr(br["dur"]))
    out = proj / "EDIT_KIT" / f"{plan['ad']}.fcpxml"; out.parent.mkdir(exist_ok=True)
    ET.indent(root); out.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding="unicode"))
    ET.parse(out)
    print(f"wrote {out}  (Resolve: File > Import > Timeline; Premiere: File > Import). Media paths point at {RAW}")


# ---------- new / variant / status ----------
def new_vo(name, audio):
    """Voiceover-led ad: the VO is the a-roll (on a black picture that the shot timeline replaces)."""
    proj = ROOT / "projects" / name; proj.mkdir(parents=True, exist_ok=True); RAW.mkdir(parents=True, exist_ok=True)
    fid = f"vo-{name}"; f = RAW / f"{fid}.mp4"
    sh("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}", "-i", audio, "-shortest",
       "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", f)
    plan = {"ad": name, "skill": SKILL, "mode": "vo", "aroll": {"fid": fid, "file": f.name, "name": pathlib.Path(audio).name,
            "creator": "voiceover", "pet": "", "seconds": round(probe(f)[0], 1), "says": ""},
            "keep": [], "beats": [], "shots": [], "cards": [], "hook_card": None, "music": None,
            "rules": {**DEFAULT_RULES, "punch_in": None, "auto_punch": None, "max_pause": 0.6, "caption_hold": 0.25}, "locked": False}
    save(proj, plan); print(f"project {proj} (voiceover mode)\n next: rawedit.py {proj} transcribe && rawedit.py {proj} pack")
    return proj


def words_cmd(plan):
    """Output-timeline time of every kept word (to place shots and cards on the words they belong to)."""
    tw, _ = transcribe(plan["aroll"]["fid"], RAW / plan["aroll"]["file"]); Wd = tw["words"]; spd = plan.get("rules", {}).get("speed", 1.0)
    for b in plan["beats"]:
        line = []
        for sg in b["segs"]:
            for i in range(sg["a"], sg["b"] + 1):
                line.append(f"{sg['t'] + (max(Wd[i]['start'], sg['in']) - sg['in']) / spd:.2f}:{Wd[i]['w']}")
        print(f"beat {b['n']:2d} @{b['t']:6.2f} ({b['dur']:.2f}s)  " + "  ".join(line))
    print(f"total {plan.get('total')}")


def shot_src(proj, src):
    if src.startswith("m:"): return fetch(find_row(all_rows(), src))
    p = pathlib.Path(src).expanduser()
    if not p.is_absolute(): p = proj / p
    if p.exists(): return p
    return fetch(find_row(all_rows(), src))


SHOT_AUDIO = []


def build_shots(proj, plan):
    """plan.shots -> SEGMENTS/picture.mp4, frame-exact to plan.total. Each shot is filled to 9:16 (or fitted over a
    blurred copy of itself), optionally flipped, sped, zoomed, or slowly pushed in; it runs until the next shot starts."""
    total = plan["total"]; shots = sorted(plan["shots"], key=lambda x: x["at"]); seg = proj / "SEGMENTS"; seg.mkdir(exist_ok=True)
    if not shots or shots[0]["at"] > 0.01: sys.exit("shots must start at 0")
    files = []
    for i, x in enumerate(shots):
        f0 = round(x["at"] * FPS); f1 = round((shots[i + 1]["at"] if i + 1 < len(shots) else total) * FPS); nf = f1 - f0
        if nf <= 0: continue
        src = shot_src(proj, x["src"]); spd = float(x.get("speed", 1.0)); need = nf / FPS * spd + 0.5
        ax, ay = x.get("anchor") or (0.5, 0.5)
        if x.get("fit") == "blur":
            base = (f"split[bg][fg];[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=28:2,eq=brightness=-0.08[b];"
                    f"[fg]scale={W}:-2[f];[b][f]overlay=(W-w)/2:(H-h)/2")
        else:
            base = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:(iw-{W})*{ax}:(ih-{H})*{ay}"
        chain = base + ",setsar=1"
        if x.get("flip"): chain += ",hflip"
        if spd != 1.0: chain += f",setpts=PTS/{spd}"
        chain += f",fps={FPS}"
        if x.get("push"):
            z0, z1 = x["push"]
            chain += (f",scale={W*2}:{H*2},zoompan=z='{z0}+({z1}-{z0})*on/{max(nf-1,1)}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                      f":d=1:s={W}x{H}:fps={FPS}")
        elif x.get("zoom") and abs(float(x["zoom"]) - 1) > 1e-3:
            chain += zoom_vf(float(x["zoom"]), tuple(x.get("zoom_anchor") or (0.5, 0.5)))
        fx = x.get("fx") or []
        if "punch" in fx:   # transition: lands 15 % tight and eases out to the frame in 0.28 s
            n_ = int(0.28 * FPS)
            chain += (f",scale={W*2}:{H*2},zoompan=z='if(lt(on,{n_}),1.15-0.15*(on/{n_})*(2-on/{n_}),1)':x='iw/2-(iw/zoom/2)'"
                      f":y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}")
        if "shake" in fx:   # impact shake for 0.3 s
            chain += f",scale={int(W*1.06)}:{int(H*1.06)},crop={W}:{H}:x='(iw-ow)/2+14*sin(t*55)*lt(t,0.3)':y='(ih-oh)/2+10*cos(t*47)*lt(t,0.3)'"
        if "flash" in fx:   # white flash on the first frames
            chain += ",eq=brightness=0.55:enable='lt(t,0.05)',eq=brightness=0.25:enable='between(t,0.05,0.12)'"
        if x.get("blur"): chain += f",gblur=sigma={float(x['blur'])}"   # calm background under a card
        # one colour tag for every shot: mixed tags (iPhone HDR bt2020, P3) make ffmpeg rebuild the filter graph mid-video,
        # which reset frame numbers and broke time-placed overlays (stopwatch, 11/5)
        chain += ",tpad=stop_mode=clone:stop_duration=6,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709,format=yuv420p"
        out = seg / f"shot_{i:02d}.mp4"
        if "in" not in x and str(x["src"]).startswith("m:"): x["in"] = moment(x["src"])["start"]
        sh("ffmpeg", "-v", "error", "-y", "-ss", f"{float(x.get('in', 0)):.3f}", "-t", f"{need:.3f}", "-i", src, "-an",
           "-filter_complex", f"[0:v]{chain}[v]", "-map", "[v]", "-frames:v", str(nf), "-r", str(FPS),
           "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p", out)
        files.append(out)
        if x.get("audio") is not None:   # the clip's own sound (product ASMR) under the voice; only for clips with no speech
            wa = seg / f"shot_{i:02d}.wav"; dd = nf / FPS
            sh("ffmpeg", "-v", "error", "-y", "-ss", f"{float(x.get('in', 0)):.3f}", "-t", f"{dd * spd:.3f}", "-i", src, "-vn",
               "-af", f"highpass=f=120{',atempo=' + str(spd) if spd != 1.0 else ''},afade=t=in:d=0.08,afade=t=out:st={max(dd - 0.12, 0):.3f}:d=0.12",
               "-ac", "2", "-ar", "48000", wa)
            SHOT_AUDIO.append((x["at"], wa, float(x["audio"])))
    pic = seg / "picture.mp4"; concat(files, pic)
    print(f"  {len(files)} shots -> picture {probe(pic)[0]:.2f}s (voice {total:.2f}s)")
    return pic


def sf(size, weight="Regular"):
    from PIL import ImageFont
    try:
        f = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", size); f.set_variation_by_name(weight); return f
    except Exception:
        return ImageFont.truetype(str(FONTS / "Montserrat-Bold.ttf"), size)


def review_png(c, out):
    """Review-widget card for a REAL review: initials avatar, name, Verified Buyer, stars, the quote verbatim, product.
    SF Pro, soft shadow. Never invent the person or the words (plan.cards: text, name, initials, product, date)."""
    from PIL import Image, ImageDraw, ImageFilter
    import math as m_
    k = float(c.get("scale", 1.0)); q = lambda v: int(round(v * k))   # whole card scales (owner: "slightly smaller")
    Wc, pad = q(c.get("width", 900)), q(44)
    fq, fn, fs = sf(q(c.get("px", 44)), "Medium"), sf(q(40), "Semibold"), sf(q(30), "Regular")
    d0 = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    lines, cur = [], ""
    for w in c["text"].split():
        t = (cur + " " + w).strip()
        if d0.textlength(t, font=fq) > Wc - 2 * pad and cur: lines.append(cur); cur = w
        else: cur = t
    lines.append(cur)
    lh = int(fq.size * 1.32); head = q(96); stars_h = q(40)
    Hc = pad + head + q(22) + stars_h + q(22) + lh * len(lines) + (q(18) + q(36) if c.get("product") else 0) + pad
    S = 40; im = Image.new("RGBA", (Wc + 2 * S, Hc + 2 * S), (0, 0, 0, 0))
    sh_ = Image.new("RGBA", im.size, (0, 0, 0, 0)); ImageDraw.Draw(sh_).rounded_rectangle([S, S + 10, S + Wc, S + Hc + 10], radius=34, fill=(0, 0, 0, 90))
    im = Image.alpha_composite(im, sh_.filter(ImageFilter.GaussianBlur(18))); d = ImageDraw.Draw(im)
    d.rounded_rectangle([S, S, S + Wc, S + Hc], radius=34, fill=(255, 255, 255, 255))
    x0, y0 = S + pad, S + pad
    col = tuple(c.get("avatar_rgb", (88, 129, 87)))
    d.ellipse([x0, y0, x0 + head, y0 + head], fill=col)
    fi = sf(q(40), "Semibold"); ini = c.get("initials", "".join(p[0] for p in c.get("name", "?").split()[:2]).upper())
    d.text((x0 + head / 2, y0 + head / 2), ini, font=fi, fill=(255, 255, 255), anchor="mm")
    nx = x0 + head + q(26)
    d.text((nx, y0 + q(6)), c.get("name", ""), font=fn, fill=(17, 17, 17))
    if c.get("verified", True):   # green check badge + Verified Buyer
        by = y0 + q(60); cs = q(28); d.ellipse([nx, by, nx + cs, by + cs], fill=(22, 163, 74))
        d.line([(nx + q(7), by + q(15)), (nx + q(12), by + q(20)), (nx + q(21), by + q(9))], fill=(255, 255, 255), width=max(2, q(4)))
        d.text((nx + q(38), by - 1), "Verified Buyer", font=fs, fill=(22, 163, 74))
    if c.get("date"):
        dw = d.textlength(c["date"], font=fs); d.text((S + Wc - pad - dw, y0 + q(12)), c["date"], font=fs, fill=(140, 140, 140))
    ys = y0 + head + q(22); r1, r2 = stars_h / 2, stars_h / 4.4
    for si in range(5):
        cx, cy = x0 + r1 + si * (stars_h + q(8)), ys + r1
        d.polygon([(cx + (r1 if j % 2 == 0 else r2) * m_.sin(j * m_.pi / 5), cy - (r1 if j % 2 == 0 else r2) * m_.cos(j * m_.pi / 5)) for j in range(10)], fill=(255, 182, 0))
    yt = ys + stars_h + q(22)
    for i, l in enumerate(lines): d.text((x0, yt + i * lh), l, font=fq, fill=(34, 34, 34))
    if c.get("product"):
        d.text((x0, yt + lh * len(lines) + q(18)), c["product"], font=fs, fill=(140, 140, 140))
    im.save(out); return out, im.size[0], im.size[1]


def card_png(c, out, R):
    """Overlay card: box (hook style), review (stars + quote), offer (brand yellow), dark (black box, white text)."""
    from PIL import Image, ImageDraw, ImageFont
    if c.get("style") == "review" and c.get("name"): return review_png(c, out)
    if not c.get("legacy"): return pretty_card(c["text"], out, c.get("style", "box"), int(c.get("px", 52)), c.get("maxw", 860), c.get("icon"), c.get("tilt", 0))
    px = int(c.get("px", 52)); style = c.get("style", "box")
    def font(sz):
        for path, idx in (("/System/Library/Fonts/HelveticaNeue.ttc", 1), ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0)):
            try: return ImageFont.truetype(path, sz, index=idx)
            except Exception: pass
        return ImageFont.load_default()
    f = font(px); d0 = ImageDraw.Draw(Image.new("RGB", (10, 10))); maxw = c.get("maxw", 820)
    lines = []
    for para in c["text"].split("\n"):
        cur = ""
        for w in para.split():
            t = (cur + " " + w).strip()
            if d0.textlength(t, font=f) > maxw and cur: lines.append(cur); cur = w
            else: cur = t
        lines.append(cur)
    lh = int(px * 1.25); star_h = int(px * 0.95) if style == "review" else 0
    tw = int(max([d0.textlength(l, font=f) for l in lines] + [star_h * 5.6 if star_h else 0]))
    bw, bh = tw + 84, lh * len(lines) + 44 + (star_h + 16 if star_h else 0)
    bg, fg = {"offer": ((255, 212, 0, 255), (0, 0, 0, 255)), "dark": ((12, 12, 12, 235), (255, 255, 255, 255))}.get(style, ((255, 255, 255, 255), (0, 0, 0, 255)))
    im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=24, fill=bg)
    y = 22
    if star_h:
        import math as m_
        r1, r2 = star_h / 2, star_h / 4.6; x0 = (bw - star_h * 5.6) / 2
        for k in range(5):
            cx, cy = x0 + star_h * (k * 1.15 + 0.5), y + star_h / 2
            pts = [(cx + (r1 if j % 2 == 0 else r2) * m_.sin(j * m_.pi / 5), cy - (r1 if j % 2 == 0 else r2) * m_.cos(j * m_.pi / 5)) for j in range(10)]
            d.polygon(pts, fill=(245, 179, 1, 255))
        y += star_h + 16
    for i, l in enumerate(lines):
        lw = d.textlength(l, font=f); d.text(((bw - lw) / 2, y + i * lh + (lh - px) * 0.3), l, font=f, fill=fg)
    tilt = c.get("tilt", R.get("hook_tilt", 0) if style == "box" else 0)
    if tilt: im = im.rotate(tilt, resample=Image.BICUBIC, expand=True)
    im.save(out); return out, im.size[0], im.size[1]


def new(name, aroll_key):
    rows = index_rows(); r = find_row(rows, aroll_key); f = fetch(r)
    proj = ROOT / "projects" / name; proj.mkdir(parents=True, exist_ok=True)
    plan = {"ad": name, "skill": SKILL, "aroll": {"fid": r["fid"], "file": f.name, "name": r["New file name"], "creator": r["Creator"],
            "pet": r["Pet"], "seconds": r["Seconds"], "says": r["Creator says (if talking)"]},
            "keep": [], "beats": [], "hook_card": None, "music": None, "rules": dict(DEFAULT_RULES), "locked": False}
    save(proj, plan); print(f"project {proj}\n a-roll: {r['New file name']} ({r['Seconds']}s, q{r['Quality (1-3)']}, {r['Type']})\n next: rawedit.py {proj} transcribe && rawedit.py {proj} pack")
    return proj


def variant(proj, plan, new_name, keep=None, hook_card=None):
    """C012 (A11): test messaging OR visuals, never both at once. --hook-card alone = message test (identical edit, new hook
    text). --keep alone = visual test (new opening take/footage, same hook text). Both = allowed, but warned."""
    if not keep and not hook_card: sys.exit("variant needs --keep \"a-b\" (new opening) and/or --hook-card \"text\" (new hook text)")
    if keep and hook_card and hook_card != plan.get("hook_card"):
        print("  WARN changing the opening AND the hook text: if it wins you will not know which did it (A11). Prefer one.")
    dst = proj.parent / new_name; dst.mkdir(exist_ok=True)
    p2 = json.loads(json.dumps(plan)); p2["ad"] = new_name; p2["locked"] = False; p2.pop("rendered", None)
    if hook_card: p2["hook_card"] = hook_card
    if keep:
        first = [[int(x) for x in r.split("-")] for r in keep.split(",")]
        p2["keep"] = first + plan["keep"][1:]
        p2["beats"] = [b for b in plan["beats"] if b["n"] > 1]   # body beats keep their b-roll; new beat 1 starts clean
        for b in p2["beats"]: b["n"] = b["n"] - 1 + len(first)
        if isinstance(p2.get("cta_beat"), int): p2["cta_beat"] += len(first) - 1
        for k in ("music_stops",):
            if p2.get(k): p2[k] = [n - 1 + len(first) if n > 1 else n for n in p2[k]]
        for e in p2.get("sfx") or []:
            if e.get("beat", 0) > 1: e["beat"] += len(first) - 1
    p2["parent"] = plan["ad"]; p2["variant_of"] = {"changed": [x for x, v in (("opening", keep), ("hook_text", hook_card)) if v]}
    save(dst, p2)
    kind = " + ".join(p2["variant_of"]["changed"])
    print(f"variant {dst}: changed {kind}, body unchanged. next: plan, storyboard, render"
          + (" (hook-text-only variant: `plan` then `render`; the cut is identical)" if not keep else ""))


def status(proj, plan):
    print(f"{plan['ad']}  skill={plan['skill']}  locked={plan.get('locked')}  a-roll={plan['aroll']['name']}")
    print(f" keep={plan.get('keep')}  beats={len(plan.get('beats', []))}  total={plan.get('total')}  music={plan.get('music')}")
    for f in ("TAKES.md", "PLAN.md", "STORYBOARD.html", "CUT.mp4", "MASTER.mp4", "VERIFY.md"):
        print(f"  {'x' if (proj / f).exists() else '-'} {f}")


def main():
    a = sys.argv[1:]
    if not a: sys.exit(__doc__)
    if a[0] == "new":
        if "--vo" in a: return new_vo(a[1], a[a.index("--vo") + 1])
        return new(a[1], a[a.index("--aroll") + 1])
    proj = pathlib.Path(a[0]).resolve()
    if not proj.exists(): proj = ROOT / "projects" / a[0]
    plan = load(proj); cmd = a[1] if len(a) > 1 else "status"; rest = a[2:]
    opt = lambda k: rest[rest.index(k) + 1] if k in rest else None
    if cmd == "transcribe": transcribe(plan["aroll"]["fid"], RAW / plan["aroll"]["file"], "--force" in rest); print("ok")
    elif cmd == "pack": pack(proj, plan)
    elif cmd == "mirror":
        if "--on" in rest or "--off" in rest: mirror_cmd(proj, plan, "--on" in rest)
        else:
            plan["aroll"].pop("flip_forced", None); plan["aroll"].pop("flip", None); mirror_of(RAW / plan["aroll"]["file"], force=True); mirror_cmd(proj, plan)
    elif cmd == "plan": plan_cmd(proj, plan)
    elif cmd == "broll": broll_cmd(proj, plan, "--keywords" in rest)
    elif cmd == "set-broll": set_broll(proj, plan, int(rest[0]), rest[1], float(opt("--in")) if opt("--in") else None, float(opt("--off") or 0), float(opt("--dur")) if opt("--dur") else None,
                                       opt("--split"), float(opt("--split-in") or 0), "--flip" in rest, "--pip" in rest)
    elif cmd == "clear-broll": next(b for b in plan["beats"] if b["n"] == int(rest[0]))["broll"] = None; save(proj, plan)
    elif cmd == "storyboard": storyboard(proj, plan)
    elif cmd == "words": words_cmd(plan)
    elif cmd == "render": render(proj, plan, opt("--music"), "--no-captions" not in rest, opt("--music-drop"))
    elif cmd == "captions":   # re-burn captions only (CUT.mp4 -> MASTER.mp4), no re-cut
        if plan.get("locked"): sys.exit("LOCKED")
        R = {**DEFAULT_RULES, **plan.get("rules", {})}
        burn(proj, plan, R, proj / "CUT.mp4", proj / "MASTER.mp4", "--no-captions" not in rest)
        print("hook box + captions re-burned into MASTER.mp4 (no re-cut)")
    elif cmd == "verify": verify(proj, plan)
    elif cmd == "fcpxml": fcpxml(proj, plan)
    elif cmd == "variant": variant(proj, plan, rest[0], opt("--keep"), opt("--hook-card"))
    elif cmd == "status": status(proj, plan)
    else: sys.exit(__doc__)


if __name__ == "__main__":
    main()
