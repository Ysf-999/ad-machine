"""Build a local review page for an ad: keyframes, clips, QC verdicts, approve/redo per item.

Usage: review_page.py <project-dir> [--no-open]  -> writes <project>/REVIEW.html (and opens it unless --no-open).

"Send to Claude" posts the decisions to the board helper on this Mac (cloud/frame_review.py, 127.0.0.1:8790), which
saves them in <project>/FRAME_REVIEW.json: nothing to paste. If the helper is not running the notes are copied to the
clipboard instead, as before. Choices and notes are remembered in the browser per FILE VERSION: when a frame or clip
is redone its box starts empty again (owner 2026-11-22: old notes must never show on a new version).
"""
import html, json, pathlib, re, secrets, subprocess, sys

proj = pathlib.Path(sys.argv[1]).resolve()
plan = json.loads((proj / "plan.json").read_text())
qcf = proj / "QC" / "qc_report.json"
qc = {r["item"]: r for r in json.loads(qcf.read_text())} if qcf.exists() else {}
AD = plan.get("ad") or proj.name


def board_token():
    f = proj.parent.parent / "cloud" / "controller" / "board-token"
    try:
        t = f.read_text().strip()
    except OSError:
        t = ""
    if len(t) < 20:
        try:
            t = secrets.token_urlsafe(24); f.parent.mkdir(parents=True, exist_ok=True); f.write_text(t); f.chmod(0o600)
        except OSError:
            t = ""
    return t


def latest(d, stem, ext=".mp4"):
    c = [p for p in d.glob(f"{stem}*{ext}") if re.fullmatch(rf"{stem}(_v\d+)?", p.stem)]
    return max(c, key=lambda p: int(p.stem.rsplit("_v", 1)[1]) if "_v" in p.stem else 1) if c else None


def ver(p):
    m = re.search(r"_v(\d+)$", p.stem) if p else None
    return f" · version {m.group(1)}" if m else ""


def stamp(p):
    return f"{p.name}@{int(p.stat().st_mtime)}" if p else "-"


rows = []
for b in plan["beats"]:
    n = b["n"]
    fr = latest(proj / "FRAMES", f"scene_{n:02d}", ".png")
    cl = latest(proj / "CLIPS", f"clip_{n:02d}")
    def badge(name):
        r = qc.get(name)
        if not r: return ""
        col = {"PASS": "#2e7d32", "FAIL": "#c62828"}.get(r["verdict"], "#777")
        d = "".join(f"<li>{html.escape(x)}</li>" for x in r.get("defects", []))
        return f'<div class="qc" style="border-color:{col}"><b style="color:{col}">{r["verdict"]}</b> {r.get("severity","")}<ul>{d}</ul></div>'
    rows.append(f"""
<section class="beat" data-n="{n}" data-sig="{html.escape(stamp(fr) + '|' + stamp(cl))}" data-frame="{html.escape(fr.name) if fr else ''}" data-has="{1 if fr or cl else 0}">
 <h2>Beat {n}</h2>
 <p class="vo">“{html.escape(b.get('vo', b.get('line','')))}”</p>
 <p class="vis">{html.escape(b['visual'])}</p>
 <div class="media">
  <div><h3 title="{html.escape(fr.name) if fr else ''}">Starting frame{ver(fr)}</h3>{f'<img src="FRAMES/{fr.name}">' if fr else '<p class="vis">(not made yet)</p>'}{badge(fr.name) if fr else ''}</div>
  {f'<div><h3 title="{html.escape(cl.name)}">Clip{ver(cl)}</h3><video src="CLIPS/{cl.name}" controls muted loop playsinline></video>{badge(cl.name)}</div>' if cl else ''}
 </div>
 <div class="decide">
  <label><input type="radio" name="d{n}" value="approve"> Approve</label>
  <label><input type="radio" name="d{n}" value="redo-frame"> Redo frame</label>
  {f'<label><input type="radio" name="d{n}" value="redo-clip"> Redo clip</label>' if cl else ''}
  <input type="text" class="note" placeholder="What's wrong / what to change">
  <label title="Tick if this should apply to every future ad, not just this one"><input type="checkbox" class="rule"> for all future ads</label>
 </div>
</section>""")

