"""Suno on kie.ai: an instrumental bed, or a sung song with hook takes and word timings.

Usage: music.py <out.mp3> "<style description>" [--seconds 45] [--title "..."] [--jobs jobs.jsonl] [--key music]
  music.py song <out.mp3> <lyrics.txt> "<style>" [--gender f|m] [--seconds N] [--title "..."] [--jobs ...] [--key song]
  music.py hook <out.mp3> <hook_lyrics.txt> <lead.tracks.json> [--pick 1] [--weight 0.85] [--gender f|m] [--key hook2]
  music.py times <x.tracks.json> [--pick 1]    word timings -> <x>.segments.json (beat_grid.py + song_plan.py read it)
Suno returns 2 tracks; the first is saved as <out>, the second as <out stem>_alt.mp3. Prints creditsConsumed.
song/hook also write <out stem>.tracks.json (task id, track ids, lyrics, style). kie deletes tracks after 14 days, so a
hook take made later falls back to uploading the lead mp3. hook lyrics = the hook's lines + Verse 1's first line, so
there is a natural join to cut on; audio_weight 0.85 is the course's Audio Influence setting that keeps the voice.
"""
import json, pathlib, re, sys, httpx
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import kie


def generate(out, style, seconds=45, title="Ad bed", jobs=None, key="music", negative="vocals, singing, lyrics, harsh noise"):
    out = pathlib.Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    jobs = jobs or str(out.parent / "jobs.jsonl")
    body = {"model": "ai-music-api/generate", "input": {"custom_mode": True, "instrumental": True, "model": "V6_MINI",
            "title": title[:80], "style": style[:1000], "negative_tags": negative, "duration": int(seconds), "variety": 1}}
    saved = kie._jobs(jobs).get(key, {})
    task_id = None if saved.get("state") == "fail" else saved.get("taskId")
    if not task_id:
        task_id = kie.create(body); kie._log(jobs, {"key": key, "taskId": task_id, "model": body["model"], "state": "submitted"})
        print(f"SUBMITTED {key} {task_id}", flush=True)
    d = kie.wait(task_id, every=10)
    if not d or d["state"] != "success":
        kie._log(jobs, {"key": key, "taskId": task_id, "state": "fail", "failMsg": (d or {}).get("failMsg")})
        sys.exit(f"music failed: {(d or {}).get('failMsg')}")
    res = d.get("resultJson"); res = json.loads(res) if isinstance(res, str) else res
    tracks = (res.get("response") or {}).get("data") or res.get("data") or []
    urls = [t.get("audio_url") or t.get("source_audio_url") for t in tracks if isinstance(t, dict)] or res.get("resultUrls", [])
    files = []
    for i, u in enumerate(urls[:2]):
        dest = out if i == 0 else out.with_name(out.stem + "_alt" + out.suffix)
        dest.write_bytes(httpx.get(u, timeout=300, follow_redirects=True).content); files.append(str(dest))
    kie._log(jobs, {"key": key, "taskId": task_id, "state": "success", "files": files, "creditsConsumed": d.get("creditsConsumed"), "raw": res if not urls else None})
    print(f"OK {key} credits={d.get('creditsConsumed')} {files}", flush=True)
    if not files:
        print(json.dumps(res)[:1500])
    return files


SONG_MODEL = "V6"
SONG_TAIL = ("Starts singing immediately, no long intro, no instrumental solos, no ad-libs, no spoken words, "
             "no added verses or repeated sections, clean ending.")
SONG_NEGATIVE = "spoken word, ad-libs, long instrumental intro, instrumental solo"


def _run(body, jobs, key):
    """Submit one Suno task, or resume it from jobs.jsonl. Returns (task_id, tracks, credits)."""
    saved = kie._jobs(jobs).get(key, {})
    task_id = None if saved.get("state") == "fail" else saved.get("taskId")
    if not task_id:
        task_id = kie.create(body); kie._log(jobs, {"key": key, "taskId": task_id, "model": body["model"], "state": "submitted"})
        print(f"SUBMITTED {key} {task_id}", flush=True)
    d = kie.wait(task_id, every=10)
    if not d or d["state"] != "success":
        kie._log(jobs, {"key": key, "taskId": task_id, "state": "fail", "failMsg": (d or {}).get("failMsg")})
        sys.exit(f"{key} failed: {(d or {}).get('failMsg')}")
    res = d.get("resultJson"); res = json.loads(res) if isinstance(res, str) else res
    return task_id, (res.get("response") or {}).get("data") or res.get("data") or [], d.get("creditsConsumed")


def _save(out, task_id, tracks, credits, jobs, key, **meta):
    rows = []
    for i, t in enumerate(tracks[:2]):
        dest = out if i == 0 else out.with_name(out.stem + "_alt" + out.suffix)
        dest.write_bytes(httpx.get(t.get("audio_url") or t.get("source_audio_url"), timeout=300, follow_redirects=True).content)
        rows.append({"file": str(dest), "id": t.get("id"), "duration": t.get("duration")})
    (out.with_name(out.stem + ".tracks.json")).write_text(json.dumps({"task_id": task_id, "tracks": rows, **meta}, indent=2))
    kie._log(jobs, {"key": key, "taskId": task_id, "state": "success", "files": [r["file"] for r in rows], "creditsConsumed": credits})
    print(f"OK {key} credits={credits} " + " ".join(f"{r['file']} ({r['duration']}s)" for r in rows), flush=True)


