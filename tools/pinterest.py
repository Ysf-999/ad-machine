"""Pinterest casting (Camilo's Seedance x Claude method): real creator / setting / prop photos as Seedance references.
Runs on the scrapling stealth browser; images never enter the Claude session (the operator picks from a sheet).

Usage (run with a python that has scrapling installed, e.g. `uv tool install scrapling`, with -I):
  pinterest.py search <dir> "<query>" [--n 16]   download up to n pins to <dir>/pin_XX.jpg + open <dir>/PICK.html
  pinterest.py pick   <dir> <XX> <dest.jpg>      copy the chosen pin (e.g. to <project>/REFS/creator.jpg)

Queries: describe the person + setting + phone feel, e.g. "woman 30s selfie kitchen iphone candid no makeup".
Pick rules (course skill): natural light, casual clothes, phone-quality, no studio or magazine poses, and only CLEAN
photos: no stickers, watermarks, text or app UI (Seedance rebuilds everything it sees as physical objects).
"""
import html, json, pathlib, re, shutil, subprocess, sys, time, urllib.parse, urllib.request


def fetch_urls(query, n):
    from scrapling.fetchers import StealthyFetcher
    def act(page):
        time.sleep(3)
        for _ in range(max(2, n // 6)):
            page.mouse.wheel(0, 2500); time.sleep(1)
        return page
    p = StealthyFetcher.fetch("https://www.pinterest.com/search/pins/?q=" + urllib.parse.quote(query),
                              network_idle=True, timeout=90000, page_action=act)
    seen, out = set(), []
    for i in p.css("img"):
        src = i.attrib.get("src", "")
        m = re.search(r"i\.pinimg\.com/[^/]+/(\w\w/\w\w/\w\w/\w+\.\w+)", src)
        if m and m[1] not in seen:
            seen.add(m[1]); out.append(m[1])
    return out[:n]


def download(tail, dest):
    for size in ("originals", "736x", "474x"):
        try:
            req = urllib.request.Request(f"https://i.pinimg.com/{size}/{tail}", headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=30).read()
            if len(data) > 5000:
                dest.write_bytes(data); return size
        except Exception:
            continue
    return None


def search(d, query, n=16):
    d = pathlib.Path(d); d.mkdir(parents=True, exist_ok=True)
    tails = fetch_urls(query, n)
    rows, meta = [], {"query": query, "pins": {}}
    for k, tail in enumerate(tails, 1):
        f = d / f"pin_{k:02d}.jpg"
        size = download(tail, f)
        if size:
            meta["pins"][f"{k:02d}"] = f"https://i.pinimg.com/{size}/{tail}"
            rows.append(f'<figure><img src="{f.name}"><figcaption>{k:02d}</figcaption></figure>')
    (d / "pins.json").write_text(json.dumps(meta, indent=1))
    (d / "PICK.html").write_text(
        f"<!doctype html><meta charset=utf-8><title>Pick a pin</title><style>body{{font:14px system-ui;margin:16px;background:#111;color:#eee}}"
        f"main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}}img{{width:100%;border-radius:6px}}"
        f"figure{{margin:0}}figcaption{{font-weight:700;text-align:center}}</style><h3>{html.escape(query)}</h3>"
        f"<p>Clean photos only (no stickers, text, watermarks, app UI). Tell Claude the number.</p><main>{''.join(rows)}</main>")
    print(f"{len(rows)} pins in {d}; opening PICK.html")
    subprocess.run(["open", str(d / "PICK.html")], check=False)


def pick(d, k, dest):
    d = pathlib.Path(d); dest = pathlib.Path(dest); dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(d / f"pin_{int(k):02d}.jpg", dest)
    meta = json.loads((d / "pins.json").read_text())
    (dest.parent / (dest.stem + "_source.txt")).write_text(f"{meta['pins'].get(f'{int(k):02d}', '')}\nquery: {meta['query']}\n")
    print(f"{dest} <- pin {int(k):02d}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == "search":
        search(a[1], a[2], int(a[a.index("--n") + 1]) if "--n" in a else 16)
    elif len(a) == 4 and a[0] == "pick":
        pick(a[1], a[2], a[3])
    else:
        sys.exit(__doc__)
