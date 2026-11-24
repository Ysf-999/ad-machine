"""Pre-render shot check for a real-footage (rawedit voiceover-mode) ad: look at every PLANNED shot before rendering.

For each shot in plan.shots it grabs 3 frames from the source clip at the planned in-point, pairs them with the line
spoken over that shot, and asks Claude (through claude_client: images never enter the calling session) whether the
shot holds up against the owner's taste rules. Built 2026-11-21 after the Rug Cleaner batch: wrong moment cards put a
clip with a burned-in graphic, cute faces on problem lines and a demo take on the wrong surface into the first render.

Usage: shot_check.py <project> [--model opus] [--batch 8] [--force]
Writes <project>/SHOT_CHECK.json + SHOT_CHECK.md. Exit 0 = nothing blocking, 3 = blocking issues, 1 = could not check.
A blocking issue is fixed by changing the shot, or acknowledged in plan.json when it is a known, accepted limit:
  "shot_check_ack": {"<source file stem>@<in-point, 1 decimal>": "why this is acceptable"}
The prompt carries the CURRENT owner taste rules for the "shot" stage (tools/taste_rules.py) after its fixed text.
Verdicts are cached PER SHOT (2026-11-22): a shot's key covers everything in its question (file stem@in, speed, slot, the
spoken words, the note, before/at/after the reveal, model, SAMPLING, the shot-stage rules hash). A re-run only asks the
shots whose key changed; the rest are reused (no call when nothing changed). Only verdicts that came back are stored, so a
shot with no verdict is asked again next time. --force re-asks every shot. Opus at effort medium.
"""
import sys as _sys, os as _os; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import claude_client as anthropic
import base64, concurrent.futures, hashlib, json, pathlib, re, subprocess, sys, tempfile
import taste_rules
from brand import BRAND, rules_text

ROOT = pathlib.Path(__file__).resolve().parent.parent
BLOCKED = 3
SAMPLING = 'frames-v2'   # bump when the frame sampling changes, so cached verdicts are not reused
EFFORT = 'medium'        # owner rule: Opus at medium for almost everything
CACHE_MAX = 400          # stored per-shot verdicts kept for shots no longer in the plan (a reverted shot is reused)
SYSTEM = (f"""You are the pre-render QA for a 9:16 {BRAND['product']} ad made from real footage. The {BRAND['product_word']}:
{BRAND['product_look']} How it works: {BRAND['how_it_works']}
""" + """For each shot you get 3 to 5 frames (spread from the start to the end of the planned window in the SOURCE clip) and the voiceover line spoken
over it. Judge each shot against the owner's rules:
- T08 the picture matches the line literally (rug line = a rug, vacuum line = a vacuum, a named thing = that thing, a
  problem line shows the problem itself, not a cute face).
- T31 the product must not be visible before the reveal shot named in the request.
- T12 on a line saying a tool fails, the tool visibly fails (the problem is still there). A tool working well on a failure line breaks it.
""" + f"""- T05 a demo shot shows the complete demo: {BRAND['complete_demo']} A result line needs a visible result.
- T10 the problem looks real, not staged.
{rules_text()}
""" + """- T04/T08 no burned-in captions, headlines, graphics or watermarks in the source frames.
- T23 no warped, glitching, frozen or badly blurred footage; T40 the subject is on screen from the first frame of the shot.
- T26 footage is sharp enough for a phone screen.
severity "block" = the owner would reject it: wrong subject for the line, burned-in text or graphics, product before the
reveal, a HARD RULE broken, a tool not failing on a failure line, warped or glitching footage, a result line with no result.
severity "minor" = worth knowing but shippable: motion blur at a cut, subject a moment late, slightly soft, staged-looking problem.
Do not invent problems you cannot see. Reply with JSON only:
{"shots": [{"i": <shot number>, "ok": true|false, "severity": "block"|"minor"|"", "rule": "T08", "issue": "<short, plain>",
"shows": "<what the frames actually show, 8-20 words>", "clip_fault": true|false}]}  One entry per shot, in order.
clip_fault is true only when the footage itself is unusable whatever the line is (burned-in text or graphics, watermark,
warped or glitching picture, too blurry, a HARD RULE broken); a clip that is fine but wrong for THIS line is clip_fault false.""")


def key_of(shot):
    return f"{pathlib.Path(shot['src']).stem}@{float(shot['in']):.1f}"