master = proj / "MASTER.mp4"
SCRIPT = r"""
const AD=__AD__,TOKEN=__TOKEN__,MSIG=__MSIG__,API='http://127.0.0.1:8790/frames',KEY='review-'+AD,TK=KEY+'-master',SK=KEY+'-sent',AK=KEY+'-ad';
const beats=()=>[...document.querySelectorAll('.beat[data-n]')];
const PAGE=beats().map(s=>s.dataset.sig).join(';')+';'+MSIG;
function get(k,d){try{const v=JSON.parse(localStorage.getItem(k));return v==null?d:v}catch(e){return d}}
function put(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch(e){}}
// a choice or note is shown again only on the exact file version it was written for
{const s=get(KEY,{});for(const sec of beats()){const v=s[sec.dataset.n];if(!v||v.sig!==sec.dataset.sig)continue;
  if(v.d){const r=sec.querySelector(`input[value="${v.d}"]`);if(r)r.checked=true}sec.querySelector('.note').value=v.note||'';sec.querySelector('.rule').checked=!!v.rule}}
function state(){const s={};beats().forEach(sec=>{const d=sec.querySelector('input[type=radio]:checked');
  s[sec.dataset.n]={d:d?d.value:'',note:sec.querySelector('.note').value,rule:sec.querySelector('.rule').checked,sig:sec.dataset.sig,frame:sec.dataset.frame}});return s}
let T=[];{const t=get(TK,null);if(t&&t.sig===MSIG&&Array.isArray(t.T))T=t.T}
const an=document.getElementById('adnote'),ar=document.getElementById('adrule');
if(an){const a=get(AK,null);if(a&&a.sig===PAGE){an.value=a.note||'';ar.checked=!!a.rule}}
function keep(){put(KEY,state());if(an)put(AK,{sig:PAGE,note:an.value,rule:ar.checked})}
document.addEventListener('change',keep);document.addEventListener('input',keep);
function saveT(){put(TK,{sig:MSIG,T})}
function esc(x){return String(x).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/[<]/g,'&lt;')}
function drawT(){const el=document.getElementById('tnotes');if(!el)return;el.innerHTML=T.map((t,i)=>`<div class="decide"><b>@${t.t}s</b><input type="text" class="note" value="${esc(t.note)}" oninput="T[${i}].note=this.value;saveT()"><label><input type="checkbox" ${t.rule?'checked':''} onchange="T[${i}].rule=this.checked;saveT()"> general rule</label><button class="small" onclick="T.splice(${i},1);saveT();drawT()">x</button></div>`).join('')}
function markTime(){const v=document.getElementById('mv');T.push({t:Math.round(v.currentTime*10)/10,note:'',rule:false});saveT();drawT()}
drawT();
function say(text,bad){const m=document.getElementById('msg');m.textContent=text;m.className=bad?'bad':'ok'}
function approveRest(){beats().forEach(sec=>{if(sec.dataset.has==='1'&&!sec.querySelector('input[type=radio]:checked'))sec.querySelector('input[value="approve"]').checked=true});keep();say('Every frame without a choice is set to Approve. Press Send to Claude.')}
function notesText(){const s=state();let out=`REVIEW ${AD}\n`;for(const [n,v] of Object.entries(s)){if(!v.d&&!v.note)continue;out+=`beat ${n}: ${v.d||'(no decision)'}${v.note?' — '+v.note:''}${v.rule&&v.note?' [RULE]':''}\n`}
  T.forEach(t=>{if(t.note)out+=`master @${t.t}s: ${t.note}${t.rule?' [RULE]':''}\n`});if(an&&an.value)out+=`ad: ${an.value}${ar.checked?' [RULE]':''}\n`;return out}
function copyNotes(why){navigator.clipboard.writeText(notesText()).then(()=>say((why||'')+'Notes copied. Paste them to Claude.',!!why),()=>say('Could not copy. Select the notes by hand.',true))}
async function send(){
  const s=state(),miss=beats().filter(sec=>sec.dataset.has==='1'&&!s[sec.dataset.n].d);
  if(miss.length){say('Pick Approve or Redo for beat '+miss.map(x=>x.dataset.n).join(', ')+' first (or press "Approve the rest").',true);miss[0].scrollIntoView({behavior:'smooth',block:'center'});return}
  const b={};for(const [n,v] of Object.entries(s))if(v.d||v.note)b[n]={d:v.d,note:v.note,rule:v.rule,frame:v.frame};
  const body={ad:AD,token:TOKEN,source:'page',beats:b,master_notes:T.filter(t=>t.note),ad_note:an?an.value:'',ad_rule:!!(ar&&ar.checked)};
  say('Sending…');let j;
  try{const r=await fetch(API,{method:'POST',headers:{'Content-Type':'text/plain'},body:JSON.stringify(body)});j=await r.json()}
  catch(e){copyNotes('The board helper is not running, so nothing was sent. ');return}
  if(!j.ok){say(j.error||'Not saved.',true);return}
  const at=new Date().toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});put(SK,{sig:PAGE,at,message:j.message});say('Sent '+at+'. '+j.message)}
{const z=get(SK,null);if(z&&z.sig===PAGE)say('Sent '+z.at+'. '+z.message)}
"""
SCRIPT = (SCRIPT.replace("__AD__", json.dumps(AD)).replace("__TOKEN__", json.dumps(board_token())).replace("__MSIG__", json.dumps(stamp(master) if master.exists() else "-"))
          .replace("</", "<\\/"))

