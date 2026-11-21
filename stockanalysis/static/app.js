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
  columns = columns.filter(Boolean);
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
  ["markets", "Markets"],
  ["lab", "Indicator lab"],
  ["track", "Track record"],
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
    banner.textContent = "Demo mode: prices, news and earnings are simulated (insider filings are real once SEC alerts are connected). Start without --demo for live market data.";
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
    h("div.f-main", h("div.f-title", n.title), h("div.f-body", n.body),
      h("div.f-meta", fmt.ago(n.created_at), n.link ? [" · ", h("a", { href: n.link, target: "_blank", rel: "noopener noreferrer", onclick: (e) => e.stopPropagation() }, "SEC filing ↗")] : null)));
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

/* ---- TradingView ---- */
let tvLoader = null;
function loadTradingView() {
  if (window.TradingView) return Promise.resolve();
  if (!tvLoader) {
    tvLoader = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://s3.tradingview.com/tv.js";
      script.onload = resolve;
      script.onerror = () => { tvLoader = null; reject(new Error("Could not load TradingView. Check your internet connection.")); };
      document.head.append(script);
    });
  }
  return tvLoader;
}

const tvPref = {
  get on() { try { return localStorage.getItem("tvCharts") === "1"; } catch (e) { return false; } },
  set on(v) { try { localStorage.setItem("tvCharts", v ? "1" : "0"); } catch (e) { /* private mode */ } },
};

function isDark() {
  const t = document.documentElement.dataset.theme;
  return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
}

let tvCounter = 0;
/** A TradingView chart for `symbol` with the given studies. Loads only after the user opts in. */
function tradingViewChart(symbol, tactic, params, height = 480) {
  const id = "tv_chart_" + (++tvCounter);
  const host = h("div", { style: "height:" + height + "px;border-radius:8px;overflow:hidden" }, h("div", { id, style: "height:100%" }));
  const wrap = h("div");
  async function show() {
    fill(wrap, host);
    try {
      const q = new URLSearchParams({ symbol, tactic: tactic || "", params: JSON.stringify(params || {}) });
      const [setup] = await Promise.all([api("/api/tradingview/studies?" + q), loadTradingView()]);
      new window.TradingView.widget({
        container_id: id, autosize: true, symbol: setup.symbol, interval: "D", timezone: "America/New_York",
        theme: isDark() ? "dark" : "light", style: "1", locale: "en", allow_symbol_change: true,
        hide_side_toolbar: false, withdateranges: true, studies: setup.studies,
      });
    } catch (e) {
      fill(wrap, h("div.note.warn", e.message));
    }
  }
  if (tvPref.on) show();
  else {
    fill(wrap, h("div.note", h("span",
      "Charts from TradingView load TradingView's script in your browser, so TradingView sees which stocks you look at. ",
      h("button.btn.small", { style: "margin-left:6px", onclick: () => { tvPref.on = true; show(); } }, "Show TradingView chart"))));
  }
  return wrap;
}

function pineModal(tactic, params, label) {
  const code = h("pre.code", "Loading…");
  const copy = h("button.btn.primary", { onclick: async () => {
    try { await navigator.clipboard.writeText(code.textContent); copy.textContent = "Copied ✓"; }
    catch (e) { const r = document.createRange(); r.selectNodeContents(code); getSelection().removeAllRanges(); getSelection().addRange(r); copy.textContent = "Press Ctrl+C to copy"; }
  } }, "Copy code");
  const body = h("div.stack", { style: "margin-top:8px" },
    h("ol.small.soft", { style: "margin:0;padding-left:18px;display:grid;gap:4px" },
      h("li", "On TradingView, open a daily chart of any stock."),
      h("li", "Open the Pine Editor at the bottom, paste this code, and click “Add to chart”."),
      h("li", "Open the Strategy Tester tab to see its trades, win rate and returns. Change the settings in the strategy's settings panel."),
      h("li", "Optional: create an alert on the strategy and send it to this app (Settings › TradingView alerts).")),
    code);
  api("/api/lab/pine?" + new URLSearchParams({ tactic, params: JSON.stringify(params) }))
    .then((r) => { code.textContent = r.code; }).catch((e) => { code.textContent = e.message; });
  modal("Pine Script: " + label, body, (close) => [h("button.btn", { onclick: close }, "Close"), copy]);
  document.querySelector(".modal").classList.add("wide");
}

/* ---- market risk indicator ---- */
function profitCard(p, reload) {
  const pct1 = (x) => fmt.pct(x, 1);
  const choices = [["off", "Off"], ...Object.entries(p.options).map(([k, o]) => [k, o.label + (k === p.chosen_by_test ? " (tested pick)" : "")])];
  const picker = h("div.chips", choices.map(([k, label]) => h("button.chip" + (p.plan === k ? ".on" : ""), {
    onclick: async () => {
      try { await api("/api/settings", { method: "PUT", body: { profit_plan: k } }); reload(); }
      catch (err) { toast({ title: "Could not change the plan", body: err.message, tone: "warning" }); }
    } }, label)));
  const head = h("div.card-head", h("h2", "Profit plan"), h("p", "The approach that made the most money in 65 years of testing, as a live instruction"));
  if (p.plan === "off" || !p.options[p.plan]) {
    return h("section.card", head, picker, h("p.soft", { style: "margin-top:8px" }, "Pick a plan to get a clear instruction and an alert whenever it changes."));
  }
  const o = p.options[p.plan], st = p.state, t = o.tested || {};
  const long = t.sp_long, fund = t.spy;
  const row = (name, x, hold) => h("tr", h("td", name),
    h("td.r.num", h("strong", pct1(x.cagr_pct)), h("span.muted", " vs " + pct1(hold.cagr_pct))),
    h("td.r.num", h("strong", fmt.pct(x.max_drawdown_pct, 0)), h("span.muted", " vs " + fmt.pct(hold.max_drawdown_pct, 0))));
  const now = !st ? h("div.empty", p.error || "Waiting for S&P 500 data.") : h("div.row", { style: "gap:14px;align-items:flex-start;flex-wrap:wrap" },
    h("div", { style: "min-width:220px;flex:1" },
      h("div.small.muted", "Do now (as of the " + fmt.date(st.as_of) + " close)"),
      h("div", { style: "font-size:20px;font-weight:700;margin:2px 0 4px" }, st.invested ? "Hold " + st.fund : "Hold T-bills (" + st.cash_fund + ")"),
      h("div.soft", st.action),
      h("div.small.muted", { style: "margin-top:4px" }, "Since " + fmt.date(st.since) + ". You get an alert the day it changes; trade at the next close.")),
    h("dl.kv", { style: "min-width:220px" },
      h("dt", "S&P 500 vs 200-day average"), h("dd", h("span." + signClass(st.gap_pct), pct1(st.gap_pct))),
      h("dt", "200-day average"), h("dd", fmt.num(st.sma200, 2)),
      st.uses_momentum ? [h("dt", "12-month return vs T-bills"), h("dd", pct1(st.momentum_12m_pct) + " vs " + st.tbill_12m_pct.toFixed(1) + "%")] : null));
  return h("section.card", head, picker,
    h("p.small.soft", { style: "margin:8px 0 10px" }, h("strong", o.label + ": "), o.rule),
    now,
    long ? h("div.table-wrap", { style: "margin-top:12px" }, h("table",
      h("thead", h("tr", h("th", "Tested (plan vs holding)"), h("th.r", "Per year"), h("th.r", "Worst drop"))),
      h("tbody", row("S&P 500 since 1961", long.plan, long.hold), fund ? row("SPY since 1994", fund.plan, fund.hold) : null))) : null,
    p.plan === "aggressive" ? h("div.note.warn", { style: "margin-top:10px;display:block" }, h("strong", "High risk. "),
      "The 3x plan made the most money in testing, but fell as much as " + (long ? fmt.pct(long.plan.max_drawdown_pct, 0) : "−78%") +
      " along the way, more than holding the index ever did. A one-day crash like 1987 would cost about 60% before the switch can act. Only use money you can leave alone for many years.")
      : p.plan === "growth" ? h("p.small.muted", { style: "margin-top:8px" }, "Chosen before testing as the highest return whose worst drop was no deeper than simply holding the S&P 500; it then beat holding in both halves of history since 1961, in the fund era, and on the Nasdaq-100. Leveraged funds held all the time lost up to 99%, so the switch is not optional.")
      : null,
    h("p.muted.small", { style: "margin-top:6px" }, "Returns above are before taxes; every switch to cash realizes gains. Details on the ", h("a", { href: "#/track" }, "Track record"), " page."));
}