def beats_of(proj):
    py = ROOT / '.venv/bin/python'
    out = subprocess.run([str(py if py.exists() else sys.executable), '-I', str(ROOT / 'tools/rawedit.py'), str(proj), 'words'],
                         capture_output=True, text=True, cwd=ROOT).stdout
    beats = []   # one (time, word) per spoken word, so a shot that starts mid-sentence still gets its own words
    for m in re.finditer(r'^beat +(\d+) @ +([\d.]+) \(([\d.]+)s\)(.*)$', out, re.M):
        for w in re.finditer(r'(\d+\.\d+):(\S+)', m[4]):
            beats.append((float(w[1]), w[2]))
    total = re.search(r'^total ([\d.]+)', out, re.M)
    return beats, (float(total[1]) if total else None)


def rows_of(plan, beats, total):
    shots = plan['shots']
    end_all = (total or (shots[-1]['at'] + 3.0)) + float((plan.get('rules') or {}).get('end_hold') or 0)   # the last shot holds past the last word
    reveal = plan.get('reveal_shot')   # set it in plan.json when the notes do not name the product; else the first note that does
    if reveal is None:
        reveal = next((i for i, s in enumerate(shots) if re.search(r'(?<!no )\b(product|' + re.escape(BRAND['product_word']) + r')\b', s.get('note', ''), re.I)), None)
    rows = []
    for i, s in enumerate(shots):
        a = float(s['at']); e = float(shots[i + 1]['at']) if i + 1 < len(shots) else end_all
        said = ' '.join(t for t0, t in beats if a - 0.08 <= t0 < e - 0.08)
        rows.append({'i': i, 'key': key_of(s), 'src': s['src'], 'in': float(s['in']), 'speed': float(s.get('speed', 1.0)),
                     'slot': round(max(e - a, 0.2), 3), 'at': a, 'said': said or '(no words: a pause in the voiceover)', 'note': s.get('note', '')})
    return rows, reveal


def fingerprint(rows, model, reveal=None, rules=''):
    """Whole-list fingerprint (kept for readers of SHOT_CHECK.json); the cache itself is per shot (shot_key)."""
    return hashlib.sha256(json.dumps([[r['key'], r['speed'], r['slot'], r['said'], r.get('note', '')] for r in rows]
                                     + [model, SAMPLING, reveal, rules]).encode()).hexdigest()[:16]


def place(i, reveal):
    return 'none' if reveal is None else 'before' if i < reveal else 'at' if i == reveal else 'after'


def shot_key(row, reveal, model, rules):
    """Per-shot cache key: everything that goes into this shot's question."""
    return hashlib.sha256(json.dumps([row['key'], row['speed'], row['slot'], row['said'], row.get('note', ''),
                                      place(row['i'], reveal), model, SAMPLING, rules]).encode()).hexdigest()[:20]


def system_prompt():
    """The fixed text (severity guidance) + the current shot-stage owner rules, read at call time."""
    block = taste_rules.prompt_block('shot')
    return SYSTEM + ('\n\n' + block + '\nUse these ids in "rule". The reply format above does not change.' if block else '')


def fractions(slot):
    """Where in a shot to look: 3 frames up to 4 s, 4 up to 7 s, 5 beyond (a one-take flips late), always near both ends."""
    n = 3 if slot <= 4 else 4 if slot <= 7 else 5
    return [round(0.1 + i * 0.82 / (n - 1), 3) for i in range(n)]


def grab(row, td):
    out = []
    for k, f in enumerate(fractions(row['slot'])):
        t = row['in'] + row['speed'] * row['slot'] * f
        fn = pathlib.Path(td) / f"s{row['i']:02d}_{k}.jpg"
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-ss', f'{t:.2f}', '-i', row['src'], '-frames:v', '1',
                        '-vf', 'scale=320:-2', '-q:v', '5', str(fn)], capture_output=True)
        if fn.exists() and fn.stat().st_size > 500:
            out.append(fn)
    return out


def parse(text):
    m = re.search(r'\{.*\}', text, re.S)
    data = json.loads(m[0]) if m else {}
    out = {}
    for x in data.get('shots', []):
        if isinstance(x, dict) and isinstance(x.get('i'), int):
            sev = x.get('severity') if x.get('severity') in ('block', 'minor') else ('' if x.get('ok') else 'minor')
            out[x['i']] = {'ok': bool(x.get('ok')), 'severity': '' if x.get('ok') else sev, 'rule': str(x.get('rule', ''))[:20],
                           'issue': str(x.get('issue', ''))[:300], 'shows': str(x.get('shows', ''))[:300],
                           'clip_fault': bool(x.get('clip_fault')) and not x.get('ok')}
    return out


