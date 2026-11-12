const COLORS = ["#1f7a4d", "#2c6fbb", "#c0392b", "#b7791f", "#7b4fc4", "#0e8a8a", "#a33f7d"];
const LEVEL_NAMES = { 1: "N1 bots simples", 2: "N2 profils solides", 3: "N3 anciennes versions", 4: "N4 meilleure version" };
const el = (id) => document.getElementById(id);
const SVGNS = "http://www.w3.org/2000/svg";

function svg(tag, attrs, text) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
}

function empty(target, msg) {
  target.replaceChildren(Object.assign(document.createElement("p"), { className: "muted", textContent: msg }));
}

// series: [{name, ys:[...], xs?:[...]}]
function lineChart(target, series, xLabel) {
  series = series.filter((s) => s.ys.length);
  if (!series.length) return empty(target, "Pas encore de données.");
  const W = 640, H = 240, L = 48, R = 10, T = 10, B = 26;
  const xsOf = (s) => s.xs || s.ys.map((_, i) => i);
  const allX = series.flatMap(xsOf), allY = series.flatMap((s) => s.ys).concat([0]);
  const x0 = Math.min(...allX), x1 = Math.max(...allX, x0 + 1);
  let y0 = Math.min(...allY), y1 = Math.max(...allY);
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const sx = (x) => L + (x - x0) / (x1 - x0) * (W - L - R);
  const sy = (y) => T + (y1 - y) / (y1 - y0) * (H - T - B);
  const g = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img" });
  g.append(svg("line", { class: "axis", x1: L, x2: W - R, y1: sy(0), y2: sy(0) }));
  for (const v of [y0, (y0 + y1) / 2, y1])
    g.append(svg("text", { x: 4, y: sy(v) + 4 }, Math.round(v)));
  g.append(svg("text", { x: W - R, y: H - 6, "text-anchor": "end" }, xLabel || ""));
  series.forEach((s, i) => {
    const xs = xsOf(s);
    const d = s.ys.map((y, k) => `${k ? "L" : "M"}${sx(xs[k]).toFixed(1)},${sy(y).toFixed(1)}`).join("");
    const color = s.color || COLORS[i % COLORS.length];
    g.append(svg("path", { d, fill: "none", stroke: color, "stroke-width": 2 }));
    if (s.ys.length <= 30)  // few points (one per version): mark each one so a single point is visible
      s.ys.forEach((y, k) => g.append(svg("circle", { cx: sx(xs[k]), cy: sy(y), r: 4, fill: color })));
  });
  target.replaceChildren(g);
}

function legend(target, items) {
  target.replaceChildren(...items.map(([name, color]) => {
    const s = document.createElement("span");
    const i = document.createElement("i"); i.style.background = color;
    s.append(i, name); return s;
  }));
}

// groups: [{label, bars:[{name, value, lo, hi, color}]}]
function barChart(target, groups) {
  const bars = groups.flatMap((g) => g.bars);
  if (!bars.length) return empty(target, "Pas encore d'évaluation : lancez `python -m pokerbot ladder`.");
  const W = 640, H = 240, L = 48, R = 10, T = 10, B = 30;
  const vals = bars.flatMap((b) => [b.lo, b.hi, b.value, 0]).filter(Number.isFinite);
  let y0 = Math.min(...vals), y1 = Math.max(...vals);
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const sy = (y) => T + (y1 - y) / (y1 - y0) * (H - T - B);
  const g = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img" });
  g.append(svg("line", { class: "axis", x1: L, x2: W - R, y1: sy(0), y2: sy(0) }));
  for (const v of [y0, 0, y1]) g.append(svg("text", { x: 4, y: sy(v) + 4 }, Math.round(v)));
  const gw = (W - L - R) / groups.length;
  groups.forEach((grp, gi) => {
    const bw = Math.min(40, (gw - 16) / Math.max(1, grp.bars.length));
    grp.bars.forEach((b, bi) => {
      const x = L + gi * gw + 8 + bi * bw;
      const top = sy(Math.max(0, b.value)), bot = sy(Math.min(0, b.value));
      g.append(svg("rect", { x, y: top, width: bw - 4, height: Math.max(1, bot - top), fill: b.color, opacity: 0.85 }));
      const cx = x + (bw - 4) / 2;
      g.append(svg("line", { x1: cx, x2: cx, y1: sy(b.lo), y2: sy(b.hi), stroke: "currentColor", "stroke-width": 1.5 }));
    });
    g.append(svg("text", { x: L + gi * gw + gw / 2, y: H - 10, "text-anchor": "middle" }, grp.label));
  });
  target.replaceChildren(g);
}

