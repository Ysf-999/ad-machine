# Library v2, 2026-11-10 (agentchad.io). Keys only from your own environment; nothing here is account-specific.
# 2026-11-10: long words split into two captions (no global shrink), real length-proportional fallback without
#             faster-whisper, plain install messages, caps/timeline.json for qa-sniper's safe-zone check.
# 2026-11-10: a word with your "|" that does not fit is always split there (VANN|FLASKEN was shrunk instead);
#             WHISPER_MODEL from ~/.agentchad/settings.env, default small (the library's one default model).
"""PROJ=<dir> VIDEO=<video> LANG_CODE=<iso code> [CAP_Y=0.709 FONT_PX=auto CAP_MIN_PX=auto OUT=caps WORDS_JSON=<file>
 CAP_FIXES=<json> FONT=<ttf> WHISPER_MODEL=small] captions.py
Word-timed captions as PNGs plus an ffconcat list for an ffmpeg overlay (Homebrew ffmpeg often has no drawtext).
Default mode: times every word of the <PROJ>/schedule.json lines with faster-whisper. Without faster-whisper (or when
Whisper hears a different number of words) the words are timed by their share of letters inside each line: a little
less exact, still in sync line by line. The script says which one it used per line.
WORDS_JSON mode (songs, or keeping the original audio): a JSON list [[start,end,"word"],...] used as-is.
Style: one word per caption (short words grouped with the next), white, soft shadow, upper case, CAP_Y down the frame.
Rules built in:
 - ONE font size for the whole video (FONT_PX, default 6.25 % of the height = 120 px at 1920 with Bebas Neue, 5 %
   with a wider fallback font).
 - A caption too wide for the safe zone at that size: a word with a "|" from you is always SPLIT there; otherwise
   a word of up to 12 letters gets its own slightly smaller size, and a longer word is SPLIT into two captions (Norwegian, Swedish, Danish, German and Dutch compounds), at a "|" you put
   in the caption text (ettermiddags|trøttheten) or else at the likeliest joint near the middle (a linking s, two
   consonants), with a hyphen on the first part. A piece that still does not fit gets its own smaller size, and only
   if that is not enough is it split again. Never below CAP_MIN_PX (default 75 % of FONT_PX). Every other caption
   keeps the full size.
 - Every caption inside the 9:16 safe zone; , . " and curly quotes stripped. CAP_FIXES = JSON {"misheard": "Right"}.
Writes <OUT>/capNNN.png, <OUT>/list.ffconcat, <OUT>/events.json and <OUT>/timeline.json (for qa-sniper --timeline).
Exit codes: 0 OK, 1 bad input or a caption cannot fit, 3 a package is missing (the message says what to install)."""
import os, json, re, subprocess, sys
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py import need, setting  # noqa: E402

if 'PROJ' not in os.environ or 'VIDEO' not in os.environ:
    sys.exit(__doc__)
if not os.environ.get('LANG_CODE') and not os.environ.get('WORDS_JSON'):
    sys.exit('Set LANG_CODE to the target language code (for example no, sv, da, de, fr, nl, en), or use WORDS_JSON.')
NO_WHISPER = need(['PIL'], optional=[] if os.environ.get('WORDS_JSON') else ['faster_whisper'])
from PIL import Image, ImageDraw, ImageFont, ImageFilter  # noqa: E402

P = os.path.expanduser(os.environ['PROJ']); V = os.path.expanduser(os.environ['VIDEO']); OUT = os.environ.get('OUT', 'caps')
FONT_CANDIDATES = [os.environ.get('FONT'), os.path.expanduser('~/Library/Fonts/BebasNeue-Regular.ttf'),
                   '/System/Library/Fonts/Supplemental/Arial Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']
FONT = next((f for f in FONT_CANDIDATES if f and os.path.exists(os.path.expanduser(f))), None)
if not FONT:
    sys.exit('No caption font found. Install Bebas Neue (free on Google Fonts) or set FONT=<path to a bold .ttf>.')
if FONT != FONT_CANDIDATES[0] and 'Bebas' not in FONT:
    print('note: Bebas Neue not found, using', FONT)
FONT = os.path.expanduser(FONT)
FIXES = json.loads(os.environ['CAP_FIXES']) if os.environ.get('CAP_FIXES') else {}
if not os.path.exists(V):
    sys.exit(f'VIDEO not found: {V}')
pr = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,r_frame_rate:format=duration', '-of', 'json', V], capture_output=True, text=True).stdout)
W = pr['streams'][0]['width']; H = pr['streams'][0]['height']; n, d = pr['streams'][0]['r_frame_rate'].split('/'); FPS = float(n) / float(d); DUR = float(pr['format']['duration'])
# default size: 6.25 % of the height for the narrow Bebas Neue, 5 % for a wide fallback font such as Arial Bold
CY = int(H * float(os.environ.get('CAP_Y', '0.709'))); FPX = int(os.environ.get('FONT_PX', round(H * (0.0625 if 'Bebas' in FONT else 0.05))))
MINPX = int(os.environ.get('CAP_MIN_PX', round(FPX * 0.75)))
os.makedirs(f'{P}/{OUT}', exist_ok=True)


