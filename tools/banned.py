"""Owner-banned clips in one place. Standard library only: cloud/ctl.py imports this under a Python with no numpy.

footage/BANNED_CLIPS.json (agents add a clip the minute the owner rejects it, AGENTS.md):
  banned_ids            {drive_id: reason}                 the whole clip, never again
  banned_name_patterns  [substring, ...]                   file-name substrings ("- Studio", "Copy of ", ...)
  banned_drive_folders  [folder name, ...]                 Drive folders whose clips are never used
  banned_windows        {drive_id: free text}              stretches of an otherwise usable clip, e.g.
                        "cream cushion 44.9-54.35 banned (owner 11/8 ...); cat-tree bed 38.8-44.1 too slow ..."
  banned_windows_s      {drive_id: [[a, b], [a, b, "scope"]]}  optional machine-readable form, merged with the parse
  notes                 {"WEB3/vac_mk36522 + WEB/vac_mk36522": reason}  clips with no Drive id (web / AI inserts),
                        keyed by path tail or file stem, several joined with " + "

Window text is parsed conservatively: only "<a>-<b> banned" counts ("husky 35-39 still fine" and "38.8-44.1 too slow"
do not). "<a>-<b> banned for 'embedded hair' lines" / "banned as a 'pet hair mess' shot" is a SCOPED ban: the window is
only wrong for that kind of line, so callers warn instead of refusing (kind "window-scoped", hard False).

  load(root=None)                          -> the parsed list (cached on the file's mtime)
  clip_banned(src_or_id, name=None)        -> reason | None   (whole-clip bans: ids, name patterns, folders, notes)
  window_banned(src_or_id, start, end)     -> reason | None   (whole-clip ban or a banned window overlapping start-end)
  window_hits(src_or_id, start, end)       -> [{in, out, scope, reason, hard}]
  plan_hits(plan, root=None)               -> [{where, src, in, out, reason, hard, kind}] every clip reference in a plan
  file_hits(dirs)                          -> banned ids / names referenced in a project's live files (preflight T06)
src_or_id is a Drive id, a moment id (m:<fid10>@<start>), a path (footage/raw/<fid>.mov, WEB3/vac_mk36522.mp4) or a name.
"""
import csv, json, os, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
REL = pathlib.Path("footage") / "BANNED_CLIPS.json"
INDEX = pathlib.Path(os.environ.get("FOOTAGE_INDEX") or ROOT / "footage" / "INDEX.csv")
DRIVE_ID = re.compile(r"1[A-Za-z0-9_-]{24,}")
EPS = 0.05                                   # windows that only touch (shared edge) do not overlap
_CACHE = {}

# "<a>-<b> banned", then an optional "for ... lines" / "as a ... shot" scope before the "(owner ...)" note
_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*s?\s*[-–]\s*(\d+(?:\.\d+)?)\s*s?\s+banned\b([^;]*)", re.I)
_SCOPE = re.compile(r"\s*((?:for|as|on|in)\b[^(]*?)\s*(?:\(|$)", re.I)


def parse_windows(text):
    """Free-text window note -> [(start, end, scope or None, segment)]. Only ranges directly followed by 'banned'."""
    out = []
    for seg in re.split(r";", str(text or "")):
        for m in _RANGE.finditer(seg):
            a, b = float(m.group(1)), float(m.group(2))
            if b <= a: continue
            sc = _SCOPE.match(m.group(3) or "")
            scope = sc.group(1).strip(" ,.") if sc and sc.group(1).strip(" ,.") else None
            out.append((a, b, scope, seg.strip()))
    return out


def load(root=None):
    """Parsed BANNED_CLIPS.json. A missing file gives missing=True (callers fail closed)."""
    root = pathlib.Path(root) if root else ROOT
    p = root / REL
    try:
        key = (str(p), p.stat().st_mtime_ns)
    except OSError:
        return {"path": str(p), "missing": True, "ids": {}, "patterns": [], "folders": [], "windows": {}, "notes": [], "raw": {}}
    if _CACHE.get("key") == key: return _CACHE["val"]
    b = json.loads(p.read_text())
    win = {}
    for fid, txt in (b.get("banned_windows") or {}).items():
        for a, e, scope, seg in parse_windows(txt):
            win.setdefault(fid, []).append({"in": a, "out": e, "scope": scope, "reason": seg, "hard": scope is None})
    for fid, rows in (b.get("banned_windows_s") or {}).items():
        for r in rows or []:
            try: a, e = float(r[0]), float(r[1])
            except (TypeError, ValueError, IndexError): continue
            scope = str(r[2]) if len(r) > 2 and r[2] else None
            if not any(abs(w["in"] - a) < 0.01 and abs(w["out"] - e) < 0.01 for w in win.get(fid, [])):
                win.setdefault(fid, []).append({"in": a, "out": e, "scope": scope, "hard": scope is None,
                                                "reason": f"{a}-{e} banned" + (f" {scope}" if scope else "")})
    notes = []
    for k, why in (b.get("notes") or {}).items():
        parts = [x.strip().strip("/") for x in str(k).split("+") if x.strip().strip("/")]
        notes.append((parts, k, str(why)))
    val = {"path": str(p), "missing": False, "ids": dict(b.get("banned_ids") or {}),
           "patterns": [x.lower() for x in b.get("banned_name_patterns") or [] if isinstance(x, str) and x],
           "folders": [x for x in b.get("banned_drive_folders") or [] if isinstance(x, str) and x],
           "windows": win, "notes": notes, "raw": b}
    _CACHE.update(key=key, val=val)
    return val


