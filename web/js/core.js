// MasterMail UI core: API client, live events, DOM helpers and Apple-style components.

const qs = new URLSearchParams(location.search);
const TOKEN = qs.get("t") || sessionStorage.getItem("mm-token") || "";
if (qs.get("t")) {
  sessionStorage.setItem("mm-token", qs.get("t"));
  history.replaceState(null, "", location.pathname + location.hash);
}

// ---------------------------------------------------------------- formatting
const FA = "۰۱۲۳۴۵۶۷۸۹";
export const fa = (v) => String(v ?? "").replace(/\d/g, (d) => FA[d]);
export const num = (n) => fa(Number(n || 0).toLocaleString("en-US"));
export const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);
export function bytes(n) {
  if (n < 1024) return fa(n) + " بایت";
  if (n < 1024 * 1024) return fa((n / 1024).toFixed(0)) + " کیلوبایت";
  return fa((n / 1024 / 1024).toFixed(1)) + " مگابایت";
}
export function ago(ts) {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "همین حالا";
  if (s < 3600) return fa(Math.floor(s / 60)) + " دقیقه پیش";
  if (s < 86400) return fa(Math.floor(s / 3600)) + " ساعت پیش";
  if (s < 86400 * 30) return fa(Math.floor(s / 86400)) + " روز پیش";
  return new Date(ts * 1000).toLocaleDateString("fa-IR");
}
export const isEmail = (v) => String(v || "").split(",").map((s) => s.trim()).filter(Boolean)
  .every((p) => /^[^\s@]+@[^\s@]+\.[A-Za-z]{2,}$/.test(p)) && String(v || "").trim() !== "";

// ---------------------------------------------------------------- API
export class ApiError extends Error {}
export async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { "X-Token": TOKEN, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw new ApiError((data && data.error) || `خطای ${res.status}`);
  return data;
}
export const get = (p) => api("GET", p);
export const post = (p, b = {}) => api("POST", p, b);
export const patch = (p, b = {}) => api("PATCH", p, b);
export const del = (p) => api("DELETE", p);

export async function upload(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload?name=" + encodeURIComponent(file.name));
    xhr.setRequestHeader("X-Token", TOKEN);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch { /* empty */ }
      xhr.status === 200 ? resolve(data) : reject(new ApiError(data.error || "بارگذاری ناموفق بود"));
    };
    xhr.onerror = () => reject(new ApiError("بارگذاری ناموفق بود"));
    xhr.send(file);
  });
}
export const downloadUrl = (path) => `/api/download?t=${encodeURIComponent(TOKEN)}&path=${encodeURIComponent(path)}`;

// ---------------------------------------------------------------- events
const listeners = new Map();
export function on(type, fn) {
  if (!listeners.has(type)) listeners.set(type, new Set());
  listeners.get(type).add(fn);
  return () => listeners.get(type).delete(fn);
}
export function emit(type, data) {
  (listeners.get(type) || []).forEach((fn) => { try { fn(data); } catch (e) { console.error(e); } });
}
function connectEvents() {
  const es = new EventSource("/api/events?t=" + encodeURIComponent(TOKEN));
  es.onmessage = (m) => {
    try { const ev = JSON.parse(m.data); emit(ev.type, ev.data); } catch { /* ignore */ }
  };
  es.onerror = () => { es.close(); setTimeout(connectEvents, 1500); };
}
connectEvents();

// ---------------------------------------------------------------- DOM
export function h(tag, props, ...children) {
  const el = document.createElementNS(tag === "svg" || tag === "path" || tag === "circle" || tag === "rect" || tag === "g" || tag === "line" || tag === "polyline"
    ? "http://www.w3.org/2000/svg" : "http://www.w3.org/1999/xhtml", tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.setAttribute("class", Array.isArray(v) ? v.filter(Boolean).join(" ") : v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "html") el.innerHTML = v;
    else if (k === "value" && "value" in el) el.value = v;
    else if (k === "checked") el.checked = !!v;
    else if (k === "ref") v(el);
    else el.setAttribute(k, v === true ? "" : v);
  }
  append(el, children);
  return el;
}
function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false || c === true) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}
export function mount(el, ...children) { el.replaceChildren(); append(el, children); return el; }

