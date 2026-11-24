"""Generate scene start frames sequentially with the course's consistency trick:
each frame uses the master refs + the last 4 generated frames as Nano Banana Pro image inputs.

Usage: gen_scenes.py <project-dir>
Reads plan.json: style_tail, lock, beats[{n, visual, refs:[master keys]}], masters{key: FRAMES/file}.
Writes FRAMES/scene_XX.png; resumable (skips existing frames, resumes saved task ids).
"""
import json, pathlib, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import kie

proj = pathlib.Path(sys.argv[1]).resolve()
plan = json.loads((proj / "plan.json").read_text())
frames, jobs = proj / "FRAMES", proj / "jobs.jsonl"
urls_file = frames / "_urls.json"
urls = json.loads(urls_file.read_text()) if urls_file.exists() else {}


def url_for(path):
    path = pathlib.Path(path)
    if str(path) not in urls:
        urls[str(path)] = kie.upload(str(path))
        urls_file.write_text(json.dumps(urls, indent=1))
    return urls[str(path)]


LIB = pathlib.Path(__file__).resolve().parent.parent / "library"
lib = json.loads((LIB / "index.json").read_text()) if (LIB / "index.json").exists() else {}

done = []
for b in plan["beats"]:
    key = f"scene_{b['n']:02d}"
    out = frames / f"{key}.png"
    if b.get("lib"):
        # approved library asset: its frame (or a clip's first frame) stands in, so review/QC and the chain still see it
        e = lib.get(b["lib"]) or sys.exit(f"beat {b['n']}: library id {b['lib']!r} not found")
        _sg = lambda t: next((g for k, g in (("clay", "claymation"), ("aardman", "claymation"), ("pixar", "pixar-3d"), ("flat 2d", "cartoon-2d"), ("cartoon-2d", "cartoon-2d"), ("diorama", "diorama"), ("ai-realistic", "ai-realistic")) if k in (t or "").lower()), None)
        if _sg(plan.get("style")) and _sg(e.get("style")) and _sg(plan.get("style")) != _sg(e.get("style")):
            sys.exit(f"beat {b['n']}: library clip {b['lib']!r} is {_sg(e.get('style'))} but this ad is {_sg(plan.get('style'))}. Animated b-roll is reused only inside its own style (owner rule).")
        if not out.exists():
            src = LIB / e["file"]
            if e["type"] == "frame":
                out.write_bytes(src.read_bytes())
            else:
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-frames:v", "1", str(out)], check=True)
            print(f"{key}: from library {b['lib']}", flush=True)
        if e["type"] == "clip":  # the clip is reused whole: no end frame needed
            done.append(out)
            continue
    if not out.exists():
        refs = [url_for(proj / plan["masters"][m]) for m in b.get("refs", [])]
        refs += [url_for(p) for p in done[-4:]]
        prompt = (f"{b['visual']} {plan['style_tail']} "
                  f"The characters and props must match the reference images exactly. {plan['lock']}")
        body = {"model": "nano-banana-pro", "input": {"prompt": prompt, "image_input": refs[:8],
                "aspect_ratio": "9:16", "resolution": "2K", "output_format": "png"}}
        kie.run(body, str(jobs), key, str(frames))
    done.append(out)
    if b.get("end_visual"):
        ekey = f"scene_{b['n']:02d}_end"; eout = frames / f"{ekey}.png"
        has_clip = any((proj / "CLIPS").glob(f"clip_{b['n']:02d}*.mp4"))  # beat already animated (e.g. a hook variant's body)
        if not eout.exists() and not has_clip:
            # end frame derives from the LATEST start-frame version (scene_XX_vN.png), not v1 (bug report, Oct 28)
            vers = sorted(frames.glob(f"{key}_v*.png"), key=lambda q: int(q.stem.rsplit("_v", 1)[1]) if q.stem.rsplit("_v", 1)[1].isdigit() else 0)
            start = vers[-1] if vers else out
            refs = [url_for(start)] + [url_for(proj / plan["masters"][m]) for m in b.get("refs", [])]
            prompt = (f"Same framing, camera, lighting, characters and props as image 1, but now: {b['end_visual']} "
                      f"{plan['style_tail']} {plan['lock']}")
            kie.run({"model": "nano-banana-pro", "input": {"prompt": prompt, "image_input": refs[:8],
                     "aspect_ratio": "9:16", "resolution": "2K", "output_format": "png"}}, str(jobs), ekey, str(frames))
print("ALL SCENES DONE", flush=True)
