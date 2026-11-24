"""JSON-on-stdin entry point. No work happens on import."""
import contextlib
import json
import sys


def main():
    from runner import Manifest, run_stage
    request = json.load(sys.stdin)
    if set(request) != {'root', 'project', 'manifest', 'result_dir'}:
        raise ValueError('Expected root, project, manifest, result_dir')
    manifest = Manifest(**request['manifest'])
    # stdout belongs to the result protocol, never a tool's progress stream.
    with contextlib.redirect_stdout(sys.stderr):
        report = run_stage(request['root'], request['project'], manifest, request['result_dir'])
    print(json.dumps(report, allow_nan=False))


if __name__ == '__main__':
    main()
