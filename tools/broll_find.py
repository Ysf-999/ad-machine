#!/usr/bin/env python3
"""Find reusable AI b-roll from your own approved ads (library/approved_broll/index.json; not shipped, optional).

  python3 tools/broll_find.py couch hair                 # words must all appear in the line/description/ad name
  python3 tools/broll_find.py --style claymation --subject product-demo
  python3 tools/broll_find.py --style pixar-3d --product --min-dur 2 --max 12
  python3 tools/broll_find.py --subject stairs --style ai-realistic --copy /tmp/pick
  python3 tools/broll_find.py --list                      # styles, subjects, worlds with counts

Owner rules (2026-11-09): --style is required (animated clips only reuse within their own style); Halloween-themed clips were removed from the library.
Styles: claymation, pixar-3d, cartoon-2d, diorama, ai-realistic (Kling/Seedance realistic hooks + b-roll).
--world keeps characters consistent (all clips from one ad world, e.g. hw1-clay-apology).
Use in an animated plan: set the beat's  "lib": "<lib_id>"  and ad.py copies the clip in (no kie spend).
--copy DIR hard-links the picks into DIR for rawedit / HyperFrames edits.
Prints caveats when a clip has them: read them before reusing.
"""
import argparse, collections, json, os, sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # repo root
_IDX = f'{R}/library/approved_broll/index.json'
if not os.path.exists(_IDX):
    sys.exit(f"no approved b-roll library yet ({_IDX} missing): nothing to reuse, generate fresh clips")
d = json.load(open(_IDX))
clips = d['clips']

ap = argparse.ArgumentParser()
ap.add_argument('words', nargs='*')
ap.add_argument('--style'); ap.add_argument('--subject', action='append', default=[])
ap.add_argument('--world'); ap.add_argument('--theme'); ap.add_argument('--role')
ap.add_argument('--product', action='store_true'); ap.add_argument('--no-product', action='store_true')
ap.add_argument('--pet', action='store_true'); ap.add_argument('--person', action='store_true')
ap.add_argument('--silent', action='store_true', help='only clips with no audio track')
ap.add_argument('--min-dur', type=float, default=0); ap.add_argument('--max-dur', type=float, default=999)
ap.add_argument('--max', type=int, default=25); ap.add_argument('--copy'); ap.add_argument('--list', action='store_true')
ap.add_argument('--json', action='store_true')
a = ap.parse_args()

if a.list:
    for title, key in (('styles', lambda c: [c['style']]), ('subjects', lambda c: c['subjects']),
                       ('worlds', lambda c: [c['world']]), ('themes', lambda c: [t for t in c['tags'] if t in ('halloween', 'christmas')])):
        print(f'\n{title}:')
        cnt = collections.Counter(x for c in clips for x in key(c))
        print('  ' + ', '.join(f'{k} ({v})' for k, v in cnt.most_common()))
    sys.exit()

def ok(c):
    text = ' '.join(str(c.get(k) or '') for k in ('vo', 'visual', 'shows', 'prompt', 'ad', 'lib_id')).lower()
    return (all(w.lower() in text for w in a.words)
            and (not a.style or c['style'] == a.style)
            and all(s in c['subjects'] for s in a.subject)
            and (not a.world or a.world in c['world'])
            and (not a.theme or a.theme in c['tags'])
            and (not a.role or c['role'] == a.role)
            and (not a.product or c.get('has_product')) and (not a.no_product or not c.get('has_product'))
            and (not a.pet or c['has_pet']) and (not a.person or c['has_person'])
            and (not a.silent or not c['audio'])
            and a.min_dur <= (c['dur'] or 0) <= a.max_dur)

if not a.style:
    sys.exit("Pass --style (claymation | pixar-3d | cartoon-2d | diorama | ai-realistic). Owner rule: animated b-roll is reused only inside its own style; claymation clips for claymation ads, Pixar for Pixar, etc.")
hits = [c for c in clips if ok(c)]
# prefer: product demo + longer + high confidence first
hits.sort(key=lambda c: (c.get('confidence') != 'high', -(c['dur'] or 0)))
print("REMINDER: reuse is optional. Only use a clip if the scene is the exact same theme and shot and fits perfectly; otherwise generate fresh.")
print(f'{len(hits)} match(es); showing {min(len(hits), a.max)}\n')
if a.json:
    print(json.dumps(hits[:a.max], indent=1)); sys.exit()
for c in hits[:a.max]:
    desc = (c.get('visual') or c.get('shows') or c.get('vo') or '')[:130].replace('\n', ' ')
    print(f"{c['lib_id']}  [{c['style']}, {c['dur']}s{', product' if c.get('has_product') else ''}{', audio' if c['audio'] else ', silent'}]")
    print(f"   {c['file']}")
    print(f"   {c['ad']} | {desc}")
    if c.get('caveats'):
        print(f"   caveat: {c['caveats'][:160]}")
if a.copy:
    os.makedirs(a.copy, exist_ok=True)
    for c in hits[:a.max]:
        dst = f"{a.copy}/{c['lib_id']}.mp4"
        if not os.path.exists(dst):
            os.link(f"{R}/{c['file']}", dst)
    print(f'\nlinked {min(len(hits), a.max)} clip(s) into {a.copy}')
