import { h, mount, icon, button, num, ago, get, post, store, toast, fa } from "../core.js";

export function campaignStatus(c) {
  const map = { draft: ["پیش‌نویس", ""], sending: ["در حال ارسال", "blue"], sent: ["ارسال شد", "green"],
    partial: ["ارسال ناقص", "orange"], stopped: ["متوقف شد", "orange"] };
  const [t, color] = map[c.status] || [c.status, ""];
  return h("span", { class: ["pill", color] }, t);
}

export function campaignRow(c) {
  const st = c.stats || {};
  return h("div", { class: "list-item-campaign", onClick: () => window.mmGo(`#/campaign/${c.id}`) },
    h("div", { class: "camp-ico", style: c.status === "sent" ? { background: "linear-gradient(160deg,#5BD777,#28A745)" } : null },
      icon(c.status === "sent" ? "check" : "send", 19, 2)),
    h("div", { style: { flex: 1, minWidth: 0 } },
      h("div", { style: { fontWeight: 600 } }, c.name),
      h("small", { class: "muted num" }, `${num(st.total || 0)} گیرنده`,
        st.sent ? ` · ${num(st.sent)} ارسال‌شده` : "", st.failed ? ` · ${num(st.failed)} ناموفق` : "", " · ", ago(c.updated_at))),
    campaignStatus(c), h("span", { class: "chev" }, icon("chevron", 16)));
}

export async function newCampaign() {
  const c = await post("/api/campaigns", {});
  window.mmGo(`#/campaign/${c.id}`);
}

export function homeView(page) {
  const s = store.state;
  const stats = s.stats;
  const derived = s.settings.derived;
  const hour = new Date().getHours();
  const greet = hour < 12 ? "صبح بخیر" : hour < 17 ? "روز بخیر" : "عصر بخیر";
  const recent = h("div");
  const setupNeeded = !derived.has_smtp_password;

  mount(page,
    h("h1", { class: "large-title" }, greet),
    h("p", { class: "page-sub" }, "از شناسه فروشنده تا ایمیل ارسال‌شده — همه در یک مسیر."),

    h("section", { class: "hero" },
      h("img", { class: "hero-art", src: "img/icon.svg", alt: "" }),
      h("h2", {}, "کمپین ایمیل جدید"),
      h("p", {}, "فقط شناسه‌ها یا فایل گزارش را بدهید؛ مستر میل ایمیل فروشنده‌ها را از پنل می‌گیرد، فایل هر فروشنده را جدا می‌کند، متن را آماده می‌کند و برای همه می‌فرستد."),
      h("div", { class: "flow" },
        h("span", {}, icon("list", 14, 2.2), "شناسه یا فایل"), h("i", {}, "←"),
        h("span", {}, icon("globe", 14, 2.2), "کراول ایمیل"), h("i", {}, "←"),
        h("span", {}, icon("scissors", 14, 2.2), "جداسازی پیوست"), h("i", {}, "←"),
        h("span", {}, icon("wand", 14, 2.2), "متن ایمیل"), h("i", {}, "←"),
        h("span", {}, icon("send", 14, 2.2), "ارسال")),
      h("div", { class: "row" },
        button("شروع کمپین جدید", { kind: "lg", icon: "plus", onClick: newCampaign }),
        button("کمپین‌های قبلی", { kind: "lg ghost", onClick: () => window.mmGo("#/campaigns"), busy: false }))),

    setupNeeded ? h("div", { class: "banner blue", style: { marginBottom: "18px" } },
      h("div", { class: "b-ico" }, icon("mail", 18, 2)),
      h("div", { class: "txt" }, h("b", {}, "حساب ایمیل را یک بار تنظیم کنید"),
        h("small", {}, "سرور، نام کاربری و رمز عبور ایمیل سازمانی را وارد کنید تا ارسال آماده شود. رمز در Credential Manager ویندوز امن نگه داشته می‌شود.")),
      button("تنظیم حساب", { kind: "primary", onClick: () => window.mmGo("#/settings"), busy: false })) : null,

    h("div", { class: "grid-4" },
      stat("ایمیل ارسال‌شده", stats.emails_sent, "send", "var(--accent)"),
      stat("کمپین‌ها", stats.campaigns, "sparkles", "var(--purple)"),
      stat("فروشنده در دفترچه", stats.sellers, "book", "var(--orange)"),
      stat("دارای ایمیل", stats.sellers_with_email, "check", "var(--green)")),

    h("div", { class: "section-head" }, h("h3", {}, "ابزارهای سریع")),
    h("div", { class: "grid-3" },
      tile("کراولر ایمیل", "فهرست شناسه‌ها را بدهید و ایمیل و نام تجاری فروشنده‌ها را در قالب اکسل بگیرید.", "globe", "linear-gradient(160deg,#5AC8FA,#007AFF)", "#/crawler"),
      tile("جداساز اکسل", "یک فایل را بر اساس هر ستونی به فایل‌های جدا یا شیت‌های جدا تقسیم کنید.", "scissors", "linear-gradient(160deg,#FFB340,#FF9500)", "#/splitter"),
      tile("دفترچه فروشندگان", "ایمیل‌هایی که قبلاً پیدا شده‌اند اینجا ذخیره‌اند؛ کراول تکراری لازم نیست.", "book", "linear-gradient(160deg,#C77DFF,#AF52DE)", "#/directory")),

    h("div", { class: "section-head" }, h("h3", {}, "کمپین‌های اخیر"), h("span", { class: "spacer" }),
      button("همه", { kind: "plain", onClick: () => window.mmGo("#/campaigns"), busy: false })),
    recent);

  get("/api/campaigns").then((list) => {
    mount(recent, list.length
      ? h("div", { class: "group" }, list.slice(0, 5).map(campaignRow))
      : h("div", { class: "group" }, h("div", { class: "empty", style: { padding: "34px" } },
          h("b", {}, "هنوز کمپینی نساخته‌اید"), "اولین کمپین را از کارت بالا شروع کنید.")));
  }).catch((e) => toast(e.message, "error"));
}

function stat(label, value, ic, color) {
  return h("div", { class: "stat" }, h("div", { class: "k" }, h("span", { style: { color } }, icon(ic, 15, 2.2)), label),
    h("div", { class: "v num" }, num(value || 0)));
}

function tile(title, text, ic, bg, href) {
  return h("button", { class: "tile", onClick: () => window.mmGo(href) },
    h("div", { class: "tile-ico", style: { background: bg } }, icon(ic, 22, 2)), h("b", {}, title), h("p", {}, text));
}
