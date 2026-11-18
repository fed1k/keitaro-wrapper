"use strict";

const $ = (s, r = document) => r.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const COLORS = ["#4caf50", "#1e73be", "#f39c12", "#9b59b6", "#e74c3c", "#16a085", "#7f8c8d"];
const ACTIONS = { add: "добавлен оффер", remove: "удалён оффер", reweight: "изменены доли" };
const FILTER_MODE = { accept: "принимать", reject: "отклонять" };

let META = null;

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    let msg = data?.detail ?? res.statusText;
    if (Array.isArray(msg)) msg = msg.map((e) => e.msg.replace(/^Value error, /, "")).join("; ");
    if (typeof msg !== "string") msg = JSON.stringify(msg);
    throw new Error(msg);
  }
  return data;
}

function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = isErr ? "err" : "";
  t.hidden = false;
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.hidden = true), isErr ? 6000 : 2500);
}

/* ---------- Offer autocomplete (reused by creator and editor) ---------- */
function offerAutocomplete(root, onPick, exclude = () => []) {
  const input = $("input", root);
  const list = $(".ac-list", root);
  let items = [], hl = -1, timer = null, seq = 0;

  const render = () => {
    const skip = new Set(exclude());
    const shown = items.filter((o) => !skip.has(o.id));
    list.innerHTML = shown.length
      ? shown.map((o, i) => `<li data-id="${o.id}" class="${i === hl ? "hl" : ""}"><small>[${o.id}]</small> ${esc(o.name)}</li>`).join("")
      : `<li class="muted">Ничего не найдено</li>`;
    list.hidden = false;
    items = shown;
  };
  const search = async () => {
    const my = ++seq;
    try {
      const res = await api(`/api/offers?q=${encodeURIComponent(input.value)}&limit=20`);
      if (my !== seq) return;
      items = res; hl = -1; render();
    } catch (e) { toast(e.message, true); }
  };
  const pick = (o) => { if (!o) return; list.hidden = true; onPick(o, input); };

  input.addEventListener("focus", search);
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(search, 200); });
  input.addEventListener("keydown", (e) => {
    if (list.hidden) return;
    if (e.key === "ArrowDown") { hl = Math.min(hl + 1, items.length - 1); render(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { hl = Math.max(hl - 1, 0); render(); e.preventDefault(); }
    else if (e.key === "Enter") { e.preventDefault(); pick(items[hl >= 0 ? hl : 0]); }
    else if (e.key === "Escape") list.hidden = true;
  });
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li[data-id]");
    if (li) { e.preventDefault(); pick(items.find((o) => o.id === +li.dataset.id)); }
  });
  input.addEventListener("blur", () => setTimeout(() => (list.hidden = true), 150));
}

/* ---------------------------- Creator ---------------------------- */
const geo = [];
let selectedOffer = null;

function renderGeo() {
  const box = $("#geo-tags");
  box.querySelectorAll(".tag").forEach((t) => t.remove());
  const input = $("#geo-input");
  geo.forEach((code) => {
    const t = document.createElement("span");
    t.className = "tag";
    t.innerHTML = `${code}<button type="button" title="Убрать">×</button>`;
    t.querySelector("button").onclick = () => { geo.splice(geo.indexOf(code), 1); renderGeo(); };
    box.insertBefore(t, input);
  });
}

function addGeo(raw) {
  for (let part of raw.split(/[,\s;]+/)) {
    part = part.trim();
    if (!part) continue;
    const up = part.toUpperCase();
    const c = META.countries.find((x) => x.code === up || x.name.toLowerCase() === part.toLowerCase() || `${x.code} — ${x.name}`.toLowerCase() === part.toLowerCase());
    if (!c) { toast(`Неизвестная страна: ${part}`, true); continue; }
    if (!geo.includes(c.code)) geo.push(c.code);
  }
  renderGeo();
}

function initCreator() {
  $("#prefix").textContent = META.prefix;
  $("#countries").innerHTML = META.countries.map((c) => `<option value="${c.code} — ${esc(c.name)}">`).join("");
  const gi = $("#geo-input");
  gi.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addGeo(gi.value.split(" — ")[0]); gi.value = ""; }
    if (e.key === "Backspace" && !gi.value && geo.length) { geo.pop(); renderGeo(); }
  });
  gi.addEventListener("change", () => { if (gi.value.includes(" — ")) { addGeo(gi.value.split(" — ")[0]); gi.value = ""; } });

  offerAutocomplete($("#offer-ac"), (o, input) => { selectedOffer = o; input.value = `[${o.id}] ${o.name}`; });
  $("#offer-input").addEventListener("input", () => (selectedOffer = null));

  $("#create-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const gi2 = $("#geo-input");
    if (gi2.value.trim()) { addGeo(gi2.value.split(" — ")[0]); gi2.value = ""; }
    const out = $("#create-result");
    const name = e.target.name.value.trim();
    if (!geo.length) return (out.innerHTML = `<div class="result error">Укажите хотя бы одну страну</div>`);
    if (!selectedOffer) return (out.innerHTML = `<div class="result error">Выберите оффер из списка</div>`);
    const btn = e.target.querySelector("button[type=submit]");
    btn.disabled = true; btn.textContent = "Создаю…";
    try {
      const c = await api("/api/campaigns", { method: "POST", body: { name, geo, offer_id: selectedOffer.id } });
      out.innerHTML = `<div class="result">
        ✅ Кампания <b>${esc(c.name)}</b> (ID ${c.keitaro_id}) создана.<br>
        Ссылка: <code>${esc(c.url)}</code><br>
        Поток 1: ${esc(c.geo.join(", "))} → Google · Поток 2: оффер ${c.initial_offer_id} (100%)<br>
        <a href="/campaigns/${c.keitaro_id}">Открыть в редакторе →</a></div>`;
      e.target.reset(); geo.length = 0; renderGeo(); selectedOffer = null;
    } catch (err) {
      out.innerHTML = `<div class="result error">${esc(err.message)}</div>`;
    } finally {
      btn.disabled = false; btn.textContent = "Create";
    }
  });
}

