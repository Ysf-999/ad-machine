"""Review notes -> log -> learned rules. The feedback loop for every ad style.

Usage:
  feedback.py ingest <project> [file]        parse a "Copy notes for Claude" paste (clipboard, or a file) into feedback/log.jsonl
                                             and print the redo commands it implies
  feedback.py add <project> "<note>" [--beat N] [--time 12.4] [--rule] [--skill S] [--src chat]
                                             log one note by hand (--rule = looks general). Projects without plan.json need --skill.
  feedback.py open [--skill S] [--ad A]      EVERY unreviewed note (ticked or not) — what /learn works through
  feedback.py pending                        notes flagged as general rules and not yet written into a rules file
  feedback.py promote <id[,id..]> "<rule text>" [--scope skill|universal] [--code tools/x.py]
                                             write the generalised rule into the rules file; several ids = repeat evidence;
                                             --code marks the rule as enforced in that tool (a check/default, not just prose)
  feedback.py dismiss <id[,id..]> ["reason"] one-off notes (fixed in that ad only, not a rule)
  feedback.py rules [skill]                  print the universal rules + that skill's rules (read this before starting an ad)
  feedback.py version <project>              print "universal=N skill=M" rule counts for that project's skill
  feedback.py stats                          notes per ad by rule-set size: is the feedback shrinking as rules are added?

Auto-learning (owner 2026-11-15: learn from EVERY revision, right away, no approval):
  every note logged (add / ingest / frameio pull) is tagged against feedback/taste_rules.json on arrival.
  A match prints REPEAT <T-id> (a known mistake came back) and the note becomes 'learned'. No match prints NEW: the
  note stays 'open' and the agent learns it in the same session with taste-add (general) or dismiss (this ad only).
  feedback.py taste                          regenerate feedback/OWNER_TASTE.md (ranked; read FIRST before any ad)
  feedback.py taste-add "<title>" "<rule>" --re "<regex>" [--ids 12,13] [--group G] [--stages plan,shot]
                                             learn a new owner rule now; --stages = which checkers see it
                                             (plan, shot, still, clip, master; default: every stage)
  feedback.py taste-edit T07 "<new wording>" newer owner note refines/contradicts a rule: newest wins, old kept
  feedback.py retag                          re-tag the whole log after the patterns change
  feedback.py top [--days 7]                 most repeated mistakes this week vs before
  feedback.py repeats [--json] [--all]       per T-rule: owner notes tagged with it AFTER the rule was added (the mistake
                                             came back), distinct ads, latest date, and which automatic checkers cover it

Files (all under <repo>/feedback/): log.jsonl, RULES_universal.md, RULES_<skill>.md.
A rule line looks like:  - **R012** (2026-10-28, hw4 beat 3) rule text
"""
import datetime, json, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))   # taste_tags; skills call this with python -I (no script dir on sys.path)
FB = ROOT / "feedback"
LOG = FB / "log.jsonl"
MODE_SKILL = {"A_material": "animated-ad-machine", "B_talking_character": "animated-ad-machine"}
RULE_RE = re.compile(r"^- \*\*R(\d+)\*\*", re.M)


def skill_of(plan):
    return plan.get("skill") or MODE_SKILL.get(plan.get("mode", ""), "unknown")


def rules_file(scope, skill):
    return FB / ("RULES_universal.md" if scope == "universal" else f"RULES_{skill}.md")


def count_rules(path):
    return len(RULE_RE.findall(path.read_text())) if path.exists() else 0


def version(skill):
    return {"universal": count_rules(FB / "RULES_universal.md"), "skill": count_rules(FB / f"RULES_{skill}.md")}


def read_log():
    if not LOG.exists():
        return []
    return [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]


def write_log(rows):
    FB.mkdir(exist_ok=True)
    LOG.write_text("".join(json.dumps(r) + "\n" for r in rows))


