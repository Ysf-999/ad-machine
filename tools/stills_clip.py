"""Turn 2–4 still keyframes into a video clip with a slow camera push and hard cuts — no AI animation.

Usage: stills_clip.py <out.mp4> <frame1.png> <frame2.png> [...] [--each 1.6] [--zoom 1.06] [--sfx <file>]
Each still gets `each` seconds with a gentle Ken Burns push-in; cuts are hard. Output 1080x1920 30fps, silent
(or with the optional sfx file looped under it). Use for product shots the video models cannot animate safely.
"""
import subprocess, sys, pathlib, tempfile


def main():
    a = sys.argv[1:]
    def opt(n, d, cast=float):
        if n in a:
            i = a.index(n); v = cast(a[i + 1]); del a[i:i + 2]; return v
        return d
    each, zoom, sfx = opt("--each", 1.6), opt("--zoom", 1.06), opt("--sfx", None, str)
    out, frames = pathlib.Path(a[0]), [pathlib.Path(f) for f in a[1:]]
    fps, n = 30, None
    parts = []
    tmp = pathlib.Path(tempfile.mkdtemp())
    for i, f in enumerate(frames):
        n = int(each * fps)
        # zoompan: push from 1.0 to `zoom` over n frames, centred
        vf = (f"scale=2160:3840:flags=lanczos,zoompan=z='1+({zoom}-1)*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s=1080x1920:fps={fps},format=yuv420p")
        p = tmp / f"p{i}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(f), "-t", f"{each}", "-vf", vf, "-c:v", "libx264", "-crf", "16", "-r", str(fps), str(p)], check=True)
        parts.append(p)
    lst = tmp / "list.txt"; lst.write_text("".join(f"file '{p}'\n" for p in parts))
    vid = tmp / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(vid)], check=True)
    total = each * len(frames)
    if sfx:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(vid), "-stream_loop", "-1", "-i", sfx, "-t", f"{total}", "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", str(out)], check=True)
    else:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(vid), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{total}", "-c:v", "copy", "-c:a", "aac", "-shortest", str(out)], check=True)
    print(f"{out} {total:.1f}s from {len(frames)} stills")


if __name__ == "__main__":
    main()
