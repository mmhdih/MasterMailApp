// Campaign wizard: source → recipients (auto-crawl) → compose → attachments → review & send.
import {
  h, mount, icon, button, toggle, segmented, select, field, input, groupRow, pill, toast, sheet, confirmSheet,
  dropZone, fileIcon, emptyState, upload, get, post, patch, del, fa, num, bytes, ago, isEmail, store, on, openPath,
  refreshState,
} from "../core.js";
import { jobCard, isFinished } from "../jobs.js";
import { crawlChooser } from "../crawlplan.js";
import { campaignRow, newCampaign } from "./home.js";

const STEPS = [
  { t: "منبع", icon: "list" }, { t: "گیرندگان", icon: "people" }, { t: "متن ایمیل", icon: "wand" },
  { t: "پیوست", icon: "clip" }, { t: "بازبینی و ارسال", icon: "send" },
];
const ORIGIN = { file: ["فایل", "indigo"], directory: ["دفترچه آدرس", "purple"], crawl: ["کراول", "blue"], manual: ["دستی", "orange"] };
const SEND_STATUS = { sent: ["ارسال شد", "green"], failed: ["ناموفق", "red"], skipped: ["رد شد", "orange"], dry: ["شبیه‌سازی", "blue"] };
const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩";

function parseIdsLocal(text) {
  const ascii = String(text || "").replace(/[۰-۹٠-٩]/g, (d) => String(FA_DIGITS.indexOf(d) % 10));
  const seen = new Set(); let dup = 0; let bad = 0;
  for (let t of ascii.split(/[\s,،;؛|/\\]+/)) {
    t = t.replace(/^["'`()[\]{}<>]+|["'`()[\]{}<>]+$/g, "").replace(/\.0$/, "");
    if (!t) continue;
    if (!/^[A-Za-z0-9\-_]{1,40}$/.test(t)) { bad++; continue; }
    if (seen.has(t)) { dup++; continue; }
    seen.add(t);
  }
  return { count: seen.size, dup, bad };
}

function debounce(fn, ms) {
  let t, last;
  const d = (...a) => { last = a; clearTimeout(t); t = setTimeout(() => { t = null; fn(...a); }, ms); };
  d.now = () => { if (t) { clearTimeout(t); t = null; fn(...(last || [])); } };
  return d;
}

// ===================================================================== list
export function campaignsView(page) {
  const list = h("div");
  mount(page,
    h("div", { class: "row" }, h("h1", { class: "large-title" }, "کمپین‌ها"), h("span", { class: "spacer" }),
      button("کمپین جدید", { kind: "primary", icon: "plus", onClick: newCampaign })),
    h("p", { class: "page-sub" }, "هر کمپین یک ارسال گروهی است: گیرندگان، متن، پیوست‌ها و گزارش ارسال در آن ذخیره می‌شود."),
    list);
  const load = () => get("/api/campaigns").then((items) => mount(list, items.length
    ? h("div", { class: "group" }, items.map((c) => {
        const row = campaignRow(c);
        row.insertBefore(button("", { icon: "trash", kind: "sm plain", title: "حذف", onClick: async (e) => {
          e.stopPropagation();
          if (await confirmSheet("حذف کمپین", `کمپین «${c.name}» و گزارش ارسال آن حذف شود؟ فایل‌های ساخته‌شده روی دیسک باقی می‌مانند.`, { ok: "حذف", danger: true })) {
            await del(`/api/campaigns/${c.id}`); refreshState(); load();
          }
        } }), row.lastChild);
        return row;
      }))
    : h("div", { class: "group" }, emptyState("send", "هنوز کمپینی ندارید", "با «کمپین جدید» اولین ارسال گروهی را بسازید.",
        button("کمپین جدید", { kind: "primary", icon: "plus", onClick: newCampaign })))));
  load();
}

// ===================================================================== wizard
export function campaignView(page, id) {
  const S = { c: null, step: 0, job: null, offs: [], templates: null };
  const header = h("div");
  const stepper = h("div", { class: "stepper" });
  const body = h("div");
  mount(page, header, stepper, body);

  // Changes made within the debounce window are merged, so a quick "next" never drops a typed name.
  let pendingPatch = {};
  const flush = debounce(() => {
    const p = pendingPatch; pendingPatch = {};
    patch(`/api/campaigns/${id}`, p).then((c) => { S.c = { ...c, ...pendingPatch }; }).catch((e) => toast(e.message, "error"));
  }, 500);
  const save = (p) => { pendingPatch = { ...pendingPatch, ...p }; flush(); };

  async function load() {
    S.c = await get(`/api/campaigns/${id}`);
    renderHeader();
  }
  function renderHeader() {
    const nameInput = h("input", { class: "large-title", value: S.c.name, style: { border: 0, background: "transparent", outline: "none", width: "100%", padding: 0, color: "inherit", fontFamily: "inherit" },
      onInput: (e) => { S.c.name = e.target.value; save({ name: e.target.value }); } });
    mount(header, h("div", { class: "row" },
      button("", { icon: "back", kind: "plain", title: "کمپین‌ها", onClick: () => window.mmGo("#/campaigns"), busy: false }),
      h("div", { style: { flex: 1 } }, nameInput)),
      h("p", { class: "page-sub", style: { marginTop: "-4px" } }, "نام کمپین را می‌توانید همین‌جا تغییر دهید. همه تغییرات خودکار ذخیره می‌شوند."));
  }
  function renderStepper() {
    const reach = maxReachable();
    mount(stepper, STEPS.map((s, i) => h("button", {
      class: ["step", i === S.step && "on", i < S.step && "done"], disabled: i > reach ? true : null,
      style: i > reach ? { opacity: .45, cursor: "default" } : null,
      onClick: () => i <= reach && goStep(i) },
    h("span", { class: "n" }, i < S.step ? icon("check", 13, 3) : fa(i + 1)), h("span", { class: "t" }, s.t))));
  }
  function maxReachable() {
    if (!S.c.recipients.length) return 0;
    return 4;
  }
  function goStep(i) {
    S.step = i; save({ step: i }); flush.now();
    renderStepper(); renderStep();
    page.parentElement.scrollTop = 0;
  }
  function cleanup() { S.offs.forEach((f) => f()); S.offs = []; }
  function renderStep() {
    cleanup();
    [stepSource, stepRecipients, stepCompose, stepAttachments, stepSend][S.step]();
  }
  function footer(...items) {
    return h("div", { class: "wizard-foot" }, ...items);
  }
  const nextBtn = (label = "ادامه", onClick) => button(label, { kind: "primary", icon: "chevron", iconEnd: true, onClick: onClick || (() => goStep(S.step + 1)) });
  const backBtn = () => button("مرحله قبل", { onClick: () => goStep(S.step - 1), busy: false });

  // ------------------------------------------------------------------ step 0
  function stepSource() {
    const src = S.c.source || {};
    const st = { mode: src.mode || "ids", text: src.text || "", file: src.file_id ? { file_id: src.file_id, name: src.file_name } : null,
      info: null, sheet: src.sheet || "", header_row: src.header_row || 1, columns: src.columns || {}, split: !!src.split };
    const panel = h("div");
    const render = () => mount(panel, st.mode === "ids" ? idsPanel() : filePanel());

    function idsPanel() {
      const counter = h("div", { class: "row wrap", style: { marginTop: "10px" } });
      const update = () => {
        const r = parseIdsLocal(st.text);
        mount(counter, pill(`${num(r.count)} شناسه معتبر`, r.count ? "blue" : ""),
          r.dup ? pill(`${num(r.dup)} تکراری حذف می‌شود`, "orange") : null,
          r.bad ? pill(`${num(r.bad)} مورد نامعتبر`, "red") : null);
      };
      const ta = h("textarea", { class: "textarea ltr", dir: "ltr", rows: 9, style: { fontFamily: "var(--mono)", minHeight: "220px" },
        placeholder: "1234567\n2345678, 3456789\n...", onInput: (e) => { st.text = e.target.value; update(); } });
      ta.value = st.text;
      update();
      return h("div", { class: "card" },
        h("div", { class: "card-title" }, icon("list", 18, 2.2), "شناسه فروشنده‌ها را وارد کنید"),
        h("p", { class: "card-sub" }, "شناسه‌ها را از اکسل، پیام یا هر جای دیگری کپی و اینجا بچسبانید. جداکننده مهم نیست (خط جدید، کاما، فاصله) و اعداد فارسی هم پذیرفته می‌شوند."),
        ta, counter);
    }

    function filePanel() {
      if (!st.file) {
        return h("div", { class: "col" },
          dropZone({ title: "فایل اکسل یا CSV را اینجا رها کنید", hint: "یا برای انتخاب کلیک کنید — xlsx، xls، csv",
            accept: ".xlsx,.xlsm,.xls,.csv", onFiles: async ([f]) => {
              try {
                const up = await upload(f);
                st.file = { file_id: up.file_id, name: f.name, size: up.size };
                st.sheet = ""; st.columns = {}; st.info = null;
                await inspect(true);
              } catch (e) { toast(e.message, "error"); }
            } }),
          h("div", { class: "group-foot" }, "دو کاربرد دارد: ۱) فهرست فروشنده‌ها با یا بدون ایمیل ۲) گزارشی که باید سهم هر فروشنده از آن جدا و برایش ارسال شود. ستون شناسه فروشنده خودکار تشخیص داده می‌شود."));
      }
      const info = st.info;
      if (!info) { inspect(false); return h("div", { class: "card" }, h("span", { class: "spinner" })); }
      const colOpts = [{ value: "", label: "— ندارد —" }, ...info.headers.map((x) => ({ value: x, label: x }))];
      const colSel = (key) => select(colOpts, st.columns[key] || "", (v) => { st.columns[key] = v; refreshCounts(); });
      const counts = h("div", { class: "row wrap" });
      const refreshCounts = () => {
        const idc = st.columns.id;
        const col = info.columns.find((x) => x.name === idc);
        mount(counts, idc ? pill(`${num(col ? col.unique : 0)} فروشنده یکتا`, "blue") : pill("ستون شناسه را انتخاب کنید", "red"),
          pill(`${num(info.row_count)} ردیف`), st.columns.email ? pill("ایمیل از فایل خوانده می‌شود", "green") : pill("ایمیل‌ها از پنل کراول می‌شوند", "purple"));
      };
      refreshCounts();
      return h("div", { class: "col", style: { gap: "16px" } },
        h("div", { class: "file-card" }, fileIcon(st.file.name),
          h("div", { style: { flex: 1, minWidth: 0 } }, h("b", {}, st.file.name), h("div", { class: "muted num", style: { fontSize: "12.5px" } },
            `${num(info.row_count)} ردیف · ${num(info.headers.length)} ستون`, info.sheets.length > 1 ? ` · ${num(info.sheets.length)} شیت` : "")),
          button("تغییر فایل", { kind: "sm", onClick: () => { st.file = null; st.info = null; render(); }, busy: false })),
        h("div", { class: "card" },
          h("div", { class: "card-title" }, icon("table", 18, 2.2), "ستون‌ها"),
          h("p", { class: "card-sub" }, "ستون‌ها خودکار تشخیص داده شدند؛ در صورت نیاز تغییرشان دهید."),
          h("div", { class: "grid-3" },
            field("شناسه فروشنده *", colSel("id")), field("ایمیل", colSel("email")), field("نام فروشنده", colSel("name"))),
          h("div", { class: "grid-3", style: { marginTop: "12px" } },
            info.sheets.length > 1 ? field("شیت", select(info.sheets.map((x) => ({ value: x, label: x })), info.sheet, async (v) => { st.sheet = v; st.columns = {}; await inspect(true); })) : null,
            field("سطر عنوان‌ها", input(String(st.header_row), null, { type: "number", onChange: async (v) => { st.header_row = Math.max(1, +v || 1); st.columns = {}; await inspect(true); } }))),
          h("div", { style: { marginTop: "14px" } }, counts)),
        h("div", { class: "group" },
          groupRow("فایل اختصاصی هر فروشنده را جدا کن و پیوست کن", toggle(st.split, (v) => { st.split = v; }), {
            icon: "scissors", color: "var(--orange)",
            sub: info.repeated_ids ? `هر فروشنده چند ردیف دارد؛ سهم هرکدام در یک فایل جدا ذخیره و فقط برای خودش ارسال می‌شود.`
              : "ردیف‌های هر فروشنده در فایلی جدا ذخیره و همراه ایمیل خودش ارسال می‌شود." })),
        previewTable(info));
    }

    async function inspect(rerender) {
      try {
        const info = await post("/api/file/inspect", { file_id: st.file.file_id, sheet: st.sheet, header_row: st.header_row });
        st.info = info; st.sheet = info.sheet;
        if (!st.columns.id && !st.columns.email && !st.columns.name) {
          st.columns = { ...info.detected };
          if (!src.file_id || src.file_id !== st.file.file_id) st.split = info.suggest_split;
        }
        if (rerender !== false) render();
      } catch (e) { toast(e.message, "error"); st.file = null; render(); }
    }

    const proceed = async () => {
      const payload = st.mode === "ids" ? { mode: "ids", text: st.text }
        : { mode: "file", file_id: st.file?.file_id, file_name: st.file?.name, sheet: st.sheet, header_row: st.header_row, columns: st.columns, split: st.split };
      if (st.mode === "file" && !st.file) throw new Error("ابتدا فایل را انتخاب کنید.");
      S.c = await post(`/api/campaigns/${id}/source`, payload);
      goStep(1);
    };

    mount(body,
      h("div", { class: "row", style: { marginBottom: "16px" } },
        segmented([{ value: "ids", label: "شناسه فروشنده‌ها", icon: "list" }, { value: "file", label: "فایل اکسل", icon: "table" }], st.mode,
          (v) => { st.mode = v; render(); }, { size: "lg" })),
      panel,
      footer(h("span", { class: "spacer" }), nextBtn("ساخت فهرست گیرندگان", proceed)));
    render();
  }

  function previewTable(info) {
    const heads = info.headers.slice(0, 8);
    return h("div", {},
      h("div", { class: "group-label" }, "پیش‌نمایش چند ردیف اول"),
      h("div", { class: "table-wrap", style: { maxHeight: "260px" } }, h("table", { class: "t" },
        h("thead", {}, h("tr", {}, heads.map((x) => h("th", {}, x)))),
        h("tbody", {}, info.preview.slice(0, 6).map((r) => h("tr", {}, heads.map((x) => h("td", {}, r[x]))))))));
  }

  // ------------------------------------------------------------------ step 1
  function stepRecipients() {
    const st = { q: "", filter: "all" };
    const summary = h("div");
    const jobSlot = h("div");
    const tableSlot = h("div");
    const tbody = h("tbody");
    const rowsById = new Map();

    const counts = () => {
      const r = S.c.recipients;
      const active = r.filter((x) => !x.excluded);
      const withEmail = active.filter((x) => isEmail(x.email));
      return { total: r.length, active: active.length, withEmail: withEmail.length, missing: active.length - withEmail.length, excluded: r.length - active.length };
    };

    const chooserSlot = h("div", { style: { marginTop: "16px" } });
    const refreshPlan = async () => {
      try {
        const plan = await get(`/api/campaigns/${id}/crawl-plan`);
        const k = counts();
        mount(chooserSlot, crawlChooser(plan, {
          title: k.missing ? `دریافت ایمیل ${num(k.missing)} فروشنده از پنل` : "به‌روزرسانی از پنل",
          onStart: (mode) => startCrawl(mode) }));
      } catch (e) { mount(chooserSlot); }
    };
    const crawledAll = () => S.c.recipients.filter((x) => !x.excluded && !isEmail(x.email)).every((x) => x.crawl_status);
    function renderSummary() {
      const k = counts();
      const running = S.job && !isFinished(S.job);
      mount(summary,
        h("div", { class: "grid-4" },
          miniStat("گیرندگان", k.total, "people", "var(--accent)"), miniStat("دارای ایمیل", k.withEmail, "check", "var(--green)"),
          miniStat("بدون ایمیل", k.missing, "warn", "var(--orange)"), miniStat("حذف از ارسال", k.excluded, "x", "var(--label-3)")),
        k.missing && !running && crawledAll() ? h("div", { class: "banner", style: { marginTop: "16px" } },
          h("div", { class: "b-ico" }, icon("warn", 18, 2)),
          h("div", { class: "txt" }, h("b", {}, `ایمیل ${num(k.missing)} فروشنده در پنل هم پیدا نشد`),
            h("small", {}, "ایمیل را در جدول زیر دستی وارد کنید یا آن‌ها را از ارسال حذف کنید. ایمیل‌های واردشده در دفترچه آدرس هم ذخیره می‌شوند.")),
          button("حذف از ارسال", { onClick: async () => { S.c = await post(`/api/campaigns/${id}/exclude`, { which: "no_email" }); renderSummary(); renderTable(); } })) : null,
        !k.missing && k.active && !running ? h("div", { class: "banner green", style: { marginTop: "16px" } },
          h("div", { class: "b-ico" }, icon("check", 18, 2.4)),
          h("div", { class: "txt" }, h("b", {}, "همه گیرندگان ایمیل دارند"), h("small", {}, "می‌توانید به مرحله نوشتن متن ایمیل بروید.")),
          button("ادامه", { kind: "primary", icon: "chevron", iconEnd: true, onClick: () => goStep(2), busy: false })) : null,
        k.active && !running ? chooserSlot : null);
      if (k.active && !running) refreshPlan();
    }

    async function startCrawl(mode) {
      const job = await post(`/api/campaigns/${id}/crawl`, { mode });
      showJob(job);
    }
    function showJob(job) {
      S.job = job;
      const card = jobCard(job, {
        onItem: (e) => {
          const rec = S.c.recipients.find((x) => x.seller_id === e.seller_id);
          if (!rec) return;
          if (e.email && (!rec.email || rec.origin?.email !== "manual")) { rec.email = e.email; rec.origin = { ...(rec.origin || {}), email: "crawl" }; }
          if (e.name && !rec.name) rec.name = e.name;
          rec.crawl_status = e.status;
          const tr = rowsById.get(rec.seller_id);
          if (tr) tr.replaceWith(row(rec));
          renderSummary();
        },
        onDone: async () => { S.c = await get(`/api/campaigns/${id}`); S.job = { state: "done" }; renderSummary(); renderTable(); },
      });
      S.offs.push(card.destroy);
      mount(jobSlot, h("div", { style: { marginTop: "16px" } }, card));
      renderSummary();
    }

    function row(r) {
      const emailInput = h("input", { class: ["edit-inline", r.email && !isEmail(r.email) && "invalid"], value: r.email || "", dir: "ltr",
        placeholder: "ایمیل را وارد کنید", onChange: async (e) => {
          try {
            const rec = await post(`/api/campaigns/${id}/recipients/${r.seller_id}`, { email: e.target.value });
            Object.assign(r, rec); e.target.classList.remove("invalid"); renderSummary();
          } catch (err) { e.target.classList.add("invalid"); toast(err.message, "error"); }
        } });
      const nameInput = h("input", { class: "edit-inline", value: r.name || "", placeholder: "—", onChange: async (e) => {
        Object.assign(r, await post(`/api/campaigns/${id}/recipients/${r.seller_id}`, { name: e.target.value }));
      } });
      const origin = ORIGIN[r.origin?.email];
      const crawlBad = { "not-found": "در پنل پیدا نشد", error: "خطا در کراول", partial: "ناقص" }[r.crawl_status];
      const tr = h("tr", { class: r.excluded ? "excluded" : "" },
        h("td", {}, h("label", { class: "check" }, h("input", { type: "checkbox", checked: !r.excluded, onChange: async (e) => {
          Object.assign(r, await post(`/api/campaigns/${id}/recipients/${r.seller_id}`, { excluded: !e.target.checked }));
          tr.classList.toggle("excluded", r.excluded); renderSummary();
        } }))),
        h("td", { class: "mono" }, r.seller_id),
        h("td", {}, nameInput),
        h("td", { class: "cell-email" }, emailInput),
        h("td", {}, origin ? pill(origin[0], origin[1]) : crawlBad ? pill(crawlBad, "red") : h("span", { class: "faint" }, "—")),
        S.c.source?.mode === "file" ? h("td", { class: "num" }, fa(r.row_count || 0)) : null);
      rowsById.set(r.seller_id, tr);
      return tr;
    }

    function renderTable() {
      rowsById.clear();
      const q = st.q.trim().toLowerCase();
      const rows = S.c.recipients.filter((r) => {
        if (st.filter === "missing" && (r.excluded || isEmail(r.email))) return false;
        if (st.filter === "excluded" && !r.excluded) return false;
        if (q && !(`${r.seller_id} ${r.name} ${r.email}`.toLowerCase().includes(q))) return false;
        return true;
      });
      mount(tbody, rows.slice(0, 1500).map(row));
      if (!rows.length) mount(tbody, h("tr", {}, h("td", { colspan: 6 }, h("div", { class: "empty", style: { padding: "26px" } }, "موردی پیدا نشد."))));
    }

    mount(tableSlot,
      h("div", { class: "row", style: { margin: "24px 0 10px" } },
        h("div", { style: { position: "relative", width: "260px" } },
          input("", (v) => { st.q = v; renderTable(); }, { placeholder: "جستجو در شناسه، نام یا ایمیل", style: { paddingInlineStart: "34px" } }),
          h("span", { style: { position: "absolute", top: "9px", insetInlineStart: "10px", color: "var(--label-3)" } }, icon("search", 17))),
        segmented([{ value: "all", label: "همه" }, { value: "missing", label: "بدون ایمیل" }, { value: "excluded", label: "حذف‌شده" }], "all",
          (v) => { st.filter = v; renderTable(); }),
        h("span", { class: "spacer" }),
        button("حذف بدون‌ایمیل‌ها از ارسال", { kind: "sm", onClick: async () => { S.c = await post(`/api/campaigns/${id}/exclude`, { which: "no_email" }); renderSummary(); renderTable(); } }),
        button("خروجی اکسل", { kind: "sm", icon: "download", onClick: async () => { const r = await post("/api/sellers/export", { ids: S.c.recipients.map((x) => x.seller_id) }); openPath(r.path, true); toast("فایل اکسل ساخته شد", "ok"); } })),
      h("div", { class: "table-wrap" }, h("table", { class: "t" },
        h("thead", {}, h("tr", {}, h("th", { style: { width: "36px" } }, ""), h("th", {}, "شناسه"), h("th", {}, "نام فروشنده"), h("th", {}, "ایمیل"), h("th", {}, "منبع"),
          S.c.source?.mode === "file" ? h("th", {}, "ردیف") : null)),
        tbody)));

    mount(body, summary, jobSlot, tableSlot,
      footer(backBtn(), h("span", { class: "spacer" }), nextBtn("نوشتن متن ایمیل")));
    renderSummary(); renderTable();
    const running = store.lastCrawl;
    get("/api/jobs").then((jobs) => {
      const j = jobs.find((x) => x.kind === "crawl" && x.meta?.campaign === id && !isFinished(x));
      if (j) showJob(j);
    });
    void running;
  }

  // ------------------------------------------------------------------ step 2
  function stepCompose() {
    const compose = S.c.compose;
    const previewSlot = h("div", { class: "sticky" });
    const subjectEl = h("input", { class: "subject", placeholder: "موضوع ایمیل", value: compose.subject || "" });
    const bodyEl = h("textarea", { placeholder: "متن ایمیل را بنویسید، از قالب‌ها شروع کنید یا از هوش مصنوعی کمک بگیرید…" });
    bodyEl.value = compose.body || "";
    let lastFocus = bodyEl;
    let previewSeller = "";
    const persist = debounce(() => {
      patch(`/api/campaigns/${id}`, { compose: { subject: subjectEl.value, body: bodyEl.value } })
        .then((c) => { S.c = c; refreshPreview(); }).catch((e) => toast(e.message, "error"));
    }, 450);
    subjectEl.addEventListener("input", persist); bodyEl.addEventListener("input", persist);
    subjectEl.addEventListener("focus", () => (lastFocus = subjectEl)); bodyEl.addEventListener("focus", () => (lastFocus = bodyEl));

    const insert = (key) => {
      const el = lastFocus; const token = `{${key}}`;
      const s = el.selectionStart ?? el.value.length; const e = el.selectionEnd ?? el.value.length;
      el.value = el.value.slice(0, s) + token + el.value.slice(e);
      el.focus(); el.selectionStart = el.selectionEnd = s + token.length; persist();
    };
    const setText = (subject, text) => { if (subject !== undefined) subjectEl.value = subject; if (text !== undefined) bodyEl.value = text; persist(); };

    const chips = h("div", { class: "ed-tools" });
    const templatesSlot = h("div", { class: "grid-3", style: { marginBottom: "18px" } });

    async function loadTemplates() {
      if (!S.templates) S.templates = await get("/api/templates");
      const extra = (S.c.source?.headers || []).filter((x) => !/^(seller id|email|seller name)$/i.test(x)).slice(0, 10);
      mount(chips, h("small", { class: "muted", style: { marginInlineEnd: "4px" } }, "درج:"),
        S.templates.placeholders.map((p) => h("button", { class: "chip", type: "button", onClick: () => insert(p.key) }, p.label)),
        extra.map((x) => h("button", { class: "chip", type: "button", title: "ستون فایل منبع", onClick: () => insert(x) }, icon("table", 12), x)));
      const hasAtt = S.c.attachments?.mode !== "none" || S.c.source?.split;
      const list = [...S.templates.templates].sort((a, b) => (b.needs_attachment === hasAtt) - (a.needs_attachment === hasAtt));
      mount(templatesSlot, list.slice(0, 6).map((t) => h("button", { class: ["template-card", compose.template_id === t.id && "on"], type: "button",
        onClick: async () => {
          if ((bodyEl.value.trim() && bodyEl.value !== t.body) && !(await confirmSheet("جایگزینی متن", "متن فعلی با این قالب جایگزین شود؟", { ok: "جایگزین کن" }))) return;
          compose.template_id = t.id; setText(t.subject, t.body); patch(`/api/campaigns/${id}`, { compose: { template_id: t.id } });
          loadTemplates();
        } },
        h("div", { class: "row" }, h("span", { style: { color: "var(--accent)" } }, icon(t.icon, 17, 2)), h("b", {}, t.title),
          t.needs_attachment ? h("span", { class: "spacer" }) : null, t.needs_attachment ? pill("با پیوست", "orange") : null),
        h("p", {}, t.body.replace(/\{(\w+)\}/g, (m, k) => ({ seller_name: "فروشگاه نمونه", seller_id: "۱۲۳۴۵۶", month: "آذر ۱۴۰۵", row_count: "۱۲" }[k] || m))))));
    }

    async function refreshPreview() {
      try {
        const p = await post(`/api/campaigns/${id}/preview`, { seller_id: previewSeller });
        previewSeller = p.seller_id;
        renderPreview(p);
      } catch (e) { mount(previewSlot, h("div", { class: "muted" }, e.message)); }
    }
    function renderPreview(p) {
      const opts = S.c.recipients.filter((r) => !r.excluded).slice(0, 80).map((r) => ({ value: r.seller_id, label: `${r.name || r.seller_id}` }));
      mount(previewSlot,
        h("div", { class: "row", style: { marginBottom: "10px" } }, h("b", {}, "پیش‌نمایش"), h("span", { class: "spacer" }),
          opts.length ? select(opts, previewSeller, (v) => { previewSeller = v; refreshPreview(); }, { style: { width: "220px", height: "32px" } }) : null),
        mailPreview(p),
        p.unknown?.length ? h("div", { class: "banner", style: { marginTop: "12px" } }, h("div", { class: "b-ico" }, icon("warn", 16, 2)),
          h("div", { class: "txt" }, h("b", {}, "جای‌نگهدار ناشناخته"), h("small", { class: "ltr" }, p.unknown.map((x) => `{${x}}`).join("  ")))) : null);
    }

    const aiSheet = () => {
      const st = { brief: "", tone: "formal", att: S.c.attachments?.mode !== "none" || !!S.c.source?.split, improve: !!bodyEl.value.trim() };
      const hasKey = store.state.settings.derived.has_ai_key;
      sheet({ title: "نوشتن ایمیل با هوش مصنوعی", subtitle: hasKey ? "هدف ایمیل را در یک یا دو جمله بگویید؛ متن کامل و شخصی‌سازی‌شده تحویل بگیرید."
        : "کلید هوش مصنوعی تنظیم نشده؛ نویسنده هوشمند آفلاین یک پیش‌نویس ساختاریافته می‌سازد. برای متن طبیعی‌تر، کلید Claude را در تنظیمات وارد کنید.",
      body: h("div", { class: "col", style: { gap: "14px" } },
        field("هدف ایمیل", h("textarea", { class: "textarea", rows: 4, placeholder: "مثلاً: ارسال صورت‌حساب تسویه آبان و درخواست بررسی مغایرت‌ها تا پایان هفته", onInput: (e) => (st.brief = e.target.value) })),
        field("لحن", segmented([{ value: "formal", label: "رسمی" }, { value: "friendly", label: "صمیمی" }, { value: "short", label: "کوتاه" }], st.tone, (v) => (st.tone = v))),
        h("div", { class: "group" },
          groupRow("ایمیل پیوست دارد", toggle(st.att, (v) => (st.att = v))),
          bodyEl.value.trim() ? groupRow("بهبود متن فعلی به‌جای نوشتن از صفر", toggle(st.improve, (v) => (st.improve = v))) : null)),
      actions: [{ label: hasKey ? "بنویس" : "ساخت پیش‌نویس", kind: "primary", icon: "sparkles", onClick: async () => {
        if (!st.brief.trim()) { toast("هدف ایمیل را بنویسید.", "warn"); return false; }
        const placeholders = ["seller_name", "seller_id", "email", "date", "month", ...(st.att ? ["file_name", "row_count"] : [])];
        const r = await post("/api/compose/ai", { brief: st.brief, tone: st.tone, has_attachment: st.att, placeholders,
          current_body: st.improve ? bodyEl.value : "" });
        setText(r.subject, r.body);
        toast(r.offline ? "پیش‌نویس آفلاین ساخته شد" : "متن ایمیل با هوش مصنوعی نوشته شد", "ok");
      } }, { label: "انصراف" }] });
    };

    const docxInput = h("input", { type: "file", accept: ".docx", class: "hidden", onChange: async (e) => {
      const f = e.target.files[0]; e.target.value = ""; if (!f) return;
      try { const up = await upload(f); const r = await post("/api/file/docx", { file_id: up.file_id }); setText(undefined, r.body); toast("متن از فایل Word وارد شد", "ok"); }
      catch (err) { toast(err.message, "error"); }
    } });

    mount(body,
      h("div", { class: "row", style: { marginBottom: "12px" } }, h("h3", { style: { margin: 0, fontSize: "17px" } }, "از یک قالب شروع کنید"),
        h("span", { class: "spacer" }),
        button("نوشتن با هوش مصنوعی", { kind: "tinted", icon: "sparkles", onClick: aiSheet, busy: false }),
        button("از فایل Word", { icon: "doc", onClick: () => docxInput.click(), busy: false }), docxInput),
      templatesSlot,
      h("div", { class: "split-view" },
        h("div", {}, h("div", { class: "editor" }, subjectEl, chips, bodyEl),
          h("div", { class: "group-foot" }, "جای‌نگهدارها مثل ", h("span", { class: "ltr mono" }, "{seller_name}"), " برای هر گیرنده با مقدار خودش جایگزین می‌شوند. ",
            h("b", {}, "**متن**"), " پررنگ می‌شود و خط‌های شروع‌شده با «-» فهرست می‌شوند.")),
        previewSlot),
      footer(backBtn(), h("span", { class: "spacer" }), nextBtn("پیوست‌ها")));
    loadTemplates().catch((e) => toast(e.message, "error"));
    refreshPreview();
  }

  // ------------------------------------------------------------------ step 3
  function stepAttachments() {
    const att = S.c.attachments;
    const detail = h("div", { style: { marginTop: "18px" } });
    const isFile = S.c.source?.mode === "file";
    const hasNative = store.state.app.native_dialogs;
    const options = h("div", { class: "col" });

    const setMode = async (mode) => {
      S.c = await patch(`/api/campaigns/${id}`, { attachments: { mode } });
      renderOptions(); renderDetail();
    };
    const opt = (mode, title, sub, ic, color, disabled) => h("button", { class: ["option-card", S.c.attachments.mode === mode && "on"], type: "button",
      disabled: disabled ? true : null, style: disabled ? { opacity: .5, cursor: "not-allowed" } : null, onClick: () => !disabled && setMode(mode) },
    h("div", { class: "o-ico", style: { background: color } }, icon(ic, 19, 2)), h("div", {}, h("b", {}, title), h("small", {}, sub)), h("span", { class: "radio" }));

    function renderOptions() {
      mount(options,
        h("div", { class: "grid-2" },
          opt("split", "فایل اختصاصی هر فروشنده", isFile ? "ردیف‌های هر فروشنده از فایل منبع جدا و فقط برای خودش ارسال می‌شود." : "برای این گزینه، منبع کمپین باید فایل اکسل باشد.", "scissors", "linear-gradient(160deg,#FFB340,#FF9500)", !isFile),
          opt("folder", "پوشه فایل‌های آماده", "از پوشه‌ای که نام فایل‌هایش با شناسه فروشنده شروع می‌شود، فایل هر نفر را پیدا می‌کند.", "folder", "linear-gradient(160deg,#5AC8FA,#007AFF)"),
          opt("shared", "یک فایل مشترک برای همه", "یک یا چند فایل (مثل بخشنامه) برای همه گیرندگان پیوست می‌شود.", "clip", "linear-gradient(160deg,#C77DFF,#AF52DE)"),
          opt("none", "بدون پیوست", "فقط متن ایمیل ارسال می‌شود.", "mail", "linear-gradient(160deg,#B0B0B8,#8E8E93)")));
    }

    function statusLine(s) {
      if (!s || s.mode === "none") return null;
      if (s.needs_split) return null;
      const total = S.c.readiness.recipients;
      return h("div", { class: ["banner", s.missing_count ? "" : "green"], style: { marginTop: "14px" } },
        h("div", { class: "b-ico" }, icon(s.missing_count ? "warn" : "check", 17, 2.2)),
        h("div", { class: "txt" }, h("b", { class: "num" }, s.mode === "shared" ? `${num((s.files || []).length)} فایل برای همه پیوست می‌شود`
          : `${num(s.matched)} از ${num(total)} گیرنده فایل پیوست دارند`),
        s.missing_count ? h("small", { class: "ltr" }, "بدون فایل: " + s.missing.slice(0, 12).join("، ") + (s.missing_count > 12 ? " …" : "")) : null));
    }

    function renderDetail() {
      const mode = S.c.attachments.mode;
      const s = S.c.attachment_status;
      const policy = h("div", { class: "group", style: { marginTop: "14px" } },
        groupRow("اگر فایل پیوست پیدا نشد، به آن فروشنده ایمیل نفرست", toggle(S.c.attachments.missing_policy !== "send", async (v) => {
          S.c = await patch(`/api/campaigns/${id}`, { attachments: { missing_policy: v ? "skip" : "send" } });
        }), { sub: "اگر خاموش باشد، ایمیل بدون پیوست ارسال می‌شود." }));
      if (mode === "split") {
        const fmt = { v: att.split_format || "xlsx" };
        const jobSlot = h("div");
        const run = async () => {
          const job = await post(`/api/campaigns/${id}/split`, { format: fmt.v });
          const card = jobCard(job, { compact: true, onDone: async () => { S.c = await get(`/api/campaigns/${id}`); renderDetail(); } });
          S.offs.push(card.destroy);
          mount(jobSlot, h("div", { style: { marginTop: "14px" } }, card));
        };
        mount(detail, h("div", { class: "card" },
          h("div", { class: "card-title" }, icon("scissors", 18, 2.2), "جداسازی فایل منبع"),
          h("p", { class: "card-sub" }, `فایل «${S.c.source.file_name}» بر اساس ستون «${S.c.source.columns.id}» برای ${num(S.c.readiness.recipients)} فروشنده جدا می‌شود. نام هر فایل همان شناسه فروشنده است.`),
          h("div", { class: "row wrap" }, field("قالب فایل‌ها", segmented([{ value: "xlsx", label: "اکسل" }, { value: "csv", label: "CSV" }], fmt.v, (v) => (fmt.v = v))),
            h("span", { class: "spacer" }),
            S.c.attachments.split_dir ? button("نمایش پوشه", { icon: "folder", onClick: () => openPath(S.c.attachments.split_dir) }) : null,
            button(S.c.attachments.split_dir ? "ساخت دوباره" : "ساخت فایل‌ها", { kind: "primary", icon: "scissors", onClick: run })),
          jobSlot, statusLine(s)), policy);
      } else if (mode === "folder") {
        const pathInput = input(att.folder || "", null, { ltr: true, placeholder: "C:\\Reports\\Aban", onChange: async (v) => {
          S.c = await patch(`/api/campaigns/${id}`, { attachments: { folder: v } }); renderDetail(); } });
        mount(detail, h("div", { class: "card" },
          h("div", { class: "card-title" }, icon("folder", 18, 2.2), "پوشه فایل‌ها"),
          h("p", { class: "card-sub" }, "فایلی که نامش با شناسه فروشنده شروع شود (مثلاً 123456.xlsx یا 123456-آبان.pdf) برای همان فروشنده پیوست می‌شود."),
          h("div", { class: "row" }, h("div", { style: { flex: 1 } }, pathInput),
            hasNative ? button("انتخاب پوشه", { icon: "folder", onClick: async () => {
              const r = await post("/api/dialog/folder", {}); if (r.path) { S.c = await patch(`/api/campaigns/${id}`, { attachments: { folder: r.path } }); renderDetail(); } } }) : null),
          h("div", { style: { marginTop: "12px" } }, dropZone({ title: "یا فایل‌ها را اینجا رها کنید", hint: "چند فایل با هم؛ در پوشه کمپین کپی می‌شوند", multiple: true,
            onFiles: async (files) => {
              const ids = []; for (const f of files) ids.push((await upload(f)).file_id);
              S.c = await post(`/api/campaigns/${id}/folder-files`, { file_ids: ids }); toast(`${fa(files.length)} فایل اضافه شد`, "ok"); renderDetail();
            } })),
          statusLine(s)), policy);
      } else if (mode === "shared") {
        const names = att.shared_names || {};
        mount(detail, h("div", { class: "card" },
          h("div", { class: "card-title" }, icon("clip", 18, 2.2), "فایل‌های مشترک"),
          (S.c.attachments.shared_files || []).map((fid) => h("div", { class: "file-card", style: { marginBottom: "8px", boxShadow: "none", background: "var(--fill-2)" } },
            fileIcon(names[fid] || "file"), h("b", { style: { flex: 1 } }, names[fid] || fid),
            button("", { icon: "trash", kind: "sm plain", onClick: async () => { S.c = await del(`/api/campaigns/${id}/shared/${fid}`); renderDetail(); } }))),
          dropZone({ title: "فایل را اینجا رها کنید", hint: "PDF، اکسل، تصویر یا هر فایل دیگر", multiple: true, onFiles: async (files) => {
            for (const f of files) { const up = await upload(f); S.c = await post(`/api/campaigns/${id}/shared`, { file_id: up.file_id }); }
            renderDetail();
          } })));
      } else {
        mount(detail);
      }
      renderOptions();
    }

    mount(body,
      h("p", { class: "muted", style: { marginTop: 0 } }, "هر گیرنده چه فایلی دریافت کند؟"),
      options, detail,
      footer(backBtn(), h("span", { class: "spacer" }), nextBtn("بازبینی و ارسال")));
    renderOptions(); renderDetail();
    if (att.mode === "split" && !att.split_dir && isFile) toast("برای ساخت فایل اختصاصی هر فروشنده «ساخت فایل‌ها» را بزنید.", "info");
  }

  // ------------------------------------------------------------------ step 4
  function stepSend() {
    const r = S.c.readiness;
    const st = { dry: false, delay: String(store.state.settings.sending.delay ?? 1.5), testTo: store.state.settings.derived.from_address || "" };
    const jobSlot = h("div");
    const live = h("tbody");
    const results = h("div");
    const derived = store.state.settings.derived;
    const sendStats = S.c.stats || {};

    const item = (ok, title, sub, action, level) => h("div", { class: "summary-item" },
      h("span", { class: ["check-ico", !ok && (level || "warn")] }, icon(ok ? "check" : level === "bad" ? "x" : "warn", 13, 3)),
      h("div", { style: { flex: 1 } }, h("b", {}, title), sub ? h("div", { class: "muted", style: { fontSize: "12.5px" } }, sub) : null), action);

    const att = S.c.attachment_status;
    const attLabel = { none: "بدون پیوست", split: "فایل اختصاصی هر فروشنده", folder: "فایل اختصاصی از پوشه", shared: "فایل مشترک" }[att.mode];

    function showJob(job) {
      S.job = job;
      mount(live);
      const card = jobCard(job, {
        onItem: (e) => {
          if (e.kind !== "send") return;
          const [t, c] = SEND_STATUS[e.status] || [e.status, ""];
          live.prepend(h("tr", {}, h("td", { class: "mono" }, e.seller_id), h("td", {}, e.name || "—"), h("td", { class: "cell-email" }, e.email),
            h("td", {}, pill(t, c)), h("td", { class: "muted", style: { fontSize: "12px" } }, e.detail || h("span", { class: "ltr" }, e.attachment || ""))));
        },
        onDone: async (j) => {
          S.c = await get(`/api/campaigns/${id}`); refreshState();
          renderResults(j);
        },
      });
      S.offs.push(card.destroy);
      mount(jobSlot, h("div", { class: "col", style: { gap: "14px", marginTop: "18px" } }, card,
        h("div", { class: "table-wrap", style: { maxHeight: "340px" } }, h("table", { class: "t" },
          h("thead", {}, h("tr", {}, h("th", {}, "شناسه"), h("th", {}, "نام"), h("th", {}, "ایمیل"), h("th", {}, "وضعیت"), h("th", {}, "جزئیات"))), live))));
    }

    function renderResults(job) {
      const res = job?.result || {};
      const s = S.c.stats || {};
      mount(results, h("div", { class: ["banner", job?.result?.dry_run ? "blue" : s.failed ? "" : "green"], style: { marginTop: "18px" } },
        h("div", { class: "b-ico" }, icon(job?.result?.dry_run ? "flask" : s.failed ? "warn" : "check", 18, 2.2)),
        h("div", { class: "txt" },
          h("b", {}, job?.result?.dry_run ? `شبیه‌سازی کامل شد — ${num(res.sent || 0)} ایمیل آماده ارسال است` : `${num(s.sent)} ایمیل ارسال شد`),
          h("small", { class: "num" }, job?.result?.dry_run ? "هیچ ایمیلی واقعاً ارسال نشد. اگر همه‌چیز درست است، حالت «ارسال واقعی» را انتخاب کنید."
            : `ناموفق: ${num(s.failed)} · ردشده: ${num(s.skipped)} · کل: ${num(s.total)}`)),
        res.report ? button("گزارش اکسل", { icon: "table", onClick: () => openPath(res.report, true) }) : null,
        !job?.result?.dry_run && s.failed ? button("ارسال دوباره ناموفق‌ها", { kind: "primary", icon: "refresh", onClick: async () => showJob(await post(`/api/campaigns/${id}/send`, { only_failed: true, delay: +st.delay })) }) : null));
    }

    const start = async () => {
      const k = r.with_email;
      if (!st.dry && !(await confirmSheet("شروع ارسال", `ایمیل برای ${fa(k)} فروشنده ارسال شود؟ این کار قابل بازگشت نیست.`, { ok: "ارسال کن" }))) return;
      showJob(await post(`/api/campaigns/${id}/send`, { dry_run: st.dry, delay: +st.delay }));
      mount(results);
    };

    mount(body,
      h("div", { class: "split-view" },
        h("div", { class: "card" },
          h("div", { class: "card-title" }, "چک‌لیست ارسال"),
          h("div", { style: { marginTop: "6px" } },
            item(r.with_email > 0 && r.with_email === r.recipients, `${num(r.with_email)} گیرنده آماده`,
              r.with_email < r.recipients ? `${num(r.recipients - r.with_email)} نفر ایمیل ندارند و ارسال نمی‌شوند.` : "همه گیرندگان ایمیل معتبر دارند.",
              button("ویرایش", { kind: "sm plain", onClick: () => goStep(1), busy: false }), r.with_email ? "warn" : "bad"),
            item(!!S.c.compose.subject && !!S.c.compose.body, S.c.compose.subject && S.c.compose.body ? "متن ایمیل آماده است" : "متن یا موضوع ایمیل خالی است",
              S.c.compose.subject ? h("span", {}, "موضوع: ", S.c.compose.subject) : "موضوع ایمیل نوشته نشده.",
              button("ویرایش", { kind: "sm plain", onClick: () => goStep(2), busy: false }), "bad"),
            item(att.ready && !att.missing_count, attLabel, att.mode === "none" ? "" : att.needs_split ? "فایل‌ها هنوز ساخته نشده‌اند." : att.missing_count ? `${num(att.missing_count)} گیرنده فایل ندارند.` : "همه فایل‌ها آماده‌اند.",
              button("ویرایش", { kind: "sm plain", onClick: () => goStep(3), busy: false }), att.ready ? "warn" : "bad"),
            item(r.smtp_ready, derived.from_address ? h("span", { class: "ltr" }, derived.from_address) : "حساب ایمیل", r.smtp_ready ? `از طریق ${store.state.settings.smtp.host}` : "رمز عبور ایمیل وارد نشده است.",
              r.smtp_ready ? button("تست اتصال", { kind: "sm plain", onClick: async () => { const t = await post("/api/smtp/test"); toast(`اتصال برقرار است (${fa(t.ms)} میلی‌ثانیه)`, "ok"); } })
                : button("تنظیم", { kind: "sm plain", onClick: () => window.mmGo("#/settings"), busy: false }), "bad"))),
        h("div", { class: "col", style: { gap: "16px" } },
          h("div", { class: "card" },
            h("div", { class: "card-title" }, icon("flask", 18, 2.2), "ایمیل آزمایشی"),
            h("p", { class: "card-sub" }, "قبل از ارسال گروهی، نسخه واقعی ایمیل اولین گیرنده را برای خودتان بفرستید."),
            h("div", { class: "row" }, h("div", { style: { flex: 1 } }, input(st.testTo, (v) => (st.testTo = v), { ltr: true, placeholder: "you@company.com" })),
              button("ارسال آزمایشی", { kind: "tinted", icon: "send", onClick: async () => { await post(`/api/campaigns/${id}/test`, { to: st.testTo }); toast("ایمیل آزمایشی ارسال شد", "ok"); } }))),
          h("div", { class: "card" },
            h("div", { class: "card-title" }, icon("send", 18, 2.2), "ارسال"),
            h("div", { class: "col", style: { gap: "14px", marginTop: "10px" } },
              segmented([{ value: "real", label: "ارسال واقعی", icon: "send" }, { value: "dry", label: "شبیه‌سازی", icon: "flask" }], "real", (v) => (st.dry = v === "dry")),
              field("فاصله بین ایمیل‌ها", select(delayOptions(st.delay), st.delay, (v) => (st.delay = v))),
              button(sendStats.sent ? "ادامه ارسال به باقی‌مانده‌ها" : "شروع ارسال", { kind: "primary lg", icon: "send", disabled: !r.can_send, onClick: start }),
              !r.can_send ? h("small", { class: "muted" }, r.issues.join(" ")) : null)))),
      results, jobSlot,
      footer(backBtn(), h("span", { class: "spacer" }), S.c.workspace ? button("پوشه کمپین", { icon: "folder", onClick: () => openPath(S.c.workspace) }) : null,
        button("گزارش اکسل", { icon: "table", onClick: async () => { const rep = await post(`/api/campaigns/${id}/report`); openPath(rep.path, true); } })));

    get("/api/jobs").then((jobs) => {
      const j = jobs.find((x) => x.kind === "send" && x.meta?.campaign === id);
      if (j && !isFinished(j)) showJob(j);
      else if (sendStats.last_run_at) renderResults({ result: { dry_run: sendStats.last_run_dry } });
    });
  }

  // ------------------------------------------------------------------ boot
  load().then(() => {
    S.step = Math.min(S.c.step || 0, maxReachable());
    renderStepper(); renderStep();
  }).catch((e) => mount(page, emptyState("warn", "کمپین باز نشد", e.message)));
  const off = on("campaign", (c) => { if (c.id === id && S.c && S.step !== 1 && S.step !== 4) get(`/api/campaigns/${id}`).then((x) => { S.c = x; }); });
  window.addEventListener("beforeunload", flush.now);
  return { destroy: () => { flush.now(); cleanup(); off(); window.removeEventListener("beforeunload", flush.now); } };
}

function delayOptions(current) {
  const opts = [{ value: "0.5", label: "سریع — نیم ثانیه" }, { value: "1.5", label: "عادی — ۱٫۵ ثانیه" }, { value: "3", label: "محتاط — ۳ ثانیه" }, { value: "6", label: "خیلی آهسته — ۶ ثانیه" }];
  if (!opts.some((o) => o.value === current)) opts.unshift({ value: current, label: `طبق تنظیمات — ${fa(current)} ثانیه` });
  return opts;
}

function miniStat(label, value, ic, color) {
  return h("div", { class: "stat" }, h("div", { class: "k" }, h("span", { style: { color } }, icon(ic, 15, 2.2)), label),
    h("div", { class: "v num" }, num(value)));
}

export function mailPreview(p) {
  const initials = (p.from_name || p.from || "M").trim().slice(0, 1).toUpperCase();
  const frame = h("iframe", { style: { width: "100%", border: 0, minHeight: "260px", background: "#fff", display: "block" }, sandbox: "allow-same-origin" });
  frame.srcdoc = p.html || `<pre style="font-family:Tahoma;white-space:pre-wrap;direction:rtl">${(p.text || "").replace(/[<&]/g, (c) => ({ "<": "&lt;", "&": "&amp;" }[c]))}</pre>`;
  frame.addEventListener("load", () => { try { frame.style.height = Math.min(470, frame.contentDocument.body.scrollHeight + 24) + "px"; } catch { /* sandboxed */ } });
  return h("div", { class: "mail-preview" },
    h("div", { class: "mail-bar" }, h("i", { style: { background: "#FF5F57" } }), h("i", { style: { background: "#FEBC2E" } }), h("i", { style: { background: "#28C840" } })),
    h("div", { class: "mail-meta" }, h("div", { class: "avatar" }, initials),
      h("div", { style: { flex: 1, minWidth: 0 } },
        h("div", { class: "subj" }, p.subject || h("span", { class: "faint" }, "بدون موضوع")),
        h("div", { class: "who" }, "از: ", h("span", { class: "ltr" }, p.from_name ? `${p.from_name} <${p.from}>` : p.from || "—")),
        h("div", { class: "who" }, "به: ", h("span", { class: "ltr" }, p.to || "—")))),
    h("div", { class: "mail-body", style: { padding: 0 } }, frame),
    p.attachments?.length ? h("div", { class: "mail-attach" }, p.attachments.map((a) => h("div", { class: "att" }, icon("clip", 14), a.name, h("span", { style: { color: "#8E8E93" } }, bytes(a.size))))) : null);
}
