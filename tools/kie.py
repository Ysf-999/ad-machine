"""Shared kie.ai client: create -> persist task id -> poll -> download, with resume by id.

Usage as a CLI:
  kie.py credit
  kie.py upload <local-file>
  kie.py run <request.json> <jobs.jsonl> <key> <out-dir>   # submits once per key, resumes by saved id
  kie.py status <task-id>
"""
import json, os, sys, time, pathlib
import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://api.kie.ai/api/v1"
UPLOAD = "https://kieai.redpandaai.co/api/file-stream-upload"


def _key():
    k = os.environ.get("KIE_API_KEY")
    if not k:
        for line in (ROOT / ".env").read_text().splitlines():
            if line.startswith("KIE_API_KEY="):
                k = line.split("=", 1)[1].strip()
    if not k:
        sys.exit("KIE_API_KEY missing from the repo .env")
    return k


def _h():
    return {"Authorization": f"Bearer {_key()}"}


def _req(method, url, **kw):
    for attempt in range(3):
        try:
            r = httpx.request(method, url, headers=_h(), timeout=120, **kw)
            r.raise_for_status()
            return r.json()
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))


def credit():
    return _req("GET", f"{API}/chat/credit")["data"]


def upload(path):
    # Large PNGs stall on kie's file server; send a high-quality JPEG copy instead.
    p = pathlib.Path(path)
    if p.suffix.lower() == ".png" and p.stat().st_size > 2_500_000:
        from PIL import Image
        jpg = p.with_suffix(".upload.jpg")
        if not jpg.exists():
            Image.open(p).convert("RGB").save(jpg, quality=92)
        path = str(jpg)
    # Unique remote name: the account's upload path is shared, so two projects uploading "scene_12.png" at the same
    # time overwrote each other (2026-10-27, parallel Halloween ads). Prefix with the parent folder + a content hash.
    import hashlib
    p = pathlib.Path(path)
    digest = hashlib.md5(p.read_bytes()).hexdigest()[:10]
    remote = f"{p.parent.parent.name}_{p.parent.name}_{p.stem}_{digest}{p.suffix}"
    with open(path, "rb") as f:
        d = _req("POST", UPLOAD, data={"uploadPath": "images/user", "fileName": remote},
                 files={"file": f})
    return d["data"].get("downloadUrl") or d["data"].get("fileUrl")


def create(body):
    d = _req("POST", f"{API}/jobs/createTask", json=body)
    if d.get("code") != 200:
        raise RuntimeError(f"createTask refused: {d.get('code')} {d.get('msg')}")
    return d["data"]["taskId"]


def status(task_id):
    return _req("GET", f"{API}/jobs/recordInfo", params={"taskId": task_id})["data"]


def wait(task_id, every=15, limit=3600):
    t0 = time.time()
    while time.time() - t0 < limit:
        try:
            d = status(task_id)
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            print(f"network issue while polling {task_id}: {e}; retrying", flush=True)
            time.sleep(30)
            continue
        if d.get("state") in ("success", "fail"):
            return d
        time.sleep(every)
    return None  # still pending: resume later by id


def _jobs(path):
    p = pathlib.Path(path)
    return {j["key"]: j for j in map(json.loads, p.read_text().splitlines())} if p.exists() else {}


def _log(path, rec):
    rec.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))   # 2026-11-15: weekly credits report needs dates
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")
        f.flush()
        os.fsync(f.fileno())


def run(body, jobs_path, key, out_dir):
    """Submit `body` under `key` unless a task id is already saved; then poll and download."""
    jobs = _jobs(jobs_path)
    last = jobs.get(key, {})
    task_id = None if last.get("state") == "fail" else last.get("taskId")  # failed tasks are not charged: resubmit
    if last.get("state") == "success":
        prev = [f for f in last.get("files") or [] if pathlib.Path(f).exists()]
        if prev and len(prev) == len(last.get("files") or []):
            print(f"DONE {key} (already downloaded, not re-billed)", flush=True)  # no re-download, no duplicate credit line
            return prev
        # the earlier result was moved/deleted = a re-roll was intended: submit a NEW task instead of re-downloading
        # the rejected one (Oct 28: producers got their old take back when re-rendering under the same name)
        print(f"REROLL {key}: previous output {last.get('files')} is gone, submitting a new task", flush=True)
        task_id = None
    if not task_id:
        task_id = create(body)
        _log(jobs_path, {"key": key, "taskId": task_id, "model": body.get("model"), "state": "submitted"})
        print(f"SUBMITTED {key} {task_id}", flush=True)
    d = wait(task_id)
    if d is None:
        print(f"PENDING {key} {task_id}", flush=True)
        return None
    if d["state"] == "fail":
        _log(jobs_path, {"key": key, "taskId": task_id, "state": "fail", "failMsg": d.get("failMsg")})
        print(f"FAIL {key} {d.get('failCode')} {d.get('failMsg')}", flush=True)
        return None
    res = d.get("resultJson")
    res = json.loads(res) if isinstance(res, str) else res
    files = []
    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    for i, url in enumerate(res.get("resultUrls", [])):
        ext = pathlib.Path(url.split("?")[0]).suffix or ".bin"
        dest = pathlib.Path(out_dir) / f"{key}{'' if i == 0 else f'_{i}'}{ext}"
        dest.write_bytes(httpx.get(url, timeout=300, follow_redirects=True).content)
        files.append(str(dest))
    _log(jobs_path, {"key": key, "taskId": task_id, "state": "success", "files": files,
                     "urls": res.get("resultUrls"), "creditsConsumed": d.get("creditsConsumed")})
    print(f"OK {key} credits={d.get('creditsConsumed')} {files}", flush=True)
    return files


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "credit":
        print(credit())
    elif cmd == "upload":
        print(upload(sys.argv[2]))
    elif cmd == "status":
        print(json.dumps(status(sys.argv[2]), indent=2))
    elif cmd == "run":
        run(json.loads(pathlib.Path(sys.argv[2]).read_text()), sys.argv[3], sys.argv[4], sys.argv[5])
    else:
        sys.exit(__doc__)
