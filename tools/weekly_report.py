"""Weekly learning + cost report (added 2026-11-15, from a friend's agency setup: rank recurring video problems weekly,
and have one place that watches spend).

  .venv/bin/python tools/weekly_report.py [--days 7]

Writes feedback/WEEKLY_<date>.md and appends a kie credit-balance snapshot to feedback/credits_log.jsonl.
Can run every Monday from a launchd agent or cron job (no Claude session needed).
  1. Revisions: which owner rules were broken most this week, and whether each is a REPEAT of a known rule.
     Notes per reviewed ad this week vs the 4 weeks before (should fall as the system learns).
  2. Credits: real spend = drop in the kie balance since the last snapshot (a rise means a top-up). Per-ad split from
     jobs.jsonl records that carry a timestamp (kie.py logs one since 2026-11-15) plus the share spent on redo/fix keys.
Never estimates a cost: anything not measured is said to be missing.
"""
import collections, datetime, json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import feedback, taste_tags  # noqa: E402

FB = ROOT / "feedback"
REDO = re.compile(r"(_v\d+|redo|fix|retry|round|_r\d+|regen)", re.I)


def balance():
    try:
        import kie
        return float(kie.credit())
    except Exception as e:  # network / key problems are reported, not guessed around
        return f"unavailable ({type(e).__name__})"


def main():
    a = sys.argv[1:]
    days = int(a[a.index("--days") + 1]) if "--days" in a else 7
    today = datetime.date.today(); since = (today - datetime.timedelta(days=days)).isoformat()
    month = (today - datetime.timedelta(days=days + 28)).isoformat()
    rows = feedback.read_log(); B = taste_tags.by_id()
    now = feedback.taste_stats(rows, since); before = feedback.taste_stats([r for r in rows if r["ts"][:10] < since])
    wk = [r for r in rows if r["ts"][:10] >= since]
    prev = [r for r in rows if month <= r["ts"][:10] < since]
    per = lambda rs: (len(rs) / max(1, len({r["ad"] for r in rs})))
    L = [f"# Weekly report {today} (last {days} days)", "",
         "## 1. What the owner corrected this week", "",
         f"{len(wk)} revisions on {len({r['ad'] for r in wk})} ads: {per(wk):.1f} per ad, against {per(prev):.1f} per ad over the 4 weeks before "
         "(this should fall as the rules take hold).", ""]
    if now:
        L += ["| Rule | Ads this week | Notes | Raised before? |", "|---|---|---|---|"]
        for t, s in sorted(now.items(), key=lambda kv: -len(kv[1]["ads"]))[:12]:
            b = before.get(t)
            L.append(f"| {t} {B[t]['title']} | {len(s['ads'])} | {s['notes']} | {'REPEAT: ' + str(len(b['ads'])) + ' ads before' if b else 'new'} |")
        L += ["", "Top 3 to fix in code or in the skill steps this week: " +
              ", ".join(f"{t} ({B[t]['title']})" for t, _ in sorted(now.items(), key=lambda kv: -len(kv[1]["ads"]))[:3]) + "."]
    unlearned = [r for r in wk if r["status"] == "open"]
    new_rules = [r for r in taste_tags.rules() if r.get("added", "") >= since]
    L += ["", f"New owner rules learned this week: {', '.join(r['id'] + ' ' + r['title'] for r in new_rules) or 'none'}.",
          f"Notes still unlearned: {len(unlearned)}" + (" (run `feedback.py open` and learn them)" if unlearned else "") + ".", ""]

    # ---- credits ----
    bal = balance(); snaps = FB / "credits_log.jsonl"
    hist = [json.loads(l) for l in snaps.read_text().splitlines()] if snaps.exists() else []
    last = next((h for h in reversed(hist) if isinstance(h.get("balance"), (int, float))), None)
    L += ["## 2. Credits (kie.ai)", ""]
    if isinstance(bal, float):
        L.append(f"Balance now: {bal:,.0f} credits.")
        if last:
            d = last["balance"] - bal
            L.append(f"Since {last['date']}: {'spent ' + format(d, ',.0f') if d >= 0 else 'balance rose by ' + format(-d, ',.0f') + ' (a top-up; spend not measurable this period)'} credits.")
        else:
            L.append("First snapshot: real weekly spend shows from next week's report.")
        with snaps.open("a") as fh:
            fh.write(json.dumps({"date": str(today), "balance": bal}) + "\n")
    else:
        L.append(f"Balance: {bal}. No spend figure this week.")
    by = collections.Counter(); redo = collections.Counter(); undated = 0
    for jf in (ROOT / "projects").glob("*/jobs.jsonl"):
        for l in jf.read_text(errors="ignore").splitlines():
            try: j = json.loads(l)
            except ValueError: continue
            c = j.get("creditsConsumed")
            if j.get("state") != "success" or not c: continue
            if not j.get("ts"): undated += c; continue
            if j["ts"][:10] >= since:
                by[jf.parent.name] += c
                if REDO.search(j.get("key", "")): redo[jf.parent.name] += c
    if by:
        L += ["", "| Ad | Credits this week | On redo/fix keys |", "|---|---|---|"]
        for ad, c in by.most_common(15):
            L.append(f"| {ad} | {c:,.0f} | {redo[ad]:,.0f} ({redo[ad] / c:.0%}) |")
        tot, rtot = sum(by.values()), sum(redo.values())
        L.append(f"\nLogged this week: {tot:,.0f} credits, {rtot / tot:.0%} on redos. Redos are the cost of every repeated mistake above.")
    else:
        L.append("\nNo dated per-ad job records this week (kie.py stamps them from 2026-11-15; project-local generators "
                 "that skip kie.py are only visible in the balance drop).")
    L.append(f"Older undated records hold {undated:,.0f} credits in total (before dates were logged).")
    try:   # market results of our own ads (tools/results.py): what Meta spent on, not only what the owner fixed
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); import results as _res
        _r = _res.build(); L += ["", _res.md(_r)]
        (FB / "results.json").write_text(json.dumps({"built": today, "projects": _r}, indent=1))
    except Exception as e:
        L.append(f"\n(results loop failed: {e})")
    out = FB / f"WEEKLY_{today}.md"
    out.write_text("\n".join(L) + "\n")
    print(out.read_text())


if __name__ == "__main__":
    main()
