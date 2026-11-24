"""Frame.io review bridge: push finished ads up, pull timestamped comments into the feedback loop.

Runs through the Composio Frame.io V4 toolkit (account linked with `composio link frame_io_v4`).

Usage:
  frameio.py setup [--name "<Brand> Ads"]       find the account + workspace, create/find the review project
  frameio.py push <project> [--file MASTER.mp4] [--label v2]
                                                 upload the ad into its own folder; later pushes become new versions
                                                 in one version stack, and comments already logged on older versions
                                                 are ticked "completed" in Frame.io (that version answers them)
  frameio.py push <project> --batch "<Batch name>"
                                                 put the ad in a shared batch folder (owner: one folder per batch,
                                                 the 3 hooks together); each hook keeps its own version stack
  frameio.py batch "<Batch name>" <proj> <proj> ...
                                                 move already-pushed ads into one batch folder, drop their old folders
  frameio.py pull <project> | --all [--dry]      log every new comment into feedback/log.jsonl (src=frameio, time in
                                                 seconds, version noted) and print the redo hints, same as `notes`
  frameio.py status [<project>]                  pushed ads, versions, comment counts, link to each
  frameio.py link <project>                      print the Frame.io link for the newest version
  frameio.py clean <project>                     after approval: pull last comments, then delete the ad's folder
                                                 from Frame.io (Free plan = 2 GB). Only command that deletes.

Comment conventions (type them in Frame.io):
  end a comment with #rule (or [RULE]) to flag it as a general rule for /learn
  start with "beat 3:" to tie it to a beat instead of the timestamp
  replies and comments ticked "completed" by a person are skipped

State: frameio/config.json (account/workspace/project ids) and <project>/frameio.json (folder, stack, files,
logged comment ids). Uploads are 720p review copies (~4 MB per 50 s ad), never the master.
"""
import json, os, pathlib, re, subprocess, sys, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = ROOT / "frameio" / "config.json"
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import feedback  # noqa: E402
from brand import BRAND  # noqa: E402


# ---------- composio ----------
def call(slug, **args):
    args = {k: v for k, v in args.items() if v is not None}
    r = subprocess.run(["composio", "execute", slug, "-d", json.dumps(args)], capture_output=True, text=True)
    out = (r.stdout or "").strip()
    try:
        d = json.loads(out)
    except json.JSONDecodeError:
        sys.exit(f"{slug} failed:\n{out[:1500]}\n{r.stderr[:800]}")
    if isinstance(d, dict) and d.get("successful") is False:
        sys.exit(f"{slug} failed: {json.dumps(d)[:1500]}")
    # unwrap {"data": {...}} layers (composio envelope + Frame.io's own "data")
    while isinstance(d, dict) and "data" in d and len([k for k in d if k not in ("successful", "error", "logId", "log_id")]) <= 2:
        d = d["data"]
    return d


def items(d):
    if isinstance(d, list):
        return d
    for k in ("data", "items", "results"):
        if isinstance(d, dict) and isinstance(d.get(k), list):
            return d[k]
    return []


def cursor(d):
    if not isinstance(d, dict):
        return None
    links = d.get("links") or {}
    return d.get("next_cursor") or (links.get("next") and re.search(r"after=([^&]+)", links["next"] or "") and
                                    re.search(r"after=([^&]+)", links["next"]).group(1))


def all_pages(slug, **args):
    out, cur = [], None
    while True:
        d = call(slug, **args, next_cursor=cur)
        out += items(d)
        cur = cursor(d)
        if not cur:
            return out


# ---------- state ----------
def cfg():
    if not CFG.exists():
        sys.exit("run `frameio.py setup` first")
    return json.loads(CFG.read_text())


def proj_dir(p):
    return feedback.resolve_proj(p)


def state_path(proj):
    return proj / "frameio.json"


def load_state(proj):
    f = state_path(proj)
    return json.loads(f.read_text()) if f.exists() else {"files": [], "logged": {}}


def save_state(proj, st):
    state_path(proj).write_text(json.dumps(st, indent=2))


