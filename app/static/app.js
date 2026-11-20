"use strict";

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    let msg = data && data.detail;
    if (Array.isArray(msg)) msg = msg.map((e) => e.msg.replace(/^Value error, /, "")).join("; ");
    throw new Error(msg || `HTTP ${res.status}`);
  }
  return data;
}

let toastTimer;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = ""), isErr ? 6000 : 3000);
}

const fmt = {
  int: (v) => Math.round(v).toLocaleString("ru-RU"),
  money: (v) => "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  pct: (v) => Number(v).toFixed(2) + "%",
  epc: (v) => "$" + Number(v).toFixed(4),
};
const signCls = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "");

/* ---------------- tabs ---------------- */
$$(".tab").forEach((b) =>
  b.addEventListener("click", () => {
    $$(".tab").forEach((x) => x.classList.toggle("active", x === b));
    $$(".panel").forEach((p) => p.classList.toggle("hidden", p.id !== "tab-" + b.dataset.tab));
    if (b.dataset.tab === "edit" && !campaignsLoaded) loadCampaigns();
  })
);

/* ---------------- meta ---------------- */
let META = null;

function fillSelect(sel, items, selected, label = (i) => `${i.name} (#${i.id})`) {
  sel.innerHTML = items.map((i) => `<option value="${i.id}" ${i.id === selected ? "selected" : ""}>${esc(label(i))}</option>`).join("");
}

async function loadMeta() {
  META = await api("GET", "/api/meta");
  const f = $("#create-form");
  fillSelect(f.offer_id, META.offers, null, (o) => `#${o.id} ${o.name}`);
  fillSelect(f.domain_id, META.domains, META.defaults.domain_id);
  fillSelect(f.group_id, META.groups, META.defaults.group_id);
  fillSelect(f.traffic_source_id, META.traffic_sources, META.defaults.traffic_source_id,
    (s) => `${s.name} (#${s.id})${s.state && s.state !== "active" ? " — " + s.state : ""}`);
  $("#interval-select").innerHTML = Object.entries(META.intervals)
    .map(([k, v]) => `<option value="${k}" ${k === "7_days_ago" ? "selected" : ""}>${esc(v)}</option>`).join("");
  $("#flow-url").textContent = META.geo_redirect_url;
  updateFlow();
}

/* ---------------- creator ---------------- */
function updateFlow() {
  const f = $("#create-form");
  $("#flow-geo").textContent = (f.country.value || "??").toUpperCase();
  $("#flow-offer").textContent = f.offer_id.value ? "#" + f.offer_id.value : "—";
}
$("#create-form").addEventListener("input", updateFlow);

