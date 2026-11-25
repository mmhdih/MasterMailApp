"""Optional AI email writer backed by Claude (needs an Anthropic API key)."""
from __future__ import annotations

import json

SYSTEM_PROMPT = (
    "You write business emails in fluent, natural Persian for a marketplace operations team that "
    "emails sellers in bulk. Each email is personalised by placeholders that the app replaces per "
    "recipient. Use only these placeholders, written exactly with single braces: {placeholders}. "
    "Always address the seller by {{seller_name}}. Keep the email concise (under 180 words), polite, "
    "and concrete; use short paragraphs separated by a blank line and '-' bullets where a list helps. "
    "Do not invent facts, amounts, dates or links that the user did not give; where a detail is "
    "needed but unknown, leave a clear bracketed slot like [تاریخ]. Do not add a signature line; "
    "the app appends one."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "description": "Email subject line in Persian, may use placeholders"},
        "body": {"type": "string", "description": "Plain-text email body in Persian"},
    },
    "required": ["subject", "body"],
    "additionalProperties": False,
}

TONE_LABELS = {"formal": "رسمی و محترمانه", "friendly": "صمیمی و گرم", "short": "کوتاه و مستقیم"}


class AIError(Exception):
    pass


def draft_email(api_key: str, *, model: str, brief: str, tone: str = "formal",
                has_attachment: bool = False, placeholders: list[str] | None = None,
                current_body: str = "") -> dict:
    try:
        import anthropic  # type: ignore
    except ImportError as exc:
        raise AIError("کتابخانه anthropic نصب نیست.") from exc
    if not api_key:
        raise AIError("کلید API هوش مصنوعی در تنظیمات وارد نشده است.")

    names = placeholders or ["seller_name", "seller_id", "email", "date", "month"]
    system = SYSTEM_PROMPT.replace("{placeholders}", ", ".join("{" + p + "}" for p in names))
    request = [
        f"هدف ایمیل: {brief.strip()}",
        f"لحن: {TONE_LABELS.get(tone, tone)}",
        "ایمیل فایل پیوست اختصاصی برای هر فروشنده دارد و باید به آن اشاره کند." if has_attachment
        else "ایمیل پیوست ندارد.",
    ]
    if current_body.strip():
        request.append("پیش‌نویس فعلی (آن را بهبود بده و ساختارش را حفظ کن):\n" + current_body.strip())

    client = anthropic.Anthropic(api_key=api_key, timeout=90, max_retries=2)
    try:
        response = client.beta.messages.create(
            model=model or "claude-opus-5-5",
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": "\n\n".join(request)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as exc:
        raise AIError("کلید API نامعتبر است.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise AIError("این کلید API به مدل انتخاب‌شده دسترسی ندارد.") from exc
    except anthropic.RateLimitError as exc:
        raise AIError("تعداد درخواست‌ها زیاد است؛ کمی بعد دوباره تلاش کنید.") from exc
    except anthropic.BadRequestError as exc:
        raise AIError(f"درخواست نامعتبر: {exc.message}") from exc
    except anthropic.APIStatusError as exc:
        raise AIError(f"خطای سرویس هوش مصنوعی ({exc.status_code}).") from exc
    except anthropic.APIConnectionError as exc:
        raise AIError("اتصال به سرویس هوش مصنوعی برقرار نشد؛ اینترنت یا VPN را بررسی کنید.") from exc

    if response.stop_reason == "refusal":
        raise AIError("سرویس هوش مصنوعی این درخواست را نپذیرفت؛ هدف ایمیل را واضح‌تر بنویسید.")
    if response.stop_reason == "max_tokens":
        raise AIError("پاسخ هوش مصنوعی ناقص ماند؛ دوباره تلاش کنید.")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AIError("پاسخ هوش مصنوعی قابل خواندن نبود.") from exc
    return {"subject": str(data.get("subject", "")).strip(), "body": str(data.get("body", "")).strip()}
