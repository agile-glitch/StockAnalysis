"use strict";

/* ------------------------------------------------------------------ *
 * Small DOM helpers. Everything is built with textContent, never
 * innerHTML, because headlines and names come from outside sources.
 * ------------------------------------------------------------------ */
const SVG_NS = "http://www.w3.org/2000/svg";

function append(node, kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

function h(spec, attrs, ...kids) {
  const [tag, ...classes] = spec.split(".");
  const node = document.createElement(tag || "div");
  if (classes.length) node.className = classes.join(" ");
  if (attrs instanceof Node || typeof attrs !== "object" || attrs === null || Array.isArray(attrs)) {
    kids.unshift(attrs);
  } else {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (key === "class") node.className += " " + value;
      else if (key in node && key !== "list") node[key] = value;
      else node.setAttribute(key, value);
    }
  }
  return append(node, kids);
}

function s(tag, attrs, ...kids) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value !== null && value !== undefined) node.setAttribute(key, value);
  }
  return append(node, kids);
}

const $ = (id) => document.getElementById(id);

/** Replace a node's children; accepts nested arrays and skips null/false. */
function fill(node, ...kids) {
  node.replaceChildren();
  return append(node, kids);
}

/* ------------------------------ formatting ------------------------------ */
const fmt = {
  money(x, digits = 2) {
    if (x === null || x === undefined) return "—";
    const sign = x < 0 ? "-" : "";
    return sign + "$" + Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  },
  money0: (x) => fmt.money(x, 0),
  compact(x) {
    if (x === null || x === undefined) return "—";
    const a = Math.abs(x);
    for (const [size, suffix] of [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]]) {
      if (a >= size) return (x < 0 ? "-" : "") + "$" + (a / size).toFixed(1) + suffix;
    }
    return fmt.money0(x);
  },
  num(x, digits = 0) {
    if (x === null || x === undefined) return "—";
    return x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  },
  pct(x, digits = 1) {
    if (x === null || x === undefined) return "—";
    return (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(digits) + "%";
  },
  signed(x) {
    return (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(Math.round(x));
  },
  date(iso) {
    if (!iso) return "—";
    const d = new Date(iso.slice(0, 10) + "T12:00:00");
    const opts = { month: "short", day: "numeric" };
    if (d.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
    return d.toLocaleDateString("en-US", opts);
  },
  ago(epoch) {
    if (!epoch) return "";
    const sec = Math.max(0, Date.now() / 1000 - epoch);
    if (sec < 90) return "just now";
    if (sec < 3600) return Math.round(sec / 60) + " min ago";
    if (sec < 86400) return Math.round(sec / 3600) + " h ago";
    return Math.round(sec / 86400) + " d ago";
  },
  inDays(n) {
    if (n === null || n === undefined) return "";
    if (n === 0) return "today";
    if (n === 1) return "tomorrow";
    return n > 0 ? "in " + n + " days" : Math.abs(n) + " days ago";
  },
};

const titleCase = (text) => (text || "").toLowerCase().replace(/(^|[\s\-'])([a-z])/g, (m, a, b) => a + b.toUpperCase());
const signClass = (x) => (x > 0 ? "up" : x < 0 ? "down" : "");
const TONE_GLYPH = { bullish: "▲", bearish: "▼", neutral: "●", warning: "!", info: "i" };

/* ------------------------------ API ------------------------------ */
async function api(path, options = {}) {
  const init = { method: options.method || "GET", headers: {} };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  const res = await fetch(path, init);
  let data = null;
  try { data = await res.json(); } catch (e) { /* empty body */ }
  if (!res.ok) {
    const detail = data && data.detail;
    throw new Error(typeof detail === "string" ? detail : "Request failed (" + res.status + ")");
  }
  return data;
}

/* ------------------------------ state ------------------------------ */
const state = {
  overview: null,
  lastNotificationId: null,
  page: null,          // the mounted page: { refresh? }
  backtests: {},
  prefs: {
    get desktop() { try { return localStorage.getItem("desktopAlerts") === "1"; } catch (e) { return false; } },
    set desktop(v) { try { localStorage.setItem("desktopAlerts", v ? "1" : "0"); } catch (e) { /* private mode */ } },
  },
};

/* ------------------------------ components ------------------------------ */
function pill(direction, label, large) {
  return h("span.pill." + direction + (large ? ".large" : ""), h("span", { "aria-hidden": "true" }, TONE_GLYPH[direction] || "●"), label);
}

function toneIcon(tone) {
  return h("div.tone-icon." + (tone || "info"), { "aria-hidden": "true" }, TONE_GLYPH[tone] || "i");
}

/** Diverging meter: value in [-max, max], zero at the centre. */
function meter(value, max = 100, label) {
  const share = Math.min(1, Math.abs(value) / max) * 50;
  const fill = h("div.meter-fill." + (value >= 0 ? "pos" : "neg"));
  fill.style.width = share + "%";
  return h("div.meter", { title: label || "" },
    h("div.meter-track", fill),
    h("span.num", fmt.signed(value)));
}

function sparkline(values, width = 72, height = 26) {
  const pts = (values || []).filter((v) => v !== null);
  if (pts.length < 2) return h("span.muted", "—");
  const min = Math.min(...pts), max = Math.max(...pts), span = max - min || 1;
  const x = (i) => 2 + (i / (pts.length - 1)) * (width - 6);
  const y = (v) => 3 + (1 - (v - min) / span) * (height - 6);
  const d = pts.map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1)).join(" ");
  const change = (pts[pts.length - 1] / pts[0] - 1) * 100;
  const svg = s("svg", { class: "spark", width, height, viewBox: `0 0 ${width} ${height}`, role: "img",
    "aria-label": "60-day price trend, " + fmt.pct(change) },
    s("path", { d, fill: "none", stroke: "var(--muted)", "stroke-width": 1.5, "stroke-linejoin": "round", "stroke-linecap": "round" }),
    s("circle", { cx: x(pts.length - 1), cy: y(pts[pts.length - 1]), r: 2.5, fill: "var(--accent)" }));
  return svg;
}

function niceTicks(min, max, count = 4) {
  const span = max - min || 1;
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v >= raw) || raw;
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-6; v += step) ticks.push(v);
  return ticks;
}

/**
 * Line chart with a shared y-axis, a legend (two or more series), and a
 * crosshair tooltip. series: [{ name, color (CSS var), values, emphasis }]
 */
function lineChart({ dates, series, height = 280, yFormat = fmt.money, label }) {
  const wrap = h("div.chart");
  const tooltip = h("div.tooltip", { hidden: true });
  const holder = h("div");
  wrap.append(holder, tooltip);

  function draw(width) {
    if (!width) return;
    const m = { l: 6, r: 58, t: 10, b: 24 };
    const pw = width - m.l - m.r, ph = height - m.t - m.b;
    const all = series.flatMap((se) => se.values).filter((v) => v !== null && v !== undefined);
    if (!all.length) return;
    let lo = Math.min(...all), hi = Math.max(...all);
    const pad = (hi - lo || hi || 1) * 0.06;
    lo -= pad; hi += pad;
    const n = dates.length;
    const x = (i) => m.l + (n > 1 ? (i / (n - 1)) * pw : pw / 2);
    const y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * ph;

    const svg = s("svg", { viewBox: `0 0 ${width} ${height}`, width, height, role: "img", "aria-label": label || "Line chart" });
    for (const tick of niceTicks(lo, hi)) {
      svg.append(
        s("line", { x1: m.l, x2: m.l + pw, y1: y(tick), y2: y(tick), stroke: "var(--grid)", "stroke-width": 1 }),
        s("text", { x: m.l + pw + 8, y: y(tick) + 4 }, yFormat(tick, tick >= 1000 ? 0 : 2)));
    }
    // Month labels, thinned so they never collide.
    let lastX = -Infinity, lastYear = null;
    for (let i = 1; i < n; i++) {
      const month = dates[i].slice(0, 7);
      if (month === dates[i - 1].slice(0, 7) || x(i) - lastX < 62 || x(i) > m.l + pw - 24) continue;
      const d = new Date(dates[i] + "T12:00:00");
      const year = d.getFullYear();
      const text = d.toLocaleDateString("en-US", { month: "short" }) + (year !== lastYear ? " ’" + String(year).slice(2) : "");
      lastYear = year;
      svg.append(s("text", { x: x(i), y: height - 6, "text-anchor": "middle" }, text));
      lastX = x(i);
    }
    svg.append(s("line", { x1: m.l, x2: m.l + pw, y1: m.t + ph, y2: m.t + ph, stroke: "var(--axis)", "stroke-width": 1 }));

    for (const se of series) {
      let d = "", pen = false;
      se.values.forEach((v, i) => {
        if (v === null || v === undefined) { pen = false; return; }
        d += (pen ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1) + " ";
        pen = true;
      });
      svg.append(s("path", { d, fill: "none", stroke: se.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    }
    const lead = series[0];
    const lastIndex = lead.values.length - 1;
    if (lead.values[lastIndex] !== null) {
      svg.append(s("circle", { cx: x(lastIndex), cy: y(lead.values[lastIndex]), r: 4, fill: lead.color, stroke: "var(--surface)", "stroke-width": 2 }));
    }

    const cross = s("line", { y1: m.t, y2: m.t + ph, stroke: "var(--axis)", "stroke-width": 1, visibility: "hidden" });
    const dots = series.map((se) => s("circle", { r: 4, fill: se.color, stroke: "var(--surface)", "stroke-width": 2, visibility: "hidden" }));
    svg.append(cross, ...dots);

    const hit = s("rect", { x: m.l, y: m.t, width: pw, height: ph, fill: "transparent" });
    function move(event) {
      const box = svg.getBoundingClientRect();
      const px = event.clientX - box.left;
      const i = Math.max(0, Math.min(n - 1, Math.round(((px - m.l) / pw) * (n - 1))));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      fill(tooltip, h("div.t-date", fmt.date(dates[i])));
      series.forEach((se, k) => {
        const v = se.values[i];
        if (v === null || v === undefined) { dots[k].setAttribute("visibility", "hidden"); return; }
        dots[k].setAttribute("cx", x(i)); dots[k].setAttribute("cy", y(v)); dots[k].setAttribute("visibility", "visible");
        const swatch = h("i"); swatch.style.background = se.color;
        tooltip.append(h("div.t-row", h("span", swatch, se.name), h("span.num", yFormat(v))));
      });
      tooltip.hidden = false;
      const tw = tooltip.offsetWidth;
      const left = x(i) + 14 + tw > width ? x(i) - 14 - tw : x(i) + 14;
      tooltip.style.left = Math.max(0, left) + "px";
      tooltip.style.top = m.t + "px";
    }
    function leave() {
      cross.setAttribute("visibility", "hidden");
      dots.forEach((dot) => dot.setAttribute("visibility", "hidden"));
      tooltip.hidden = true;
    }
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", leave);
    svg.append(hit);
    fill(holder, svg);
  }

  new ResizeObserver(() => draw(wrap.clientWidth)).observe(wrap);

  const legend = series.length > 1
    ? h("div.legend", series.map((se) => { const key = h("i"); key.style.background = se.color; return h("span", key, se.name); }))
    : null;
  return { node: wrap, legend };
}

function dataTable(columns, rows, options = {}) {
  if (!rows.length) return h("div.empty", options.empty || "Nothing to show yet.");
  return h("div.table-wrap", h("table",
    h("thead", h("tr", columns.map((c) => h("th" + (c.right ? ".r" : "") + (c.hideSmall ? ".hide-sm" : ""), c.label)))),
    h("tbody", rows.map((row) => {
      const tr = h("tr" + (options.onRow ? ".click" : ""), columns.map((c) =>
        h("td" + (c.right ? ".r.num" : "") + (c.hideSmall ? ".hide-sm" : ""), c.cell(row))));
      if (options.onRow) tr.addEventListener("click", (e) => { if (!e.target.closest("button, a")) options.onRow(row); });
      return tr;
    }))));
}

function card(title, subtitle, ...body) {
  return h("section.card", h("div.card-head", h("h2", title), subtitle ? h("p", subtitle) : null), body);
}

function modal(title, body, actions) {
  const root = $("modal-root");
  const close = () => { fill(root); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  const box = h("div.modal", { role: "dialog", "aria-modal": "true", "aria-label": title }, h("h2", title), body, h("div.actions", actions(close)));
  const backdrop = h("div.modal-backdrop", { onclick: (e) => { if (e.target === backdrop) close(); } }, box);
  fill(root, backdrop);
  const first = box.querySelector("input");
  if (first) { first.focus(); first.select(); }
  return close;
}

function safeLink(url, text) {
  if (url && /^https?:\/\//i.test(url)) return h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, text);
  return h("span", text);
}

/* ------------------------------ shell ------------------------------ */
const NAV = [
  ["dashboard", "Dashboard"],
  ["alerts", "Alerts"],
  ["news", "News"],
  ["earnings", "Earnings"],
  ["insiders", "Insider trades"],
  ["positions", "Positions"],
  ["guide", "Strategy guide"],
  ["settings", "Settings"],
];

function renderSidebar() {
  const current = (location.hash.slice(2).split("/")[0]) || "dashboard";
  const unread = state.overview ? state.overview.unread : 0;
  fill($("sidebar"), 
    h("div.brand",
      s("svg", { width: 26, height: 26, viewBox: "0 0 32 32", "aria-hidden": "true" },
        s("rect", { width: 32, height: 32, rx: 7, fill: "var(--accent)" }),
        s("path", { d: "M6 22l6-7 5 4 9-11", fill: "none", stroke: "#fff", "stroke-width": 3, "stroke-linecap": "round", "stroke-linejoin": "round" })),
      "StockAnalysis"),
    NAV.map(([key, label]) => h("a.nav-link" + ((current === key || (key === "dashboard" && current === "stock")) ? ".active" : ""),
      { href: "#/" + key }, label, key === "alerts" && unread ? h("span.badge", unread > 99 ? "99+" : unread) : null)),
    h("div.sidebar-foot", h("button.btn.ghost.small", { onclick: toggleTheme }, "Switch theme")));
}

function toggleTheme() {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("theme", root.dataset.theme); } catch (e) { /* private mode */ }
}

let bellOpen = false;

function renderTopbar() {
  const o = state.overview;
  if (!o) return;
  const status = o.status;
  const statusText = status.scanning ? "Updating…" : status.last_scan ? "Updated " + fmt.ago(status.last_scan) : "Waiting for first update";
  const bell = h("div.pop-anchor",
    h("button.btn.icon-btn", { "aria-label": "Alerts, " + o.unread + " unread", onclick: (e) => { e.stopPropagation(); bellOpen = !bellOpen; renderTopbar(); } },
      s("svg", { width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" },
        s("path", { d: "M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" }), s("path", { d: "M10.3 21a1.94 1.94 0 0 0 3.4 0" })),
      o.unread ? h("span.badge", o.unread > 99 ? "99+" : o.unread) : null));
  if (bellOpen) {
    const pop = h("div.popover", { onclick: (e) => e.stopPropagation() }, h("div.muted.small", { style: "padding:8px 0" }, "Loading…"));
    bell.append(pop);
    api("/api/notifications?limit=8").then((data) => {
      fill(pop, 
        data.items.length ? data.items.map((n) => notificationItem(n, () => { bellOpen = false; })) : h("div.empty", "No alerts yet."),
        h("div.row", { style: "justify-content:space-between;padding-top:8px" },
          h("a", { href: "#/alerts", onclick: () => { bellOpen = false; renderTopbar(); } }, "View all alerts"),
          data.unread ? h("button.btn.small.ghost", { onclick: async () => { await api("/api/notifications/read", { method: "POST", body: {} }); await refreshOverview(); } }, "Mark all read") : null));
    });
  }

  fill($("topbar"), 
    h("button.btn.budget-chip", { onclick: budgetModal, title: "Change your budget" },
      h("span.k", "Budget"), h("span.v.num", fmt.money0(o.budget.total))),
    h("div.budget-chip", h("span.k", "Available"), h("span.v.num", fmt.money0(o.budget.available))),
    h("span.spacer"),
    h("span.row.small.soft", h("span.status-dot" + (status.scanning ? ".busy" : "")), statusText),
    h("button.btn", { disabled: status.scanning, onclick: async () => { await api("/api/scan", { method: "POST" }); state.overview.status.scanning = true; renderTopbar(); setTimeout(poll, 1500); } }, "Refresh"),
    bell);

  const banner = $("banner");
  if (o.demo) {
    banner.hidden = false;
    banner.textContent = "Demo mode: prices, news and filings are simulated. Start without --demo for live market data.";
  } else if (status.last_error) {
    banner.hidden = false;
    banner.textContent = "Some data could not be updated (" + status.last_error + "). Showing the last good values.";
  } else {
    banner.hidden = true;
  }
}

document.addEventListener("click", () => { if (bellOpen) { bellOpen = false; renderTopbar(); } });

function budgetModal() {
  const settings = state.overview.settings;
  const input = h("input", { type: "number", min: 1, step: 100, value: settings.budget, inputMode: "decimal" });
  const error = h("div.error-text", { hidden: true });
  const body = h("div.stack", { style: "margin-top:12px" },
    h("p.soft", "The total you are willing to trade with. Share counts, stops and options ideas are all sized from it."),
    h("div.field", h("label", { htmlFor: "budget-input" }, "Budget"), h("div.input-affix", h("span", "$"), Object.assign(input, { id: "budget-input" }))),
    error,
    h("a.small", { href: "#/settings", onclick: () => fill($("modal-root")) }, "More risk settings"));
  const save = async (close) => {
    try {
      await api("/api/settings", { method: "PUT", body: { budget: Number(input.value) } });
      close();
      await refreshOverview();
      mountRoute();
    } catch (e) { error.hidden = false; error.textContent = e.message; }
  };
  modal("Change budget", body, (close) => {
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") save(close); });
    return [h("button.btn", { onclick: close }, "Cancel"), h("button.btn.primary", { onclick: () => save(close) }, "Save budget")];
  });
}

/* ------------------------------ notifications ------------------------------ */
function notificationItem(n, onOpen) {
  const open = async () => {
    if (!n.read) { await api("/api/notifications/read", { method: "POST", body: { ids: [n.id] } }); refreshOverview(); }
    if (onOpen) onOpen();
    if (n.symbol) location.hash = "#/stock/" + n.symbol;
  };
  return h("div.feed-item" + (n.read ? "" : ".unread"), { style: "cursor:pointer", onclick: open },
    toneIcon(n.tone),
    h("div.f-main", h("div.f-title", n.title), h("div.f-body", n.body), h("div.f-meta", fmt.ago(n.created_at))));
}

function toast(n) {
  const node = h("div.toast", { role: "status", onclick: () => { node.remove(); if (n.symbol) location.hash = "#/stock/" + n.symbol; } },
    toneIcon(n.tone), h("div.f-main", h("div.f-title", n.title), h("div.f-body", n.body)));
  $("toasts").append(node);
  while ($("toasts").children.length > 4) $("toasts").firstChild.remove();
  setTimeout(() => node.remove(), 12000);
}

function desktopNotify(n) {
  if (!state.prefs.desktop || !("Notification" in window) || Notification.permission !== "granted") return;
  try {
    const note = new Notification(n.title, { body: n.body, tag: "stockanalysis-" + n.id });
    note.onclick = () => { window.focus(); if (n.symbol) location.hash = "#/stock/" + n.symbol; };
  } catch (e) { /* some browsers only allow service-worker notifications */ }
}

async function checkNotifications() {
  if (state.lastNotificationId === null) {
    const data = await api("/api/notifications?limit=1");
    state.lastNotificationId = data.items.length ? data.items[0].id : 0;
    return;
  }
  const data = await api("/api/notifications?after_id=" + state.lastNotificationId + "&limit=20");
  if (!data.items.length) return;
  state.lastNotificationId = data.items[0].id;
  const fresh = data.items.slice().reverse();
  fresh.slice(-4).forEach(toast);
  fresh.forEach(desktopNotify);
  if (fresh.length > 4) toast({ title: (fresh.length - 4) + " more alerts", body: "Open Alerts to see them all.", tone: "info" });
}

/* ------------------------------ pages ------------------------------ */
function pageHead(title, subtitle, ...right) {
  return h("div.page-head", h("div", h("h1", title), subtitle ? h("p", subtitle) : null), h("div.row", right));
}

/* ---- dashboard ---- */
function dashboardPage(root) {
  const tiles = h("div.tiles");
  const tableHost = h("div");
  const error = h("div.error-text", { hidden: true });
  const input = h("input.input", { placeholder: "Add a ticker, e.g. AMD", "aria-label": "Ticker symbol", autocomplete: "off", style: "width:220px" });
  const suggestions = h("div.suggestions", { hidden: true });
  let searchTimer = null;

  async function add(symbol) {
    symbol = (symbol || input.value).trim().toUpperCase();
    if (!symbol) return;
    error.hidden = true;
    suggestions.hidden = true;
    addBtn.disabled = true; addBtn.textContent = "Adding…";
    try {
      await api("/api/watchlist", { method: "POST", body: { symbol } });
      input.value = "";
      await refreshOverview();
    } catch (e) { error.hidden = false; error.textContent = e.message; }
    addBtn.disabled = false; addBtn.textContent = "Add to watchlist";
  }

  input.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); if (e.key === "Escape") suggestions.hidden = true; });
  input.addEventListener("input", () => {
    clearTimeout(searchTimer);
    const q = input.value.trim();
    if (q.length < 2) { suggestions.hidden = true; return; }
    searchTimer = setTimeout(async () => {
      try {
        const hits = await api("/api/search?q=" + encodeURIComponent(q));
        if (input.value.trim() !== q) return;
        fill(suggestions, hits.map((hit) => h("button", { onclick: () => add(hit.symbol) }, h("span.sym", hit.symbol), h("span.muted", hit.name))));
        suggestions.hidden = !hits.length;
      } catch (e) { suggestions.hidden = true; }
    }, 250);
  });
  input.addEventListener("blur", () => setTimeout(() => { suggestions.hidden = true; }, 200));
  const addBtn = h("button.btn.primary", { onclick: () => add() }, "Add to watchlist");

  fill(root, 
    pageHead("Dashboard", "Your watchlist, scored by the trading rules and sized to your budget.",
      h("div.search-wrap", input, suggestions), addBtn),
    error, h("div.stack", tiles, h("section.card", tableHost)));

  function refresh() {
    const o = state.overview;
    if (!o) return;
    const live = o.watchlist.filter((w) => !w.error && !w.pending);
    const buys = live.filter((w) => w.direction === "bullish").length;
    const sells = live.filter((w) => w.direction === "bearish").length;
    const soon = live.filter((w) => w.earnings_days !== null && w.earnings_days >= 0 && w.earnings_days <= 7).length;
    const tile = (label, value, sub) => h("div.tile", h("div.label", label), h("div.value.num", value), sub ? h("div.sub", sub) : null);
    fill(tiles, 
      tile("Budget", fmt.money0(o.budget.total), fmt.money0(o.budget.invested) + " in positions"),
      tile("Available to trade", fmt.money0(o.budget.available), "Risk per trade " + fmt.money0(o.budget.total * o.settings.risk_per_trade_pct / 100)),
      tile("Buy signals", buys, "of " + live.length + " watched"),
      tile("Sell signals", sells, "of " + live.length + " watched"),
      tile("Earnings this week", soon, soon ? "Expect big moves" : "None scheduled"));

    const columns = [
      { label: "Stock", cell: (w) => h("div", h("div.sym", w.symbol, w.held ? h("span.tag", { style: "margin-left:6px" }, "Held") : null), h("div.sym-name", w.name || "")) },
      { label: "Price", right: true, cell: (w) => (w.error || w.pending ? "—" : fmt.money(w.price)) },
      { label: "Today", right: true, cell: (w) => (w.error || w.pending ? "—" : h("span." + (signClass(w.change_pct) || "soft"), fmt.pct(w.change_pct, 2))) },
      { label: "60 days", hideSmall: true, cell: (w) => (w.spark ? sparkline(w.spark) : "") },
      { label: "Signal", cell: (w) => (w.error ? h("span.pill.warning", "! No data") : w.pending ? h("span.muted", "Loading…") : pill(w.direction, w.action_label)) },
      { label: "Score", cell: (w) => (w.error || w.pending ? "" : meter(w.score, 100, "Score from −100 (sell) to +100 (buy)")) },
      { label: "Main reason", hideSmall: true, cell: (w) => h("div.why.small", w.error || w.gate_note || w.reason || "") },
      { label: "Suggested trade", hideSmall: true, cell: (w) => suggestion(w) },
      { label: "Next earnings", hideSmall: true, cell: (w) => (w.next_earnings ? h("div", h("div.nowrap", fmt.date(w.next_earnings)),
          h("div.small" + (w.earnings_days <= 7 ? "" : ".muted"), w.earnings_days <= 7 ? h("span.pill.warning", "! " + fmt.inDays(w.earnings_days)) : fmt.inDays(w.earnings_days))) : h("span.muted", "—")) },
      { label: "", cell: (w) => h("button.btn.ghost.small", { title: "Remove " + w.symbol, "aria-label": "Remove " + w.symbol,
          onclick: async () => { await api("/api/watchlist/" + w.symbol, { method: "DELETE" }); refreshOverview(); } }, "✕") },
    ];
    fill(tableHost, dataTable(columns, o.watchlist, {
      empty: "Your watchlist is empty. Add a ticker above to start.",
      onRow: (w) => { location.hash = "#/stock/" + w.symbol; },
    }));
  }

  function suggestion(w) {
    if (w.error || w.pending) return "";
    if (w.direction === "bullish") {
      return h("div.small.nowrap", h("div", w.held ? "Hold your position" : w.shares ? "Buy " + fmt.num(w.shares) + " shares" : "Stock: over budget"), w.option ? h("div.muted", "or " + w.option.toLowerCase()) : null);
    }
    if (w.direction === "bearish") {
      return h("div.small.nowrap", h("div", w.held ? "Sell your position" : "Avoid buying"), w.option ? h("div.muted", "or " + w.option.toLowerCase()) : null);
    }
    return h("span.small.muted", w.option ? w.option : "Wait");
  }

  refresh();
  return { refresh };
}

/* ---- stock detail ---- */
function stockPage(root, symbol) {
  let loadedAt = 0;

  async function load() {
    let a;
    try {
      a = await api("/api/stock/" + encodeURIComponent(symbol));
    } catch (e) {
      fill(root, pageHead(symbol, null, h("a.btn", { href: "#/dashboard" }, "Back")), h("div.card", h("div.empty", e.message)));
      return;
    }
    loadedAt = a.as_of;
    const keepScroll = window.scrollY;
    render(a);
    window.scrollTo(0, keepScroll);
  }

  function render(a) {
    const watched = state.overview && state.overview.watchlist.some((w) => w.symbol === a.symbol);
    const head = h("div.page-head",
      h("div",
        h("div.row", h("h1", a.symbol), pill(a.direction, a.action_label, true), a.position ? h("span.tag", "Held") : null, a.stale ? h("span.pill.warning", "! Out of date") : null),
        h("p", a.name, a.quote.sector ? " · " + a.quote.sector : "")),
      h("div", { style: "text-align:right" },
        h("div.num", { style: "font-size:26px;font-weight:650" }, fmt.money(a.price)),
        h("div.num." + (signClass(a.change_pct) || "soft"), fmt.pct(a.change_pct, 2) + " today")));

    const actions = h("div.row", { style: "margin-bottom:16px" },
      h("a.btn.small", { href: "#/dashboard" }, "← Dashboard"),
      watched ? null : h("button.btn.small.primary", { onclick: async () => { await api("/api/watchlist", { method: "POST", body: { symbol: a.symbol } }); await refreshOverview(); load(); } }, "Add to watchlist"),
      h("button.btn.small", { onclick: () => positionModal(a, load) }, a.position ? "Edit position" : "Record a position"));

    fill(root, head, actions,
      a.problems && a.problems.length ? h("div.note.warn", { style: "margin-bottom:16px" }, "Some data is missing: " + a.problems.join("; ")) : null,
      h("div.stack",
        h("div.grid-main",
          h("div.stack", chartCard(a), signalsCard(a), newsCard(a)),
          h("div.stack", planCard(a), optionsCard(a), earningsCard(a), insidersCard(a))),
        backtestCard(a.symbol)));
  }

  function chartCard(a) {
    const chart = lineChart({
      dates: a.chart.dates,
      label: a.symbol + " price with 50-day and 200-day averages",
      series: [
        { name: "Price", color: "var(--series-1)", values: a.chart.close },
        { name: "50-day average", color: "var(--series-2)", values: a.chart.sma50 },
        { name: "200-day average", color: "var(--series-3)", values: a.chart.sma200 },
      ],
    });
    const tableHost = h("div", { hidden: true });
    const toggle = h("button.btn.ghost.small", { onclick: () => {
      tableHost.hidden = !tableHost.hidden;
      toggle.textContent = tableHost.hidden ? "Show data table" : "Hide data table";
      if (!tableHost.hidden && !tableHost.firstChild) {
        const rows = a.chart.dates.map((d, i) => ({ d, c: a.chart.close[i], s50: a.chart.sma50[i], s200: a.chart.sma200[i] })).slice(-20).reverse();
        tableHost.append(dataTable([
          { label: "Date", cell: (r) => fmt.date(r.d) },
          { label: "Close", right: true, cell: (r) => fmt.money(r.c) },
          { label: "50-day avg", right: true, cell: (r) => fmt.money(r.s50) },
          { label: "200-day avg", right: true, cell: (r) => fmt.money(r.s200) },
        ], rows));
      }
    } }, "Show data table");
    const st = a.stats;
    return h("section.card",
      h("div.card-head", h("h2", "Price, past year"), chart.legend),
      chart.node,
      h("div.metrics", { style: "margin-top:12px" },
        metric("52-week high", fmt.money(st.high_52w)), metric("52-week low", fmt.money(st.low_52w)),
        metric("14-day RSI", st.rsi14 === null ? "—" : fmt.num(st.rsi14)), metric("Volatility (30d)", st.hv30 === null ? "—" : fmt.num(st.hv30 * 100) + "%"),
        a.quote.market_cap ? metric("Market cap", fmt.compact(a.quote.market_cap)) : null,
        a.quote.analyst_target ? metric("Analyst target", fmt.money(a.quote.analyst_target)) : null),
      h("div", { style: "margin-top:8px" }, toggle), tableHost);
  }

  function metric(k, v) { return h("div.metric", h("div.k", k), h("div.v", v)); }

  function signalsCard(a) {
    return card("Why " + a.action_label.toLowerCase() + "?", "Score " + fmt.signed(a.score) + " of ±100",
      a.gate_note ? h("div.note.warn", { style: "margin-bottom:6px" }, a.gate_note) : null,
      a.signals.map((sig) => h("div.signal" + (sig.available ? "" : ".off"),
        h("div", h("div.s-name", sig.name), h("div.muted.small", "up to ±" + sig.weight)),
        sig.available ? meter(sig.points, sig.weight, sig.name + " contributes " + fmt.signed(sig.points) + " points") : h("span.muted.small", "No data"),
        h("div", h("div", sig.headline), sig.detail ? h("div.s-detail", sig.detail) : null))));
  }

  function planCard(a) {
    const p = a.plan;
    const rows = [];
    const add = (k, v) => rows.push(h("dt", k), h("dd", v));
    if (a.direction === "bullish" && !a.position) {
      add("Buy", p.shares ? fmt.num(p.shares) + " shares" : "0 shares");
      add("Entry near", fmt.money(p.entry));
      add("Cost", fmt.money(p.cost) + (p.pct_of_budget ? " (" + p.pct_of_budget + "% of budget)" : ""));
    }
    if (p.stop !== undefined) {
      add("Stop loss", fmt.money(p.stop) + " (−" + p.stop_pct + "%)");
      if (a.direction === "bullish" && !a.position) add("First target", fmt.money(p.target) + " (+" + p.target_pct + "%)");
      if (p.trailing_stop) add("Trailing stop", fmt.money(p.trailing_stop));
      if (a.direction === "bullish" && p.shares) add("Loss if stopped", fmt.money(p.risk_amount));
    }
    if (p.holding) {
      add("You hold", fmt.num(p.holding.shares, p.holding.shares % 1 ? 2 : 0) + " shares at " + fmt.money(p.holding.entry_price));
      add("Position value", fmt.money(p.holding.value));
      rows.push(h("dt", "Profit / loss"), h("dd." + signClass(p.holding.pnl), fmt.money(p.holding.pnl) + " (" + fmt.pct(p.holding.pnl_pct) + ")"));
    }
    const title = a.direction === "bullish" ? (a.position ? "Your position" : "Stock trade plan") : a.direction === "bearish" ? (a.position ? "Exit plan" : "Stock: stay out") : "Stock: no trade";
    return card(title, "Budget " + fmt.money0(p.budget) + " · " + fmt.money0(p.cash_available) + " free",
      rows.length ? h("dl.kv", rows) : null,
      h("div", { style: "margin-top:10px" }, (p.notes || []).map((n) => h("div.note", n))));
  }

  function optionsCard(a) {
    const o = a.options;
    const sub = o.atm_iv ? "Implied vol " + fmt.num(o.atm_iv * 100) + "% vs " + fmt.num(o.hv30 * 100) + "% realised" : null;
    const regime = { rich: "Options are expensive right now", cheap: "Options are cheap right now", normal: null }[o.iv_regime];
    return card("Options: calls and puts", sub,
      regime ? h("div.note", { style: "margin-bottom:8px" }, regime + " (implied volatility is " + o.iv_hv_ratio + "× what the stock has actually been doing).") : null,
      (o.notes || []).map((n) => h("div.note", { style: "margin-bottom:8px" }, n)),
      (o.ideas || []).map(ideaBlock),
      o.risk_budget ? h("p.muted.small", { style: "margin-top:10px" }, "Sized to risk at most " + fmt.money0(o.risk_budget) + " per options trade. ", h("a", { href: "#/settings" }, "Change")) : null);
  }

  function ideaBlock(idea) {
    const credit = idea.net_cost < 0;
    return h("div.idea",
      h("div.idea-head", pill(idea.direction, idea.strategy), idea.primary ? h("span.tag", "Top pick") : h("span.tag", "Alternative"),
        h("span.muted.small", "Expires " + fmt.date(idea.expiry) + " · " + idea.dte + " days")),
      dataTable([
        { label: "", cell: (l) => h("span", { style: "font-weight:650;text-transform:capitalize" }, l.action) },
        { label: "Contract", cell: (l) => h("span.nowrap", "$" + l.strike + " " + l.type) },
        { label: "Price", right: true, cell: (l) => fmt.money(l.price) },
        { label: "Delta", right: true, cell: (l) => l.delta.toFixed(2) },
        { label: "IV", right: true, cell: (l) => fmt.num(l.iv * 100) + "%" },
        { label: "Open int.", right: true, hideSmall: true, cell: (l) => fmt.num(l.open_interest) },
      ], idea.legs),
      h("div.metrics", { style: "margin-top:10px" },
        metric(idea.cost_label, fmt.money0(Math.abs(idea.net_cost)) + (credit ? " credit" : "")),
        metric("Contracts", idea.affordable ? idea.contracts : "0 (over budget)"),
        metric("Max loss", idea.max_loss === null ? "Stock risk" : fmt.money0(idea.max_loss)),
        metric("Max profit", idea.max_profit === null ? "Unlimited" : fmt.money0(idea.max_profit)),
        metric("Breakeven", fmt.money(idea.breakeven)),
        idea.collateral ? metric("Cash set aside", fmt.money0(idea.collateral)) : null),
      h("div", { style: "margin-top:10px" }, idea.warnings.map((w) => h("div.note.warn", h("span", { "aria-hidden": "true" }, "!"), w))),
      h("ul.small", idea.rationale.map((r) => h("li", r)), h("li", h("strong", "Exit: "), idea.exit_plan)));
  }

  function newsCard(a) {
    const tone = a.sentiment;
    return card("News", tone.count ? tone.positive + " positive · " + tone.negative + " negative this week" : null,
      a.news.length ? a.news.map((n) => newsItem(n)) : h("div.empty", "No recent headlines."));
  }

  function earningsCard(a) {
    const e = a.earnings;
    const history = e.history.filter((r) => r.eps_actual !== null).slice(0, 6);
    return card("Earnings", e.next_date ? "Next: " + fmt.date(e.next_date) + " (" + fmt.inDays(e.days_until) + ")" : "No date scheduled",
      e.days_until !== null && e.days_until >= 0 && e.days_until <= 7
        ? h("div.note.warn", { style: "margin-bottom:8px" }, h("span", { "aria-hidden": "true" }, "!"), "Reports " + fmt.inDays(e.days_until) + ". Expect a large move; avoid buying options right before it.") : null,
      dataTable([
        { label: "Reported", cell: (r) => fmt.date(r.date) },
        { label: "Expected", right: true, cell: (r) => (r.eps_estimate === null ? "—" : fmt.money(r.eps_estimate)) },
        { label: "Actual", right: true, cell: (r) => fmt.money(r.eps_actual) },
        { label: "Surprise", right: true, cell: (r) => (r.surprise_pct === null ? "—" : h("span." + signClass(r.surprise_pct), fmt.pct(r.surprise_pct))) },
      ], history, { empty: "No earnings history for this symbol." }));
  }

  function insidersCard(a) {
    const sum = a.insiders.summary;
    const trades = a.insiders.trades.filter((t) => t.kind !== "other").slice(0, 8);
    return card("Insider trades", "Last " + sum.window_days + " days: " + sum.buyers.length + " buyers, " + sum.sellers.length + " sellers",
      a.insiders.available ? insiderTable(trades, false, true) : h("div.empty", "Insider filings are unavailable for this symbol."));
  }

  function backtestCard(sym) {
    const body = h("div", h("div.skeleton"));
    const section = card("How these timing rules did on " + sym, "Price rules only, replayed day by day", body);
    const show = (b) => {
      if (!b.available) { fill(body, h("div.empty", b.reason)); return; }
      const chart = lineChart({
        dates: b.curve.dates, height: 220, label: "Growth of 100 dollars: rules versus buy and hold",
        yFormat: (v) => "$" + Math.round(v).toLocaleString("en-US"),
        series: [
          { name: "Following the rules", color: "var(--series-1)", values: b.curve.strategy },
          { name: "Buy and hold", color: "var(--series-2)", values: b.curve.buy_hold },
        ],
      });
      fill(body, 
        h("div.metrics", { style: "margin-bottom:12px" },
          metric("Rules: return", fmt.pct(b.strategy_return_pct)), metric("Buy & hold: return", fmt.pct(b.buy_hold_return_pct)),
          metric("Rules: worst drop", fmt.pct(b.strategy_max_drawdown_pct)), metric("Buy & hold: worst drop", fmt.pct(b.buy_hold_max_drawdown_pct)),
          metric("Trades", b.trades), metric("Winning trades", b.win_rate_pct === null ? "—" : b.win_rate_pct + "%"),
          metric("Time invested", b.time_in_market_pct + "%")),
        chart.legend, h("div", { style: "margin-top:8px" }, chart.node),
        h("p.muted.small", { style: "margin-top:10px" },
          "Growth of $100 from " + fmt.date(b.start) + " to " + fmt.date(b.end) + ". Trend rules usually trail buy-and-hold in strong bull markets and " +
          "earn their keep by sidestepping the deep declines. This ignores trading costs and taxes, and past results do not predict future ones."));
    };
    if (state.backtests[sym]) show(state.backtests[sym]);
    else api("/api/stock/" + sym + "/backtest").then((b) => { state.backtests[sym] = b; show(b); }).catch((e) => fill(body, h("div.empty", e.message)));
    return section;
  }

  fill(root, h("div.stack", h("div.skeleton"), h("div.skeleton")));
  load();
  return {
    refresh() {
      const w = state.overview && state.overview.watchlist.find((x) => x.symbol === symbol);
      if (w && w.as_of && w.as_of > loadedAt + 1 && !$("modal-root").firstChild) load();
    },
  };
}

function positionModal(a, done) {
  const pos = a.position;
  const field = (label, id, value, prefix, hint) => {
    const input = h("input", { id, type: "number", step: "any", min: 0, value: value === null || value === undefined ? "" : value, inputMode: "decimal" });
    return { input, node: h("div.field", h("label", { htmlFor: id }, label), h("div.input-affix", prefix ? h("span", prefix) : null, input), hint ? h("div.hint", hint) : null) };
  };
  const shares = field("Shares", "pos-shares", pos ? pos.shares : a.plan.shares || "", null);
  if (!shares.input.previousSibling) shares.input.style.paddingLeft = "10px";
  const entry = field("Price paid per share", "pos-entry", pos ? pos.entry_price : a.price, "$");
  const stop = field("Stop loss", "pos-stop", pos && pos.stop !== null ? pos.stop : a.plan.stop, "$", "You get a sell alert if the price closes at or below this.");
  const error = h("div.error-text", { hidden: true });
  const body = h("div.stack", { style: "margin-top:12px" },
    h("p.soft", "Tell the app what you own so it can send sell alerts and subtract the cost from your available budget."),
    shares.node, entry.node, stop.node, error);
  modal((pos ? "Edit" : "Record") + " position in " + a.symbol, body, (close) => [
    pos ? h("button.btn", { style: "margin-right:auto", onclick: async () => { await api("/api/positions/" + a.symbol, { method: "DELETE" }); close(); await refreshOverview(); done(); } }, "Close position") : null,
    h("button.btn", { onclick: close }, "Cancel"),
    h("button.btn.primary", { onclick: async () => {
      try {
        await api("/api/positions", { method: "POST", body: {
          symbol: a.symbol, shares: Number(shares.input.value), entry_price: Number(entry.input.value),
          stop: stop.input.value === "" ? null : Number(stop.input.value) } });
        close(); await refreshOverview(); done();
      } catch (e) { error.hidden = false; error.textContent = /greater than/.test(e.message) ? e.message : "Enter the number of shares and the price paid."; }
    } }, "Save position"),
  ]);
}

function newsItem(n, withSymbol) {
  const tone = n.tone === "positive" ? "bullish" : n.tone === "negative" ? "bearish" : "neutral";
  return h("div.feed-item", toneIcon(tone),
    h("div.f-main",
      h("div.f-title", safeLink(n.url, n.title)),
      h("div.f-meta", withSymbol ? [h("a.sym", { href: "#/stock/" + n.symbol }, n.symbol), " · "] : null,
        [n.publisher, fmt.ago(n.published)].filter(Boolean).join(" · "),
        " · ", n.relevant === false ? "general market story" : n.tone === "neutral" ? "neutral tone" : n.tone + " tone")));
}

function insiderTable(trades, withSymbol, compact) {
  return dataTable([
    withSymbol ? { label: "Stock", cell: (t) => h("a.sym", { href: "#/stock/" + t.symbol }, t.symbol) } : null,
    { label: "Date", cell: (t) => h("span.nowrap", fmt.date(t.date)) },
    { label: "Insider", cell: (t) => h("div", h("div", titleCase(t.insider)), h("div.muted.small", t.position)) },
    { label: "Trade", cell: (t) => (t.kind === "buy" ? pill("bullish", "Bought") : t.kind === "sell" ? pill("bearish", "Sold") : h("span.tag", "Other")) },
    compact ? null : { label: "Shares", right: true, hideSmall: true, cell: (t) => fmt.num(t.shares) },
    { label: "Value", right: true, cell: (t) => (t.value ? fmt.compact(t.value) : "—") },
  ].filter(Boolean), trades, { empty: "No open-market insider trades on record." });
}

/* ---- alerts ---- */
function alertsPage(root) {
  let filter = "all";
  const list = h("div");
  const chips = h("div.chips");
  const FILTERS = [["all", "All"], ["bullish", "Buy side"], ["bearish", "Sell side"], ["warning", "Heads-up"]];

  async function refresh() {
    const data = await api("/api/notifications?limit=300");
    const items = data.items.filter((n) => filter === "all" || n.tone === filter);
    fill(chips, FILTERS.map(([key, label]) => h("button.chip" + (filter === key ? ".on" : ""), { onclick: () => { filter = key; refresh(); } }, label)));
    fill(list, items.length ? items.map((n) => notificationItem(n)) : h("div.empty", "No alerts here yet. They appear when a signal changes, earnings approach, or an insider buys."));
  }

  const desktop = h("input", { type: "checkbox", checked: state.prefs.desktop && "Notification" in window && Notification.permission === "granted",
    onchange: async (e) => {
      if (e.target.checked && "Notification" in window) {
        const permission = await Notification.requestPermission();
        e.target.checked = permission === "granted";
      }
      state.prefs.desktop = e.target.checked;
    } });

  fill(root, 
    pageHead("Alerts", "Signal changes, chart events, earnings and insider buying on your watchlist.",
      h("label.switch", desktop, "Desktop pop-ups"),
      h("button.btn", { onclick: async () => { await api("/api/notifications/read", { method: "POST", body: {} }); await refreshOverview(); refresh(); } }, "Mark all read"),
      h("button.btn", { onclick: async () => { await api("/api/notifications", { method: "DELETE" }); await refreshOverview(); refresh(); } }, "Clear all")),
    h("div.stack", chips, h("section.card", list)));
  refresh();
  return { refresh };
}

/* ---- news ---- */
function newsPage(root) {
  let tone = "all";
  const list = h("div");
  const chips = h("div.chips");
  async function refresh() {
    const items = (await api("/api/news")).filter((n) => tone === "all" || n.tone === tone);
    fill(chips, [["all", "All"], ["positive", "Positive"], ["negative", "Negative"]].map(([key, label]) =>
      h("button.chip" + (tone === key ? ".on" : ""), { onclick: () => { tone = key; refresh(); } }, label)));
    fill(list, items.length ? items.map((n) => newsItem(n, true)) : h("div.empty", "No headlines yet."));
  }
  fill(root, pageHead("News", "Latest headlines for every stock you watch, with a quick read on tone."), h("div.stack", chips, h("section.card", list)));
  refresh();
  return {};
}

/* ---- earnings ---- */
function earningsPage(root) {
  const host = h("div");
  async function refresh() {
    const rows = await api("/api/earnings");
    fill(host, dataTable([
      { label: "Stock", cell: (r) => h("div", h("div.sym", r.symbol), h("div.sym-name", r.name)) },
      { label: "Next report", cell: (r) => (r.next_date ? h("div", h("div.nowrap", fmt.date(r.next_date)), h("div.small.muted", fmt.inDays(r.days_until))) : h("span.muted", "Not scheduled")) },
      { label: "", cell: (r) => (r.days_until !== null && r.days_until >= 0 && r.days_until <= 7 ? h("span.pill.warning", "! This week") : "") },
      { label: "EPS expected", right: true, cell: (r) => (r.eps_estimate === null ? "—" : fmt.money(r.eps_estimate)) },
      { label: "Last report", hideSmall: true, cell: (r) => (r.last ? fmt.date(r.last.date) : "—") },
      { label: "Last surprise", right: true, cell: (r) => (r.last && r.last.surprise_pct !== null ? h("span." + signClass(r.last.surprise_pct), fmt.pct(r.last.surprise_pct)) : "—") },
      { label: "Signal", cell: (r) => pill(r.direction, r.action_label) },
    ], rows, { empty: "Add stocks to your watchlist to see their earnings dates.", onRow: (r) => { location.hash = "#/stock/" + r.symbol; } }));
  }
  fill(root, pageHead("Earnings calendar", "Upcoming reports and how the last one compared with expectations."), h("section.card", host));
  refresh();
  return {};
}

/* ---- insiders ---- */
function insidersPage(root) {
  let kind = "buy";
  const host = h("div");
  const chips = h("div.chips");
  async function refresh() {
    const all = await api("/api/insiders");
    const rows = all.filter((t) => (kind === "all" ? t.kind !== "other" : t.kind === kind)).slice(0, 150);
    fill(chips, [["buy", "Buys"], ["sell", "Sales"], ["all", "Both"]].map(([key, label]) =>
      h("button.chip" + (kind === key ? ".on" : ""), { onclick: () => { kind = key; refresh(); } }, label)));
    fill(host, insiderTable(rows, true));
  }
  fill(root, 
    pageHead("Insider trades", "Open-market trades by executives and directors, from their public SEC filings."),
    h("div.stack",
      h("div.note", "Buys matter most: insiders sell for many reasons but buy for one. Gifts, stock grants and option exercises are left out because they are not a view on the stock."),
      chips, h("section.card", host)));
  refresh();
  return {};
}

/* ---- positions ---- */
function positionsPage(root) {
  const host = h("div");
  async function refresh() {
    const rows = await api("/api/positions");
    fill(host, dataTable([
      { label: "Stock", cell: (p) => h("span.sym", p.symbol) },
      { label: "Shares", right: true, cell: (p) => fmt.num(p.shares, p.shares % 1 ? 2 : 0) },
      { label: "Paid", right: true, cell: (p) => fmt.money(p.entry_price) },
      { label: "Now", right: true, cell: (p) => fmt.money(p.price) },
      { label: "Value", right: true, hideSmall: true, cell: (p) => fmt.money(p.value) },
      { label: "Profit / loss", right: true, cell: (p) => (p.pnl === null ? "—" : h("span." + signClass(p.pnl), fmt.money(p.pnl) + " (" + fmt.pct(p.pnl_pct) + ")")) },
      { label: "Stop", right: true, cell: (p) => (p.stop ? fmt.money(p.stop) : "—") },
      { label: "Signal", cell: (p) => (p.action ? pill(p.direction, p.direction === "bearish" ? "Sell" : p.action_label) : "") },
    ], rows, { empty: "No positions recorded. Open a stock and choose “Record a position” after you buy.", onRow: (p) => { location.hash = "#/stock/" + p.symbol; } }));
  }
  fill(root, pageHead("Positions", "What you own. Recorded positions get sell alerts and reduce your available budget."), h("section.card", host));
  refresh();
  return { refresh };
}

/* ---- settings ---- */
function settingsPage(root) {
  const st = state.overview.settings;
  const error = h("div.error-text", { hidden: true });
  const saved = h("span.small.up", { hidden: true }, "✓ Saved");
  const inputs = {};
  const field = (key, label, hint, affix, step) => {
    const input = h("input", { id: "set-" + key, type: "number", step, min: 0, value: st[key], inputMode: "decimal", oninput: update });
    inputs[key] = input;
    const derived = h("div.hint");
    input._derived = derived;
    return h("div.field", h("label", { htmlFor: "set-" + key }, label),
      h("div.input-affix" + (affix === "$" ? "" : ".suffix"), affix === "$" ? h("span", "$") : null, input, affix !== "$" ? h("span", affix) : null),
      h("div.hint", hint), derived);
  };
  const optionsOn = h("input", { type: "checkbox", checked: st.options_enabled });

  const form = h("div.stack.form-narrow",
    card("Budget", "Everything is sized from this",
      field("budget", "Total trading budget", "The money you are prepared to trade with. Not your whole savings.", "$", 100)),
    card("Stock trades", null, h("div.grid-2",
      field("risk_per_trade_pct", "Risk per trade", "How much of the budget you lose if a trade hits its stop. 1% is a common choice; above 2% is aggressive.", "%", 0.1),
      field("max_position_pct", "Largest single position", "Caps how much of the budget one stock can take.", "%", 1))),
    card("Options", null, h("div.stack",
      h("label.switch", optionsOn, "Show call and put recommendations"),
      field("option_risk_pct", "Risk per options trade", "The most one options trade may lose. A bought option can go to zero, so keep this small.", "%", 0.5))),
    card("Updates", null,
      field("refresh_minutes", "Check for new data every", "How often prices, news and filings are refreshed in the background.", "minutes", 1)),
    h("div.row", h("button.btn.primary", { onclick: save }, "Save settings"), saved), error);

  function update() {
    const budget = Number(inputs.budget.value) || 0;
    inputs.risk_per_trade_pct._derived.textContent = "= " + fmt.money0(budget * Number(inputs.risk_per_trade_pct.value) / 100) + " at risk per stock trade";
    inputs.max_position_pct._derived.textContent = "= up to " + fmt.money0(budget * Number(inputs.max_position_pct.value) / 100) + " in one stock";
    inputs.option_risk_pct._derived.textContent = "= up to " + fmt.money0(budget * Number(inputs.option_risk_pct.value) / 100) + " lost on one options trade";
    saved.hidden = true;
  }

  async function save() {
    const body = { options_enabled: optionsOn.checked };
    for (const [key, input] of Object.entries(inputs)) body[key] = Number(input.value);
    try {
      await api("/api/settings", { method: "PUT", body });
      error.hidden = true; saved.hidden = false;
      await refreshOverview();
    } catch (e) { error.hidden = false; error.textContent = e.message.replace(/_/g, " "); }
  }

  fill(root, pageHead("Settings", "Your budget and how much risk each trade may take."), form);
  update();
  return {};
}

/* ---- strategy guide ---- */
const GUIDE = [
  { title: "1. Only buy what is already going up (trend filter)", weight: "25 points, plus a hard rule",
    text: "A stock above its 200-day average is in an uptrend; below it, a downtrend. Faber's study of the equivalent 10-month rule back to 1900 found it kept stock-like returns while roughly halving the worst losses, because it steps aside during long declines. The app never issues a Buy on a stock below its 200-day average, however good the other signals look.",
    sources: [["Faber, A Quantitative Approach to Tactical Asset Allocation", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461"], ["Alpha Architect replication", "https://alphaarchitect.com/2014/09/are-uber-simple-asset-allocation-systems-robust/"]] },
  { title: "2. Winners keep winning for a while (momentum)", weight: "15 + 10 points",
    text: "Stocks that beat the market over the past 3 to 12 months tend to keep beating it for several more months (Jegadeesh and Titman). A related finding: stocks close to their 52-week high outperform, because investors anchor on the old high and are slow to price in good news (George and Hwang). The app scores the 12-month return, skipping the latest month, and the distance from the 52-week high.",
    sources: [["Jegadeesh & Titman, Profitability of Momentum Strategies", "https://www.nber.org/system/files/working_papers/w7159/w7159.pdf"], ["George & Hwang, The 52-Week High and Momentum Investing", "https://www.bauer.uh.edu/tgeorge/papers/gh5-paper.pdf"]] },
  { title: "3. Time entries on dips, not spikes", weight: "10 + 5 points",
    text: "Inside an uptrend, short sharp dips tend to recover within days. The app flags a pullback entry when the 2-day RSI falls under 10 while the stock is above its 200-day average, and warns when a stock is stretched (14-day RSI above 75). The published backtests of this rule are hypothetical and ignore costs, so it is used to pick the day, never to pick the stock.",
    sources: [["StockCharts: RSI(2)", "https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/rsi-2"], ["CXO Advisory on the limits of these backtests", "https://cxoadvisory.com/technical-trading/a-few-notes-on-short-term-trading-strategies-that-work"]] },
  { title: "4. Follow the insiders who buy", weight: "15 points",
    text: "Executives and directors must report their trades to the SEC. Their open-market purchases carry information; their sales mostly do not. Cohen, Malloy and Pomorski found that non-routine insider trades earned about 0.8% a month in abnormal returns while routine ones earned nothing. Several insiders buying at the same time is the strongest version. The app alerts on every insider purchase and scores cluster buying highest.",
    sources: [["Cohen, Malloy & Pomorski, Decoding Inside Information", "https://www.nber.org/papers/w16454"]] },
  { title: "5. Earnings surprises keep drifting", weight: "10 points",
    text: "After a company beats or misses expectations, its price has tended to keep moving the same way for about 60 trading days. The effect was strong in early studies (around 2% over the window) but has faded for large, heavily followed companies since the mid-2000s, so it gets a modest weight that decays as the report ages.",
    sources: [["Fink, review of post-earnings-announcement drift", "https://static.uni-graz.at/fileadmin/sowi/Working_Paper/2020-04_Fink.pdf"], ["Martineau, Rest in Peace Post-Earnings Announcement Drift", "https://cfr.ivo-welch.info/published/papers/martineau2021rest.pdf"]] },
  { title: "6. News tone is a tie-breaker", weight: "10 points",
    text: "Negative wording in financial news predicts lower prices, but for a day or two, after which prices revert (Tetlock). The app reads headline tone with a finance-specific word list and gives it a small weight. Use the News page to read the stories, not just the score.",
    sources: [["Tetlock, Giving Content to Investor Sentiment", "https://www.columbia.edu/~pt2238/papers/Tetlock_Media_Sentiment_JF.pdf"]] },
  { title: "7. Size by risk, and always have an exit", weight: "Sizing rule",
    text: "Position size comes from the stop, not from conviction: shares = (budget × risk per trade) ÷ (entry − stop). The stop sits 2.5 ATRs below the entry (ATR is the stock's average daily range), so a volatile stock gets a wider stop and fewer shares. A trailing stop 3 ATRs under the 22-day high locks in gains. This does not raise returns by itself; it makes sure no single trade can do serious damage.",
    sources: [] },
  { title: "8. Options: where retail traders actually lose", weight: "Options rules",
    text: "Studies of retail option trading find the losses concentrate in three habits: cheap far out-of-the-money contracts, expiries a few days away with wide bid/ask spreads, and buying just before earnings, when prices are inflated and collapse after the report (losses of 5 to 14% on average around announcements). The app does the opposite: about 45 days to expiry, delta near 0.60, spreads instead of outright buys near earnings or when options are expensive, and selling cash-secured puts when implied volatility is rich. Every idea is capped by your options risk setting.",
    sources: [["MIT Sloan: Retail investors lose big in options markets", "https://mitsloan.mit.edu/ideas-made-to-matter/retail-investors-lose-big-options-markets-research-shows"], ["de Silva, Smith & So, Losing is Optional", "https://www.gsb.stanford.edu/faculty-research/working-papers/losing-optional-retail-option-trading-expected-announcement"], ["Cboe: PutWrite and BuyWrite index performance", "https://www.cboe.com/insights/posts/key-cboe-benchmark-indexes-using-spx-options-offer-strong-risk-adjusted-returns/"]] },
];

function guidePage(root) {
  fill(root, 
    pageHead("Strategy guide", "The rules behind every signal, and the research they come from."),
    h("div.stack.guide",
      h("div.note", "No rule gets the timing right every time. These were picked because independent research supports them, and they are combined so that no single signal can trigger a trade. Each stock page shows how the price rules would have done on that stock."),
      GUIDE.map((g) => h("section.card", h("div.card-head", h("h2", g.title), h("p", g.weight)), h("p", g.text),
        g.sources.length ? h("div.sources", "Sources: ", g.sources.map(([name, url], i) => [i ? " · " : "", safeLink(url, name)])) : null)),
      h("section.card", h("h2", "How the score becomes a signal"),
        h("p", "Each rule adds or subtracts points, up to its weight. The total runs from −100 to +100: +25 or more is Buy, +50 or more is Strong buy, −25 or less is Sell, −50 or less is Strong sell, and anything between is Hold. For a stock you own, Sell means exit. For one you do not, it means stay out."))));
  return {};
}

/* ------------------------------ router & polling ------------------------------ */
const ROUTES = {
  dashboard: dashboardPage, alerts: alertsPage, news: newsPage, earnings: earningsPage,
  insiders: insidersPage, positions: positionsPage, settings: settingsPage, guide: guidePage,
};

function mountRoute() {
  const [name, arg] = location.hash.slice(2).split("/");
  const content = $("content");
  renderSidebar();
  if (name === "stock" && arg) state.page = stockPage(content, decodeURIComponent(arg).toUpperCase());
  else state.page = (ROUTES[name] || dashboardPage)(content);
}

async function refreshOverview() {
  state.overview = await api("/api/overview");
  renderSidebar();
  renderTopbar();
  if (state.page && state.page.refresh) state.page.refresh();
}

async function poll() {
  try {
    await refreshOverview();
    await checkNotifications();
  } catch (e) { /* server restarting; try again next tick */ }
}

window.addEventListener("hashchange", () => { window.scrollTo(0, 0); mountRoute(); });

(async function start() {
  try {
    state.overview = await api("/api/overview");
  } catch (e) {
    fill($("content"), h("div.card", h("div.empty", "Could not reach the StockAnalysis server. Is it still running?")));
    return;
  }
  renderTopbar();
  mountRoute();
  await checkNotifications().catch(() => {});
  setInterval(poll, 15000);
  // While the first scan is running, poll faster so results appear as they land.
  const fast = setInterval(() => { if (state.overview.status.scanning || !state.overview.status.last_scan) poll(); else clearInterval(fast); }, 2500);
})();
