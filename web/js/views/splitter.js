// Standalone Excel splitter (ExcelSeparator, rebuilt).
import { h, mount, icon, button, toggle, segmented, select, field, input, groupRow, pill, toast, dropZone, fileIcon, upload, post, num, fa, openPath, store } from "../core.js";
import { jobCard } from "../jobs.js";

export function splitterView(page) {
  const st = { file: null, info: null, sheet: "", header_row: 1, column: "", format: "xlsx", single: false, blanks: true, out: "" };
  const main = h("div");
  const jobSlot = h("div", { style: { marginTop: "18px" } });
  const view = { offs: [], destroy: () => view.offs.forEach((f) => f()) };

  async function inspect() {
    st.info = await post("/api/file/inspect", { file_id: st.file.file_id, sheet: st.sheet, header_row: st.header_row });
    st.sheet = st.info.sheet;
    if (!st.info.headers.includes(st.column)) st.column = st.info.detected.id || "";
    render();
  }

  function render() {
    if (!st.file) {
      mount(main, dropZone({ title: "فایل اکسل یا CSV را اینجا رها کنید", hint: "xlsx، xlsm، xls و csv — بدون محدودیت تعداد ردیف",
        accept: ".xlsx,.xlsm,.xls,.csv", onFiles: async ([f]) => {
          try { const up = await upload(f); st.file = { ...up, name: f.name }; await inspect(); } catch (e) { toast(e.message, "error"); }
        } }));
      return;
    }
    const info = st.info;
    const col = info.columns.find((c) => c.name === st.column);
    const groups = col ? col.unique + (st.blanks && col.blank ? 1 : 0) : 0;
    const outcome = !col ? "ستون مبنا را انتخاب کنید"
      : st.single ? `یک فایل اکسل با ${fa(groups)} شیت ساخته می‌شود` : `${fa(groups)} فایل ${st.format} ساخته می‌شود`;
    const colOptions = [{ value: "", label: "— انتخاب کنید —" }, ...info.columns.map((c) => ({ value: c.name, label: `${c.name} (${fa(c.unique)} گروه)` }))];
    mount(main,
      h("div", { class: "file-card" }, fileIcon(st.file.name),
        h("div", { style: { flex: 1 } }, h("b", {}, st.file.name), h("div", { class: "muted num", style: { fontSize: "12.5px" } }, `${num(info.row_count)} ردیف · ${num(info.headers.length)} ستون`)),
        button("فایل دیگر", { kind: "sm", onClick: () => { st.file = null; st.info = null; render(); }, busy: false })),
      h("div", { class: "group-label" }, "فایل"),
      h("div", { class: "group" },
        info.sheets.length > 1 ? groupRow("شیت", select(info.sheets.map((s) => ({ value: s, label: s })), st.sheet, async (v) => { st.sheet = v; await inspect(); }, { bare: true })) : null,
        groupRow("سطر عنوان‌ها", h("input", { class: "input bare num", type: "number", min: 1, value: st.header_row, style: { width: "80px" },
          onChange: async (e) => { st.header_row = Math.max(1, +e.target.value || 1); await inspect(); } }), { sub: "اگر بالای جدول چند سطر توضیح دارید، شماره سطر نام ستون‌ها را وارد کنید." })),
      h("div", { class: "group-label" }, "جداسازی"),
      h("div", { class: "group" },
        groupRow("بر اساس ستون", select(colOptions, st.column, (v) => { st.column = v; render(); }, { bare: true })),
        groupRow("خروجی", segmented([{ value: "files", label: "فایل‌های جدا" }, { value: "single", label: "یک فایل چندشیتی" }], st.single ? "single" : "files", (v) => { st.single = v === "single"; if (st.single) st.format = "xlsx"; render(); })),
        !st.single ? groupRow("قالب", segmented([{ value: "xlsx", label: "Excel" }, { value: "csv", label: "CSV" }], st.format, (v) => { st.format = v; render(); })) : null,
        groupRow("سطرهای بدون مقدار در یک فایل جدا", toggle(st.blanks, (v) => { st.blanks = v; render(); }), { sub: col && col.blank ? `${fa(col.blank)} سطر در این ستون خالی است.` : "" }),
        groupRow("پوشه خروجی", h("input", { class: "input bare ltr", placeholder: "پیش‌فرض: Documents/MasterMail/Splits", value: st.out, style: { width: "320px" }, onChange: (e) => (st.out = e.target.value) }),
          { sub: "خالی بگذارید تا پوشه‌ای تازه در محل کار برنامه ساخته شود." })),
      h("div", { class: "banner blue", style: { marginTop: "18px" } }, h("div", { class: "b-ico" }, icon("info", 18, 2)),
        h("div", { class: "txt" }, h("b", {}, outcome), h("small", {}, "عنوان ستون‌ها در همه فایل‌ها حفظ می‌شود؛ نام فایل‌ها از مقدار ستون ساخته و برای ویندوز امن می‌شود.")),
        button("شروع جداسازی", { kind: "primary", icon: "scissors", disabled: !col, onClick: run })));
  }

  async function run() {
    const job = await post("/api/split", { file_id: st.file.file_id, name: st.file.name, sheet: st.sheet, header_row: st.header_row, column: st.column,
      format: st.format, single_workbook: st.single, include_blanks: st.blanks, output_dir: st.out });
    const card = jobCard(job, { compact: true, onDone: (j) => {
      if (j.result?.output_dir) card.appendChild(h("div", { class: "row", style: { marginTop: "14px" } },
        pill(`${fa(j.result.file_count)} فایل · ${fa(j.result.row_count)} ردیف`, "green"), h("span", { class: "spacer" }),
        button("باز کردن پوشه خروجی", { kind: "primary", icon: "folder", onClick: () => openPath(j.result.output_dir) })));
    } });
    view.offs.push(card.destroy);
    mount(jobSlot, card);
  }

  mount(page, h("h1", { class: "large-title" }, "جداساز اکسل"),
    h("p", { class: "page-sub" }, "یک فایل را بر اساس مقادیر یک ستون به چند فایل یا چند شیت تبدیل کنید."), main, jobSlot);
  render();
  return view;
}