/* ---------------------------- List ---------------------------- */
let listTimer = null;
async function loadList() {
  const body = $("#list-body");
  body.innerHTML = `<tr><td colspan="5" class="muted">Загрузка…</td></tr>`;
  try {
    const q = encodeURIComponent($("#list-q").value);
    const rows = await api(`/api/campaigns?scope=${$("#list-scope").value}&q=${q}`);
    body.innerHTML = rows.length
      ? rows.map((c) => `<tr><td>${c.id}</td><td>${esc(c.name)}${c.created_here ? ' <span class="tag">создана здесь</span>' : ""}</td>
          <td>${esc(c.group || "—")}</td><td>${esc(c.state)}</td><td><a href="/campaigns/${c.id}">Редактировать →</a></td></tr>`).join("")
      : `<tr><td colspan="5" class="muted">Кампаний нет. <a href="/">Создать</a></td></tr>`;
  } catch (e) {
    body.innerHTML = `<tr><td colspan="5" class="error">${esc(e.message)}</td></tr>`;
  }
}

function initList() {
  $("#list-scope").onchange = loadList;
  $("#list-q").oninput = () => { clearTimeout(listTimer); listTimer = setTimeout(loadList, 300); };
}

/* ---------------------------- Editor ---------------------------- */
let EDIT = null; // {id, data}

const statCells = (s) => `<td class="num">${s.clicks}</td><td class="num">${s.unique}</td><td class="num">${s.bots}</td><td class="num">${s.conversions}</td>`;

function streamHtml(s) {
  const filters = s.filters.map((f) => {
    const what = f.name === "country" ? "Страны" : f.name;
    const val = Array.isArray(f.payload) ? f.payload.map((c) => (f.name === "country" ? (META.countries.find((x) => x.code === c)?.name ?? c) : c)).join(", ") : JSON.stringify(f.payload);
    return `<div class="filter">${esc(what)} ${FILTER_MODE[f.mode] || f.mode} «${esc(val)}»</div>`;
  }).join("");
  const action = s.schema === "redirect" || (!s.editable && s.action_payload) ? `<div>${esc(s.action_payload || "")}</div>` : "";
  let offers = "";
  if (s.editable) {
    const bar = s.offers.map((o, i) => `<i style="width:${o.share}%;background:${COLORS[i % COLORS.length]}"></i>`).join("");
    offers = `<div class="muted" style="margin-top:6px">Офферы</div>
      <div class="share-bar">${bar}</div>
      <ul class="offers">${s.offers.map((o, i) => `
        <li data-offer="${o.offer_id}">
          <span class="dot" style="background:${COLORS[i % COLORS.length]}"></span>
          <span class="oname">[${o.offer_id}] ${esc(o.name)}</span>
          <span class="ostat">${o.stats.clicks} кл · ${o.stats.unique} уник · ${o.stats.conversions} конв</span>
          <input class="share" type="number" min="0" max="100" value="${o.share}" aria-label="Доля, %"> %
          <button class="icon-btn" data-remove="${o.offer_id}" title="Удалить оффер" ${s.offers.length < 2 ? "disabled" : ""}>×</button>
        </li>`).join("") || `<li class="muted">Офферов нет</li>`}
      </ul>
      <div class="stream-tools">
        <div class="ac"><input placeholder="+ Добавить оффер: поиск по названию или ID"><ul class="ac-list" hidden></ul></div>
        <button class="btn small" data-even>Поровну</button>
        <span class="sum muted"></span>
        <button class="btn small primary" data-save disabled>Сохранить доли</button>
      </div>`;
  }
  return `<tr data-stream="${s.id}">
    <td><div class="stream-name"><span class="dot ${s.state === "active" ? "" : "off"}"></span>${esc(s.name)}</div>
      ${action}${filters ? `<div class="muted" style="margin-top:6px">Фильтры</div>${filters}` : ""}${offers}</td>
    ${statCells(s.stats)}</tr>`;
}

