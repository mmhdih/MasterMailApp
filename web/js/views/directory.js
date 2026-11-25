// Seller directory: every email ever found (crawl, file, manual) — the crawl cache.
import { h, mount, icon, button, input, pill, toast, confirmSheet, dropZone, upload, get, post, del, num, fa, ago, isEmail, openPath, sheet, emptyState, refreshState } from "../core.js";

const SRC = { crawl: ["کراول", "blue"], file: ["فایل", "indigo"], manual: ["دستی", "orange"], import: ["وارد شده", "purple"] };

export function directoryView(page) {
  const st = { q: "" };
  const tbody = h("tbody");
  const meta = h("div", { class: "row wrap" });
  let timer;

  async function load() {
    const data = await get(`/api/sellers?q=${encodeURIComponent(st.q)}&limit=500`);
    mount(meta, pill(`${num(data.counts.total)} فروشنده`, "blue"), pill(`${num(data.counts.with_email)} دارای ایمیل`, "green"),
      st.q ? pill(`${num(data.total)} نتیجه`) : null);
    mount(tbody, data.sellers.length ? data.sellers.map(row)
      : h("tr", {}, h("td", { colspan: 6 }, emptyState("book", st.q ? "نتیجه‌ای پیدا نشد" : "دفترچه خالی است",
          st.q ? "عبارت دیگری را جستجو کنید." : "با هر کراول یا کمپین، ایمیل فروشنده‌ها اینجا ذخیره می‌شود تا دفعه بعد بدون کراول استفاده شود."))));
  }

  function row(s) {
    const [t, c] = SRC[s.source] || [s.source || "—", ""];
    return h("tr", {},
      h("td", { class: "mono" }, s.seller_id),
      h("td", {}, h("input", { class: "edit-inline", value: s.name || "", placeholder: "—", onChange: async (e) => { await post(`/api/sellers/${s.seller_id}`, { name: e.target.value }); toast("ذخیره شد", "ok", 1500); } })),
      h("td", { class: "cell-email" }, h("input", { class: ["edit-inline", s.email && !isEmail(s.email) && "invalid"], dir: "ltr", value: s.email || "", placeholder: "—",
        onChange: async (e) => { try { await post(`/api/sellers/${s.seller_id}`, { email: e.target.value }); e.target.classList.remove("invalid"); toast("ذخیره شد", "ok", 1500); } catch (err) { e.target.classList.add("invalid"); toast(err.message, "error"); } } })),
      h("td", {}, pill(t, c)),
      h("td", { class: "muted", style: { fontSize: "12px" } }, ago(s.updated_at)),
      h("td", {}, button("", { icon: "trash", kind: "sm plain", title: "حذف", onClick: async () => {
        if (await confirmSheet("حذف از دفترچه", `فروشنده ${s.seller_id} از دفترچه حذف شود؟`, { ok: "حذف", danger: true })) { await del(`/api/sellers/${s.seller_id}`); load(); refreshState(); }
      } })));
  }

  const importSheet = () => sheet({ title: "وارد کردن فهرست فروشنده‌ها", subtitle: "فایلی با ستون شناسه فروشنده و ایمیل (و در صورت وجود نام). ستون‌ها خودکار تشخیص داده می‌شوند.",
    body: dropZone({ title: "فایل اکسل یا CSV", hint: "رها کنید یا کلیک کنید", accept: ".xlsx,.xls,.csv", onFiles: async ([f]) => {
      const up = await upload(f);
      const r = await post("/api/sellers/import", { file_id: up.file_id });
      toast(`${fa(r.imported)} فروشنده وارد شد`, "ok");
      document.querySelector(".sheet-backdrop")?.remove();
      load(); refreshState();
    } }) });

  mount(page,
    h("div", { class: "row" }, h("h1", { class: "large-title" }, "دفترچه فروشندگان"), h("span", { class: "spacer" }),
      button("وارد کردن", { icon: "upload", onClick: importSheet, busy: false }),
      button("خروجی اکسل", { icon: "download", kind: "tinted", onClick: async () => { const r = await post("/api/sellers/export", {}); openPath(r.path, true); toast("فایل اکسل ساخته شد", "ok"); } })),
    h("p", { class: "page-sub" }, "حافظه برنامه از ایمیل فروشنده‌ها. کمپین‌ها اول اینجا را نگاه می‌کنند و فقط موارد ناموجود را کراول می‌کنند."),
    h("div", { class: "row", style: { marginBottom: "12px" } },
      h("div", { style: { position: "relative", width: "320px" } },
        input("", (v) => { st.q = v; clearTimeout(timer); timer = setTimeout(load, 250); }, { placeholder: "جستجو در شناسه، نام یا ایمیل", style: { paddingInlineStart: "34px" } }),
        h("span", { style: { position: "absolute", top: "9px", insetInlineStart: "10px", color: "var(--label-3)" } }, icon("search", 17))),
      h("span", { class: "spacer" }), meta),
    h("div", { class: "table-wrap", style: { maxHeight: "calc(100vh - 250px)" } }, h("table", { class: "t" },
      h("thead", {}, h("tr", {}, h("th", {}, "شناسه"), h("th", {}, "نام تجاری"), h("th", {}, "ایمیل"), h("th", {}, "منبع"), h("th", {}, "بروزرسانی"), h("th", { style: { width: "40px" } }, ""))),
      tbody)));
  load().catch((e) => toast(e.message, "error"));
}
