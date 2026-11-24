"""ElevenLabs Voice Design: describe a voice, get 3 previews, keep the one you like (Camilo: always design the
voice instead of using stock voices; describe accent, age, energy, persona, pace and the recording setup).

Usage:
  voice_design.py design <dir> "<description>" [--text "<100-1000 chars read in the preview>"]
      -> <dir>/voice_preview_1..3.mp3 + voice_previews.json (opens the folder so you can listen)
  voice_design.py pick <dir> <1|2|3> "<voice name>"
      -> creates the voice in the ElevenLabs account and prints its voice_id (also saved in voice_previews.json)

Description recipe: "<age> <gender> with a <accent> accent, <energy/mood>, sounds like <persona>, speaks <pace>,
recorded <setup: on a high-quality studio mic / on a phone in a car / ...>". No celebrity names.
"""
import base64, json, pathlib, subprocess, sys
import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://api.elevenlabs.io/v1/text-to-voice"


def key():
    import os
    k = os.environ.get("ELEVENLABS_API_KEY") or next((l.split("=", 1)[1].strip() for l in (ROOT / ".env").read_text().splitlines()
                                                      if l.startswith("ELEVENLABS_API_KEY=")), None)
    return k or sys.exit("ELEVENLABS_API_KEY missing from the repo .env")


def design(d, description, text=None):
    d = pathlib.Path(d); d.mkdir(parents=True, exist_ok=True)
    body = {"voice_description": description, "model_id": "eleven_multilingual_ttv_v2"}
    if text and 100 <= len(text) <= 1000:
        body["text"] = text
    else:
        body["auto_generate_text"] = True
    r = httpx.post(f"{API}/design", headers={"xi-api-key": key()}, json=body, timeout=180)
    r.raise_for_status(); j = r.json()
    ids = []
    for i, p in enumerate(j["previews"][:3], 1):
        (d / f"voice_preview_{i}.mp3").write_bytes(base64.b64decode(p["audio_base_64"]))
        ids.append(p["generated_voice_id"])
    (d / "voice_previews.json").write_text(json.dumps({"description": description, "text": j.get("text"),
                                                       "generated_voice_ids": ids}, indent=1))
    print(f"{len(ids)} previews in {d} (voice_preview_1..{len(ids)}.mp3). Listen, then: voice_design.py pick {d} <n> \"<name>\"")
    subprocess.run(["open", str(d)], check=False)
    return ids


def pick(d, n, name):
    d = pathlib.Path(d); meta = json.loads((d / "voice_previews.json").read_text())
    gid = meta["generated_voice_ids"][int(n) - 1]
    r = httpx.post(API, headers={"xi-api-key": key()}, timeout=120, json={
        "voice_name": name, "voice_description": meta["description"], "generated_voice_id": gid,
        "played_not_selected_voice_ids": [g for g in meta["generated_voice_ids"] if g != gid]})
    r.raise_for_status(); vid = r.json()["voice_id"]
    meta["picked"] = int(n); meta["voice_id"] = vid; meta["voice_name"] = name
    (d / "voice_previews.json").write_text(json.dumps(meta, indent=1))
    print(f"voice_id {vid}")
    return vid


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == "design":
        design(a[1], a[2], a[a.index("--text") + 1] if "--text" in a else None)
    elif len(a) == 4 and a[0] == "pick":
        pick(a[1], a[2], a[3])
    else:
        sys.exit(__doc__)