def fix(t):
    core = re.sub(r'[^\w%|-]', '', t)
    return t.replace(core, FIXES[core.lower()]) if core.lower() in FIXES else t


clean = lambda t: re.sub(r'\s+', ' ', re.sub(r'[,.\"“”«»…]', '', t)).strip()


def group(toks, times, line_end):
    g = []; i = 0
    while i < len(toks):
        if len(re.sub(r'\W', '', toks[i])) <= 2 and i + 1 < len(toks) and len(toks[i]) + len(toks[i + 1]) <= 10:
            g.append((toks[i] + ' ' + toks[i + 1], times[i][0])); i += 2
        else:
            g.append((toks[i], times[i][0])); i += 1
    return [[clean(t).upper(), a, (g[j + 1][1] if j + 1 < len(g) else line_end)] for j, (t, a) in enumerate(g) if clean(t)]


def proportional(toks, start, dur):
    tot = sum(len(t) for t in toks) or 1; acc = 0; times = []
    for t in toks:
        a = acc / tot * dur; acc += len(t); times.append((start + a, start + acc / tot * dur))
    return times


events = []
if os.environ.get('WORDS_JSON'):
    words = json.load(open(os.path.expanduser(os.environ['WORDS_JSON'])))
    phrase = []  # split into phrases at gaps > 0.6 s so captions disappear in pauses
    for k, (a, b, w) in enumerate(words):
        phrase.append((a, b, fix(w))); nxt = words[k + 1][0] if k + 1 < len(words) else None
        if nxt is None or nxt - b > 0.6:
            events += group([x[2] for x in phrase], [(x[0], x[1]) for x in phrase], phrase[-1][1] + 0.15); phrase = []
else:
    if not os.path.exists(f'{P}/schedule.json'):
        sys.exit(f'{P}/schedule.json not found: run fit.py first.')
    m = None
    if NO_WHISPER:
        print('note: faster-whisper is not installed in this Python, so words are timed by their share of letters '
              'inside each line (a little less exact). For word-exact timing run it with the shared Python '
              '(AGENTCHAD_PY in ~/.agentchad/settings.env).')
    else:
        from faster_whisper import WhisperModel
        mname = setting('WHISPER_MODEL', 'small')
        print(f'Whisper model {mname} (the first use downloads it once: small about 0.5 GB, large-v3-turbo about 1.6 GB)', flush=True)
        m = WhisperModel(mname, device=os.environ.get('WHISPER_DEVICE', 'cpu'), compute_type='int8')
    for s in json.load(open(f'{P}/schedule.json')):
        toks = [fix(t) for t in s['cap'].split()]
        dur = s['end'] - s['start']; how = 'proportional (no whisper)'
        times = proportional(toks, s['start'], dur)
        if m is not None:
            segs, _ = m.transcribe(s['file'], language=os.environ['LANG_CODE'], word_timestamps=True)
            words = [w for sg in segs for w in sg.words]
            if len(words) == len(toks):
                times = [(s['start'] + w.start, s['start'] + w.end) for w in words]; how = 'whisper'
            else:
                how = f'proportional (whisper heard {len(words)} words, caption has {len(toks)})'
        ev = group(toks, times, s['end'] + 0.12); events += ev
        print(f"{s['i']:02d} {how}: " + ' | '.join(e[0] for e in ev), flush=True)

