"""Selenium crawler that fetches seller email + business name from the admin panel.

Ported from MailCrawlerDK. Works on a plain list of seller ids, reports through a
Job, waits for a manual login in the opened Chrome window, keeps the Chrome
profile so the login survives between runs, retries and restarts the browser.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .jobs import Job, JobCancelled
from .paths import chrome_profile_dir
from .textutil import clean_email

LOGIN_URL_HINTS = ("login", "signin", "sign-in", "/auth", "sso", "accounts.")

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_EMPTY = "not-found"
STATUS_ERROR = "error"


@dataclass
class CrawlConfig:
    base_url: str
    email_selector: str = 'input[name="email"]'
    name_selector: str = 'input[name="business_name_fa"]'
    delay: float = 1.0
    page_timeout: int = 30
    element_timeout: int = 10
    retries: int = 2
    headless: bool = False
    keep_profile: bool = True
    chrome_binary: str = ""
    chromedriver_path: str = ""
    login_wait: int = 300
    profile_dir: str = ""

    @staticmethod
    def from_settings(section: dict) -> "CrawlConfig":
        keys = CrawlConfig.__dataclass_fields__.keys()
        cfg = CrawlConfig(**{k: v for k, v in section.items() if k in keys})
        if not cfg.profile_dir:
            cfg.profile_dir = str(chrome_profile_dir())
        return cfg

    def selectors(self) -> list[tuple[str, str]]:
        return [(k, s) for k, s in (("email", self.email_selector), ("name", self.name_selector)) if s]


@dataclass
class CrawlResult:
    seller_id: str
    status: str
    email: str = ""
    name: str = ""
    message: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class CrawlSummary:
    total: int = 0
    ok: int = 0
    partial: int = 0
    empty: int = 0
    failed: int = 0
    results: list[dict] = field(default_factory=list)


class CrawlAborted(Exception):
    pass


def default_driver_factory(cfg: CrawlConfig):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    options = Options()
    if cfg.headless:
        options.add_argument("--headless=new")
    if cfg.keep_profile and cfg.profile_dir:
        options.add_argument(f"--user-data-dir={cfg.profile_dir}")
        options.add_argument("--profile-directory=Default")
    if cfg.chrome_binary:
        options.binary_location = cfg.chrome_binary
    for arg in ("--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--window-size=1280,900",
                "--disable-blink-features=AutomationControlled", "--lang=fa"):
        options.add_argument(arg)
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    service = Service(cfg.chromedriver_path) if cfg.chromedriver_path else Service()
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(cfg.page_timeout)
    return driver


class Crawler:
    def __init__(self, cfg: CrawlConfig, job: Job,
                 driver_factory: Callable[[CrawlConfig], Any] | None = None,
                 on_result: Callable[[CrawlResult], None] | None = None):
        self.cfg = cfg
        self.job = job
        self.driver_factory = driver_factory or default_driver_factory
        self.on_result = on_result
        self.driver = None

    # -- public ------------------------------------------------------------
    def run(self, ids: list[str]) -> CrawlSummary:
        summary = CrawlSummary(total=len(ids))
        if not ids:
            return summary
        if "{id}" not in self.cfg.base_url:
            raise CrawlAborted("آدرس صفحه فروشنده در تنظیمات باید شامل {id} باشد.")
        self.job.progress(0, len(ids), "در حال باز کردن مرورگر…")
        try:
            self._start_driver()
            if not self._ensure_logged_in(self._url(ids[0])):
                raise CrawlAborted("ورود به پنل انجام نشد.")
            for position, seller_id in enumerate(ids, start=1):
                self.job.check()
                result = self._crawl_one(seller_id)
                summary.results.append(result.to_dict())
                if result.status == STATUS_OK:
                    summary.ok += 1
                elif result.status == STATUS_PARTIAL:
                    summary.partial += 1
                elif result.status == STATUS_EMPTY:
                    summary.empty += 1
                else:
                    summary.failed += 1
                if self.on_result:
                    self.on_result(result)
                self.job.item({"kind": "crawl", **result.to_dict()})
                self.job.progress(position, len(ids), f"شناسه {seller_id}")
                if self.cfg.delay > 0 and position < len(ids):
                    self.job.sleep(self.cfg.delay)
        finally:
            self._quit()
        return summary

    # -- browser -----------------------------------------------------------
    def _url(self, seller_id: str) -> str:
        return self.cfg.base_url.replace("{id}", seller_id)

    def _start_driver(self) -> None:
        self.job.log("info", "در حال باز کردن مرورگر کروم…")
        try:
            self.driver = self.driver_factory(self.cfg)
        except Exception as exc:  # noqa: BLE001
            raise CrawlAborted(driver_error_hint(exc)) from exc
        self.job.log("ok", "مرورگر آماده است.")

    def _restart(self) -> bool:
        self.job.log("warn", "ارتباط با مرورگر قطع شد؛ راه‌اندازی دوباره…")
        self._quit()
        try:
            self._start_driver()
            return True
        except CrawlAborted as exc:
            self.job.log("error", str(exc))
            return False

    def _quit(self) -> None:
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:  # noqa: BLE001
                pass
            self.driver = None

    def _goto(self, url: str) -> bool:
        from selenium.common.exceptions import InvalidSessionIdException, TimeoutException, WebDriverException

        try:
            self.driver.get(url)
            return True
        except TimeoutException:
            return True
        except InvalidSessionIdException:
            raise
        except WebDriverException as exc:
            self.job.log("warn", f"صفحه باز نشد: {_short(exc)}")
            return False

    def _current_url(self) -> str:
        try:
            return (self.driver.current_url or "").lower()
        except Exception:  # noqa: BLE001
            return ""

    def _on_login_page(self) -> bool:
        url = self._current_url()
        return any(h in url for h in LOGIN_URL_HINTS)

    def _has_form(self) -> bool:
        from selenium.webdriver.common.by import By

        for _, selector in self.cfg.selectors():
            try:
                if self.driver.find_elements(By.CSS_SELECTOR, selector):
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _looks_logged_in(self) -> bool:
        return not self._on_login_page() and self._has_form()

    def _wait_for_form(self) -> None:
        deadline = time.monotonic() + self.cfg.element_timeout
        while time.monotonic() < deadline:
            self.job.check()
            if self._has_form() or self._on_login_page():
                return
            time.sleep(0.25)

    def _ensure_logged_in(self, url: str) -> bool:
        self._goto(url)
        self._wait_for_form()
        if self._looks_logged_in():
            self.job.log("ok", "نشست قبلی معتبر است؛ نیازی به ورود دوباره نیست.")
            return True

        self.job.log("warn", "در پنجره کروم وارد پنل شوید؛ سپس «ورود انجام شد» را بزنید.")
        confirmed = self.job.signal("confirm-login")
        confirmed.clear()
        self.job.request_action({"type": "login", "url": url})
        deadline = time.monotonic() + max(self.cfg.login_wait, 30)
        try:
            while time.monotonic() < deadline:
                if self.job.stopped:
                    raise JobCancelled()
                if confirmed.wait(timeout=2.0):
                    break
                if self._looks_logged_in():
                    self.job.log("ok", "ورود به‌صورت خودکار تشخیص داده شد.")
                    break
            else:
                self.job.log("error", "مهلت ورود تمام شد.")
                return False
        finally:
            if not self.job.stopped:
                self.job.clear_action()
        self._goto(url)
        self._wait_for_form()
        if self._looks_logged_in():
            self.job.log("ok", "ورود موفق بود" + ("؛ نشست برای دفعات بعد ذخیره شد." if self.cfg.keep_profile else "."))
        else:
            self.job.log("warn", "فرم اطلاعات فروشنده هنوز دیده نمی‌شود؛ ادامه می‌دهیم.")
        return True

    def _read(self, selector: str) -> str:
        from selenium.webdriver.common.by import By

        try:
            elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
        except Exception:  # noqa: BLE001
            return ""
        for element in elements:
            try:
                value = (element.get_attribute("value") or "").strip()
                if not value:
                    value = (element.text or "").strip() or (element.get_attribute("textContent") or "").strip()
            except Exception:  # noqa: BLE001
                continue
            if value:
                return value
        return ""

    def _crawl_one(self, seller_id: str) -> CrawlResult:
        from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

        attempts = max(1, int(self.cfg.retries) + 1)
        last = ""
        relogins = 0
        attempt = 0
        while attempt < attempts:
            attempt += 1
            self.job.check()
            try:
                if self.driver is None and not self._restart():
                    return CrawlResult(seller_id, STATUS_ERROR, message="مرورگر در دسترس نیست")
                if not self._goto(self._url(seller_id)):
                    last = "صفحه باز نشد"
                    self.job.sleep(min(2.0 * attempt, 8.0))
                    continue
                self._wait_for_form()
                if self._on_login_page() and relogins < 2:
                    relogins += 1
                    attempt -= 1
                    self.job.log("warn", "نشست منقضی شده است؛ نیاز به ورود دوباره.")
                    if not self._ensure_logged_in(self._url(seller_id)):
                        return CrawlResult(seller_id, STATUS_ERROR, message="ورود مجدد ناموفق")
                    continue
                values = {key: self._read(sel) for key, sel in self.cfg.selectors()}
                email = clean_email(values.get("email", ""))
                name = values.get("name", "")
                found = sum(1 for v in (email, name) if v)
                wanted = len(self.cfg.selectors())
                if found and found >= wanted:
                    return CrawlResult(seller_id, STATUS_OK, email, name)
                if found:
                    missing = "ایمیل" if not email else "نام"
                    return CrawlResult(seller_id, STATUS_PARTIAL, email, name, f"{missing} پیدا نشد")
                last = "اطلاعاتی در صفحه پیدا نشد"
                if attempt < attempts:
                    self.job.sleep(min(2.0 * attempt, 8.0))
                    continue
                return CrawlResult(seller_id, STATUS_EMPTY, message=last)
            except JobCancelled:
                raise
            except InvalidSessionIdException:
                if not self._restart():
                    return CrawlResult(seller_id, STATUS_ERROR, message="مرورگر بسته شد")
                last = "مرورگر دوباره راه‌اندازی شد"
            except WebDriverException as exc:
                last = _short(exc)
                low = last.lower()
                if ("invalid session" in low or "disconnected" in low or "no such window" in low) and not self._restart():
                    return CrawlResult(seller_id, STATUS_ERROR, message=last)
                self.job.sleep(min(2.0 * attempt, 8.0))
        return CrawlResult(seller_id, STATUS_ERROR, message=last or "خطای نامشخص")


def _short(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return text[0][:200] if text else type(exc).__name__


def driver_error_hint(exc: Exception) -> str:
    message = str(exc).lower()
    if "cannot find chrome binary" in message or "no chrome binary" in message:
        return "مرورگر Google Chrome پیدا نشد. کروم را نصب کنید یا مسیر آن را در تنظیمات کراولر وارد کنید."
    if "user data directory is already in use" in message:
        return "پروفایل کروم برنامه در پنجره دیگری باز است. پنجره‌های کروم قبلی برنامه را ببندید و دوباره تلاش کنید."
    if "only supports chrome version" in message or "session not created" in message:
        return "نسخه chromedriver با کروم هماهنگ نیست. مسیر chromedriver را در تنظیمات خالی بگذارید تا خودکار دریافت شود."
    if "unable to obtain driver" in message or "selenium manager" in message:
        return "دریافت خودکار chromedriver ناموفق بود (اینترنت را بررسی کنید) یا مسیر آن را در تنظیمات وارد کنید."
    return f"اجرای مرورگر ناموفق بود: {_short(exc)}"
