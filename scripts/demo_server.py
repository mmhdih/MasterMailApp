"""Run the UI against a fake seller panel and a fake SMTP server (for demos and screenshots).

    python scripts/demo_server.py --port 8765 --token demo
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token", default="demo")
    ap.add_argument("--dir", default="")
    ap.add_argument("--login", action="store_true", help="panel asks for a login first")
    args = ap.parse_args()

    base = Path(args.dir or tempfile.mkdtemp(prefix="mastermail-demo-"))
    os.environ["MASTERMAIL_DATA"] = str(base / "data")
    os.environ["MASTERMAIL_WORKSPACE"] = str(base / "MasterMail")

    import mastermail.settings as settings_mod
    settings_mod.keyring = None
    from fakes import FakeSMTP, Panel, SELLERS, stub_factory
    from mastermail.server import AppServer
    from mastermail.service import Service

    sellers = dict(SELLERS)
    names = ["دیجی‌استایل", "خانه هوشمند پارس", "کتاب‌سرای نو", "ابزار ایران", "زیبایی مهسا", "ورزشی قهرمان",
             "اسباب‌بازی رنگین‌کمان", "قهوه برشته", "موبایل سیتی", "عطر نیلوفر", "فرش دستباف تبریز", "پوشاک نوین"]
    for i, name in enumerate(names):
        sid = str(2101 + i)
        sellers[sid] = (f"seller{sid}@example.ir", name) if i % 5 != 3 else (None, name)
    panel = Panel(sellers, require_login=args.login)
    smtp = FakeSMTP(username="m.ahmadi", password="demo")

    svc = Service(driver_factory=stub_factory)
    svc.settings.update({
        "smtp": {"host": "127.0.0.1", "port": smtp.port, "security": "none", "username": "m.ahmadi",
                 "use_system_username": False, "from_email": "m.ahmadi@digikala.com", "from_name": "تیم عملیات فروشندگان"},
        "sending": {"delay": 0.35, "pause_every": 0, "signature": "تیم عملیات فروشندگان\nواحد مالی بازارگاه"},
        "crawler": {"base_url": panel.base_url, "delay": 0.25, "element_timeout": 1, "retries": 0},
    })
    svc.settings.set_secret("smtp_password", "demo", persist=False)
    for sid in ("2101", "2102", "2103", "2105"):
        email, name = sellers[sid]
        svc.db.upsert_seller(sid, email=email, name=name, source="crawl", status="ok")

    # a finished campaign for the history list
    c = svc.create_campaign({"name": "اطلاعیه تغییر زمان تسویه"})
    svc.set_source(c["id"], {"mode": "ids", "text": "2101 2102 2103 2105"})
    svc.update_campaign(c["id"], {"compose": {"subject": "اطلاعیه مهم برای {seller_name}", "body": "سلام {seller_name}\n\nزمان تسویه تغییر کرد."}})
    job = svc.start_send(c["id"], {"delay": 0})
    while not svc.jobs.get(job["id"]).finished_at:
        time.sleep(0.05)

    # sample report for the walkthrough
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["seller id", "نام فروشنده", "کد سفارش", "کالا", "مبلغ (ریال)", "تاریخ"])
    import random
    random.seed(7)
    goods = ["گوشی موبایل", "هدفون", "کتاب", "کفش ورزشی", "قهوه‌ساز", "عطر", "فرش", "تی‌شرت"]
    for sid in [str(2101 + i) for i in range(12)]:
        for _ in range(random.randint(2, 9)):
            ws.append([int(sid), sellers[sid][1], random.randint(10**7, 10**8), random.choice(goods),
                       random.randint(5, 900) * 10000, "1405/08/" + str(random.randint(1, 30)).zfill(2)])
    sample = base / "گزارش فروش آبان.xlsx"
    wb.save(sample)

    server = AppServer(svc, port=args.port, token=args.token).start()
    print(f"URL {server.url}", flush=True)
    print(f"SAMPLE {sample}", flush=True)
    print(f"BASE {base}", flush=True)
    print(f"PANEL http://127.0.0.1:{panel.port}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