def learn_now(entry, rows=None, quiet=False):
    """Auto-learn (owner 2026-11-15: learn from EVERY revision right away, no approval). Tag the note against the
    taste rules. A match = the system already knew this, so it is a REPEAT mistake: count it and say so loudly.
    No match = NEW: the note stays 'open' and the agent must turn it into a rule or a one-off in this same session."""
    import taste_tags
    ids = taste_tags.tag(entry.get("text", ""))
    entry["taste"] = ids
    if ids and entry.get("status", "open") == "open":
        entry["status"] = "learned"
    if quiet:
        return entry
    B = taste_tags.by_id()
    rows = rows if rows is not None else read_log()
    for i in ids:
        prev = sorted({r["ad"] for r in rows if i in (r.get("taste") or []) and r.get("id") != entry.get("id")})
        print(f"  REPEAT {i} '{B[i]['title']}' - already raised on {len(prev)} ad(s). Rule: {B[i]['rule'][:160]}...")
    if not ids:
        print(f"  NEW #{entry.get('id')} matches no taste rule - learn it NOW (no approval): "
              f"`feedback.py taste-add \"<title>\" \"<rule>\" --re \"<regex>\" --ids {entry.get('id')}` if it would apply to "
              f"another ad, or `feedback.py dismiss {entry.get('id')} one-off` if it is about this ad only.")
    return entry


def append(entry, learn=True):
    rows = read_log()
    entry["id"] = (max([r["id"] for r in rows]) + 1) if rows else 1
    entry.setdefault("ts", datetime.datetime.now().isoformat(timespec="seconds"))
    entry.setdefault("status", "open")
    if learn:
        learn_now(entry, rows)
    rows.append(entry)
    write_log(rows)
    return entry


LINE = re.compile(r"^(beat\s+(?P<beat>\d+)|master\s*@\s*(?P<time>[\d.]+)s?|ad)\s*:\s*(?P<rest>.+)$", re.I)


def parse(text, ad):
    """Parse review-page output. Returns entries (no id/ts yet)."""
    out = []
    for raw in text.splitlines():
        m = LINE.match(raw.strip())
        if not m:
            continue
        rest = m.group("rest").strip()
        decision, note = "", rest
        dm = re.match(r"^(approve|redo-frame|redo-clip|\(no decision\))\s*(?:—|-)?\s*(.*)$", rest)
        if dm:
            decision = dm.group(1) if dm.group(1) != "(no decision)" else ""
            note = dm.group(2)
        rule = bool(re.search(r"\[RULE\]\s*$", note))
        note = re.sub(r"\s*\[RULE\]\s*$", "", note).strip()
        if not note and decision in ("", "approve"):
            continue
        out.append({"ad": ad, "beat": int(m.group("beat")) if m.group("beat") else None,
                    "time": float(m.group("time")) if m.group("time") else None,
                    "decision": decision, "text": note, "rule": rule})
    return out


def cmd_ingest(proj, src=None):
    proj = pathlib.Path(proj).resolve()
    plan = json.loads((proj / "plan.json").read_text())
    text = pathlib.Path(src).read_text() if src else subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
    entries = parse(text, proj.name)
    if not entries:
        sys.exit("no review lines found (expected 'beat N: …', 'master @12.4s: …' or 'ad: …')")
    skill = skill_of(plan)
    ver = version(skill)
    for e in entries:
        e.update(skill=skill, rules_at_time=ver, status="open")
        append(e)
    print(f"logged {len(entries)} notes for {proj.name} (skill {skill}, rules {ver})")
    print("\nwhat to do now:")
    for e in entries:
        pj = f"ad.py {proj.name}"
        if e["beat"] and e["decision"] == "redo-frame":
            print(f"  {pj} redo {e['beat']} frame \"{e['text']}\"")
        elif e["beat"] and e["decision"] == "redo-clip":
            print(f"  {pj} redo {e['beat']} clip \"{e['text']}\"")
        elif e["time"] is not None:
            print(f"  master @{e['time']}s: {e['text']}  (find the beat whose window covers that time)")
        elif e["beat"]:
            print(f"  beat {e['beat']}: {e['text']}")
        else:
            print(f"  whole ad: {e['text']}")
    flagged = [e for e in read_log() if e["ad"] == proj.name and e.get("rule") and e["status"] == "open"]
    if flagged:
        print(f"\n{len(flagged)} note(s) flagged as general rules. After fixing the ad, generalise them:")
        print("  feedback.py pending   then   feedback.py promote <id> \"<rule>\" --scope skill|universal")
        print("  (a flagged note you decide is one-off: feedback.py dismiss <id>)")


def resolve_proj(proj):
    p = pathlib.Path(proj)
    if not p.exists() and (ROOT / "projects" / proj).exists():
        p = ROOT / "projects" / proj
    return p.resolve()


