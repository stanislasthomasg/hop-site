// Static-site build: runs the Python bot in the browser with Pyodide and exposes
// window.pokerApi(path, body), which play.js uses instead of HTTP calls.
(async () => {
  const loading = document.getElementById("loading");
  const start = document.getElementById("start");
  start.disabled = true;
  const bytes = async (url) => {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url} : ${r.status}`);
    return new Uint8Array(await r.arrayBuffer());
  };
  try {
    loading.textContent = "Chargement du moteur Python dans le navigateur (≈ 15 Mo, une seule fois)…";
    const py = await loadPyodide({ indexURL: window.PYODIDE_URL });
    loading.textContent = "Chargement du bot…";
    py.unpackArchive(await bytes("pokerbot.zip"), "zip", { extractDir: "/app" });
    const manifest = await (await fetch("model/manifest.json")).json();
    const dir = `/app/models/${manifest.version}`;
    py.FS.mkdirTree(dir);
    py.FS.mkdirTree("/app/data");
    for (const f of manifest.files) py.FS.writeFile(`${dir}/${f}`, await bytes(`model/${f}`));
    py.FS.writeFile(`${dir}/meta.json`, JSON.stringify({ iterations: manifest.iterations }));
    py.FS.writeFile("/app/models/best.txt", manifest.version);
    try {  // the bot remembers this visitor's playing style between visits
      const mem = localStorage.getItem("pokerbot-opponents");
      if (mem) py.FS.writeFile("/app/data/opponents.json", mem);
    } catch (e) { /* storage unavailable: start fresh */ }
    py.runPython(`
import os, sys
sys.path.insert(0, "/app")
os.environ["POKERBOT_MODELS"] = "/app/models"
from pokerbot.ui.web_server import App
app = App(["bot:best"], db=False, search=False)   # river search is too slow in pure Python
`);
    const app = py.globals.get("app");
    window.pokerApi = async (path, body) => {
      const out = JSON.parse(app.handle_json(path, body === undefined ? null : JSON.stringify(body)));
      try {
        localStorage.setItem("pokerbot-opponents",
          py.FS.readFile("/app/data/opponents.json", { encoding: "utf8" }));
      } catch (e) { /* nothing saved yet or storage unavailable */ }
      return out;
    };
    const six = manifest.sixmax ? ", stratégie préflop 6-max incluse" : "";
    document.getElementById("model-info").textContent =
      `${manifest.version} · ${(manifest.iterations || 0).toLocaleString("fr-FR")} itérations${six}`;
    loading.hidden = true;
    start.disabled = false;
  } catch (e) {
    loading.textContent = `Impossible de charger le bot : ${e.message}`;
  }
})();
