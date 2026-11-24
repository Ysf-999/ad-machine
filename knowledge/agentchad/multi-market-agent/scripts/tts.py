# Library v2, 2026-11-09 (agentchad.io). Keys only from your own environment; nothing here is account-specific.
"""PROJ=<dir> LANG_CODE=<iso code> [PREFIX=line STABILITY=0.5 SIMILARITY=0.75 MODEL=eleven_v4] tts.py <voice_id> [only=3,7] [--yes]
Reads <PROJ>/lines.json ([{"s","e","cap","tts"}]) and writes <PROJ>/vo/<PREFIX>NN.mp3, one ElevenLabs call per line.
Paid: every call uses characters from your ElevenLabs plan. Without --yes the script only prints the character total.
Key: env ELEVENLABS_API_KEY, else ELEVENLABS_API_KEY=... in ~/.config/elevenlabs/.env. The key is never printed.
Exit codes: 0 OK or dry run, 1 an error (the message says which)."""
import os, re, json, sys, subprocess, time, urllib.request, urllib.error


def read_key(env_name, env_file):
    v = os.environ.get(env_name)
    if not v:
        p = os.path.expanduser(env_file)
        if os.path.exists(p):
            m = re.search(rf'^{env_name}=(.+)$', open(p).read(), re.M)
            v = m.group(1).strip().strip('"\'') if m else None
    if not v:
        sys.exit(f'{env_name} not set. Put {env_name}=... in {env_file} (your own account).')
    return v


if len(sys.argv) < 2 or 'PROJ' not in os.environ:
    sys.exit(__doc__)
if not os.environ.get('LANG_CODE'):
    sys.exit('Set LANG_CODE to the target language code (for example no, sv, da, fi, de, fr, nl, en).')
P = os.environ['PROJ']
voice = sys.argv[1]
args = sys.argv[2:]
yes = '--yes' in args
only_arg = next((a for a in args if a != '--yes'), None)
only = [int(x) for x in only_arg.split(',')] if only_arg else None
PREFIX = os.environ.get('PREFIX', 'line')
MODEL = os.environ.get('MODEL', 'eleven_v4')
LANG = os.environ['LANG_CODE']
VS = {'stability': float(os.environ.get('STABILITY', '0.5')),
      'similarity_boost': float(os.environ.get('SIMILARITY', '0.75'))}
lines = json.load(open(f'{P}/lines.json'))
todo = [i for i in range(len(lines)) if not only or i in only]
chars = sum(len(lines[i]['tts']) for i in todo)
print(f'{len(todo)} lines, about {chars} ElevenLabs characters (billed to your plan).')
if not yes:
    print('Not run (dry run, nothing spent). Show this total to the user; after a yes, run again with --yes.')
    sys.exit(0)
# the key is only needed for the paid run
key = read_key('ELEVENLABS_API_KEY', '~/.config/elevenlabs/.env')
os.makedirs(f'{P}/vo', exist_ok=True)


def tts(text, prev, nxt, out):
    body = {'text': text, 'model_id': MODEL, 'language_code': LANG, 'previous_text': prev, 'next_text': nxt,
            'voice_settings': VS}
    for attempt in range(8):
        req = urllib.request.Request(
            f'https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_192',
            data=json.dumps(body).encode(), headers={'xi-api-key': key, 'Content-Type': 'application/json'})
        try:
            open(out, 'wb').write(urllib.request.urlopen(req, timeout=180).read())
            return
        except urllib.error.HTTPError as e:
            err = e.read().decode()[:300]
            if e.code == 429 or e.code >= 500:
                time.sleep(6 * (attempt + 1))
                continue
            if 'language_code' in err and 'language_code' in body:
                body.pop('language_code')
                continue
            if 'previous_text' in err or 'next_text' in err:
                body.pop('previous_text', None)
                body.pop('next_text', None)
                continue
            if 'model' in err.lower():
                sys.exit(f'ElevenLabs HTTP {e.code}: {err}\nYour plan may not have {MODEL}: run again with MODEL=eleven_multilingual_v2.')
            sys.exit(f'ElevenLabs HTTP {e.code}: {err}')
    sys.exit('ElevenLabs: too many retries')


def dur(f):
    return float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f],
                                capture_output=True, text=True).stdout)


for i in todo:
    l = lines[i]
    out = f'{P}/vo/{PREFIX}{i:02d}.mp3'
    tts(l['tts'], lines[i - 1]['tts'] if i else '', lines[i + 1]['tts'] if i + 1 < len(lines) else '', out)
    print(f"{i:02d} slot {l['e'] - l['s']:5.2f}s  tts {dur(out):5.2f}s  {l['cap'][:50]}", flush=True)
