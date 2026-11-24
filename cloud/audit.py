"""Offline source/installed-metadata audit; never import or execute production tools.

Run with .venv/bin/python cloud/audit.py --check, or --write to refresh cloud/locks.
Only top-level tools/*.py are executable scope; backups/vendor code are counted separately.
No .env, auth files, images, provider endpoints, or production assets are opened.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from names import PREFIX  # noqa: E402
HOMES = str(Path.home().parent).rstrip("/") + "/"   # the folder that holds home folders (macOS: the Users folder)

ROOT = Path(__file__).resolve().parents[1]
LOCKS = ROOT / "cloud" / "locks"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe(value):
    """Do not persist URL query/userinfo or likely credential-bearing argument values."""
    s = str(value)
    if re.search(r"(?i)(bearer\s+|sk-[a-z0-9]|(?:token|password|secret|api[_-]?key)\s*[=:]\s*\S+)", s):
        return "<redacted credential-bearing value>"
    s = re.sub(r"https?://[^\s\"'<>]+", lambda m: urlsplit(m[0]).scheme + "://" + (urlsplit(m[0]).hostname or "") + urlsplit(m[0]).path, s)
    return s.replace(str(Path.home()), "~")


def expr(node):
    return safe(ast.unparse(node))[:500]


def inspect_tool(p):
    data = p.read_bytes()
    tree = ast.parse(data, filename=str(p))
    imports, calls, strings, env = set(), [], [], set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imports.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            imports.add(n.module or "")
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            s = n.value
            if len(s) < 300 and (s.startswith((HOMES, "~/", "/tmp/", "/System/", "/Library/")) or s in ("ffmpeg", "ffprobe", "open", "pbpaste", "claude", "curl", "composio", "demucs", "node", "npx", "tools/hf") or re.search(r"\.(jsonl?|npz|csv|ass|mp[34]|wav|html|ttf|otf|md)$", s)):
                strings.append({"line": n.lineno, "value": safe(s)})
        if isinstance(n, ast.Call):
            f = ast.unparse(n.func)
            if f.endswith(("read_text", "read_bytes", "write_text", "write_bytes", "mkdir", "unlink", "rmtree", "copyfile", "copy", "link", "open", "run", "Popen", "execv", "urlopen", "urlretrieve", "create", "transcribe")) or f in ("open", "sh", "ff", "run"):
                calls.append({"line": n.lineno, "call": expr(n)})
            if f.endswith(("getenv", "environ.get", "environ.setdefault")) and n.args and isinstance(n.args[0], ast.Constant):
                env.add(str(n.args[0].value))
    return {"file": str(p.relative_to(ROOT)), "sha256": sha(data), "lines": len(data.splitlines()),
            "summary": (ast.get_docstring(tree) or "").split("\n")[0], "imports": sorted(imports),
            "claude_client_direct": "claude_client" in imports,
            "anthropic_direct": "anthropic" in imports,
            "functions": [{"name": n.name, "line": n.lineno, "end": n.end_lineno} for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))],
            "env_names": sorted(env), "path_binary_literals": sorted(strings, key=lambda x: x["line"]),
            "io_process_llm_calls": sorted(calls, key=lambda x: x["line"])}


def inventory():
    ps = sorted((ROOT / "tools").glob("*.py"))
    items = [inspect_tool(p) for p in ps]
    return {"schema": 1, "method": "AST + source review; candidates, not a complete runtime dependency tracer",
            "scope": "tools/*.py (non-recursive); backups/vendor excluded",
            "tool_count": len(items), "source_lines": sum(x["lines"] for x in items), "tools": items}


def pins(venv):
    sites = sorted((ROOT / venv / "lib").glob("python*/site-packages"))
    packages = []
    for d in importlib.metadata.distributions(path=[str(p) for p in sites]):
        name, version = d.metadata.get("Name"), d.version
        if not name or not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or not re.fullmatch(r"[A-Za-z0-9_.+!-]+", version):
            raise ValueError("Unserializable installed metadata (omitted)")
        direct = d.read_text("direct_url.json")
        origin = None
        if direct:
            j = json.loads(direct)
            u = urlsplit(j.get("url", ""))
            origin = {"scheme": u.scheme, "host": u.hostname, "editable": bool(j.get("dir_info", {}).get("editable")),
                      "vcs": j.get("vcs_info", {}).get("vcs"), "commit_id": j.get("vcs_info", {}).get("commit_id")}
        packages.append({"name": name, "version": version, "direct_origin": origin})
    packages.sort(key=lambda x: x["name"].lower())
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv unavailable; no freeze capture")
    cmd = [uv, "--offline", "pip", "freeze", "--python", str(ROOT / venv / "bin" / "python")]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    if r.returncode:
        raise RuntimeError("Offline uv freeze failed; raw output suppressed")
    # Raw uv output may contain direct URLs: never persist or print those.
    frozen = [x for x in r.stdout.splitlines() if x and not x.startswith("#")]
    plain = [x for x in frozen if re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", x)]
    normalize = lambda s: re.sub(r"[-_.]+", "-", s).lower()
    by_pin = {normalize(x) for x in plain}
    nonplain = len(frozen) - len(plain)
    for p in packages:
        if not p["direct_origin"] and normalize(f"{p['name']}=={p['version']}") not in by_pin:
            raise ValueError("uv/metadata mismatch; package details suppressed")
    header = ["# Installed snapshot; generated offline by cloud/audit.py.",
              "# NOT a portable Linux resolution or hash-verified wheel lock.",
              "# Direct/editable requirements are version-normalized; see capture.json limitations."]
    text = "\n".join(header + [f"{p['name']}=={p['version']}" for p in packages]) + "\n"
    return text, {"venv": venv, "command": f"uv --offline pip freeze --python {venv}/bin/python", "exit_code": r.returncode,
                  "uv_lines": len(frozen), "version_pin_lines": len(plain), "nonplain_lines_normalized": nonplain,
                  "installed_packages": len(packages), "packages": packages, "pin_sha256": sha(text.encode())}


def schedulers():
    rows = []
    for p in sorted((Path.home() / "Library" / "LaunchAgents").glob(f"com.{PREFIX}.*.plist")):
        data = p.read_bytes()
        j = plistlib.loads(data)
        args = j.get("ProgramArguments", [])
        cleaned, redact_next = [], False
        for arg in args:
            cleaned.append("<redacted>" if redact_next else safe(arg))
            redact_next = bool(re.fullmatch(r"--?(?:token|password|secret|api[-_]?key)", str(arg), re.I))
        rows.append({"file": safe(p), "sha256": sha(data), "label": j.get("Label"),
                     "program": safe(j.get("Program", "")), "arguments": cleaned,
                     "working_directory": safe(j.get("WorkingDirectory", "")),
                     "environment_names": sorted(j.get("EnvironmentVariables", {})),
                     "schedule": {k: j[k] for k in ("StartCalendarInterval", "StartInterval", "RunAtLoad", "KeepAlive", "ThrottleInterval", "ProcessType", "WatchPaths", "QueueDirectories") if k in j},
                     "stdout": safe(j.get("StandardOutPath", "")), "stderr": safe(j.get("StandardErrorPath", ""))})
    return {"schema": 1, "method": "plist bytes only; loaded/enabled launchd state NOT queried", "count": len(rows), "jobs": rows}


def runtime():
    binaries = {}
    for name in ("uv", "ffmpeg", "ffprobe", "node", "npm", "claude", "composio", "docker", "modal"):
        p = shutil.which(name)
        binaries[name] = safe(Path(p).resolve()) if p else None
    static = ROOT / ".venv/lib/python3.12/site-packages/static_ffmpeg/bin/darwin_arm64"
    ff = static / "ffmpeg"
    version = subprocess.run([str(ff), "-version"], capture_output=True, text=True, timeout=15)
    models = {}
    hub = Path.home() / ".cache/huggingface/hub"
    for p in sorted(hub.glob("models--*")):
        # Directory names and ref revision IDs only; never open model media or auth metadata.
        models[p.name] = {"snapshots": sorted(q.name for q in (p / "snapshots").glob("*")),
                          "refs": {q.name: q.read_text().strip() for q in (p / "refs").glob("*") if q.is_file()}}
    package_lock = ROOT / "tools/hyperframes/package-lock.json"
    lock = json.loads(package_lock.read_text())
    npm = {k: {field: v[field] for field in ("name", "version", "integrity", "os", "cpu", "optional") if field in v}
           for k, v in lock.get("packages", {}).items()}
    extras = {}
    scrap = Path.home() / ".local/share/uv/tools/scrapling/lib"
    for d in importlib.metadata.distributions(path=[str(p) for p in scrap.glob("python*/site-packages")]):
        if d.metadata.get("Name", "").lower() in ("scrapling", "playwright", "patchright"):
            extras[d.metadata["Name"]] = d.version
    fonts = {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in sorted((ROOT / "library/fonts").glob("*")) if p.is_file()}
    return {"python": sys.version.split()[0], "system": platform.system(), "machine": platform.machine(),
            "binaries": binaries, "ffmpeg_version": safe(version.stdout),
            "static_binary_sha256": {p.name: sha(p.read_bytes()) for p in (static / "ffmpeg", static / "ffprobe")},
            "fonts_sha256": fonts, "cached_model_revisions": models, "scrapling_environment_selected_packages": extras,
            "hyperframes_package_lock_sha256": sha(package_lock.read_bytes()), "npm_packages": npm,
            "limitations": "No model loads, browser launches, CLI auth/version calls, renders, API calls, or image viewing. Model directories are not a completeness check."}


def check():
    inv = inventory()
    old = json.loads((LOCKS / "tools-inventory.json").read_text())
    changed = [x["file"] for x in inv["tools"] if x["sha256"] != next((y["sha256"] for y in old["tools"] if y["file"] == x["file"]), None)]
    if changed:
        print(json.dumps({"source_changed_since_inventory": changed}))
        return 1
    assert inv["tool_count"] == old["tool_count"]
    if (LOCKS / "stage-manifests.json").exists():   # optional hand-written stage manifest
        stage = json.loads((LOCKS / "stage-manifests.json").read_text())
        for name in ("ad", "rawedit"):
            for item in stage[name]:
                assert all(k in item for k in ("stage", "inputs", "outputs", "risks"))
    for key in ("venv", "object-separation"):
        p = LOCKS / (key + ".freeze.txt")
        lines = [s for s in p.read_text().splitlines() if s and not s.startswith("#")]
        assert lines and all(re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", s) for s in lines)
    for p in LOCKS.glob("*.json"):
        json.loads(p.read_text())
    print(json.dumps({"tools": inv["tool_count"], "source_lines": inv["source_lines"], "ad_stages": len(stage["ad"]), "rawedit_stages": len(stage["rawedit"]), "result": "PASS: source fingerprints, report coverage, manifest shape, pin syntax, JSON"}))
    return 0


def main():
    a = argparse.ArgumentParser(description=__doc__)
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    args = a.parse_args()
    if args.check:
        return check()
    LOCKS.mkdir(exist_ok=True)
    def put(name, value):
        (LOCKS / name).write_text(json.dumps(value, indent=2) + "\n")
    put("tools-inventory.json", inventory())
    put("launchd-inventory.json", schedulers())
    put("runtime-inventory.json", runtime())
    cap = {}
    for directory, key in ((".venv", "venv"), (".object-separation", "object-separation")):
        txt, metadata = pins(directory)
        (LOCKS / (key + ".freeze.txt")).write_text(txt)
        cap[key] = metadata
    put("capture.json", cap)
    print(json.dumps({"result": "captured offline", "tools": len(list((ROOT / 'tools').glob('*.py'))), "venv_packages": cap['venv']['installed_packages'], "object_separation_packages": cap['object-separation']['installed_packages']}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