def cmd_add(proj, note, beat=None, time=None, rule=False, skill=None, src=None):
    proj = resolve_proj(proj)
    if not skill:
        pf = proj / "plan.json"
        if not pf.exists():
            sys.exit(f"{proj.name} has no plan.json: pass --skill <skill> (e.g. raw-ugc-editor)")
        skill = skill_of(json.loads(pf.read_text()))
    e = append({"ad": proj.name, "beat": beat, "time": time, "decision": "", "text": note, "rule": rule,
                "skill": skill, "rules_at_time": version(skill), **({"src": src} if src else {})})
    print(f"logged #{e['id']} [{skill}] {proj.name}")


def where_of(r):
    return f"beat {r['beat']}" if r.get("beat") else (f"@{r['time']}s" if r.get("time") is not None else "whole ad")


def cmd_open(skill=None, ad=None):
    rows = [r for r in read_log() if r["status"] == "open"
            and (not skill or r["skill"] == skill) and (not ad or r["ad"] == ad)]
    if not rows:
        print("no open notes"); return
    by = {}
    for r in rows:
        by.setdefault(r["skill"], {}).setdefault(r["ad"], []).append(r)
    for sk, ads in by.items():
        print(f"\n=== {sk} ({sum(len(v) for v in ads.values())} open) ===")
        for a, rs in ads.items():
            print(f"  {a}")
            for r in rs:
                tag = " [RULE?]" if r.get("rule") else ""
                print(f"    #{r['id']} {r['ts'][:10]} {where_of(r)} {r.get('decision') or ''}: {r['text']}{tag}")


def cmd_pending():
    rows = [r for r in read_log() if r.get("rule") and r["status"] == "open"]
    if not rows:
        print("no pending rule candidates")
    for r in rows:
        where = f"beat {r['beat']}" if r["beat"] else (f"@{r['time']}s" if r["time"] is not None else "whole ad")
        print(f"#{r['id']}  [{r['skill']}]  {r['ad']} {where}: {r['text']}")


def next_rule_id():
    n = 0
    for f in FB.glob("RULES_*.md"):
        ids = [int(x) for x in RULE_RE.findall(f.read_text())]
        n = max([n] + ids)
    return n + 1


def parse_ids(arg):
    return [int(x) for x in str(arg).split(",") if x.strip()]


def cmd_promote(ids, text, scope="skill", code=None):
    rows = read_log()
    ids = parse_ids(ids)
    found = [x for x in rows if x["id"] in ids]
    if len(found) != len(ids):
        sys.exit(f"unknown note id(s): {sorted(set(ids) - {x['id'] for x in found})}")
    r = found[0]
    f = rules_file(scope, r["skill"])
    if not f.exists():
        f.write_text(f"# Learned rules — {'all ad styles' if scope == 'universal' else r['skill']}\n\n"
                     "Each rule came from an owner review. Read these before starting an ad. Do not remove a rule "
                     "without an owner note saying it is wrong.\n\n")
    rid = next_rule_id()
    src = ", ".join(sorted({f"{x['ad']} {where_of(x)}" for x in found}))
    extra = f" [notes #{', #'.join(str(i) for i in ids)}]" if len(ids) > 1 else ""
    enforced = f" [enforced: {code}]" if code else ""
    with f.open("a") as fh:
        fh.write(f"- **R{rid:03d}** ({datetime.date.today()}, {src}) {text}{enforced}{extra}\n")
    for x in found:
        x["status"] = "promoted"; x["rule_id"] = rid
        if code: x["code"] = code
    write_log(rows)
    print(f"R{rid:03d} written to {f.name} from {len(found)} note(s); rule counts now {version(r['skill'])}")


def cmd_dismiss(ids, reason=None):
    ids = parse_ids(ids)
    rows = read_log()
    n = 0
    for r in rows:
        if r["id"] in ids:
            r["status"] = "dismissed"; n += 1
            if reason: r["reason"] = reason
    write_log(rows)
    print(f"dismissed {n} note(s)")


TASTE_MD = FB / "OWNER_TASTE.md"