def clean_lyrics(text):
    """[Beat N] tags are for the grid, not the singer. [Verse]/[Chorus] stay."""
    return re.sub(r"(?im)^\s*\[beat[^\]]*\]\s*$\n?", "", text).strip()


def song(out, lyrics, style, gender=None, seconds=None, title="Ad song", jobs=None, key="song"):
    out = pathlib.Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    jobs = jobs or str(out.parent / "jobs.jsonl")
    if SONG_TAIL not in style:
        style = f"{style.rstrip()} {SONG_TAIL}"
    inp = {"custom_mode": True, "instrumental": False, "model": SONG_MODEL, "title": title[:80], "style": style[:1000],
           "lyrics": clean_lyrics(lyrics)[:5000], "negative_tags": SONG_NEGATIVE, "variety": 1}
    if gender: inp["vocal_gender"] = gender
    if seconds: inp["duration"] = int(seconds)
    task_id, tracks, credits = _run({"model": "ai-music-api/generate", "input": inp}, jobs, key)
    _save(out, task_id, tracks, credits, jobs, key, lyrics=inp["lyrics"], style=inp["style"], gender=gender, title=inp["title"])


def hook(out, lyrics, lead_json, pick=1, weight=0.85, gender=None, title=None, jobs=None, key="hook"):
    """A short take of another hook, built from the lead song so the voice and sound match."""
    out = pathlib.Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    jobs = jobs or str(out.parent / "jobs.jsonl")
    lead = json.loads(pathlib.Path(lead_json).read_text()); track = lead["tracks"][pick - 1]
    inp = {"instrumental": False, "model": SONG_MODEL, "title": (title or lead.get("title", "Ad song"))[:80], "style": lead["style"],
           "lyrics": clean_lyrics(lyrics)[:5000], "audio_weight": weight, "negative_tags": SONG_NEGATIVE}
    if gender or lead.get("gender"): inp["vocal_gender"] = gender or lead["gender"]
    import time
    age_days = (time.time() - pathlib.Path(lead_json).stat().st_mtime) / 86400
    inp.update({"upload_url": kie.upload(track["file"])} if age_days > 13 else {"task_id": lead["task_id"], "audio_id": track["id"]})
    task_id, tracks, credits = _run({"model": "ai-music-api/upload-and-cover-audio", "input": inp}, jobs, key)
    _save(out, task_id, tracks, credits, jobs, key, lyrics=inp["lyrics"], style=inp["style"], gender=inp.get("vocal_gender"), title=inp["title"])


def times(tracks_json, pick=1):
    """Word timings Suno aligned to the lyrics. Prints the intro trim point (first sung word minus 0.2 s)."""
    f = pathlib.Path(tracks_json); meta = json.loads(f.read_text())
    d = kie._req("POST", f"{kie.API}/jobs/createTask", json={"model": "ai-music-api/timeStamped-lyrics",
                 "input": {"task_id": meta["task_id"], "audio_id": meta["tracks"][pick - 1]["id"]}})
    if d.get("code") != 200:
        sys.exit(f"times refused: {d.get('code')} {d.get('msg')}")
    data = d["data"]
    if data.get("taskId"):  # some accounts get an async task instead of the documented sync reply
        r = kie.wait(data["taskId"], every=5); data = r.get("resultJson"); data = json.loads(data) if isinstance(data, str) else data
    while isinstance(data.get("data"), dict): data = data["data"]
    words = data.get("alignedWords") or data.get("aligned_words") or []
    segs = []
    for w in words:
        t = " ".join(re.sub(r"\[[^\]]*\]", " ", w.get("word", "")).split())
        if t:
            segs.append({"start": w.get("startS", w.get("start_s")), "end": w.get("endS", w.get("end_s")), "text": t})
    if not segs:
        sys.exit(f"no aligned words returned: {json.dumps(d)[:400]}")
    out = f.with_name(f.name.replace(".tracks.json", "") + (f"_alt" if pick == 2 else "") + ".segments.json")
    out.write_text(json.dumps(segs, indent=1))
    print(f"OK {out} {len(segs)} words, first word {segs[0]['start']:.2f}s (intro trim {max(0, segs[0]['start'] - .2):.2f}s), last word ends {segs[-1]['end']:.2f}s")


if __name__ == "__main__":
    a = sys.argv[1:]
    def opt(n, d, cast=str):
        if n in a:
            i = a.index(n); v = cast(a[i + 1]); del a[i:i + 2]; return v
        return d
    cmd = a.pop(0) if a and a[0] in ("song", "hook", "times") else None
    if cmd == "times":
        times(a[0], opt("--pick", 1, int)); sys.exit()
    if cmd == "hook":
        pick = opt("--pick", 1, int); weight = opt("--weight", 0.85, float); g = opt("--gender", None); jobs = opt("--jobs", None); key = opt("--key", "hook")
        hook(a[0], pathlib.Path(a[1]).read_text(), a[2], pick, weight, g, jobs=jobs, key=key); sys.exit()
    if cmd == "song":
        g = opt("--gender", None); secs = opt("--seconds", None, int); title = opt("--title", "Ad song"); jobs = opt("--jobs", None); key = opt("--key", "song")
        song(a[0], pathlib.Path(a[1]).read_text(), a[2], g, secs, title, jobs, key); sys.exit()
    secs = opt("--seconds", 45, int); title = opt("--title", "Ad bed"); jobs = opt("--jobs", None); key = opt("--key", "music")
    generate(a[0], a[1], secs, title, jobs, key)
