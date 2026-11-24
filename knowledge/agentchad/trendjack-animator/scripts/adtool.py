#!/usr/bin/env python3
# Changelog: 2026-11-09 Library v2 (agentchad.io; reads Whisper w/s/e and [start,end,word] transcripts too).
# Story method adapted from MIT-licensed open-source work, see ../NOTICE.
"""Local steps for a short AI-animated video ad (9:16) built with Starpop. All steps are free.

    adtool.py doctor  AD_DIR                       # ffmpeg, Pillow, caption font
    adtool.py words   AD_DIR TRANSCRIPT.json [N]   # word-timed transcript -> line timings for take N (default 1)
    adtool.py lines   AD_DIR [N]                   # when each line starts and ends (song seconds)
    adtool.py contact AD_DIR                       # review sheet: stills + 3 frames of every clip
    adtool.py render  AD_DIR                       # final 1080x1920 mp4: clips cut to the audio + captions
    adtool.py frames  AD_DIR                       # QA sheet: 3 frames per line of the final video

AD_DIR holds ad.json (copy one from templates/). The audio itself is made outside this script:
voice = scripts/elevenlabs_tts.py, song = suno.com in the browser. "audio": "song" or "voice" picks the mode.
Audio lives in AD_DIR/song/takeN.mp3 (sung) or AD_DIR/voice/takeN.mp3 (one continuous voiceover).
Stills in AD_DIR/stills/<shot id>.png, clips in AD_DIR/clips/<shot id>.mp4.
Run with the skill venv python: .venv/bin/python3 -I scripts/adtool.py <step> <ad folder>
Caption font: the first system font found in FONTS, or set captions.font in ad.json to a .ttf path.
"""
import difflib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

W, H, FPS = 1080, 1920, 30
FONTS = ["/System/Library/Fonts/Supplemental/Arial Black.ttf", "/Library/Fonts/Arial Black.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
CAPTION_STRIP = ',."“”„»«'  # caption rule: never , . or quote marks in captions
# Reels/Stories safe zone on a 1080x1920 frame: (top, bottom, left, right) bands of the clear area
# (x 71-1027 for y 347-867; x 71-886 for y 868-1426, the right side is the button column)
SAFE_BANDS = [(347, 867, 71, 1027), (868, 1426, 71, 886)]
# Small words never end a caption and are never left alone; override per ad with captions.small_words
# (e.g. a list for the target language). captions.no_end_words adds words that must open the next caption.
DEFAULT_SMALL_WORDS = {"the", "a", "an", "and", "to", "of", "in", "on", "for", "with", "but", "or", "at", "by", "so"}
SMALL_WORDS = set(DEFAULT_SMALL_WORDS)
NO_END_WORDS = set(DEFAULT_SMALL_WORDS)
PERCENT_WORDS = {"percent", "procent", "prosent", "prozent", "pourcent", "por", "procento"}
EMOJI_FONT = "/System/Library/Fonts/Apple Color Emoji.ttc"


# ------------------------------------------------------------------ helpers
def load(ad_dir):
    p = Path(ad_dir) / "ad.json"
    if not p.exists():
        sys.exit(f"{p} not found. Copy a file from templates/ to {p} and fill it in.")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    cap = cfg.get("captions") or {}
    global SMALL_WORDS, NO_END_WORDS
    SMALL_WORDS = {w.lower() for w in cap.get("small_words", DEFAULT_SMALL_WORDS)}
    NO_END_WORDS = SMALL_WORDS | {w.lower() for w in cap.get("no_end_words", [])}
    return cfg


def mode(cfg):
    return cfg.get("audio", "song")


def audio_dir(ad_dir, cfg):
    return Path(ad_dir) / ("voice" if mode(cfg) == "voice" else "song")


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        sys.exit("command failed: %s\n%s" % (" ".join(map(str, cmd[:6])), p.stderr[-1500:]))
    return p.stdout


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]))


