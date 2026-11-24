"""Results loop: which of OUR ads actually spent and sold on Meta, joined back to the project that made them.

The taste rules learn from revision notes (what the owner fixed). This file learns from the market (what Meta spent on).
Spend is the verdict (owner rule): an ad with little spend has no readable ROAS, hook or hold, so it is listed as "too
little spend", never as a loser.

Matching a project to its live ads, in order:
  1. feedback/meta_map.json  {"<project>": ["<exact Meta ad name or substring>", ...]}  (manual, always wins)
  2. the project folder name inside the ad name (the owner often launches with it, e.g. coat-and-cats-song-h2-couch-throw)
  3. the project's script vs the creative's transcript (the results DB holds transcripts of creatives with >= $300 spend);
     a SequenceMatcher ratio >= 0.6 counts, best creative per project.
Data: an optional SQLite ad-results DB (tables ads, ad_daily, creatives), opened read-only. Path: env RESULTS_DB, default
feedback/results.db. When it is missing the results loop is skipped with a one-line message.
Optional env PROJECTS_ARCHIVE: a folder of finished projects moved out of projects/ that should still count.

Usage (PY = .venv/bin/python, from the repo root):
  results.py               write feedback/RESULTS.md + feedback/results.json + footage/moments/clip_results.json
  results.py --md          print the markdown section only (used by weekly_report.py)
"""
import collections, difflib, json, os, pathlib, re, sqlite3, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = pathlib.Path(os.environ.get("RESULTS_DB") or ROOT / "feedback" / "results.db")
FB = ROOT / "feedback"
MAP = FB / "meta_map.json"
MIN_SPEND = 300     # below this the numbers are noise (same gate the brain uses before transcribing)


