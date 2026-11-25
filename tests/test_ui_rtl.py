"""Drive the real UI in Chromium and check Persian / right-to-left behaviour on every screen.

Needs the Python `playwright` package and a Chromium build (`python -m playwright install chromium`);
skipped otherwise.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from openpyxl import Workbook  # noqa: E402

from fakes import FakeSMTP, Panel, stub_factory  # noqa: E402

ZWNJ = "‌"
WIDTHS = [1440, 1080]          # default window and the app's minimum window width
THEMES = ["light", "dark"]

# Latin words that are fine inside right-to-left text (product and protocol names).
ALLOWED_LATIN = {
    "MasterMail", "SMTP", "STARTTLS", "SSL", "CSV", "Excel", "Word", "Reply", "To", "BCC", "HTML", "API",
    "Claude", "Opus", "Sonnet", "Haiku", "Chrome", "chromedriver", "Selenium", "Manager", "Headless",
    "Powered", "By", "HajMehdi", "xlsx", "xls", "csv", "PDF", "Dry", "Run", "Credential", "Windows",
    "Documents", "Splits", "seller", "id", "name", "email", "ms", "id}", "XLSX", "DOCX", "ANY",
}

AUDIT_JS = r"""
(allowed) => {
  const problems = [];
  const fa = /[؀-ۿ]/;
  const visible = (el) => {
    if (!el || !el.getClientRects().length) return false;
    const s = getComputedStyle(el);
    return s.visibility !== "hidden" && s.display !== "none" && parseFloat(s.opacity || "1") > 0.05;
  };
  const html = document.documentElement;
  if (html.dir !== "rtl") problems.push("html dir is " + html.dir);
  if (html.lang !== "fa") problems.push("html lang is " + html.lang);
  if (getComputedStyle(document.body).direction !== "rtl") problems.push("body direction not rtl");
  if (!document.fonts.check("16px Vazirmatn", "سلام")) problems.push("Vazirmatn font not loaded");
  if (!/^"?Vazirmatn"?,/.test(getComputedStyle(document.body).fontFamily)) problems.push("body font is not Vazirmatn");

  // layout: sidebar on the right, nothing wider than the window
  const sb = document.querySelector(".sidebar").getBoundingClientRect();
  const main = document.querySelector(".main").getBoundingClientRect();
  if (sb.left < main.right - 1) problems.push("sidebar is not on the right");
  if (document.scrollingElement.scrollWidth > innerWidth + 1) problems.push("page scrolls horizontally");
  const content = document.querySelector(".content");
  if (content.scrollWidth > content.clientWidth + 1) problems.push(`content overflows horizontally by ${content.scrollWidth - content.clientWidth}px`);
  for (const el of document.querySelectorAll(".page *")) {
    if (!visible(el) || el.closest(".table-wrap, .log, textarea, .mail-body")) continue;
    const r = el.getBoundingClientRect();
    if (r.width && (r.left < main.left - 2 || r.right > main.right + 2))
      problems.push(`element sticks out of the window: <${el.tagName.toLowerCase()} class="${el.className}">`);
  }

  // large title starts at the right edge of the page
  const title = document.querySelector(".page .large-title");
  if (title && visible(title) && title.tagName !== "INPUT") {
    const range = document.createRange(); range.selectNodeContents(title);
    const tr = range.getBoundingClientRect(), pr = title.parentElement.getBoundingClientRect();
    if (Math.abs(tr.right - pr.right) > 4) problems.push(`title not right aligned (${Math.round(pr.right - tr.right)}px gap)`);
  }

  // text: Latin words only inside left-to-right elements, no mojibake
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = n.nodeValue.trim();
    const el = n.parentElement;
    if (!text || !el || el.closest("script,style,svg") || !visible(el)) continue;
    if (/[�]|Ã.|Ø[§¨ª]|Ù[…‡ˆ]/.test(text)) problems.push("broken characters: " + text.slice(0, 40));
    if (getComputedStyle(el).direction === "ltr") continue;
    const words = (text.match(/[A-Za-z][A-Za-z.@_\-]*/g) || []).map((w) => w.replace(/[.\-]+$/, ""));
    const bad = words.filter((w) => w && !allowed.includes(w) && !/@|\./.test(w));
    if (bad.length && !fa.test(text)) problems.push(`English text in RTL context: "${text.slice(0, 50)}"`);
    if (/@/.test(text) && !fa.test(text)) problems.push(`email shown in RTL context: "${text.slice(0, 50)}"`);
  }

  // counters and badges use Persian digits
  for (const el of document.querySelectorAll(".stat .v, .nav-item .badge, .pill, .step .n, .ring b, .activity-btn .count")) {
    if (visible(el) && /[0-9]/.test(el.textContent) && !el.closest('[dir="ltr"], .ltr'))
      problems.push(`Latin digits in counter: "${el.textContent.trim()}"`);
  }

  // form fields: Persian fields are RTL, email/code fields are LTR
  for (const f of document.querySelectorAll("input:not([type=checkbox]):not([type=file]), textarea, select")) {
    if (!visible(f)) continue;
    const dir = getComputedStyle(f).direction;
    const wantsLtr = f.getAttribute("dir") === "ltr" || f.classList.contains("ltr");
    if (wantsLtr && dir !== "ltr") problems.push("LTR field rendered RTL: " + (f.placeholder || f.value).slice(0, 30));
    if (!wantsLtr && dir !== "rtl") problems.push("Persian field rendered LTR: " + (f.placeholder || f.value).slice(0, 30));
    const v = f.value || f.placeholder || "";
    if (!wantsLtr && /^[^؀-ۿ]*@[^؀-ۿ]*$/.test(v.trim()) && v.trim()) problems.push("email field is not LTR: " + v);
  }

  // tables: first column on the right
  for (const tr of document.querySelectorAll("table.t thead tr")) {
    const cells = [...tr.children].filter(visible);
    if (cells.length > 1 && cells[0].getBoundingClientRect().left < cells[cells.length - 1].getBoundingClientRect().left)
      problems.push("table columns are not right-to-left");
  }
  // stepper: step 1 on the right
  const steps = [...document.querySelectorAll(".stepper .step")];
  if (steps.length > 1 && steps[0].getBoundingClientRect().left < steps[1].getBoundingClientRect().left)
    problems.push("wizard steps are not right-to-left");

  // arrows: forward points left, back points right
  for (const svg of document.querySelectorAll('svg[data-icon="chevron"], svg[data-icon="back"]')) {
    if (!visible(svg)) continue;
    const m = new DOMMatrix(getComputedStyle(svg).transform === "none" ? undefined : getComputedStyle(svg).transform);
    const drawnRight = svg.dataset.icon === "chevron";            // as drawn in the path data
    const pointsRight = m.a < 0 ? !drawnRight : drawnRight;
    if (svg.dataset.icon === "chevron" && pointsRight) problems.push("forward arrow points right");
    if (svg.dataset.icon === "back" && !pointsRight) problems.push("back arrow points left");
  }
  // forward buttons keep the arrow at the end (left) of the label
  for (const btn of document.querySelectorAll(".wizard-foot .btn.primary")) {
    const ic = btn.querySelector('svg[data-icon="chevron"]'), label = btn.querySelector("span");
    if (ic && label && ic.getBoundingClientRect().left > label.getBoundingClientRect().left)
      problems.push("forward arrow is before the label");
  }
  // switches: the knob of an ON switch sits on the left (iOS in RTL)
  for (const sw of document.querySelectorAll(".switch input:checked + span")) {
    if (!visible(sw)) continue;
    const t = getComputedStyle(sw, "::after").transform;
    if (!t || t === "none" || new DOMMatrix(t).e >= 0) problems.push("ON switch knob is not on the left");
  }
  return problems;
}
"""


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    base = tmp_path_factory.mktemp("ui")
    os.environ["MASTERMAIL_DATA"] = str(base / "data")
    os.environ["MASTERMAIL_WORKSPACE"] = str(base / "ws")
    from mastermail import paths
    paths.set_data_dir(None)
    import mastermail.settings as settings_mod
    settings_mod.keyring = None
    from mastermail.server import AppServer
    from mastermail.service import Service

    sellers = {"1001": ("ali@shop.ir", "فروشگاه علی"), "1002": (None, f"کتاب{ZWNJ}سرای سارا"),
               "1003": ("reza@shop.ir", "لوازم خانگی رضا")}
    panel = Panel(sellers)
    smtp = FakeSMTP(username="m.ahmadi", password="pw")
    svc = Service(driver_factory=stub_factory)
    svc.settings.update({
        "smtp": {"host": "127.0.0.1", "port": smtp.port, "security": "none", "username": "m.ahmadi",
                 "use_system_username": False, "from_name": "تیم عملیات"},
        "sending": {"delay": 0, "signature": "تیم عملیات فروشندگان"},
        "crawler": {"base_url": panel.base_url, "delay": 0, "element_timeout": 1, "retries": 0},
    })
    svc.settings.set_secret("smtp_password", "pw", persist=False)

    wb = Workbook()
    ws = wb.active
    ws.append(["شناسه فروشنده", "نام فروشنده", "شهر", "مبلغ"])
    for sid, city, amount in (("۱۰۰۱", "تهران", 1000), ("۱۰۰۱", "تهران", 2000), ("1002", "شیراز", 500), ("1003", "تبریز", 700)):
        ws.append([sid, "", city, amount])
    report = base / "report.xlsx"
    wb.save(report)
    up = svc.upload(f"گزارش{ZWNJ}فروش آبان.xlsx", report.read_bytes())

    c = svc.create_campaign({"name": "کمپین آزمایشی آبان"})
    info = svc.inspect_file({"file_id": up["file_id"]})
    svc.set_source(c["id"], {"mode": "file", "file_id": up["file_id"], "columns": info["detected"], "split": True})
    for job in (svc.crawl_campaign(c["id"], {}), svc.prepare_split(c["id"], {})):
        while not svc.jobs.get(job["id"]).finished_at:
            time.sleep(0.05)
    svc.update_campaign(c["id"], {"compose": {"subject": "گزارش {month} — {seller_name}",
                                             "body": "{seller_name} گرامی، سلام\n\nشهر شما: {شهر}\n\n- مورد اول\n- مورد دوم"}})
    server = AppServer(svc, token="ui").start()
    yield {"url": f"http://127.0.0.1:{server.port}", "svc": svc, "campaign": c["id"], "report": report, "file": up}
    server.stop()
    panel.stop()
    smtp.stop()
    paths.set_data_dir(None)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium not available: {exc}")
        yield b
        b.close()


def open_page(browser, app, theme="light", width=1440):
    ctx = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=theme, locale="fa-IR")
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto(app["url"] + "/?t=ui")
    page.wait_for_selector(".nav-item")
    page.evaluate("document.fonts.ready")
    return ctx, page, errors


def audit(page, where):
    page.wait_for_timeout(350)
    problems = page.evaluate(AUDIT_JS, sorted(ALLOWED_LATIN))
    return [f"{where}: {p}" for p in dict.fromkeys(problems)]


def visit_all(page, app):
    """Yield (name) after navigating to each screen and wizard step."""
    for route in ("home", "campaigns", "crawler", "splitter", "directory", "settings"):
        page.evaluate(f"location.hash = '#/{route}'")
        page.wait_for_selector(".large-title")
        if route == "splitter":
            page.set_input_files(".drop input[type=file]", str(app["report"]))
            page.wait_for_selector("text=شروع جداسازی")
        yield route
    page.evaluate(f"location.hash = '#/campaign/{app['campaign']}'")
    page.wait_for_selector(".stepper")
    for i, name in enumerate(["منبع", "گیرندگان", "متن ایمیل", "پیوست", "بازبینی و ارسال"]):
        page.locator(".stepper .step").nth(i).click()
        page.wait_for_timeout(500)
        yield f"کمپین / {name}"
    page.locator(".stepper .step").nth(2).click()
    page.click("button:has-text('نوشتن با هوش مصنوعی')")
    page.wait_for_selector(".sheet")
    yield "پنجره هوش مصنوعی"
    page.keyboard.press("Escape")


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("width", WIDTHS)
def test_every_screen_is_rtl(browser, app, theme, width):
    ctx, page, errors = open_page(browser, app, theme, width)
    problems = []
    for where in visit_all(page, app):
        problems += audit(page, where)
    ctx.close()
    assert not errors, errors
    assert not problems, "\n".join(problems)


def test_persian_input_round_trips(browser, app):
    ctx, page, errors = open_page(browser, app)
    svc = app["svc"]
    # campaign name with ZWNJ and Persian digits
    page.click("text=کمپین‌ها")
    page.click(".row >> button:has-text('کمپین جدید')")
    page.wait_for_selector(".stepper")
    name = f"کمپین{ZWNJ}های آذر ۱۴۰۵"
    page.fill("input.large-title", name)
    # ids with Persian / Arabic digits and Persian separators
    page.fill("textarea", "۱۰۰۱، ۱۰۰۳؛ ١٠٠١\n1002")
    pills = page.locator(".card .pill").all_inner_texts()
    assert "۳ شناسه معتبر" in pills and "۱ تکراری حذف می‌شود" in pills
    page.click("button:has-text('ساخت فهرست گیرندگان')")
    page.wait_for_selector("table.t tbody tr")
    page.wait_for_timeout(300)
    cid = page.evaluate("location.hash.split('/')[2]")
    assert svc.get_campaign(cid)["name"] == name
    assert [r["seller_id"] for r in svc.get_campaign(cid)["recipients"]] == ["1001", "1003", "1002"]

    # edit a seller name in Persian, then reload the page
    cell = page.locator("tbody tr").nth(2).locator("input.edit-inline").first
    cell.fill(f"کتاب{ZWNJ}سرای سارا (شعبه ۲)")
    cell.press("Tab")
    page.wait_for_timeout(400)
    page.reload()
    page.wait_for_selector("tbody tr")
    assert page.locator("tbody tr").nth(2).locator("input.edit-inline").first.input_value() == f"کتاب{ZWNJ}سرای سارا (شعبه ۲)"
    assert svc.db.get_seller("1002")["name"] == f"کتاب{ZWNJ}سرای سارا (شعبه ۲)"

    # compose in Persian and check the live preview is right-to-left
    page.locator(".stepper .step").nth(2).click()
    page.fill("input.subject", "سلام {seller_name}")
    page.fill(".editor textarea", "{seller_name} عزیز،\n\nاین یک **پیام آزمایشی** است.")
    page.wait_for_timeout(1200)
    frame = page.frame_locator(".mail-preview iframe")
    div = frame.locator("div[dir=rtl]")
    assert div.evaluate("e => getComputedStyle(e).direction") == "rtl"
    assert div.evaluate("e => getComputedStyle(e).textAlign") == "right"
    assert "فروشگاه علی عزیز،" in div.inner_text()
    assert frame.locator("strong").inner_text() == "پیام آزمایشی"
    assert page.locator(".mail-meta .subj").inner_text() == "سلام فروشگاه علی"
    ctx.close()
    assert not errors, errors


def test_persian_file_names_in_ui(browser, app):
    ctx, page, errors = open_page(browser, app)
    page.evaluate("location.hash = '#/splitter'")
    page.wait_for_selector(".drop")
    page.set_input_files(".drop input[type=file]", files=[{
        "name": f"گزارش{ZWNJ}فروش آبان.xlsx",
        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "buffer": Path(app["report"]).read_bytes()}])
    page.wait_for_selector(".file-card b")
    assert page.locator(".file-card b").inner_text() == f"گزارش{ZWNJ}فروش آبان.xlsx"
    page.select_option("select", label="شهر (۳ گروه)")
    page.click("button:has-text('شروع جداسازی')")
    page.wait_for_selector("text=باز کردن پوشه خروجی")
    job = next(j for j in app["svc"].jobs.list() if j["kind"] == "split" and j["result"] and j["result"].get("files"))
    names = sorted(Path(p).name for p in job["result"]["files"].values())
    assert names == ["تبریز.xlsx", "تهران.xlsx", "شیراز.xlsx"]
    assert "فروش آبان" in Path(job["result"]["output_dir"]).name
    ctx.close()
    assert not errors, errors


def test_audit_catches_rtl_mistakes(browser, app):
    """Guard against a checker that always passes: inject known mistakes and expect each to be reported."""
    ctx, page, _ = open_page(browser, app)
    assert audit(page, "clean") == []
    page.evaluate("""() => {
      const page = document.querySelector('.page');
      page.insertAdjacentHTML('beforeend',
        '<button class="btn">Save changes</button>' +
        '<div style="width:4000px;height:4px"></div>' +
        '<div class="stat"><div class="v">42</div></div>' +
        '<b>support@shop.ir</b>' +
        '<input class="input" value="seller@shop.ir">');
      document.querySelector('svg[data-icon="chevron"]')?.style.setProperty('transform', 'none');
    }""")
    found = "\n".join(audit(page, "broken"))
    for expected in ("English text in RTL context", "overflows horizontally", "Latin digits in counter",
                     "email shown in RTL context", "email field is not LTR", "forward arrow points right"):
        assert expected in found, f"checker missed: {expected}\n{found}"
    page.evaluate("document.documentElement.dir = 'ltr'")
    found = "\n".join(audit(page, "ltr"))
    assert "html dir is ltr" in found and "sidebar is not on the right" in found
    ctx.close()
