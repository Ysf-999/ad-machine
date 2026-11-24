# Library v2, 2026-11-09 (agentchad.io). Keys only from your own environment; nothing here is account-specific.
"""mkwords.py <src_transcript.json> <lines.json> <out_words.json>
For videos that keep the original audio and only get new captions (for example English speech with local-language text):
times every word of each translated caption by its share of characters, warped through the original words' times inside [s,e].
lines.json: [{"s":..,"e":..,"cap":"translated caption text"}]. Output: [[start,end,"word"],...] for captions.py WORDS_JSON."""
import sys, json, bisect
if len(sys.argv) < 4:
    sys.exit(__doc__)
tr, ln, out = sys.argv[1:4]
words = [w for s in json.load(open(tr))['segments'] for w in s['words']]
res = []
for l in json.load(open(ln)):
    sw = [w for w in words if w[0] >= l['s'] - 0.05 and w[1] <= l['e'] + 0.05] or [[l['s'], l['e'], 'x']]
    tot = sum(len(w[2]) for w in sw); fr = [0.0]; tm = [sw[0][0]]
    acc = 0
    for w in sw:
        tm[-1] = min(tm[-1], w[0]) if len(tm) == 1 else tm[-1]
        fr.append(fr[-1]); tm.append(w[0])   # start of word
        acc += len(w[2]); fr.append(acc / tot); tm.append(w[1])
    def at(p):
        k = bisect.bisect_left(fr, p); k = min(max(k, 1), len(fr) - 1)
        f0, f1, t0, t1 = fr[k - 1], fr[k], tm[k - 1], tm[k]
        return t0 if f1 == f0 else t0 + (p - f0) / (f1 - f0) * (t1 - t0)
    toks = l['cap'].split(); T = sum(len(t) for t in toks); a = 0
    for t in toks:
        st = at(a / T); a += len(t); en = at(a / T); res.append([round(st, 3), round(en, 3), t])
json.dump(res, open(out, 'w'), ensure_ascii=False); print(len(res), 'words; last', res[-1])