// ---------------------------------------------------------------- icons (SF Symbols-like)
const P = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z",
  sparkles: "M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8zM5 15l.6 1.4L7 17l-1.4.6L5 19l-.6-1.4L3 17l1.4-.6z",
  globe: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm0 0c2.5 2.6 3.7 5.6 3.7 9s-1.2 6.4-3.7 9m0-18C9.5 5.6 8.3 8.6 8.3 12s1.2 6.4 3.7 9M3.5 9h17M3.5 15h17",
  scissors: "M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm0 12a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM20 4 8.1 15.9M14.5 14.5 20 20M8.1 8.1 12 12",
  book: "M4 19.5V5a2 2 0 0 1 2-2h13v15H6.5A2.5 2.5 0 0 0 4 20.5 2.5 2.5 0 0 0 6.5 23H19v-5M8 7h7M8 11h5",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm0 4.5V12l3 2",
  gear: "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  mail: "M3 6.5A1.5 1.5 0 0 1 4.5 5h15A1.5 1.5 0 0 1 21 6.5v11a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5zM3.5 6l8.5 6.5L20.5 6",
  clip: "M21 11.5 12.5 20a5 5 0 0 1-7-7L14 4.5a3.3 3.3 0 0 1 4.7 4.7L10.2 17.7a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8",
  upload: "M12 15V4m0 0L7.5 8.5M12 4l4.5 4.5M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15",
  download: "M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15",
  check: "M5 12.5 10 17.5 19.5 7",
  x: "M6 6l12 12M18 6 6 18",
  chevron: "M9 6l6 6-6 6",
  back: "M15 6l-6 6 6 6",
  play: "M7 4.5v15l13-7.5z",
  pause: "M7 4.5h3.5v15H7zM13.5 4.5H17v15h-3.5z",
  stop: "M6 6h12v12H6z",
  doc: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h6",
  table: "M3.5 5A1.5 1.5 0 0 1 5 3.5h14A1.5 1.5 0 0 1 20.5 5v14a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 19zM3.5 9.5h17M3.5 15h17M9.5 9.5v11",
  wand: "M15 4V2M15 16v-2M8 9h2M20 9h2M17.8 11.8 19 13M17.8 6.2 19 5M3 21l9-9M12.2 6.2 11 5",
  refresh: "M20 11a8 8 0 0 0-14.6-4.5L4 8M4 4v4h4M4 13a8 8 0 0 0 14.6 4.5L20 16M20 20v-4h-4",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  send: "M21.5 2.5 10.5 13.5M21.5 2.5l-7 19-4-8-8-4z",
  person: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm-7.5 8.5a7.5 7.5 0 0 1 15 0",
  people: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2.5 20a6.5 6.5 0 0 1 13 0M16 4.3a3.5 3.5 0 0 1 0 6.4M18.5 14.5A6.5 6.5 0 0 1 21.5 20",
  key: "M15.5 7.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM12.5 10.5 4 19v2h3l1-1v-2h2v-2h2l1.5-1.5",
  bolt: "M13 2 4 14h7l-1 8 9-12h-7z",
  info: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm0 8v5m0-8.5v.5",
  warn: "M12 3.5 2.5 20h19zM12 10v4.5m0 2.5v.5",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3",
  plus: "M12 5v14M5 12h14",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zm9 16-4.2-4.2",
  moon: "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z",
  chart: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  megaphone: "M3 10v4a1 1 0 0 0 1 1h3l5 4V5L7 9H4a1 1 0 0 0-1 1zM16 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12",
  wallet: "M3 7a2 2 0 0 1 2-2h13v4M3 7v10a2 2 0 0 0 2 2h15V9H5a2 2 0 0 1-2-2zM16 14h.5",
  bell: "M6 9a6 6 0 1 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15 6 9zM10 20a2 2 0 0 0 4 0",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  shield: "M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6z",
  lock: "M6.5 11V8a5.5 5.5 0 0 1 11 0v3M5 11h14v10H5z",
  copy: "M8 8h11v13H8zM5 16H4V3h11v1",
  list: "M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01",
  flask: "M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3M7 15h10",
  heart: "M12 20s-8-4.8-8-10.5A4.5 4.5 0 0 1 12 7a4.5 4.5 0 0 1 8 2.5C20 15.2 12 20 12 20z",
};
export function icon(name, size = 18, sw = 1.9) {
  const svg = h("svg", { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": sw, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", "data-icon": name });
  svg.appendChild(h("path", { d: P[name] || P.info }));
  return svg;
}

