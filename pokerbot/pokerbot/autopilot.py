"""Autopilot: keeps the bot improving on this PC with nobody watching.

    python -m pokerbot autopilot          (or double-click Autopilote-pokerbot)

Every cycle:
  1. trains a new version (resuming the latest version that can be resumed);
  2. runs it through the level ladder (cash conditions); a version that beats the
     current best at level 4 becomes the new best;
  3. refreshes the dashboard; when the best version changed, rebuilds the static
     site and, if configured, publishes it into a git repository (your website)
     and pushes it with your own git credentials;
  4. optionally plays the bot-friendly platforms that are configured (ACPC
     servers, Slumbot).
Meanwhile the play page and dashboard stay available in the browser.

Settings live in autopilot.json (created with defaults on first run). Stop with
Ctrl+C or by closing the window: the next start picks up where it left off.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import traceback
from pathlib import Path

from .training.registry import PROJECT_ROOT, list_versions, models_dir, resolve

CONFIG_FILE = PROJECT_ROOT / "autopilot.json"
LOG_FILE = PROJECT_ROOT / "data" / "autopilot.log"

DEFAULTS = {
    "cycles": 0,                       # 0 = run until stopped
    "train_minutes": 60,               # training time per cycle
    "workers": max(1, (os.cpu_count() or 2) - 1),   # leave one core for you
    "ladder_hands": 50000,             # duplicate hands per ladder level
    "pause_minutes": 0,                # rest between cycles
    "web": {"enabled": True, "host": "127.0.0.1", "port": 8000, "open_browser": True},
    "site": {
        "build": True,                 # rebuild the playable static site when the best version changes
        "out": "site",
        "pyodide_dir": "",             # empty = Pyodide loaded from the jsdelivr CDN
        "deploy_repo": "",             # path of a local git clone of your website ("" = no publishing)
        "deploy_subdir": "poker",      # published at <your site>/poker/
        "push": False,                 # git push after committing (uses your git credentials)
    },
    "platforms": {
        "acpc": [],                    # e.g. [{"host": "dealer.example.org", "port": 18791}]
        "slumbot_hands": 0,            # hands vs Slumbot per cycle (0 = off)
    },
}


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG_FILE.exists():
        user = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    else:
        CONFIG_FILE.write_text(json.dumps(DEFAULTS, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"configuration par défaut créée : {CONFIG_FILE}")
    return cfg


def resumable_version() -> str | None:
    """Latest version that still has its regret tables (pre-trained ones do not)."""
    for v in reversed(list_versions()):
        if (models_dir() / v / "tables.pkl.gz").exists():
            return v
    return None


def start_web(cfg: dict) -> None:
    from .ui.web_server import serve
    w = cfg["web"]
    t = threading.Thread(target=serve, kwargs={"port": w["port"], "host": w["host"],
                                               "open_browser": w.get("open_browser", True)},
                         daemon=True)
    t.start()


def publish_site(cfg: dict) -> None:
    from .ui.site_builder import build_site
    s = cfg["site"]
    out = PROJECT_ROOT / s["out"]
    build_site(out, "best", s["pyodide_dir"] or None, title="Pokerbot")
    log(f"site jouable reconstruit dans {out}")
    repo = s.get("deploy_repo")
    if not repo:
        return
    repo = Path(repo).expanduser()
    if not (repo / ".git").exists():
        log(f"publication ignorée : {repo} n'est pas un dépôt git")
        return
    dest = repo / s["deploy_subdir"]
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True)  # noqa: E731
    if s.get("push"):
        r = git("pull", "--ff-only")
        if r.returncode:
            log(f"git pull a échoué, publication annulée : {r.stderr.strip()[:300]}")
            return
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(out, dest)
    git("add", s["deploy_subdir"])
    r = git("commit", "-m", f"pokerbot: nouvelle meilleure version ({resolve('best')})")
    if r.returncode and "nothing to commit" not in r.stdout + r.stderr:
        log(f"git commit a échoué : {r.stderr.strip()[:300]}")
        return
    if s.get("push"):
        r = git("push")
        log("site publié (git push effectué)" if r.returncode == 0
            else f"git push a échoué : {r.stderr.strip()[:300]}")
    else:
        log(f"site copié et commité dans {dest} (push désactivé dans autopilot.json)")


def play_platforms(cfg: dict) -> None:
    p = cfg["platforms"]
    for server in p.get("acpc", []):
        try:
            from .evaluation.acpc import play_acpc
            n = play_acpc(server["host"], int(server["port"]), "bot:best", verbose=False)
            log(f"ACPC {server['host']}:{server['port']} : {n} mains jouées")
        except OSError as e:
            log(f"ACPC {server.get('host')} injoignable : {e}")
    if p.get("slumbot_hands"):
        try:
            from .evaluation.slumbot import play_slumbot
            (m, lo, hi), _ = play_slumbot(int(p["slumbot_hands"]), "bot:best", verbose=False)
            log(f"Slumbot : {m:+.1f} bb/100 [{lo:+.1f}, {hi:+.1f}]")
        except Exception as e:  # network, API change...
            log(f"Slumbot indisponible : {e}")


def run(cycles: int | None = None) -> None:
    from .evaluation.ladder import climb
    from .training.run import train_version
    from .ui.dashboard import export_html

    cfg = load_config()
    if cycles is not None:
        cfg["cycles"] = cycles
    log(f"autopilote démarré : {cfg['train_minutes']} min d'entraînement par cycle, "
        f"{cfg['workers']} processus, meilleure version actuelle : {resolve('best')}")
    if cfg["web"]["enabled"]:
        start_web(cfg)
    done = 0
    while cfg["cycles"] == 0 or done < cfg["cycles"]:
        done += 1
        try:
            best_before = resolve("best")
            parent = resumable_version()
            log(f"cycle {done} : entraînement {'depuis ' + parent if parent else 'depuis zéro'}")
            v = train_version(10**9, workers=cfg["workers"], parent=parent,
                              minutes=cfg["train_minutes"], verbose=False)
            log(f"cycle {done} : {v} entraîné, passage sur l'échelle de niveaux")
            results = climb(v, hands=cfg["ladder_hands"], workers=cfg["workers"],
                            min_hands=cfg["ladder_hands"], verbose=False)
            for r in results:
                word = {"promote": "monte", "demote": "descend", "stay": "reste"}[r.decision]
                log(f"  {v} niveau {r.level} : {r.bb100:+.1f} bb/100 [{r.lo:+.1f}, {r.hi:+.1f}] -> {word}")
            best = resolve("best")
            if best != best_before:
                src6 = models_dir() / best_before / "sixmax.pkl.gz"
                if src6.exists() and not (models_dir() / best / "sixmax.pkl.gz").exists():
                    shutil.copy(src6, models_dir() / best / "sixmax.pkl.gz")   # keep the 6-max strategy
                log(f"NOUVELLE MEILLEURE VERSION : {best}")
                if cfg["site"]["build"]:
                    publish_site(cfg)
            else:
                log(f"la meilleure version reste {best}")
            export_html(PROJECT_ROOT / "data" / "dashboard.html")
            play_platforms(cfg)
        except KeyboardInterrupt:
            raise
        except Exception:
            log("erreur pendant le cycle (l'autopilote continue) :\n" + traceback.format_exc())
            time.sleep(60)
        if cfg["pause_minutes"]:
            time.sleep(cfg["pause_minutes"] * 60)
    log("autopilote terminé")
