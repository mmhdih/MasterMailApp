// Standalone crawler: ids (pasted or from a file) → email + business name → Excel.
import { h, mount, icon, button, toggle, segmented, groupRow, pill, toast, dropZone, fileIcon, upload, post, get, num, fa, openPath, store } from "../core.js";
import { jobCard, isFinished } from "../jobs.js";

const STATUS = { ok: ["کامل", "green"], partial: ["ناقص", "orange"], "not-found": ["پیدا نشد", "red"], error: ["خطا", "red"], cached: ["از دفترچه", "purple"] };

export function crawlerView(page) {
  const st = { mode: "ids", text: "", file: null, refresh: false };
  const input = h("div");
  const jobSlot = h("div");
  const tbody = h("tbody");
  const results = h("div", { class: "hidden" }, h("div", { class: "group-label" }, "نتایج"),
    h("div", { class: "table-wrap" }, h("table", { class: "t" },
      h("thead", {}, h("tr", {}, h("th", {}, "شناسه"), h("th", {}, "نام تجاری"), h("th", {}, "ایمیل"), h("th", {}, "وضعیت"))), tbody)));
  const cacheDays = store.state.settings.crawler.cache_days;

  const renderInput = () => mount(input, st.mode === "ids"
    ? h("textarea", { class: "textarea ltr", dir: "ltr", rows: 8, style: { fontFamily: "var(--mono)", minHeight: "200px" },
        placeholder: "1234567\n2345678\n…", onInput: (e) => (st.text = e.target.value) }, st.text)
    : st.file ? h("div", { class: "file-card" }, fileIcon(st.file.name), h("b", { style: { flex: 1 } }, st.file.name),
        st.file.info ? pill(`${num(st.file.info.id_groups)} شناسه در ستون «${st.file.info.detected.id || "?"}»`, st.file.info.detected.id ? "blue" : "red") : null,
        button("تغییر", { kind: "sm", onClick: () => { st.file = null; renderInput(); }, busy: false }))
      : dropZone({ title: "فایلی که ستون شناسه فروشنده دارد", hint: "xlsx، xls یا csv", accept: ".xlsx,.xls,.xlsm,.csv", onFiles: async ([f]) => {
          const up = await upload(f); st.file = { ...up, name: f.name };
          st.file.info = await post("/api/file/inspect", { file_id: up.file_id }); renderInput();
        } }));

  const run = async () => {
    const payload = st.mode === "ids" ? { text: st.text, refresh: st.refresh } : { file_id: st.file?.file_id, refresh: st.refresh };
    if (st.mode === "file" && !st.file) throw new Error("ابتدا فایل را انتخاب کنید.");
    const job = await post("/api/crawl", payload);
    attach(job);
  };
  function attach(job) {
    mount(tbody); results.classList.remove("hidden");
    const card = jobCard(job, {
      onItem: (e) => {
        const [t, c] = STATUS[e.status] || [e.status, ""];
        tbody.appendChild(h("tr", {}, h("td", { class: "mono" }, e.seller_id), h("td", {}, e.name || "—"),
          h("td", { class: "cell-email" }, e.email || h("span", { class: "faint" }, "—")), h("td", {}, pill(t, c))));
      },
      onDone: (j) => {
        if (j.result?.rows) mount(tbody, j.result.rows.map((e) => {
          const [t, c] = STATUS[e.status] || [e.status, ""];
          return h("tr", {}, h("td", { class: "mono" }, e.seller_id), h("td", {}, e.name || "—"),
            h("td", { class: "cell-email" }, e.email || h("span", { class: "faint" }, "—")), h("td", {}, pill(t, c)));
        }));
        if (j.result?.export) {
          mount(jobSlot.querySelector(".after") || jobSlot.appendChild(h("div", { class: "after" })),
            h("div", { class: "banner green", style: { marginTop: "14px" } }, h("div", { class: "b-ico" }, icon("check", 18, 2.4)),
              h("div", { class: "txt" }, h("b", {}, `ایمیل ${num((j.result.ok || 0) + (j.result.partial || 0) + (j.result.cached || 0))} فروشنده آماده است`),
                h("small", {}, "نتایج در دفترچه فروشندگان هم ذخیره شد و در کمپین‌ها خودکار استفاده می‌شود.")),
              button("باز کردن اکسل", { kind: "primary", icon: "table", onClick: () => openPath(j.result.export) }),
              button("نمایش در پوشه", { icon: "folder", onClick: () => openPath(j.result.export, true) })));
        }
      },
    });
    view.offs.push(card.destroy);
    mount(jobSlot, card);
  }

  mount(page,
    h("h1", { class: "large-title" }, "کراولر ایمیل"),
    h("p", { class: "page-sub" }, "ایمیل و نام تجاری فروشنده‌ها را از پنل ادمین بگیرید و خروجی اکسل تحویل بگیرید."),
    h("div", { class: "card" },
      h("div", { class: "row", style: { marginBottom: "14px" } },
        segmented([{ value: "ids", label: "چسباندن شناسه‌ها", icon: "list" }, { value: "file", label: "از فایل", icon: "table" }], st.mode, (v) => { st.mode = v; renderInput(); })),
      input,
      h("div", { class: "group", style: { marginTop: "16px", boxShadow: "none", background: "var(--fill-2)" } },
        groupRow("کراول دوباره همه، حتی آن‌هایی که در دفترچه هستند", toggle(false, (v) => (st.refresh = v)),
          { sub: `در حالت عادی، فروشنده‌هایی که در ${fa(cacheDays)} روز اخیر پیدا شده‌اند دوباره کراول نمی‌شوند.` })),
      h("div", { class: "row", style: { marginTop: "16px" } }, h("span", { class: "spacer" }),
        button("شروع کراول", { kind: "primary", icon: "bolt", onClick: run }))),
    h("div", { style: { marginTop: "18px" } }, jobSlot), results);
  renderInput();
  const view = { offs: [], destroy: () => view.offs.forEach((f) => f()) };
  get("/api/jobs").then((jobs) => { const j = jobs.find((x) => x.kind === "crawl" && !x.meta?.campaign && !isFinished(x)); if (j) attach(j); });
  return view;
}