def taste_stats(rows=None, since=None):
    """Per T-rule: notes, distinct ads, first/last date, and how many ads it came back on AFTER it was first raised."""
    rows = rows if rows is not None else read_log()
    out = {}
    for r in rows:
        if since and r["ts"][:10] < since:
            continue
        for t in r.get("taste") or []:
            s = out.setdefault(t, {"notes": 0, "ads": set(), "first": r["ts"][:10], "last": r["ts"][:10]})
            s["notes"] += 1; s["ads"].add(r["ad"])
            s["first"] = min(s["first"], r["ts"][:10]); s["last"] = max(s["last"], r["ts"][:10])
    return out


def score(s, today=None):
    today = today or datetime.date.today().isoformat()
    recent = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(s["last"])).days <= 14
    return len(s["ads"]) * (2 if recent else 1) + s["notes"] * 0.25


def cmd_taste(quiet=False):
    """Regenerate OWNER_TASTE.md: the ranked owner-taste list every producer reads first."""
    import taste_tags
    rows = read_log(); st = taste_stats(rows); R = taste_tags.rules()
    ranked = sorted(R, key=lambda r: -score(st[r["id"]]) if r["id"] in st else 0)
    n_rev = sum(1 for r in rows if r.get("src") != "seed"); n_ads = len({r["ad"] for r in rows})
    L = ["# What the owner wants in every video (read this FIRST)", "",
         f"Generated by `feedback.py taste` on {datetime.date.today()} from {n_rev} owner revisions across {n_ads} ads "
         "(review page, chat, Frame.io). These T-rules apply to EVERY video style "
         "(animated, song, AI UGC, real-footage edit, HyperFrames, hybrid) and win over every R/S/C/A rule. "
         "Source of truth: `feedback/taste_rules.json`. Do not hand-edit this file.", "",
         "The first rules are general starter craft rules; every new rule comes from an owner review note. "
         "Repeating a known mistake is the worst outcome. Before any delivery, `tools/preflight.py <project>` "
         "makes you go through this list line by line.", "",
         "## Most repeated (fix these first)", "",
         "| # | Rule | Ads | Notes | Last raised |", "|---|---|---|---|---|"]
    for r in ranked[:12]:
        s = st.get(r["id"])
        if s:
            L.append(f"| {r['id']} | {r['title']} | {len(s['ads'])} | {s['notes']} | {s['last']} |")
    L += ["", "## All rules", ""]
    group = None
    for r in sorted(R, key=lambda r: r["id"]):
        if r["group"] != group:
            group = r["group"]; L += [f"### {group}", ""]
        s = st.get(r["id"])
        ev = f" *(raised on {len(s['ads'])} ads, {s['notes']} notes, last {s['last']})*" if s else ""
        L.append(f"- **{r['id']} {r['title']}.** {r['rule']}{ev}")
        L.append("")
    TASTE_MD.write_text("\n".join(L) + "\n")
    if not quiet:
        print(f"wrote {TASTE_MD} ({len(R)} rules)")


def parse_stages(arg):
    """'plan,shot' -> ['plan', 'shot'] (validated); None = the rule goes to every checker stage."""
    if arg is None:
        return None
    import taste_rules
    got = [x.strip() for x in str(arg).split(",") if x.strip()]
    bad = [x for x in got if x not in taste_rules.STAGES]
    if bad:
        sys.exit(f"unknown stage(s) {bad}: use {', '.join(taste_rules.STAGES)}")
    return [x for x in taste_rules.STAGES if x in got]


def cmd_taste_add(title, rule, regex, ids=None, group="Learned", stages=None):
    """Learn a NEW owner rule right away (no approval). ids = the note(s) it came from. stages = the checker stages that
    see it (tools/taste_rules.py); left out, every checker sees it."""
    import taste_tags
    p = taste_tags.TASTE; d = json.loads(p.read_text())
    nid = f"T{max(int(r['id'][1:]) for r in d['rules']) + 1:02d}"
    re.compile(regex)
    st = parse_stages(stages)
    new = {"id": nid, "group": group, "title": title, "rule": rule, "re": regex,
           "added": str(datetime.date.today()), **({"from": parse_ids(ids)} if ids else {}),
           **({"stages": st} if st is not None else {})}
    import taste_rules   # store which checkers see it, like every other rule (tests compare the two)
    if taste_rules.checkers_of(new):
        new["enforced_by"] = taste_rules.checkers_of(new)
    d["rules"].append(new)
    p.write_text(json.dumps(d, indent=1, ensure_ascii=False))
    rows = read_log(); hit = 0
    for r in rows:
        if r["id"] in (parse_ids(ids) if ids else []) or re.search(regex, taste_tags.norm(r["text"]), re.I):
            if nid not in (r.get("taste") or []):
                r["taste"] = (r.get("taste") or []) + [nid]; hit += 1
            if r["status"] == "open":
                r["status"] = "learned"
    write_log(rows); cmd_taste(quiet=True)
    print(f"{nid} learned: {title} (tagged {hit} note(s), OWNER_TASTE.md regenerated; checker stages: "
          f"{', '.join(st) if st is not None else 'all'})")