function marketCard(m, budget) {
  if (!m) return null;
  const share = m.exposure_pct / 100;
  const bar = h("div.meter-track", { style: "width:100%;height:8px" });
  const fillBar = h("div.meter-fill.pos", { style: "left:0;width:" + m.exposure_pct + "%;background:var(--accent)" });
  bar.append(fillBar);
  const check = (ok, text) => h("li", h("span", { style: "font-weight:700;margin-right:6px", class: ok ? "up" : "down" }, ok ? "✓" : "✗"), text);
  return h("section.card",
    h("div.card-head",
      h("div.row", h("h2", "Market risk"), pill(m.tone, m.state)),
      h("a.small", { href: "#/track" }, "Why this rule? See the track record")),
    h("div.grid-2", { style: "align-items:center" },
      h("div",
        h("div.muted.small", "Suggested share of your budget in stocks"),
        h("div", { style: "font-size:28px;font-weight:650;margin:2px 0 6px" }, m.exposure_pct + "% ", h("span.soft", { style: "font-size:16px;font-weight:500" }, "≈ " + fmt.money0(budget * share))),
        h("div.market-bar", bar),
        h("p.soft.small", { style: "margin-top:8px" }, m.headline)),
      h("ul.small", { style: "margin:0;padding-left:4px;list-style:none;display:grid;gap:4px" },
        check(m.above_200, "S&P 500 " + (m.pct_from_200 >= 0 ? m.pct_from_200 + "% above" : Math.abs(m.pct_from_200) + "% below") + " its 200-day average"),
        check(m.momentum_ok, "12-month return " + fmt.pct(m.mom12_pct) + " vs " + m.tbill_pct.toFixed(1) + "% for T-bills"),
        check(m.vol20_pct <= m.vol_target_pct * 1.1, "Recent swings " + m.vol20_pct.toFixed(0) + "% a year (comfort level " + m.vol_target_pct + "%)"))),
    h("p.muted.small", { style: "margin-top:8px" }, "In 20 years of testing this was the part that came closest to holding up: it made crashes smaller (worst loss −31% to −45% instead of −55%), but trailed always-invested by about 2–2.5% a year. Individual Buy/Sell ratings and indicator settings did not beat the market."));
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

  const marketHost = h("div");
  const profitHost = h("div");
  fill(root,
    pageHead("Dashboard", "Your watchlist, scored by the trading rules and sized to your budget.",
      h("div.search-wrap", input, suggestions), addBtn),
    error, h("div.stack", profitHost, marketHost, tiles, h("section.card", tableHost)));
  const loadProfit = () => api("/api/profit").then((p) => fill(profitHost, profitCard(p, loadProfit))).catch(() => fill(profitHost));
  loadProfit();

  function refresh() {
    const o = state.overview;
    if (!o) return;
    fill(marketHost, marketCard(o.market, o.budget.total));
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
      o.settings.my_tactic && o.settings.my_tactic.tactic ? { label: "My indicator", hideSmall: true, cell: (w) => (w.my_tactic
          ? h("span", { title: w.my_tactic.label + (w.my_tactic.since ? " · since " + w.my_tactic.since : "") }, w.my_tactic.holding ? pill("bullish", "Hold") : pill("neutral", "Cash"))
          : "") } : null,
      { label: "Next earnings", hideSmall: true, cell: (w) => (w.next_earnings ? h("div", h("div.nowrap", fmt.date(w.next_earnings)),
          h("div.small" + (w.earnings_days <= 7 ? "" : ".muted"), w.earnings_days <= 7 ? h("span.pill.warning", "! " + fmt.inDays(w.earnings_days)) : fmt.inDays(w.earnings_days))) : h("span.muted", "—")) },
      { label: "", cell: (w) => h("button.btn.ghost.small", { title: "Remove " + w.symbol, "aria-label": "Remove " + w.symbol,
          onclick: async () => { await api("/api/watchlist/" + encodeURIComponent(w.symbol), { method: "DELETE" }); refreshOverview(); } }, "✕") },
    ];
    fill(tableHost, dataTable(columns, o.watchlist, {
      empty: "Your watchlist is empty. Add a ticker above to start.",
      onRow: (w) => { location.hash = "#/stock/" + encodeURIComponent(w.symbol); },
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
          h("div.stack", chartCard(a), h("section.card",
            h("div.card-head", h("h2", "TradingView chart"), h("p", "All of TradingView's indicators and drawing tools; 50/200-day averages and RSI pre-loaded")),
            tradingViewChart(a.symbol, null, null, 460),
            h("p.muted.small", { style: "margin-top:8px" }, h("a", { href: "https://www.tradingview.com/chart/?symbol=" + encodeURIComponent(a.symbol), target: "_blank", rel: "noopener noreferrer" }, "Open " + a.symbol + " on TradingView.com ↗"))),
            signalsCard(a), newsCard(a)),
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
      if (p.trailing_stop) add("Trailing stop (" + p.trailing_stop_pct + "% below best close)", fmt.money(p.trailing_stop));
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
    const source = a.insiders.source === "sec"
      ? h("p.muted.small", { style: "margin-top:8px" }, "From SEC Form 4 filings, checked every few minutes.")
      : h("p.muted.small", { style: "margin-top:8px" }, "From Yahoo Finance's summary. ", h("a", { href: "#/settings" }, "Connect SEC filings"), " for live alerts, exact trade types and 10b5-1 flags.");
    const notes = [
      sum.planned_buys ? sum.planned_buys + " pre-planned 10b5-1 buy(s) not counted" : null,
      sum.routine_buyers && sum.routine_buyers.length ? sum.routine_buyers.length + " routine buyer(s) counted at half weight" : null,
    ].filter(Boolean);
    return card("Insider trades", "Last " + sum.window_days + " days: " + sum.buyers.length + " buyers, " + sum.sellers.length + " sellers",
      a.insiders.available ? insiderTable(trades, false, true) : h("div.empty", "Insider filings are unavailable for this symbol."),
      notes.length ? h("p.small.soft", { style: "margin-top:8px" }, notes.join(" · ")) : null,
      source);
  }

  function backtestCard(sym) {
    const body = h("div", h("div.skeleton"));
    const section = card("How these timing rules did on " + sym, "Price rules only, replayed day by day", body);
    const show = (b) => {
      if (!b.available) { fill(body, h("div.empty", b.reason)); return; }
      const chart = lineChart({
        dates: b.curve.dates, height: 220, label: "Growth of 100 dollars: rules versus buy and hold",
        yFormat: (v) => "$" + (Math.round(v) || 0).toLocaleString("en-US"),
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
    else api("/api/stock/" + encodeURIComponent(sym) + "/backtest").then((b) => { state.backtests[sym] = b; show(b); }).catch((e) => fill(body, h("div.empty", e.message)));
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
    pos ? h("button.btn", { style: "margin-right:auto", onclick: async () => { await api("/api/positions/" + encodeURIComponent(a.symbol), { method: "DELETE" }); close(); await refreshOverview(); done(); } }, "Close position") : null,
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
    { label: "Insider", cell: (t) => h("div", h("div", t.insider_display || titleCase(t.insider)), h("div.muted.small", t.position)) },
    { label: "Trade", cell: (t) => h("div.chips", t.kind === "buy" ? pill("bullish", "Bought") : t.kind === "sell" ? pill("bearish", "Sold") : h("span.tag", "Other"), insiderTags(t)) },
    compact ? null : { label: "Shares", right: true, hideSmall: true, cell: (t) => fmt.num(t.shares) },
    { label: "Value", right: true, cell: (t) => (t.value ? fmt.compact(t.value) : "—") },
    compact ? null : { label: "", hideSmall: true, cell: (t) => (t.url ? safeLink(t.url, "Filing ↗") : "") },
  ].filter(Boolean), trades, { empty: "No open-market insider trades on record." });
}

/* ---- alerts ---- */
function alertsPage(root) {
  let filter = "all";
  const list = h("div");
  const chips = h("div.chips");
  const FILTERS = [["all", "All"], ["insider", "Insider trades"], ["trend", "Profit plan & trends"], ["tradingview", "TradingView"], ["bullish", "Buy side"], ["bearish", "Sell side"], ["warning", "Heads-up"]];

  async function refresh() {
    const data = await api("/api/notifications?limit=300");
    const items = data.items.filter((n) => filter === "all" || (filter === "insider" ? n.kind.startsWith("insider")
      : filter === "tradingview" ? n.kind === "tradingview"
      : filter === "trend" ? ["market_trend", "trend_portfolio", "market_regime", "profit_plan"].includes(n.kind) : n.tone === filter));
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
function insiderTags(t) {
  return [
    t.code && t.kind === "other" ? h("span.tag", { title: t.text || "" }, t.code) : null,
    t.plan_10b5_1 ? h("span.tag", { title: "Pre-planned under a Rule 10b5-1 trading plan" }, "10b5-1 plan") : null,
    t.routine === "routine" ? h("span.tag", { title: "Traded in this same month in each of the last 3 years" }, "Routine") : null,
    t.routine === "opportunistic" ? h("span.pill.bullish", { title: "Not a routine pattern for this insider" }, "Opportunistic") : null,
  ].filter(Boolean);
}

function insidersPage(root) {
  let scope = "market";
  let kind = "buy";
  let minValue = 100000;
  const host = h("div");
  const controls = h("div.row");
  const banner = h("div");

  async function refresh() {
    const connected = state.overview && state.overview.insiders && state.overview.insiders.configured;
    fill(banner, connected ? null : h("div.note.warn",
      h("span", { "aria-hidden": "true" }, "!"),
      h("span", "Live SEC filings are not connected, so you are seeing Yahoo's delayed summary and no market-wide feed. ",
        h("a", { href: "#/settings" }, "Add your name and email in Settings"), " to get insider alerts within minutes of each filing.")));
    const scopeChips = h("div.chips", [["market", "Whole market (live)"], ["watchlist", "My watchlist"]].map(([key, label]) =>
      h("button.chip" + (scope === key ? ".on" : ""), { onclick: () => { scope = key; refresh(); } }, label)));
    if (scope === "market") {
      fill(controls, scopeChips, h("div.chips", [[0, "Any size"], [100000, "$100K+"], [500000, "$500K+"], [1000000, "$1M+"]].map(([v, label]) =>
        h("button.chip" + (minValue === v ? ".on" : ""), { onclick: () => { minValue = v; refresh(); } }, label))));
      const rows = await api("/api/insiders?scope=market&days=14&min_value=" + minValue);
      fill(host, dataTable([
        { label: "Filed", cell: (t) => h("div", h("div.nowrap", fmt.date(t.filed)), h("div.small.muted", "traded " + fmt.date(t.trade_date))) },
        { label: "Company", cell: (t) => h("div", t.symbol ? h("a.sym", { href: "#/stock/" + t.symbol }, t.symbol) : h("span.sym", "—"), h("div.sym-name", t.issuer_name || "")) },
        { label: "Insider", cell: (t) => h("div", h("div", t.owner_display), h("div.muted.small", t.role || "")) },
        { label: "Bought", right: true, cell: (t) => h("div", h("div", { style: "font-weight:650" }, fmt.compact(t.value)), h("div.small.muted", fmt.num(t.shares) + " sh" + (t.avg_price ? " @ " + fmt.money(t.avg_price) : ""))) },
        { label: "Stake", right: true, hideSmall: true, cell: (t) => (t.stake_change_pct === null || t.stake_change_pct === undefined ? "—" : "+" + fmt.num(t.stake_change_pct) + "%") },
        { label: "", hideSmall: true, cell: (t) => h("div.chips", insiderTags(t)) },
        { label: "", cell: (t) => safeLink(t.url, "Filing ↗") },
      ], rows, { empty: connected ? "No open-market purchases of this size in the last 14 days of filings the app has read. The feed fills up as new filings arrive." : "Connect SEC filings in Settings to see this feed." }));
    } else {
      fill(controls, scopeChips, h("div.chips", [["buy", "Buys"], ["sell", "Sales"], ["all", "Both"]].map(([key, label]) =>
        h("button.chip" + (kind === key ? ".on" : ""), { onclick: () => { kind = key; refresh(); } }, label))));
      const all = await api("/api/insiders");
      const rows = all.filter((t) => (kind === "all" ? t.kind !== "other" : t.kind === kind)).slice(0, 150);
      fill(host, insiderTable(rows, true));
    }
  }
  fill(root,
    pageHead("Insider trades", "Open-market trades by executives and directors, from their SEC Form 4 filings."),
    h("div.stack",
      banner,
      h("div.note", "Buys matter most: insiders sell for many reasons but buy for one. Purchases that are not part of a pre-planned 10b5-1 trade, by insiders without a routine pattern, and by several insiders at once have been the most informative. Gifts, grants and option exercises are left out."),
      controls, h("section.card", host)));
  refresh();
  return { refresh: () => { if (scope === "market") refresh(); } };
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
  const inputs = {};   // numeric fields
  const texts = {};    // text fields
  const toggles = {};  // checkboxes
  const field = (key, label, hint, affix, step) => {
    const input = h("input", { id: "set-" + key, type: "number", step, min: 0, value: st[key], inputMode: "decimal", oninput: update });
    inputs[key] = input;
    const derived = h("div.hint");
    input._derived = derived;
    return h("div.field", h("label", { htmlFor: "set-" + key }, label),
      h("div.input-affix" + (affix === "$" ? "" : ".suffix"), affix === "$" ? h("span", "$") : null, input, affix !== "$" ? h("span", affix) : null),
      hint ? h("div.hint", hint) : null, derived);
  };
  const textField = (key, label, hint, placeholder, type = "text") => {
    const input = h("input.input", { id: "set-" + key, type, value: st[key] || "", placeholder, autocomplete: "off", spellcheck: false, oninput: update });
    texts[key] = input;
    return h("div.field", h("label", { htmlFor: "set-" + key }, label), input, hint ? h("div.hint", hint) : null);
  };
  const toggle = (key, label) => {
    const input = h("input", { type: "checkbox", checked: !!st[key], onchange: update });
    toggles[key] = input;
    return h("label.switch", input, label);
  };
  const scope = h("select.input", { id: "set-push_scope", onchange: update },
    h("option", { value: "insider", selected: st.push_scope === "insider" }, "Insider trades, TradingView and market trend alerts"),
    h("option", { value: "all", selected: st.push_scope === "all" }, "Every alert"));

  const insiderStatus = h("div.note", "Checking…");
  const pushStatus = h("div.hint");
  const pollBtn = h("button.btn.small", { onclick: async () => {
    pollBtn.disabled = true;
    try { await api("/api/insiders/poll", { method: "POST" }); setTimeout(loadStatus, 2500); }
    catch (e) { insiderStatus.className = "note warn"; insiderStatus.textContent = e.message; }
    setTimeout(() => { pollBtn.disabled = false; }, 3000);
  } }, "Check filings now");
  const testBtn = h("button.btn.small", { onclick: async () => {
    testBtn.disabled = true;
    try {
      await api("/api/push/test", { method: "POST", body: { url: texts.push_url.value } });
      pushStatus.className = "hint up"; pushStatus.textContent = "✓ Test sent. Check your phone.";
    } catch (e) { pushStatus.className = "error-text"; pushStatus.textContent = e.message; }
    testBtn.disabled = false;
  } }, "Send a test");

  async function loadStatus() {
    try {
      const sts = await api("/api/insiders/status");
      if (!sts.configured) {
        insiderStatus.className = "note warn";
        insiderStatus.textContent = "Not connected yet. Enter your name and email above and save to start receiving SEC filings.";
      } else if (sts.last_error) {
        insiderStatus.className = "note warn";
        insiderStatus.textContent = "Last check had a problem: " + sts.last_error;
      } else {
        insiderStatus.className = "note";
        insiderStatus.textContent = sts.polling ? "Checking SEC filings now…" :
          sts.last_poll ? "✓ Connected to SEC EDGAR. Last checked " + fmt.ago(sts.last_poll) + "; " + sts.filings_seen + " filings read since the app started." :
          "✓ Connected. The first check starts in a moment.";
      }
      if (sts.push.last_error) { pushStatus.className = "error-text"; pushStatus.textContent = sts.push.last_error; }
    } catch (e) { /* status is best-effort */ }
  }

  const form = h("div.stack.form-narrow",
    card("Budget", "Everything is sized from this",
      field("budget", "Total trading budget", "The money you are prepared to trade with. Not your whole savings.", "$", 100)),
    card("Stock trades", null, h("div.grid-2",
      field("risk_per_trade_pct", "Risk per trade", "How much of the budget you lose if a trade hits its stop. 1% is a common choice; above 2% is aggressive.", "%", 0.1),
      field("max_position_pct", "Largest single position", "Caps how much of the budget one stock can take.", "%", 1))),
    card("Options", null, h("div.stack",
      toggle("options_enabled", "Show call and put recommendations"),
      field("option_risk_pct", "Risk per options trade", "The most one options trade may lose. A bought option can go to zero, so keep this small.", "%", 0.5))),
    card("Insider trade alerts", "Live from SEC Form 4 filings", h("div.stack",
      h("p.soft", "Insiders must report every trade to the SEC within two business days. The app reads those filings directly, minutes after they are published, so you hear about an insider purchase as soon as it is public."),
      textField("sec_contact", "Your name and email for the SEC",
        "The SEC requires every automated tool to identify itself with a contact. This is only sent to sec.gov, never anywhere else.",
        "Jane Doe jane@example.com"),
      insiderStatus,
      h("div.row", pollBtn),
      toggle("insider_market_alerts", "Also alert on big insider buys at any US company"),
      h("div.grid-2",
        field("insider_market_min_value", "Smallest market-wide buy to alert on", "Officers and directors only; pre-planned 10b5-1 buys are skipped.", "$", 50000),
        field("insider_poll_minutes", "Check for new filings every", null, "minutes", 1)),
      toggle("insider_alert_sells", "Alert on insider sales of stocks on my watchlist"),
      field("insider_sell_min_value", "Smallest sale to alert on", "Sales are usually for taxes or diversification, so only big ones are worth a look.", "$", 100000))),
    card("Phone notifications", "Optional", h("div.stack",
      h("p.soft", "Get alerts on your phone even when this page is closed. The free ntfy app is the simplest option: install it, subscribe to a topic name only you know, and paste the topic link below. Discord and Slack webhook links also work."),
      textField("push_url", "Push link", null, "https://ntfy.sh/your-secret-topic-name", "url"),
      h("div.field", h("label", { htmlFor: "set-push_scope" }, "Send to phone"), scope),
      h("div.row", testBtn), pushStatus,
      h("p.muted.small", "Anyone who knows an ntfy topic name can read it, so pick a long random one."))),
    tradingViewCard(),
    card("Updates", null,
      field("refresh_minutes", "Check prices and news every", "How often prices, news and earnings are refreshed in the background.", "minutes", 1)),
    h("div.row", h("button.btn.primary", { onclick: save }, "Save settings"), saved), error);

  function tradingViewCard() {
    const urlBox = h("input.input", { readOnly: true, value: "Loading…", style: "flex:1;min-width:0;font-family:ui-monospace,monospace;font-size:12.5px" });
    const msgBox = h("pre.code", "");
    const status = h("div.hint");
    async function load() {
      const setup = await api("/api/tradingview/setup");
      urlBox.value = setup.local_url;
      urlBox.dataset.path = setup.webhook_path;
      msgBox.textContent = setup.message;
    }
    load();
    const copyBtn = (getText, label) => {
      const b = h("button.btn.small", { onclick: async () => { try { await navigator.clipboard.writeText(getText()); b.textContent = "Copied ✓"; } catch (e) { b.textContent = "Select and copy"; } } }, label);
      return b;
    };
    return card("TradingView alerts", "Optional", h("div.stack",
      h("p.soft", "Send alerts you set on TradingView (price levels, indicators, your own Pine strategies) into this app's alert feed, and to your phone if push is set up."),
      h("div.field", h("label", "Webhook address (keep it private: it contains your secret token)"), h("div.row", { style: "flex-wrap:nowrap" }, urlBox, copyBtn(() => urlBox.value, "Copy"))),
      h("div.field", h("label", "Suggested alert message"), msgBox, h("div.row", copyBtn(() => msgBox.textContent, "Copy message"))),
      h("details", h("summary.small", "How to connect TradingView (needs a paid TradingView plan)"),
        h("ol.small.soft", { style: "margin:6px 0 0;padding-left:18px;display:grid;gap:4px" },
          h("li", "TradingView only sends webhooks on paid plans, and only with two-factor sign-in turned on."),
          h("li", "TradingView must be able to reach this app over HTTPS on a normal web port. Since the app runs on your computer, start a free tunnel, for example: cloudflared tunnel --url http://localhost:8000 (Cloudflare) or ngrok http 8000. It prints a public https:// address."),
          h("li", "Replace the start of the address above with the tunnel's address, keeping /api/webhooks/tradingview?token=… on the end. Requests arriving through a tunnel can reach only this webhook, not the rest of the app."),
          h("li", "In TradingView, create an alert, tick “Webhook URL” in Notifications, paste the address, and paste the suggested message (or any text)."),
          h("li", "The suggested message is for alerts on a strategy (such as one exported from the Indicator Lab). For a price or indicator alert, change {{strategy.order.action}} to buy or sell, or just write a plain sentence starting with the ticker, like “AAPL crossed above 200 buy”."),
          h("li", "Alerts appear under Alerts › TradingView. If the address ever leaks, click “New secret token”."))),
      h("div.row",
        h("button.btn.small", { onclick: async () => {
          try {
            const res = await fetch(urlBox.value.replace(/^https?:\/\/[^/]+/, ""), { method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ ticker: "AAPL", action: "buy", price: "100.00", title: "Test alert from TradingView settings", message: "If you can read this in Alerts, the webhook works." }) });
            status.className = res.ok ? "hint up" : "error-text";
            status.textContent = res.ok ? "✓ Test alert received. Check Alerts." : "Test failed (" + res.status + ").";
            refreshOverview();
          } catch (e) { status.className = "error-text"; status.textContent = e.message; }
        } }, "Send a test alert"),
        h("button.btn.small.ghost", { onclick: async () => { await api("/api/tradingview/token", { method: "POST" }); load(); status.className = "hint"; status.textContent = "New token created. Update the address in your TradingView alerts."; } }, "New secret token")),
      status));
  }

  function update() {
    const budget = Number(inputs.budget.value) || 0;
    inputs.risk_per_trade_pct._derived.textContent = "= " + fmt.money0(budget * Number(inputs.risk_per_trade_pct.value) / 100) + " at risk per stock trade";
    inputs.max_position_pct._derived.textContent = "= up to " + fmt.money0(budget * Number(inputs.max_position_pct.value) / 100) + " in one stock";
    inputs.option_risk_pct._derived.textContent = "= up to " + fmt.money0(budget * Number(inputs.option_risk_pct.value) / 100) + " lost on one options trade";
    saved.hidden = true;
  }

  async function save() {
    const body = { push_scope: scope.value };
    for (const [key, input] of Object.entries(toggles)) body[key] = input.checked;
    for (const [key, input] of Object.entries(inputs)) body[key] = Number(input.value);
    for (const [key, input] of Object.entries(texts)) body[key] = input.value.trim();
    try {
      await api("/api/settings", { method: "PUT", body });
      error.hidden = true; saved.hidden = false;
      await refreshOverview();
      setTimeout(loadStatus, 2500);
    } catch (e) { error.hidden = false; error.textContent = e.message.replace(/_/g, " "); }
  }

  fill(root, pageHead("Settings", "Your budget, how much risk each trade may take, and where alerts go."), form);
  update();
  loadStatus();
  const timer = setInterval(() => { if (document.body.contains(insiderStatus)) loadStatus(); else clearInterval(timer); }, 15000);
  return {};
}

/* ---- markets (gold, silver, oil, bonds, crypto...) ---- */
function marketsPage(root) {
  const body = h("div.stack", h("div.skeleton"));
  fill(root, pageHead("Markets", "Gold, silver, oil, bonds, currencies, crypto and stock indexes: live trend status and what 20 years of testing found."), body);
  let classFilter = "All";
  let markets = null;
  let trend = null;

  async function setAlerts(symbols, extra = {}) {
    try {
      await api("/api/settings", { method: "PUT", body: { trend_alert_symbols: symbols, ...extra } });
      trend = await api("/api/trend");
      render();
    } catch (err) {
      toast({ title: "Could not change trend alerts", body: err.message, tone: "warning" });
    }
  }

  function alertButton(sym) {
    if (!trend) return "";
    const list = trend.alerts.symbols;
    const on = list.includes(sym);
    return h("button.btn.small" + (on ? "" : ".ghost"), {
      title: on ? "Alerts on: click to stop alerts for " + sym : "Get an alert when the 10-month rule changes for " + sym,
      "aria-pressed": String(on),
      onclick: (e) => { e.stopPropagation(); e.target.disabled = true; setAlerts(on ? list.filter((s) => s !== sym) : [...list, sym]); },
    }, on ? "🔔 On" : "Off");
  }

  function trackerCard() {
    if (!trend) return null;
    const p = trend.portfolio;
    const toggle = h("input", { type: "checkbox", checked: p.alerts_on, onchange: async (e) => {
      try { await api("/api/settings", { method: "PUT", body: { trend_portfolio_alerts: e.target.checked } }); }
      catch (err) { e.target.checked = !e.target.checked; toast({ title: "Could not change the setting", body: err.message, tone: "warning" }); }
    } });
    const pending = p.assets.filter((a) => a.signal && a.signal.flip_pending);
    const changes = p.changes.slice(0, 8);
    const band = trend.band_pct || 0;
    const bandSelect = h("select.input", { style: "width:auto", "aria-label": "Trend rule band", onchange: async (e) => {
      try {
        await api("/api/settings", { method: "PUT", body: { trend_band_pct: Number(e.target.value) } });
        [markets, trend] = await Promise.all([api("/api/markets"), api("/api/trend")]);
        render();
      } catch (err) { toast({ title: "Could not change the band", body: err.message, tone: "warning" }); }
    } }, [[0, "No band (original rule)"], [1, "1% band"], [2, "2% band (tested, default)"], [3, "3% band"]].map(([v, label]) =>
      h("option", { value: v, selected: Number(band) === v }, label)));
    return h("section.card",
      h("div.card-head", h("h2", "Your trend portfolio"), h("p", "The 8-asset 10-month rule, sized to your " + fmt.money0(p.budget) + " budget")),
      h("div.row", { style: "justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:10px" },
        h("div.soft", "Holding ", h("strong", p.holding.length + " of " + p.assets.length), ": ", h("strong", fmt.money0(p.invested)), " invested, ",
          h("strong", fmt.money0(p.cash)), " in cash or T-bills (" + fmt.money0(p.slot) + " per asset)."),
        h("label.switch", toggle, "Alert me when it changes")),
      dataTable([
        { label: "Asset", cell: (a) => h("div", h("a.sym", { href: "#/stock/" + encodeURIComponent(a.symbol) }, a.name), h("div.sym-name", a.symbol)) },
        { label: "Rule says", cell: (a) => (!a.signal ? h("span.muted.small", "No data") : h("div",
            a.signal.holding ? pill("bullish", "Hold") : pill("bearish", "Cash"),
            h("div.small", { style: "margin-top:3px" }, h("span." + signClass(a.signal.gap_pct), fmt.pct(a.signal.gap_pct, 1)), h("span.muted", " vs average")))) },
        { label: band ? "Buy above / sell below" : "Average", right: true, hideSmall: true, cell: (a) => (!a.signal ? "—" : band
            ? h("div.small", h("div", (a.signal.holding ? h("span.muted", fmt.num(a.signal.buy_level, 2)) : h("strong", fmt.num(a.signal.buy_level, 2)))),
                h("div", a.signal.holding ? h("strong", fmt.num(a.signal.sell_level, 2)) : h("span.muted", fmt.num(a.signal.sell_level, 2))))
            : fmt.num(a.signal.average, 2)) },
        { label: "Amount", right: true, cell: (a) => (a.amount ? fmt.money0(a.amount) : h("span.muted", "$0")) },
        { label: "Since", right: true, hideSmall: true, cell: (a) => (a.signal ? fmt.date(a.signal.since) : "—") },
        { label: "At month end", hideSmall: true, cell: (a) => (!a.signal ? "" : a.signal.flip_pending
            ? h("span.tag", { style: "background:var(--warn-wash);color:var(--ink)" }, a.signal.holding ? "Would sell if it ends here" : "Would buy if it ends here")
            : h("span.muted.small", "No change")) },
      ], p.assets),
      h("p.small", { style: "margin-top:8px" }, h("strong", "Next check: "), "after the close on " + fmt.date(p.next_check) +
        " (the month's last trading day). " + (pending.length ? pending.length + " asset" + (pending.length > 1 ? "s are" : " is") + " past " + (band ? "a buy or sell level" : "the average") + " right now, so a change is possible." : "No asset is past " + (band ? "a buy or sell level" : "the average") + " right now.")),
      h("div.row", { style: "margin-top:8px;gap:8px" }, h("span.small", h("strong", "Whipsaw band: ")), bandSelect),
      h("p.small.soft", { style: "margin-top:4px" }, band
        ? "Buys only when a month ends more than " + band + "% above the 10-month average and sells only when one ends more than " + band + "% below; in between it keeps what it has. On 2016–2026 data the 2% band was not chosen on, it halved the trades and cut losing trades from 62% to 45%, with about the same return."
        : "Original rule: buys on any month-end close above the average and sells on any close below, which trades about twice as often and loses on more trades."),
      changes.length ? h("div", { style: "margin-top:10px" }, h("h3.small", "Recent changes"),
        h("ul.small.soft", { style: "margin:4px 0 0;padding-left:18px" }, changes.map((c) => h("li", fmt.date(c.date) + ": ",
          c.bought.length ? h("span.up", "bought " + c.bought.join(", ")) : null, c.bought.length && c.sold.length ? "; " : null,
          c.sold.length ? h("span.down", "sold " + c.sold.join(", ")) : null, " (holding " + c.holding + ")")))) : null,
      h("p.muted.small", { style: "margin-top:8px" }, "Prices are checked once a month. In the 2007–2026 test below this portfolio had by far the smallest crashes but earned less than a plain 60/40 mix. Amounts are a guide: round to whole shares, and in a taxable account selling can trigger taxes."));
  }

  function edge(v) { return h("span." + signClass(v), (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2)); }

  function marketTable(data) {
    const classes = ["All", ...new Set(data.markets.map((m) => m.class))];
    const rows = data.markets.filter((m) => classFilter === "All" || m.class === classFilter);
    const watched = new Set((state.overview ? state.overview.watchlist : []).map((w) => w.symbol));
    return h("div.stack",
      h("div.chips", classes.map((c) => h("button.chip" + (classFilter === c ? ".on" : ""), { onclick: () => { classFilter = c; render(); } }, c))),
      h("section.card", dataTable([
        { label: "Market", cell: (m) => h("div", h("a.sym", { href: "#/stock/" + encodeURIComponent(m.symbol) }, m.name), h("div.sym-name", m.symbol + " · " + m.class)) },
        { label: "Price", right: true, cell: (m) => (m.live.error ? "—" : fmt.num(m.live.price, m.live.price < 10 ? 3 : 2)) },
        { label: "Today", right: true, cell: (m) => (m.live.error ? "—" : h("span." + (signClass(m.live.change_pct) || "soft"), fmt.pct(m.live.change_pct, 2))) },
        { label: "1 year", right: true, hideSmall: true, cell: (m) => (m.live.return_1y_pct === null || m.live.return_1y_pct === undefined ? "—" : h("span." + signClass(m.live.return_1y_pct), fmt.pct(m.live.return_1y_pct, 1))) },
        { label: "Year", hideSmall: true, cell: (m) => (m.live.spark ? sparkline(m.live.spark) : "") },
        { label: "Trend (10-month rule)", cell: (m) => (m.live.error ? h("span.muted.small", "No data") : m.live.trend_hold ? pill("bullish", "Uptrend: hold") : pill("bearish", "Downtrend: cash")) },
        { label: "What testing found", hideSmall: true, cell: (m) => (m.tested ? h("div.small",
            h("div", pill(m.tested.tone, m.tested.trend_wins + " of 4 trend rules beat holding")),
            h("div.muted", { style: "margin-top:3px" }, "Holding: " + fmt.pct(m.tested.hold.cagr_pct, 1) + "/yr, worst drop " + fmt.pct(m.tested.hold.max_drawdown_pct, 0) + " · " + m.tested.years + " yrs"))
            : h("span.muted.small", "Not tested")) },
        { label: "Alerts", cell: (m) => alertButton(m.symbol) },
        { label: "", cell: (m) => (watched.has(m.symbol) ? h("span.tag", "Watching")
            : h("button.btn.small", { onclick: async (e) => { e.target.disabled = true; try { await api("/api/watchlist", { method: "POST", body: { symbol: m.symbol } }); await refreshOverview(); e.target.replaceWith(h("span.tag", "Watching")); } catch (err) { e.target.disabled = false; toast({ title: "Could not add " + m.symbol, body: err.message, tone: "warning" }); } } }, "Watch")) },
      ], rows, { onRow: (m) => { location.hash = "#/stock/" + encodeURIComponent(m.symbol); } })),
      trend ? h("p.small.soft", "🔔 = you get an alert (in the app, and on your phone if push is set up) when that market's 10-month rule changes, on the first scan after a month's last close. " +
        (trend.alerts.using_default ? "Turned on by default for the markets where most trend rules beat holding in testing." : ""),
        trend.alerts.using_default ? null : h("button.btn.ghost.small", { onclick: () => setAlerts(null) }, "Reset to the tested trend-friendly markets")) : null,
      h("p.muted.small", "Trend (10-month rule): hold while the last month-end close is above its 10-month average, otherwise cash" + (data.band_pct ? " (with your " + data.band_pct + "% whipsaw band: buy only that far above the average, sell only that far below)" : "") + ". “What testing found” counts how many of four trend rules (10-month average, 200-day average, 50/200 crossover, 55-day breakout) beat holding that market on a risk-adjusted basis over its whole history, with costs. With several rules per market some will win by luck, so agreement matters more than any single winner. Futures prices (=F) ignore the cost of rolling contracts."));
  }

  function detailTable(data) {
    const rules = Object.keys(data.rules);
    const tested = data.markets.filter((m) => m.tested);
    return h("section.card",
      h("div.card-head", h("h2", "Every rule on every market"), h("p", "Sharpe ratio above T-bills minus holding's, whole history; ✓ = better in both halves")),
      dataTable([
        { label: "Market", cell: (m) => h("span", m.name) },
        { label: "Years", right: true, hideSmall: true, cell: (m) => m.tested.years },
        ...rules.map((k) => ({ label: data.rules[k], right: true, hideSmall: k === "rsi" || k === "app", cell: (m) => {
          const r = m.tested.rules[k]; return h("span", edge(r.edge), r.consistent ? h("span.up", { title: "Beat holding in both halves of history" }, " ✓") : ""); } })),
      ], tested));
  }

  function faberCard(f) {
    if (!f) return null;
    const names = { trend: "Trend portfolio (10-month rule)", hold_same: "Hold the same 8", spy: "S&P 500", sixty_forty: "60% stocks / 40% bonds" };
    const chart = lineChart({ dates: f.curve.dates, height: 240, label: "Growth of $100", yFormat: (x) => "$" + (Math.round(x) || 0).toLocaleString("en-US"),
      series: [
        { name: names.trend, color: "var(--series-1)", values: f.curve.trend },
        { name: names.hold_same, color: "var(--series-2)", values: f.curve.hold_same },
        { name: names.sixty_forty, color: "var(--series-3)", values: f.curve.sixty_forty },
      ] });
    const keys = ["trend", "hold_same", "sixty_forty", "spy"];
    const pct = (x) => fmt.pct(x, 1);
    return h("section.card",
      h("div.card-head", h("h2", "Diversified trend portfolio"), h("p", "Faber's 10-month rule across 8 asset classes, unchanged from the 2007 paper, since " + fmt.date(f.start))),
      h("p.soft", "Equal shares of US, foreign and emerging stocks, real estate, Treasury bonds, inflation-linked bonds, commodities and gold. Each month, an asset is held only while it is above its 10-month average; otherwise that share sits in T-bills."),
      chart.legend, h("div", { style: "margin-top:8px" }, chart.node),
      dataTable([
        { label: "", cell: (k) => names[k] },
        { label: "Yearly return", right: true, cell: (k) => pct(f.metrics[k].cagr_pct) },
        { label: "Worst drop", right: true, cell: (k) => pct(f.metrics[k].max_drawdown_pct) },
        { label: "Volatility", right: true, hideSmall: true, cell: (k) => f.metrics[k].volatility_pct.toFixed(1) + "%" },
        { label: "Sharpe", right: true, cell: (k) => f.metrics[k].sharpe.toFixed(2) },
        { label: "2008", right: true, hideSmall: true, cell: (k) => pct(f.yearly[k]["2008"]) },
        { label: "2022", right: true, hideSmall: true, cell: (k) => pct(f.yearly[k]["2022"]) },
      ], keys),
      h("p.small", { style: "margin-top:8px" }, h("strong", "Holding now: "),
        Object.entries(f.holding_now_live || f.holding_now).map(([s, on], i) => [i ? " · " : "", h("span" + (on ? ".up" : ".soft"), s + (on ? " ✓" : " (cash)"))])),
      h("p.muted.small", "It cut the worst drop to a fraction of the stock market's and lost far less in 2008 and 2022, but earned less than the S&P 500 or a plain 60/40 mix, which had the best return per unit of risk over this period."));
  }

  function persistenceCard(p) {
    if (!p) return null;
    const rows = Object.values(p.rules);
    return h("section.card",
      h("div.card-head", h("h2", "Which stocks are we best at?"), h("p", p.stocks + " stocks; rules ranked on 2003–2014, checked on 2015–2026")),
      h("div.note.warn", { style: "margin-bottom:10px" }, "Being good on a stock did not last. The stocks where a rule did best in 2003–2014 did about as badly as the rest in 2015–2026, so a “best stocks” list from the past is mostly a list of lucky ones."),
      dataTable([
        { label: "Rule", cell: (r) => r.label },
        { label: "Ranking carried over", right: true, cell: (r) => h("span", { title: "Rank correlation between the two periods (1 = same order, 0 = unrelated)" }, (r.rank_corr_A_vs_B >= 0 ? "+" : "") + r.rank_corr_A_vs_B.toFixed(2)) },
        { label: "Top fifth, 2003–14", right: true, cell: (r) => edge(r.top_quintile_edge_A) },
        { label: "Same stocks, 2015–26", right: true, cell: (r) => edge(r.top_quintile_edge_B) },
        { label: "Bottom fifth, 2015–26", right: true, hideSmall: true, cell: (r) => edge(r.bottom_quintile_edge_B) },
        { label: "Beat holding 2015–26", right: true, hideSmall: true, cell: (r) => r.share_beating_hold_B + "%" },
      ], rows),
      h("p.small.soft", { style: "margin-top:8px" }, "The one trait that carried over a little: trend rules lost less on more volatile, higher-beta stocks (for the 10-month rule, " +
        p.rules.faber.edge_B_by_volatility_A[0].beating_hold_B_pct + "% of the calmest fifth beat holding later vs " + p.rules.faber.edge_B_by_volatility_A[3].beating_hold_B_pct +
        "% of the second-most volatile fifth), but even there most stocks were better held. How smoothly a stock had trended before predicted nothing."));
  }

  function render() {
    const data = markets;
    fill(body,
      data.tested_available ? h("div.note", "Testing found trend rules most useful in commodity funds (oil, natural gas, broad commodities, farm goods), where simply holding lost money over time, and in Ether. In gold, bonds, real estate and most stock markets, holding did as well or better.") : null,
      marketTable(data), trackerCard(), faberCard(data.faber), persistenceCard(data.persistence), data.tested_available ? detailTable(data) : null);
  }

  Promise.all([api("/api/markets"), api("/api/trend").catch(() => null)])
    .then(([m, t]) => { markets = m; trend = t; render(); })
    .catch((e) => fill(body, h("div.card", h("div.empty", e.message))));
  return {};
}

/* ---- indicator lab ---- */
function labPage(root) {
  const body = h("div.stack");
  fill(root, pageHead("Indicator lab", "Change an indicator's settings and see how it would have traded any stock over the last 10 years."), body);
  let catalog = [], results = null, current = null, lastRun = null;

  const symbolInput = h("input.input", { value: (state.overview && state.overview.watchlist[0] && state.overview.watchlist[0].symbol) || "AAPL",
    "aria-label": "Ticker", style: "width:110px;text-transform:uppercase" });
  const tacticSelect = h("select.input", { "aria-label": "Indicator" });
  const paramHost = h("div.lab-params");
  const resultHost = h("div");
  const runBtn = h("button.btn.primary", { onclick: run }, "Run test");
  const inputs = {};

  function paramFields(t, values) {
    fill(paramHost, t.params.map((p) => {
      const v = values[p.key] ?? p.default;
      let input;
      if (p.kind === "bool") {
        input = h("input", { type: "checkbox", checked: !!v });
        inputs[p.key] = () => (input.checked ? 1 : 0);
        return h("label.switch", { title: p.help }, input, p.label);
      }
      input = h("input", { type: "number", min: p.min, max: p.max, step: p.step, value: v, inputMode: "decimal" });
      const slider = h("input", { type: "range", min: p.min, max: p.max, step: p.step, value: v, "aria-label": p.label });
      slider.addEventListener("input", () => { input.value = slider.value; });
      input.addEventListener("input", () => { slider.value = input.value; });
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
      slider.addEventListener("change", run);
      inputs[p.key] = () => Number(input.value);
      return h("div.field", h("label", p.label), h("div.row", { style: "flex-wrap:nowrap" }, slider, h("div.input-affix", { style: "width:90px;flex:none" }, input)),
        p.help ? h("div.hint", p.help) : null);
    }));
  }

  function selectTactic(key, values) {
    current = catalog.find((t) => t.key === key);
    tacticSelect.value = key;
    for (const k of Object.keys(inputs)) delete inputs[k];
    paramFields(current, values || {});
    fill(tacticNote, current.summary, current.tested ? [" Tested-best settings: ", h("strong", current.tested.best_label), "."] : null);
  }
  const tacticNote = h("p.soft.small");
  tacticSelect.addEventListener("change", () => { selectTactic(tacticSelect.value); run(); });

  function params() {
    const out = {};
    for (const [k, get] of Object.entries(inputs)) out[k] = get();
    return out;
  }

  async function run() {
    if (!current) return;
    runBtn.disabled = true; runBtn.textContent = "Testing…";
    try {
      lastRun = await api("/api/lab/run", { method: "POST", body: { symbol: symbolInput.value.trim().toUpperCase(), tactic: current.key, params: params() } });
      fill(resultHost, renderRun(lastRun));
    } catch (e) {
      fill(resultHost, h("div.note.warn", e.message));
    }
    runBtn.disabled = false; runBtn.textContent = "Run test";
  }

  function renderRun(r) {
    const s = r.strategy, hd = r.hold;
    const tvHost = h("div");
    const better = (a, b, higher = true) => (a === null || b === null ? "" : (higher ? a > b : a < b) ? ".up" : ".down");
    const price = lineChart({ dates: r.chart.dates, height: 240, label: r.symbol + " price, highlighted while the indicator holds it",
      series: [
        { name: "Price", color: "var(--axis)", values: r.chart.price },
        { name: "Indicator holding", color: "var(--series-1)", values: r.chart.holding_price },
      ] });
    const growth = lineChart({ dates: r.chart.dates, height: 200, label: "Growth of $100", yFormat: (x) => "$" + (Math.round(x) || 0).toLocaleString("en-US"),
      series: [
        { name: r.label, color: "var(--series-1)", values: r.chart.strategy },
        { name: "Buy and hold " + r.symbol, color: "var(--series-2)", values: r.chart.hold },
      ] });
    const row = (label, a, b, f, higher = true) => h("tr", h("td", label), h("td.r.num" + better(a, b, higher), f(a)), h("td.r.num", f(b)));
    const pct = (x) => (x === null || x === undefined ? "—" : fmt.pct(x, 1));
    return h("div.stack",
      h("div.row", h("h3", r.symbol + ": " + r.label), r.holding_now ? pill("bullish", "Holding now") : pill("neutral", "In cash now"),
        h("span.muted.small", r.start + " to " + r.end)),
      h("div.grid-2",
        h("div.table-wrap", h("table",
          h("thead", h("tr", h("th", ""), h("th.r", "Indicator"), h("th.r", "Buy and hold"))),
          h("tbody",
            row("Yearly return", s.cagr_pct, hd.cagr_pct, pct),
            row("Total return", s.total_return_pct, hd.total_return_pct, (x) => fmt.pct(x, 0)),
            row("Worst drop", s.max_drawdown_pct, hd.max_drawdown_pct, pct),
            row("Sharpe ratio", s.sharpe, hd.sharpe, (x) => (x === null || x === undefined ? "—" : x.toFixed(2)))))),
        h("div.metrics",
          h("div.metric", h("div.k", "Time holding"), h("div.v", r.stats.time_in_market_pct + "%")),
          h("div.metric", h("div.k", "Trades"), h("div.v", r.stats.trades)),
          h("div.metric", h("div.k", "Winning trades"), h("div.v", r.stats.win_rate_pct === null ? "—" : r.stats.win_rate_pct + "%")),
          h("div.metric", h("div.k", "Average trade"), h("div.v", r.stats.avg_trade_pct === null ? "—" : fmt.pct(r.stats.avg_trade_pct, 2))),
          r.open_trade ? h("div.metric", h("div.k", "Open trade"), h("div.v", fmt.pct(r.open_trade.return_pct, 1))) : null)),
      price.legend, price.node, growth.legend, growth.node,
      h("p.muted.small", "Signals use each day's close and trade at the next open, with 0.1% cost per trade; cash earns T-bill interest. One stock over one decade is a tiny sample: a setting that looks great here is usually luck. Compare with the tested results below."),
      h("div.row",
        h("button.btn", { onclick: (e) => { e.target.disabled = true; tvHost.append(tradingViewChart(r.symbol, r.tactic, r.params, 520)); } }, "Show on TradingView"),
        h("button.btn", { onclick: () => pineModal(r.tactic, r.params, r.label) }, "Get Pine Script for TradingView")),
      tvHost,
      r.trades.length ? h("details", h("summary.small", "Recent trades (" + r.trades.length + ")"),
        dataTable([
          { label: "Bought", cell: (t) => fmt.date(t.entry_date) + " @ " + fmt.money(t.entry) },
          { label: "Sold", cell: (t) => fmt.date(t.exit_date) + " @ " + fmt.money(t.exit) },
          { label: "Days", right: true, cell: (t) => t.days },
          { label: "Return", right: true, cell: (t) => h("span." + signClass(t.return_pct), fmt.pct(t.return_pct, 1)) },
        ], r.trades)) : null);
  }

  async function saveAlert() {
    if (!current) return;
    await api("/api/settings", { method: "PUT", body: { my_tactic: { tactic: current.key, params: params() } } });
    await refreshOverview();
    renderMine();
    toast({ title: "Saved as your indicator alert", body: "You'll get an alert when it says buy or sell on any stock in your watchlist.", tone: "bullish" });
  }

  const mineHost = h("div");
  function renderMine() {
    const mine = state.overview.settings.my_tactic;
    if (!mine || !mine.tactic) {
      fill(mineHost, h("p.soft.small", "No indicator alert saved. Set up a tactic above and choose “Use as my alert” to get buy and sell alerts for your watchlist."));
      return;
    }
    const t = catalog.find((x) => x.key === mine.tactic);
    fill(mineHost, h("div.row", h("span", "Your alert: ", h("strong", t ? t.name : mine.tactic), " ", h("span.soft", JSON.stringify(mine.params).replace(/[{}"]/g, "").replace(/,/g, ", "))),
      h("button.btn.small", { onclick: () => { selectTactic(mine.tactic, mine.params); run(); } }, "Load"),
      h("button.btn.small.ghost", { onclick: async () => { await api("/api/settings", { method: "PUT", body: { my_tactic: {} } }); await refreshOverview(); renderMine(); } }, "Remove")));
  }

  function findingsCard() {
    if (!results) return null;
    const fams = results.families;
    const edge = (x) => h("span." + signClass(x), (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(2));
    const anyHeld = fams.some((f) => f.validation_edge > 0 && f.test_edge > 0);
    return h("section.card",
      h("div.card-head", h("h2", "What testing found"), h("p", results.settings_total + " settings across " + fams.length + " indicators, " +
        (results.groups.train + results.groups.holdout + results.groups.test) + " stocks, 2003–2026")),
      h("div.note" + (anyHeld ? "" : ".warn"), { style: "margin-bottom:10px" },
        anyHeld ? "Some settings held up on unseen data; see the table." :
          "No indicator setting beat simply holding the same stocks on data it was not tuned on. Settings that looked best in training lost their edge on new stocks and later years, the same overfitting that happens when a model memorises its training data."),
      dataTable([
        { label: "Indicator", cell: (f) => h("div", h("div", f.name), h("div.small.muted", f.style === "trend" ? "Trend" : "Mean reversion")) },
        { label: "Best settings in training", cell: (f) => h("span.small", f.best_label) },
        { label: "Training", right: true, cell: (f) => edge(f.train_edge) },
        { label: "Unseen data", right: true, cell: (f) => edge(f.validation_edge) },
        { label: "New stocks", right: true, cell: (f) => edge(f.test_edge) },
        { label: "Rankings agree?", right: true, hideSmall: true, cell: (f) => h("span", { title: "How well the training ranking of settings predicted the unseen-data ranking (1 = perfectly, 0 = not at all)" }, f.rank_corr_train_vs_validation.toFixed(2)) },
        { label: "S&P 500 timing (Sharpe vs hold)", right: true, hideSmall: true, cell: (f) => h("span.small",
            ["2003_2014", "2015_now"].map((p) => f.spy[p].sharpe.toFixed(2) + " vs " + f.spy[p].hold.sharpe.toFixed(2)).join(" · ")) },
      ], fams),
      h("p.muted.small", { style: "margin-top:8px" }, "Edge = Sharpe ratio (returns above T-bills) minus that of holding the same stocks, with the tactic trading one shared pot of money across all signalling stocks (max 10% each). Training: 2003–2014 on " + results.groups.train +
        " stocks. Unseen data: other stocks and later years. New stocks: " + results.groups.test + " stocks used for nothing else. On the S&P 500 itself, trend indicators beat holding in 2003–2014 (thanks to 2008) and lagged since 2015."));
  }

  Promise.all([api("/api/lab/tactics"), api("/api/lab/results").catch(() => null)]).then(([cat, res]) => {
    catalog = cat; results = res;
    fill(tacticSelect, catalog.map((t) => h("option", { value: t.key }, t.name)));
    const mine = state.overview.settings.my_tactic;
    selectTactic(mine && mine.tactic ? mine.tactic : "ma_cross", mine && mine.tactic ? mine.params : {});
    fill(body,
      h("section.card",
        h("div.card-head", h("h2", "Try it"), h("p", "Settings work like a model's weights: change them and see what happens")),
        h("div.row", { style: "align-items:flex-end;margin-bottom:10px" },
          h("div.field", h("label", "Stock"), symbolInput), h("div.field", { style: "flex:1;min-width:200px" }, h("label", "Indicator"), tacticSelect)),
        tacticNote, paramHost,
        h("div.row", { style: "margin-top:12px" }, runBtn,
          h("button.btn", { onclick: () => { selectTactic(current.key, current.tested ? current.tested.best_params : {}); run(); } }, "Use tested-best settings"),
          h("button.btn", { onclick: () => { selectTactic(current.key, {}); run(); } }, "Reset to defaults"),
          h("button.btn", { onclick: saveAlert }, "Use as my alert")),
        h("div", { style: "margin-top:16px" }, resultHost)),
      h("section.card", h("div.card-head", h("h2", "My indicator alert")), mineHost),
      findingsCard());
    renderMine();
    run();
  }).catch((e) => fill(body, h("div.card", h("div.empty", e.message))));
  symbolInput.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
  return {};
}

/* ---- track record (historical validation) ---- */
const CELL_LABELS = {
  train_2015_now: ["Later years", "Same stocks, 2015 to today: years the rules were never tuned on"],
  holdout_2015_now: ["Unseen stocks, recent", "Different stocks, 2015 to today"],
  holdout_2003_2014: ["Unseen stocks, 2003–2014", "Different stocks through the 2008 crash"],
  train_2003_2014: ["Training data", "The stocks and years used to choose between rule variants"],
};

function trackRecordPage(root) {
  let cell = "train_2015_now";
  let which = "chosen";
  let report = null;
  let stops = null;
  let experiments = null;
  let scorecard = null;
  let scoreKey = null;
  let entries = null;
  let profit = null;
  let profitTest = "sp_long";
  let recent = null;
  const body = h("div.stack");
  fill(root, pageHead("Track record", "The rules replayed day by day on 20+ years of past prices, then checked against what happened next, on stocks and years they were not tuned on."), body);

  const check = (ok, label) => h("div.row", { style: "gap:8px" },
    h("span.pill." + (ok ? "bullish" : "bearish"), ok ? "✓ Yes" : "✗ No"), h("span", label));
  const pct = (x, digits = 1) => (x === null || x === undefined ? "—" : fmt.pct(x, digits));

  function render() {
    const r = report;
    const port = r.portfolio[which][cell];
    const study = r.signal_study[cell];
    const v = r.verdict[which][cell];
    const rules = which === "chosen" ? r.chosen_rules : r.baseline_rules;
    const testCells = r.design.test_cells;
    const passed = testCells.filter((c) => r.verdict[which][c].holds_up).length;

    const cellChips = h("div.chips", Object.entries(CELL_LABELS).map(([key, [label]]) =>
      h("button.chip" + (cell === key ? ".on" : ""), { onclick: () => { cell = key; render(); } }, label)));
    const rulesChips = h("div.chips", [["chosen", "Best rules: " + r.chosen_rules.name], ["baseline", "Original app rules"]].map(([key, label]) =>
      h("button.chip" + (which === key ? ".on" : ""), { onclick: () => { which = key; render(); } }, label)));

    const summary = h("section.card",
      h("div.card-head", h("h2", "Does it hold up?"), h("p", "Judged only on data the rules were not tuned on")),
      h("p", { style: "font-size:15px" }, h("strong", passed + " of " + testCells.length), " test periods pass every check for ", h("strong", rules.name), "."),
      h("div.table-wrap", { style: "margin-top:10px" }, h("table",
        h("thead", h("tr", h("th", "Test"), h("th", "Buy signals beat the market"), h("th", "Made money"), h("th", "Beat buy-and-hold"), h("th", "Overall"))),
        h("tbody", testCells.map((c) => {
          const vv = r.verdict[which][c];
          const mark = (ok) => h("td", h("span.pill." + (ok ? "bullish" : "bearish"), ok ? "✓" : "✗"));
          return h("tr", h("td", CELL_LABELS[c][0]), mark(vv.buy_signals_beat_market), mark(vv.profitable), mark(vv.beats_buy_and_hold), mark(vv.holds_up));
        })))),
      h("p.muted.small", { style: "margin-top:8px" }, "Beat buy-and-hold means a better Sharpe ratio (return per unit of risk) than holding the same stocks, or a third smaller worst drop while keeping at least 60% of the yearly return."));

    const s = port.strategy, spy = port.spy, ew = port.equal_weight;
    const chart = lineChart({
      dates: port.curve.dates, height: 260, label: "Growth of $100",
      yFormat: (x) => "$" + (Math.round(x) || 0).toLocaleString("en-US"),
      series: [
        { name: "Following the rules", color: "var(--series-1)", values: port.curve.strategy },
        { name: "S&P 500 (SPY)", color: "var(--series-2)", values: port.curve.spy },
        { name: "Buy and hold the same stocks", color: "var(--series-3)", values: port.curve.equal_weight },
      ],
    });
    const row = (label, key, f = pct) => h("tr", h("td", label), [s, spy, ew].map((m) => h("td.r.num", f(m[key]))));
    const portfolioCard = h("section.card",
      h("div.card-head", h("h2", "Portfolio: $100,000 following the rules"), h("p", CELL_LABELS[cell][1])),
      chart.legend, h("div", { style: "margin-top:8px" }, chart.node),
      h("div.table-wrap", { style: "margin-top:12px" }, h("table",
        h("thead", h("tr", h("th", ""), h("th.r", "Rules"), h("th.r", "S&P 500"), h("th.r", "Hold same stocks"))),
        h("tbody",
          row("Yearly return", "cagr_pct", (x) => pct(x, 1)),
          row("Total return", "total_return_pct", (x) => pct(x, 0)),
          row("Worst drop", "max_drawdown_pct"),
          row("Sharpe ratio", "sharpe", (x) => (x === null || x === undefined ? "—" : x.toFixed(2))),
          row("Volatility", "volatility_pct", (x) => (x === null || x === undefined ? "—" : x.toFixed(1) + "%"))))),
      h("div.metrics", { style: "margin-top:12px" },
        h("div.metric", h("div.k", "Trades"), h("div.v", fmt.num(s.trades))),
        h("div.metric", h("div.k", "Winning trades"), h("div.v", s.win_rate_pct + "%")),
        h("div.metric", h("div.k", "Average win"), h("div.v", pct(s.avg_win_pct))),
        h("div.metric", h("div.k", "Average loss"), h("div.v", pct(s.avg_loss_pct))),
        h("div.metric", h("div.k", "Profit factor"), h("div.v", s.profit_factor ?? "—")),
        h("div.metric", h("div.k", "Days held (avg)"), h("div.v", s.avg_days_held)),
        h("div.metric", h("div.k", "Time invested"), h("div.v", s.invested_pct + "%"))),
      h("p.muted.small", { style: "margin-top:8px" }, "Includes " + r.design.cost_bps_per_side + " basis points of cost on every buy and sell. Profit factor is total gains divided by total losses."));

    const ev = study.events;
    const signalTable = (kind) => dataTable([
      { label: "Held for", cell: (e) => ({ 5: "1 week", 20: "1 month", 60: "3 months", 120: "6 months" }[e.horizon]) },
      { label: "Signals", right: true, cell: (e) => fmt.num(e.signals) },
      { label: kind === "buy" ? "Beat the market" : "Lagged the market", right: true, cell: (e) => h("strong", e.win_rate + "%") },
      { label: "Avg vs market", right: true, cell: (e) => h("span." + signClass(kind === "buy" ? e.avg_excess : -e.avg_excess), pct(e.avg_excess, 2)) },
      { label: "Stock went up", right: true, hideSmall: true, cell: (e) => e.rose_rate + "%" },
      { label: "Confidence (t)", right: true, hideSmall: true, cell: (e) => (e.t_stat === null ? "—" : e.t_stat.toFixed(1)) },
    ], ev.filter((e) => e.kind === kind));
    const states = dataTable([
      { label: "When the app said", cell: (x) => pill(x.state === "buy" ? "bullish" : x.state === "sell" ? "bearish" : "neutral", x.state[0].toUpperCase() + x.state.slice(1)) },
      { label: "Stock-days", right: true, cell: (x) => fmt.num(x.stock_days) },
      { label: "Next month vs market", right: true, cell: (x) => h("span." + signClass(x.avg_excess_20d), pct(x.avg_excess_20d, 2)) },
      { label: "Beat the market", right: true, cell: (x) => x.beat_market + "%" },
    ], study.states);
    const signalCard = h("section.card",
      h("div.card-head", h("h2", "Signals: what happened after the app said Buy or Sell"), h("p", CELL_LABELS[cell][1])),
      h("h3", { style: "margin:4px 0 6px" }, "Each new Buy signal"), signalTable("buy"),
      h("h3", { style: "margin:14px 0 6px" }, "Each new Sell signal"), signalTable("sell"),
      h("h3", { style: "margin:14px 0 6px" }, "Every day, by signal"), states,
      h("p.muted.small", { style: "margin-top:8px" }, "Entered at the next day's open, compared with the S&P 500 over the same days. Confidence above about 2 means the result is unlikely to be luck; it treats each month as one observation because signals bunch together."));

    const years = Object.keys(port.yearly.strategy);
    const yearCard = h("section.card",
      h("div.card-head", h("h2", "Year by year")),
      dataTable([
        { label: "Year", cell: (y) => y },
        { label: "Rules", right: true, cell: (y) => h("span." + signClass(port.yearly.strategy[y]), pct(port.yearly.strategy[y])) },
        { label: "S&P 500", right: true, cell: (y) => pct(port.yearly.spy[y]) },
        { label: "Hold same stocks", right: true, cell: (y) => pct(port.yearly.equal_weight[y]) },
        { label: "Buy signals beat market (3 mo)", right: true, hideSmall: true, cell: (y) => {
          const b = study.buy_60d_by_year[y]; return b ? b.win_rate + "% of " + b.signals : "—"; } },
      ], years.slice().reverse()));

    const searchCard = h("section.card",
      h("div.card-head", h("h2", "Rule variants tried"), h("p", "Training data only (" + r.design.train + "). The best is then tested once on the other periods.")),
      dataTable([
        { label: "Variant", cell: (x) => h("div", h("div", { style: x.name === r.chosen_rules.name ? "font-weight:700" : "" }, x.name, x.name === r.chosen_rules.name ? h("span.tag", { style: "margin-left:6px" }, "Chosen") : null), x.notes ? h("div.small.muted", x.notes) : null) },
        { label: "Yearly", right: true, cell: (x) => pct(x.cagr_pct) },
        { label: "Worst drop", right: true, cell: (x) => pct(x.max_drawdown_pct) },
        { label: "Sharpe", right: true, cell: (x) => (x.sharpe ?? "—") },
        { label: "Trades", right: true, hideSmall: true, cell: (x) => fmt.num(x.trades) },
        { label: "Win rate", right: true, hideSmall: true, cell: (x) => x.win_rate_pct + "%" },
      ], r.search.slice().sort((a, b) => (b.sharpe ?? -9) - (a.sharpe ?? -9))));

    const caveats = h("section.card", h("h2", "What this test cannot tell you"),
      h("ul.small.soft", { style: "margin:8px 0 0;padding-left:18px" },
        h("li", "Only stocks that still exist today could be downloaded, so companies that went bust are missing. That flatters every long-only result, including buy-and-hold."),
        h("li", "Insider trades and news tone are not replayed (no free history). They are 25 of the score's 100 points in the live app."),
        h("li", "Options ideas are not tested: free historical option prices do not exist."),
        h("li", "Past results do not guarantee future ones, and markets change once rules become popular.")),
      h("p.muted.small", { style: "margin-top:8px" }, "Run on " + new Date(r.generated).toLocaleString() + ". Rerun with: python -m stockanalysis.validation"));

    fill(body, recent ? recentCard(recent) : null, profit ? profitStudyCard(profit) : null, scorecard ? scorecardCard(scorecard) : null, entries ? entriesCard(entries) : null, ...storyCards(r), experiments ? experimentsCard(experiments) : null, stops ? stopsCard(stops) : null, h("h2", { style: "margin-top:12px;font-size:18px" }, "Round 1 in detail: the app's own Buy and Sell rules"),
      h("div.row", rulesChips), summary, h("div.row", cellChips), portfolioCard, signalCard, yearCard, searchCard, caveats);
  }

  function recentCard(rc) {
    const m = rc.methods, ins = rc.insiders;
    const cell = (x) => (!x || x.return_pct === null || x.return_pct === undefined ? "—"
      : h("div", h("strong." + signClass(x.return_pct), fmt.pct(x.return_pct, 1)), h("div.small.muted", "worst " + fmt.pct(x.max_drawdown_pct, 0))));
    const insiderRows = ins && ins.variants ? Object.values(ins.variants) : [];
    const ex = (x) => (!x ? "—" : h("div", h("span." + signClass(x.avg_excess_pct), fmt.pct(x.avg_excess_pct, 1)), h("div.small.muted", "beat " + x.beat_market_pct + "% · n " + x.n)));
    return h("section.card",
      h("div.card-head", h("h2", "Recent market"), h("p", "Data to " + fmt.date(m.as_of) + "; short periods are mostly luck")),
      dataTable([
        { label: "Method", cell: (r) => r.label },
        { label: "Last 12 months", right: true, cell: (r) => cell(r["12m"]) },
        { label: "Since 2024", right: true, cell: (r) => cell(r.since_2024) },
        { label: m.as_of.slice(0, 4) + " so far", right: true, hideSmall: true, cell: (r) => cell(r.ytd) },
      ], Object.values(m.rows)),
      insiderRows.length ? h("div", { style: "margin-top:12px" }, h("h3", "Copying insider purchases, last two years"),
        h("p.small.soft", ins.purchases + " purchases in " + ins.stocks + " of the app's test stocks (" + fmt.date(ins.first) + " to " + fmt.date(ins.last) + "), bought three trading days after each trade. Return over the S&P 500 for the same days:"),
        dataTable([
          { label: "Copy rule", cell: (v) => v.label },
          { label: "1 month", right: true, cell: (v) => ex(v.h21) },
          { label: "3 months", right: true, cell: (v) => ex(v.h63) },
          { label: "6 months", right: true, cell: (v) => ex(v.h126) },
        ], insiderRows)) : null,
      h("p.muted.small", { style: "margin-top:8px" }, "Full tables: docs/RECENT.md. The long tests above decide whether a method works; this checks how it has done lately."));
  }

  function profitStudyCard(pr) {
    const tests = Object.entries(pr.tests).filter(([k]) => k !== "dual_momentum");
    const t = pr.tests[profitTest] || tests[0][1];
    const rows = Object.entries(t.rows).sort((a, b) => b[1].cagr_pct - a[1].cagr_pct);
    const hold = t.rows.hold_1x;
    const dm = pr.tests.dual_momentum;
    return h("section.card",
      h("div.card-head", h("h2", "Maximum profit"), h("p", "Index funds, leverage and trend switches over 65 years")),
      h("div.note", { style: "display:block;margin-bottom:10px" }, h("strong", "What made the most money: leverage with a trend switch. "),
        "Holding a 2x or 3x index fund while the index is above its 200-day average (or the app's market switch is on), and T-bills otherwise, beat holding the index in every period tested. " +
        "Leverage held all the time was a disaster (3x lost 99% at worst). The more leverage, the more profit and the deeper the drops, so the Profit plan on the dashboard lets you choose."),
      h("div.chips", tests.map(([k, x]) => h("button.chip" + (k === profitTest ? ".on" : ""), { onclick: () => { profitTest = k; render(); } }, x.name.replace(/ \(.*\)/, "")))),
      h("p.small.muted", { style: "margin:6px 0" }, t.name),
      dataTable([
        { label: "Strategy", cell: ([k, x]) => h("span", { style: k === pr.chosen ? "font-weight:700" : "" }, x.label, k === pr.chosen ? h("span.tag", { style: "margin-left:6px" }, "Tested pick") : null) },
        { label: "Yearly return", right: true, cell: ([, x]) => h("span." + (x.cagr_pct > hold.cagr_pct ? "up" : ""), fmt.pct(x.cagr_pct, 1)) },
        { label: "Worst drop", right: true, cell: ([, x]) => h("span." + (x.max_drawdown_pct < hold.max_drawdown_pct ? "down" : ""), fmt.pct(x.max_drawdown_pct, 0)) },
        { label: "Worst year", right: true, hideSmall: true, cell: ([, x]) => fmt.pct(x.worst_year_pct, 0) + " (" + x.worst_year + ")" },
        { label: "$10k became", right: true, hideSmall: true, cell: ([, x]) => fmt.money0(x.growth_of_10k) },
      ], rows),
      h("p.small.soft", { style: "margin-top:8px" }, "Green return = more than holding; red drop = deeper than holding. Simulated leveraged funds match the real ones closely (" +
        pr.calibration.map((c) => c.fund + " " + fmt.pct(c.real_cagr_pct, 1) + " real vs " + fmt.pct(c.simulated_cagr_pct, 1) + " simulated").join(", ") + ")."),
      dm ? h("p.small.soft", "Dual momentum (US / foreign stocks / bonds) since " + dm.name.match(/\d{4}/)[0] + ": " + fmt.pct(dm.rows.dual_momentum.cagr_pct, 1) + " a year vs " +
        fmt.pct(dm.rows.hold_1x.cagr_pct, 1) + " for the S&P 500, so it is not used.") : null,
      h("p.muted.small", "Index tests from 1961 use prices without dividends for every row, so all returns are about 2 points a year low. Full tables: docs/PROFIT.md."));
  }

  function entriesCard(en) {
    const part = (p, title, selLabel, testLabel) => {
      const rows = Object.entries(p.variants);
      const v = p.test_verdict;
      const status = (k) => (k === "base" ? h("span.tag", "Now") : k === p.pick ? h("span.tag", { style: "background:var(--accent);color:var(--on-accent)" }, "Picked")
        : p.kept.includes(k) ? h("span.tag", "Kept") : h("span.muted.small", "Dropped"));
      return h("div", { style: "margin-top:12px" }, h("h3", title),
        dataTable([
          { label: "Entry filter", cell: ([k, x]) => h("div", h("div", x.label), x.filters ? h("div.small.muted", x.filters.join(" + ")) : null) },
          { label: "", cell: ([k]) => status(k) },
          { label: selLabel + ": losing trades", right: true, hideSmall: true, cell: ([, x]) => x.selection.losing_pct + "%" },
          { label: testLabel + ": losing trades", right: true, cell: ([, x]) => h("strong", x.test.losing_pct + "%") },
          { label: "Trades", right: true, hideSmall: true, cell: ([, x]) => fmt.num(x.test.trades) },
          { label: "Yearly return", right: true, cell: ([, x]) => fmt.pct(x.test.basket_cagr_pct, 1) },
          { label: "Sharpe", right: true, hideSmall: true, cell: ([, x]) => (x.test.basket_sharpe ?? 0).toFixed(2) },
        ], rows),
        v ? h("p.small", { style: "margin-top:6px" }, h("strong", "Picked before testing: "), p.variants[p.pick].label + ". On data it never saw, losing trades went from " +
          v.losing_pct[0] + "% to " + v.losing_pct[1] + "%, yearly return " + fmt.pct(v.cagr_pct[0], 1) + " → " + fmt.pct(v.cagr_pct[1], 1) + ", Sharpe " + v.sharpe[0] + " → " + v.sharpe[1] + ". " +
          (v.held_up ? "It held up." : "Fewer losing trades, but it did not keep the profits, so it is not used as a rule.")) : null);
    };
    return h("section.card",
      h("div.card-head", h("h2", "Cutting losing entries"), h("p", "Entry filters that delay or skip buys; exits unchanged")),
      h("div.note", { style: "display:block" }, h("strong", "What worked: a 2% band on the 10-month trend rule. "),
        "Buying only when a month ends more than 2% above the average (and selling only 2% below) cut losing trades and halved the number of trades with about the same return, on years it was not chosen on. It is now the default for market trend alerts and the trend portfolio (changeable on the Markets page). " +
        "For stocks, no combination helped: filters cut losers but cut winners too. Volume confirmation alone did best, so Buy alerts now say whether volume confirmed the signal."),
      part(en.trend, "Trend-rule entries (" + en.trend.markets.length + " funds)", "2003–2015", "2016–today"),
      part(en.stocks, "Stock Buy entries", "Training stocks 2003–2014", en.stocks.test_stocks + " other stocks 2015–today"),
      h("p.muted.small", { style: "margin-top:8px" }, "Most losing stock trades come from the exit, not the entry: the trailing stop (3× the average daily range) closes many trades early for small losses, and a minority of long trends pays for them. Full tables: docs/ENTRIES.md."));
  }

  function scoreSummary(methods) {
    const made = methods.filter((m) => m.verdict.made_money && m.verdict.beat_cash);
    const more = methods.filter((m) => m.verdict.more_money_than_comparison);
    const safer = methods.filter((m) => m.verdict.smaller_worst_drop);
    const lead = made.length === methods.length ? "Yes: every method made money and beat T-bills. "
      : made.length + " of " + methods.length + " methods made money and beat T-bills. ";
    const vs = more.length === 0 ? "None made more money than its comparison (usually simply holding). "
      : more.length === methods.length ? "All made more money than their comparison. "
      : "Only " + more.map((m) => m.name.toLowerCase()).join(" and ") + " made more money than " + (more.length > 1 ? "their comparisons" : "its comparison") + "; the rest earned less than simply holding. ";
    const drop = safer.length ? safer.length + " of " + methods.length + " had a clearly smaller worst drop, which is what they are best at." : "";
    return h("div.note", { style: "margin-bottom:10px;display:block" }, h("strong", lead), vs + drop);
  }

  function scorecardCard(sc) {
    const methods = sc.methods;
    if (!methods.length) return null;
    if (!scoreKey || !methods.find((m) => m.key === scoreKey)) scoreKey = (methods.find((m) => m.curve) || methods[0]).key;
    const mark = (ok) => h("span.pill." + (ok ? "bullish" : "bearish"), ok ? "✓" : "✗");
    const pct1 = (x) => fmt.pct(x, 1);
    const sel = methods.find((m) => m.key === scoreKey);
    let chartBlock = null;
    if (sel && sel.curve) {
      const chart = lineChart({ dates: sel.curve.strategy.dates, height: 230, label: "Growth of $100: " + sel.name + " vs " + sel.comparison.name,
        yFormat: (x) => "$" + (Math.round(x) || 0).toLocaleString("en-US"),
        series: [{ name: sel.name, color: "var(--series-1)", values: sel.curve.strategy.values },
                 { name: sel.comparison.name, color: "var(--series-2)", values: sel.curve.comparison.values }] });
      chartBlock = h("div", { style: "margin-top:12px" },
        h("div.chips", methods.filter((m) => m.curve).map((m) => h("button.chip" + (m.key === scoreKey ? ".on" : ""), { onclick: () => { scoreKey = m.key; render(); } }, m.name))),
        h("div", { style: "margin-top:8px" }, chart.legend), h("div", { style: "margin-top:6px" }, chart.node));
    }
    const t = sc.trend_alerts;
    return h("section.card",
      h("div.card-head", h("h2", "Scorecard: is each method profitable?"), h("p", "Every method the app recommends, replayed on past prices with costs")),
      scoreSummary(methods),
      dataTable([
        { label: "Method", cell: (m) => h("div", h("strong", m.name), h("div.small.muted", m.period)) },
        { label: "Tested on unseen data?", hideSmall: true, cell: (m) => h("div.small.soft", { style: "max-width:220px" }, m.unseen) },
        { label: "Yearly return", right: true, cell: (m) => h("div", h("strong", pct1(m.strategy.cagr_pct)), h("div.small.muted", pct1(m.comparison.cagr_pct) + " comparison")) },
        { label: "Worst drop", right: true, cell: (m) => h("div", h("strong", fmt.pct(m.strategy.max_drawdown_pct, 0)), h("div.small.muted", fmt.pct(m.comparison.max_drawdown_pct, 0) + " comparison")) },
        { label: "Made money", cell: (m) => mark(m.verdict.made_money) },
        { label: "Beat T-bills", hideSmall: true, cell: (m) => mark(m.verdict.beat_cash) },
        { label: "More than comparison", hideSmall: true, cell: (m) => mark(m.verdict.more_money_than_comparison) },
        { label: "Better per unit of risk", hideSmall: true, cell: (m) => mark(m.verdict.better_risk_adjusted) },
        { label: "Profitable 3-year stretches", right: true, hideSmall: true, cell: (m) => (m.rolling["3y"] ? m.rolling["3y"].made_money_pct + "%" : "—") },
      ], methods),
      h("p.small.soft", { style: "margin-top:8px" }, "Compared with: " + methods.map((m) => m.name + " → " + m.comparison.name).join("; ") +
        ". Profitable 3-year stretches = share of all 3-year periods, starting on any day, that ended with a gain."),
      chartBlock,
      t ? h("div", { style: "margin-top:12px" }, h("h3", "Market trend alerts without hindsight"),
        h("p.small.soft", "The markets that get alerts today were chosen using their whole history, which flatters them. So the same choosing rule was run on data up to " +
          t.pick_end.slice(0, 4) + " only. It picked " + t.picks.join(", ") + ". Those were then traded on every 10-month-rule alert from " + t.test_start.slice(0, 4) + ":"),
        dataTable([
          { label: "Basket", cell: ([k]) => ({ picked: "Picked before " + t.test_start.slice(0, 4), all: "All " + t.eligible.length + " markets, no picking", today_list: "Today's list (hindsight)" })[k] },
          { label: "Alerts followed", right: true, cell: ([, b]) => h("div", pct1(b.rule.cagr_pct) + "/yr", h("div.small.muted", "worst " + fmt.pct(b.rule.max_drawdown_pct, 0))) },
          { label: "Held instead", right: true, cell: ([, b]) => h("div", pct1(b.hold.cagr_pct) + "/yr", h("div.small.muted", "worst " + fmt.pct(b.hold.max_drawdown_pct, 0))) },
          { label: "Trades that won", right: true, hideSmall: true, cell: ([, b]) => (b.win_rate_pct === null ? "—" : b.win_rate_pct + "% of " + b.trades) },
        ], Object.entries(t.baskets)),
        h("p.muted.small", { style: "margin-top:6px" }, "Most single trades lost a little; a few long trends paid for them. That is normal for trend rules, so expect to be wrong more often than right. " +
          "Choosing markets added little over using the rule on all of them, which had a better return per unit of risk.")) : null,
      h("p.muted.small", { style: "margin-top:8px" }, "Full tables: docs/SCORECARD.md. Past results do not guarantee future ones."));
  }

  function storyCards(r) {
    const wf = r.walk_forward;
    const exam = r.final_exam;
    const cards = [];
    if (wf) {
      const ex = wf.panels.exam_stocks, sp = wf.panels.sp500;
      cards.push(h("section.card",
        h("div.card-head", h("h2", "Bottom line")),
        h("ul", { style: "margin:4px 0 0;padding-left:18px;display:grid;gap:6px" },
          h("li", h("strong", "Every version of the rules made money"), " in every period tested."),
          h("li", h("strong", "Individual Buy and Sell ratings did not beat the market."), " New Buy signals beat the S&P 500 about half the time, like a coin flip, across " +
            fmt.num(r.signal_study.train_2015_now.events.find((e) => e.kind === "buy" && e.horizon === 60).signals) + "+ signals per period."),
          h("li", h("strong", "Market risk control made crashes smaller, but did not improve returns."), " Stepping back when the whole market was in a downtrend or very turbulent cut the worst loss from " +
            ex.buy_and_hold.max_drawdown_pct + "% to " + ex.walk_forward.max_drawdown_pct + "% on stocks the rules never saw, with " +
            (ex.walk_forward.sharpe >= ex.buy_and_hold.sharpe ? "a similar or better" : "a similar or slightly lower") +
            " return per unit of risk (Sharpe " + ex.walk_forward.sharpe + " vs " + ex.buy_and_hold.sharpe + ", measured above T-bill returns)."),
          h("li", h("strong", "It did not make more money than holding."), " It earned " + ex.walk_forward.cagr_pct + "% a year against " + ex.buy_and_hold.cagr_pct +
            "% for always staying invested, because it missed some fast rebounds (2019, 2020, 2023)."),
          h("li", "So the app now shows a ", h("a", { href: "#/dashboard" }, "market risk indicator"), " with a suggested share of your budget in stocks, and treats single-stock ratings as information rather than a trading system."))));

      const chart = lineChart({
        dates: ex.curve.dates, height: 260, label: "Growth of $100, walk-forward versus buy and hold",
        yFormat: (x) => "$" + (Math.round(x) || 0).toLocaleString("en-US"),
        series: [
          { name: "Market risk rule (walk-forward)", color: "var(--series-1)", values: ex.curve.walk_forward },
          { name: "Always invested", color: "var(--series-2)", values: ex.curve.buy_and_hold },
        ],
      });
      const metricsRow = (label, a, b, f) => h("tr", h("td", label), h("td.r.num", f(a)), h("td.r.num", f(b)));
      const pct1 = (x) => fmt.pct(x, 1);
      const picks = Object.entries(wf.picks);
      const yearsWF = Object.keys(ex.yearly.walk_forward).reverse();
      cards.push(h("section.card",
        h("div.card-head", h("h2", "Walk-forward: the market risk rule, chosen in real time"),
          h("p", "Each year's rule was picked using only earlier years, then applied to " + exam.symbols.length + " stocks never used for tuning")),
        chart.legend, h("div", { style: "margin-top:8px" }, chart.node),
        h("div.grid-2", { style: "margin-top:12px" },
          h("div.table-wrap", h("table",
            h("thead", h("tr", h("th", "Unseen stocks, " + ex.walk_forward.years + " years"), h("th.r", "Rule"), h("th.r", "Always invested"))),
            h("tbody",
              metricsRow("Yearly return", ex.walk_forward.cagr_pct, ex.buy_and_hold.cagr_pct, pct1),
              metricsRow("Worst drop", ex.walk_forward.max_drawdown_pct, ex.buy_and_hold.max_drawdown_pct, pct1),
              metricsRow("Sharpe ratio", ex.walk_forward.sharpe, ex.buy_and_hold.sharpe, (x) => x.toFixed(2)),
              metricsRow("Volatility", ex.walk_forward.volatility_pct, ex.buy_and_hold.volatility_pct, (x) => x.toFixed(1) + "%"),
              metricsRow("S&P 500 alone: yearly", sp.walk_forward.cagr_pct, sp.buy_and_hold.cagr_pct, pct1),
              metricsRow("S&P 500 alone: worst drop", sp.walk_forward.max_drawdown_pct, sp.buy_and_hold.max_drawdown_pct, pct1)))),
          h("div.table-wrap", h("table",
            h("thead", h("tr", h("th", "Year"), h("th.r", "Rule"), h("th.r", "Always invested"), h("th.hide-sm", "Rule in use"))),
            h("tbody", yearsWF.map((y) => h("tr", h("td", y),
              h("td.r.num", h("span." + signClass(ex.yearly.walk_forward[y]), pct1(ex.yearly.walk_forward[y]))),
              h("td.r.num", pct1(ex.yearly.buy_and_hold[y])),
              h("td.small.soft.hide-sm", wf.picks[y] || "—"))))))),
        h("p.muted.small", { style: "margin-top:8px" }, "Candidates: " + wf.candidates.map((c) => c.name).join(", ") +
          ". The candidate list was written after seeing the round 2 final exam; the year-by-year choices were not.")));
    }
    if (exam) {
      const rules = r.round2.chosen_rules;
      cards.push(h("section.card",
        h("div.card-head", h("h2", "Final exam: round 2's pick on " + exam.symbols.length + " untouched stocks"), h("p", rules.name)),
        h("p.soft", rules.notes),
        dataTable([
          { label: "Period", cell: (k) => (k === "exam_2003_2014" ? "2003–2014" : "2015–today") },
          { label: "Rule: yearly", right: true, cell: (k) => fmt.pct(exam.cells[k].portfolio.strategy.cagr_pct) },
          { label: "Rule: worst drop", right: true, cell: (k) => fmt.pct(exam.cells[k].portfolio.strategy.max_drawdown_pct) },
          { label: "Hold same: yearly", right: true, cell: (k) => fmt.pct(exam.cells[k].portfolio.equal_weight.cagr_pct) },
          { label: "Hold same: worst drop", right: true, cell: (k) => fmt.pct(exam.cells[k].portfolio.equal_weight.max_drawdown_pct) },
          { label: "Original rules: yearly", right: true, hideSmall: true, cell: (k) => fmt.pct(exam.cells[k].baseline.cagr_pct) },
          { label: "Holds up?", cell: (k) => (exam.cells[k].verdict.holds_up ? h("span.pill.bullish", "✓ Yes") : h("span.pill.bearish", "✗ No")) },
        ], Object.keys(exam.cells)),
        h("p.muted.small", { style: "margin-top:8px" }, "Round 2 compared " + r.round2.rows.length + " ideas on every period already seen and picked the most consistent one before this exam was run once.")));
      cards.push(h("section.card",
        h("div.card-head", h("h2", "Round 2 ideas"), h("p", "Advantage = Sharpe ratio minus that of holding the same stocks, across the four periods already seen")),
        dataTable([
          { label: "Idea", cell: (x) => h("div", h("div", { style: x.name === r.round2.chosen_rules.name ? "font-weight:700" : "" }, x.name,
            x.name === r.round2.chosen_rules.name ? h("span.tag", { style: "margin-left:6px" }, "Chosen") : null), x.notes ? h("div.small.muted", x.notes) : null) },
          { label: "Median advantage", right: true, cell: (x) => h("span." + signClass(x.median_sharpe_edge), (x.median_sharpe_edge > 0 ? "+" : "") + x.median_sharpe_edge.toFixed(2)) },
          { label: "Worst period", right: true, cell: (x) => (x.worst_sharpe_edge > 0 ? "+" : "") + x.worst_sharpe_edge.toFixed(2) },
          { label: "Always profitable", cell: (x) => (x.always_profitable ? "Yes" : "No") },
        ], r.round2.rows.slice().sort((a, b) => b.median_sharpe_edge - a.median_sharpe_edge))));
    }
    return cards;
  }

  function stopsCard(st) {
    const base = st.results[0];
    const rows = st.results.slice(1).sort((a, b) => b.avg_sharpe_vs_hold - a.avg_sharpe_vs_hold);
    const avg = (x, key) => {
      const vals = Object.values(x.cells).map((c) => c[key]).filter((v) => v !== null && v !== undefined);
      return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    };
    const signed = (x, d = 1) => {
      if (x === null) return "—";
      const r = Number(x.toFixed(d));
      return (r > 0 ? "+" : r < 0 ? "−" : "") + Math.abs(r).toFixed(d);
    };
    return h("section.card",
      h("div.card-head", h("h2", "Stop-loss test: does a stop under each stock help?"),
        h("p", "Every stock held with one exit rule, " + Object.keys(base.cells).length + " stock-and-period sets, 2003–2026")),
      h("p.soft", "Every stop lowered the average yearly return. Wide trailing stops cut the worst drawdowns for a modest cost; tight stops were hit by ordinary noise and cost 7–9 points a year. After a stop-out, the stock was usually higher three months later."),
      dataTable([
        { label: "Exit rule", cell: (x) => h("div", h("div", x.name), h("div.small.muted", x.family)) },
        { label: "Return vs holding", right: true, cell: (x) => h("span." + signClass(x.avg_cagr_vs_hold), signed(x.avg_cagr_vs_hold, 2) + " pts/yr") },
        { label: "Worst drop vs holding", right: true, cell: (x) => h("span." + signClass(x.avg_drawdown_vs_hold), signed(x.avg_drawdown_vs_hold) + " pts") },
        { label: "Sharpe vs holding", right: true, hideSmall: true, cell: (x) => h("span." + signClass(x.avg_sharpe_vs_hold), signed(x.avg_sharpe_vs_hold, 2)) },
        { label: "Stop-outs / stock / yr", right: true, hideSmall: true, cell: (x) => (avg(x, "stop_outs_per_stock_year") ?? 0).toFixed(2) },
        { label: "Higher 3 months after stop-out", right: true, hideSmall: true, cell: (x) => { const v = avg(x, "rose_after_stop_pct"); return v === null ? "—" : Math.round(v) + "%"; } },
      ], rows),
      h("p.muted.small", { style: "margin-top:8px" }, "Stops fill at the stop price, or at the open when a stock gaps below it. 10 basis points per trade; cash earns T-bill interest while stopped out. A positive drawdown difference means a shallower worst loss. Rerun with: python -m stockanalysis.validation.stops"));
  }

  function experimentsCard(x) {
    const w = x.weights, c = x.combinations;
    const cells = ["train_2003_2014", ...x.validation_cells, ...x.test_cells];
    const names = { train_2003_2014: "Training", holdout_2003_2014: "Held-out 03–14", train_2015_now: "Train stocks 15–26",
      holdout_2015_now: "Held-out 15–26", fresh_2003_2014: "Fresh 03–14", fresh_2015_now: "Fresh 15–26" };
    const edge = (v) => h("span." + signClass(v), (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2));
    const feats = ["trend", "momentum", "high52", "pullback", "macd", "earnings"];
    const featNames = { trend: "Trend", momentum: "Momentum", high52: "52-wk high", pullback: "Pullback", macd: "MACD", earnings: "Earnings" };
    const d = c.best.deflated_sharpe;
    return h("section.card",
      h("div.card-head", h("h2", "Experiments: fitted weights and indicator combinations"),
        h("p", "Fresh test: " + x.groups.fresh + " stocks used in no earlier test")),
      h("h3", { style: "margin:4px 0 6px" }, "1. Learning the score's weights from data"),
      dataTable([
        { label: "Weights", cell: (m) => m.name },
        ...feats.map((k) => ({ label: featNames[k], right: true, hideSmall: true, cell: (m) => (m.weights[k] > 0 ? "+" : "") + Math.round(m.weights[k]) })),
      ], w.models.slice(0, 3)),
      h("p.small.soft", { style: "margin:10px 0 4px" }, "Top-15 portfolio, Sharpe ratio minus holding all the same stocks (monthly rebalance, with costs):"),
      dataTable([
        { label: "Model", cell: (m) => m.name },
        ...cells.map((k) => ({ label: names[k], right: true, hideSmall: !k.startsWith("fresh"), cell: (m) => edge(m.cells[k].edge) })),
        { label: "Ranking skill, fresh 15–26 (t)", right: true, hideSmall: true, cell: (m) => {
          const v = m.cells.fresh_2015_now; return v.ic_mean === null ? "—" : v.ic_mean.toFixed(3) + " (" + v.ic_t.toFixed(1) + ")"; } },
      ], w.models),
      h("p.small", { style: "margin-top:6px" }, h("strong", "Adopted: " + (w.adopt ? "yes" : "no") + ". "),
        "Fresh-stock ranking skill, both periods: t = " + w.fresh_pooled_ic_t.toFixed(2) + " (2 or more is significant)."),
      h("h3", { style: "margin:16px 0 6px" }, "2. Combining indicators"),
      dataTable([
        { label: "Rule type", cell: (t) => t.kind },
        { label: "Rules", right: true, cell: (t) => t.count },
        { label: "Median training edge", right: true, cell: (t) => edge(t.median_train_edge) },
        { label: "Median unseen-data edge", right: true, cell: (t) => edge(t.median_val_edge) },
        { label: "Beat holding on unseen data", right: true, cell: (t) => t.share_beating_hold_in_validation + "%" },
      ], Object.entries(c.by_type).map(([kind, t]) => ({ kind, ...t }))),
      h("p.small", { style: "margin-top:8px" }, h("strong", "Best of " + c.combinations.toLocaleString() + " in training: "), c.best.label,
        ". Edge: training ", edge(c.best.train_edge), ", unseen data ", edge(c.best.val_edge), ", fresh stocks ", edge(c.best.test_edge), "."),
      h("p.small", "Luck check (deflated Sharpe ratio): its better training score came from holding less risk; its return minus holding's had a Sharpe of " +
        d.sharpe_annual.toFixed(2) + " even in training, against about " + d.luck_threshold_annual.toFixed(2) + " that the best of " + d.trials.toLocaleString() +
        " tries would reach by luck. Probability it really beats holding: " + Math.round(d.probability_real * 100) + "%."),
      h("p.small", h("strong", "Adopted: " + (c.adopt ? "yes" : "no") + ". "), "Rules fixed before running: change the app only if it beats holding on the fresh stocks in both periods and the result is statistically significant."));
  }

  Promise.all([api("/api/validation"), api("/api/validation/stops").catch(() => null), api("/api/validation/experiments").catch(() => null),
    api("/api/validation/scorecard").catch(() => null), api("/api/validation/entries").catch(() => null), api("/api/validation/profit").catch(() => null),
    api("/api/validation/recent").catch(() => null)])
    .then(([r, st, ex, sc, en, pr, rc]) => { report = r; stops = st; experiments = ex; scorecard = sc; entries = en; profit = pr; recent = rc; render(); })
    .catch((e) => fill(body, h("section.card", h("div.empty", e.message))));
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
    text: "Position size comes from the stop, not from conviction: shares = (budget × risk per trade) ÷ (entry − stop). The stop sits 2.5 ATRs below the entry (ATR is the stock's average daily range), so a volatile stock gets a wider stop and fewer shares. Once you hold a stock, the app tracks a trailing stop 20% below its best close since you bought. In the app's own 20-year test, every stop lowered average return; a 20% trailing stop was the best trade-off, cutting the worst drawdown by about 13 points for about 2.6 points a year, while tight trailing stops (10%, or 3 ATRs under the 22-day high) cost 7–9 points a year in whipsaws. Stops are insurance against big losses, not a way to make more money.",
    sources: [] },
  { title: "8. Options: where retail traders actually lose", weight: "Options rules",
    text: "Studies of retail option trading find the losses concentrate in three habits: cheap far out-of-the-money contracts, expiries a few days away with wide bid/ask spreads, and buying just before earnings, when prices are inflated and collapse after the report (losses of 5 to 14% on average around announcements). The app does the opposite: about 45 days to expiry, delta near 0.60, spreads instead of outright buys near earnings or when options are expensive, and selling cash-secured puts when implied volatility is rich. Every idea is capped by your options risk setting.",
    sources: [["MIT Sloan: Retail investors lose big in options markets", "https://mitsloan.mit.edu/ideas-made-to-matter/retail-investors-lose-big-options-markets-research-shows"], ["de Silva, Smith & So, Losing is Optional", "https://www.gsb.stanford.edu/faculty-research/working-papers/losing-optional-retail-option-trading-expected-announcement"], ["Cboe: PutWrite and BuyWrite index performance", "https://www.cboe.com/insights/posts/key-cboe-benchmark-indexes-using-spx-options-offer-strong-risk-adjusted-returns/"]] },
];

function guidePage(root) {
  fill(root, 
    pageHead("Strategy guide", "The rules behind every signal, and the research they come from."),
    h("div.stack.guide",
      h("div.note.warn", h("span", h("strong", "What our own test found: "),
        "replayed on 190 large US stocks over 20+ years, the Buy and Sell ratings below did not beat the market on their own; the published effects are weaker among large, heavily traded companies today. What did hold up was applying the trend and volatility rules to the whole market, shown as Market risk on the dashboard. ",
        h("a", { href: "#/track" }, "See the track record"), ".")),
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
  insiders: insidersPage, positions: positionsPage, settings: settingsPage, guide: guidePage, track: trackRecordPage, lab: labPage, markets: marketsPage,
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
