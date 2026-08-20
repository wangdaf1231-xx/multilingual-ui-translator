# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any

from app.agent.deepseek import translate_with_deepseek
from app.agent.format import check_report, markdown_table, overwrite_block, pending_block
from app.agent.parse import ParsedMessage, parse_message
from app.constants import HIT_FAIL, HIT_GLOSSARY, HIT_NEW, HIT_TM, KB_ID, LANGS, SKILL_ID
from app.kb.export_xlsx import export_batch
from app.kb.normalize import cell_str, is_empty_trans
from app.kb.store import SessionState, Store
from app.skills_io import get_skill, list_skills

SENTENCE_PUNCT = re.compile(r"[。！？\n]")
GLOSSARY_BAD = re.compile(r"[，、：:（）()【】\[\]{}%*]|\{n\}|\$n")


def should_write_glossary(zh: str, langs: dict[str, str]) -> bool:
    compact = re.sub(r"\s+", "", zh)
    if SENTENCE_PUNCT.search(zh) or GLOSSARY_BAD.search(zh):
        return False
    if re.search(r"\d", compact):
        return False
    n = sum(1 for k in LANGS if not is_empty_trans(langs.get(k, "")))
    if n < 7:
        return False
    if len(compact) == 1:
        return True
    return 2 <= len(compact) <= 4


def _row(zh: str, langs: dict[str, str], ui_type: str = "") -> dict[str, str]:
    item = {"zh": zh, "ui_type": ui_type}
    for k in LANGS:
        item[k] = langs.get(k, "")
    return item


