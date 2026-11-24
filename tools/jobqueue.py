#!/usr/bin/env python3
"""Run heavy AI-UGC video jobs one at a time.

Keeps exactly one job tree running; every other job tree is frozen with
SIGSTOP (nothing lost) and resumed with SIGCONT when its turn comes.
New heavy jobs started later are queued automatically.
Stop the queue with `kill <pid>` (SIGTERM): it resumes every frozen job first.

usage: jobqueue.py LOGFILE [pid ...]   (pids = initial priority order)
"""
import datetime
import os
import re
import signal
import subprocess
import sys
import time

PAT = re.compile(r'(rawedit\.py|render_lin\.py|tools/ad\.py)\b.*\b(render|transcribe|captions|stitch|assemble)\b')
LOG = sys.argv[1]
ME = os.getpid()


def log(msg):
    with open(LOG, 'a') as f:
        f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def snapshot():
    out = subprocess.run(['ps', '-Ao', 'pid=,ppid=,stat=,args='], capture_output=True, text=True).stdout
    procs = {}
    for line in out.splitlines():
        p = line.split(None, 3)
        if len(p) == 4:
            procs[int(p[0])] = (int(p[1]), p[2], p[3])
    return procs


def is_job(args):
    return 'python' in args.lower() and PAT.search(args) is not None


def alive(pid, procs):
    return pid in procs and not procs[pid][1].startswith('Z')


def tree(pid, procs):
    ch = {}
    for p, (pp, _, _) in procs.items():
        ch.setdefault(pp, []).append(p)
    out, stack = [pid], [pid]
    while stack:
        for c in ch.get(stack.pop(), []):
            out.append(c)
            stack.append(c)
    return out


def signal_tree(pid, procs, sig):
    t = tree(pid, procs)
    for p in (t if sig == signal.SIGSTOP else reversed(t)):
        try:
            os.kill(p, sig)
        except (ProcessLookupError, PermissionError):
            pass


def roots(procs):
    found = []
    for pid, (pp, _, args) in procs.items():
        if pid == ME or not is_job(args) or not alive(pid, procs):
            continue
        a, top = pp, True
        while a in procs and a > 1:
            if is_job(procs[a][2]):
                top = False
                break
            a = procs[a][0]
        if top:
            found.append(pid)
    return sorted(found)


def label(pid, procs):
    args = procs.get(pid, (0, '', '?'))[2]
    m = re.search(r'(rawedit\.py|render_lin\.py|ad\.py)\s+(\S+)\s+(\S+)', args)
    return f"{pid} {m.group(2)} {m.group(3)}" if m else f"{pid} {args[:80]}"


queue = [int(p) for p in sys.argv[2:]]
active = None


def shutdown(*_):
    procs = snapshot()
    for pid in queue:
        if alive(pid, procs):
            signal_tree(pid, procs, signal.SIGCONT)
    log("queue stopped: resumed every job")
    sys.exit(0)


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)
log(f"queue started (pid {ME})")

while True:
    procs = snapshot()
    queue = [p for p in queue if alive(p, procs)]
    for pid in roots(procs):
        if pid not in queue:
            queue.append(pid)
            log(f"queued {label(pid, procs)}")
    if active is not None and not alive(active, procs):
        log(f"finished {active}")
        active = None
    if active is None and queue:
        active = queue[0]
        log(f"running {label(active, procs)}  ({len(queue) - 1} waiting)")
    for pid in queue:
        signal_tree(pid, procs, signal.SIGCONT if pid == active else signal.SIGSTOP)
    time.sleep(5)
