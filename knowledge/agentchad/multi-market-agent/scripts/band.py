# Library v2, 2026-11-09 (agentchad.io). Free and local: ffmpeg + numpy. Nothing here calls a paid service.
# 2026-11-10: `cover` = the free no-Vmake fallback (blur or a solid bar over the old caption band).
# 2026-11-10: `find` uses AGENTCHAD_PY from ~/.agentchad/settings.env (re-starts itself with it) instead of exit 3.
"""band.py: the Band Rip helper. Find the caption band, cut it out, paste the cleaned band back.

  band.py find  <video> [--step 0.5]                    suggest the caption band (y, h) from bright text rows
  band.py sheet <video> <out.png> [--every 1.0]         frame grid with a pixel ruler, to check the band by eye
  band.py crop  <video> <out.mp4> --y Y --h H           cut a full-width strip (what you upload to the remover)
  band.py paste <original> <clean> <out.mp4> --y Y --h H [--feather 6] [--t0 0 --t1 999]
                                                         lay the cleaned strip (or a full cleaned frame) back
                                                         over the original, only inside the band
  band.py probe <a.mp4> [<b.mp4>]                       size, fps, duration and real frame count (compare!)
  band.py cover <video> <out.mp4> --y Y --h H [--mode blur|solid] [--dim 0.1] [--feather 10] [--t0 0 --t1 999]
                                                         FREE fallback without Vmake: hides the old captions under
                                                         a strong blur (default) or a solid bar in the band's own
                                                         average colour. The new captions go on top of it. It shows:
                                                         viewers see a soft blurred strip (or a bar) where the old
                                                         text was. Vmake removal is invisible; this is not.

Why: a caption remover wipes ALL text it sees (logos, labels, phone screens) and smears faces under text.
Sending only the strip where the captions are, then pasting it back, keeps everything else original.
Env VCODEC (default libx264; on a Mac hevc_videotoolbox is faster), CRF (default 18).
"""
import argparse
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py import need  # noqa: E402  (finds AGENTCHAD_PY: environment, then ~/.agentchad/settings.env)

VCODEC = os.environ.get("VCODEC", "libx264")
CRF = os.environ.get("CRF", "18")


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("ffmpeg failed:\n" + r.stderr[-800:])
    return r.stdout


def info(path, count=False):
    entries = "stream=width,height,r_frame_rate" + (",nb_read_packets" if count else "") + ":format=duration"
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", entries, "-of", "json"]
    if count:
        cmd.insert(1, "-count_packets")
    j = json.loads(run(cmd + [path]))
    s = j["streams"][0]
    n, d = s["r_frame_rate"].split("/")
    return {"w": s["width"], "h": s["height"], "fps": float(n) / float(d),
            "dur": float(j["format"]["duration"]), "frames": int(s.get("nb_read_packets", 0) or 0)}


def even(v):
    return int(v) // 2 * 2


def enc_args():
    a = ["-c:v", VCODEC]
    if VCODEC == "libx264":
        a += ["-crf", CRF, "-preset", "medium"]
    else:
        a += ["-b:v", os.environ.get("BITRATE", "16M")]
    if "hevc" in VCODEC:
        a += ["-tag:v", "hvc1"]
    return a + ["-pix_fmt", "yuv420p"]


