# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.constants import EXPORT_TRIGGERS, UI_TYPE_ALIASES, UI_TYPES
from app.kb.normalize import cell_str

HAS_HAN = re.compile(r"[\u4e00-\u9fff]")
BATCH_UI = re.compile(r"^UI类型\s*[：:]\s*(.+)$")
LINE_UI = re.compile(r"^【([^】]+)】\s*(.*)$")
INTENTS = {
    "confirm": ("确认入库",),
    "reject": ("本次不入库", "不入库"),
    "overwrite": ("确认覆盖", "覆盖入库"),
    "edit": ("修改后入库",),
}


@dataclass
class ParsedLine:
    zh: str
    ui_type: str = ""


@dataclass
class ParsedMessage:
    intent: str  # translate | confirm | reject | overwrite | edit | empty
    lines: list[ParsedLine] = field(default_factory=list)
    want_excel: bool = False
    batch_ui: str = ""
    raw: str = ""
    edited_rows: list[dict] = field(default_factory=list)


def _canon_ui(text: str) -> str:
    t = cell_str(text)
    if t in UI_TYPES:
        return t
    if t in UI_TYPE_ALIASES:
        return UI_TYPE_ALIASES[t]
    for u in UI_TYPES:
        if t.lower() == u.lower():
            return u
    return ""


def _is_export_token(line: str) -> bool:
    s = cell_str(line).lower().replace(" ", "")
    for t in EXPORT_TRIGGERS:
        if s == t.lower().replace(" ", ""):
            return True
    return False


def _strip_export(text: str) -> tuple[str, bool]:
    want = False
    remaining = text
    for t in EXPORT_TRIGGERS:
        if t.lower() in remaining.lower() or t in remaining:
            want = True
            remaining = re.sub(re.escape(t), " ", remaining, flags=re.I)
    remaining = re.sub(r"[ \t]{2,}", " ", remaining)
    return remaining, want


def _parse_md_table(text: str) -> list[dict]:
    rows: list[dict] = []
    lines = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
    data_lines = []
    for ln in lines:
        if re.match(r"^\|\s*-+", ln.strip()):
            continue
        data_lines.append(ln)
    if len(data_lines) < 2:
        return rows
    header = [cell_str(c) for c in data_lines[0].strip("|").split("|")]
    keys = []
    mapping = {
        "中文": "zh",
        "英文": "en",
        "英语": "en",
        "法语": "fr",
        "德语": "de",
        "意大利语": "it",
        "波兰语": "pl",
        "西班牙语": "es",
        "葡萄牙语": "pt",
    }
    for h in header:
        keys.append(mapping.get(h, ""))
    for ln in data_lines[1:]:
        cols = [cell_str(c) for c in ln.strip("|").split("|")]
        item = {}
        for k, v in zip(keys, cols):
            if k:
                item[k] = v.replace("\\|", "|")
        if item.get("zh"):
            rows.append(item)
    return rows


def parse_message(text: str) -> ParsedMessage:
    raw = text or ""
    cleaned, want_excel = _strip_export(raw)
    stripped = cell_str(cleaned)

    for intent, phrases in INTENTS.items():
        for p in phrases:
            if p in stripped and not HAS_HAN.search(stripped.replace(p, "")):
                edited = _parse_md_table(raw) if intent == "edit" else []
                return ParsedMessage(intent=intent, want_excel=want_excel, raw=raw, edited_rows=edited)
            if stripped.startswith(p) or stripped == p:
                edited = _parse_md_table(raw) if intent == "edit" else []
                extra = stripped[len(p) :].strip()
                if intent == "edit" or (not extra or not HAS_HAN.search(extra)):
                    return ParsedMessage(
                        intent=intent, want_excel=want_excel, raw=raw, edited_rows=edited
                    )

    if "修改后入库" in stripped:
        return ParsedMessage(
            intent="edit",
            want_excel=want_excel,
            raw=raw,
            edited_rows=_parse_md_table(raw),
        )

    lines: list[ParsedLine] = []
    batch_ui = ""
    for ln in cleaned.splitlines():
        s = cell_str(ln)
        if not s:
            continue
        if _is_export_token(s):
            continue
        m = BATCH_UI.match(s)
        if m:
            batch_ui = _canon_ui(m.group(1))
            continue
        m = LINE_UI.match(s)
        if m:
            ui = _canon_ui(m.group(1))
            zh = cell_str(m.group(2))
            if zh and HAS_HAN.search(zh):
                lines.append(ParsedLine(zh=zh, ui_type=ui or batch_ui))
            continue
        if re.match(r"^\d+[\.、\)]\s*", s):
            s = re.sub(r"^\d+[\.、\)]\s*", "", s)
        if HAS_HAN.search(s):
            lines.append(ParsedLine(zh=s, ui_type=batch_ui))

    if not lines:
        return ParsedMessage(intent="empty", want_excel=want_excel, raw=raw, batch_ui=batch_ui)
    return ParsedMessage(
        intent="translate",
        lines=lines,
        want_excel=want_excel,
        batch_ui=batch_ui,
        raw=raw,
    )
