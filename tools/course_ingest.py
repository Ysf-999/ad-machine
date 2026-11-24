"""Ingest a video course from Drive into text notes, without any frame ever entering the Claude Code session.

Built 2026-11-05 for the "Video Ads Mastery" + "Video Editing Breakdowns" course (owner: jason04liang, shared by link).
Usage:  .venv/bin/python -I tools/course_ingest.py <kb-dir>      (kb-dir holds lessons.json)
lessons.json: [{"id": <drive file id>, "name": "<file name>", "slug": "A01", "module": "<module name>", "size": <bytes>}]

Per lesson, idempotent (re-run resumes):
  1. download   course/<NN - module>/<name>   (public usercontent URL, size checked)
  2. transcribe transcripts/<slug>.json + .txt (mlx-whisper large-v3-turbo, [mm:ss] segments)
  3. frames     frames/<slug>/f_<sec>.jpg   (one every FRAME_EVERY s, 1280 px wide)
  4. windows    window-notes/<slug>_wNN.md  (Sonnet reads WINDOW s of transcript + its frames)
  5. lesson     lesson-notes/<slug>.md      (Sonnet merges the window notes)
Threads: one downloader, one transcriber (GPU), a pool of analysers.
"""
import base64, io, json, os, pathlib, queue, re, subprocess, sys, threading, time, traceback

ROOT = pathlib.Path(__file__).resolve().parent.parent
for l in (ROOT / ".env").read_text().splitlines():
    if "=" in l and not l.startswith("#"):
        k, v = l.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
import sys as _sys, os as _os; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import claude_client as anthropic
from PIL import Image

KB = pathlib.Path(sys.argv[1]).resolve()
LESSONS = json.loads((KB / "lessons.json").read_text())
MODULE_DIRS = {"Video Ads Mastery": ROOT / "course" / "07 - Video Ads Mastery",
               "Video Editing Breakdowns": ROOT / "course" / "08 - Video Editing Breakdowns"}
MODEL = os.environ.get("INGEST_MODEL", "claude-sonnet-5-5")
FRAME_EVERY, WINDOW = 15, 180
LOG = KB / "ingest.log"
lock = threading.Lock()
client = anthropic.Anthropic()


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    with lock:
        print(line, flush=True)
        with open(LOG, "a") as f:
            f.write(line + "\n")


def vid_path(L):
    d = MODULE_DIRS[L["module"]]; d.mkdir(parents=True, exist_ok=True)
    return d / L["name"]


def duration(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout.strip() or 0)


def download(L):
    p = vid_path(L)
    if p.exists() and p.stat().st_size == L["size"]:
        return p
    url = f"https://drive.usercontent.google.com/download?id={L['id']}&export=download&confirm=t"
    for attempt in range(4):
        subprocess.run(["curl", "-sL", "--retry", "3", "-o", str(p) + ".part", url])
        part = pathlib.Path(str(p) + ".part")
        if part.exists() and part.stat().st_size == L["size"]:
            part.rename(p); log(f"DOWNLOADED {L['slug']} {L['size']//1_000_000} MB"); return p
        log(f"download size mismatch {L['slug']} attempt {attempt}"); time.sleep(10)
    raise RuntimeError(f"download failed {L['slug']}")


def transcribe(L, p):
    out = KB / "transcripts" / f"{L['slug']}.json"
    if out.exists():
        return
    import mlx_whisper
    wav = KB / "transcripts" / f"{L['slug']}.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(p), "-vn", "-ac", "1", "-ar", "16000", str(wav)], check=True)
    r = mlx_whisper.transcribe(str(wav), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en")
    segs = [{"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"].strip()} for s in r["segments"]]
    txt = "\n".join(f"[{int(s['start'])//60:02d}:{int(s['start'])%60:02d}] {s['text']}" for s in segs)
    (KB / "transcripts" / f"{L['slug']}.txt").write_text(f"# {L['slug']} {L['module']} / {L['name']}\n\n{txt}\n")
    out.write_text(json.dumps({"duration": duration(p), "segments": segs}))
    wav.unlink()
    log(f"TRANSCRIBED {L['slug']} {len(segs)} segs")


def frames(L, p):
    d = KB / "frames" / L["slug"]
    if (d / ".done").exists():
        return
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(p), "-vf", f"fps=1/{FRAME_EVERY},scale=1280:-2",
                    "-q:v", "4", str(d / "raw_%05d.jpg")], check=True)
    for f in sorted(d.glob("raw_*.jpg")):
        n = int(f.stem.split("_")[1]) - 1
        f.rename(d / f"f_{n*FRAME_EVERY:05d}.jpg")
    (d / ".done").write_text("ok")
    log(f"FRAMES {L['slug']} {len(list(d.glob('f_*.jpg')))}")


def mmss(s):
    return f"{int(s)//60:02d}:{int(s)%60:02d}"


def img_block(path):
    im = Image.open(path).convert("RGB"); im.thumbnail((1280, 1280))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=80)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.standard_b64encode(buf.getvalue()).decode()}}