NO_FRAMES = {'ok': False, 'severity': 'block', 'rule': 'T23', 'shows': '', 'clip_fault': False}


def ask(client, model, batch, reveal, td, system=None, frames=None):
    """One call for a batch of shots -> {shot i: verdict} for the shots of this batch that came back. `frames` maps shot i
    to its grabbed frames (grabbed here when not given); a shot with no frames is not sent (the caller marks it)."""
    content, lines = [], []
    frames = frames if frames is not None else {r['i']: grab(r, td) for r in batch}
    sent = [r for r in batch if frames.get(r['i'])]
    if not sent:
        return {}
    for r in sent:
        for f in frames[r['i']]:
            content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': base64.b64encode(f.read_bytes()).decode()}})
        lines.append(f"SHOT {r['i']} (the next {len(frames[r['i']])} frames): voiceover during it: \"{r['said']}\" | planned as: {r['note']}")
    rv = f'The product is revealed at shot {reveal}; it must not appear in any earlier shot.' if reveal is not None else 'No reveal shot is marked.'
    content.append({'type': 'text', 'text': rv + '\nFrames are attached in shot order.\n' + '\n'.join(lines)})
    r = client.messages.create(model=model, max_tokens=4000, system=system or system_prompt(), output_config={'effort': EFFORT},
                               messages=[{'role': 'user', 'content': content}])
    got = parse(''.join(b.text for b in r.content if getattr(b, 'type', '') == 'text'))
    want = {x['i'] for x in sent}
    return {i: v for i, v in got.items() if i in want}


def check_rows(rows, reveal, model, old, force=False, size=8, client=None, td=None):
    """Per-shot cache: reuse every stored verdict whose shot key is unchanged, ask Claude only for the rest.
    Returns (verdicts {i: v}, cache {shot key: v}, keys [shot key per row], stats). Only verdicts that came back are cached."""
    rules = taste_rules.stage_hash('shot')
    keys = [shot_key(r, reveal, model, rules) for r in rows]
    cache = dict((old or {}).get('cache') or {})
    verdicts, todo = {}, []
    for r, k in zip(rows, keys):
        if not force and isinstance(cache.get(k), dict):
            verdicts[r['i']] = cache[k]
        else:
            todo.append(r)
    stats = {'reused': len(rows) - len(todo), 'asked': 0, 'calls': 0, 'failed_calls': 0, 'no_frames': 0}
    if todo:
        own = td is None
        tmp = tempfile.TemporaryDirectory(prefix='shot_check_') if own else None
        work = tmp.name if own else td
        try:
            frames = {r['i']: grab(r, work) for r in todo}
            for r in todo:
                if not frames[r['i']]:   # not asked and not cached: the source may simply not be fetched yet
                    verdicts[r['i']] = {**NO_FRAMES, 'issue': f"no frames could be read from the source at {r['in']}s"}
                    stats['no_frames'] += 1
            send = [r for r in todo if frames[r['i']]]
            batches = [send[i:i + size] for i in range(0, len(send), size)]
            client = client or (anthropic.Anthropic() if batches else None)
            system = system_prompt() if batches else None

            def one(b):
                try:
                    return ask(client, model, b, reveal, work, system=system, frames=frames)
                except Exception as e:   # one failed call must not throw away the batches that did come back
                    print(f'  shot check call failed for shots {[x["i"] for x in b]}: {type(e).__name__}: {str(e)[:200]}', file=sys.stderr)
                    return None
            with concurrent.futures.ThreadPoolExecutor(3) as ex:
                for got in ex.map(one, batches):
                    stats['calls'] += 1
                    if got is None:
                        stats['failed_calls'] += 1; continue
                    verdicts.update(got)
            by_i = {r['i']: k for r, k in zip(rows, keys)}
            for r in send:
                if r['i'] in verdicts:
                    cache[by_i[r['i']]] = verdicts[r['i']]; stats['asked'] += 1
        finally:
            if tmp:
                tmp.cleanup()
    live = set(keys)
    extra = [k for k in cache if k not in live]
    for k in extra[:max(len(extra) - CACHE_MAX, 0)]:   # oldest first (insertion order)
        cache.pop(k)
    cache = {**{k: v for k, v in cache.items() if k not in live}, **{k: cache[k] for k in keys if k in cache}}
    return verdicts, cache, keys, stats


