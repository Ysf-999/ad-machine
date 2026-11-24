"""Small SFX library for the editors (rawedit.py plan.sfx, any assemble step): one-time generation with ElevenLabs
sound effects, saved to library/sfx/<kind>.mp3 and trimmed to the sound itself (no lead silence).

Course rule C011 (A14, B06, B07, B09): a sound effect supports a visible on-screen event (the harness click, a graph pop,
a riser before the key word, a whoosh where a cut feels like something is missing). Benefits get a ding, negatives a
buzzer, list items escalate. Organic / UGC ads use one or two at most; heavy SFX is for Dr. Squatch-style punchy edits.

Usage: .venv/bin/python -I tools/sfx.py build [kind ...]     generate missing kinds (credits printed before/after)
       .venv/bin/python -I tools/sfx.py list
"""
import json, pathlib, subprocess, sys, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "library" / "sfx"
KINDS = {   # kind: (prompt, seconds)
    "pop": ("a single soft hollow pop, clean, short, like a bubble pop for a video graphic appearing", 0.6),
    "whoosh": ("a quick soft whoosh transition for a video cut, airy, short, no music", 0.8),
    "swipe": ("a fast subtle swipe swoosh for a phone video transition, very short", 0.5),
    "riser": ("a short tension riser building up into a moment, cinematic, ends abruptly", 2.0),
    "ding": ("a single bright positive ding notification, clean, short", 0.7),
    "tick": ("a crisp check-mark tick sound for a benefit appearing on screen, short", 0.4),
    "buzzer": ("a short wrong-answer buzzer, game show, not too loud", 0.8),
    "click": ("a firm plastic buckle click, like a seatbelt or harness clip snapping shut", 0.5),
    "cash": ("a cash register cha-ching, short, for a price or discount appearing", 1.0),
    "impact": ("a soft deep cinematic impact boom for a big text reveal, short", 1.2),
    "camera": ("a phone camera shutter click", 0.4),
    "record-scratch": ("a short vinyl record scratch, comedic stop", 0.8),
    "clock-tick": ("a stopwatch ticking, crisp fast clock ticks, clean, no music, no voice", 1.6),
    "scrub": ("close-up ASMR sound of scrubbing a fabric surface back and forth, rhythmic, crisp texture, no voice, no music", 5.0),
    "scrub-short": ("close-up ASMR of quick short brushing strokes on fabric, crisp, no voice, no music", 2.5),
    "peel": ("close-up ASMR of something soft being peeled off fabric, soft fluffy tearing, no voice", 1.5),
}


def key():
    for l in (ROOT / ".env").read_text().splitlines():
        if l.startswith("ELEVENLABS_API_KEY="): return l.split("=", 1)[1].strip()
    sys.exit("ELEVENLABS_API_KEY missing in .env")


def credits(k):
    r = urllib.request.urlopen(urllib.request.Request("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": k}))
    j = json.load(r); return j["character_count"], j["character_limit"]


def gen(k, kind):
    prompt, sec = KINDS[kind]
    body = json.dumps({"text": prompt, "duration_seconds": max(sec, 0.5), "prompt_influence": 0.6}).encode()
    req = urllib.request.Request("https://api.elevenlabs.io/v1/sound-generation", data=body, method="POST",
                                 headers={"xi-api-key": k, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    raw = OUT / f"_{kind}.mp3"; raw.write_bytes(urllib.request.urlopen(req, timeout=120).read())
    # trim lead/tail silence so `at` in plan.sfx is the moment the sound hits
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-af",
                    "silenceremove=start_periods=1:start_threshold=-55dB,areverse,silenceremove=start_periods=1:start_threshold=-65dB,areverse",
                    "-ar", "48000", "-ac", "2", "-b:a", "192k", OUT / f"{kind}.mp3"], check=True)
    raw.unlink(); normalize(OUT / f"{kind}.mp3")


def normalize(f, peak=-3.0):
    """Peak-normalise to -3 dBFS so plan.sfx "db" means the same thing for every sound (generations vary by 40 dB)."""
    import re
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", f, "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"max_volume:\s*(-?[\d.]+)", r.stderr)
    if not m: return
    g = peak - float(m.group(1)); tmp = f.with_name("_n_" + f.name)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f, "-af", f"volume={g:.2f}dB", "-ar", "48000", "-ac", "2", "-b:a", "192k", tmp], check=True)
    tmp.replace(f)


def main():
    a = sys.argv[1:]
    OUT.mkdir(parents=True, exist_ok=True)
    if not a or a[0] == "list":
        for k_, (p, s) in KINDS.items(): print(f"{'x' if (OUT / f'{k_}.mp3').exists() else '-'} {k_:15s} {p}")
        return
    if a[0] == "normalize":
        for f in sorted(OUT.glob("*.mp3")): normalize(f); print("normalised", f.name)
        return
    if a[0] == "build":
        k = key(); want = a[1:] or [x for x in KINDS if not (OUT / f"{x}.mp3").exists()]
        c0 = credits(k)[0]
        for kind in want:
            gen(k, kind); print("made", kind)
        c1, lim = credits(k)
        print(f"ElevenLabs credits used: {c1 - c0} ({c1}/{lim} this period)")


if __name__ == "__main__":
    main()