def cmd_find(a):
    need(["numpy"])   # another Python: switches to AGENTCHAD_PY by itself, else exit 3 with the install line
    import numpy as np
    v = info(a.video)
    W = 270
    H = even(v["h"] * W / v["w"])
    acc = np.zeros(H)
    n = 0
    t = 0.2
    while t < v["dur"] - 0.1:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", a.video, "-frames:v", "1",
                              "-vf", f"scale={W}:{H},format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
        if len(raw) == W * H:
            f = np.frombuffer(raw, np.uint8).reshape(H, W).astype(int)
            bright = f > 215
            edges = np.abs(np.diff(f, axis=1)) > 60
            acc += (bright[:, 1:] & edges).sum(1)
            n += 1
        t += a.step
    if not n:
        sys.exit("Could not read frames.")
    prof = acc / n
    thr = max(prof.max() * 0.25, 1.0)
    rows = np.where(prof > thr)[0]
    print(f"frames sampled {n}, size {v['w']}x{v['h']}, text-like rows (fraction of height):")
    for y in range(H):
        if prof[y] > thr:
            print(f"{y / H:.3f} {prof[y]:.1f}", end=" | ")
    print()
    if not len(rows):
        print("No bright text rows found. Captions may be dark or on a box: check with `band.py sheet`.")
        return
    # largest contiguous group (allow 3-row gaps)
    groups, start, last = [], rows[0], rows[0]
    for r in rows[1:]:
        if r - last > 3:
            groups.append((start, last))
            start = r
        last = r
    groups.append((start, last))
    g = max(groups, key=lambda p: prof[p[0]:p[1] + 1].sum())
    pad = 0.02
    y0 = max(0.0, g[0] / H - pad)
    y1 = min(1.0, (g[1] + 1) / H + pad)
    Y, Hh = even(y0 * v["h"]), even((y1 - y0) * v["h"])
    print(f"suggested band: --y {Y} --h {Hh}   (rows {y0:.3f}-{y1:.3f} of the height)")
    print("Check it on the frame sheet before uploading anything: band.py sheet <video> sheet.png")


def cmd_sheet(a):
    v = info(a.video)
    cols = 6
    k = max(1, int(round(v["dur"] / a.every)))
    rows = (k + cols - 1) // cols
    # ruler: a thin line every 10 % of the height so a band can be read off the sheet
    lines = ",".join(f"drawbox=x=0:y=ih*{i/10}:w=iw:h=2:color=yellow@0.8:t=fill" for i in range(1, 10))
    run(["ffmpeg", "-v", "error", "-y", "-i", a.video, "-vf",
         f"fps=1/{a.every},{lines},scale=270:-2,tile={cols}x{rows}:padding=4:color=white", "-frames:v", "1", a.out])
    print(f"wrote {a.out}  (yellow lines every 10 % of the height, one frame every {a.every} s)")


def cmd_crop(a):
    v = info(a.video)
    y, h = even(a.y), even(a.h)
    if y + h > v["h"]:
        sys.exit(f"band ends at {y + h}, the video is {v['h']} high")
    run(["ffmpeg", "-v", "error", "-y", "-i", a.video, "-vf", f"crop={v['w']}:{h}:0:{y}", *enc_args(),
         "-c:a", "copy", a.out])
    print(f"wrote {a.out}  strip {v['w']}x{h} from y {y}. Upload this strip, not the whole ad.")


def cmd_paste(a):
    o, c = info(a.original), info(a.clean)
    y, h, F = even(a.y), even(a.h), a.feather
    if c["w"] != o["w"]:
        sys.exit(f"width differs: original {o['w']}, clean {c['w']}. Scale the clean file to {o['w']} first.")
    if c["h"] == o["h"]:
        src = f"[1:v]crop={o['w']}:{h}:0:{y}"          # a full cleaned frame: take only the band
    elif c["h"] == h:
        src = "[1:v]null"                               # the cleaned strip itself
    else:
        sys.exit(f"clean height {c['h']} is neither the full frame ({o['h']}) nor the band (--h {h}).")
    alpha = f"255*min(1,min(Y,H-1-Y)/{F})" if F > 0 else "255"
    fl = (f"{src},format=yuva420p,geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)':a='{alpha}'[b];"
          f"[0:v][b]overlay=0:{y}:eof_action=pass:enable='between(t,{a.t0},{a.t1})',format=yuv420p[v]")
    run(["ffmpeg", "-v", "error", "-y", "-i", a.original, "-i", a.clean, "-filter_complex", fl,
         "-map", "[v]", "-map", "0:a?", "-c:a", "copy", *enc_args(), "-t", f"{o['dur']:.3f}", a.out])
    n = info(a.out, count=True)["frames"]
    no = info(a.original, count=True)["frames"]
    print(f"wrote {a.out}  frames {n} (original {no})" + ("" if n == no else "  MISMATCH: run retime.py first"))


