"""Build a static website where visitors play against the bot in their browser.

The bot runs client-side with Pyodide (Python compiled to WebAssembly): no server,
no account, nothing leaves the visitor's machine. The output folder can be put on
any static host (GitHub Pages, Netlify, an existing site under /poker/...).

    python -m pokerbot build-site --out site --pyodide-dir path/to/pyodide
"""
from __future__ import annotations

import gzip
import io
import json
import pickle
import shutil
import zipfile
from pathlib import Path

from ..training.registry import models_dir, read_meta, resolve

PKG = Path(__file__).resolve().parents[1]
WEB = Path(__file__).with_name("web")
PYODIDE_CDN = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/"
PYODIDE_FILES = ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip",
                 "pyodide-lock.json"]


def _package_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(PKG.rglob("*")):
            rel = f.relative_to(PKG.parent)
            if "__pycache__" in f.parts or f.is_dir() or "web" in rel.parts:
                continue
            if f.suffix in (".py", ".json"):
                z.write(f, rel.as_posix())
    return buf.getvalue()


def _pruned(src: Path, min_weight: float) -> bytes:
    with gzip.open(src, "rb") as f:
        bp = pickle.load(f)
    kept = {k: (v[0], tuple(round(x, 3) for x in v[1]), v[2]) for k, v in bp.items()
            if len(v) < 3 or v[2] >= min_weight}
    return gzip.compress(pickle.dumps(kept, protocol=4), compresslevel=9)


def build_site(out: str | Path, version: str = "best", pyodide_dir: str | None = None,
               min_weight: float = 20.0, title: str = "Poker contre le bot",
               inline: bool = False) -> Path:
    """``inline=True``: CSS and JS inlined into index.html, body content only (no
    html/head/body tags), for hosts that wrap the page in their own skeleton."""
    out = Path(out)
    v = resolve(version)
    src = models_dir() / v
    if out.exists():
        shutil.rmtree(out)
    (out / "model").mkdir(parents=True)

    files = ["abstraction.json", "blueprint.pkl.gz"]
    (out / "model" / "blueprint.pkl.gz").write_bytes(_pruned(src / "blueprint.pkl.gz", min_weight))
    shutil.copy(src / "abstraction.json", out / "model" / "abstraction.json")
    if (src / "sixmax.pkl.gz").exists():
        (out / "model" / "sixmax.pkl.gz").write_bytes(_pruned(src / "sixmax.pkl.gz", min_weight))
        files.append("sixmax.pkl.gz")
    meta = read_meta(v)
    (out / "model" / "manifest.json").write_text(json.dumps(
        {"version": v, "files": files, "iterations": meta.get("iterations"),
         "sixmax": "sixmax.pkl.gz" in files}))
    (out / "pokerbot.zip").write_bytes(_package_zip())

    if pyodide_dir:
        (out / "pyodide").mkdir()
        for f in PYODIDE_FILES:
            shutil.copy(Path(pyodide_dir) / f, out / "pyodide" / f)
        pyodide_url = "pyodide/"
    else:
        pyodide_url = PYODIDE_CDN

    shutil.copy(WEB / "style.css", out / "style.css")
    shutil.copy(WEB / "play.js", out / "play.js")
    shutil.copy(WEB / "site_app.js", out / "app.js")
    html = (WEB / "play.html").read_text()
    html = html.replace("<title>Table de poker</title>", f"<title>{title}</title>")
    html = html.replace('href="/static/style.css"', 'href="style.css"')
    html = html.replace('<nav><a href="/" aria-current="page">Table</a><a href="/dashboard">Tableau de bord</a></nav>',
                        '<span class="muted" id="model-info"></span>')
    html = html.replace('<option value="abc">Bot ABC (heads-up)</option>\n', "")
    html = html.replace('<option value="station">Calling station (heads-up)</option>\n', "")
    html = html.replace('<option value="nit">Nit (heads-up)</option>\n', "")
    html = html.replace('<option value="maniac">Maniac (heads-up)</option>\n', "")
    html = html.replace('<h1>Jouer contre les bots</h1>',
                        '<h1>Jouer contre les bots</h1>\n  <p class="muted" id="loading" role="status">'
                        'Chargement du bot…</p>')
    html = html.replace('<script src="/static/play.js"></script>',
                        f'<script>window.PYODIDE_URL = "{pyodide_url}";</script>\n'
                        f'<script src="{pyodide_url}pyodide.js"></script>\n'
                        '<script src="app.js"></script>\n<script src="play.js"></script>')
    if inline:
        css = (WEB / "style.css").read_text()
        body = html[html.index("<header>"): html.index("</body>")]
        scripts = (f'<script>window.PYODIDE_URL = "{pyodide_url}";</script>\n'
                   f'<script src="{pyodide_url}pyodide.js"></script>\n'
                   f"<script>{(WEB / 'site_app.js').read_text()}</script>\n"
                   f"<script>{(WEB / 'play.js').read_text()}</script>")
        body = body[: body.index("<script>window.PYODIDE_URL")] + scripts
        html = (f"<title>{title}</title>\n"
                '<meta name="claude:viewport-fit-sides" content="cover">\n'
                f"<style>{css}</style>\n{body}\n")
        for f in ("style.css", "play.js", "app.js"):
            (out / f).unlink()
    (out / "index.html").write_text(html)
    return out
