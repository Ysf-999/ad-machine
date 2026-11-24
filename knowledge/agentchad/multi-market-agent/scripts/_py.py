# Library v2, 2026-11-10 (agentchad.io). Shared helper for this skill's scripts. Nothing here calls the internet.
# 2026-11-10: the install message names your AGENTCHAD_PY path, not a fixed one.
"""Finds the library's shared Python and explains plainly what to install when a package is missing.

Settings are read with the library's shared settings reader (the same block in every agentchad script):
environment variable -> ~/.agentchad/settings.env (written by the ad-clone-system setup) -> default.
  AGENTCHAD_PY   = ~/.venvs/agentchad/bin/python3   (numpy, scipy, soundfile, pillow, faster-whisper)
  DEMUCS_PYTHON  = ~/.venvs/demucs/bin/python3      (demucs: splits the voice from the music)
Exit code 3 always means "something is not installed"; the message says what to run."""
import importlib
import os
import sys

SHARED_INSTALL = ("(no python3.12 yet: brew install python@3.12) "
                  "python3.12 -m venv ~/.venvs/agentchad && "
                  "~/.venvs/agentchad/bin/pip install numpy scipy soundfile pillow faster-whisper")
DEMUCS_INSTALL = "(no python3.12 yet: brew install python@3.12) python3.12 -m venv ~/.venvs/demucs && ~/.venvs/demucs/bin/pip install demucs"
MISSING = 3


# --- settings reader (same in every agentchad script; skills are copied one by one, so no shared import) ---
# Order: environment variable, then ~/.agentchad/settings.env (written by the ad-clone-system setup), then the default.
_ALIASES = {"QA_PYTHON": "AGENTCHAD_PY", "MOTION_PYTHON": "AGENTCHAD_PY", "NUMPY_PYTHON": "AGENTCHAD_PY",
            "QA_DEMUCS_PYTHON": "DEMUCS_PYTHON"}
_SETTINGS_CACHE = None


def _settings_file():
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is None:
        _SETTINGS_CACHE = {}
        p = os.path.join(os.path.expanduser("~"), ".agentchad", "settings.env")
        try:
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:].strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    _SETTINGS_CACHE[k.strip()] = v.strip().strip('"').strip("'")
        except OSError:
            pass
    return _SETTINGS_CACHE


def setting(name, default=""):
    for key in (name, _ALIASES.get(name)):
        if key:
            v = os.environ.get(key, "").strip() or _settings_file().get(key, "")
            if v:
                return os.path.expanduser(v)
    return os.path.expanduser(default) if default else default
# --- end settings reader ---


def shared_python():
    return setting('AGENTCHAD_PY', '~/.venvs/agentchad/bin/python3')


def demucs_python():
    return setting('DEMUCS_PYTHON', '~/.venvs/demucs/bin/python3')


def _missing(mods):
    out = []
    for m in mods:
        try:
            importlib.import_module(m)
        except ImportError:
            out.append(m)
    return out


def _reexec():
    """Start this script again with the shared Python (once), if it exists and is not the one running."""
    alt = shared_python()
    if os.environ.get('_AGENTCHAD_REEXEC') or not os.path.exists(alt):
        return
    if os.path.abspath(alt) == os.path.abspath(sys.executable):
        return
    os.environ['_AGENTCHAD_REEXEC'] = '1'
    os.execv(alt, [alt, '-I', '-B', os.path.abspath(sys.argv[0]), *sys.argv[1:]])


def need(mods, optional=()):
    """Exit with a plain message if a required package is missing. Returns the list of missing optional ones."""
    miss = _missing(mods)
    opt = _missing(optional)
    if miss or opt:
        _reexec()
    if miss:
        names = {'PIL': 'pillow', 'faster_whisper': 'faster-whisper'}
        sys.stderr.write(
            f"{os.path.basename(sys.argv[0])} needs {', '.join(names.get(m, m) for m in miss)}, which this Python "
            f"({sys.executable}) does not have.\nMake the shared Python once (about 5 minutes, about 600 MB):\n  "
            f"{SHARED_INSTALL}\nthen run the script with {shared_python()} -I -B ... (or set AGENTCHAD_PY in "
            f"~/.agentchad/settings.env to the Python that has it)\n")
        sys.exit(MISSING)
    return opt
