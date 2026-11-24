"""Taste references: a few great ads per style, with the measurable facts and the owner's reason why they work.

Usage:
  taste.py add <skill> <video> "<why it works>" [--name N] [--narration <audio/video file>]
        copies the video to taste/<skill>/, measures it (length, cuts, average shot length, speech pace, transcript),
        and writes taste/<skill>/<name>.md. --narration = a recording of the owner talking through the ad; it is transcribed
        into the note (the cheapest way to capture why a cut, pace or hook works).
  taste.py from-ad <project> "<why it works>"     save one of our own approved/launched masters as a reference
  taste.py list [skill]
  taste.py brief <skill>                          one compact text block of every note for that style (what a skill reads)

Notes are text. Nothing here sends a frame into a session.
"""
import json, pathlib, re, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TASTE = ROOT / "taste"
sys.path.insert(0, str(pathlib.Path(__file__).parent))


def probe(v):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_type", "-of", "json", str(v)],
                       capture_output=True, text=True)
    j = json.loads(r.stdout or "{}")
    dur = float(j.get("format", {}).get("duration", 0))
    vs = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    return dur, vs.get("width"), vs.get("height")


def cuts(v, thresh=0.3):
    """Scene-change timestamps (seconds) from ffmpeg's scene score."""
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(v), "-vf", f"select='gt(scene,{thresh})',showinfo", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    return [float(m) for m in re.findall(r"pts_time:([\d.]+)", r.stderr)]


def transcribe(f):
    try:
        import mlx_whisper
    except ImportError:
        return None
    r = mlx_whisper.transcribe(str(f), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en", word_timestamps=True)
    words = [w for s in r["segments"] for w in s.get("words", [])]
    return r["text"].strip(), words


def note_for(video, why, name, narration=None):
    dur, w, h = probe(video)
    cs = cuts(video)
    asl = dur / (len(cs) + 1) if dur else 0
    t = transcribe(video)
    lines = [f"# {name}", "", f"**Why it works (owner):** {why}", ""]
    if narration:
        nt = transcribe(narration)
        if nt:
            lines += ["**Owner narration (transcribed):**", "", nt[0], ""]
    lines += ["## Measured", f"- length {dur:.1f} s, {w}x{h}", f"- {len(cs)} cuts, average shot {asl:.1f} s"]
    if cs:
        first = cs[:6]
        lines.append(f"- first cuts at {', '.join(f'{c:.1f}s' for c in first)}" + (" ..." if len(cs) > 6 else ""))
        lines.append(f"- hook window: {sum(1 for c in cs if c <= 3)} cut(s) in the first 3 s")
    if t:
        text, words = t
        span = (words[-1]["end"] - words[0]["start"]) if words else 0
        lines.append(f"- speech: {len(words)} words, {len(words) / span * 60:.0f} words/min" if span else "- speech: none detected")
        lines += ["", "## Transcript", "", text, ""]
    return "\n".join(lines) + "\n"


def cmd_add(skill, video, why, name=None, narration=None):
    video = pathlib.Path(video).expanduser().resolve()
    d = TASTE / skill
    d.mkdir(parents=True, exist_ok=True)
    name = name or re.sub(r"[^a-z0-9]+", "-", video.stem.lower()).strip("-")
    dst = d / f"{name}{video.suffix}"
    if video != dst:
        shutil.copy2(video, dst)
    (d / f"{name}.md").write_text(note_for(dst, why, name, pathlib.Path(narration).expanduser() if narration else None))
    print(f"saved {dst.name} + {name}.md in taste/{skill}/")


def cmd_from_ad(proj, why):
    proj = pathlib.Path(proj).resolve()
    import feedback as fb
    plan = json.loads((proj / "plan.json").read_text())
    cmd_add(fb.skill_of(plan), proj / "MASTER.mp4", why, name=proj.name)


def cmd_list(skill=None):
    for d in sorted(TASTE.glob(skill or "*")):
        if d.is_dir():
            print(f"{d.name}: {len(list(d.glob('*.md')))} reference(s) — " + ", ".join(p.stem for p in sorted(d.glob('*.md'))))


def cmd_brief(skill):
    d = TASTE / skill
    notes = sorted(d.glob("*.md")) if d.exists() else []
    if not notes:
        print(f"(no taste references for {skill} yet — add 3 to 5 with: taste.py add {skill} <video> \"why it works\")")
        return
    for n in notes:
        print(n.read_text().split("## Transcript")[0].strip(), "\n")


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    c, r = a[0], a[1:]
    opt = lambda k: r[r.index(k) + 1] if k in r else None
    if c == "add": cmd_add(r[0], r[1], r[2], opt("--name"), opt("--narration"))
    elif c == "from-ad": cmd_from_ad(r[0], r[1])
    elif c == "list": cmd_list(r[0] if r else None)
    elif c == "brief": cmd_brief(r[0])
    else: sys.exit(__doc__)


if __name__ == "__main__":
    main()
