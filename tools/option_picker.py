"""Clip / hook options for one slot -> a local picker page. Never Frame.io (owner 2026-11-22: "Frame.io is when we're
dissecting a full video and doing revisions"; a single clip with options goes in a picker, like the keyframe picker).

Usage:
  option_picker.py <project> --slot "<slot name>" <clip> <clip> ... [--slot "<slot name>" <clip> ...] [--why "<one line>"] [--no-open]
      clips are video or image files (any path on this Mac). Writes <project>/OPTIONS.json + OPTIONS.html and opens it.
      The ad board lists it under "To approve" until he sends his picks.
  option_picker.py <project> --rebuild [--no-open]     rebuild the page from OPTIONS.json (after adding or replacing options)
  option_picker.py <project> --picks                   print what he picked (OPTIONS_PICK.json)

He picks one option per slot (or "none of these" with a note), can leave a note on any option, and presses
"Send to Claude": the board helper (cloud/frame_review.py, 127.0.0.1:8790) saves OPTIONS_PICK.json in the project and
logs each pick to feedback/log.jsonl (taste rule T29: learn his picks). If the helper is not running the page copies
the picks as text instead. Options are told apart by their name under the video only: nothing is drawn on the
picture (taste rule T52).
"""
import html
import json
import pathlib
import re
import secrets
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
VIDEO = ('.mp4', '.mov', '.m4v', '.webm')
IMAGE = ('.png', '.jpg', '.jpeg', '.webp')


def board_token():
    f = ROOT / 'cloud' / 'controller' / 'board-token'
    try:
        t = f.read_text().strip()
    except OSError:
        t = ''
    if len(t) < 20:
        t = secrets.token_urlsafe(24)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(t)
        f.chmod(0o600)
    return t


GENERIC = {'master', 'cut', 'clip', 'video', 'final', 'output', 'out', 'render'}


def raw_name(path):
    """The part of the path that tells this option apart: the file name, or its folder for MASTER.mp4 and the like."""
    p = pathlib.Path(path)
    return p.parent.name if p.stem.lower() in GENERIC else p.stem


def nice(text):
    """"green-sofa_take2" -> "Green sofa take2"."""
    s = re.sub(r'[_-]+', ' ', str(text)).strip()
    return (s[:1].upper() + s[1:])[:80] or 'Option'


def name_slot(paths):
    """Readable names for one slot's options, with the part they all share cut off
    ("washer-opt-demo-option-a---green-sofa" ... -> "A green sofa", "B grey duvet" ...)."""
    raws = [raw_name(p) for p in paths]
    words = [re.split(r'[_\s-]+', r.strip('-_ ')) for r in raws]
    k = 0
    while len(raws) > 1 and all(len(w) > k + 1 for w in words) and len({w[k].lower() for w in words}) == 1:
        k += 1
    names = [nice(' '.join(w[k:])) for w in words]
    return names if len(set(names)) == len(names) else [nice(r) for r in raws]


def parse(args):
    slots, why, cur = [], '', None
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--slot':
            cur = {'name': args[i + 1].strip(), 'options': []}
            slots.append(cur)
            i += 2
            continue
        if a == '--why':
            why = args[i + 1]
            i += 2
            continue
        if a.startswith('--'):
            i += 1
            continue
        if cur is None:
            sys.exit('name the slot first: --slot "<slot name>" <clip> <clip> ...')
        f = pathlib.Path(a).expanduser().resolve()
        if not f.is_file():
            sys.exit(f'not a file: {a}')
        if f.suffix.lower() not in VIDEO + IMAGE:
            sys.exit(f'not a video or image: {a}')
        cur['options'].append({'id': f"{len(slots)}{chr(96 + len(cur['options']) + 1)}", 'file': str(f)})
        i += 1
    for s in slots:
        for o, n in zip(s['options'], name_slot([o['file'] for o in s['options']])):
            o['name'] = n
        if len(s['options']) < 2:
            sys.exit(f"slot '{s['name']}' needs at least 2 options (got {len(s['options'])})")
    if not slots:
        sys.exit(__doc__)
    return slots, why


def stamp(slots):
    """Changes when any option file changes: a new set of options starts with empty choices."""
    parts = []
    for s in slots:
        for o in s['options']:
            p = pathlib.Path(o['file'])
            parts.append(f"{o['id']}={p.name}@{int(p.stat().st_mtime) if p.exists() else 0}")
    return ';'.join(parts)


