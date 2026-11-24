#!/usr/bin/python3 -I
"""ffmpeg gate: one video render at a time, low priority, capped threads.

~/.local/bin/ffmpeg can point here (a symlink). The real binary is found at run
time: static_ffmpeg inside the repo .venv, else the first other ffmpeg on PATH
(FFMPEG_REAL=/path/to/ffmpeg overrides). Every tool and every Claude session that runs "ffmpeg" goes
through it.

- Video encodes (output .mp4/.mov/.mkv/.webm/.m4v/.gif that is not a stream
  copy) wait for a machine-wide lock, so only one runs at a time. Frame grabs,
  audio work, analysis passes (-f null) and stream-copy concats skip the lock.
- Everything runs at nice 10 so the Mac stays responsive.
- Video encodes get -threads FFMPEG_THREADS (default 6) unless the command
  already sets -threads.

Night mode (1:00-10:59 local): up to FFMPEG_NIGHT_SLOTS (default 3) renders at
once with no thread cap. One render only keeps ~3.7 of 10 cores busy (measured
11/15), so parallel renders really do finish a queue sooner.

Env overrides: FFMPEG_NO_GATE=1 (bypass entirely), FFMPEG_THREADS=N,
FFMPEG_NIGHT_SLOTS=N.
Undo: ln -sf "$REAL" ~/.local/bin/ffmpeg
"""
import fcntl
import glob
import os
import signal
import subprocess
import sys
import time

NIGHT_START, NIGHT_END = 1, 11          # 1:00 am to 10:59 am local time
NIGHT_SLOTS = int(os.environ.get("FFMPEG_NIGHT_SLOTS", "3"))



def _find_real():
    """The real ffmpeg: $FFMPEG_REAL, static_ffmpeg in the repo .venv, else the first ffmpeg on PATH that is not this gate."""
    if os.environ.get("FFMPEG_REAL"): return os.environ["FFMPEG_REAL"]
    me = os.path.realpath(__file__)
    root = os.path.dirname(os.path.dirname(me))
    for c in sorted(glob.glob(os.path.join(root, ".venv", "lib", "python*", "site-packages", "static_ffmpeg", "bin", "*", "ffmpeg"))):
        if os.access(c, os.X_OK): return c
    for d in os.environ.get("PATH", "").split(os.pathsep):
        c = os.path.join(d, "ffmpeg")
        if os.path.isfile(c) and os.access(c, os.X_OK) and os.path.basename(os.path.realpath(c)) != os.path.basename(me): return c
    return None


REAL = _find_real()
LOCK = os.path.expanduser("~/.cache/ffmpeg-render.lock")
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".gif")


def opt(args, *names):
    for i, a in enumerate(args[:-1]):
        if a in names:
            return args[i + 1]
    return None


def is_video_encode(args):
    if "-i" not in args or len(args) < 3:
        return False
    out = args[-1]
    fmt = opt(args, "-f")
    if fmt == "null" or "-vn" in args:
        return False
    if not out.lower().endswith(VIDEO_EXT) and fmt not in ("mp4", "mov", "matroska", "webm"):
        return False
    vcodec = opt(args, "-c:v", "-vcodec", "-codec:v")
    allc = opt(args, "-c", "-codec")
    if vcodec == "copy" or (allc == "copy" and vcodec is None):
        return False
    return True


def allowed_slots():
    """1 render by day; NIGHT_SLOTS renders from 1:00 to 10:59 local time."""
    force = os.environ.get("FFMPEG_GATE_FORCE")  # "night" / "day", for testing
    if force:
        return NIGHT_SLOTS if force == "night" else 1
    h = time.localtime().tm_hour
    return NIGHT_SLOTS if NIGHT_START <= h < NIGHT_END else 1


def try_lock(i):
    fd = os.open(LOCK if i == 0 else f"{LOCK}.{i}", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        os.close(fd)
        return None


def acquire_slot():
    """Take a free render slot; re-checks the clock while waiting, so a queued
    render starts at 1:00 when the night slots open. By day a render only starts
    when every slot is free (night renders still finishing count as busy)."""
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    told = False
    while True:
        n = allowed_slots()
        if n > 1:
            for i in range(n):
                fd = try_lock(i)
                if fd is not None:
                    return fd
        else:
            fd = try_lock(0)
            if fd is not None:
                others = [try_lock(i) for i in range(1, NIGHT_SLOTS)]
                busy = any(o is None for o in others)
                for o in others:
                    if o is not None:
                        os.close(o)
                if not busy:
                    return fd
                os.close(fd)
        if not told:
            sys.stderr.write("[ffmpeg-gate] another render is running, waiting for it...\n")
            told = True
        time.sleep(2)


def main():
    if not REAL: sys.exit("ffmpeg_gate: no real ffmpeg found (pip install static-ffmpeg in .venv, brew install ffmpeg, or set FFMPEG_REAL)")
    args = sys.argv[1:]
    if os.environ.get("FFMPEG_NO_GATE") == "1":
        os.execv(REAL, [REAL] + args)

    heavy = is_video_encode(args)
    if heavy and "-threads" not in args and allowed_slots() == 1:
        threads = os.environ.get("FFMPEG_THREADS", "6")
        args = args[:-1] + ["-threads", threads, args[-1]]

    lock_fd = acquire_slot() if heavy else None

    try:
        os.nice(10)
    except OSError:
        pass

    child = subprocess.Popen([REAL] + args)

    def forward(sig, _frame):
        try:
            child.send_signal(sig)
        except ProcessLookupError:
            pass

    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, forward)

    rc = child.wait()
    if lock_fd is not None:
        os.close(lock_fd)  # releases the lock (also released automatically if we die)
    sys.exit(rc if rc >= 0 else 128 - rc)


if __name__ == "__main__":
    main()
