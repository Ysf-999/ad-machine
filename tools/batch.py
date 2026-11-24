"""Run several kie requests concurrently, each resumable by its saved task id.

Usage: batch.py <jobs.jsonl> <out-dir> <key>=<request.json> [<key>=<request.json> ...] [--workers N]
Already-finished keys (file present in out-dir) are skipped; keys with a saved task id are polled, not resubmitted.
"""
import json, pathlib, sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import kie


def main():
    args = sys.argv[1:]
    workers = 4
    if "--workers" in args:
        i = args.index("--workers"); workers = int(args[i + 1]); del args[i:i + 2]
    jobs, out = args[0], pathlib.Path(args[1])
    pairs = [a.split("=", 1) for a in args[2:]]
    todo = []
    for key, req in pairs:
        if any(out.glob(f"{key}.*")):
            print(f"SKIP {key} (already downloaded)", flush=True)
            continue
        todo.append((key, json.loads(pathlib.Path(req).read_text())))
    print(f"credit before: {kie.credit()}", flush=True)

    def one(item):
        key, body = item
        try:
            return key, kie.run(body, jobs, key, str(out))
        except Exception as e:
            print(f"FAIL {key} {e}", flush=True)
            return key, None

    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(one, todo))
    print(f"credit after: {kie.credit()}", flush=True)
    bad = [k for k, r in results if not r]
    print("ALL OK" if not bad else f"NOT DONE: {bad}", flush=True)


if __name__ == "__main__":
    main()
