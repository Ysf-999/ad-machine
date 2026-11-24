"""Clone a voice from a clean VO sample (ElevenLabs instant voice clone) and speak new lines in it.

Usage: .venv/bin/python -I tools/vo_clone.py clone <name> <sample.wav> [<sample2.wav> ...]   -> prints voice_id (saved in library/voices.json)
       .venv/bin/python -I tools/vo_clone.py say <name|voice_id> "<text>" <out.mp3> [--stability 0.45] [--similarity 0.9] [--style 0.2]
Keys come from .env (ELEVENLABS_API_KEY); never printed.
"""
import json, pathlib, sys
import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
REG = ROOT / "library" / "voices.json"
API = "https://api.elevenlabs.io/v1"


def key():
    for l in (ROOT / ".env").read_text().splitlines():
        if l.startswith("ELEVENLABS_API_KEY="): return l.split("=", 1)[1].strip()
    sys.exit("ELEVENLABS_API_KEY missing in .env")


def reg():
    return json.loads(REG.read_text()) if REG.exists() else {}


def clone(name, samples):
    files = [("files", (pathlib.Path(s).name, open(s, "rb"), "audio/wav")) for s in samples]
    r = httpx.post(f"{API}/voices/add", headers={"xi-api-key": key()}, data={"name": name, "remove_background_noise": "true",
                   "description": "cloned from an owner ad VO for hook variants"}, files=files, timeout=300)
    if r.status_code >= 300: sys.exit(f"clone failed {r.status_code}: {r.text[:300]}")
    vid = r.json()["voice_id"]; d = reg(); d[name] = vid; REG.write_text(json.dumps(d, indent=1)); print(vid); return vid


def say(voice, text, out, stability=0.45, similarity=0.9, style=0.2):
    vid = reg().get(voice, voice)
    body = {"text": text, "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": stability, "similarity_boost": similarity, "style": style, "use_speaker_boost": True}}
    r = httpx.post(f"{API}/text-to-speech/{vid}", params={"output_format": "mp3_44100_128"}, headers={"xi-api-key": key()}, json=body, timeout=180)
    if r.status_code >= 300: sys.exit(f"tts failed {r.status_code}: {r.text[:300]}")
    pathlib.Path(out).write_bytes(r.content); print(f"wrote {out}")


def main():
    a = sys.argv[1:]
    opt = lambda n, d: float(a[a.index(n) + 1]) if n in a else d
    if a and a[0] == "clone": clone(a[1], a[2:])
    elif a and a[0] == "say": say(a[1], a[2], a[3], opt("--stability", 0.45), opt("--similarity", 0.9), opt("--style", 0.2))
    else: sys.exit(__doc__)


if __name__ == "__main__":
    main()