def decide(rows, verdicts, acks):
    """Merge verdicts with the plan's acknowledgements -> (issues, blocking). A shot with no verdict is itself blocking."""
    issues, blocking = [], []
    for r in rows:
        v = verdicts.get(r['i']) or verdicts.get(str(r['i']))
        if v is None:
            v = {'ok': False, 'severity': 'block', 'rule': 'T30', 'issue': 'not checked (no verdict came back)', 'shows': ''}
        if v['ok']:
            continue
        item = {**{k: r[k] for k in ('i', 'key', 'at', 'said', 'note')}, **v, 'ack': acks.get(r['key'])}
        issues.append(item)
        if v['severity'] == 'block' and not item['ack']:
            blocking.append(item)
    return issues, blocking


def report(proj, rows, verdicts, issues, blocking, fp, model, cache=None, keys=None, stats=None):
    data = {'fingerprint': fp, 'model': model, 'shots': len(rows), 'verdicts': verdicts,
            'issues': issues, 'blocking': [b['key'] for b in blocking]}
    if keys is not None:   # per-shot cache (2026-11-22): shot_keys[i] is row i's key into cache
        data.update(rules_hash=taste_rules.stage_hash('shot')[:16], shot_keys=keys, cache=cache or {}, last_run=stats or {})
    tmp = proj / 'SHOT_CHECK.json.tmp'
    tmp.write_text(json.dumps(data, indent=1) + '\n'); tmp.replace(proj / 'SHOT_CHECK.json')
    md = [f'# Shot check {proj.name}', '', f'{len(rows)} shots checked before rendering, {len(issues)} flagged, {len(blocking)} blocking.', '']
    for it in issues:
        tag = 'ACKNOWLEDGED' if it['ack'] and it['severity'] == 'block' else it['severity'].upper()
        md.append(f"- **{tag}** shot {it['i']} at {it['at']:.1f}s `{it['key']}` ({it['rule']}): {it['issue']}")
        md.append(f"  - line: \"{it['said']}\" | frames show: {it['shows']}" + (f" | accepted because: {it['ack']}" if it['ack'] else ''))
    if not issues:
        md.append('Every shot matches its line.')
    (proj / 'SHOT_CHECK.md').write_text('\n'.join(md) + '\n')


def main():
    a = sys.argv[1:]
    model = a[a.index('--model') + 1] if '--model' in a else 'claude-opus-5-5'
    size = int(a[a.index('--batch') + 1]) if '--batch' in a else 8
    proj = pathlib.Path(next(x for x in a if not x.startswith('--') and x not in (model, str(size)))).resolve()
    plan = json.loads((proj / 'plan.json').read_text())
    if not plan.get('shots'):
        print('no shot timeline in this plan: nothing to check'); return 0
    beats, total = beats_of(proj)
    if not beats:
        print('could not read the beat timings (rawedit words)'); return 1
    rows, reveal = rows_of(plan, beats, total)
    fp = fingerprint(rows, model, reveal, taste_rules.stage_hash('shot'))
    try:
        old = json.loads((proj / 'SHOT_CHECK.json').read_text()) if (proj / 'SHOT_CHECK.json').exists() else {}
    except json.JSONDecodeError:
        old = {}
    verdicts, cache, keys, st = check_rows(rows, reveal, model, old, force='--force' in a, size=size)
    print(f"{st['reused']} shot verdicts reused, {st['asked']} asked in {st['calls']} call(s)"
          + (f", {st['failed_calls']} call(s) failed" if st['failed_calls'] else '') + (f", {st['no_frames']} shot(s) with no frames" if st['no_frames'] else ''))
    issues, blocking = decide(rows, verdicts, plan.get('shot_check_ack') or {})
    report(proj, rows, verdicts, issues, blocking, fp, model, cache, keys, st)
    print(f'shot check: {len(rows)} shots, {len(issues)} flagged, {len(blocking)} blocking -> {proj / "SHOT_CHECK.md"}')
    for b in blocking:
        print(f"  BLOCK shot {b['i']} {b['key']} ({b['rule']}): {b['issue']}")
    if st['failed_calls']:
        print('could not check every shot (a Claude call failed): run again; the shots that came back are kept')
        return 1
    return BLOCKED if blocking else 0


if __name__ == '__main__':
    sys.exit(main())
