# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import unicodedata

EMPTY_TRANS = {"", "None", "null", "/", "-", "—", "无"}

_DOLLAR_AFTER_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*\$")
_DOLLAR_SPACED = re.compile(r"\$\s+(\d)")


def cell_str(v) -> str:
    if v is None:
        return ""
    s = str(v).replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    return s.strip()


def is_empty_trans(s: str) -> bool:
    return cell_str(s) in EMPTY_TRANS


def zh_norm(s: str) -> str:
    """等值查询键：去首尾空白；金额 $ 在数字前/后视为同一条。"""
    t = cell_str(s)
    if not t:
        return ""
    t = unicodedata.normalize("NFKC", t)
    t = t.replace("＄", "$").replace("￥", "$")
    t = re.sub(r"[ \t]+", "", t)
    t = _DOLLAR_AFTER_NUM.sub(r"$\1", t)
    t = _DOLLAR_SPACED.sub(r"$\1", t)
    return t