// ---------------------------------------------------------------- components
export function button(text, opts = {}) {
  const el = h("button", { class: ["btn", opts.kind, opts.size, !text && "icon"], type: "button",
    title: opts.title, disabled: opts.disabled, onClick: async (e) => {
      if (!opts.onClick) return;
      if (opts.busy === false) return opts.onClick(e);
      const prev = [...el.childNodes];
      el.disabled = true;
      const t = setTimeout(() => mount(el, h("span", { class: "spinner" }), text ? h("span", {}, text) : null), 180);
      try { await opts.onClick(e); } catch (err) { toast(err.message || String(err), "error"); }
      finally { clearTimeout(t); if (el.isConnected) { mount(el, ...prev); el.disabled = !!opts.disabled; } }
    } },
  opts.icon && !opts.iconEnd ? icon(opts.icon, opts.size === "sm" ? 15 : 17) : null, text ? h("span", {}, text) : null,
  opts.icon && opts.iconEnd ? icon(opts.icon, opts.size === "sm" ? 15 : 17) : null);
  return el;
}

export function toggle(checked, onChange, opts = {}) {
  return h("label", { class: "switch", title: opts.title },
    h("input", { type: "checkbox", checked, onChange: (e) => onChange(e.target.checked) }), h("span"));
}

export function segmented(options, value, onChange, opts = {}) {
  const wrap = h("div", { class: ["segmented", opts.size], role: "tablist" });
  const render = (val) => mount(wrap, options.map((o) => h("button", { class: o.value === val ? "on" : "", type: "button",
    onClick: () => { render(o.value); onChange(o.value); } }, o.icon ? icon(o.icon, 15) : null, o.label)));
  render(value);
  return wrap;
}

export function select(options, value, onChange, opts = {}) {
  return h("select", { class: ["select", opts.bare && "bare"], onChange: (e) => onChange(e.target.value), style: opts.style },
    options.map((o) => h("option", { value: o.value, selected: o.value === value ? "selected" : null }, o.label)));
}

export function field(label, control, hint) {
  return h("div", { class: "field" }, label ? h("label", {}, label) : null, control,
    hint ? h("small", { class: "muted", style: { fontSize: "12px" } }, hint) : null);
}

export function input(value, onInput, opts = {}) {
  return h("input", { class: ["input", opts.bare && "bare", opts.ltr && "ltr"], value: value ?? "", type: opts.type || "text",
    placeholder: opts.placeholder, dir: opts.ltr ? "ltr" : null, style: opts.style,
    onInput: (e) => onInput && onInput(e.target.value), onChange: (e) => opts.onChange && opts.onChange(e.target.value) });
}

export function groupRow(label, control, opts = {}) {
  return h("div", { class: ["group-row", opts.icon && "has-icon", opts.onClick && "link"], onClick: opts.onClick },
    opts.icon ? h("div", { class: "row-icon", style: { background: opts.color || "var(--accent)" } }, icon(opts.icon, 17, 2)) : null,
    h("div", { class: "label" }, label, opts.sub ? h("small", {}, opts.sub) : null),
    control,
    opts.onClick && !control ? icon("chevron", 16) : null);
}

export function pill(text, color, dot) {
  return h("span", { class: ["pill", color] }, dot ? h("i", { class: "d" }) : null, text);
}

export function progressBar(value, total, opts = {}) {
  const p = total ? Math.min(100, (value / total) * 100) : 0;
  return h("div", { class: ["progress", opts.color, opts.indeterminate && "indeterminate"] }, h("i", { style: { width: p + "%" } }));
}

export function ring(p) {
  return h("div", { class: "ring", style: { "--p": p } }, h("b", { class: "num" }, fa(p) + "٪"));
}