def fps_of(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()
    try:
        n, d = r.split("/")
        return float(n) / float(d)
    except Exception:
        return 30.0


# ---------- commands ----------
def cmd_setup(name=None):
    name = name or f"{BRAND['brand']} Ads"
    accts = items(call("FRAME_IO_V4_LIST_ACCOUNTS"))
    if not accts:
        sys.exit("no Frame.io account visible: is frame_io_v4 linked? (`composio link frame_io_v4 --list`)")
    acct = accts[0]
    aid = acct["id"]
    ws = items(call("FRAME_IO_V4_LIST_WORKSPACES", account_id=aid))
    if not ws:
        sys.exit(f"account {aid} has no workspace")
    wid = ws[0]["id"]
    projects = all_pages("FRAME_IO_V4_LIST_WORKSPACE_PROJECTS", account_id=aid, workspace_id=wid)
    pr = next((p for p in projects if p.get("name") == name), None)
    if not pr:
        pr = call("FRAME_IO_V4_CREATE_PROJECT", account_id=aid, workspace_id=wid, name=name)
        print(f"created project {name}")
    CFG.parent.mkdir(exist_ok=True)
    c = {"account_id": aid, "account_name": acct.get("display_name") or acct.get("name"), "workspace_id": wid,
         "workspace_name": ws[0].get("name"), "project_id": pr["id"], "project_name": name,
         "root_folder_id": pr["root_folder_id"]}
    CFG.write_text(json.dumps(c, indent=2))
    print(json.dumps(c, indent=2))


def upload(c, folder_id, path, name):
    size = path.stat().st_size
    f = call("FRAME_IO_V4_CREATE_LOCAL_UPLOAD", account_id=c["account_id"], folder_id=folder_id, name=name, file_size=size)
    parts = f.get("upload_urls") or []
    mtype = f.get("media_type") or "video/mp4"
    with open(path, "rb") as fh:
        for i, p in enumerate(parts, 1):
            chunk = fh.read(p["size"])
            req = urllib.request.Request(p["url"], data=chunk, method="PUT",
                                         headers={"Content-Type": mtype, "x-amz-acl": "private"})
            urllib.request.urlopen(req, timeout=600).read()
            print(f"  part {i}/{len(parts)} up", flush=True)
    for _ in range(60):
        s = call("FRAME_IO_V4_GET_FILE_UPLOAD_STATUS", account_id=c["account_id"], file_id=f["id"])
        if s.get("upload_complete") or s.get("status") in ("complete", "uploaded", "transcoded"):
            break
        time.sleep(2)
    return f


def batch_folder(c, name):
    """One Frame.io folder per batch (owner 2026-11-12): the 3 hooks of an ad sit together, each in its own version stack."""
    b = c.setdefault("batches", {})
    if not b.get(name):
        b[name] = call("FRAME_IO_V4_CREATE_FOLDER", account_id=c["account_id"],
                       parent_folder_id=c["root_folder_id"], name=name)["id"]
        CFG.write_text(json.dumps(c, indent=2))
    return b[name]


OPTION_NAME = re.compile(r"(^|[-_ ])(opt|option|options|picks?)([-_ ]|$)", re.I)
MIN_FULL_S = 10.0


def options_gate(proj, path):
    """Owner 2026-11-22 (taste rules T29/T32): Frame.io is for FULL videos only. Clip or hook options for one slot go
    in the local picker (tools/option_picker.py -> OPTIONS.html + the ad board), never Frame.io."""
    if (proj / "OPTIONS.json").exists() and path.name != "MASTER.mp4":
        sys.exit("BLOCKED: this project holds clip options. Options go in the picker (tools/option_picker.py), not Frame.io.")
    if OPTION_NAME.search(proj.name):
        sys.exit(f"BLOCKED: '{proj.name}' looks like a clip option. Options go in the picker: tools/option_picker.py <project> "
                 "--slot \"<slot>\" <clip> <clip> ...  (Frame.io is for full videos only, owner 2026-11-22).")
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=60)
        dur = float(r.stdout.strip() or 0)
    except (ValueError, OSError, subprocess.SubprocessError):
        return
    if 0 < dur < MIN_FULL_S:
        sys.exit(f"BLOCKED: {path.name} is {dur:.1f} s, not a full video. Short clips and options go in the picker "
                 "(tools/option_picker.py), not Frame.io.")


