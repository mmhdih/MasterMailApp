// Settings: mail account, sending, crawler, AI, appearance, about.
import { h, mount, icon, button, toggle, segmented, select, groupRow, toast, post, store, refreshState, applyTheme, fa, openPath } from "../core.js";

export function settingsView(page) {
  const s = store.state.settings;
  const d = s.derived;
  const pending = {};
  const secrets = {};
  const setPath = (path, value) => {
    const [a, b] = path.split(".");
    pending[a] = pending[a] || {}; pending[a][b] = value;
    saveSoon();
  };
  let timer;
  const saveSoon = () => { clearTimeout(timer); timer = setTimeout(save, 600); };
  async function save(silent) {
    const body = { ...pending };
    if (Object.keys(secrets).length) body.secrets = { ...secrets };
    if (!Object.keys(body).length) return;
    Object.keys(pending).forEach((k) => delete pending[k]);
    Object.keys(secrets).forEach((k) => delete secrets[k]);
    const r = await post("/api/settings", body);
    store.state.settings = r;
    if (!silent) toast("ذخیره شد", "ok", 1400);
    if (body.secrets && r.stored_in_keyring && Object.values(r.stored_in_keyring).some((x) => !x))
      toast("رمز فقط برای همین اجرا نگه داشته شد (Credential Manager در دسترس نبود).", "warn", 6000);
  }

  const text = (path, value, opts = {}) => h("input", { class: ["input bare", opts.ltr && "ltr"], dir: opts.ltr ? "ltr" : null, type: opts.type || "text",
    value: value ?? "", placeholder: opts.placeholder || "", style: { width: opts.width || "260px" },
    onInput: (e) => setPath(path, opts.type === "number" ? +e.target.value : e.target.value) });
  const sw = (path, value) => toggle(value, (v) => setPath(path, v));
  const secret = (kind, has, placeholder) => h("input", { class: "input bare ltr", dir: "ltr", type: "password", style: { width: "260px" },
    placeholder: has ? "•••••••• (ذخیره شده)" : placeholder, autocomplete: "new-password",
    onInput: (e) => { secrets[kind] = e.target.value; saveSoon(); } });

  mount(page,
    h("h1", { class: "large-title" }, "تنظیمات"),
    h("p", { class: "page-sub" }, "تغییرات خودکار ذخیره می‌شوند."),

    h("div", { class: "group-label" }, "حساب ایمیل"),
    h("div", { class: "group" },
      groupRow("سرور SMTP", text("smtp.host", s.smtp.host, { ltr: true }), { icon: "mail", color: "var(--accent)" }),
      groupRow("پورت", text("smtp.port", s.smtp.port, { type: "number", width: "90px", ltr: true }), { icon: "link", color: "var(--teal)" }),
      groupRow("امنیت اتصال", segmented([{ value: "starttls", label: "STARTTLS" }, { value: "ssl", label: "SSL" }, { value: "none", label: "هیچ" }], s.smtp.security, (v) => setPath("smtp.security", v)), { icon: "shield", color: "var(--green)" }),
      groupRow("نام کاربری", text("smtp.username", s.smtp.username, { ltr: true, placeholder: d.smtp_username || "user یا DOMAIN\\user" }),
        { icon: "person", color: "var(--indigo)", sub: s.smtp.use_system_username ? `خالی بماند ← نام کاربری ویندوز (${d.smtp_username || "—"}) استفاده می‌شود` : "" }),
      groupRow("رمز عبور", secret("smtp_password", d.has_smtp_password, "رمز ایمیل"), { icon: "key", color: "var(--orange)",
        sub: d.keyring ? "در Credential Manager ویندوز ذخیره می‌شود؛ هیچ‌وقت در فایل نوشته نمی‌شود." : "Credential Manager در دسترس نیست؛ رمز فقط تا بستن برنامه نگه داشته می‌شود." }),
      groupRow("نام فرستنده", text("smtp.from_name", s.smtp.from_name, { placeholder: "مثلاً: تیم پشتیبانی فروشندگان" }), { icon: "people", color: "var(--purple)" }),
      groupRow("آدرس فرستنده", text("smtp.from_email", s.smtp.from_email, { ltr: true, placeholder: d.from_address }), { icon: "send", color: "var(--pink)", sub: "خالی بماند تا از نام کاربری ساخته شود." }),
      groupRow("پاسخ به (Reply-To)", text("smtp.reply_to", s.smtp.reply_to, { ltr: true, placeholder: "اختیاری" }), { icon: "back", color: "var(--teal)" }),
      groupRow("استفاده از نام کاربری ویندوز", sw("smtp.use_system_username", s.smtp.use_system_username), { icon: "person", color: "var(--label-2)" })),
    h("div", { class: "row", style: { margin: "10px 16px 0" } }, h("span", { class: "spacer" }),
      button("تست اتصال", { kind: "tinted", icon: "bolt", onClick: async () => { await save(true); const t = await post("/api/smtp/test"); toast(`اتصال برقرار است — ${t.from} (${fa(t.ms)} ms)`, "ok"); refreshState(); } })),

    h("div", { class: "group-label" }, "ارسال"),
    h("div", { class: "group" },
      groupRow("فاصله پیش‌فرض بین ایمیل‌ها (ثانیه)", text("sending.delay", s.sending.delay, { type: "number", width: "90px", ltr: true })),
      groupRow("استراحت پس از هر چند ایمیل", text("sending.pause_every", s.sending.pause_every, { type: "number", width: "90px", ltr: true }), { sub: "برای جلوگیری از محدودیت سرور؛ صفر یعنی بدون استراحت." }),
      groupRow("مدت استراحت (ثانیه)", text("sending.pause_seconds", s.sending.pause_seconds, { type: "number", width: "90px", ltr: true })),
      groupRow("ایمیل با قالب‌بندی زیبا (HTML)", sw("sending.html", s.sending.html), { sub: "نسخه متنی ساده هم همیشه همراه ایمیل ارسال می‌شود." }),
      groupRow("یک نسخه مخفی (BCC) برای خودم", sw("sending.bcc_self", s.sending.bcc_self)),
      groupRow("امضا", h("textarea", { class: "textarea", rows: 3, style: { width: "320px", minHeight: "76px" }, placeholder: "نام شما\nسمت\nشماره تماس",
        onInput: (e) => setPath("sending.signature", e.target.value) }, s.sending.signature || ""), { sub: "زیر همه ایمیل‌ها اضافه می‌شود." })),

    h("div", { class: "group-label" }, "کراولر پنل"),
    h("div", { class: "group" },
      groupRow("آدرس صفحه فروشنده", text("crawler.base_url", s.crawler.base_url, { ltr: true, width: "440px" }), { sub: "به‌جای شناسه، {id} بنویسید." }),
      groupRow("سلکتور ایمیل", text("crawler.email_selector", s.crawler.email_selector, { ltr: true })),
      groupRow("سلکتور نام تجاری", text("crawler.name_selector", s.crawler.name_selector, { ltr: true })),
      groupRow("فاصله بین صفحه‌ها (ثانیه)", text("crawler.delay", s.crawler.delay, { type: "number", width: "90px", ltr: true })),
      groupRow("اعتبار دفترچه آدرس (روز)", text("crawler.cache_days", s.crawler.cache_days, { type: "number", width: "90px", ltr: true }), { sub: "در کراول هوشمند، ایمیل‌های قدیمی‌تر از این دوباره از پنل خوانده می‌شوند. صفر یعنی همیشه معتبر." }),
      groupRow("تلاش مجدد برای هر فروشنده", text("crawler.retries", s.crawler.retries, { type: "number", width: "90px", ltr: true })),
      groupRow("ذخیره نشست کروم (بدون ورود دوباره)", sw("crawler.keep_profile", s.crawler.keep_profile)),
      groupRow("اجرای مخفی مرورگر (Headless)", sw("crawler.headless", s.crawler.headless), { sub: "فقط وقتی نشست ذخیره‌شده معتبر است؛ برای ورود اول خاموش باشد." }),
      groupRow("مسیر Chrome", text("crawler.chrome_binary", s.crawler.chrome_binary, { ltr: true, placeholder: "خودکار" })),
      groupRow("مسیر chromedriver", text("crawler.chromedriver_path", s.crawler.chromedriver_path, { ltr: true, placeholder: "خودکار (Selenium Manager)" }))),

    h("div", { class: "group-label" }, "هوش مصنوعی"),
    h("div", { class: "group" },
      groupRow("کلید API Claude", secret("anthropic_api_key", d.has_ai_key, "sk-ant-…"), { icon: "sparkles", color: "var(--purple)",
        sub: "اختیاری. بدون کلید، نویسنده هوشمند آفلاین پیش‌نویس می‌سازد. کلید در Credential Manager ذخیره می‌شود." }),
      groupRow("مدل", select([{ value: "claude-opus-5-5", label: "Claude Opus 5.5" }, { value: "claude-sonnet-5-5", label: "Claude Sonnet 5.5" }, { value: "claude-haiku-5-5", label: "Claude Haiku 5.5" }],
        s.ai.model, (v) => setPath("ai.model", v), { bare: true }), { icon: "bolt", color: "var(--indigo)" })),

    h("div", { class: "group-label" }, "ظاهر و فایل‌ها"),
    h("div", { class: "group" },
      groupRow("پوسته", segmented([{ value: "system", label: "خودکار" }, { value: "light", label: "روشن" }, { value: "dark", label: "تیره" }], s.appearance.theme,
        (v) => { applyTheme(v); setPath("appearance.theme", v); }), { icon: "moon", color: "#5E5CE6" }),
      groupRow("محل ذخیره خروجی‌ها", text("workspace_dir", s.workspace_dir, { ltr: true, width: "360px", placeholder: d.workspace }), { icon: "folder", color: "var(--teal)" }),
      groupRow("باز کردن پوشه خروجی‌ها", null, { icon: "folder", color: "var(--accent)", onClick: () => openPath(d.workspace) })),

    h("div", { class: "group-label" }, "درباره"),
    h("div", { class: "group" },
      h("div", { class: "group-row", style: { padding: "18px 16px" } },
        h("img", { src: "img/icon.svg", style: { width: "56px", height: "56px" } }),
        h("div", { class: "label" }, h("b", { style: { fontSize: "16px" } }, "مستر میل"),
          h("small", {}, `نسخه ${fa(store.state.app.version)} — ${store.state.app.tagline}`),
          h("small", {}, store.state.app.powered_by)))));
  return { destroy: () => { clearTimeout(timer); save(true).catch(() => {}); } };
}
