"""Burn bold word-timed captions (3 words per card) onto a video, timed by Whisper word timestamps.

Usage: burn_captions.py <in.mp4> <out.mp4> [--margin 520] [--size 78]
"""
import subprocess, sys, pathlib
import mlx_whisper

FONT = "Arial Black"


def t(x):
    h, r = divmod(x, 3600); m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def main():
    a = sys.argv[1:]
    def opt(n, d):
        if n in a:
            i = a.index(n); v = int(a[i + 1]); del a[i:i + 2]; return v
        return d
    margin, size = opt("--margin", 520), opt("--size", 78)
    src, dst = pathlib.Path(a[0]).resolve(), pathlib.Path(a[1]).resolve()
    r = mlx_whisper.transcribe(str(src), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en", word_timestamps=True)
    words = [(w["word"].strip(), w["start"], w["end"]) for s in r["segments"] for w in s.get("words", []) if w["word"].strip()]
    groups, g = [], []
    for w in words:
        g.append(w)
        if len(g) == 3 or w[0][-1] in ".,!?": groups.append(g); g = []
    if g: groups.append(g)
    ass = dst.with_suffix(".ass")
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Cap,{FONT},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,7,2,2,80,80,{margin},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    ev = []
    for i, grp in enumerate(groups):
        s = grp[0][1]
        e = min(groups[i + 1][0][1], grp[-1][2] + 0.6) if i + 1 < len(groups) else grp[-1][2] + 0.5
        ev.append(f"Dialogue: 0,{t(s)},{t(e)},Cap,,0,0,0,,{' '.join(w[0] for w in grp).upper().rstrip('.,')}")
    ass.write_text(head + "\n".join(ev) + "\n")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", f"subtitles={ass.name}", "-c:v", "libx264", "-crf", "17",
                    "-pix_fmt", "yuv420p", "-c:a", "copy", str(dst)], check=True, cwd=ass.parent)
    print(f"captioned {dst} ({len(groups)} cards)")


if __name__ == "__main__":
    main()
