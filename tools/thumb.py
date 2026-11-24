"""Make small thumbnails so an agent can Read a frame without blowing its context.
Usage: thumb.py <image|mp4> [...] [--size 540] [--frames 5]   -> writes <name>_thumb.jpg (image) or <name>_qcstrip.jpg (video, N frames in a row)
"""
import pathlib, subprocess, sys
from PIL import Image
a = sys.argv[1:]
size = int(a[a.index("--size") + 1]) if "--size" in a else 540
nfr = int(a[a.index("--frames") + 1]) if "--frames" in a else 5
for x in [p for p in a if not p.startswith("--") and p not in (str(size), str(nfr))]:
    p = pathlib.Path(x)
    if p.suffix.lower() in (".mp4", ".mov"):
        out = p.with_name(p.stem + "_qcstrip.jpg")
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout)
        frs = []
        for i in range(nfr):
            f = p.with_name(f"{p.stem}_t{i}.jpg")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur*(i+0.5)/nfr:.2f}", "-i", str(p), "-frames:v", "1", "-vf", "scale=320:-2", str(f)], check=True)
            frs.append(Image.open(f))
        w, h = frs[0].size; sheet = Image.new("RGB", (w * nfr, h))
        for i, fr in enumerate(frs): sheet.paste(fr, (i * w, 0)); p.with_name(f"{p.stem}_t{i}.jpg").unlink()
        sheet.save(out, quality=85)
    else:
        out = p.with_name(p.stem + "_thumb.jpg")
        im = Image.open(p).convert("RGB"); im.thumbnail((size, size)); im.save(out, quality=85)
    print(out)