def cmd_taste_edit(tid, rule):
    """A newer owner note refines or contradicts a T-rule: the newest owner wording wins; old wording kept in 'was'."""
    import taste_tags
    p = taste_tags.TASTE; d = json.loads(p.read_text())
    for r in d["rules"]:
        if r["id"] == tid:
            r.setdefault("was", []).append({"until": str(datetime.date.today()), "rule": r["rule"]})
            r["rule"] = rule
            p.write_text(json.dumps(d, indent=1, ensure_ascii=False)); cmd_taste(quiet=True)
            print(f"{tid} updated"); return
    sys.exit(f"no rule {tid}")


def cmd_retag():
    """Re-run the tagger over the whole log (after the patterns change). Never reopens dismissed notes."""
    rows = read_log()
    for r in rows:
        learn_now(r, quiet=True)
    write_log(rows); cmd_taste(quiet=True)
    print(f"retagged {len(rows)} notes; open (untagged, need a decision): {sum(1 for r in rows if r['status'] == 'open')}")


def cmd_top(days=7):
    """Weekly ranking: which owner rules got broken most in the last N days, against the weeks before."""
    import taste_tags
    B = taste_tags.by_id(); rows = read_log()
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    now, before = taste_stats(rows, since), taste_stats([r for r in rows if r["ts"][:10] < since])
    new_open = [r for r in rows if r["status"] == "open" and r["ts"][:10] >= since]
    print(f"Owner revisions in the last {days} days: {sum(1 for r in rows if r['ts'][:10] >= since)} "
          f"on {len({r['ad'] for r in rows if r['ts'][:10] >= since})} ads\n")
    print("Most repeated mistakes this period (ads / notes; 'before' = ads it was raised on earlier):")
    for t, s in sorted(now.items(), key=lambda kv: -len(kv[1]["ads"]))[:10]:
        b = before.get(t)
        tail = f"   (before: {len(b['ads'])} ads - a REPEAT of a known rule)" if b else "   (new this period)"
        print(f"  {t} {B[t]['title'][:55]:55s} {len(s['ads']):2d} ads / {s['notes']:2d} notes{tail}")
    if new_open:
        print(f"\n{len(new_open)} new note(s) still unlearned: run `feedback.py open` and learn them now.")


NOT_A_MISTAKE = {"like", "approved"}   # owner praise / approvals carry tags too, but they are not a mistake coming back


def repeats(rows=None, rules=None):
    """Per T-rule: owner notes tagged with it dated AFTER the rule's 'added' day (T01-T34 have none: built 2026-11-15),
    not counting the notes the rule was learned from. Read-only. Sorted by count, most first."""
    import taste_rules
    rows = rows if rows is not None else read_log()
    rules = rules if rules is not None else taste_rules.load()
    out = []
    for r in rules:
        added = r.get("added") or taste_rules.BUILT
        src = set(r.get("from") or [])
        hits = [x for x in rows if r["id"] in (x.get("taste") or []) and x.get("ts", "")[:10] > added
                and x.get("id") not in src and x.get("status") not in NOT_A_MISTAKE]
        out.append({"id": r["id"], "title": r.get("title", ""), "added": added, "repeats": len(hits),
                    "ads": len({x["ad"] for x in hits}), "latest": max((x["ts"][:10] for x in hits), default=None),
                    "note_ids": [x["id"] for x in hits], "stages": taste_rules.stages_of(r),
                    "checked_by": taste_rules.coverage(r)})
    out.sort(key=lambda x: (-x["repeats"], -x["ads"], x["id"]))
    return out


