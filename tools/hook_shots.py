"""AI hook shots for real-footage (rawedit) ads: 9:16 still (nano-banana-pro) -> silent Kling 3.0 clip, per shot.

Usage: .venv/bin/python -I tools/hook_shots.py <shots.json> frames|clips [--only key,key]
shots.json: {"dir": "projects/<ad>/hooks", "shots": [{"key": "h2a", "frame": "<still prompt>", "motion": "<clip prompt>",
             "refs": ["projects/.../ref.jpg"], "duration": 5}]}
Frames first (cheap; check them), then clips. Credits are read before/after and printed (measured, not estimated).
Realism lines from the ugc-talking-head skill are appended automatically.
"""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import kie

ROOT = pathlib.Path(__file__).resolve().parent.parent
REAL = (" Candid photo taken with an iPhone 15, uneven camera angle, TikTok style, natural window light, realistic textures and "
        "skin, slightly imperfect framing, no text, no logos, no watermark, vertical 9:16.")
MOVE = (" Handheld shaky phone camera movement, realistic physics, the motion starts at the very first frame. No spoken words, "
        "no music, no text on screen. One continuous shot, no cuts.")


def main():
    a = sys.argv[1:]
    spec = json.loads(pathlib.Path(a[0]).read_text()); stage = a[1]
    only = set(a[a.index("--only") + 1].split(",")) if "--only" in a else None
    d = ROOT / spec["dir"]; (d / "frames").mkdir(parents=True, exist_ok=True); (d / "clips").mkdir(exist_ok=True)
    jobs = str(d / "jobs.jsonl"); c0 = kie.credit()
    for s in spec["shots"]:
        if only and s["key"] not in only: continue
        if stage == "frames":
            refs = [kie.upload(str(ROOT / r)) for r in s.get("refs", [])]
            body = {"model": "nano-banana-pro", "input": {"prompt": s["frame"] + REAL, "image_input": refs, "aspect_ratio": "9:16",
                                                          "resolution": "2K", "output_format": "png"}}
            kie.run(body, jobs, f"frame_{s['key']}", str(d / "frames"))
        elif stage == "clips":
            fr = d / "frames" / f"frame_{s['key']}.png"
            if not fr.exists(): print(f"no frame for {s['key']}"); continue
            body = {"model": "kling-3.0/video", "input": {"prompt": s["motion"] + MOVE, "image_urls": [kie.upload(str(fr))],
                    "sound": False, "duration": str(s.get("duration", 5)), "mode": "std", "multi_shots": False}}
            kie.run(body, jobs, f"clip_{s['key']}", str(d / "clips"))
    c1 = kie.credit(); print(f"kie credits: {c0} -> {c1} (used {round(c0 - c1, 1)})")


if __name__ == "__main__":
    main()