# ---------------------------------------------------------------- the old helpers (moments.is_banned, same results)
def ids_and_patterns(root=None):
    B = load(root)
    return set(B["ids"]), list(B["patterns"])


def basic(fid, name, ids=None, pats=None, root=None):
    """moments.is_banned's rule, unchanged: the exact Drive id is banned, or a name pattern is in the name."""
    if ids is None: ids, pats = ids_and_patterns(root)
    return fid in ids or any(p in (name or "").lower() for p in pats)


# ---------------------------------------------------------------- single references
def fid_of(src):
    """Drive id (or the 10-char prefix a moment id carries) of a clip reference, else None."""
    s = str(src or "").strip()
    if s.startswith("m:"): return s[2:].split("@")[0] or None
    stem = pathlib.Path(s).stem if ("/" in s or "." in s) else s
    return stem if DRIVE_ID.fullmatch(stem) else None


def _same(fid, bid):
    return bool(fid) and (fid == bid or (len(fid) >= 10 and bid.startswith(fid)))


def _note_reason(s, B):
    low = str(s or "").lower()
    if not low: return None
    p = pathlib.PurePosixPath(low)
    noext = str(p.with_suffix("")) if p.suffix else low
    for parts, key, why in B["notes"]:
        for part in parts:
            q = part.lower()
            if "/" in q:
                if noext == q or noext.endswith("/" + q): return f"banned clip '{part}' (notes): {why}"
            elif p.stem == q or (len(q) >= 6 and q in p.name):
                return f"banned clip '{part}' (notes): {why}"
    return None


def clip_banned(src_or_id, name=None, root=None):
    """Reason the WHOLE clip is banned, or None."""
    B = load(root)
    if B["missing"]: return f"ban list {B['path']} not found (refusing until it is back)"
    s = str(src_or_id or "")
    fid = fid_of(s)
    if fid:
        for bid, why in B["ids"].items():
            if _same(fid, bid): return f"banned clip {bid[:12]}: {why}"
    for t in (name, s):
        if not t: continue
        low = str(t).lower()
        for pat in B["patterns"]:
            if pat in low: return f"banned name '{pat}' in '{pathlib.Path(str(t)).name[:70]}'"
        for fo in B["folders"]:
            if fo.lower() in low: return f"clip from banned Drive folder '{fo}'"
    return _note_reason(s, B) or (_note_reason(name, B) if name else None)


def window_hits(src_or_id, start, end, root=None):
    """Banned windows of this clip that overlap start-end (source seconds)."""
    B = load(root); fid = fid_of(src_or_id)
    if not fid: return []
    a, e = float(start or 0), float(end if end is not None else start or 0)
    if e < a: a, e = e, a
    out = []
    for bid, ws in B["windows"].items():
        if not _same(fid, bid): continue
        for w in ws:
            if a < w["out"] - EPS and w["in"] < e - EPS or (abs(e - a) < 1e-6 and w["in"] + EPS < a < w["out"] - EPS):
                out.append({**w, "fid": bid})
    return out


def window_banned(src_or_id, start, end, root=None, scoped=True, name=None):
    """Reason this window of the clip may not be used (whole-clip ban first), or None. scoped=False ignores line-scoped bans."""
    r = clip_banned(src_or_id, name, root)
    if r: return r
    hs = sorted(window_hits(src_or_id, start, end, root), key=lambda w: not w["hard"])
    hs = [h for h in hs if h["hard"] or scoped]
    if not hs: return None
    h = hs[0]
    return f"banned window {h['fid'][:12]} {h['in']:g}-{h['out']:g}s" + (f" ({h['scope']})" if h["scope"] else "") + f": {h['reason'][:120]}"