def avg_colour(video, y, h, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-vf",
                          f"crop=iw:{h}:0:{y},scale=1:1,format=rgb24", "-f", "rawvideo", "-"], capture_output=True).stdout
    return "0x%02x%02x%02x" % tuple(raw[:3]) if len(raw) >= 3 else "0x202020"


def cmd_cover(a):
    v = info(a.video)
    y, h, F = even(a.y), even(a.h), a.feather
    if y + h > v["h"]:
        sys.exit(f"band ends at {y + h}, the video is {v['h']} high")
    alpha = f"255*min(1,min(Y,H-1-Y)/{F})" if F > 0 else "255"
    if a.mode == "solid":
        col = avg_colour(a.video, y, h, v["dur"] / 2)
        strip = f"color=c={col}:s={v['w']}x{h}:r={v['fps']:.4f},format=yuva420p"
        fl = (f"{strip},geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)':a='{alpha}'[b];"
              f"[0:v][b]overlay=0:{y}:shortest=1:enable='between(t,{a.t0},{a.t1})',format=yuv420p[v]")
        how = f"solid bar {col}"
    else:
        dim = f",eq=brightness=-{a.dim}" if a.dim > 0 else ""
        fl = (f"[0:v]split[o][c];[c]crop={v['w']}:{h}:0:{y},gblur=sigma={max(12, h // 4)}:steps=3{dim},format=yuva420p,"
              f"geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)':a='{alpha}'[b];"
              f"[o][b]overlay=0:{y}:enable='between(t,{a.t0},{a.t1})',format=yuv420p[v]")
        how = "blur"
    run(["ffmpeg", "-v", "error", "-y", "-i", a.video, "-filter_complex", fl, "-map", "[v]", "-map", "0:a?",
         "-c:a", "copy", *enc_args(), "-t", f"{v['dur']:.3f}", a.out])
    print(f"wrote {a.out}  ({how} over y {y}-{y + h}). Put the new captions on this band (CAP_Y = {(y + h / 2) / v['h']:.3f}),"
          " then look at a frame: no old letter may be readable.")


def cmd_probe(a):
    res = [(p, info(p, count=True)) for p in a.files]
    for p, i in res:
        print(f"{p}: {i['w']}x{i['h']} {i['fps']:.3f} fps {i['dur']:.3f} s frames {i['frames']}")
    if len(res) == 2 and res[0][1]["frames"] != res[1][1]["frames"]:
        d = res[0][1]["frames"] - res[1][1]["frames"]
        print(f"frame counts differ by {d}: the remover dropped frames. Run retime.py before pasting.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    f = sp.add_parser("find"); f.add_argument("video"); f.add_argument("--step", type=float, default=0.5)
    s = sp.add_parser("sheet"); s.add_argument("video"); s.add_argument("out"); s.add_argument("--every", type=float, default=1.0)
    c = sp.add_parser("crop"); c.add_argument("video"); c.add_argument("out")
    c.add_argument("--y", type=int, required=True); c.add_argument("--h", type=int, required=True)
    q = sp.add_parser("paste"); q.add_argument("original"); q.add_argument("clean"); q.add_argument("out")
    q.add_argument("--y", type=int, required=True); q.add_argument("--h", type=int, required=True)
    q.add_argument("--feather", type=int, default=6)
    q.add_argument("--t0", type=float, default=0); q.add_argument("--t1", type=float, default=99999)
    r = sp.add_parser("probe"); r.add_argument("files", nargs="+")
    cv = sp.add_parser("cover"); cv.add_argument("video"); cv.add_argument("out")
    cv.add_argument("--y", type=int, required=True); cv.add_argument("--h", type=int, required=True)
    cv.add_argument("--mode", choices=["blur", "solid"], default="blur"); cv.add_argument("--dim", type=float, default=0.1)
    cv.add_argument("--feather", type=int, default=10)
    cv.add_argument("--t0", type=float, default=0); cv.add_argument("--t1", type=float, default=99999)
    a = p.parse_args()
    {"find": cmd_find, "sheet": cmd_sheet, "crop": cmd_crop, "paste": cmd_paste, "probe": cmd_probe,
     "cover": cmd_cover}[a.cmd](a)


if __name__ == "__main__":
    main()
