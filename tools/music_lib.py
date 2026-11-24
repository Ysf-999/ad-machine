"""Local music library for both editors (rawedit.py real footage, assemble_anim.py AI ads). No kie credits.

Folders (library/music/):
  trendy/    trending TikTok/Reels sounds and viral tracks      (drop files in, or `add <url> --kind trendy`)
  popular/   well-known songs                                    (drop files in, or `add <url> --kind popular`)
  library/   free cleared tracks, one folder per mood (seeded from Mixkit with `fetch-free`)
  A folder named after a mood anywhere in the path tags the track with it (popular/sad/x.mp3 -> sad).
  _stems/    instrumental versions made by Demucs (songs with vocals play these under a voiceover)

Usage: .venv/bin/python -I tools/music_lib.py scan [--force]           analyse new files: tempo, key/mode, energy, drop,
                                                                        vocals (Demucs, trendy/popular), moods (Haiku)
       .venv/bin/python -I tools/music_lib.py add <url|file> [--kind trendy|popular|library] [--mood sad]
       .venv/bin/python -I tools/music_lib.py fetch-free [--per 4]   seed library/<mood>/ from Mixkit
       .venv/bin/python -I tools/music_lib.py source-youtube [--per 6] [--mood m]   copyright-free tracks from YouTube
                                                   (free-to-use producers; Haiku screens for ad fit) -> library/<mood>/
       .venv/bin/python -I tools/music_lib.py import-tiktok <apify dataset id> [...]   trending TikTok songs from an
                                                   s_actors/tiktok-trending-sounds-scraper run (downloadAudio on) -> trendy/
       .venv/bin/python -I tools/music_lib.py list [--mood m] [--kind k]
       .venv/bin/python -I tools/music_lib.py pick --mood happy [--kind any|trendy|popular|library] [--dur 40]
                                                   [--project <name>] [--vocals]   -> prints the chosen file + drop
       .venv/bin/python -I tools/music_lib.py tag "<file substring>" [--mood a,b] [--kind k]
Moods: happy, sad, intense, calm, funny, inspiring, suspense, holiday, heartfelt.
In a plan: "music_mood": "sad" (+ optional "music_kind": "trendy", "music_vocals": true). Hook variants (-h2, -h3) reuse
the base ad's track so the body sounds the same.
"""
import html, json, os, pathlib, re, shutil, subprocess, sys, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from brand import BRAND
LIB = ROOT / "library" / "music"
IDX, USE = LIB / "index.json", LIB / "usage.json"
STEMS = LIB / "_stems"
KINDS = ("trendy", "popular", "library")
MOODS = ("happy", "sad", "intense", "calm", "funny", "inspiring", "suspense", "holiday", "heartfelt")
MOOD_HELP = {"happy": "bright, upbeat, feel-good", "sad": "melancholy, loss, regret, the 'before' pain",
             "intense": "driving, epic, high stakes, fast", "calm": "relaxed, soft, cosy background",
             "funny": "quirky, playful, comedic timing", "inspiring": "uplifting build, hope, transformation",
             "suspense": "tension, mystery, something is wrong", "holiday": "Christmas, festive, gifting",
             "heartfelt": "warm, tender, love and care"}
MIXKIT = {"happy": ["happy", "upbeat", "cheerful"], "sad": ["sad", "melancholic", "emotional"], "intense": ["energetic", "epic", "driving"],
          "calm": ["calm", "relaxed", "mellow"], "funny": ["quirky", "humorous", "playful"], "inspiring": ["uplifting", "hopeful", "motivating"],
          "suspense": ["suspenseful", "mysterious", "tension"], "holiday": ["festive"], "heartfelt": ["sentimental", "tender", "warm"]}
AUDIO = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm")
FF = os.path.dirname(shutil.which("ffmpeg") or "")   # folder of the ffmpeg on PATH (Demucs / yt-dlp use it)
EMPTY = ("the music library is empty: drop tracks into library/music/<trendy|popular|library>/<mood>/ and run "
         "`music_lib.py scan`, or use `music_lib.py add <url|file>` / `fetch-free`")


def env():
    f = ROOT / ".env"
    if f.exists():
        for l in f.read_text().splitlines():
            if "=" in l and not l.lstrip().startswith("#"):
                k, v = l.split("=", 1); os.environ.setdefault(k.strip(), v.strip())