def preflight_gate(proj, path):
    """Owner 2026-11-15: he must never find a mistake he already corrected. Nothing goes to Frame.io until
    tools/preflight.py has run on THIS file, every taste rule and earlier revision is answered, and no FAIL is open."""
    import preflight
    pf = proj / "PREFLIGHT.md"
    if os.environ.get("PREFLIGHT_SKIP"):
        print(f"!! preflight skipped: {os.environ['PREFLIGHT_SKIP']}"); return
    if not pf.exists():
        sys.exit(f"BLOCKED: run `.venv/bin/python tools/preflight.py {proj.name}{' --file ' + path.name if path.name != 'MASTER.mp4' else ''}` first, "
                 "answer every box in PREFLIGHT.md, then push.")
    t = pf.read_text()
    fp = re.search(r"^fingerprint: (\S+)", t, re.M)
    if not fp or fp.group(1) != preflight.fingerprint(path) or f"master: {path.name}" not in t:
        sys.exit(f"BLOCKED: PREFLIGHT.md is for another render. Re-run tools/preflight.py {proj.name} on {path.name}.")
    open_boxes = len(re.findall(r"^- \[ \]", t, re.M))
    fails = [l for l in t.splitlines() if l.startswith("- FAIL") and "override:" not in l]
    if open_boxes or fails:
        sys.exit(f"BLOCKED: PREFLIGHT.md has {open_boxes} unanswered box(es) and {len(fails)} open FAIL(s). "
                 "Fix the FAILs, answer every [ ] with [x] or [n/a], then push.")


def cmd_push(p, file=None, label=None, batch=None):
    c, proj = cfg(), proj_dir(p)
    path = proj / (file or "MASTER.mp4")
    if not path.exists():
        sys.exit(f"{path} not found")
    options_gate(proj, path)
    preflight_gate(proj, path)
    st = load_state(proj)
    if batch and not st.get("folder_id"):
        st["folder_id"], st["batch"] = batch_folder(c, batch), batch
    if not st.get("folder_id"):
        st["folder_id"] = call("FRAME_IO_V4_CREATE_FOLDER", account_id=c["account_id"],
                               parent_folder_id=c["root_folder_id"], name=proj.name)["id"]
    v = len(st["files"]) + 1
    name = f"{proj.name} v{v}{(' ' + label) if label else ''}.mp4"
    # Free plan = 2 GB: upload a 720p review copy (~5-10 MB), never the full master. Same fps so timestamps map 1:1.
    proxy = proj / "FRAMEIO_REVIEW.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-vf", "scale=-2:'min(1280,ih)'",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart", str(proxy)], check=True)
    print(f"uploading {path.name} as a {proxy.stat().st_size / 1048576:.1f} MB review copy -> {name}")
    f = upload(c, st["folder_id"], proxy, name)
    proxy.unlink()
    st["files"].append({"id": f["id"], "v": v, "src": path.name, "fps": fps_of(path),
                        "pushed": time.strftime("%Y-%m-%dT%H:%M:%S")})
    # version stack: first stack needs two files; later versions are moved into it
    if v == 2:
        st["stack_id"] = call("FRAME_IO_V4_CREATE_VERSION_STACK", account_id=c["account_id"], folder_id=st["folder_id"],
                              file_ids=[st["files"][0]["id"], f["id"]])["id"]
    elif v > 2 and st.get("stack_id"):
        call("FRAME_IO_V4_MOVE_FILE", account_id=c["account_id"], file_id=f["id"], parent_id=st["stack_id"])
    # comments already logged on older versions are answered by this one
    done = 0
    for old in st["files"][:-1]:
        for cid in st["logged"].get(old["id"], []):
            if cid in st.get("completed", []):
                continue
            call("FRAME_IO_V4_UPDATE_COMMENT", account_id=c["account_id"], comment_id=cid, completed=True)
            st.setdefault("completed", []).append(cid)
            done += 1
    save_state(proj, st)
    print(f"pushed v{v}" + (f", ticked {done} handled comment(s) on older versions" if done else ""))
    print(link_of(c, f["id"]))


