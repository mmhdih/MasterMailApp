// Shell: sidebar navigation, router, toolbar, activity popover.
import { h, mount, icon, on, get, store, refreshState, applyTheme, fa, num, toast, button, pct, progressBar } from "./core.js";
import { STATE_LABEL } from "./jobs.js";
import { homeView } from "./views/home.js";
import { campaignView, campaignsView } from "./views/campaign.js";
import { crawlerView } from "./views/crawler.js";
import { splitterView } from "./views/splitter.js";
import { directoryView } from "./views/directory.js";
import { settingsView } from "./views/settings.js";

const NAV = [
  { section: null, items: [
    { id: "home", label: "خانه", icon: "home" },
    { id: "campaigns", label: "کمپین‌ها", icon: "send", badge: () => store.state?.stats?.campaigns },
  ] },
  { section: "ابزارها", items: [
    { id: "crawler", label: "کراولر ایمیل", icon: "globe" },
    { id: "splitter", label: "جداساز اکسل", icon: "scissors" },
    { id: "directory", label: "دفترچه آدرس", icon: "book", badge: () => store.state?.stats?.sellers },
  ] },
  { section: null, items: [{ id: "settings", label: "تنظیمات", icon: "gear" }] },
];

const VIEWS = { home: homeView, campaigns: campaignsView, campaign: campaignView, crawler: crawlerView,
  splitter: splitterView, directory: directoryView, settings: settingsView };

const sidebar = h("nav", { class: "sidebar" });
const toolbarTitle = h("div", { class: "title-sm" });
const activityBtn = h("button", { class: "btn icon activity-btn", title: "فعالیت‌ها", onClick: () => togglePopover() });
const toolbar = h("header", { class: "toolbar" }, toolbarTitle, h("div", { class: "spacer" }), activityBtn);
const content = h("main", { class: "content" });
document.getElementById("app").replaceChildren(
  h("div", { class: "app" }, sidebar, h("div", { class: "main" }, toolbar, content)));
content.addEventListener("scroll", () => toolbar.classList.toggle("scrolled", content.scrollTop > 30));

let current = null;
function route() {
  if (!store.state) return;
  const [, name = "home", arg] = location.hash.replace(/^#/, "").split("/");
  const view = VIEWS[name] || homeView;
  if (current && current.destroy) current.destroy();
  content.scrollTop = 0;
  const page = h("div", { class: "page" });
  mount(content, page);
  current = view(page, arg) || null;
  toolbarTitle.textContent = page.querySelector(".large-title")?.textContent || "";
  renderSidebar(name === "campaign" ? "campaigns" : name);
}
window.addEventListener("hashchange", route);
export const go = (hash) => { if (location.hash === hash) route(); else location.hash = hash; };
window.mmGo = go;

function renderSidebar(active) {
  const s = store.state;
  const smtpOk = s?.settings?.derived?.has_smtp_password;
  mount(sidebar,
    h("div", { class: "brand" }, h("img", { src: "img/icon.svg", alt: "" }),
      h("div", {}, h("b", {}, "مستر میل"), h("span", {}, "MasterMail"))),
    NAV.map((group) => [
      group.section ? h("div", { class: "nav-section" }, group.section) : h("div", { style: { height: "8px" } }),
      group.items.map((item) => {
        const badge = item.badge ? item.badge() : null;
        return h("button", { class: ["nav-item", active === item.id && "active"], onClick: () => go("#/" + item.id) },
          h("span", { class: "ico" }, icon(item.icon, 18, 2)), h("span", { class: "t" }, item.label),
          badge ? h("span", { class: "badge num" }, num(badge)) : null);
      }),
    ]),
    h("div", { class: "sidebar-foot" },
      h("div", { class: "account-chip", onClick: () => go("#/settings"), title: "حساب ایمیل" },
        h("i", { class: ["dot", smtpOk ? "ok" : "warn"] }),
        h("span", { class: "ltr", style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } },
          s?.settings?.derived?.from_address || "حساب ایمیل تنظیم نشده")),
      h("div", {}, `نسخه ${fa(s?.app?.version || "")} · ${s?.app?.powered_by || ""}`)));
}

// --------------------------------------------------------------- activity popover
let popover = null;
const liveJobs = new Map();
function renderActivityBtn() {
  const running = [...liveJobs.values()].filter((j) => !["done", "failed", "stopped"].includes(j.state)).length;
  mount(activityBtn, icon(running ? "refresh" : "list", 17), running ? h("span", { class: "count" }, fa(running)) : null);
  activityBtn.style.animation = "";
}
function togglePopover() {
  if (popover) { popover.remove(); popover = null; return; }
  popover = h("div", { class: "popover" });
  renderPopover();
  document.body.appendChild(popover);
  setTimeout(() => document.addEventListener("mousedown", closePop), 0);
}
function closePop(e) {
  if (popover && !popover.contains(e.target) && !activityBtn.contains(e.target)) {
    popover.remove(); popover = null; document.removeEventListener("mousedown", closePop);
  }
}
function renderPopover() {
  if (!popover) return;
  const jobs = [...liveJobs.values()].sort((a, b) => b.started_at - a.started_at).slice(0, 12);
  mount(popover, h("div", { style: { padding: "6px 12px 8px", fontWeight: 700 } }, "فعالیت‌ها"),
    jobs.length ? jobs.map((j) => {
      const [label, color] = STATE_LABEL[j.state] || [j.state, ""];
      return h("div", { class: "pop-item" },
        h("div", { class: "row" }, h("b", { style: { fontSize: "13px" } }, fa(j.title)), h("span", { class: "spacer" }),
          h("span", { class: ["pill", color] }, label)),
        !["done", "failed", "stopped"].includes(j.state) ? progressBar(j.done, j.total, { indeterminate: !j.total }) : null,
        h("small", { class: "muted num" }, j.total ? `${num(j.done)} از ${num(j.total)}` : "", j.error ? " — " + j.error : ""));
    }) : h("div", { class: "muted", style: { padding: "12px" } }, "فعالیتی در جریان نیست."));
}
on("job", (j) => {
  const prev = liveJobs.get(j.id);
  if (prev && (j.version ?? 0) < (prev.version ?? 0)) return;
  liveJobs.set(j.id, j);
  renderActivityBtn();
  renderPopover();
  if (prev && !["done", "failed", "stopped"].includes(prev.state)) {
    if (j.state === "done") { toast(`«${fa(j.title)}» تمام شد`, "ok"); refreshState().then(() => renderSidebar(currentNav())); }
    if (j.state === "failed") toast(j.error || "عملیات ناموفق بود", "error", 6000);
  }
  if (j.action && j.action.type === "login" && (!prev || !prev.action)) toast("برای ادامه، در پنجره کروم وارد پنل شوید.", "warn", 6000);
});
const currentNav = () => { const n = location.hash.replace(/^#\//, "").split("/")[0] || "home"; return n === "campaign" ? "campaigns" : n; };
on("settings", (s) => { if (store.state) store.state.settings = s; renderSidebar(currentNav()); });

// --------------------------------------------------------------- boot
(async () => {
  try {
    const state = await refreshState();
    applyTheme(state.settings.appearance.theme);
    (state.jobs || []).forEach((j) => liveJobs.set(j.id, j));
    renderActivityBtn();
    route();
    if (!state.settings.onboarded && !location.hash) {
      // first launch → home shows the setup card
    }
  } catch (e) {
    mount(content, h("div", { class: "page" }, h("div", { class: "empty" }, h("b", {}, "اتصال به برنامه برقرار نشد"), e.message)));
  }
})();
