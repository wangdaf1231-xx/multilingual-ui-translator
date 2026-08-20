# -*- coding: utf-8 -*-
from __future__ import annotations

from app.constants import LANG_LABEL, LANGS, SOURCE_LABEL, TABLE_HEADERS
from app.kb.normalize import cell_str


def _cell(s: str) -> str:
    return cell_str(s).replace("|", "｜").replace("\n", " ")


def markdown_table(items: list[dict]) -> str:
    head = "| " + " | ".join(TABLE_HEADERS) + " |"
    sep = "|" + "|".join("---" for _ in TABLE_HEADERS) + "|"
    lines = [head, sep]
    for it in items:
        cols = [_cell(it.get("zh", ""))]
        cols.extend(_cell(it.get(k, "")) for k in LANGS)
        lines.append("| " + " | ".join(cols) + " |")
    return "\n".join(lines)


def check_report(checks: list[dict]) -> str:
    lines = ["翻译库检查"]
    for i, c in enumerate(checks, 1):
        zh = c.get("zh", "")
        src = c.get("hit_source")
        label = SOURCE_LABEL.get(src, src)
        missing = c.get("missing") or []
        fills = c.get("fills") or {}
        err = c.get("error")
        if err:
            lines.append(f"{i}. 【{zh}】{err}")
            continue
        if src in ("glossary", "tm") and not missing:
            lines.append(f"{i}. 【{zh}】命中{label}，七国齐全，已原样复用。")
        elif src in ("glossary", "tm") and missing:
            miss_l = "、".join(LANG_LABEL[k] for k in missing)
            fill_l = "；".join(f"{LANG_LABEL[k]}：{fills.get(k, '')}" for k in missing)
            lines.append(f"{i}. 【{zh}】命中{label}，缺少：{miss_l}。补译：{fill_l}")
        elif src == "fail":
            lines.append(f"{i}. 【{zh}】DeepSeek 调用失败，未生成新译，不入库。")
        else:
            lines.append(f"{i}. 【{zh}】未命中术语库 / 翻译记忆，七国按新译。")
    return "\n".join(lines)


def pending_block(pending: list[dict]) -> str:
    if not pending:
        return ""
    names = "、".join(f"「{p['zh']}」" for p in pending)
    return (
        f"\n\n待入库（未写入正式库）：{names}\n"
        "请点确认入库后才会进入术语库/翻译记忆。也可回复「本次不入库」或贴修改后的表格并写「修改后入库」。"
    )


def overwrite_block(items: list[dict]) -> str:
    if not items:
        return ""
    names = "、".join(f"「{p['zh']}」" for p in items)
    return f"\n\n库中已有：{names}。默认不覆盖。若要用本轮译文替换，请点「确认覆盖」。"
