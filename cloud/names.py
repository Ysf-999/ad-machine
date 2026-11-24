"""Settings file + Modal names in one place.

Settings: cloud/controller/config.json (yours, not shipped). When it is missing, cloud/controller/config.example.json
is used as is. Every Modal app / volume / dict / secret name is "<app_prefix>-<role>". The prefix comes from the
ADMACHINE_PREFIX environment variable, else "app_prefix" in the settings file, else "admachine".
Used by the Mac side (ctl.py, dash.py, usage.py ...) and by `modal deploy controller/app.py` (which runs on the Mac).
"""
import json
import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
STATE = HERE / 'controller'
CONFIG = STATE / 'config.json'
EXAMPLE = STATE / 'config.example.json'


def config(state=None):
    """The settings as a dict: <state>/config.json, or config.example.json when there is none ({} when neither reads).
    `state` is the settings folder (default cloud/controller; tests pass their own)."""
    state = pathlib.Path(state) if state else STATE
    for f in (state / 'config.json', state / 'config.example.json'):
        if f.exists():
            try:
                data = json.loads(f.read_text())
            except ValueError:
                continue
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if not k.startswith('_')}
    return {}


def prefix():
    return (os.environ.get('ADMACHINE_PREFIX') or str(config().get('app_prefix') or '') or 'admachine').strip()


PREFIX = prefix()
APP = f'{PREFIX}-ads'                     # the deployed Modal app (controller/app.py)
VOLUME = f'{PREFIX}-adjobs'               # projects, code snapshots and the shared clip store
STATUS = f'{PREFIX}-ads-status'           # Modal Dict: live state of every run
GEN_SECRET = f'{PREFIX}-generation'       # Modal Secret: KIE_API_KEY, ELEVENLABS_API_KEY
CLAUDE_SECRET = f'{PREFIX}-claude'        # Modal Secret: CLAUDE_CODE_OAUTH_TOKEN
MODEL_VOLUME = f'{PREFIX}-whisper-ct2'    # Modal Volume: the CT2 whisper-large-v3-turbo model (read-only in workers)