# ---- sizing: one font size; split what does not fit; shrink only a leftover piece, never below the floor
fonts = {}
F = lambda px: fonts.setdefault(px, ImageFont.truetype(FONT, px))
SH = max(1, FPX // 48)
_k = W / 1080
LIM_Y = (347 * H / 1920, 1426 * H / 1920)


def limit(px):
    # 9:16 safe zone (at 1080x1920: x 71-1027, y 347-1426; below y 868 only x <= 886), scaled to this frame
    r = (886 if CY + px / 2 > 868 * H / 1920 else 1027) * _k
    return int(2 * min(W / 2 - 71 * _k, r - W / 2) - 2 * SH)


width = lambda t, px: F(px).getbbox(t.replace('|', ''))[2] - F(px).getbbox(t.replace('|', ''))[0]
VOW = set('AEIOUYÆØÅÄÖÜÉÈÁÀ')


def split_word(w):
    """Two pieces of a too-long word: at a '|' if given, else near the middle at a syllable joint."""
    if '|' in w:
        a, b = w.split('|', 1)
        return [a + '-', b]
    if '-' in w.strip('-'):
        k = w.index('-', 1)
        return [w[:k + 1], w[k + 1:]]
    best = None
    for k in range(3, len(w) - 2):
        score = abs(k - len(w) / 2)
        if w[k - 1] not in VOW and w[k] not in VOW and w[k - 1] != w[k]:
            score -= 1.5          # between two consonants: a usual compound or syllable joint
        if w[k - 1] == 'S' and w[k - 2] not in VOW and w[k] not in VOW:
            score -= 2.5          # the linking s of Nordic and German compounds (ettermiddags|trøttheten)
        if best is None or score < best[0]:
            best = (score, k)
    k = best[1] if best else len(w) // 2
    return [w[:k] + '-', w[k:]]


sized = []   # [text, a, b, px]


def own_size(t):
    """The largest size >= MINPX at which this caption fits, or None."""
    px = FPX
    while px > MINPX and width(t, px) > limit(px):
        px -= 2
    return px if width(t, px) <= limit(px) else None


def pieces_of(t, a, b, parts):
    tot = sum(len(p) for p in parts); acc = 0; out = []
    for p in parts:
        pa = a + acc / tot * (b - a); acc += len(p); out.append((p, pa, a + acc / tot * (b - a), True))
    return out


for t, a, b in events:
    todo = [(t, a, b, False)]
    while todo:
        t, a, b, is_piece = todo.pop(0)
        if width(t, FPX) <= limit(FPX):
            sized.append([t.replace('|', ''), a, b, FPX]); continue
        letters = len(re.sub(r'\W', '', t))
        if ' ' in t:   # a grouped pair: show the words one by one
            todo = [(p, pa, pb, False) for p, pa, pb, _ in pieces_of(t, a, b, t.split(' '))] + todo; continue
        if '|' in t and not is_piece:   # the user marked where this word may be split: always split there
            ps = pieces_of(t, a, b, split_word(t))
            print(f'split "{t.replace("|", "")}" at your | -> ' + ' / '.join(q[0] for q in ps))
            todo = ps + todo; continue
        px = own_size(t)
        if px and (is_piece or letters <= 12):
            print(f'note: "{t.replace("|", "")}" gets its own size {px}px (the rest stay {FPX}px)')
            sized.append([t.replace('|', ''), a, b, px]); continue
        parts = split_word(t)
        if letters >= 6 and all(len(re.sub(r'\W', '', q)) >= 3 for q in parts):
            ps = pieces_of(t, a, b, parts)
            print(f'split "{t.replace("|", "")}" -> ' + ' / '.join(q[0] for q in ps))
            todo = ps + todo; continue
        if px:
            sized.append([t.replace('|', ''), a, b, px]); continue
        sys.exit(f'Caption "{t}" does not fit the safe zone even at {MINPX}px. Put a "|" where the word may be '
                 'split in lines.json (cap), or shorten that caption.')
for t, a, b, px in sized:
    if not (LIM_Y[0] <= CY - px / 2 and CY + px / 2 <= LIM_Y[1]):
        sys.exit(f'CAP_Y {CY} puts captions outside the safe zone (y {int(LIM_Y[0])}-{int(LIM_Y[1])}). Move it.')


def render(text, px, path):
    font = F(px); sh = max(1, px // 48)
    bb = font.getbbox(text); tw = bb[2] - bb[0]; capt = font.getbbox('M'); x = (W - tw) // 2 - bb[0]; y = CY - (capt[1] + capt[3]) // 2
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0)); ImageDraw.Draw(im).text((x + sh * 2.5, y + sh * 4), text, font=font, fill=(0, 0, 0, 150)); im = im.filter(ImageFilter.GaussianBlur(sh * 3.5))
    ImageDraw.Draw(im).text((x, y), text, font=font, fill=(255, 255, 255, 255)); im.save(path)
    return {'x': int(x + bb[0]), 'y': int(y + bb[1]), 'w': int(tw), 'h': int(bb[3] - bb[1])}


Image.new('RGBA', (W, H), (0, 0, 0, 0)).save(f'{P}/{OUT}/blank.png')
q = lambda t: round(t * FPS) / FPS
L = ["ffconcat version 1.0"]; cur = 0.0; k = 0; tl = []
for j, (t, a, b, px) in enumerate(sized):
    a = q(a); b = q(b)
    if j + 1 < len(sized):
        b = min(b, q(sized[j + 1][1]))
    if a > cur:
        L += ["file blank.png", f"duration {a - cur:.3f}"]
    a = max(a, cur)
    if b <= a:
        continue
    p = f'cap{k:03d}.png'; k += 1; box = render(t, px, f'{P}/{OUT}/{p}'); L += [f"file {p}", f"duration {b - a:.3f}"]; cur = b
    tl.append({'text': t, **box, 'start': round(a, 3), 'end': round(b, 3), 'px': px})
L += ["file blank.png", f"duration {max(DUR - cur, 0.04):.3f}", "file blank.png"]
open(f'{P}/{OUT}/list.ffconcat', 'w').write('\n'.join(L) + '\n')
json.dump([[t, a, b] for t, a, b, _ in sized], open(f'{P}/{OUT}/events.json', 'w'), ensure_ascii=False)
json.dump({'width': W, 'height': H, 'caption_style': 'plain', 'caption_size': FPX, 'captions': tl},
          open(f'{P}/{OUT}/timeline.json', 'w'), ensure_ascii=False, indent=1)
sizes = sorted({c['px'] for c in tl})
print(f'captions: {k} images, {W}x{H} @ {FPS:g} fps, font {FPX}px' + (f' (own smaller size: {sizes[:-1]})' if len(sizes) > 1 else '')
      + f', y={CY}, last end {cur:.2f}/{DUR:.2f}. qa-sniper: --timeline {P}/{OUT}/timeline.json')