def media(o):
    p = pathlib.Path(o['file'])
    if not p.exists():
        return '<div class="gone">file missing</div>'
    uri = html.escape(p.as_uri())
    if p.suffix.lower() in IMAGE:
        return f'<img src="{uri}" alt="" loading="lazy">'
    return f'<video src="{uri}#t=0.5" controls muted loop playsinline preload="auto"></video>'   # #t: a still frame shows before play


def page(proj, d):
    ad = d['ad']
    blocks = []
    for k, s in enumerate(d['slots']):
        cards = ''.join(f'''
   <label class="opt" data-opt="{html.escape(o['id'])}">
    <div class="m">{media(o)}</div>
    <div class="row"><input type="radio" name="s{k}" value="{html.escape(o['id'])}"><b>{html.escape(o['name'])}</b></div>
    <input type="text" class="note" placeholder="Note on this one (optional)">
   </label>''' for o in s['options'])
        blocks.append(f'''
 <section class="slot" data-slot="{k}">
  <h2>{html.escape(s['name'])} <span>{len(s['options'])} options · pick one</span></h2>
  <div class="grid">{cards}</div>
  <div class="none"><label><input type="radio" name="s{k}" value="none"> None of these</label>
   <input type="text" class="slotnote" placeholder="What to look for instead, or anything else about this slot"></div>
 </section>''')
    script = r'''
const AD=__AD__,TOKEN=__TOKEN__,SIG=__SIG__,API='http://127.0.0.1:8790/options',KEY='options-'+AD;
const slots=()=>[...document.querySelectorAll('.slot')];
function get(k,d){try{const v=JSON.parse(localStorage.getItem(k));return v==null?d:v}catch(e){return d}}
function put(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch(e){}}
function state(){return slots().map(s=>{const r=s.querySelector('input[type=radio]:checked');const notes={};
  s.querySelectorAll('.opt').forEach(o=>{const v=o.querySelector('.note').value.trim();if(v)notes[o.dataset.opt]=v});
  return {pick:r?r.value:'',note:s.querySelector('.slotnote').value.trim(),notes}})}
{const s=get(KEY,null);if(s&&s.sig===SIG)s.v.forEach((v,i)=>{const el=slots()[i];if(!el)return;
  if(v.pick){const r=el.querySelector(`input[value="${v.pick}"]`);if(r)r.checked=true}
  el.querySelector('.slotnote').value=v.note||'';el.querySelectorAll('.opt').forEach(o=>{o.querySelector('.note').value=(v.notes||{})[o.dataset.opt]||''})})}
function mark(){slots().forEach(s=>s.querySelectorAll('.opt').forEach(o=>o.classList.toggle('on',o.querySelector('input').checked)))}
function keep(){put(KEY,{sig:SIG,v:state()});mark()}
document.addEventListener('change',keep);document.addEventListener('input',keep);mark();
function say(t,bad){const m=document.getElementById('msg');m.textContent=t;m.className=bad?'bad':'ok'}
function text(){const v=state();let out=`PICKS ${AD}\n`;slots().forEach((s,i)=>{const name=s.querySelector('h2').firstChild.textContent.trim();
  const p=v[i].pick,o=p&&p!=='none'?s.querySelector(`[data-opt="${p}"] b`).textContent:'none of these';
  out+=`${name}: ${o}${v[i].note?' — '+v[i].note:''}\n`;for(const [id,n] of Object.entries(v[i].notes))out+=`  note on ${s.querySelector(`[data-opt="${id}"] b`).textContent}: ${n}\n`});return out}
function copyText(why){navigator.clipboard.writeText(text()).then(()=>say((why||'')+'Picks copied. Paste them to Claude.',!!why),()=>say('Could not copy.',true))}
async function send(){const v=state(),miss=v.map((x,i)=>x.pick?null:i+1).filter(Boolean);
  if(miss.length){say('Pick one option (or "None of these") in every section first.',true);slots()[miss[0]-1].scrollIntoView({behavior:'smooth'});return}
  if(v.some(x=>x.pick==='none'&&!x.note)){say('Say what to look for instead where you chose "None of these".',true);return}
  say('Sending…');let j;
  try{const r=await fetch(API,{method:'POST',headers:{'Content-Type':'text/plain'},body:JSON.stringify({ad:AD,token:TOKEN,sig:SIG,slots:v})});j=await r.json()}
  catch(e){copyText('The board helper is not running, so nothing was sent. ');return}
  if(!j.ok){say(j.error||'Not saved.',true);return}
  const at=new Date().toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});put(KEY+'-sent',{sig:SIG,at,m:j.message});say('Sent '+at+'. '+j.message)}
{const z=get(KEY+'-sent',null);if(z&&z.sig===SIG)say('Sent '+z.at+'. '+z.m)}
'''
    script = (script.replace('__AD__', json.dumps(ad)).replace('__TOKEN__', json.dumps(board_token())).replace('__SIG__', json.dumps(d['sig']))
              .replace('</', '<\\/'))
    why = f'<p class="why">{html.escape(d["why"])}</p>' if d.get('why') else ''
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pick — {html.escape(ad)}</title><style>
body{{font-family:-apple-system,system-ui,sans-serif;margin:0;background:#111;color:#eee}}
header{{position:sticky;top:0;z-index:5;background:#1b1b1b;padding:12px 20px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;border-bottom:1px solid #333}}
button{{background:#ffd400;border:0;padding:8px 14px;border-radius:6px;font-weight:700;cursor:pointer;color:#111;font-size:14px}}
a.alt{{color:#999;font-size:13px;cursor:pointer;text-decoration:underline}} #msg{{font-size:14px}} #msg.ok{{color:#7ddc9a}} #msg.bad{{color:#ff8a7a}}
.why{{color:#aaa;margin:16px 20px 0;max-width:80ch}}
.slot{{padding:20px;border-bottom:1px solid #333}} h2{{margin:0 0 14px;font-size:20px}} h2 span{{color:#888;font-size:13px;font-weight:400;margin-left:8px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:16px}}
.opt{{display:block;background:#1a1a1a;border:2px solid #2a2a2a;border-radius:10px;padding:8px;cursor:pointer}} .opt.on{{border-color:#ffd400}}
.m video,.m img{{width:100%;aspect-ratio:9/16;object-fit:cover;border-radius:6px;background:#000;display:block}} .gone{{aspect-ratio:9/16;display:grid;place-items:center;color:#f88}}
.row{{display:flex;gap:8px;align-items:center;margin:8px 2px 6px;font-size:14px}}
.note,.slotnote{{width:100%;box-sizing:border-box;padding:6px;background:#222;color:#eee;border:1px solid #444;border-radius:4px}}
.none{{margin-top:14px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}} .none .slotnote{{flex:1;min-width:260px;width:auto}}
</style></head><body>
<header><b>{html.escape(ad)}</b> <span style="color:#999">{"Pick one clip" if len(d["slots"]) == 1 else f"Pick one clip in each of the {len(d['slots'])} sections"}</span>
<button onclick="send()">Send to Claude</button> <a class="alt" onclick="copyText()">copy picks instead</a> <span id="msg"></span></header>
{why}{"".join(blocks)}
<script>{script}</script></body></html>'''


def write(proj, d, open_it=True):
    d['sig'] = stamp(d['slots'])
    (proj / 'OPTIONS.json').write_text(json.dumps(d, indent=1))
    (proj / 'OPTIONS.html').write_text(page(proj, d))
    print(proj / 'OPTIONS.html')
    if open_it:
        subprocess.run(['open', str(proj / 'OPTIONS.html')])


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        sys.exit(__doc__)
    proj = pathlib.Path(argv[0])
    if not proj.is_absolute() and not proj.exists() and '/' not in argv[0]:   # a bare name = a project folder
        proj = ROOT / 'projects' / argv[0]
    proj = proj.resolve()
    proj.mkdir(parents=True, exist_ok=True)
    rest = argv[1:]
    if '--picks' in rest:
        f = proj / 'OPTIONS_PICK.json'
        print(f.read_text() if f.exists() else 'no picks sent yet')
        return
    if '--rebuild' in rest:
        d = json.loads((proj / 'OPTIONS.json').read_text())
    else:
        slots, why = parse(rest)
        d = {'ad': proj.name, 'made_at': time.time(), 'why': why, 'slots': slots}
    write(proj, d, '--no-open' not in rest)


if __name__ == '__main__':
    main(sys.argv[1:])
