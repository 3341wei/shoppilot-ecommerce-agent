# -*- coding: utf-8 -*-
"""安全工具：常量时间比较与 PII 脱敏。"""
from __future__ import annotations

import hmac
import re

_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)")


def constant_time_equals(left: str, right: str) -> bool:
    """避免按字符短路比较泄露密钥长度/前缀。"""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def mask_phone(phone: str) -> str:
    """13800138000 -> 138****8000。"""
    if not phone:
        return ""
    return _PHONE_RE.sub(r"\1****\3", phone)


def mask_address(address: str) -> str:
    """只保留前 6 个字符与后 4 个字符。"""
    if not address:
        return ""
    if len(address) <= 12:
        return address[:2] + "****"
    return f"{address[:6]}****{address[-4:]}"


def mask_name(name: str) -> str:
    if not name:
        return ""
    return name[0] + "*" * max(1, len(name) - 1)