// toast ----------------------------------------------------------------
const toastWrap = h("div", { class: "toasts" });
document.body.appendChild(toastWrap);
export function toast(text, kind = "info", ms = 3800) {
  const ic = { ok: "check", error: "x", warn: "warn", info: "info" }[kind] || "info";
  const el = h("div", { class: ["toast", kind] }, h("span", { class: "t-ico" }, icon(ic, 14, 2.6)), h("span", {}, text));
  toastWrap.appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 260); }, ms);
}

// sheet ----------------------------------------------------------------
export function sheet({ title, subtitle, body, actions = [], wide = false, onClose }) {
  const backdrop = h("div", { class: "sheet-backdrop" });
  const close = () => { backdrop.remove(); document.removeEventListener("keydown", esc); onClose && onClose(); };
  const esc = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", esc);
  backdrop.addEventListener("mousedown", (e) => { if (e.target === backdrop) close(); });
  const foot = h("div", { class: "sheet-foot" }, actions.map((a) => button(a.label, { kind: a.kind, icon: a.icon,
    onClick: async () => { const r = await a.onClick?.(close); if (r !== false && a.close !== false) close(); } })));
  backdrop.appendChild(h("div", { class: ["sheet", wide && "wide"], role: "dialog" },
    h("div", { class: "sheet-head" }, h("h3", {}, title), subtitle ? h("p", {}, subtitle) : null),
    h("div", { class: "sheet-body" }, body), actions.length ? foot : null));
  document.body.appendChild(backdrop);
  return { close };
}

export function confirmSheet(title, text, { ok = "تأیید", danger = false } = {}) {
  return new Promise((resolve) => {
    let done = false;
    sheet({ title, body: h("p", { class: "muted", style: { margin: "0 0 6px" } }, text),
      onClose: () => !done && resolve(false),
      actions: [
        { label: ok, kind: danger ? "danger solid" : "primary", onClick: () => { done = true; resolve(true); } },
        { label: "انصراف", onClick: () => { done = true; resolve(false); } },
      ] });
  });
}

// drop zone ------------------------------------------------------------
export function dropZone({ title, hint, accept, multiple = false, onFiles }) {
  const inputEl = h("input", { type: "file", accept, multiple, class: "hidden",
    onChange: (e) => { if (e.target.files.length) onFiles([...e.target.files]); e.target.value = ""; } });
  const zone = h("div", { class: "drop", tabindex: 0, onClick: () => inputEl.click(),
    onKeydown: (e) => (e.key === "Enter" || e.key === " ") && inputEl.click(),
    onDragover: (e) => { e.preventDefault(); zone.classList.add("over"); },
    onDragleave: () => zone.classList.remove("over"),
    onDrop: (e) => { e.preventDefault(); zone.classList.remove("over"); if (e.dataTransfer.files.length) onFiles([...e.dataTransfer.files]); } },
  h("div", { class: "drop-ico" }, icon("upload", 26, 2)), h("b", {}, title),
  h("small", {}, hint), inputEl);
  return zone;
}

export function fileIcon(name) {
  const ext = (name.split(".").pop() || "").toLowerCase();
  const cls = ["xlsx", "xls", "csv", "xlsm"].includes(ext) ? "" : ext === "docx" || ext === "doc" ? "doc" : "any";
  return h("div", { class: ["file-ico", cls] }, ext.toUpperCase().slice(0, 4));
}

export function emptyState(ic, title, text, action) {
  return h("div", { class: "empty" }, h("div", { class: "e-ico" }, icon(ic, 30, 1.6)), h("b", {}, title),
    h("div", {}, text), action ? h("div", { style: { marginTop: "16px" } }, action) : null);
}

// log --------------------------------------------------------------------
export function logView(entries) {
  const el = h("div", { class: "log" });
  const add = (e) => {
    el.appendChild(h("div", { class: e.level }, h("i", { class: "lv" }), h("span", {}, e.text)));
    el.scrollTop = el.scrollHeight;
  };
  (entries || []).forEach(add);
  el.add = add;
  return el;
}

// app state (shared, small) -------------------------------------------------
export const store = { state: null, campaigns: [] };
export async function refreshState() {
  store.state = await get("/api/state");
  emit("state", store.state);
  return store.state;
}
export function applyTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}
export function openPath(path, reveal = false) {
  return post("/api/open", { path, reveal }).catch((e) => toast(e.message, "error"));
}