function bindStream(tr, s) {
  if (!s.editable) return;
  const inputs = [...tr.querySelectorAll("input.share")];
  const sumEl = $(".sum", tr), saveBtn = $("[data-save]", tr);
  const original = Object.fromEntries(s.offers.map((o) => [o.offer_id, o.share]));
  const current = () => Object.fromEntries(inputs.map((i) => [+i.closest("li").dataset.offer, parseInt(i.value || "0", 10)]));
  const refresh = () => {
    const cur = current();
    const sum = Object.values(cur).reduce((a, b) => a + b, 0);
    const changed = Object.keys(cur).some((k) => cur[k] !== original[k]);
    sumEl.textContent = `Сумма: ${sum}%`;
    sumEl.classList.toggle("bad", sum !== 100);
    saveBtn.disabled = !changed || sum !== 100;
  };
  inputs.forEach((i) => i.addEventListener("input", refresh));
  refresh();

  $("[data-even]", tr).onclick = () => {
    const n = inputs.length, base = Math.floor(100 / n), rest = 100 - base * n;
    inputs.forEach((inp, idx) => (inp.value = base + (idx < rest ? 1 : 0)));
    refresh();
  };
  saveBtn.onclick = () => mutate(saveBtn, () => api(`/api/campaigns/${EDIT.id}/streams/${s.id}/shares`, { method: "PUT", body: { shares: current() } }), "Доли сохранены");

  tr.querySelectorAll("[data-remove]").forEach((b) => {
    b.onclick = () => {
      const oid = +b.dataset.remove;
      if (!confirm(`Удалить оффер ${oid} из потока? Доли остальных будут выровнены.`)) return;
      mutate(b, () => api(`/api/campaigns/${EDIT.id}/streams/${s.id}/offers/${oid}`, { method: "DELETE" }), `Оффер ${oid} удалён`);
    };
  });

  offerAutocomplete($(".ac", tr), (o, input) => {
    input.value = "";
    mutate(input, () => api(`/api/campaigns/${EDIT.id}/streams/${s.id}/offers`, { method: "POST", body: { offer_id: o.id } }), `Оффер ${o.id} добавлен`);
  }, () => s.offers.map((o) => o.offer_id));
}

async function mutate(el, fn, okMsg) {
  el.disabled = true;
  try { await fn(); toast(okMsg); await loadEditor(); }
  catch (e) { toast(e.message, true); el.disabled = false; }
}

async function loadEditor() {
  const interval = $("#ed-interval").value;
  try {
    const [d, events] = await Promise.all([
      api(`/api/campaigns/${EDIT.id}?interval=${interval}`),
      api(`/api/campaigns/${EDIT.id}/events`),
    ]);
    EDIT.data = d;
    document.title = `${d.name} — Keitaro Wrapper`;
    $("#ed-name").textContent = d.name;
    $("#ed-id").textContent = d.id;
    $("#ed-group").textContent = d.group || "—";
    $("#ed-url").textContent = d.url;
    const body = $("#ed-streams");
    body.innerHTML = d.streams.map(streamHtml).join("") || `<tr><td colspan="5" class="muted">Потоков нет</td></tr>`;
    d.streams.forEach((s) => bindStream(body.querySelector(`tr[data-stream="${s.id}"]`), s));
    $("#ed-total").innerHTML = `<td>Итого</td>${statCells(d.total)}`;
    $("#ed-events").innerHTML = events.length
      ? events.map((e) => `<li>${new Date(e.created_at).toLocaleString("ru")} — поток ${e.stream_id}: ${ACTIONS[e.action] || e.action}${e.offer_id ? " " + e.offer_id : ""}
          → ${Object.entries(e.shares_after).map(([k, v]) => `${k}: ${v}%`).join(", ")}</li>`).join("")
      : `<li class="muted">Изменений через этот сервис ещё не было</li>`;
  } catch (e) {
    $("#ed-name").textContent = "Ошибка";
    $("#ed-streams").innerHTML = `<tr><td colspan="5" class="error">${esc(e.message)}</td></tr>`;
  }
}

function initEditor() {
  $("#ed-interval").onchange = loadEditor;
  $("#ed-refresh").onclick = loadEditor;
  $("#ed-copy").onclick = () => navigator.clipboard?.writeText($("#ed-url").textContent).then(() => toast("Скопировано"));
}

/* ---------------------------- Routing ---------------------------- */
function route() {
  const m = location.pathname.match(/^\/campaigns\/(\d+)/);
  const view = m ? "edit" : location.hash === "#list" ? "list" : "create";
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== `view-${view}`));
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === view || (view === "edit" && a.dataset.nav === "list")));
  if (view === "list") loadList();
  if (view === "edit") { EDIT = { id: +m[1] }; loadEditor(); }
}

(async function boot() {
  try { META = await api("/api/meta"); }
  catch (e) { toast(`Не удалось загрузить настройки: ${e.message}`, true); return; }
  initCreator(); initList(); initEditor();
  window.addEventListener("hashchange", route);
  route();
})();