function table(target, cols, rows) {
  if (!rows.length) return empty(target, "Pas encore de données.");
  const t = document.createElement("table");
  const head = t.createTHead().insertRow();
  for (const [, label] of cols) head.append(Object.assign(document.createElement("th"), { textContent: label, scope: "col" }));
  const body = t.createTBody();
  for (const r of rows) {
    const tr = body.insertRow();
    for (const [key] of cols) {
      const td = tr.insertCell();
      const v = r[key];
      td.textContent = v === null || v === undefined ? "–" : (typeof v === "boolean" ? (v ? "oui" : "") : v);
      if (typeof v !== "number") td.classList.add("text");
      if (key === "bb100" && typeof v === "number") td.classList.add(v >= 0 ? "win" : "loss");
    }
  }
  target.replaceChildren(t);
}

const DECISIONS = { promote: "monte", demote: "descend", stay: "reste", "": "" };

function render(d) {
  table(el("versions"), [["version", "Version"], ["iterations", "Itérations"], ["infosets", "Infosets"],
    ["train_minutes", "Entraînement (min)"], ["parent", "Parent"], ["level", "Niveau"],
    ["champion", "Champion"], ["best", "Meilleure"], ["created", "Créée le"]], d.versions);

  const all = d.evals.filter((e) => e.opponent === "ALL");
  const versions = [...new Set(all.map((e) => e.version))];
  const vColor = (v) => COLORS[versions.indexOf(v) % COLORS.length];
  const latest = {};
  for (const e of all) latest[`${e.version}|${e.level}`] = e;
  const groups = [1, 2, 3, 4].map((lvl) => ({ label: `N${lvl}`, bars: versions
    .filter((v) => latest[`${v}|${lvl}`])
    .map((v) => ({ name: v, value: latest[`${v}|${lvl}`].bb100, lo: latest[`${v}|${lvl}`].lo,
                   hi: latest[`${v}|${lvl}`].hi, color: vColor(v) })) })).filter((g) => g.bars.length);
  barChart(el("levels"), groups);
  legend(el("levels-legend"), versions.map((v) => [v, vColor(v)]));

  const lvls = [1, 2, 3, 4].filter((l) => versions.some((v) => latest[`${v}|${l}`]));
  const num = (v) => +v.replace("bot_v", "");
  lineChart(el("progress"), lvls.map((l, i) => {
    const pts = versions.filter((v) => latest[`${v}|${l}`]).sort((a, b) => num(a) - num(b));
    return { name: LEVEL_NAMES[l], xs: pts.map(num), ys: pts.map((v) => latest[`${v}|${l}`].bb100), color: COLORS[i] };
  }), "version");
  legend(el("progress-legend"), lvls.map((l, i) => [LEVEL_NAMES[l], COLORS[i]]));

  const pick = el("eval-pick");
  pick.replaceChildren(...d.evals.map((e, i) => Object.assign(document.createElement("option"), {
    value: i, textContent: `${e.version} · N${e.level} · ${e.opponent === "ALL" ? "tous adversaires" : e.opponent} · ${e.bb100} bb/100` })));
  const showCurve = () => {
    const e = d.evals[+pick.value];
    lineChart(el("eval-curve"), e ? [{ name: e.opponent, ys: e.curve }] : [], "donnes duplicate");
  };
  pick.onchange = showCurve;
  pick.value = Math.max(0, d.evals.length - 1);
  showCurve();

  table(el("evals"), [["ts", "Date"], ["version", "Version"], ["level", "Niveau"], ["opponent", "Adversaire"],
    ["hands", "Mains"], ["bb100", "bb/100"], ["lo", "IC bas"], ["hi", "IC haut"], ["decision", "Décision"]],
    d.evals.slice().reverse().map((e) => ({ ...e, opponent: e.opponent === "ALL" ? "TOUS" : e.opponent,
                                            decision: DECISIONS[e.decision] ?? e.decision })));

  lineChart(el("human-curve"), [{ name: "vous", ys: d.human_curve }], "mains");
  table(el("players"), [["name", "Joueur"], ["hands", "Mains"], ["bb100", "bb/100"], ["vpip", "VPIP"],
    ["pfr", "PFR"], ["3bet", "3-bet"], ["af", "AF"], ["cbet", "C-bet"], ["fold_to_cbet", "Fold c-bet"],
    ["wtsd", "WTSD"]], d.players);
}

if (window.DASHBOARD_DATA) render(window.DASHBOARD_DATA);
else fetch("/api/dashboard").then((r) => r.json()).then(render)
  .catch((e) => { el("status").textContent = `Impossible de charger les données : ${e.message}`; });