def link_of(c, file_id):
    try:
        g = call("FRAME_IO_V4_GET_FILE", account_id=c["account_id"], file_id=file_id)
        if g.get("view_url"):
            return g["view_url"]
    except SystemExit:
        pass
    return f"https://next.frame.io/project/{c['project_id']}/view/{file_id}"


def secs(ts, fps):
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return round(ts / fps, 2)
    m = re.match(r"^(\d+):(\d+):(\d+)[:;](\d+)$", str(ts))
    if m:
        h, mi, s, fr = map(int, m.groups())
        return round(h * 3600 + mi * 60 + s + fr / fps, 2)
    try:
        return round(float(ts) / fps, 2)
    except ValueError:
        return None


BEAT = re.compile(r"^\s*beat\s+(\d+)\s*[:\-]\s*", re.I)
RULE = re.compile(r"\s*(#rule|\[rule\])\s*$", re.I)


def pull_one(c, proj, dry=False):
    st = load_state(proj)
    if not st["files"]:
        return 0
    pf = proj / "plan.json"
    plan = json.loads(pf.read_text()) if pf.exists() else {}
    skill = feedback.skill_of(plan) if plan else (st.get("skill") or "unknown")
    ver = feedback.version(skill)
    new, hints = 0, []
    for f in st["files"]:
        seen = set(st["logged"].get(f["id"], []))
        for cm in all_pages("FRAME_IO_V4_LIST_COMMENTS", account_id=c["account_id"], file_id=f["id"],
                            include="owner", sort="created_at_asc", page_size=100):
            cid = cm.get("id")
            if not cid or cid in seen or cm.get("parent_id") or cm.get("completed_at") or cm.get("completed"):
                continue
            text = (cm.get("text") or "").strip()
            if not text:
                continue
            beat = None
            bm = BEAT.match(text)
            if bm:
                beat, text = int(bm.group(1)), text[bm.end():]
            rule = bool(RULE.search(text))
            text = RULE.sub("", text).strip()
            t = None if beat else secs(cm.get("timestamp"), f.get("fps") or 30.0)
            who = ((cm.get("owner") or {}).get("name") or "").split(" ")[0]
            note = f"[frame.io v{f['v']}{(' ' + who) if who else ''}] {text}"
            e = {"ad": proj.name, "beat": beat, "time": t, "decision": "", "text": note, "rule": rule,
                 "skill": skill, "rules_at_time": ver, "src": "frameio", "frameio_comment": cid}
            if not dry:
                feedback.append(e)
                st["logged"].setdefault(f["id"], []).append(cid)
            new += 1
            where = f"beat {beat}" if beat else (f"@{t}s" if t is not None else "whole ad")
            hints.append(f"  {where}: {note}{'  [RULE]' if rule else ''}")
    if not dry:
        save_state(proj, st)
    if new:
        print(f"\n{proj.name}: {new} new comment(s){' (dry run, not logged)' if dry else ''} (skill {skill})")
        print("\n".join(hints))
        print(f"  fix, then: ad.py {proj.name} redo/stitch ...  and  frameio.py push {proj.name}")
    return new


def cmd_pull(p=None, all_=False, dry=False):
    c = cfg()
    projs = [x.parent for x in (ROOT / "projects").glob("*/frameio.json")] if all_ else [proj_dir(p)]
    total = sum(pull_one(c, pr, dry) for pr in sorted(projs))
    print(f"\n{total} new comment(s) across {len(projs)} ad(s)" + ("" if total else " — nothing to do"))
    if total and not dry:
        print("logged to feedback/log.jsonl and auto-learned (REPEAT = a known rule was broken; NEW = learn it now with feedback.py taste-add or dismiss). Then fix, re-run tools/preflight.py, push.")


def cmd_status(p=None):
    c = cfg()
    projs = [proj_dir(p)] if p else sorted(x.parent for x in (ROOT / "projects").glob("*/frameio.json"))
    for pr in projs:
        st = load_state(pr)
        if not st["files"]:
            continue
        logged = sum(len(v) for v in st["logged"].values())
        print(f"{pr.name}: v{st['files'][-1]['v']} pushed {st['files'][-1]['pushed'][:16]}, {logged} comment(s) logged")
    print(f"project: {c['project_name']} (https://next.frame.io/project/{c['project_id']})")