def script_lines(cfg):
    """The approved lines, in order: lyric lines without [section tags], or the voiceover lines."""
    if mode(cfg) == "voice":
        return [l.strip() for l in cfg["voice"]["lines"] if l.strip()]
    out = []
    for raw in cfg["song"]["lyrics"].splitlines():
        line = re.sub(r"\[[^\]]*\]", "", raw).strip()
        if re.search(r"\w", line):
            out.append(line)
    return out


def norm(word):
    return re.sub(r"[^\w]", "", word.lower())


def transcript_words(data):
    """Find every timed word in a transcript (ElevenLabs, Starpop or Whisper JSON), whatever its nesting: [(text, start_s, end_s)]."""
    found = []

    def walk(x):
        if isinstance(x, list):
            # [start, end, "word"] (multi-market-agent transcribe.py) is one word, not a list to walk
            if len(x) == 3 and all(isinstance(v, (int, float)) for v in x[:2]) and isinstance(x[2], str):
                if x[2].strip() and len(x[2].split()) == 1:
                    found.append((x[2].strip(), float(x[0]), float(x[1])))
                return
            for y in x:
                walk(y)
            return
        if not isinstance(x, dict):
            return
        # "w"/"s"/"e" = thumb-stop-shield whisper_words.py
        text = next((x[k] for k in ("word", "text", "punctuated_word", "w") if isinstance(x.get(k), str)), None)
        start = next((x[k] for k in ("start", "startS", "start_time", "startSeconds", "from", "s") if k in x), None)
        end = next((x[k] for k in ("end", "endS", "end_time", "endSeconds", "to", "e") if k in x), None)
        scale = 1.0
        if start is None and "startMs" in x:
            start, end, scale = x["startMs"], x.get("endMs"), 0.001
        is_word = text is not None and start is not None and end is not None and len(text.split()) == 1
        if is_word:
            found.append((text.strip(), float(start) * scale, float(end) * scale))
            return
        for v in x.values():
            walk(v)

    walk(data)
    found.sort(key=lambda w: w[1])
    return found


def align(lines_, heard):
    """Give every approved word a time from the transcript. Approved spelling wins; unheard words are interpolated.
    Returns [{text, start, end, words: [[word, start, end]]}] and the list of words the singer changed or dropped."""
    want = [(li, w) for li, line in enumerate(lines_) for w in line.split()]
    a, b = [norm(w) for _, w in want], [norm(w) for w, _, _ in heard]
    times = [None] * len(want)
    missed = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                times[i1 + k] = heard[j1 + k][1:]
        elif op == "replace":  # sung differently or misheard: spread the heard span over the approved words
            missed += [w for _, w in want[i1:i2]]
            t0, t1 = heard[j1][1], heard[j2 - 1][2]
            step = (t1 - t0) / (i2 - i1)
            for k in range(i2 - i1):
                times[i1 + k] = (t0 + step * k, t0 + step * (k + 1))
        elif op == "delete":
            missed += [w for _, w in want[i1:i2]]
    known = [i for i, t in enumerate(times) if t]
    if not known:
        sys.exit("No word of the script was found in the transcript. Is it the right audio and language?")
    for i, t in enumerate(times):  # interpolate unheard words between their heard neighbours
        if t:
            continue
        prev = max((k for k in known if k < i), default=None)
        nxt = min((k for k in known if k > i), default=None)
        a0 = times[prev][1] if prev is not None else times[nxt][0] - 0.3 * (nxt - i)
        b0 = times[nxt][0] if nxt is not None else times[prev][1] + 0.3 * (i - prev)
        lo, hi = (prev if prev is not None else i - 1), (nxt if nxt is not None else i + 1)
        step = (b0 - a0) / max(hi - lo, 1)
        times[i] = (a0 + step * (i - lo - 1), a0 + step * (i - lo))
    out = []
    for li, line in enumerate(lines_):
        toks = [[want[i][1], round(times[i][0], 3), round(times[i][1], 3)] for i in range(len(want)) if want[i][0] == li]
        out.append({"text": line, "start": toks[0][1], "end": toks[-1][2], "words": toks})
    return out, missed