page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Review — {html.escape(AD)}</title>
<style>
body{{font-family:-apple-system,system-ui,sans-serif;margin:0;background:#111;color:#eee}}
header{{position:sticky;top:0;z-index:5;background:#1b1b1b;padding:12px 20px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;border-bottom:1px solid #333}}
button{{background:#ffd400;border:0;padding:8px 14px;border-radius:6px;font-weight:700;cursor:pointer;color:#111;font-size:14px}}
button.line{{background:none;color:#eee;border:1px solid #555}} button.small{{padding:4px 9px}}
a.alt{{color:#999;font-size:13px;cursor:pointer;text-decoration:underline}}
#msg{{font-size:14px}} #msg.ok{{color:#7ddc9a}} #msg.bad{{color:#ff8a7a}}
.beat{{padding:20px;border-bottom:1px solid #333}} .vo{{font-size:18px;margin:4px 0}} .vis{{color:#aaa;margin:0 0 10px}}
.media{{display:flex;gap:20px}} .media>div{{flex:1}} img,video{{width:100%;max-width:360px;border-radius:8px;background:#000}}
.qc{{border-left:4px solid;padding:6px 10px;margin-top:8px;background:#1e1e1e;max-width:360px}} .qc ul{{margin:4px 0 0 16px;padding:0;color:#ccc;font-size:13px}}
.decide{{margin-top:10px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}} .note{{flex:1;min-width:260px;padding:6px;background:#222;color:#eee;border:1px solid #444;border-radius:4px}}
h3{{font-size:13px;color:#999;margin:0 0 6px}}
</style></head><body>
<header><b>{html.escape(AD)}</b> <span style="color:#999">{len(rows)} beats</span> <button class="line" onclick="approveRest()">Approve the rest</button>
<button onclick="send()">Send to Claude</button> <a class="alt" onclick="copyNotes()">copy notes instead</a> <span id="msg"></span>
{'<a href="MASTER.mp4" style="color:#ffd400">MASTER.mp4</a>' if master.exists() else ''}</header>
{''.join(rows)}
{('<section class="beat" id="master"><h2>Whole ad</h2><video id="mv" src="MASTER.mp4" controls playsinline style="max-width:360px;width:100%;border-radius:8px;background:#000"></video><div class="decide"><button class="line" onclick="markTime()">Add note at current time</button><span id="mt" style="color:#999"></span></div><div id="tnotes"></div><div class="decide"><input type="text" id="adnote" class="note" placeholder="Note about the whole ad (pacing, voice, music, hook...)"><label><input type="checkbox" id="adrule"> general rule</label></div></section>') if master.exists() else ''}
<script>{SCRIPT}</script></body></html>"""
(proj / "REVIEW.html").write_text(page)
print(proj / "REVIEW.html")
if "--no-open" not in sys.argv[2:]:
    subprocess.run(["open", str(proj / "REVIEW.html")])
