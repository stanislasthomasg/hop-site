const $ = (id) => document.getElementById(id);
const SUITS = { c: "♣", d: "♦", h: "♥", s: "♠" };
let snap = null;

async function api(path, body) {
  if (window.pokerApi) {                 // static site: the game runs in the browser (Pyodide)
    const { status, body: data } = await window.pokerApi(path, body);
    if (status !== 200) throw new Error(data.error || `erreur ${status}`);
    return data;
  }
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function cardEl(c) {
  const d = document.createElement("span");
  if (!c) { d.className = "card back"; d.setAttribute("aria-label", "carte cachée"); return d; }
  const rank = c[0] === "T" ? "10" : c[0];
  d.className = "card" + ("dh".includes(c[1]) ? " red" : "");
  d.textContent = rank + SUITS[c[1]];
  return d;
}

const bb = (x) => `${+(x / snap.bb).toFixed(2)} bb`;

function render() {
  if (!snap || snap.phase === "idle") return;
  const s = snap.session;
  $("session").textContent = `${s.hands} mains · ${s.net_bb >= 0 ? "+" : ""}${s.net_bb} bb · ${s.bb100} bb/100`;
  const seats = $("seats"); seats.replaceChildren();
  for (const p of snap.seats) {
    const el = document.createElement("div");
    el.className = "seat" + (p.to_act ? " to-act" : "") + (p.folded ? " folded" : "");
    const name = document.createElement("div"); name.className = "name";
    name.textContent = `${p.name} · ${p.position}${p.seat === snap.button ? " (bouton)" : ""}`;
    const cards = document.createElement("div"); cards.className = "cards";
    if (!p.folded || p.cards) (p.cards || [null, null]).forEach((c) => cards.append(cardEl(c)));
    const info = document.createElement("div");
    let txt = `Tapis ${bb(p.stack)}`;
    if (p.bet) txt += ` · mise ${bb(p.bet)}`;
    if (p.all_in) txt += " · tapis !";
    if (p.folded) txt += " · couché";
    if (p.net !== null) txt += ` · ${p.net >= 0 ? "+" : ""}${bb(p.net)}`;
    info.textContent = txt;
    el.append(name, cards, info);
    seats.append(el);
  }
  $("board").replaceChildren(...snap.board.map(cardEl));
  $("pot").textContent = `Pot : ${bb(snap.pot)} · ${snap.street}`;
  $("log").replaceChildren(...snap.log.map((l) => Object.assign(document.createElement("p"), { textContent: l })));
  if (snap.explanations.length) {
    $("why").replaceChildren(...snap.explanations.map((e) => {
      const d = document.createElement("div"); d.className = "why";
      const a = document.createElement("strong"); a.textContent = e.action;
      const p = document.createElement("pre"); p.textContent = e.why;
      d.append(a, p); return d;
    }));
  }
  renderControls();
  const over = snap.phase === "over";
  $("history-panel").hidden = !over;
  if (over) $("history").textContent = snap.history_text;
}

function button(label, onClick, primary) {
  const b = document.createElement("button");
  b.textContent = label; if (primary) b.className = "primary";
  b.addEventListener("click", onClick); return b;
}

function renderControls() {
  const c = $("controls"); c.replaceChildren();
  if (snap.phase === "over") {
    const r = snap.result_bb;
    const msg = document.createElement("strong");
    msg.className = r >= 0 ? "win" : "loss";
    msg.textContent = `Main terminée : ${r >= 0 ? "+" : ""}${r} bb`;
    c.append(msg, button("Main suivante", () => send("/api/new_hand", {}), true));
    return;
  }
  const la = snap.legal;
  if (!la) { c.append(Object.assign(document.createElement("span"), { textContent: "Les bots réfléchissent…", className: "muted" })); return; }
  if (la.fold) c.append(button("Se coucher", () => act({ type: "fold" })));
  c.append(la.check ? button("Checker", () => act({ type: "check" }), true)
                    : button(`Suivre ${bb(la.call_amount)}`, () => act({ type: "call" }), true));
  if (la.raise) {
    const potAfter = la.pot + la.call_amount;
    for (const [label, f] of [["½ pot", 0.5], ["Pot", 1], ["2× pot", 2]]) {
      const to = Math.round(la.current_bet + f * potAfter);
      if (to >= la.min_raise_to && to < la.max_raise_to)
        c.append(button(`${label} (${bb(to)})`, () => act({ type: "raise", amount: to })));
    }
    const lab = document.createElement("label");
    lab.textContent = "Relancer à (bb) ";
    const input = document.createElement("input");
    Object.assign(input, { type: "number", step: "0.5", min: la.min_raise_to / snap.bb,
      max: la.max_raise_to / snap.bb, value: la.min_raise_to / snap.bb });
    input.style.width = "90px";
    lab.append(input);
    c.append(lab, button("Relancer", () => act({ type: "raise", amount: Math.round(+input.value * snap.bb) })),
             button(`Tapis (${bb(la.max_raise_to)})`, () => act({ type: "raise", amount: la.max_raise_to })));
  }
}

let busy = false;
async function send(path, body) {
  if (busy) return;                       // ignore double clicks while a request is running
  busy = true;
  document.querySelectorAll("#controls button, #start").forEach((b) => { b.disabled = true; });
  $("status").textContent = "";
  try { snap = await api(path, body); }
  catch (e) { $("status").textContent = e.message; }
  finally {
    busy = false;
    $("start").disabled = false;
    render();
  }
}
const act = (a) => send("/api/act", a);

$("start").addEventListener("click", () =>
  send("/api/new_session", { opponents: $("opponents").value.split(",") }));
if (!window.PYODIDE_URL)  // local server: resume the current session; static site starts fresh
  api("/api/state").then((s) => { snap = s; render(); }).catch(() => {});