# ---------------------------------------------------------------- plans
def shot_windows(plan):
    """Voiceover-mode shot timeline: [{i, at, dur, src, in, out, speed, shot}] in play order; out = in + dur * speed."""
    shots = [s for s in plan.get("shots") or [] if isinstance(s, dict) and "at" in s and s.get("src") is not None]
    shots = sorted(shots, key=lambda x: float(x["at"]))
    try: total = float(plan.get("total") or 0)
    except (TypeError, ValueError): total = 0.0
    out = []
    for i, s in enumerate(shots):
        at = float(s["at"])
        end_at = float(shots[i + 1]["at"]) if i + 1 < len(shots) else max(total, at)
        d = max(0.0, end_at - at)
        src = str(s["src"])
        if "in" in s and s["in"] is not None: a = float(s["in"])
        elif src.startswith("m:") and "@" in src:
            try: a = float(src.split("@", 1)[1])
            except ValueError: a = 0.0
        else: a = 0.0
        spd = float(s.get("speed") or 1.0) or 1.0
        out.append({"i": i, "at": at, "dur": d, "src": src, "in": a, "out": a + d * spd, "speed": spd, "shot": s})
    return out


REF_KEYS = {"src", "file", "fid", "hook_src", "path", "clip", "lib", "video", "name", "source_clip"}
SKIP_KEYS = {"suggest", "intent", "history", "was", "candidates", "options", "alternatives", "rejected", "banned",
             "rendered", "music", "music_pick", "note", "notes"}
OLD_KEY = re.compile(r"(_v\d+|_old|_prev|_orig|_was|_before)$")   # superseded versions kept for the record (real_v1, ...)


def _hit(where, src, a, e, reason, kind):
    return {"where": where, "src": str(src), "in": None if a is None else round(float(a), 3),
            "out": None if e is None else round(float(e), 3), "reason": reason, "hard": kind != "window-scoped", "kind": kind}


def _ref_hits(where, src, a, e, root, name=None):
    r = clip_banned(src, name, root)
    if r: return [_hit(where, src, a, e, r, "clip")]
    if a is None: return []
    return [_hit(where, src, a, e, f"banned window {w['fid'][:12]} {w['in']:g}-{w['out']:g}s"
                 + (f" ({w['scope']})" if w["scope"] else "") + f": {w['reason'][:120]}",
                 "window" if w["hard"] else "window-scoped") for w in window_hits(src, a, e, root)]


def plan_hits(plan, root=None):
    """Every banned clip or window a plan references. Covers rawedit plans (aroll, beats[].broll + split, a-roll pieces in
    beats[].segs, vo-mode shots[] src/in/speed/hook_src) and any other clip-like key (src/file/fid/lib/clip/path/name) in
    any style of plan, e.g. AI beats' "lib". Suggestions/intent/history are skipped (not used). Never raises on odd plans."""
    out = []
    B = load(root)
    if B["missing"]:
        return [_hit("BANNED_CLIPS.json", B["path"], None, None, f"ban list {B['path']} not found", "clip")]
    ar = plan.get("aroll") if isinstance(plan.get("aroll"), dict) else None
    if ar:
        asrc = ar.get("fid") or ar.get("file") or ""
        out += _ref_hits("a-roll", asrc, None, None, root, ar.get("name"))
    for b in plan.get("beats") or []:
        if not isinstance(b, dict): continue
        n = b.get("n")
        if ar and fid_of(ar.get("fid") or ar.get("file")):     # a real creator take (vo-mode a-roll is a voice file)
            for sg in b.get("segs") or []:
                try: out += [h for h in _ref_hits(f"beat {n} a-roll", ar.get("fid") or ar.get("file"), float(sg["in"]), float(sg["out"]), root)
                             if h["kind"] != "clip"]
                except (KeyError, TypeError, ValueError): pass
        br = b.get("broll")
        if isinstance(br, dict):
            try:
                spd = float(br.get("speed") or 1.0) or 1.0; d = float(br.get("dur") or 0) * spd; a = float(br.get("in") or 0)
            except (TypeError, ValueError):
                spd, d, a = 1.0, 0.0, 0.0
            out += _ref_hits(f"beat {n} b-roll", br.get("fid") or br.get("file") or br.get("mid") or "", a, a + d, root, br.get("name"))
            sp = br.get("split")
            if isinstance(sp, dict):
                try: a2 = float(sp.get("in") or 0)
                except (TypeError, ValueError): a2 = 0.0
                out += _ref_hits(f"beat {n} split", sp.get("fid") or sp.get("file") or "", a2, a2 + d, root, sp.get("name"))
    for w in shot_windows(plan):
        out += _ref_hits(f"shot {w['i'] + 1} at {w['at']:.2f}s", w["src"], w["in"], w["out"], root)
        hs = w["shot"].get("hook_src")
        if hs and hs != w["src"]: out += _ref_hits(f"shot {w['i'] + 1} hook_src", hs, None, None, root)
    seen = {(h["src"], h["reason"]) for h in out}

    def walk(x, where, top=False):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in SKIP_KEYS or OLD_KEY.search(str(k)) or (top and k in ("aroll", "shots")): continue
                if k in REF_KEYS and isinstance(v, str) and v.strip():
                    r = clip_banned(v, None, root)
                    if r and (v, r) not in seen:
                        seen.add((v, r)); out.append(_hit(f"{where}.{k}".lstrip("."), v, None, None, r, "clip"))
                elif isinstance(v, (dict, list)):
                    walk(v, f"{where}.{k}")
        elif isinstance(x, list):
            for i, v in enumerate(x): walk(v, f"{where}[{i}]")
    walk(plan, "", top=True)
    for i, s in enumerate(plan.get("shots") or []):   # other clip keys on shots (src / hook_src were checked above)
        if isinstance(s, dict): walk({k: v for k, v in s.items() if k not in ("src", "hook_src")}, f"shots[{i}]")
    return out


