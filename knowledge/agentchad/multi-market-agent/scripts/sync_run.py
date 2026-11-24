# Library v2, 2026-11-09 (agentchad.io). Keys only from your own environment; nothing here is account-specific.
"""sync_run.py <video_no_audio.mp4> <voice_only.wav> <out.mp4> [model=sync-3] [resume_job_id] [--yes]
Submits a lipsync job to the sync. API (multipart upload), polls with curl every 15 s, downloads the result.
PAID per second of output on your plan: without --yes the script only prints the video length and stops.
NEVER resubmit a job that was accepted: pass its id as resume_job_id instead. Waits and retries when your plan's
concurrency limit is reached. Uses curl because the API rejects Python's default user agent.
Key: env SYNC_API_KEY, else SYNC_API_KEY=... in ~/.config/sync/.env. The key is never printed.
Send the clean voice track (no music); put the music back in the final render."""
import re, json, sys, time, subprocess, os


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


args = [a for a in sys.argv[1:] if a != '--yes']; yes = '--yes' in sys.argv
if len(args) < 3:
    sys.exit(__doc__)
video, audio, out = args[:3]; model = args[3] if len(args) > 3 else 'sync-3'; gid = args[4] if len(args) > 4 else None
curl = lambda *a: subprocess.run(['curl', '-s', *a], capture_output=True, text=True).stdout
if gid:
    key = read_key('SYNC_API_KEY', '~/.config/sync/.env')
    print('resuming', gid, flush=True)
else:
    secs = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', video], capture_output=True, text=True).stdout or 0)
    print(f'{secs:.1f} s of video -> paid per second of output on your sync. plan (model {model}).')
    if not yes:
        print('Not submitted (dry run, nothing spent). Show this to the user; after a yes, run again with --yes. Test 10 s first.')
        sys.exit(0)
    # the key is only needed for the paid run
    key = read_key('SYNC_API_KEY', '~/.config/sync/.env')
    for attempt in range(40):
        r = curl('-X', 'POST', 'https://api.sync.so/v2/generate', '-H', f'x-api-key: {key}', '-F', f'video=@{video}', '-F', f'audio=@{audio}', '-F', f'model={model}',
                 '-F', 'options={"sync_mode":"cut_off","temperature":0.5,"occlusion_detection_enabled":true}')
        try:
            j = json.loads(r)
        except Exception:
            print('bad response', r[:300]); time.sleep(30); continue
        if j.get('id'):
            gid = j['id']; print('submitted', gid, flush=True); break
        if 'concurrency' in json.dumps(j):
            print("your plan's concurrency limit is reached, waiting 60 s", flush=True); time.sleep(60); continue
        sys.exit('submit failed: ' + r[:500])
    else:
        sys.exit('submit: gave up')
t0 = time.time()
while True:
    time.sleep(15)
    try:
        g = json.loads(curl('-H', f'x-api-key: {key}', f'https://api.sync.so/v2/generate/{gid}'))
    except Exception:
        continue
    st = g.get('status')
    if st in ('COMPLETED', 'FAILED', 'REJECTED'):
        break
    if int(time.time() - t0) % 300 < 15:
        print(f'{int(time.time() - t0)}s {st}', flush=True)
if st != 'COMPLETED':
    sys.exit(f"sync job {gid} {st}: {g.get('error')} {g.get('errorCode')}")
subprocess.run(['curl', '-s', '-L', '-o', out, g['outputUrl']], check=True); print('saved', out, 'duration', g.get('outputDuration'), 'job', gid)
