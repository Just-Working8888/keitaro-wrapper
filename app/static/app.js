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
const deepLink = location.hash.match(/^#edit\/(\d+)/);
if (deepLink) {
  $('.tab[data-tab="edit"]').click();
  openCampaign(+deepLink[1]);
}
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
let CAMPAIGNS = [];
let STATE = null; // last editor state from the server

async function loadCampaigns() {
  try {
    CAMPAIGNS = await api("GET", "/api/campaigns");
    campaignsLoaded = true;
    $("#camp-list").innerHTML = CAMPAIGNS.map((c) => `<option value="#${c.id} ${esc(c.name)}">`).join("");
  } catch (err) {
    toast(err.message, true);
  }
}

function campaignFromInput() {
  const v = $("#camp-search").value.trim();
  const m = v.match(/^#?(\d+)/);
  return m ? +m[1] : null;
}

$("#camp-search").addEventListener("change", () => {
  const id = campaignFromInput();
  if (id) openCampaign(id);
});
$("#stream-select").addEventListener("change", () => STATE && openCampaign(STATE.campaign.id, +$("#stream-select").value));
$("#interval-select").addEventListener("change", () => STATE && openCampaign(STATE.campaign.id, STATE.stream_id));
$("#reload").addEventListener("click", () => {
  const id = (STATE && STATE.campaign.id) || campaignFromInput();
  if (id) openCampaign(id, STATE && STATE.stream_id);
});

async function openCampaign(id, streamId) {
  const q = new URLSearchParams({ interval: $("#interval-select").value || "7_days_ago" });
  if (streamId) q.set("stream_id", streamId);
  try {
    STATE = await api("GET", `/api/campaigns/${id}/editor?${q}`);
    const c = STATE.campaign;
    $("#camp-search").value = `#${c.id} ${c.name}`;
    history.replaceState(null, "", `#edit/${c.id}`);
    renderEditor();
    loadHistory();
  } catch (err) {
    toast(err.message, true);
  }
}

function renderEditor() {
  const s = STATE;
  $("#editor").classList.remove("hidden");
  $("#ed-title").textContent = `#${s.campaign.id} ${s.campaign.name}`;
  $("#ed-url").textContent = s.campaign.url;
  $("#ed-url").href = s.campaign.url;

  const ss = $("#stream-select");
  ss.innerHTML = s.streams.map((x) => `<option value="${x.id}" ${x.id === s.stream_id ? "selected" : ""}>#${x.id} ${esc(x.name)} (${x.offers_count})</option>`).join("");
  ss.disabled = s.streams.length < 2;

  const row = (o) => {
    const m = o.stats;
    return `<tr data-offer="${o.offer_id}">
      <td>${o.offer_id}</td>
      <td class="name">${esc(o.name)}${o.state !== "active" ? ` <span class="muted">(${esc(o.state)})</span>` : ""}</td>
      <td><input class="share-input" type="number" min="0" max="100" step="1" value="${o.share}" data-orig="${o.share}"></td>
      <td>${fmt.int(m.clicks)}</td><td>${fmt.int(m.campaign_unique_clicks)}</td><td>${fmt.int(m.conversions)}</td>
      <td>${fmt.pct(m.cr)}</td><td>${fmt.money(m.revenue)}</td><td>${fmt.money(m.cost)}</td>
      <td class="${signCls(m.profit)}">${fmt.money(m.profit)}</td><td class="${signCls(m.roi)}">${fmt.pct(m.roi)}</td><td>${fmt.epc(m.epc)}</td>
      <td><button class="danger" data-remove="${o.offer_id}" title="Удалить оффер">✕</button></td>
    </tr>`;
  };
  $("#offers-body").innerHTML = s.offers.length ? s.offers.map(row).join("")
    : `<tr><td colspan="13" class="left muted">В потоке нет офферов</td></tr>`;

  const t = s.totals;
  $("#offers-foot").innerHTML = `<tr>
    <td></td><td class="left">Итого: ${s.offers.length} офф.</td><td id="share-sum"></td>
    <td>${fmt.int(t.clicks)}</td><td>${fmt.int(t.campaign_unique_clicks)}</td><td>${fmt.int(t.conversions)}</td>
    <td>${fmt.pct(t.cr)}</td><td>${fmt.money(t.revenue)}</td><td>${fmt.money(t.cost)}</td>
    <td class="${signCls(t.profit)}">${fmt.money(t.profit)}</td><td class="${signCls(t.roi)}">${fmt.pct(t.roi)}</td><td>${fmt.epc(t.epc)}</td><td></td></tr>`;

  $("#add-select").innerHTML = s.available_offers.length
    ? s.available_offers.map((o) => `<option value="${o.id}">#${o.id} ${esc(o.name)}</option>`).join("")
    : `<option disabled>Все доступные офферы уже в потоке</option>`;
  $("#add-btn").disabled = !s.available_offers.length;
  refreshShares();
}

function currentShares() {
  const out = {};
  $$("#offers-body tr[data-offer]").forEach((tr) => {
    out[tr.dataset.offer] = parseInt($(".share-input", tr).value, 10) || 0;
  });
  return out;
}

function refreshShares() {
  const inputs = $$(".share-input");
  const sum = inputs.reduce((a, i) => a + (parseInt(i.value, 10) || 0), 0);
  const changed = inputs.some((i) => i.value !== i.dataset.orig);
  inputs.forEach((i) => i.classList.toggle("changed", i.value !== i.dataset.orig));
  const ok = sum === 100;
  const cell = $("#share-sum");
  if (cell) cell.innerHTML = `<span class="${ok ? "pos" : "neg"}">${sum}%</span>`;
  const badge = $("#share-badge");
  badge.className = "badge " + (ok ? "ok" : "bad");
  badge.textContent = ok ? (changed ? "Сумма 100% · не сохранено" : "Сумма долей 100%") : `Сумма долей ${sum}% (нужно 100)`;
  $("#save-shares").disabled = !(changed && ok);
}

$("#offers-body").addEventListener("input", (e) => e.target.classList.contains("share-input") && refreshShares());

$("#even-btn").addEventListener("click", () => {
  const inputs = $$(".share-input");
  const n = inputs.length;
  if (!n) return;
  const base = Math.floor(100 / n), rest = 100 % n; // same rule as the backend: 34/33/33
  inputs.forEach((i, idx) => (i.value = base + (idx < rest ? 1 : 0)));
  refreshShares();
});

async function mutate(promise, okMsg) {
  try {
    await promise;
    toast(okMsg);
    await openCampaign(STATE.campaign.id, STATE.stream_id);
  } catch (err) {
    toast(err.message, true);
  }
}

$("#save-shares").addEventListener("click", () =>
  mutate(api("PUT", `/api/campaigns/${STATE.campaign.id}/streams/${STATE.stream_id}/shares`, { shares: currentShares() }), "Доли сохранены"));

$("#add-btn").addEventListener("click", () => {
  const ids = $$("#add-select option:checked").map((o) => +o.value).filter(Boolean);
  if (!ids.length) return toast("Выберите офферы в списке (Cmd/Ctrl — несколько)", true);
  mutate(api("POST", `/api/campaigns/${STATE.campaign.id}/streams/${STATE.stream_id}/offers`, { offer_ids: ids }),
    `Добавлено офферов: ${ids.length}`);
});

$("#offers-body").addEventListener("click", (e) => {
  const b = e.target.closest("[data-remove]");
  if (!b) return;
  const id = b.dataset.remove;
  if (!confirm(`Удалить оффер #${id} из потока? Доли оставшихся будут поделены поровну.`)) return;
  mutate(api("DELETE", `/api/campaigns/${STATE.campaign.id}/streams/${STATE.stream_id}/offers/${id}`), `Оффер #${id} удалён`);
});

const ACTION_LABEL = { add: "добавлен", remove: "удалён", shares: "доли" };
async function loadHistory() {
  const list = await api("GET", `/api/campaigns/${STATE.campaign.id}/history`).catch(() => []);
  $("#history-card").classList.toggle("hidden", !list.length);
  const fmtShares = (o) => Object.entries(o).map(([k, v]) => `#${k}: ${v}%`).join(", ") || "—";
  $("#history").innerHTML = list.map((h) => `<div class="hist">
      <span class="tag ${h.action}">${ACTION_LABEL[h.action] || h.action}</span>
      ${h.action !== "shares" ? h.offer_ids.map((i) => "#" + i).join(", ") : ""}
      <span class="muted">поток #${h.stream_id} · ${new Date(h.created_at + "Z").toLocaleString("ru-RU")}</span><br>
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