def timeline(ad_dir, cfg, take=None):
    """(lines, t0, t1, audio file): the timing shots and captions follow, in seconds of that audio."""
    take = take or cfg.get("cut", {}).get("take", 1)
    d = audio_dir(ad_dir, cfg)
    p = d / f"take{take}_timing.json"
    if not p.exists():
        sys.exit(f"{p} missing: run the words step with the transcript (ElevenLabs word timings or a Whisper/Starpop transcript).")
    ls = [(l["text"], l["start"], l["end"], [tuple(w) for w in l["words"]])
          for l in json.loads(p.read_text(encoding="utf-8"))]
    cut = cfg.get("cut", {})
    audio = next((d / f"take{take}{ext}" for ext in (".mp3", ".wav", ".m4a") if (d / f"take{take}{ext}").exists()), None)
    if not audio:
        sys.exit(f"audio missing: save the voice or song as {d}/take{take}.mp3")
    t1 = min(float(cut.get("t_end", ls[-1][2] + 0.4)), duration(audio))  # never past the end of the file
    return ls, float(cut.get("t_start", max(ls[0][1] - 0.2, 0))), t1, audio


# ------------------------------------------------------------------ steps
def doctor(ad_dir, *_):
    ok = True
    for tool in ("ffmpeg", "ffprobe"):
        print(f"{tool}: {'ok' if shutil.which(tool) else 'MISSING (brew install ffmpeg)'}")
        ok &= bool(shutil.which(tool))
    try:
        import PIL  # noqa: F401
        print("Pillow: ok")
    except ImportError:
        print("Pillow: MISSING - run this script with the skill venv python (.venv/bin/python3)")
        ok = False
    font = next((f for f in FONTS if Path(f).exists()), None)
    print("caption font:", font or "none found; set captions.font in ad.json")
    print("READY" if ok else "NOT READY: fix the lines above")


def words(ad_dir, transcript, *args):
    cfg = load(ad_dir)
    take = int(args[0]) if args and args[0].isdigit() else 1
    heard = transcript_words(json.loads(Path(transcript).read_text(encoding="utf-8")))
    if not heard:
        sys.exit("No timed words found in that file. Save the full transcribe result as JSON and try again.")
    out, missed = align(script_lines(cfg), heard)
    d = audio_dir(ad_dir, cfg)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"take{take}_timing.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"heard {len(heard)} words; wrote {d.name}/take{take}_timing.json")
    if missed:
        print(f"NOT HEARD AS WRITTEN ({len(missed)}): {' '.join(missed)}  - the singer changed or swallowed these; "
              "times are estimated. Listen before planning shots.")
    lines(ad_dir, str(take))


def lines(ad_dir, *args):
    cfg = load(ad_dir)
    take = int(args[0]) if args and args[0].isdigit() else None
    ls, t0, t1, audio = timeline(ad_dir, cfg, take)
    print(f"\ntake {take or cfg.get('cut', {}).get('take', 1)}: file {duration(audio):.1f} s, first word {ls[0][1]:.2f} s, "
          f"last word ends {ls[-1][2]:.2f} s -> {ls[-1][2] - ls[0][1]:.1f} s of words")
    for text, a, b, _ in ls:
        print(f"  {a:6.2f}-{b:6.2f}  {text}")


def grab(video, t, w, h):
    from io import BytesIO
    from PIL import Image
    b = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{max(t, 0):.2f}", "-i", str(video), "-frames:v", "1",
                        "-vf", f"scale={w}:{h}", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
    return Image.open(BytesIO(b)).convert("RGB") if b else Image.new("RGB", (w, h), "grey")


def caption_font(path, size):
    from PIL import ImageFont
    for f in ([path] if path else []) + FONTS:
        if f and Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def label(img, text, font_size=22):
    from PIL import ImageDraw
    ImageDraw.Draw(img).text((8, 6), text, fill="yellow", font=caption_font(None, font_size), stroke_width=2,
                             stroke_fill="black")


def clip_start(s):
    return float(s.get("clip_start", 0.0 if s.get("lipsync") else 0.45))


