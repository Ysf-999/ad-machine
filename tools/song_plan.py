"""Turn a timed song into an ad.py project, so frames -> clips -> qc -> review -> stitch run as for any animated ad.

Usage: song_plan.py <project> --song song/lead.mp3 --segments song/lead.segments.json --grid grid.json
Run it after `music.py song`, `music.py times` and the storyboard's beat_grid.py (paths are relative to the project).
Writes VO/vo.mp3 (the song, trimmed to start on the first sung word), VO/alignment.json (from the word timings) and one
plan beat per grid shot with its song window and clip duration. A beat that already has visual/camera/refs keeps them,
so re-timing never loses approved work. Sets plan.song (ad.py vo refuses to run) and plan.sfx_db (clip sound far under
the song; the song is the master audio). Re-run with a new --pace grid at any time.
Suno's word timings ran late on the 2026-10-30 pilot (caption check FAIL, median +0.18 s), so they only seed the map:
the last step re-times everything from Whisper on the real audio, as every other ad does (R001).
"""
import json, pathlib, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from ad import set_durations
import realign_vo

LEAD, TAIL = 0.2, 1.2  # seconds kept before the first sung word and after the last


def alignment(words, cut):
    """ElevenLabs-shaped character alignment, which is what assemble_anim's captions read."""
    chars, st, en = [], [], []
    for i, w in enumerate(words):
        s, e = w["start"] - cut, w["end"] - cut
        step = (e - s) / max(len(w["text"]), 1)
        for k, c in enumerate(w["text"]):
            chars.append(c); st.append(round(s + k * step, 3)); en.append(round(s + (k + 1) * step, 3))
        if i + 1 < len(words):
            chars.append(" "); st.append(round(e, 3)); en.append(round(e, 3))
    return {"characters": chars, "character_start_times_seconds": st, "character_end_times_seconds": en}


def main():
    a = sys.argv[1:]
    def opt(n):
        return a[a.index(n) + 1]
    proj = pathlib.Path(a[0]).resolve(); (proj / "VO").mkdir(exist_ok=True)
    words = json.loads((proj / opt("--segments")).read_text()); grid = json.loads((proj / opt("--grid")).read_text())
    cut = max(0.0, words[0]["start"] - LEAD); end = words[-1]["end"] + TAIL
    song_len = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(proj / opt("--song"))],
                                    capture_output=True, text=True).stdout); end = min(end, song_len)
    length = end - cut
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{cut:.3f}", "-to", f"{end:.3f}", "-i", str(proj / opt("--song")),
                    "-af", f"afade=t=out:st={max(0, length - 0.8):.3f}:d=0.8", "-c:a", "libmp3lame", "-q:a", "2", str(proj / "VO" / "vo.mp3")], check=True)
    (proj / "VO" / "alignment.json").write_text(json.dumps(alignment(words, cut)))

    f = proj / "plan.json"; plan = json.loads(f.read_text()) if f.exists() else {"ad": proj.name}
    old = {b["n"]: b for b in plan.get("beats", [])}; beats = []
    shots = grid["shots"]; bounds = [s["start"] for s in shots[1:]] + [float("inf")]
    left = list(words)
    for s, stop in zip(shots, bounds):
        b = old.get(s["shot"], {"n": s["shot"], "visual": "", "refs": []})
        sung = []  # the words really sung in this window: a split line must not repeat its text (realign finds beats by text)
        while left and left[0]["start"] < stop - 0.011:  # the grid rounds line starts to 0.01 s
            sung.append(left.pop(0)["text"])
        b.update({"vo": " ".join(sung), "lyric": s["lyric"], "vo_start": round(max(0, s["start"] - cut), 3), "vo_end": round(min(length, s["end"] - cut), 3)})
        if s.get("section"): b["section"] = s["section"]
        beats.append(b)
    plan.update({"beats": beats, "song": opt("--song"), "sfx_db": plan.get("sfx_db", -30), "skill": plan.get("skill", "song-ad-machine")})
    f.write_text(json.dumps(plan, indent=2, ensure_ascii=False))
    realign_vo.realign(proj)
    plan = json.loads(f.read_text()); set_durations(plan, length)
    f.write_text(json.dumps(plan, indent=2, ensure_ascii=False))
    print(f"song {length:.1f}s (cut {cut:.2f}s of intro), {len(plan['beats'])} beats, clips {sum(b['duration'] for b in plan['beats'])}s total, plan + VO written")


if __name__ == "__main__":
    main()