class AgentLoop:
    def __init__(self, store: Store) -> None:
        self.store = store

    def handle(
        self,
        session_id: str,
        message: str,
        *,
        skill_id: str = SKILL_ID,
        kb_id: str = "",
        action: str = "",
    ) -> dict[str, Any]:
        parsed = parse_message(message)
        if action in {"confirm", "reject", "overwrite", "edit"}:
            parsed.intent = action
        skill = get_skill(skill_id) or {}
        kb_id = kb_id or (skill.get("kb_ids") or [KB_ID])[0]
        state = self.store.get_session(session_id)

        if parsed.intent == "confirm":
            return self._confirm(session_id, state, overwrite=False, kb_id=kb_id)
        if parsed.intent == "overwrite":
            return self._confirm(session_id, state, overwrite=True, kb_id=kb_id)
        if parsed.intent == "reject":
            return self._reject(session_id, state)
        if parsed.intent == "edit":
            return self._edit_confirm(session_id, state, parsed, kb_id)

        if parsed.intent == "empty":
            if parsed.want_excel and state.last_result.get("items"):
                return self._export_state(state, "已根据上一轮结果导出 Excel。")
            if parsed.want_excel:
                return {
                    "reply_markdown": "请在同一条消息里附上中文文案和导出要求。",
                    "pending": False,
                    "needs_overwrite": False,
                    "excel_url": None,
                }
            return {
                "reply_markdown": "请发送需要翻译的中文文案。",
                "pending": False,
                "needs_overwrite": False,
                "excel_url": None,
            }

        return self._translate(session_id, state, parsed, skill_id, kb_id)

    def _translate(
        self,
        session_id: str,
        state: SessionState,
        parsed: ParsedMessage,
        skill_id: str,
        kb_id: str,
    ) -> dict[str, Any]:
        items: list[dict] = []
        checks: list[dict] = []
        pending: list[dict] = []
        locked: list[dict] = []
        need_model: list[dict] = []

        for line in parsed.lines:
            hit = self.store.lookup(line.zh, kb_id=kb_id)
            if hit and hit.complete:
                row = _row(line.zh, hit.langs, line.ui_type)
                items.append(row)
                locked.append(row)
                checks.append(
                    {
                        "zh": line.zh,
                        "hit_source": hit.source,
                        "complete": True,
                        "missing": [],
                        "fills": {},
                    }
                )
                self.store.log_request(session_id, line.zh, hit.source, ui_type=line.ui_type)
                continue
            if hit and not hit.complete:
                need_model.append(
                    {
                        "zh": line.zh,
                        "ui_type": line.ui_type,
                        "need": hit.missing,
                        "base": hit.langs,
                        "hit_source": hit.source,
                    }
                )
                continue
            need_model.append(
                {
                    "zh": line.zh,
                    "ui_type": line.ui_type,
                    "need": list(LANGS),
                    "base": {k: "" for k in LANGS},
                    "hit_source": HIT_NEW,
                }
            )

        translated, err = ({}, None)
        if need_model:
            translated, err = translate_with_deepseek(need_model, locked, skill_id=skill_id)

        for job in need_model:
            zh = job["zh"]
            langs = dict(job["base"])
            src = job["hit_source"]
            model_row = translated.get(zh) or {}
            # DeepSeek 可能对 zh 做了空白规范化
            if not model_row:
                for k, v in translated.items():
                    if cell_str(k) == zh:
                        model_row = v
                        break
            failed = bool(err) or (src == HIT_NEW and not any(model_row.values()))
            fills = {}
            for k in job["need"]:
                val = cell_str(model_row.get(k, ""))
                if val:
                    langs[k] = val
                    fills[k] = val
            if failed and src == HIT_NEW:
                row = _row(zh, langs, job["ui_type"])
                items.append(row)
                checks.append(
                    {
                        "zh": zh,
                        "hit_source": HIT_FAIL,
                        "complete": False,
                        "missing": list(LANGS),
                        "fills": {},
                        "error": err or "DeepSeek 未返回译文，不入库。",
                    }
                )
                self.store.log_request(
                    session_id,
                    zh,
                    HIT_FAIL,
                    ui_type=job["ui_type"],
                    is_new=True,
                    deepseek_failed=True,
                )
                continue
            row = _row(zh, langs, job["ui_type"])
            items.append(row)
            complete = all(not is_empty_trans(langs.get(k, "")) for k in LANGS)
            checks.append(
                {
                    "zh": zh,
                    "hit_source": src,
                    "complete": complete,
                    "missing": [k for k in LANGS if is_empty_trans(langs.get(k, ""))],
                    "fills": fills,
                }
            )
            self.store.log_request(
                session_id,
                zh,
                src,
                ui_type=job["ui_type"],
                is_new=src == HIT_NEW,
                deepseek_failed=False,
            )
            pending.append(row)

        md = markdown_table(items) + "\n\n" + check_report(checks)
        if err and need_model:
            md += f"\n\n{err}"
        md += pending_block(pending)
        excel_url = None
        if parsed.want_excel:
            path = export_batch(items, checks)
            excel_url = f"/api/downloads/{path.name}"
            md += "\n\n已生成 Excel，请下载。"

        state.pending = pending
        state.overwrite = []
        state.last_result = {"items": items, "checks": checks, "kb_id": kb_id}
        self.store.save_session(session_id, state)
        return {
            "reply_markdown": md,
            "pending": bool(pending),
            "needs_overwrite": False,
            "excel_url": excel_url,
            "items": items,
            "checks": checks,
        }

    def _confirm(self, session_id: str, state: SessionState, overwrite: bool, kb_id: str = KB_ID) -> dict[str, Any]:
        pending = state.pending or state.overwrite
        if overwrite:
            pending = state.overwrite or state.pending
        if not pending:
            return {
                "reply_markdown": "当前没有待入库条目。请先发送需要翻译的中文。",
                "pending": False,
                "needs_overwrite": False,
                "excel_url": None,
            }
        written = []
        blocked = []
        for item in pending:
            zh = item["zh"]
            langs = {k: item.get(k, "") for k in LANGS}
            exists = self.store.exists(zh, kb_id=kb_id)
            if exists["tm"] and not overwrite:
                blocked.append(item)
                continue
            action = self.store.upsert(
                "tm",
                zh,
                langs,
                overwrite=overwrite,
                ui_type=item.get("ui_type", ""),
                source_version="chat",
                kb_id=kb_id,
            )
            self.store.audit(action + "_tm", zh, "tm", langs, session_id)
            if should_write_glossary(zh, langs):
                g_action = self.store.upsert(
                    "glossary",
                    zh,
                    langs,
                    overwrite=overwrite,
                    source_version="chat",
                    kb_id=kb_id,
                )
                if g_action != "ignore":
                    self.store.audit(g_action + "_glossary", zh, "glossary", langs, session_id)
            written.append(zh)
        self.store.mark_confirmed(session_id, written)
        if blocked and not overwrite:
            state.overwrite = blocked
            state.pending = []
            self.store.save_session(session_id, state)
            names = "、".join(written) if written else "无"
            return {
                "reply_markdown": (
                    f"已写入翻译记忆：{names}。\n"
                    + overwrite_block(blocked)
                ),
                "pending": False,
                "needs_overwrite": True,
                "excel_url": None,
            }
        state.pending = []
        state.overwrite = []
        self.store.save_session(session_id, state)
        if not written:
            return {
                "reply_markdown": "没有新行被写入（可能库中已有且未选择覆盖）。",
                "pending": False,
                "needs_overwrite": False,
                "excel_url": None,
            }
        return {
            "reply_markdown": "已写入知识库：" + "、".join(f"「{z}」" for z in written) + "。下次精确命中将直接复用。",
            "pending": False,
            "needs_overwrite": False,
            "excel_url": None,
        }

    def _reject(self, session_id: str, state: SessionState) -> dict[str, Any]:
        n = len(state.pending) + len(state.overwrite)
        for item in state.pending:
            self.store.audit("reject", item["zh"], "pending", item, session_id)
        state.pending = []
        state.overwrite = []
        self.store.save_session(session_id, state)
        return {
            "reply_markdown": f"已放弃本轮 {n} 条待入库，正式库未改动。译文仍可复制到在线翻译文档。",
            "pending": False,
            "needs_overwrite": False,
            "excel_url": None,
        }

    def _edit_confirm(self, session_id: str, state: SessionState, parsed: ParsedMessage, kb_id: str = KB_ID) -> dict[str, Any]:
        if not parsed.edited_rows:
            return {
                "reply_markdown": "请在同一条消息里贴上修改后的七国 Markdown 表格，并写「修改后入库」。",
                "pending": bool(state.pending),
                "needs_overwrite": bool(state.overwrite),
                "excel_url": None,
            }
        by_zh = {cell_str(p["zh"]): p for p in (state.pending or [])}
        new_pending = []
        for row in parsed.edited_rows:
            zh = cell_str(row.get("zh"))
            base = by_zh.get(zh, {"zh": zh, "ui_type": ""})
            merged = dict(base)
            merged["zh"] = zh
            for k in LANGS:
                if row.get(k):
                    merged[k] = row[k]
            new_pending.append(merged)
        state.pending = new_pending
        self.store.save_session(session_id, state)
        return self._confirm(session_id, state, overwrite=False, kb_id=kb_id)

    def _export_state(self, state: SessionState, prefix: str) -> dict[str, Any]:
        items = state.last_result.get("items") or []
        checks = state.last_result.get("checks") or []
        path = export_batch(items, checks)
        return {
            "reply_markdown": prefix,
            "pending": bool(state.pending),
            "needs_overwrite": bool(state.overwrite),
            "excel_url": f"/api/downloads/{path.name}",
        }


def skill_catalog() -> list[dict]:
    return list_skills()