def load(f, d):
    return json.loads(f.read_text()) if f.exists() else d


def save(f, d):
    f.write_text(json.dumps(d, indent=1, ensure_ascii=False))


def rel(p):
    return str(pathlib.Path(p).resolve().relative_to(LIB))


def tracks():
    for p in sorted(LIB.rglob("*")):
        if p.suffix.lower() in AUDIO and "_stems" not in p.parts and not p.name.startswith("."):
            yield p


def kind_of(p):
    parts = pathlib.Path(rel(p)).parts
    return parts[0] if parts[0] in KINDS else "library"


def folder_mood(p):
    return [x for x in pathlib.Path(rel(p)).parts[:-1] if x in MOODS]


# ---------- analysis (numpy only) ----------
def decode(f, sr=22050, secs=None):
    import numpy as np
    cmd = ["ffmpeg", "-v", "error", "-i", str(f)] + (["-t", str(secs)] if secs else []) + ["-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, dtype=np.float32), sr


def analyse(f):
    import numpy as np
    x, sr = decode(f)
    d = len(x) / sr
    if d < 5: return {"duration": round(d, 1), "error": "too short"}
    hop, win = 512, 2048
    n = (len(x) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    S = np.abs(np.fft.rfft(x[idx] * np.hanning(win), axis=1)).astype(np.float32)
    # tempo: autocorrelation of spectral flux, 70-180 BPM, folded into 75-160
    flux = np.maximum(np.diff(np.log1p(S), axis=0), 0).sum(1); flux = flux - flux.mean()
    ac = np.correlate(flux[:6000], flux[:6000], "full")[len(flux[:6000]) - 1:]
    fps = sr / hop; lags = np.arange(int(fps * 60 / 180), int(fps * 60 / 70))
    bpm = 60 * fps / lags[np.argmax(ac[lags])]
    while bpm < 75: bpm *= 2
    while bpm > 160: bpm /= 2
    # key / mode: chroma (55-2000 Hz) against Krumhansl-Schmuckler profiles
    fr = np.fft.rfftfreq(win, 1 / sr); m = (fr > 55) & (fr < 2000)
    pc = (np.round(12 * np.log2(fr[m] / 440.0)) + 9) % 12
    ch = np.array([S[:, m][:, pc == k].sum() for k in range(12)])
    maj = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    mnr = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    sc = [(np.corrcoef(ch, np.roll(p, k))[0, 1], k, nm) for nm, p in (("major", maj), ("minor", mnr)) for k in range(12)]
    best = max(sc); names = "C C# D D# E F F# G G# A A# B".split()
    # energy per second
    sec = int(d); rms = 20 * np.log10(np.sqrt((x[:sec * sr].reshape(sec, sr) ** 2).mean(1)) + 1e-6)
    loud = float(np.percentile(rms, 75)); dyn = float(np.percentile(rms, 90) - np.percentile(rms, 10))
    intro = next((i for i, v in enumerate(rms) if v > loud - 6), 0)
    drop, jump = find_drop(rms, intro, d)
    return {"duration": round(d, 1), "bpm": round(float(bpm)), "key": f"{names[best[1]]} {best[2]}", "mode": best[2],
            "loud_db": round(loud, 1), "dynamics_db": round(dyn, 1), "intro_s": intro, "drop": drop, "drop_jump_db": jump,
            "energy": "high" if loud > -14 and bpm >= 110 else "low" if loud < -22 or bpm < 85 else "medium"}


def find_drop(rms, intro, d):
    """Where the track kicks in, in the usable part (after the fade-in, early enough that 25 s+ of music follows): the
    biggest rise of the next 2 s over the previous 2 s while the previous 2 s is already audible. A rise under 3 dB means
    no real drop: return the point the track reaches full energy instead (it still lands on the hold)."""
    import numpy as np
    lo, hi = intro + 2, int(min(d * 0.6, d - 25, 75))
    floor = np.percentile(rms, 75) - 20
    best, bt = 0.0, None
    for i in range(max(lo, 2), max(hi, lo)):
        prev, nxt = rms[i - 2:i].mean(), rms[i:i + 2].mean()
        if prev > floor and nxt - prev > best: best, bt = float(nxt - prev), i
    if bt is None or best < 3: return float(intro), round(best, 1)
    return float(bt), round(best, 1)


def stems(f):
    """Demucs two-stem split -> _stems/<name>.instrumental.mp3 + how much of the track has singing."""
    import numpy as np
    out = STEMS / (pathlib.Path(rel(f)).with_suffix("").as_posix().replace("/", "__") + ".instrumental.mp3")
    tmp = STEMS / "_tmp"; tmp.mkdir(parents=True, exist_ok=True)
    py = str(ROOT / ".venv" / "bin" / "python")
    r = subprocess.run([py, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs", "--mp3", "-o", str(tmp), str(f)],
                       capture_output=True, text=True, env={**os.environ, "PATH": (FF + ":" if FF else "") + os.environ["PATH"]})
    d = next(tmp.glob(f"htdemucs/{pathlib.Path(f).stem}"), None)
    if r.returncode or not d:
        return {"vocals": None, "stem_error": (r.stderr or "")[-300:]}
    voc, inst = d / "vocals.mp3", d / "no_vocals.mp3"
    v, sr = decode(voc, 8000); a, _ = decode(inst, 8000); k = min(len(v), len(a)) // sr
    vd = 20 * np.log10(np.sqrt((v[:k * sr].reshape(k, sr) ** 2).mean(1)) + 1e-6)
    ad = 20 * np.log10(np.sqrt((a[:k * sr].reshape(k, sr) ** 2).mean(1)) + 1e-6)
    frac = float(((vd > -40) & (vd > ad - 10)).mean())
    inst.replace(out); subprocess.run(["rm", "-rf", str(d)])
    return {"vocals": round(frac, 2), "has_vocals": frac > 0.15, "instrumental": rel(out)}


def moods_ai(rows):
    """Haiku tags moods from the title + measured features (it knows popular songs by name)."""
    env()
    if not os.environ.get("ANTHROPIC_API_KEY"): return {}
    import sys as _sys, os as _os; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import claude_client as anthropic
    items = [{"id": k, "title": v.get("title") or pathlib.Path(k).stem, "kind": v["kind"], "folder_moods": v.get("folder_moods"),
              **{x: v.get(x) for x in ("bpm", "key", "energy", "dynamics_db", "has_vocals", "duration")}} for k, v in rows.items()]
    sysm = (f"You tag music tracks for short video ads ({BRAND['product']}; ads are funny, emotional, dramatic or holiday). "
            f"Moods: {json.dumps(MOOD_HELP)}. For each track return 1-3 moods from that list, best first; keep any folder_moods "
            "first. Use what you know about a named song plus the measured tempo, key and energy. Also a 'use' line under 12 "
            "words saying what kind of ad moment it fits. Reply with JSON only: {\"<id>\": {\"moods\": [...], \"use\": \"...\"}}")
    out = {}
    cl = anthropic.Anthropic()
    for i in range(0, len(items), 25):
        r = cl.messages.create(model="claude-haiku-5-5", max_tokens=8000, system=sysm,
                               messages=[{"role": "user", "content": json.dumps(items[i:i + 25])}])
        t = "".join(getattr(b, "text", "") for b in r.content)
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try: out.update(json.loads(m.group(0)))
            except json.JSONDecodeError: pass
    return out


def scan(force=False, only=None):
    LIB.mkdir(parents=True, exist_ok=True)
    idx = load(IDX, {}); new = {}
    files = [pathlib.Path(only)] if only else list(tracks())
    for f in files:
        k = rel(f)
        if k in idx and "duration" in idx[k] and not force: continue
        print(f"  analysing {k}", flush=True)
        row = {"kind": kind_of(f), "folder_moods": folder_mood(f), "title": idx.get(k, {}).get("title"), **analyse(f)}
        if row["kind"] != "library" and "error" not in row:
            print("    separating vocals (Demucs)...", flush=True); row.update(stems(f))
        idx[k] = {**idx.get(k, {}), **row}; new[k] = idx[k]
    for k in [k for k in idx if not (LIB / k).exists()]: del idx[k]
    if new:
        tags = moods_ai(new)
        for k in new:
            t = tags.get(k) or {}
            ms = [m for m in (idx[k].get("folder_moods") or []) + (t.get("moods") or []) if m in MOODS]
            idx[k]["moods"] = list(dict.fromkeys(ms)) or idx[k].get("moods") or [guess(idx[k])]
            if t.get("use"): idx[k]["use"] = t["use"]
    save(IDX, idx)
    print(f"index: {len(idx)} tracks ({len(new)} new)")
    return idx


def guess(r):
    if r.get("mode") == "minor": return "sad" if r.get("energy") == "low" else "suspense" if r.get("energy") == "medium" else "intense"
    return "calm" if r.get("energy") == "low" else "happy" if r.get("energy") == "medium" else "intense"


# ---------- adding ----------
def add(src, kind="trendy", mood=None):
    dest = LIB / kind / (mood or ""); dest.mkdir(parents=True, exist_ok=True)
    if re.match(r"https?://", src):
        import yt_dlp
        opts = {"format": "bestaudio/best", "outtmpl": str(dest / "%(title).80s.%(ext)s"), "quiet": True, "noplaylist": True,
                "ffmpeg_location": FF or None, "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]}
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(src, download=True)
            f = pathlib.Path(y.prepare_filename(info)).with_suffix(".mp3")
        title = " - ".join(x for x in (info.get("artist") or info.get("uploader"), info.get("track") or info.get("title")) if x)
    else:
        f = dest / pathlib.Path(src).name; subprocess.run(["cp", src, str(f)], check=True); title = pathlib.Path(src).stem
    idx = load(IDX, {}); idx.setdefault(rel(f), {})["title"] = title
    if src.startswith("http"): idx[rel(f)]["source"] = src
    save(IDX, idx); scan(only=f)
    show([rel(f)])


def fetch_free(per=4):
    idx = load(IDX, {}); have = {v.get("source") for v in idx.values()}
    for mood, slugs in MIXKIT.items():
        dest = LIB / "library" / mood; dest.mkdir(parents=True, exist_ok=True)
        got = len(list(dest.glob("*.mp3")))
        for slug in slugs:
            if got >= per: break
            h = urllib.request.urlopen(urllib.request.Request(f"https://mixkit.co/free-stock-music/mood/{slug}/",
                                                              headers={"User-Agent": "Mozilla/5.0"})).read().decode("utf8", "ignore")
            for m in re.finditer(r'data-audio-player-preview-url-value="(https://assets\.mixkit\.co/music/\d+/\d+\.mp3)"', h):
                if got >= per: break
                url = m.group(1)
                if url in have: continue
                t = re.search(r'class="item-grid-card__title"[^>]*>\s*([^<]+?)\s*<', h[m.end():])   # the card's title follows its player
                title = html.unescape(t.group(1) if t else url.rsplit("/", 1)[1])
                f = dest / (re.sub(r"[^\w\- ]", "", title).strip().replace(" ", "-").lower() + ".mp3")
                if f.exists(): continue
                f.write_bytes(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})).read())
                idx[rel(f)] = {"title": f"{title} (Mixkit)", "source": url}; have.add(url); got += 1
                print(f"  {mood:10s} {title}")
    save(IDX, idx); scan()


YT_QUERIES = {
    "happy": ["no copyright upbeat happy background music for ads", "royalty free feel good pop background music free to use"],
    "sad": ["no copyright music sad emotional piano background", "free to use sad cinematic background music no copyright"],
    "intense": ["no copyright energetic epic background music for ads", "royalty free intense trailer action music free to use"],
    "calm": ["no copyright calm acoustic background music", "free to use chill lofi background music no copyright"],
    "funny": ["no copyright funny quirky background music", "royalty free comedy playful background music free to use"],
    "inspiring": ["no copyright inspiring uplifting background music for ads", "free to use motivational corporate cinematic music"],
    "suspense": ["no copyright suspense mystery background music", "free to use tense dramatic background music no copyright"],
    "holiday": ["royalty free christmas background music for videos", "no copyright christmas music free to use upbeat"],
    "heartfelt": ["no copyright heartwarming emotional background music", "free to use warm acoustic family background music"]}
YT_BAD = re.compile(r"type beat|remix|cover|\bhours?\b|1 hour|mix\b|nonstop|non-stop|medley|karaoke|compilation|playlist|collection|lyrics|\bft\.|feat\.|meme|sound effect", re.I)
YT_FREE = re.compile(r"no copyright|royalty.free|free to use|free download|copyright.free|creative commons|\bcc\b|\bncs\b|free music|free use|no copy", re.I)


def source_youtube(per=6, only=None):
    """Copyright-free tracks from YouTube producers: search by mood, keep 1-6 min single tracks labelled free to use, drop
    type beats / remixes / covers / hour mixes, let Haiku choose the best `per` for short brand ads, download, scan."""
    import yt_dlp
    env(); import sys as _sys, os as _os; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import claude_client as anthropic
    idx = load(IDX, {}); have = {v.get("source") for v in idx.values()}
    cl = anthropic.Anthropic()
    for mood, qs in YT_QUERIES.items():
        if only and mood != only: continue
        cand = {}
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True, "skip_download": True}) as y:
            for q in qs:
                for e in y.extract_info(f"ytsearch30:{q}", download=False)["entries"]:
                    t, ch, d = e.get("title") or "", e.get("channel") or "", e.get("duration") or 0
                    url = f"https://www.youtube.com/watch?v={e['id']}"
                    if not (60 <= d <= 360) or YT_BAD.search(t) or not YT_FREE.search(t + " " + ch) or url in have: continue
                    if int(e.get("view_count") or 0) < 10000: continue   # unproven uploads sound unproven
                    cand[e["id"]] = {"id": e["id"], "title": t, "channel": ch, "secs": int(d), "views": int(e.get("view_count") or 0)}
        if not cand: print(f"  {mood}: no candidates"); continue
        msg = (f"Pick music for short (20-60 s) Facebook/Instagram video ads for {BRAND['brand']} ({BRAND['product']}); buyers are "
               f"{BRAND['audience']}. Mood wanted: {mood} ({MOOD_HELP[mood]}). From the candidates, choose the "
               f"best {per}: polished, modern, sounds like a real ad or film, instrumental, from a producer offering it free to use. "
               "Skip cheesy stock/corporate-ukulele clichés unless the mood is funny, skip meme sounds, game music, beats sold for "
               "lease, covers of famous songs, and near-duplicates of each other. Prefer more views when quality is equal. "
               'Reply JSON only: {"pick": ["<id>", ...]}\n' + json.dumps(list(cand.values())))
        r = cl.messages.create(model="claude-haiku-5-5", max_tokens=8000, messages=[{"role": "user", "content": msg}])
        t = "".join(getattr(b, "text", "") for b in r.content); m = re.search(r"\{.*\}", t, re.S)
        dest = LIB / "library" / mood
        need = per - len([k for k, v in idx.items() if v.get("from") == "youtube" and k.startswith(f"library/{mood}/") and (LIB / k).exists()])
        if need <= 0: print(f"  {mood}: already has {per} YouTube tracks"); continue
        picks = [i for i in (json.loads(m.group(0)).get("pick", []) if m else []) if i in cand][:need]
        if not picks: print(f"  {mood}: Haiku kept none of {len(cand)} candidates; reply: {t[:200]}")
        dest = LIB / "library" / mood; dest.mkdir(parents=True, exist_ok=True)
        for i in picks:
            c = cand[i]; url = f"https://www.youtube.com/watch?v={i}"
            name = re.sub(r"[^\w\- ]", "", re.split(r"[|\[(]| - (?:no|free|royalty)", c["title"], flags=re.I)[0]).strip()[:60] or i
            stem = re.sub(r"\s+", "-", name.lower()) + f"-yt{i[:4]}"
            opts = {"format": "bestaudio/best", "outtmpl": str(dest / f"{stem}.%(ext)s"), "quiet": True, "noprogress": True, "noplaylist": True,
                    "ffmpeg_location": FF or None, "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]}
            try:
                with yt_dlp.YoutubeDL(opts) as y: y.download([url])
            except Exception as ex:
                print(f"  {mood}: download failed {c['title'][:50]}: {str(ex)[:80]}"); continue
            idx[rel(dest / f"{stem}.mp3")] = {"title": f"{c['title']} ({c['channel']})", "source": url, "channel": c["channel"],
                                               "views": c["views"], "from": "youtube"}
            have.add(url); print(f"  {mood:10s} {c['title'][:70]}  [{c['channel']}, {c['views']:,} views]", flush=True)
        save(IDX, idx)
    scan()


def apify_token():
    env()
    return os.environ.get("APIFY_TOKEN") or None   # set APIFY_TOKEN in .env


def import_tiktok(datasets):
    """Trending TikTok songs (sampled from the US Explore feed by the Apify actor) -> trendy/. Haiku drops what is not an ad
    bed (SFX, voice memes, sub-25 s snippets, foreign 'original sound' clips). Keeps plays + TikTok's commercial-use flag."""
    env(); import sys as _sys, os as _os; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import claude_client as anthropic
    tok = apify_token(); rows = {}
    for ds in datasets:
        u = f"https://api.apify.com/v2/datasets/{ds}/items?clean=true&format=json" + (f"&token={tok}" if tok else "")
        for r in json.loads(urllib.request.urlopen(u).read()):
            if r.get("audioFileUrl"): rows[str(r["musicId"])] = r
    idx = load(IDX, {}); have = {v.get("source") for v in idx.values()}
    cand = [{"id": f"t{k}", "title": r["musicTitle"], "author": r["musicAuthor"], "secs": r.get("musicDurationSeconds"),
             "plays_in_sample": r.get("samplePlays"), "videos_in_sample": r.get("videosInSample"), "categories": r.get("categories")}
            for k, r in rows.items() if f"tiktok:{k}" not in have and (r.get("musicDurationSeconds") or 0) >= 25]
    if not cand: print("nothing new"); return
    msg = ("These sounds are trending on TikTok right now. Keep the ones usable as the music bed of a 20-60 s Facebook/Instagram "
           f"ad for {BRAND['brand']} ({BRAND['product']}; {BRAND['audience']}): real music with a clear mood. Drop sound effects, "
           "voice or meme clips, chants, foreign-language 'original sound' uploads, and anything that only works as a joke. "
           'Reply JSON only: {"keep": ["<id>", ...]}\n' + json.dumps(cand))
    r = anthropic.Anthropic().messages.create(model="claude-haiku-5-5", max_tokens=8000, messages=[{"role": "user", "content": msg}])
    t = "".join(getattr(b, "text", "") for b in r.content); m = re.search(r"\{.*\}", t, re.S)
    keep = [str(k).lstrip("t") for k in (json.loads(m.group(0)).get("keep", []) if m else []) if str(k).lstrip("t") in rows]
    if not keep: print("Haiku reply:", t[:400])
    dest = LIB / "trendy"; dest.mkdir(parents=True, exist_ok=True)
    for k in keep:
        x = rows[k]; name = re.sub(r"[^\w\- ]", "", f"{x['musicTitle']} {x['musicAuthor']}").strip()[:60]
        f = dest / (re.sub(r"\s+", "-", name.lower()) + f"-tt{k[-4:]}.mp3")
        f.write_bytes(urllib.request.urlopen(x["audioFileUrl"]).read())
        idx[rel(f)] = {"title": f"{x['musicTitle']} - {x['musicAuthor']}", "source": f"tiktok:{k}", "from": "tiktok",
                       "tiktok_commercial": bool(x.get("musicIsCommercial")), "tiktok_plays": x.get("samplePlays"),
                       "tiktok_videos": x.get("videosInSample"), "tiktok_url": x.get("musicUrl")}
        print(f"  {'cleared ' if x.get('musicIsCommercial') else 'trending'} {x['musicTitle'][:40]:40s} {x['musicAuthor'][:30]:30s} {x.get('samplePlays') or 0:>12,} plays")
    print(f"kept {len(keep)} of {len(cand)}"); save(IDX, idx); scan()


# ---------- choosing ----------
def base_name(p):
    return re.sub(r"-[hH]\d+$", "", p or "")


def pick(mood, kind="any", dur=None, project=None, vocals=False, hold=0.0, quiet=False):
    """Best track for a mood: mood rank, kind, long enough from its drop, least used. Returns a dict or None."""
    idx = load(IDX, {}); use = load(USE, {})
    if project:   # hook variants keep the base ad's track
        for k, ps in use.items():
            if k in idx and base_name(project) in {base_name(x.split("|")[0]) for x in ps} and mood in (idx[k].get("moods") or []):
                return choice(k, idx[k], vocals, project, use)
    best = None
    for k, r in idx.items():
        if "error" in r or mood not in (r.get("moods") or []): continue
        if kind != "any" and r["kind"] != kind: continue
        s = 3 - r["moods"].index(mood)
        if dur: s += 1 if r["duration"] - max(r.get("drop", 0) - hold, 0) >= dur else -2
        if hold and (r.get("drop") or 0) >= hold and (r.get("drop_jump_db") or 0) >= 3: s += 1   # its drop can land on the hold
        s -= 0.6 * len(use.get(k, []))
        if r.get("has_vocals") and not vocals and not r.get("instrumental"): s -= 3
        if best is None or s > best[0]: best = (s, k, r)
    if not best:
        if not idx:
            if not quiet: print(EMPTY)
            return None
        if not quiet: print(f"no '{mood}' track{'' if kind == 'any' else ' of kind ' + kind} in {LIB} (scan, add or fetch-free)")
        return None
    return choice(best[1], best[2], vocals, project, use)


def choice(k, r, vocals, project, use):
    f = LIB / k
    if r.get("has_vocals") and not vocals and r.get("instrumental"): f = LIB / r["instrumental"]
    if project:
        tag = f"{project}|{f.name}"
        if tag not in use.setdefault(k, []): use[k].append(tag); save(USE, use)
    return {"file": str(f), "track": k, "title": r.get("title") or pathlib.Path(k).stem, "kind": r["kind"],
            "moods": r.get("moods"), "drop": r.get("drop"), "bpm": r.get("bpm"), "instrumental": f.name.endswith(".instrumental.mp3")}


def show(keys=None, mood=None, kind=None):
    idx = load(IDX, {}); use = load(USE, {})
    if not idx: print(EMPTY); return
    for k, r in sorted(idx.items(), key=lambda kv: (kv[1].get("kind", ""), (kv[1].get("moods") or ["~"])[0], kv[0])):
        if keys and k not in keys: continue
        if mood and mood not in (r.get("moods") or []): continue
        if kind and r.get("kind") != kind: continue
        v = "" if r.get("has_vocals") is None else (" vocals->instrumental" if r.get("has_vocals") else " instrumental")
        print(f"{r.get('kind','?'):8s} {','.join(r.get('moods') or ['?']):24s} {r.get('bpm','?'):>4} bpm {r.get('key','?'):9s} "
              f"{r.get('duration',0):5.0f}s drop {r.get('drop',0):5.1f}s used {len(use.get(k, []))}{v}  {k}"
              + (f"\n{'':34s}{r['use']}" if r.get("use") else ""))


def tag(sub, moods=None, kind=None):
    idx = load(IDX, {}); hit = [k for k in idx if sub.lower() in k.lower()]
    if len(hit) != 1: sys.exit(f"{len(hit)} tracks match '{sub}': {hit[:5]}")
    k = hit[0]
    if moods: idx[k]["moods"] = [m for m in moods.split(",") if m in MOODS]
    if kind: idx[k]["kind"] = kind
    save(IDX, idx); show([k])


def main():
    a = sys.argv[1:]
    if not a: sys.exit(__doc__)
    opt = lambda n, d=None: a[a.index(n) + 1] if n in a else d
    c = a[0]
    if c == "scan": scan("--force" in a)
    elif c == "add": add(a[1], opt("--kind", "trendy"), opt("--mood"))
    elif c == "fetch-free": fetch_free(int(opt("--per", 4)))
    elif c == "import-tiktok": import_tiktok(a[1:])
    elif c == "source-youtube": source_youtube(int(opt("--per", 6)), opt("--mood"))
    elif c == "list": show(mood=opt("--mood"), kind=opt("--kind"))
    elif c == "tag": tag(a[1], opt("--mood"), opt("--kind"))
    elif c == "pick":
        r = pick(opt("--mood"), opt("--kind", "any"), float(opt("--dur")) if opt("--dur") else None, opt("--project"), "--vocals" in a)
        if r: print(json.dumps(r, indent=1))
    else: sys.exit(__doc__)


if __name__ == "__main__":
    main()