def cmd_repeats(as_json=False, everything=False):
    rows = [x for x in repeats() if everything or x["repeats"]]
    if as_json:
        print(json.dumps({"generated": datetime.datetime.now().isoformat(timespec="seconds"), "rules": rows}, indent=1)); return
    if not rows:
        print("no taste rule has come back after it was added"); return
    print("Owner notes that hit a T-rule AFTER it was added (the mistake came back):\n")
    print(f"  {'rule':4s}  {'title':52s} {'notes':>5s} {'ads':>4s}  {'latest':10s}  checked by")
    for x in rows:
        print(f"  {x['id']:4s}  {x['title'][:52]:52s} {x['repeats']:5d} {x['ads']:4d}  {x['latest'] or '-':10s}  "
              f"{', '.join(x['checked_by']) or 'NOTHING (process rule)'}")
    print(f"\n{sum(x['repeats'] for x in rows)} repeat notes on {len(rows)} rules. 'checked by' = enforced_by in "
          "taste_rules.json + the LLM checkers its stages reach (tools/taste_rules.py).")


def cmd_rules(skill=None):
    if not TASTE_MD.exists():
        cmd_taste(quiet=True)
    print(TASTE_MD.read_text())
    if skill in (None, "unknown"):
        print("\n(hybrid/unknown skill: also read the RULES_<skill>.md of every part you use, e.g. ugc-talking-head + raw-ugc-editor)")
    for f in [FB / "RULES_universal.md"] + ([FB / f"RULES_{skill}.md"] if skill else []):
        print(f"\n=== {f.name} ===")
        print(f.read_text() if f.exists() else "(none yet)")


def cmd_stats():
    rows = read_log()
    if not rows:
        print("no notes logged yet")
        return
    by_ad = {}
    for r in rows:
        by_ad.setdefault(r["ad"], []).append(r)
    print("notes per ad, in the order they were first reviewed (rules = universal+skill count at review time)\n")
    first = sorted(by_ad.items(), key=lambda kv: kv[1][0]["ts"])
    for ad, rs in first:
        v = rs[0].get("rules_at_time", {})
        print(f"{rs[0]['ts'][:10]}  {ad:34s} {rs[0]['skill']:22s} rules={v.get('universal', 0) + v.get('skill', 0):3d}  notes={len(rs)}  redo={sum(1 for r in rs if r['decision'].startswith('redo'))}")
    buckets = {}
    for ad, rs in first:
        v = rs[0].get("rules_at_time", {}); k = v.get("universal", 0) + v.get("skill", 0)
        buckets.setdefault(k, []).append(len(rs))
    if len(buckets) > 1:
        print("\naverage notes per ad by rule count:")
        for k in sorted(buckets):
            print(f"  {k:3d} rules: {sum(buckets[k]) / len(buckets[k]):.1f} notes/ad over {len(buckets[k])} ad(s)")


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    c, rest = a[0], a[1:]
    def opt(name, cast=str):
        return cast(rest[rest.index(name) + 1]) if name in rest else None
    if c == "ingest": cmd_ingest(rest[0], rest[1] if len(rest) > 1 else None)
    elif c == "add": cmd_add(rest[0], rest[1], opt("--beat", int), opt("--time", float), "--rule" in rest,
                             opt("--skill"), opt("--src"))
    elif c == "open": cmd_open(opt("--skill"), opt("--ad"))
    elif c == "pending": cmd_pending()
    elif c == "promote": cmd_promote(rest[0], rest[1], opt("--scope") or "skill", opt("--code"))
    elif c == "dismiss": cmd_dismiss(rest[0], rest[1] if len(rest) > 1 and not rest[1].startswith("--") else None)
    elif c == "rules": cmd_rules(rest[0] if rest else None)
    elif c == "version":
        plan = json.loads((pathlib.Path(rest[0]).resolve() / "plan.json").read_text())
        v = version(skill_of(plan)); print(f"universal={v['universal']} skill={v['skill']}")
    elif c == "stats": cmd_stats()
    elif c == "taste": cmd_taste()
    elif c == "taste-add": cmd_taste_add(rest[0], rest[1], opt("--re"), opt("--ids"), opt("--group") or "Learned", opt("--stages"))
    elif c == "taste-edit": cmd_taste_edit(rest[0], rest[1])
    elif c == "retag": cmd_retag()
    elif c == "top": cmd_top(opt("--days", int) or 7)
    elif c == "repeats": cmd_repeats("--json" in rest, "--all" in rest)
    else: sys.exit(__doc__)


if __name__ == "__main__":
    main()