def batch_members(c, batch):
    """Every project whose state points at this batch folder."""
    fid = c.get("batches", {}).get(batch)
    out = []
    for f in (ROOT / "projects").glob("*/frameio.json"):
        try:
            if json.loads(f.read_text()).get("folder_id") == fid:
                out.append(f.parent)
        except (json.JSONDecodeError, OSError):
            pass
    return out


def cmd_clean(p):
    """Free-plan housekeeping: pull any last comments, then delete this ad's folder from Frame.io.
    For a batch folder this removes the whole batch (all its hooks), since approval is per batch."""
    c, proj = cfg(), proj_dir(p)
    st = load_state(proj)
    if not st.get("folder_id"):
        sys.exit(f"{proj.name} is not on Frame.io")
    members = batch_members(c, st["batch"]) if st.get("batch") else [proj]
    for m in members:
        pull_one(c, m)  # nothing is lost: every comment is in feedback/log.jsonl first
    call("FRAME_IO_V4_DELETE_FOLDER", account_id=c["account_id"], folder_id=st["folder_id"])
    for m in members:
        ms = load_state(m)
        ms["cleaned"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        ms["folder_id"], ms["stack_id"] = None, None
        ms["history"] = ms.get("history", []) + ms["files"]
        ms["files"] = []
        save_state(m, ms)
    if st.get("batch"):
        c.get("batches", {}).pop(st["batch"], None)
        CFG.write_text(json.dumps(c, indent=2))
    print(f"deleted {st.get('batch') or proj.name} ({', '.join(m.name for m in members)}) from Frame.io; "
          "comments stay in feedback/log.jsonl")


def cmd_batch(name, projs):
    """Move already-pushed ads into one batch folder and drop their old per-ad folders."""
    c = cfg()
    fid = batch_folder(c, name)
    for p in projs:
        proj = proj_dir(p)
        st = load_state(proj)
        if st.get("folder_id") == fid or not st.get("files"):
            print(f"{proj.name}: skipped ({'already in batch' if st.get('folder_id') == fid else 'not pushed'})")
            continue
        old = st["folder_id"]
        if st.get("stack_id"):
            call("FRAME_IO_V4_MOVE_VERSION_STACK", account_id=c["account_id"], version_stack_id=st["stack_id"],
                 parent_id=fid)
        else:
            for f in st["files"]:
                call("FRAME_IO_V4_MOVE_FILE", account_id=c["account_id"], file_id=f["id"], parent_id=fid)
        left = items(call("FRAME_IO_V4_LIST_FOLDER_CHILDREN", account_id=c["account_id"], folder_id=old))
        if not left:
            call("FRAME_IO_V4_DELETE_FOLDER", account_id=c["account_id"], folder_id=old)
        st["folder_id"], st["batch"] = fid, name
        save_state(proj, st)
        print(f"{proj.name}: moved into '{name}'" + ("" if not left else f" (old folder kept: {len(left)} item(s) left)"))


def cmd_link(p):
    c, st = cfg(), load_state(proj_dir(p))
    if not st["files"]:
        sys.exit("not pushed yet")
    print(link_of(c, st["files"][-1]["id"]))


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__); return

    def opt(flag, default=None):
        if flag in a:
            i = a.index(flag); v = a[i + 1]; del a[i:i + 2]; return v
        return default

    def flag(f):
        if f in a:
            a.remove(f); return True
        return False

    cmd = a.pop(0)
    if cmd == "setup":
        cmd_setup(opt("--name", None))
    elif cmd == "push":
        file, label, batch = opt("--file"), opt("--label"), opt("--batch")
        cmd_push(a[0], file, label, batch)
    elif cmd == "batch":
        cmd_batch(a[0], a[1:])
    elif cmd == "pull":
        dry, all_ = flag("--dry"), flag("--all")
        cmd_pull(a[0] if a else None, all_, dry)
    elif cmd == "status":
        cmd_status(a[0] if a else None)
    elif cmd == "link":
        cmd_link(a[0])
    elif cmd == "clean":
        cmd_clean(a[0])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