def blockers(plan, root=None):
    """plan_hits that must stop a submit / render (whole-clip bans and hard windows; line-scoped windows only warn)."""
    return [h for h in plan_hits(plan, root) if h["hard"]]


# ---------------------------------------------------------------- project files (preflight T06, moved from preflight.py)
SKIP_DIRS = {"__pycache__", "node_modules", "site-packages", "_backup", "_backups", "archive", "old"}
TEXT_EXT = {".py", ".json", ".md", ".txt", ".csv", ".jsonl", ".yaml", ".sh", ".html"}
MEDIA_EXT = {".mp4", ".mov", ".m4v"}
MEDIA_RE = re.compile(r"[^\"'\n/]{3,120}\.(?:mp4|mov|m4v)", re.I)
SKIP_FILES = {"PREFLIGHT.md", "frameio.json", "DELIVERY.md"}


def live_files(d):
    """Project files that can feed the current build: skips venvs/packages/caches and every vN folder except the newest."""
    d = pathlib.Path(d)
    vers = sorted([x for x in d.iterdir() if x.is_dir() and re.fullmatch(r"v\d+", x.name)], key=lambda x: int(x.name[1:]))
    old = set(vers[:-1])
    for f in d.rglob("*"):
        rel = f.relative_to(d).parts
        if any(p.startswith(".") or p in SKIP_DIRS or "env" in p.lower() for p in rel[:-1]) or (d / rel[0]) in old:
            continue
        if f.is_file():
            yield f


def file_hits(dirs, root=None):
    """[(kind, file, key, detail)] for banned ids found as text and banned name patterns in media names, in the live
    files of each project dir. kind 'id': key = drive id, detail = reason; kind 'name': key = media name, detail = pattern.
    Exactly the scan preflight.check_banned did before 2026-11-22 (same files, same matches)."""
    B = load(root)
    ids = list(B["ids"]); pats = [p for p in B["raw"].get("banned_name_patterns", []) if isinstance(p, str) and p]
    out = []
    for d in dirs:
        d = pathlib.Path(d)
        for f in live_files(d):
            names = [f.name] if f.suffix.lower() in MEDIA_EXT else []
            if f.suffix.lower() in TEXT_EXT and f.name not in SKIP_FILES and f.stat().st_size < 3_000_000:
                t = f.read_text(errors="ignore")
                for i in ids:
                    if i in t: out.append(("id", f.relative_to(d.parent), i, B["ids"][i]))
                names += MEDIA_RE.findall(t)
            for n in names:
                for p in pats:
                    if p.lower() in n.lower(): out.append(("name", f.relative_to(d.parent), n, p))
    return out


def index_name(fid):
    """INDEX.csv file name for a Drive id (stdlib csv; '' when the catalogue is not on this machine)."""
    try:
        for r in csv.DictReader(open(INDEX)):
            if fid and fid in r.get("Link", ""): return r.get("New file name", "")
    except OSError:
        pass
    return ""


if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    if not a:
        B = load()
        print(f"{len(B['ids'])} banned clips, {len(B['patterns'])} name patterns, {len(B['folders'])} folders, {len(B['notes'])} notes")
        for fid, ws in B["windows"].items():
            for w in ws: print(f"  window {fid[:12]} {w['in']:g}-{w['out']:g}s {'HARD' if w['hard'] else 'scoped: ' + w['scope']}")
    elif a[0] == "plan":
        p = pathlib.Path(a[1]); p = p / "plan.json" if p.is_dir() else p
        hs = plan_hits(json.loads(p.read_text()))
        for h in hs: print(("BLOCK " if h["hard"] else "WARN  ") + f"{h['where']}: {h['src'][-60:]} {h['in']}-{h['out']} {h['reason'][:110]}")
        print(f"{len(hs)} hit(s), {sum(h['hard'] for h in hs)} blocking"); sys.exit(1 if any(h["hard"] for h in hs) else 0)
    else:
        print(window_banned(a[0], float(a[1]), float(a[2])) if len(a) >= 3 else clip_banned(a[0]) or "not banned")