def contact(ad_dir, *_):
    from PIL import Image
    cfg, root = load(ad_dir), Path(ad_dir)
    w, h = 240, 427
    shots = cfg["shots"]
    # Long ads get one numbered contact page per 10 shots: one tall sheet is too big to read.
    pages = [shots[i:i + 10] for i in range(0, len(shots), 10)]
    for n, page in enumerate(pages, 1):
        out = root / ("contact.jpg" if len(pages) == 1 else f"contact_{n:02d}.jpg")
        contact_page(root, page, w, h, out)
        print("wrote", out)
    print("look at it: every clip must move, faces and product must stay the same")


def contact_page(root, shots, w, h, out):
    from PIL import Image
    sheet = Image.new("RGB", (w * 4, h * len(shots)), "white")
    for r, s in enumerate(shots):
        still = root / "stills" / f"{s['id']}.png"
        if still.exists():
            im = Image.open(still).convert("RGB").resize((w, h))
            label(im, f"{s['id']} still{' LIPSYNC' if s.get('lipsync') else ''}")
            sheet.paste(im, (0, r * h))
        clip = root / "clips" / f"{s['id']}.mp4"
        if clip.exists():
            dur = duration(clip)
            for c, t in enumerate([clip_start(s), dur / 2, max(dur - 0.25, 0)], 1):  # dur-0.05 can fall past the last frame
                im = grab(clip, t, w, h)
                label(im, f"{s['id']} {t:.1f}s")
                sheet.paste(im, (c * w, r * h))
    sheet.save(out, quality=85)


def in_safe_zone(box):
    """True when the box (x0, y0, x1, y1) sits fully inside the clear area of the safe-zone template."""
    x0, y0, x1, y1 = box
    rows = [b for b in SAFE_BANDS if b[0] <= y1 and y0 <= b[1]]
    return (y0 >= SAFE_BANDS[0][0] and y1 <= SAFE_BANDS[-1][1]
            and all(x0 >= left and x1 <= right for _, _, left, right in rows))



def png_layer(src, x, y, scale, out):
    """A ready-made overlay PNG (e.g. a sticker or badge from your editing kit): crop to its visible part, scale it, and place its
    top-left corner at (x, y). Returns (x, y) for the PNG and its box for the safe-zone check."""
    from PIL import Image
    img = Image.open(Path(src).expanduser()).convert("RGBA")
    img = img.crop(img.getbbox() or (0, 0, 1, 1))
    img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    img.save(out)
    return (int(x), int(y)), (int(x), int(y), int(x) + img.width, int(y) + img.height)