WINDOW_SYS = """You are extracting lessons from one window of a video-ad EDITING course (screen recordings of an editor working
in an NLE, plus example ads). The notes feed an AI agent that edits Meta/TikTok direct-response video ads for a DTC
brand. The agent edits with ffmpeg + Python (cuts, speed, zoom/punch-ins, overlays, captions burned as
ASS subtitles, music + SFX mixing, b-roll inserts, 9:16 output) and can generate AI voiceover/images/video. It cannot
click around a GUI editor.

You get the transcript of this window and frames sampled every 15 s (time stamps given). Write faithful markdown notes:
## What is taught  (2-4 sentences)
## Concrete rules and numbers  (bullets; keep every number the instructor gives or the screen shows: durations, cut
   frequency, zoom %, keyframe timing, font/size/stroke/colour, caption words per card, safe-zone margins, dB levels,
   speed %, transition length, effect names and settings)
## What the screen shows that the transcript does not  (timeline structure, layer stack, effect panels and their values,
   caption look, b-roll density, example ads and what makes them work). Say "unclear" rather than guess.
## Tools, plugins, sites, resources named
## Worth quoting  (max 3 short verbatim lines)
Rules: never invent; if the window is filler (intro, small talk) say so in one line and stop. No preamble."""

LESSON_SYS = """You merge per-window notes of ONE lesson from a video-ad editing course into one lesson file for an AI agent
that edits direct-response video ads with ffmpeg + Python (it cannot drive a GUI editor; it can burn ASS captions,
cut, retime, zoom, overlay, mix audio, generate AI VO/images/video). Write markdown:
# <slug> — <lesson title>
**One-line summary.**
## Key lessons  (numbered; each one actionable, with every number kept; cite [mm:ss])
## Editing recipe  (if the lesson walks through an edit: the steps in order, as an editor would do them)
## On-screen specifics  (settings, values, layer stacks, caption styles, example ads described)
## How an ffmpeg/Python agent applies this  (for each key lesson: AUTOMATE (how, concretely) / JUDGE (needs a model or
   human look; say what to check) / SKIP (GUI-only or irrelevant, say why))
## Tools and resources named
## Quotes  (max 5)
Faithful only: drop filler, merge duplicates, never invent numbers. No preamble."""


def call(system, content, max_tokens):
    for attempt in range(6):
        try:
            r = client.messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                                       messages=[{"role": "user", "content": content}])
            return "".join(b.text for b in r.content if b.type == "text")
        except Exception as e:  # rate limits, overload
            log(f"api retry {attempt}: {str(e)[:120]}"); time.sleep(20 * (attempt + 1))
    raise RuntimeError("api failed")


def analyse_window(L, segs, frame_dir, w, t0, t1):
    out = KB / "window-notes" / f"{L['slug']}_w{w:02d}.md"
    if out.exists():
        return
    text = "\n".join(f"[{mmss(s['start'])}] {s['text']}" for s in segs if t0 <= s["start"] < t1)
    content = [{"type": "text", "text": f"Lesson {L['slug']}: {L['module']} / {L['name']}\nWindow {mmss(t0)}–{mmss(t1)}\n\nTRANSCRIPT:\n{text or '(no speech)'}\n\nFRAMES:"}]
    for f in sorted(frame_dir.glob("f_*.jpg")):
        t = int(f.stem.split("_")[1])
        if t0 <= t < t1:
            content += [{"type": "text", "text": f"frame at {mmss(t)}"}, img_block(f)]
    out.write_text(f"<!-- {L['slug']} {mmss(t0)}-{mmss(t1)} -->\n" + call(WINDOW_SYS, content, 3000))


def analyse(L):
    out = KB / "lesson-notes" / f"{L['slug']}.md"
    if out.exists():
        return
    tj = json.loads((KB / "transcripts" / f"{L['slug']}.json").read_text())
    dur = tj["duration"]; fd = KB / "frames" / L["slug"]
    nw = max(1, int((dur + WINDOW - 1) // WINDOW))
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda w: analyse_window(L, tj["segments"], fd, w, w * WINDOW, (w + 1) * WINDOW), range(nw)))
    notes = "\n\n".join((KB / "window-notes" / f"{L['slug']}_w{w:02d}.md").read_text() for w in range(nw))
    body = call(LESSON_SYS, [{"type": "text", "text": f"slug {L['slug']}, lesson title: {L['name'][:-4]} ({L['module']}), "
                              f"length {mmss(dur)}.\n\nWINDOW NOTES:\n\n{notes}"}], 8000)
    out.write_text(body)
    log(f"LESSON NOTES {L['slug']} ({nw} windows)")


def main():
    order = sorted(LESSONS, key=lambda L: L["size"])  # small lessons first so notes start flowing
    tq, aq = queue.Queue(), queue.Queue()

    def downloader():
        for L in order:
            try:
                tq.put((L, download(L)))
            except Exception:
                log(f"FAIL download {L['slug']}\n{traceback.format_exc()}")
        tq.put(None)

    def transcriber():
        while (item := tq.get()) is not None:
            L, p = item
            try:
                frames(L, p); transcribe(L, p); aq.put(L)
            except Exception:
                log(f"FAIL transcribe {L['slug']}\n{traceback.format_exc()}")
        for _ in range(3):
            aq.put(None)

    def analyser():
        while (L := aq.get()) is not None:
            try:
                analyse(L)
            except Exception:
                log(f"FAIL analyse {L['slug']}\n{traceback.format_exc()}")

    ts = [threading.Thread(target=downloader), threading.Thread(target=transcriber)] + \
         [threading.Thread(target=analyser) for _ in range(3)]
    for t in ts: t.start()
    for t in ts: t.join()
    log("ALL DONE")


if __name__ == "__main__":
    main()
