"""Ready-made Persian email templates and an offline "smart writer"."""
from __future__ import annotations

TEMPLATES = [
    {
        "id": "monthly_report",
        "title": "ارسال گزارش ماهانه",
        "icon": "chart",
        "subject": "گزارش {month} فروشگاه {seller_name}",
        "body": (
            "فروشنده گرامی، {seller_name}\n\n"
            "با سلام و احترام،\n"
            "گزارش عملکرد فروشگاه شما (شناسه {seller_id}) در {month} آماده شده و به پیوست همین ایمیل ارسال می‌شود.\n\n"
            "لطفاً فایل پیوست را بررسی کنید و در صورت وجود هرگونه مغایرت، حداکثر تا یک هفته از طریق پاسخ به همین ایمیل با ما در میان بگذارید.\n\n"
            "با سپاس از همراهی شما"
        ),
        "needs_attachment": True,
    },
    {
        "id": "announcement",
        "title": "اطلاع‌رسانی عمومی",
        "icon": "megaphone",
        "subject": "اطلاعیه مهم برای فروشندگان",
        "body": (
            "{seller_name} عزیز، سلام\n\n"
            "به اطلاع می‌رساند [متن اطلاعیه را اینجا بنویسید].\n\n"
            "این تغییر از تاریخ [تاریخ] اعمال خواهد شد و نیازی به اقدام خاصی از سوی شما نیست.\n\n"
            "در صورت داشتن هرگونه سؤال، از طریق پاسخ به همین ایمیل در خدمت شما هستیم.\n\n"
            "با احترام"
        ),
        "needs_attachment": False,
    },
    {
        "id": "documents",
        "title": "درخواست تکمیل مدارک",
        "icon": "doc",
        "subject": "درخواست تکمیل مدارک — شناسه {seller_id}",
        "body": (
            "فروشنده محترم {seller_name}\n\n"
            "با سلام،\n"
            "برای ادامه همکاری، لازم است مدارک زیر تا تاریخ [مهلت] در پنل فروشندگان بارگذاری شود:\n\n"
            "- [مدرک اول]\n- [مدرک دوم]\n\n"
            "در صورت عدم تکمیل مدارک تا مهلت تعیین‌شده، ممکن است برخی دسترسی‌های پنل به‌طور موقت محدود شود.\n\n"
            "با تشکر از همکاری شما"
        ),
        "needs_attachment": False,
    },
    {
        "id": "settlement",
        "title": "صورت‌حساب و تسویه",
        "icon": "wallet",
        "subject": "صورت‌حساب تسویه {month} — {seller_name}",
        "body": (
            "{seller_name} گرامی، سلام\n\n"
            "صورت‌حساب تسویه {month} فروشگاه شما به پیوست ارسال شده است. این فایل شامل {row_count} ردیف تراکنش است.\n\n"
            "مبلغ نهایی طی روزهای کاری آینده به حساب ثبت‌شده شما واریز خواهد شد.\n\n"
            "در صورت نیاز به توضیح بیشتر، کافی است به همین ایمیل پاسخ دهید.\n\n"
            "با احترام"
        ),
        "needs_attachment": True,
    },
    {
        "id": "campaign_invite",
        "title": "دعوت به کمپین",
        "icon": "sparkles",
        "subject": "دعوت از {seller_name} برای شرکت در کمپین ویژه",
        "body": (
            "{seller_name} عزیز، سلام\n\n"
            "خوشحالیم که اعلام کنیم کمپین [نام کمپین] از تاریخ [شروع] آغاز می‌شود و فروشگاه شما برای حضور در آن انتخاب شده است.\n\n"
            "مزایای شرکت در کمپین:\n"
            "- نمایش ویژه کالاهای شما\n- افزایش بازدید و فروش\n\n"
            "برای ثبت‌نام، تا تاریخ [مهلت] از طریق پنل فروشندگان اقدام کنید.\n\n"
            "منتظر حضور شما هستیم"
        ),
        "needs_attachment": False,
    },
    {
        "id": "followup",
        "title": "پیگیری و یادآوری",
        "icon": "bell",
        "subject": "یادآوری: {seller_name}",
        "body": (
            "{seller_name} گرامی، سلام\n\n"
            "پیرو ایمیل قبلی، خواستیم یادآوری کنیم که [موضوع] هنوز در انتظار اقدام شماست.\n\n"
            "اگر کار را انجام داده‌اید، این پیام را نادیده بگیرید.\n\n"
            "با سپاس"
        ),
        "needs_attachment": False,
    },
]

TONES = {
    "formal": ("فروشنده گرامی، {seller_name}", "با سلام و احترام،", "با سپاس و احترام"),
    "friendly": ("{seller_name} عزیز، سلام", "", "با آرزوی موفقیت برای شما"),
    "short": ("{seller_name} گرامی،", "", "با احترام"),
}


def smart_compose(purpose: str, *, tone: str = "formal", has_attachment: bool = False,
                  sender_name: str = "", deadline: str = "") -> dict:
    """Offline writer: turns a one-line purpose into a structured, polite email."""
    purpose = (purpose or "").strip().rstrip(".")
    greeting, opener, closing = TONES.get(tone, TONES["formal"])
    lines = [greeting, ""]
    if opener:
        lines.append(opener)
    topic = purpose or "اطلاع‌رسانی درباره همکاری"
    lines.append(f"این ایمیل درباره «{topic}» برای فروشگاه شما (شناسه {{seller_id}}) ارسال می‌شود.")
    if has_attachment:
        lines += ["", "جزئیات کامل در فایل پیوست آمده است؛ لطفاً آن را با دقت بررسی کنید."]
    if deadline:
        lines += ["", f"لطفاً حداکثر تا {deadline} اقدامات لازم را انجام دهید."]
    lines += ["", "در صورت وجود هرگونه سؤال یا مغایرت، کافی است به همین ایمیل پاسخ دهید.", "", closing]
    if sender_name:
        lines.append(sender_name)
    subject = f"{topic} — {{seller_name}}" if purpose else "پیام برای {seller_name}"
    return {"subject": subject, "body": "\n".join(lines)}
