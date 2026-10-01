from __future__ import annotations

import re


PHONE_RE = re.compile(r"(1[3-9]\d)[\d*]{4}(\d{4})")


def mask_name(name: str | None) -> str:
    if not name:
        return ""
    if name in {"保密", "匿名", "网络匿名"}:
        return name
    if len(name) <= 1:
        return "*"
    return f"{name[0]}{'*' * max(1, len(name) - 1)}"


def mask_phone(phone: str | None) -> str:
    if not phone:
        return ""
    if phone in {"保密", "网络匿名"}:
        return phone
    return PHONE_RE.sub(r"\1****\2", phone)


def mask_text(text: str | None) -> str:
    if not text:
        return ""
    masked = PHONE_RE.sub(r"\1****\2", text)
    masked = re.sub(r"电话[：: ]?1[3-9]\d{9}", "电话：1**********", masked)
    return masked


def sanitize_for_llm(payload: dict) -> dict:
    clean = dict(payload)
    clean["caller_name"] = mask_name(clean.get("caller_name"))
    clean["caller_phone"] = mask_phone(clean.get("caller_phone"))
    clean["content"] = mask_text(clean.get("content"))
    clean["handling_result"] = mask_text(clean.get("handling_result"))
    clean["reply_content"] = mask_text(clean.get("reply_content"))
    return clean