def norm(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
def words(s): return re.findall(r"[a-z']+", (s or "").lower())


def project_text(p):
    try: j = json.loads((p / "plan.json").read_text())
    except Exception: return ""
    out = []
    for b in j.get("beats", []):
        for k in ("vo", "line", "text", "say", "dialogue"):
            if isinstance(b.get(k), str): out.append(b[k]); break
    return " ".join(out)


def project_fids(p):
    try: t = (p / "plan.json").read_text()
    except Exception: return set()
    return set(re.findall(r'"fid":\s*"([A-Za-z0-9_-]{20,})"', t))


def build():
    if not DB.exists(): raise FileNotFoundError(f"results loop skipped: no ad results DB at {DB} (set RESULTS_DB)")
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ads = db.execute("select ad_id, name, creative_key, created_time from ads").fetchall()
    perf = {r[0]: r[1:] for r in db.execute(
        "select ad_id, sum(spend), sum(impressions), sum(video_3s), sum(thruplays), sum(purchases), sum(purchase_value), "
        "min(date), max(date) from ad_daily group by ad_id")}
    trans = [(k, words(t)) for k, t in db.execute(
        "select creative_key, transcript from creatives where transcript is not null and length(transcript) > 40")]
    manual = json.loads(MAP.read_text()) if MAP.exists() else {}
    by_name = [(a, norm(a[1] or "")) for a in ads]
    # finished projects moved to an archive folder (env PROJECTS_ARCHIVE) still count: only their small text files are read
    arch = pathlib.Path(os.environ["PROJECTS_ARCHIVE"]).expanduser() if os.environ.get("PROJECTS_ARCHIVE") else None
    dirs = [q for q in (ROOT / "projects").iterdir()] if (ROOT / "projects").is_dir() else []
    dirs = dirs + (sorted(q for q in arch.iterdir()) if arch and arch.is_dir() else [])
    folders = {q.name for q in dirs if q.is_dir()}
    res = {}
    for p in sorted(dirs, key=lambda q: q.name):
        if not p.is_dir() or p.name.startswith(("_", ".")): continue
        st = p.stat(); born = time.strftime("%Y-%m-%d", time.localtime(getattr(st, "st_birthtime", st.st_mtime) - 86400))
        mine = lambda xs: [a for a in xs if (a[3] or "")[:10] >= born]   # a remake reuses the original's script: only ads made after the project
        hit, how = [], None
        if p.name in manual:
            pats = [x.lower() for x in manual[p.name]]
            hit = [a for a in ads if any(x in (a[1] or "").lower() for x in pats)]; how = "manual"   # manual wins, no date filter
        if not hit:
            s = norm(p.name)
            if len(s) >= 8:
                hit = mine([a for a, nn in by_name if s in nn]); how = "name"
                # a base name also sits inside its hook variants' names (x vs x-h2): leave those to the variant's own folder
                hit = [a for a in hit if not any(re.search(re.escape(s) + r"-(h\d+)\b", norm(a[1] or "")) and v in folders
                                                 for v in [s + "-" + m_ for m_ in re.findall(re.escape(s) + r"-(h\d+)", norm(a[1] or ""))])]
        if not hit:
            w = words(project_text(p))
            if len(w) >= 12:
                sw = set(w); best = (0.0, None)
                ok_keys = {a[2] for a in mine(ads)}
                for k, cw in trans:
                    if k not in ok_keys: continue
                    if len(sw & set(cw)) < 0.4 * len(sw): continue
                    r = difflib.SequenceMatcher(None, w, cw, autojunk=False).ratio()
                    if r > best[0]: best = (r, k)
                if best[0] >= 0.6:
                    hit = mine([a for a in ads if a[2] == best[1]]); how = f"transcript {best[0]:.2f}"
        if not hit: continue
        sp = im = v3 = tp = pu = pv = 0.0; first, last = "9999", "0000"
        for a in hit:
            x = perf.get(a[0])
            if not x: continue
            sp += x[0] or 0; im += x[1] or 0; v3 += x[2] or 0; tp += x[3] or 0; pu += x[4] or 0; pv += x[5] or 0
            first = min(first, x[6] or first); last = max(last, x[7] or last)
        res[p.name] = {"match": how, "ads": sorted({a[1] for a in hit})[:12], "n_ads": len(hit), "spend": round(sp, 2),
                       "purchases": round(pu, 1), "roas": round(pv / sp, 2) if sp else None,
                       "hook": round(v3 / im, 3) if im else None, "hold": round(tp / v3, 3) if v3 else None,
                       "first": first if sp else None, "last": last if sp else None, "fids": sorted(project_fids(p))}
    return res


def clip_results(res):
    """fid -> spend of the ads that used the clip (a project's spend counts once per clip)."""
    c = collections.defaultdict(lambda: {"spend": 0.0, "value": 0.0, "projects": []})
    for name, r in res.items():
        for f in r["fids"]:
            c[f]["spend"] += r["spend"]; c[f]["value"] += (r["roas"] or 0) * r["spend"]; c[f]["projects"].append(name)
    return {f: {"spend": round(v["spend"], 2), "roas": round(v["value"] / v["spend"], 2) if v["spend"] else None,
                "projects": v["projects"]} for f, v in c.items()}


def md(res):
    live = sorted(res.items(), key=lambda kv: -kv[1]["spend"])
    big = [(k, v) for k, v in live if v["spend"] >= MIN_SPEND]
    small = [(k, v) for k, v in live if 0 < v["spend"] < MIN_SPEND]
    none = [k for k, v in live if not v["spend"]]
    L = ["## Our ads in the market (Meta, account currency, lifetime)", "",
         f"{len(res)} projects matched to live ads; {len(big)} have spent at least ${MIN_SPEND} (readable), "
         f"{len(small)} have spent less (too early to judge), {len(none)} have no spend yet. Spend is the verdict.", ""]
    for k, v in big:
        L.append(f"- **{k}**: ${v['spend']:,.0f} spend, ROAS {v['roas']}, hook {v['hook'] if v['hook'] is not None else '-'}, "
                 f"hold {v['hold'] if v['hold'] is not None else '-'}, {v['purchases']:.0f} purchases, {v['n_ads']} ad(s), "
                 f"{v['first']} to {v['last']} (matched by {v['match']})")
    if small:
        L += ["", "Too little spend to read: " + ", ".join(f"{k} (${v['spend']:,.0f})" for k, v in small)]
    if none:
        L += ["", "Launched, no spend yet: " + ", ".join(none)]
    L += ["", f"Not matched? Add the Meta ad name to `feedback/meta_map.json` (\"<project>\": [\"<ad name or part of it>\"])."]
    return "\n".join(L)


def main():
    try: res = build()
    except FileNotFoundError as e: print(e); return
    if "--md" in sys.argv: print(md(res)); return
    (FB / "results.json").write_text(json.dumps({"built": time.strftime("%Y-%m-%d %H:%M"), "projects": res}, indent=1))
    cr = clip_results(res)
    out = ROOT / "footage" / "moments"; out.mkdir(parents=True, exist_ok=True)
    (out / "clip_results.json").write_text(json.dumps(cr, indent=1))
    (FB / "RESULTS.md").write_text(f"# RESULTS ({time.strftime('%Y-%m-%d')})\n\n" + md(res) + "\n")
    print(md(res)); print(f"\n{len(cr)} library clips appear in matched ads -> footage/moments/clip_results.json")


if __name__ == "__main__":
    main()