def crop_to_content(img, out, pad=16):
    """Save only the visible part of a full-frame RGBA layer; return its (x, y) and the text box (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = img.getbbox() or (0, 0, 1, 1)
    x0, y0, x1, y1 = max(x0 - pad, 0), max(y0 - pad, 0), min(x1 + pad, W), min(y1 + pad, H)
    img.crop((x0, y0, x1, y1)).save(out)
    return x0, y0


def caption_png(text, y, font, out, max_width=680):
    """White caption with a soft dark shadow, centred at height y, wrapped to at most max_width px.
    Returns (x, y) to place the cropped PNG and the text box for the safe-zone check."""
    from PIL import Image, ImageDraw, ImageFilter
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rows = [""]
    for wd in text.split():
        trial = (rows[-1] + " " + wd).strip()
        if d.textlength(trial, font=font) > max_width and rows[-1]:
            rows.append(wd)
        else:
            rows[-1] = trial
    lh = font.size * 1.15
    top = y - lh * len(rows) / 2
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for i, row in enumerate(rows):
        sd.text(((W - d.textlength(row, font=font)) / 2, top + i * lh + 4), row, font=font, fill=(0, 0, 0, 230))
    img = Image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(7)), img)
    d = ImageDraw.Draw(img)
    for i, row in enumerate(rows):
        d.text(((W - d.textlength(row, font=font)) / 2, top + i * lh), row, font=font, fill="white", stroke_width=3,
               stroke_fill=(0, 0, 0, 200))
    widest = max(d.textlength(r, font=font) for r in rows)
    box = ((W - widest) / 2 - 3, top - 3, (W + widest) / 2 + 3, top + lh * len(rows))
    return crop_to_content(img, out), box


def fit_font(font, caps, path, max_width):
    """One caption size for the whole video: shrink it until the widest whole caption fits max_width on ONE line."""
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    start = font.size
    while font.size > 20 and max((d.textlength(t, font=font) for t, _, _ in caps), default=0) > max_width:
        font = caption_font(path, font.size - 1)
    if font.size != start:
        print(f"caption size {start} -> {font.size} so the widest caption fits {max_width} px on one line")
    if font.size < 44:
        print("note: captions got small; lower captions.max_words (e.g. 3). The lower band allows max_width up to "
              "about 690 px (centred), the band above y 868 about 950 px.")
    return font


def is_emoji(ch):
    return ord(ch) >= 0x2600


def headline_png(lines_, top, out, size=50):
    """Hook headline: black upper-case text, one white rounded box per line,
    an emoji allowed at the end. Returns (x, y) for the cropped PNG and the box for the safe-zone check."""
    from PIL import Image, ImageDraw, ImageFont
    font = caption_font("/System/Library/Fonts/Supplemental/Arial Bold.ttf", size)
    emo = ImageFont.truetype(EMOJI_FONT, 160) if Path(EMOJI_FONT).exists() else None
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad_x, pad_y, lh = 22, 10, int(size * 1.32)

    def runs(line):
        out_, cur = [], ""
        for ch in line:
            if is_emoji(ch) and emo:
                if cur:
                    out_.append(("t", cur))
                out_.append(("e", ch))
                cur = ""
            elif ch != "\ufe0f":
                cur += ch
        return out_ + ([("t", cur)] if cur else [])

    def width(rs):
        return sum(d.textlength(t, font=font) if k == "t" else size * 1.1 for k, t in rs)

    x0s, x1s = [], []
    for i, line in enumerate(lines_):
        rs = runs(line.upper())
        w = width(rs)
        x, y = (W - w) / 2, top + i * lh
        d.rounded_rectangle((x - pad_x, y - pad_y, x + w + pad_x, y + lh - pad_y), radius=14, fill="white")
        x0s.append(x - pad_x)
        x1s.append(x + w + pad_x)
        for k, t in rs:
            if k == "t":
                d.text((x, y + (lh - pad_y * 2 - size) / 2), t, font=font, fill="black")
                x += d.textlength(t, font=font)
            else:
                e = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
                ImageDraw.Draw(e).text((0, 0), t, font=emo, embedded_color=True)
                e = e.crop(e.getbbox() or (0, 0, 1, 1)).resize((int(size * 1.0), int(size * 1.0)))
                img.alpha_composite(e, (int(x + size * 0.08), int(y + (lh - pad_y * 2 - size) / 2)))
                x += size * 1.1
    box = (min(x0s), top - pad_y, max(x1s), top + lh * len(lines_) - pad_y)
    return crop_to_content(img, out, pad=4), box


def caption_chunks(lines_, repl, max_words=4):
    """Lines -> captions of 2-4 words, broken after punctuation: [(text, start, end)] in audio seconds."""
    out = []
    for li, (_, a, b, toks) in enumerate(lines_):
        groups, cur = [], []
        merged = []  # "55 percent" (or the same word in the target language) -> one caption word "55%"
        for tok in toks:
            if merged and tok[0].strip(CAPTION_STRIP + ",").lower() in PERCENT_WORDS and merged[-1][0].isdigit():
                merged[-1] = (merged[-1][0] + "%" + tok[0][len(tok[0].rstrip(",.")):], merged[-1][1], tok[2])
            else:
                merged.append(tok)
        toks = merged
        for tok in toks:
            cur.append(tok)
            if re.search(r"[.!?…]$", tok[0].strip('"»”')) or (
                    re.search(r"[,;:]$", tok[0].strip('"»”')) and len(cur) >= 2):
                groups.append(cur)
                cur = []
            elif len(cur) >= max_words:
                # a full caption never ends on a small word (or a captions.no_end_words word): it opens the next caption
                carry = []
                while len(cur) > 1 and cur[-1][0].strip(CAPTION_STRIP + "!?:;…").lower() in NO_END_WORDS:
                    carry.insert(0, cur.pop())
                if len(cur) == 1 and carry and cur[0][0].strip(CAPTION_STRIP + "!?:;…").lower() in NO_END_WORDS:
                    # never leave one small word alone: keep the group together until a real word ends it
                    cur = cur + carry
                    continue
                groups.append(cur)
                cur = carry
        if cur:
            if groups and len(cur) == 1:
                groups[-1] += cur
            else:
                groups.append(cur)
        nxt = lines_[li + 1][1] if li + 1 < len(lines_) else b + 0.6
        for gi, g in enumerate(groups):
            text = " ".join(t for t, _, _ in g).upper()
            for k, v in repl.items():
                text = text.replace(k.upper(), v)
            text = re.sub(r"\s+", " ", text.translate({ord(c): None for c in CAPTION_STRIP})).strip()
            end = groups[gi + 1][0][1] if gi + 1 < len(groups) else min(b + 0.35, nxt)
            out.append((text, g[0][1], end))
    return out


def render(ad_dir, *_):
    cfg, root = load(ad_dir), Path(ad_dir)
    ls, t0, t1, audio = timeline(ad_dir, cfg)
    total = t1 - t0
    shots = sorted(cfg["shots"], key=lambda s: s["start"])
    missing = [s["id"] for s in shots if not (root / "clips" / f"{s['id']}.mp4").exists()]
    if missing:
        sys.exit(f"missing clips: {missing}")
    outside_audio = [s["id"] for s in shots if min(s["end"], t1) - max(s["start"], t0) <= 0]
    if outside_audio:
        sys.exit(f"shots outside the audio ({t0:.2f}-{t1:.2f} s): {outside_audio}. Shot start/end are seconds of the "
                 "audio take; plan them on its real timing (adtool.py lines) and make them back to back.")
    tmp = root / "final" / "_work"
    tmp.mkdir(parents=True, exist_ok=True)
    cap = cfg.get("captions", {"on": True})
    font = caption_font(cap.get("font"), cap.get("size", 64))  # one size for the whole video
    caps = caption_chunks(ls, cfg.get("caption_replace", {}), cap.get("max_words", 4)) if cap.get("on", True) else []
    font = fit_font(font, caps, cap.get("font"), cap.get("max_width", 680))

    ins, filt = [], []
    for i, s in enumerate(shots):
        dur = min(s["end"], t1) - max(s["start"], t0)
        ins += ["-i", str(root / "clips" / f"{s['id']}.mp4")]
        # never change clip speed: trim, and hold the last frame if a clip runs short
        filt.append(f"[{i}:v]trim=start={clip_start(s):.3f},setpts=PTS-STARTPTS,fps={FPS},scale={W}:{H}:"
                    f"force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,tpad=stop_mode=clone:"
                    f"stop_duration={dur:.3f},trim=duration={dur:.3f},setpts=PTS-STARTPTS[v{i}]")
    n = len(shots)
    filt.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[base]")
    last = "base"
    layers, outside = [], []
    for j, (text, a, b) in enumerate(caps):
        y = next((s.get("caption_y") for s in shots if s.get("caption_y") and s["start"] <= a < s["end"]), None)
        png = tmp / f"cap{j:02d}.png"
        xy, box = caption_png(text, y or cap.get("y", 1300), font, png, cap.get("max_width", 680))
        layers.append((png, xy, a, b))
        if not in_safe_zone(box):
            outside.append(f"caption {a:.1f}s {text!r} box {tuple(round(v) for v in box)}")
    for j, ov in enumerate(cfg.get("overlays", [])):
        png = tmp / f"ov{j:02d}.png"
        if ov.get("png"):  # a ready-made sticker/badge PNG from your editing kit
            xy, box = png_layer(ov["png"], ov.get("x", 80), ov.get("y", 400), ov.get("scale", 1.0), png)
        else:
            xy, box = headline_png(ov["lines"], ov.get("top", 400), png, ov.get("size", 50))
        layers.append((png, xy, ov.get("start", t0), ov.get("end", t0 + 3)))
        if not in_safe_zone(box):
            outside.append(f"overlay {ov.get('lines') or ov['png']} box {tuple(round(v) for v in box)}")
    if outside:
        sys.exit("outside the Reels safe zone (move with caption_y / overlay top):\n  " + "\n  ".join(outside))
    for j, (png, (x, y), a, b) in enumerate(layers):
        ins += ["-loop", "1", "-t", f"{total:.3f}", "-i", str(png)]
        # start inclusive, end exclusive, so two captions never share a frame
        filt.append(f"[{last}][{n + j}:v]overlay={x}:{y}:enable='gte(t,{max(a - t0, 0):.3f})*lt(t,{max(b - t0, 0):.3f})'[c{j}]")
        last = f"c{j}"
    fade = float(cfg.get("cut", {}).get("fade_out", 0.4))
    aidx = n + len(layers)
    ins += ["-ss", f"{t0:.3f}", "-t", f"{total:.3f}", "-i", str(audio)]
    bed = root / "music" / f"take{(cfg.get('music') or {}).get('take', 1)}.mp3"
    if mode(cfg) == "voice" and cfg.get("music") and bed.exists():
        ins += ["-t", f"{total:.3f}", "-i", str(bed)]
        vol = float(cfg["music"].get("volume", 0.18))
        filt.append(f"[{aidx + 1}:a]volume={vol},afade=t=in:d=0.3[bed]")
        filt.append(f"[{aidx}:a][bed]amix=inputs=2:duration=first:normalize=0,afade=t=out:st={total - fade:.3f}:"
                    f"d={fade:.3f},loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    else:
        filt.append(f"[{aidx}:a]afade=t=out:st={total - fade:.3f}:d={fade:.3f},loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    out = root / "final" / f"{cfg.get('name', 'ad')}.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", *ins, "-filter_complex", ";".join(filt), "-map", f"[{last}]",
         "-map", "[aout]", "-t", f"{total:.3f}", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"wrote {out} ({total:.1f} s, {n} shots, {len(caps)} captions, "
          f"{len(cfg.get('overlays', []))} overlays, all inside the safe zone)")


def frames(ad_dir, *_):
    """QA sheet: for every line, 3 frames of the final video (start, middle, end) next to the line."""
    from PIL import Image, ImageDraw
    cfg, root = load(ad_dir), Path(ad_dir)
    final = root / "final" / f"{cfg.get('name', 'ad')}.mp4"
    if not final.exists():
        sys.exit("render first")
    ls, t0, _, _ = timeline(ad_dir, cfg)
    w, h, tw = 200, 356, 420
    sheet = Image.new("RGB", (w * 3 + tw, h * len(ls)), "white")
    d = ImageDraw.Draw(sheet)
    font = caption_font(None, 22)
    for r, (text, a, b, _) in enumerate(ls):
        for c, t in enumerate([a, (a + b) / 2, b]):
            sheet.paste(grab(final, t - t0, w, h), (c * w, r * h))
        rows, line = [], ""
        for wd in text.split():
            if d.textlength((line + " " + wd).strip(), font=font) > tw - 20:
                rows.append(line)
                line = wd
            else:
                line = (line + " " + wd).strip()
        rows.append(line)
        for k, row in enumerate([f"{a - t0:.1f}-{b - t0:.1f} s"] + rows):
            d.text((w * 3 + 10, r * h + 10 + k * 28), row, fill="black", font=font)
    out = root / "final" / "qa_frames.jpg"
    sheet.save(out, quality=85)
    print("wrote", out, "- check: does every picture show what its line says?")


STEPS = {"doctor": doctor, "words": words, "lines": lines, "contact": contact, "render": render, "frames": frames}

if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in STEPS:
        sys.exit(__doc__)
    STEPS[sys.argv[1]](sys.argv[2], *sys.argv[3:])
