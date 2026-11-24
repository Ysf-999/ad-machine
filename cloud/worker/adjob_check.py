"""Offline readiness check run through adjob_boot (no network, no secrets needed): can every pipeline tool import,
are the shims active, are ffmpeg / fonts / claude CLI / whisper model present. Prints one JSON line."""
import importlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

work = pathlib.Path(os.environ['ADJOB_WORK'])
sys.path.insert(0, str(work / 'tools'))
out = {'python': sys.version.split()[0], 'imports': {}, 'ad': sys.argv[1]}
for mod in ['kie', 'ad', 'music_lib', 'feedback', 'rawedit', 'claude_client', 'taste']:
    try:
        m = importlib.import_module(mod)
        out['imports'][mod] = 'ok' + (' (kie POST patched)' if getattr(m, '_adjob_patched', False) else '')
    except SystemExit as e:
        out['imports'][mod] = f'SystemExit {e}'
    except Exception as e:
        out['imports'][mod] = f'{type(e).__name__}: {e}'[:200]
for script in ['gen_scenes.py', 'batch.py', 'assemble_anim.py', 'qc.py', 'realign_vo.py', 'caption_sync_check.py', 'plan_review.py', 'master_qc.py']:
    p = work / 'tools' / script
    if not p.exists():
        out['imports'][script] = 'missing'
        continue
    r = subprocess.run([str(work / '.venv/bin/python'), '-I', '-c',
                        f'import ast,sys; ast.parse(open("{p}").read()); sys.path.insert(0,"{work}/tools"); '
                        f'src=open("{p}").read(); [__import__(l.split()[1].split(",")[0].split(".")[0]) for l in src.splitlines() '
                        f'if l.startswith("import ") and " as " not in l and l.split()[1].split(",")[0] not in ("anthropic",)]'],
                       capture_output=True, text=True, cwd=work, timeout=120)
    out['imports'][script] = 'ok' if r.returncode == 0 else (r.stderr.strip().splitlines() or ['?'])[-1][:200]
out['mlx_shim'] = 'mlx_whisper' in sys.modules
out['ffmpeg'] = shutil.which('ffmpeg')
out['ffprobe'] = shutil.which('ffprobe')
out['claude_cli'] = shutil.which('claude')
out['model_files'] = sorted(p.name for p in (work / '.ct2').glob('*')) if (work / '.ct2').exists() else []
fc = subprocess.run(['fc-match', '-f', '%{file}', 'Montserrat ExtraBold'], capture_output=True, text=True)
out['font_montserrat_extrabold'] = fc.stdout.strip()
out['fonts_in_library'] = len(list((work / 'library/fonts').glob('*')))
out['secrets_present'] = sorted(k for k in ('KIE_API_KEY', 'ELEVENLABS_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN') if os.environ.get(k))
print(json.dumps(out))
