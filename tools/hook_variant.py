"""Create a hook-variant project from a finished ad: the body (beats from --body-from on) keeps its exact audio, frames,
clips and captions; the hook beats are removed so new ones can be written and generated.

Usage: hook_variant.py <base-project-dir> <variant-name> --body-from <beat n>
Then: add the new hook beats at the top of plan.json (new n numbers >= 101, voice_id = the base voice, visual/motion/...),
set plan.script and plan.hook_text, run `ad.py <variant> vo` (renders ONLY the hook take and joins it with the body take),
`frames`, `clips`, `stitch`. The body take lives in VO/body_take.mp3 + .json and is referenced by vo_take_file.
"""
import json, pathlib, shutil, subprocess, sys
base = pathlib.Path(sys.argv[1]).resolve(); name = sys.argv[2]; body_n = int(sys.argv[sys.argv.index("--body-from") + 1])
var = base.parent / name
if var.exists(): sys.exit(f"{var} exists")
plan = json.loads((base / "plan.json").read_text())
beats = plan["beats"]; idx = next(i for i, b in enumerate(beats) if b["n"] == body_n)
hook, body = beats[:idx], beats[idx:]
for d in ("FRAMES", "CLIPS", "VO", "EDIT_KIT", "QC"): (var / d).mkdir(parents=True)
for f in (base / "FRAMES").iterdir():  # masters, props and the body's scene frames; hook scene frames are left behind
    if f.is_file() and not any(f.name.startswith(f"scene_{b['n']:02d}") for b in hook): shutil.copy2(f, var / "FRAMES" / f.name)
for f in (base / "CLIPS").iterdir():
    if f.is_file() and f.suffix == ".mp4" and not any(f.name.startswith(f"clip_{b['n']:02d}") for b in hook): shutil.copy2(f, var / "CLIPS" / f.name)
if plan.get("music"): shutil.copy2(base / plan["music"], var / plan["music"])
# body take: cut from the base vo.mp3 using its alignment
al = json.loads((base / "VO" / "alignment.json").read_text())
chars, st, en = al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]
text = "".join(chars); body_text = " ".join(b["vo"] for b in body); i0 = text.find(body_text)
if i0 < 0: sys.exit("body text not found in the base alignment")
prev_end = en[i0 - 2] if i0 >= 2 else 0.0  # end of the last hook word (i0-1 is the space)
cut = max(prev_end + 0.02, st[i0] - 0.15)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{cut:.3f}", "-i", str(base / "VO" / "vo.mp3"), "-c:a", "libmp3lame", "-b:a", "128k", str(var / "VO" / "body_take.mp3")], check=True)
sub = {"characters": chars[i0:], "character_start_times_seconds": [round(max(0.0, t - cut), 3) for t in st[i0:]],
       "character_end_times_seconds": [round(max(0.0, t - cut), 3) for t in en[i0:]]}
voice = body[0].get("voice_id") or plan.get("voice_id")
(var / "VO" / "body_take.json").write_text(json.dumps({"voice": voice, "text": body_text, "alignment": sub, "from": str(base), "cut_at": cut}))
for b in body:
    b.setdefault("voice_id", voice)
body[0]["vo_take_file"] = "VO/body_take"; body[0]["vo_break"] = True
plan["beats"] = body; plan["ad"] = name; plan["variant_of"] = base.name; plan["hook_beats_removed"] = [b["n"] for b in hook]
plan.pop("locked", None); plan["script"] = body_text; plan.pop("hook_text", None)
plan["vo_max_gap"] = None  # the body take is already cut; re-cutting pauses would change the approved body (Oct 28)
(var / "plan.json").write_text(json.dumps(plan, indent=2))
(var / "SCRIPT.md").write_text(f"# {name}\n\nHook variant of {base.name}. Body = beats {body_n}+ unchanged. Removed hook beats: {[b['n'] for b in hook]}\n\nOld hook lines:\n" + "\n".join(f"- {b['n']}: {b['vo']}" for b in hook) + "\n")
print(f"{var}: body take {cut:.2f}s→end of base VO ({len(body)} beats), hook beats removed: {[b['n'] for b in hook]}")