$("#create-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const btn = $("button[type=submit]", f);
  const out = $("#create-result");
  btn.disabled = true;
  btn.textContent = "Создаю…";
  out.innerHTML = "";
  try {
    const c = await api("POST", "/api/campaigns", {
      name: f.name.value,
      country: f.country.value,
      offer_id: +f.offer_id.value,
      domain_id: +f.domain_id.value,
      group_id: +f.group_id.value,
      traffic_source_id: +f.traffic_source_id.value,
    });
    out.innerHTML = `<div class="result">
      Кампания <b>#${c.keitaro_id}</b> «${esc(c.name)}» создана.<br>
      Ссылка: <a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.url)}</a><br>
      Потоки: #${c.geo_stream_id} (${esc(c.country)} → Google), #${c.offer_stream_id} (оффер #${c.offer_id})<br>
      <a href="#" data-open="${c.keitaro_id}">Открыть в редакторе →</a></div>`;
    f.name.value = "";
    campaignsLoaded = false;
    loadCreated();
  } catch (err) {
    out.innerHTML = `<div class="result err">${esc(err.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Создать";
  }
});

async function loadCreated() {
  const box = $("#created-list");
  try {
    const list = await api("GET", "/api/campaigns/created");
    box.classList.toggle("muted", !list.length);
    box.innerHTML = list.length
      ? list.map((c) => `<div class="list-item">
          <div><b>#${c.keitaro_id}</b> ${esc(c.name)}<br>
            <span class="muted">${esc(c.country)} → Google · оффер #${c.offer_id} · ${new Date(c.created_at + "Z").toLocaleString("ru-RU")}</span></div>
          <div><a href="${esc(c.url)}" target="_blank" rel="noopener">ссылка</a> · <a href="#" data-open="${c.keitaro_id}">редактор</a></div>
        </div>`).join("")
      : "Пока ничего не создано";
  } catch (err) {
    box.textContent = err.message;
  }
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-open]");
  if (!a) return;
  e.preventDefault();
  $('.tab[data-tab="edit"]').click();
  openCampaign(+a.dataset.open);
});

/* ---------------- editor ---------------- */
let campaignsLoaded = false;
let STATE = null; // {campaign, streams}
let STATS = {}; // {streams: {sid: {oid: m}}, totals: {sid: m}}

async function loadCampaigns() {
  try {
    const list = await api("GET", "/api/campaigns");
    campaignsLoaded = true;
    $("#camp-list").innerHTML = list.map((c) => `<option value="#${c.id} ${esc(c.name)}">`).join("");
  } catch (err) {
    toast(err.message, true);
  }
  loadFetched();
}

async function loadFetched() {
  const list = await api("GET", "/api/campaigns/fetched").catch(() => []);
  $("#fetched").innerHTML = list.length
    ? "Загружены: " + list.map((c) => `<a href="#" data-load="${c.id}" class="${c.dirty ? "dirty-link" : ""}">#${c.id} ${esc(c.name)}</a>`).join(" · ")
    : "";
}

function campaignFromInput() {
  const m = $("#camp-search").value.trim().match(/^#?(\d+)/);
  return m ? +m[1] : null;
}

$("#fetch-btn").addEventListener("click", () => {
  const id = campaignFromInput();
  if (!id) return toast("Укажите ID кампании", true);
  fetchStreams(id);
});
$("#camp-search").addEventListener("keydown", (e) => e.key === "Enter" && $("#fetch-btn").click());
$("#fetched").addEventListener("click", (e) => {
  const a = e.target.closest("[data-load]");
  if (!a) return;
  e.preventDefault();
  openCampaign(+a.dataset.load);
});
$("#interval-select").addEventListener("change", () => STATE && loadStats());

async function fetchStreams(id) {
  const dirty = STATE && STATE.campaign.id === id && STATE.streams.some((s) => s.dirty);
  if (dirty && !confirm("Fetch загрузит состояние из Keitaro, неопубликованные изменения пропадут. Продолжить?")) return;
  const btn = $("#fetch-btn");
  btn.disabled = true;
  try {
    STATE = await api("POST", `/api/campaigns/${id}/fetch`);
    toast("Потоки загружены из Keitaro");
    showCampaign();
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
  }
}

// open from the local DB; fetch from Keitaro only if the campaign was never loaded
async function openCampaign(id) {
  try {
    STATE = await api("GET", `/api/campaigns/${id}/streams`);
    showCampaign();
  } catch (err) {
    fetchStreams(id);
  }
}

function showCampaign() {
  const c = STATE.campaign;
  $("#camp-search").value = `#${c.id} ${c.name}`;
  history.replaceState(null, "", `#edit/${c.id}`);
  $("#editor").classList.remove("hidden");
  $("#ed-title").textContent = `#${c.id} ${c.name}`;
  $("#ed-url").textContent = c.url;
  $("#ed-url").href = c.url;
  $("#ed-fetched").textContent = "Fetch: " + new Date(c.fetched_at + "Z").toLocaleString("ru-RU");
  renderStreams();
  loadStats();
  loadHistory();
  loadFetched();
}

async function loadStats() {
  try {
    STATS = await api("GET", `/api/campaigns/${STATE.campaign.id}/stats?interval=${$("#interval-select").value}`);
  } catch (err) {
    STATS = {};
  }
  renderStreams();
}

const ZERO = { clicks: 0, conversions: 0, cr: 0, revenue: 0, profit: 0, roi: 0 };
const statCells = (m) => `<td>${fmt.int(m.clicks)}</td><td>${fmt.int(m.conversions)}</td><td>${fmt.pct(m.cr)}</td>
  <td>${fmt.money(m.revenue)}</td><td class="${signCls(m.profit)}">${fmt.money(m.profit)}</td><td class="${signCls(m.roi)}">${fmt.pct(m.roi)}</td>`;

function renderStreams() {
  $("#streams").innerHTML = STATE.streams.map(renderStream).join("") || `<div class="card muted">В кампании нет потоков</div>`;
}

function renderStream(s) {
  if (!s.is_offer_stream) {
    return `<div class="stream plain"><span class="pos-n">${s.position}</span> <b>${esc(s.name)}</b>
      <span class="muted">#${s.id} · поток без офферов</span></div>`;
  }
  const st = (STATS.streams && STATS.streams[s.id]) || {};
  const rows = s.offers.map((o) => {
    const removed = o.state === "removed";
    const m = st[o.offer_id] || ZERO;
    const was = o.dirty && !o.is_new && o.published_share !== null && o.published_share !== o.share
      ? `<span class="was">было ${o.published_share}%</span>` : "";
    return `<tr class="${removed ? "removed" : ""} ${o.dirty ? "row-dirty" : ""}" data-offer="${o.offer_id}">
      <td>${o.offer_id}</td>
      <td class="name">${esc(o.name)} ${o.is_new ? '<span class="chip new">новый</span>' : ""}${removed ? '<span class="chip">removed</span>' : ""}</td>
      <td class="share-cell">
        ${removed ? "0%" : `<input class="share-input" type="number" min="0" max="100" value="${o.share}" data-orig="${o.share}">`}
        ${was}
      </td>
      <td>${removed ? "" : `<button class="pin ${o.pinned ? "on" : ""}" data-pin="${o.pinned ? 0 : 1}" title="${o.pinned ? "Открепить" : "Закрепить долю"}">📌</button>`}</td>
      ${statCells(m)}
      <td>${removed ? `<button class="ghost sm" data-restore>Bring back</button>` : `<button class="danger sm" data-remove>Remove</button>`}</td>
    </tr>`;
  }).join("");
  const ok = s.share_total === 100;
  const t = (STATS.totals && STATS.totals[s.id]) || ZERO;
  return `<div class="card stream ${s.dirty ? "dirty" : ""}" data-stream="${s.id}">
    <div class="stream-head">
      <div><span class="pos-n">${s.position}</span> <b>${esc(s.name)}</b> <span class="muted">#${s.id}</span>
        ${s.dirty ? '<span class="chip warn">не опубликовано</span>' : ""}</div>
      <div class="stream-actions">
        <button class="ghost" data-cancel ${s.dirty ? "" : "disabled"}>Cancel</button>
        <button class="primary" data-push ${s.dirty && ok ? "" : "disabled"}>Push stream</button>
      </div>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>ID</th><th class="left">Оффер</th><th>Доля</th><th></th>
        <th>Клики</th><th>Конв.</th><th>CR</th><th>Доход</th><th>Прибыль</th><th>ROI</th><th></th></tr></thead>
      <tbody>${rows || `<tr><td colspan="11" class="left muted">Офферов нет</td></tr>`}</tbody>
      <tfoot><tr><td></td><td class="left">Активных: ${s.active_count}</td>
        <td><span class="${ok ? "pos" : "neg"}">${s.share_total}%</span></td><td></td>${statCells(t)}<td></td></tr></tfoot>
    </table></div>
    <div class="add-offer">
      <input class="offer-search" placeholder="Добавить оффер: ID или название…" autocomplete="off">
      <div class="suggest hidden"></div>
    </div>
  </div>`;
}

async function streamAction(sid, method, url, body, okMsg) {
  try {
    const updated = await api(method, url, body);
    STATE.streams = STATE.streams.map((s) => (s.id === sid ? updated : s));
    renderStreams();
    if (okMsg) toast(okMsg);
    return updated;
  } catch (err) {
    toast(err.message, true);
    renderStreams(); // drop invalid inputs
  }
}

$("#streams").addEventListener("click", async (e) => {
  const card = e.target.closest("[data-stream]");
  if (!card) return;
  const sid = +card.dataset.stream;
  const tr = e.target.closest("[data-offer]");
  const oid = tr && +tr.dataset.offer;
  const base = `/api/streams/${sid}`;

  if (e.target.closest("[data-remove]")) streamAction(sid, "DELETE", `${base}/offers/${oid}`);
  else if (e.target.closest("[data-restore]")) streamAction(sid, "POST", `${base}/offers/${oid}/restore`);
  else if (e.target.closest("[data-pin]")) streamAction(sid, "PATCH", `${base}/offers/${oid}`, { pinned: e.target.closest("[data-pin]").dataset.pin === "1" });
  else if (e.target.closest("[data-cancel]")) streamAction(sid, "POST", `${base}/cancel`, null, "Изменения отменены");
  else if (e.target.closest("[data-push]")) {
    if (await streamAction(sid, "POST", `${base}/push`, null, "Опубликовано в Keitaro")) {
      loadHistory();
      loadFetched();
    }
  } else if (e.target.closest("[data-add]")) {
    const id = +e.target.closest("[data-add]").dataset.add;
    $(".offer-search", card).value = "";
    streamAction(sid, "POST", `${base}/offers`, { offer_id: id }, `Оффер #${id} добавлен (не опубликован)`);
  }
});

// manual share: commit on Enter / blur
$("#streams").addEventListener("change", (e) => {
  if (!e.target.classList.contains("share-input")) return;
  const sid = +e.target.closest("[data-stream]").dataset.stream;
  const oid = +e.target.closest("[data-offer]").dataset.offer;
  const share = parseInt(e.target.value, 10);
  if (Number.isNaN(share) || share < 0 || share > 100) {
    toast("Доля — целое число от 0 до 100", true);
    return renderStreams();
  }
  streamAction(sid, "PATCH", `/api/streams/${sid}/offers/${oid}`, { share });
});

// offer search with suggestions (debounced, goes to our API -> Keitaro)
let searchTimer;
$("#streams").addEventListener("input", (e) => {
  if (!e.target.classList.contains("offer-search")) return;
  const input = e.target;
  const box = input.nextElementSibling;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    const q = input.value.trim();
    if (!q) return box.classList.add("hidden");
    const card = input.closest("[data-stream]");
    const stream = STATE.streams.find((s) => s.id === +card.dataset.stream);
    const active = new Set(stream.offers.filter((o) => o.state === "active").map((o) => o.offer_id));
    try {
      const found = await api("GET", `/api/offers/search?q=${encodeURIComponent(q)}`);
      box.innerHTML = found.length
        ? found.map((o) => active.has(o.id)
            ? `<div class="sg disabled">#${o.id} ${esc(o.name)} <span class="muted">— уже в потоке</span></div>`
            : `<div class="sg" data-add="${o.id}">#${o.id} ${esc(o.name)}</div>`).join("")
        : `<div class="sg disabled">Ничего не найдено</div>`;
      box.classList.remove("hidden");
    } catch (err) {
      toast(err.message, true);
    }
  }, 250);
});
document.addEventListener("click", (e) => {
  if (!e.target.closest(".add-offer")) $$(".suggest").forEach((b) => b.classList.add("hidden"));
});

async function loadHistory() {
  const list = await api("GET", `/api/campaigns/${STATE.campaign.id}/history`).catch(() => []);
  $("#history-card").classList.toggle("hidden", !list.length);
  const fmtShares = (o) => Object.entries(o).map(([k, v]) => `#${k}: ${v}%`).join(", ") || "—";
  $("#history").innerHTML = list.map((h) => `<div class="hist">
      <span class="tag shares">push</span> поток #${h.stream_id}
      <span class="muted">· ${new Date(h.created_at + "Z").toLocaleString("ru-RU")}</span><br>
      <span class="muted">было:</span> ${esc(fmtShares(h.before))} → <span class="muted">стало:</span> ${esc(fmtShares(h.after))}
    </div>`).join("");
}

/* ---------------- boot ---------------- */
loadMeta().catch((err) => toast("Не удалось загрузить справочники: " + err.message, true));
loadCreated();
const deepLink = location.hash.match(/^#edit\/(\d+)/);
if (deepLink) {
  $('.tab[data-tab="edit"]').click();
  openCampaign(+deepLink[1]);
}
