# Library v2, 2026-11-09 (agentchad.io). Keys only from your own environment; nothing here is account-specific.
"""recaps_box.py <caps_dir> <out_dir> <W> <H> <fps> <dur> [cy]
Re-renders the events.json that captions.py wrote as captions on a rounded box (default black text on white), for places
where the original caption was wiped and a blur would show. Kept inside the 9:16 safe zone (x 71-1027, y 347-1426;
below y 868 only x <= 886, scaled to the frame). Short gaps (< 0.8 s) keep the previous box up so no blur shows.
One font size for the whole video, set by the widest caption. Punctuation , . " and curly quotes stripped.
The box hugs the text: measure the original's box (colour, height, padding) and copy it with the env below.
Env: BOX_RGB="255,255,255" TEXT_RGB="0,0,0" FONT_PX (at 1080 wide, default 120) BOX_H (default 140) PAD_X (default 30)
  RADIUS (default 18, 0 = square) STROKE_PX + STROKE_RGB (thin edge round the letters, default none) FONT=<ttf>
  EVENTS (file name in caps_dir, default events.json). An event may carry [text,a,b,x0,x1]: the box then also covers
  x0..x1 (+COVER_MARGIN px, default 12). Use that only when asked: a box widened over the old caption's area looks wrong."""
import sys, json, os, re
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py import need  # noqa: E402
if len(sys.argv) < 7:
    sys.exit(__doc__)
need(['PIL'])
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
cd, od, W, H, FPS, DUR = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5]), float(sys.argv[6])
k = W / 1080; CY = int(sys.argv[7]) if len(sys.argv) > 7 else int(H * 0.69)
rgb = lambda s: tuple(int(v) for v in s.split(',')) + (255,)
BOX = rgb(os.environ.get('BOX_RGB', '255,255,255')); FG = rgb(os.environ.get('TEXT_RGB', '0,0,0'))
FPX = int(float(os.environ.get('FONT_PX', 120)) * k); PADX = int(float(os.environ.get('PAD_X', 30)) * k)
BOXH = int(float(os.environ.get('BOX_H', 140)) * k); R = int(float(os.environ.get('RADIUS', 18)) * k)
SW = round(float(os.environ.get('STROKE_PX', 0)) * k); SF = rgb(os.environ.get('STROKE_RGB', '40,40,40'))
SAFE_L = 71 * k; SAFE_R = (886 if CY + BOXH / 2 > 868 * k else 1027) * k; CX = W / 2
MAXW = 2 * min(CX - SAFE_L, SAFE_R - CX)
FONT_CANDIDATES = [os.environ.get('FONT'), os.path.expanduser('~/Library/Fonts/BebasNeue-Regular.ttf'),
                   '/System/Library/Fonts/Supplemental/Arial Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']
FONT = next((f for f in FONT_CANDIDATES if f and os.path.exists(os.path.expanduser(f))), None)
if not FONT:
    sys.exit('No caption font found. Install Bebas Neue (free on Google Fonts) or set FONT=<path to a bold .ttf>.')
FONT = os.path.expanduser(FONT); os.makedirs(od, exist_ok=True)
clean = lambda t: re.sub(r'\s+', ' ', re.sub(r'[,.\"“”«»…]', '', t)).strip()
ev = [(clean(e[0]), e[1], e[2], e[3:]) for e in json.load(open(f"{cd}/{os.environ.get('EVENTS', 'events.json')}"))]
CM = float(os.environ.get('COVER_MARGIN', 12))
ev = [e for e in ev if e[0]]
base = ImageFont.truetype(FONT, FPX)
widest = max(ev, key=lambda e: base.getbbox(e[0])[2] - base.getbbox(e[0])[0])[0]
ww = base.getbbox(widest)[2] - base.getbbox(widest)[0]
if ww + 2 * PADX > MAXW:
    FPX = int(FPX * (MAXW - 2 * PADX) / ww)
FNT = ImageFont.truetype(FONT, FPX)
if not (347 * k <= CY - BOXH / 2 and CY + BOXH / 2 <= 1426 * k):
    sys.exit(f'box y {CY - BOXH/2:.0f}-{CY + BOXH/2:.0f} is outside the safe zone (y {347*k:.0f}-{1426*k:.0f}). Move cy.')
q = lambda t: round(t * FPS) / FPS
def render(text, path, cov=()):
    bb = FNT.getbbox(text); tw = bb[2] - bb[0]
    capt = FNT.getbbox('M'); x0 = CX - tw / 2 - PADX; x1 = CX + tw / 2 + PADX
    if cov:
        x0 = min(x0, cov[0] - CM); x1 = max(x1, cov[1] + CM)
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    (d.rounded_rectangle if R else lambda b, radius, fill: d.rectangle(b, fill=fill))([x0, CY - BOXH / 2, x1, CY + BOXH / 2], radius=R, fill=BOX)
    d.text((CX - tw / 2 - bb[0], CY - (capt[1] + capt[3]) / 2), text, font=FNT, fill=FG, stroke_width=SW, stroke_fill=SF); im.save(path)
    return x0, x1
Image.new('RGBA', (W, H), (0, 0, 0, 0)).save(f'{od}/blank.png')
L = ["ffconcat version 1.0"]; cur = 0.0; n = 0; ext = []
for j, (t, a, b, cov) in enumerate(ev):
    a = q(a); b = q(b)
    if j + 1 < len(ev):
        nx = q(ev[j + 1][1]); b = nx if nx - b < 0.8 else min(b, nx)
    if a > cur:
        L += ["file blank.png", f"duration {a - cur:.3f}"]
    a = max(a, cur)
    if b <= a:
        continue
    p = f'cap{n:03d}.png'; n += 1; ext.append(render(t, f'{od}/{p}', cov)); L += [f"file {p}", f"duration {b - a:.3f}"]; cur = b
L += ["file blank.png", f"duration {max(DUR - cur, 0.04):.3f}", "file blank.png"]
open(f'{od}/list.ffconcat', 'w').write('\n'.join(L) + '\n')
print(f'{n} boxes, font {FPX}px (widest "{widest}"), x range {min(e[0] for e in ext):.0f}-{max(e[1] for e in ext):.0f}, box y {CY - BOXH / 2:.0f}-{CY + BOXH / 2:.0f}, safe x {SAFE_L:.0f}-{SAFE_R:.0f}')
