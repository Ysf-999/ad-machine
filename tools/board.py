"""Style board: every master of one skill side by side, with its rule-set version and the notes it received.
No regeneration, nothing is re-rendered: it only reads MASTER.mp4, plan.json and feedback/log.jsonl.
Use it after changing a skill's rules to judge NEW ads against the ones before (oldest first).

Usage: board.py <skill> [--since YYYY-MM-DD]   -> boards/<skill>.html and opens it
"""
import datetime, html, json, pathlib, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import feedback as fb

ROOT = pathlib.Path(__file__).resolve().parent.parent
skill = sys.argv[1]
since = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv else "0000"
log = fb.read_log()
cards = []
for pf in sorted((ROOT / "projects").glob("*/plan.json")):
    proj = pf.parent
    if not (proj / "MASTER.mp4").exists():
        continue
    plan = json.loads(pf.read_text())
    if fb.skill_of(plan) != skill:
        continue
    made = datetime.datetime.fromtimestamp((proj / "MASTER.mp4").stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    if made[:10] < since:
        continue
    cards.append((made, proj, plan))
cards.sort(key=lambda c: c[0])
out = []
for made, proj, plan in cards:
    rv = plan.get("rules_version")
    notes = [r for r in log if r["ad"] == proj.name]
    rv_txt = f"rules {rv['universal']}+{rv['skill']}" if rv else "made before rule tracking"
    flag = "LOCKED / launched" if plan.get("locked") else ""
    out.append(f"""<div class="c"><video src="file://{proj}/MASTER.mp4" controls muted playsinline></video>
<b>{html.escape(proj.name)}</b><br><small>{made} · {rv_txt} · {len(notes)} notes</small>
{f'<br><small class="lk">{flag}</small>' if flag else ''}
<ul>{''.join(f'<li>{html.escape(n["text"][:140])}</li>' for n in notes[:5])}</ul></div>""")
page = f"""<!doctype html><meta charset=utf-8><title>Board — {skill}</title>
<style>body{{font-family:-apple-system,sans-serif;background:#111;color:#eee;margin:0;padding:16px}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px}}
.c{{background:#1b1b1b;padding:10px;border-radius:8px}} video{{width:100%;border-radius:6px;background:#000}}
small{{color:#999}} .lk{{color:#ffd400}} ul{{margin:6px 0 0 16px;padding:0;font-size:12px;color:#ccc}}</style>
<h2>{skill} — {len(cards)} ads, oldest first</h2><div class="g">{''.join(out)}</div>"""
(ROOT / "boards").mkdir(exist_ok=True)
f = ROOT / "boards" / f"{skill}.html"
f.write_text(page); print(f, f"({len(cards)} ads)")
subprocess.run(["open", str(f)])
