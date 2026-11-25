// "How should we crawl?" card: smart (use the address book) vs full (re-read everyone from the panel).
import { h, mount, icon, button, pill, num, fa } from "./core.js";

export function crawlChooser(plan, { onStart, title = "دریافت ایمیل از پنل" } = {}) {
  let mode = plan.smart > 0 ? "smart" : null;
  const root = h("div", { class: "card crawl-chooser" });

  const option = (value, name, desc, count, ic, color, disabled) => h("button", {
    type: "button", class: ["option-card", mode === value && "on"], disabled: disabled ? true : null,
    style: disabled ? { opacity: .5, cursor: "not-allowed" } : null,
    onClick: () => { if (!disabled) { mode = value; render(); } } },
  h("div", { class: "o-ico", style: { background: color } }, icon(ic, 19, 2)),
  h("div", { style: { flex: 1 } }, h("b", {}, name), h("small", {}, desc)),
  h("span", { class: "pill " + (value === "smart" ? "blue" : "") }, `${num(count)} فروشنده`),
  h("span", { class: "radio" }));

  function render() {
    const known = plan.fresh + (plan.provided || 0);
    const smartParts = [plan.new && "جدیدها", plan.no_email && "بدون ایمیل‌ها", plan.stale && "قدیمی‌ها"].filter(Boolean);
    const smartDesc = plan.smart
      ? `فقط ${smartParts.join("، ")} از پنل خوانده می‌شوند؛ ${known ? `${num(known)} فروشنده دیگر از دفترچه آدرس${plan.provided ? " یا فایل" : ""} پر می‌شوند.` : "بقیه از دفترچه آدرس پر می‌شوند."}`
      : "ایمیل همه فروشنده‌ها از قبل در دفترچه آدرس هست؛ چیزی برای کراول نمانده.";
    const count = mode === "full" ? plan.full : mode === "smart" ? plan.smart : 0;
    mount(root,
      h("div", { class: "card-title" }, icon("globe", 18, 2.2), title),
      h("div", { class: "row wrap", style: { margin: "6px 0 14px" } },
        plan.fresh ? pill(`${num(plan.fresh)} در دفترچه آدرس`, "green", true) : null,
        plan.provided ? pill(`${num(plan.provided)} از فایل یا ورود دستی`, "indigo", true) : null,
        plan.stale ? pill(`${num(plan.stale)} قدیمی‌تر از ${fa(plan.cache_days)} روز`, "orange", true) : null,
        plan.no_email ? pill(`${num(plan.no_email)} بدون ایمیل در کراول قبلی`, "orange", true) : null,
        plan.new ? pill(`${num(plan.new)} جدید`, "blue", true) : null),
      h("div", { class: "col" },
        option("smart", "کراول هوشمند", smartDesc, plan.smart, "sparkles", "linear-gradient(160deg,#5AC8FA,#007AFF)", !plan.smart),
        option("full", "کراول کامل از نو", "ایمیل و نام همه فروشنده‌ها دوباره از پنل خوانده و در دفترچه آدرس به‌روز می‌شود. کندتر است؛ وقتی لازم است که فکر می‌کنید اطلاعات پنل تغییر کرده.",
          plan.full, "refresh", "linear-gradient(160deg,#FFB340,#FF9500)", !plan.full)),
      h("div", { class: "row", style: { marginTop: "14px" } }, h("span", { class: "spacer" }),
        button(!mode ? "یک روش را انتخاب کنید" : mode === "smart" ? `شروع کراول هوشمند (${num(count)} فروشنده)` : `شروع کراول کامل (${num(count)} فروشنده)`,
          { kind: "primary", icon: "bolt", disabled: !count, onClick: () => onStart(mode) })));
  }
  render();
  return root;
}
